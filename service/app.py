import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
import wave
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import sherpa_onnx
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from remote_worker import RemoteUnavailable, RemoteWorker, TaskCancelled
import llm_refine

DATA = Path(os.getenv("DATA_DIR", "/data"))
MODELS = Path(os.getenv("MODEL_DIR", "/models"))
MODEL = MODELS / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"
ACCESS_CODE = os.environ["ACCESS_CODE"]
ORIGIN = os.getenv("PUBLIC_ORIGIN", "https://80.238.236.1")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").lower() in ("true", "1", "yes")
ASR_THREADS = max(1, min(8, int(os.getenv("ASR_THREADS", "3"))))
REMOTE_URL = os.getenv("REMOTE_WORKER_URL", "http://192.168.1.73:18788").strip()
LLM_DEFAULT_URL = "https://llm-4qs0qwijnzh269f3.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
LLM_DEFAULT_MODEL = "kimi-k3"
LLM_ENV_URL = os.getenv("LLM_BASE_URL", "").strip()
LLM_ENV_MODEL = os.getenv("LLM_MODEL", "").strip()
LLM_ENV_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_ENV_ENABLED = os.getenv("LLM_ENABLED", "true").lower() in ("true", "1", "yes")
LOCAL_NODE_NAME = os.getenv("LOCAL_NODE_NAME", "本机 CPU")
LOCAL_ENGINE = "SenseVoice INT8 / sherpa-onnx CPU"
REMOTE_ENGINE = "SenseVoiceSmall / FunASR CUDA"
MAX_BYTES = 300 * 1024 * 1024
MAX_SECONDS = 3 * 3600
RETENTION = 7 * 86400
SESSION_TTL = 7 * 86400
DATA.mkdir(parents=True, exist_ok=True)


def session_secret():
    configured = os.getenv("SESSION_SECRET")
    if configured:
        return configured.encode()
    path = DATA / ".session-secret"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        value = path.read_text().strip()
        if len(value) < 32:
            raise RuntimeError("Persistent session secret is invalid")
        return value.encode()
    with os.fdopen(descriptor, "w") as output:
        value = secrets.token_hex(32)
        output.write(value)
    return value.encode()


SECRET = session_secret()
log = logging.getLogger("atow")
log.setLevel(logging.INFO)
log.propagate = False


class AppFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        return datetime.fromtimestamp(record.created, timezone(timedelta(hours=4))).isoformat(sep=" ", timespec="seconds")


if not log.handlers:
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(AppFormatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(stream_handler)
ready = False
engine_failed = False
stop = threading.Event()
login_attempts = defaultdict(deque)
upload_gate = asyncio.Semaphore(2)
cancel_lock = threading.RLock()
cancel_flags = {}
active_job = None
TERMINAL = ("done", "error", "cancelled")


def db():
    conn = sqlite3.connect(DATA / "jobs.sqlite3", timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def update(job_id, **fields):
    with cancel_lock:
        flag = cancel_flags.get(job_id)
        if flag and flag.is_set():
            if fields.get("status") in ("done", "error"):
                raise TaskCancelled()
            if fields.get("status") and fields["status"] not in TERMINAL:
                fields["status"] = "cancelling"
        with db() as conn:
            conn.execute("UPDATE jobs SET " + ",".join(k + "=?" for k in fields) + " WHERE id=?", [*fields.values(), job_id])


def check_cancel(job_id):
    with cancel_lock:
        if job_id in cancel_flags and cancel_flags[job_id].is_set():
            raise TaskCancelled()


def finish_cancel(job_id, clock_started=None, remote_clean=True):
    cleaned = clean_audio(job_id)
    note = "任务已终止，NAS 临时音频已清理" if cleaned else "处理已停止，NAS 临时文件等待重试清理"
    if not remote_clean:
        note += "；电脑端取消已请求，如电脑离线将在下次启动时清理残留"
    fields = {"status": "cancelled" if cleaned else "cancelling", "text": "", "worker_note": note, "finished": time.time()}
    if clock_started is not None:
        fields["elapsed"] = round(time.monotonic() - clock_started, 3)
    task_event(job_id, "终止", note)
    update(job_id, **fields)


def task_event(job_id, event, message):
    try:
        with db() as conn:
            job = conn.execute("SELECT name,started,backend_name,engine_name FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not job:
                return
            conn.execute("INSERT INTO job_events(job_id,created,event,message) VALUES (?,?,?,?)", (job_id, time.time(), event, message))
        started = datetime.fromtimestamp(job["started"], timezone(timedelta(hours=4))).isoformat(sep=" ", timespec="seconds") if job["started"] else "尚未开始"
        log.info("任务=%s | ID=%s | 开始时间=%s | 设备=%s | 引擎=%s | %s：%s", json.dumps(job["name"], ensure_ascii=False), job_id, started, job["backend_name"] or "待选择", job["engine_name"] or "待选择", event, message)
    except Exception:
        log.warning("任务日志暂时无法保存，任务ID=%s", job_id)


def remote_settings():
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='remote_worker'").fetchone()
    if row:
        config = json.loads(row[0])
        config["source"] = "网页设置"
        return config
    return {"enabled": True, "url": REMOTE_URL, "source": "默认配置"}


def remote_from_settings(config):
    if not config.get("enabled", True):
        raise RemoteUnavailable("已关闭电脑优先，按设置使用 NAS 本机转写", "disabled")
    if not config.get("url"):
        raise RemoteUnavailable("尚未配置电脑地址，请在网页的电脑加速设置中填写", "not_configured")
    try:
        return RemoteWorker(config["url"])
    except ValueError:
        raise RemoteUnavailable("电脑地址格式不正确，请检查电脑加速设置", "invalid_config")


def llm_settings():
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='llm_refine'").fetchone()
    if row:
        config = json.loads(row[0])
        return {
            "enabled": bool(config.get("enabled", True)),
            "base_url": config.get("base_url") or LLM_DEFAULT_URL,
            "model": config.get("model") or LLM_DEFAULT_MODEL,
            "api_key": config.get("api_key", ""),
            "source": "网页设置",
        }
    return {
        "enabled": LLM_ENV_ENABLED,
        "base_url": LLM_ENV_URL or LLM_DEFAULT_URL,
        "model": LLM_ENV_MODEL or LLM_DEFAULT_MODEL,
        "api_key": LLM_ENV_KEY,
        "source": "默认配置",
    }


def claim_refine(job_id):
    with db() as conn:
        claimed = conn.execute(
            "UPDATE jobs SET refine_status='running' WHERE id=? AND (refine_status IS NULL OR refine_status IN ('none','done','failed'))",
            (job_id,))
        return bool(claimed.rowcount)


def run_refine(job_id):
    started = time.time()
    try:
        config = llm_settings()
        with db() as conn:
            row = conn.execute("SELECT text FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None or not row["text"]:
            raise llm_refine.RefineError("没有可提炼的转写文字")
        result = llm_refine.refine(row["text"], config["base_url"], config["model"], config["api_key"])
        update(job_id, refine_status="done", refined_text=result["corrected"], summary=result["summary"], refine_error="", refine_at=time.time())
        task_event(job_id, "提炼", "AI 提炼完成，耗时 %.1f 秒" % (time.time() - started))
    except Exception as exc:
        reason = str(exc)[:200] or exc.__class__.__name__
        update(job_id, refine_status="failed", refine_error=reason, refine_at=time.time())
        task_event(job_id, "提炼", "AI 提炼失败：" + reason)


def maybe_refine(job_id):
    config = llm_settings()
    if not config["enabled"] or not config["api_key"]:
        return
    with db() as conn:
        row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None or row["status"] != "done":
        return
    if claim_refine(job_id):
        run_refine(job_id)


def clean_expired():
    with db() as conn:
        rows = conn.execute("SELECT id FROM jobs WHERE status IN ('done','error','cancelled')").fetchall()
        for row in rows:
            clean_audio(row["id"])
        conn.execute("DELETE FROM job_events WHERE job_id IN (SELECT id FROM jobs WHERE created < ? AND status IN ('done','error','cancelled'))", (time.time() - RETENTION,))
        conn.execute("DELETE FROM jobs WHERE created < ? AND status IN ('done','error','cancelled')", (time.time() - RETENTION,))
        pending = conn.execute("SELECT id,backend FROM jobs WHERE status='cancelling'").fetchall()
        known = {row[0] for row in conn.execute("SELECT id FROM jobs")}
    for row in pending:
        job_id = row["id"]
        if job_id != active_job:
            confirmed = True
            if row["backend"] == "remote_gpu":
                try:
                    confirmed = remote_from_settings(remote_settings()).cancel(job_id)
                except Exception:
                    confirmed = False
            finish_cancel(job_id, remote_clean=confirmed)
    for extension in ("*.upload", "*.wav"):
        for path in DATA.glob(extension):
            try:
                if path.stem not in known and time.time() - path.stat().st_mtime > 3600:
                    path.unlink(missing_ok=True)
            except OSError:
                log.warning("Orphan audio cleanup will be retried")


def clean_audio(job_id):
    removed = 0
    for suffix in (".upload", ".wav"):
        try:
            path = DATA / (job_id + suffix)
            if path.exists():
                path.unlink()
                removed += 1
        except OSError:
            log.warning("Temporary audio cleanup will be retried for %s", job_id)
    if removed:
        task_event(job_id, "清理", "NAS 临时音频已删除")
    return not any((DATA / (job_id + suffix)).exists() for suffix in (".upload", ".wav"))


def transcribe(job, recognizer, clock_started=None):
    job_id = job["id"]
    source = DATA / (job_id + ".upload")
    target = DATA / (job_id + ".wav")
    if clock_started is None:
        clock_started = time.monotonic()
        update(job_id, started=time.time())
    try:
        check_cancel(job_id)
        update(job_id, status="converting", progress=1, backend="local_cpu", backend_name=LOCAL_NODE_NAME, engine_name=LOCAL_ENGINE)
        task_event(job_id, "执行", "使用本机 CPU 转写，先转换音频格式")
        command = [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-protocol_whitelist", "file,pipe", "-i", str(source), "-vn", "-t", str(MAX_SECONDS + 1),
            "-ac", "1", "-ar", "16000", "-af", "highpass=f=80,lowpass=f=7500",
            "-c:a", "pcm_s16le", str(target),
        ]
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        conversion_started = time.monotonic()
        try:
            while process.poll() is None:
                check_cancel(job_id)
                if time.monotonic() - conversion_started > 600:
                    raise subprocess.TimeoutExpired(command, 600)
                time.sleep(0.1)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        check_cancel(job_id)
        if process.returncode:
            raise ValueError("无法读取这段音频，请使用 MP3、M4A、WAV、WebM 等常见录音格式。")
        with wave.open(str(target), "rb") as wav:
            total = wav.getnframes()
            duration = total / 16000
            if duration > MAX_SECONDS:
                raise ValueError("录音超过 3 小时，请分段后上传。")
            if duration < 0.1:
                raise ValueError("录音过短或没有音轨。")
            update(job_id, status="processing", duration=round(duration, 2), progress=3)
            config = sherpa_onnx.VadModelConfig()
            config.silero_vad.model = str(MODELS / "silero_vad.onnx")
            config.silero_vad.threshold = 0.6
            config.silero_vad.min_silence_duration = 0.5
            config.silero_vad.min_speech_duration = 0.2
            config.silero_vad.max_speech_duration = 25
            config.sample_rate = 16000
            config.num_threads = 1
            vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=60)
            window = config.silero_vad.window_size
            texts = []
            consumed = 0
            last_update = 0

            def drain():
                while not vad.empty():
                    check_cancel(job_id)
                    samples = vad.front.samples
                    stream = recognizer.create_stream()
                    stream.accept_waveform(16000, samples)
                    recognizer.decode_stream(stream)
                    check_cancel(job_id)
                    text = re.sub(r"<\|.*?\|>", "", stream.result.text).strip()
                    if text:
                        texts.append(text)
                        update(job_id, text="\n".join(texts))
                    vad.pop()

            while True:
                check_cancel(job_id)
                raw = wav.readframes(window)
                if not raw:
                    break
                samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
                consumed += len(samples)
                vad.accept_waveform(samples)
                drain()
                if time.monotonic() - last_update > 1:
                    update(job_id, progress=min(98, 3 + int(consumed / total * 95)), elapsed=round(time.monotonic() - clock_started, 3))
                    last_update = time.monotonic()
            vad.flush()
            drain()
            check_cancel(job_id)
            update(job_id, status="done", progress=100, text="\n".join(texts) or "（未检测到可识别的语音）", finished=time.time(), elapsed=round(time.monotonic() - clock_started, 3))
            task_event(job_id, "完成", "录音时长 %.1f 秒，转写总耗时 %.2f 秒" % (duration, time.monotonic() - clock_started))
    except TaskCancelled:
        finish_cancel(job_id, clock_started)
    except subprocess.TimeoutExpired:
        update(job_id, status="error", error="音频转换超时，请缩短录音后重试。", finished=time.time(), elapsed=round(time.monotonic() - clock_started, 3))
        task_event(job_id, "失败", "音频转换超时")
    except ValueError as exc:
        update(job_id, status="error", error=str(exc), finished=time.time(), elapsed=round(time.monotonic() - clock_started, 3))
        task_event(job_id, "失败", str(exc))
    except Exception:
        log.exception("Transcription failed for %s", job_id)
        update(job_id, status="error", error="转写暂时失败，请稍后重试。", finished=time.time(), elapsed=round(time.monotonic() - clock_started, 3))
        task_event(job_id, "失败", "本机转写发生错误，请检查服务日志")
    finally:
        clean_audio(job_id)


def dispatch(job, recognizer):
    clock_started = time.monotonic()
    job_id = job["id"]
    check_cancel(job_id)
    update(job_id, started=time.time(), elapsed=0, backend="local_cpu", backend_name="", engine_name="", worker_note="")
    task_event(job_id, "开始", "开始选择转写设备")
    remote = None
    try:
        remote = remote_from_settings(remote_settings())
        task_event(job_id, "检测", "检查电脑转写服务是否就绪")
        seen_phase = set()
        def progress(status, percent, name, note):
            update(job_id, status=status, progress=percent, backend="remote_gpu", backend_name=str(name)[:80], engine_name=REMOTE_ENGINE, worker_note=note, elapsed=round(time.monotonic() - clock_started, 3))
            if status not in seen_phase:
                task_event(job_id, "执行", note)
                seen_phase.add(status)
        result = remote.run(job_id, DATA / (job_id + ".upload"), progress, stop, lambda: check_cancel(job_id))
        check_cancel(job_id)
        update(job_id, status="done", progress=100, text=result["text"], duration=round(result["duration"], 2), finished=time.time(), elapsed=round(time.monotonic() - clock_started, 3), backend="remote_gpu", backend_name=str(result.get("backend_name", "电脑 GPU"))[:80], engine_name=REMOTE_ENGINE, worker_note="通过局域网由电脑 GPU 完成")
        task_event(job_id, "完成", "电脑 GPU 转写完成，录音 %.1f 秒，总耗时 %.2f 秒" % (result["duration"], time.monotonic() - clock_started))
        clean_audio(job_id)
        remote.release(job_id)
        return
    except TaskCancelled:
        confirmed = remote.cancel(job_id) if remote else True
        finish_cancel(job_id, clock_started, confirmed)
        return
    except Exception as exc:
        reason = str(exc) if isinstance(exc, RemoteUnavailable) else "电脑转写发生异常"
        try:
            check_cancel(job_id)
        except TaskCancelled:
            confirmed = remote.cancel(job_id) if remote else True
            finish_cancel(job_id, clock_started, confirmed)
            return
        if remote:
            remote.release(job_id)
        if stop.is_set():
            return  # Retain audio for recovery on the next start.
        update(job_id, status="converting", progress=1, text="", backend="local_cpu", backend_name=LOCAL_NODE_NAME, engine_name=LOCAL_ENGINE, worker_note="未使用电脑：" + reason + "；已自动切换到本机转写")
        task_event(job_id, "调度", "未使用电脑：" + reason + "；使用 " + LOCAL_NODE_NAME)
    transcribe(job, recognizer, clock_started)


def worker():
    global ready, engine_failed, active_job
    try:
        recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(MODEL / "model.int8.onnx"), tokens=str(MODEL / "tokens.txt"),
            num_threads=ASR_THREADS, use_itn=True, debug=False,
        )
        ready = True
        log.info("本机识别引擎就绪 | 引擎=%s | 设备=%s", LOCAL_ENGINE, LOCAL_NODE_NAME)
        config = remote_settings()
        try:
            remote_from_settings(config)
            log.info("电脑加速已启用 | 来源=%s | 地址=%s | 任务开始前自动检测电脑，在线即优先使用 GPU，无需密钥", config["source"], config.get("url", ""))
        except RemoteUnavailable as exc:
            log.warning("电脑加速未启用：%s；当前任务将使用本机 CPU", str(exc))
        while not stop.is_set():
            clean_expired()
            with db() as conn:
                job = conn.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
                if job:
                    claimed = conn.execute("UPDATE jobs SET status='converting' WHERE id=? AND status='queued'", (job["id"],))
                    if not claimed.rowcount:
                        job = None
            if job:
                active_job = job["id"]
                try:
                    dispatch(job, recognizer)
                except TaskCancelled:
                    finish_cancel(job["id"])
                finally:
                    with cancel_lock:
                        cancel_flags.pop(job["id"], None)
                    active_job = None
                try:
                    maybe_refine(job["id"])
                except Exception:
                    log.exception("AI 提炼调度失败，不影响转写任务 | 任务ID=%s", job["id"])
            else:
                stop.wait(1)
    except Exception:
        engine_failed = True
        ready = False
        log.exception("Speech worker failed")


@asynccontextmanager
async def lifespan(app):
    with db() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL,
            progress INTEGER DEFAULT 0, text TEXT DEFAULT '', error TEXT DEFAULT '',
            duration REAL DEFAULT 0, created REAL NOT NULL, finished REAL DEFAULT 0)""")
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
        for column in ("started", "elapsed"):
            if column not in columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN " + column + " REAL DEFAULT NULL")
        for column, default in (("backend", "local_cpu"), ("backend_name", ""), ("worker_note", ""), ("engine_name", "")):
            if column not in columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN " + column + " TEXT DEFAULT '" + default + "'")
        for column, default in (("refine_status", "none"), ("refined_text", ""), ("summary", ""), ("refine_error", "")):
            if column not in columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN " + column + " TEXT DEFAULT '" + default + "'")
        if "refine_at" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN refine_at REAL DEFAULT NULL")
        conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS job_events (id INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL,created REAL NOT NULL,event TEXT NOT NULL,message TEXT NOT NULL)")
        conn.execute("CREATE INDEX IF NOT EXISTS job_events_job_id ON job_events(job_id,id)")
        conn.execute("UPDATE jobs SET status='queued', progress=0, text='', started=NULL, elapsed=NULL WHERE status IN ('converting','processing','remote_upload','remote_processing')")
    threading.Thread(target=worker, daemon=True).start()
    yield
    stop.set()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


def authenticated(request):
    token = request.cookies.get("atow_session", "")
    try:
        expires, nonce, signature = token.split(".")
        payload = expires + "." + nonce
        expected = hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()
        return int(expires) > time.time() and hmac.compare_digest(expected, signature)
    except (ValueError, TypeError):
        return False


@app.middleware("http")
async def protect(request: Request, call_next):
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin and origin != (ORIGIN or str(request.base_url).rstrip("/")):
            return JSONResponse({"detail": "请求来源无效"}, status_code=403)
    if request.url.path.startswith("/api/") and request.url.path not in ("/api/login", "/api/health"):
        if not authenticated(request):
            return JSONResponse({"detail": "请先输入访问口令"}, status_code=401)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Permissions-Policy"] = "microphone=(), camera=()"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@app.get("/")
def index():
    return FileResponse("/app/index.html")


@app.get("/api/health")
def health():
    return {"ready": ready, "failed": engine_failed, "version": "1.5.3"}


@app.get("/api/worker-config")
def worker_config():
    config = remote_settings()
    return {"enabled": config.get("enabled", True), "url": config.get("url", ""), "source": config["source"]}


@app.post("/api/worker-config")
async def save_worker_config(request: Request):
    try:
        raw = await request.body()
        if len(raw) > 8192:
            raise ValueError()
        body = json.loads(raw)
        config = remote_settings()
        enabled = body.get("enabled", True)
        url = body.get("url", config.get("url", ""))
        if not isinstance(enabled, bool) or not isinstance(url, str) or len(url) > 512:
            raise ValueError()
        url = url.strip().rstrip("/")
        if url:
            RemoteWorker(url)
        config = {"enabled": enabled, "url": url}
        with db() as conn:
            conn.execute("INSERT INTO settings(key,value) VALUES ('remote_worker',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(config),))
        log.info("电脑加速设置已保存 | 启用=%s | 地址=%s | 对下一条开始的任务生效", enabled, url or "未配置")
        return worker_config()
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, "配置格式无效，请填写正确的电脑地址")


@app.post("/api/worker-config/test")
def test_worker_config():
    try:
        remote = remote_from_settings(remote_settings())
        health = remote.probe()
        return {"ok": True, "message": "电脑在线，将优先使用 GPU 转写（" + str(health.get("name", "电脑 GPU"))[:60] + "）"}
    except RemoteUnavailable as exc:
        return {"ok": False, "code": exc.code, "message": str(exc)}
    except Exception:
        return {"ok": False, "code": "unavailable", "message": "电脑服务暂时无法连接"}


@app.get("/api/llm-config")
def llm_config():
    config = llm_settings()
    key = config["api_key"]
    return {"enabled": config["enabled"], "base_url": config["base_url"], "model": config["model"],
            "api_key_set": bool(key), "api_key_masked": (key[:3] + "***") if key else "", "source": config["source"]}


@app.post("/api/llm-config")
async def save_llm_config(request: Request):
    try:
        raw = await request.body()
        if len(raw) > 8192:
            raise ValueError()
        body = json.loads(raw)
        current = llm_settings()
        enabled = body.get("enabled", current["enabled"])
        base_url = body.get("base_url") or current["base_url"]
        model = body.get("model") or current["model"]
        api_key = body.get("api_key", "")
        if not isinstance(enabled, bool) or not isinstance(base_url, str) or not isinstance(model, str) or not isinstance(api_key, str):
            raise ValueError()
        if len(base_url) > 512 or len(model) > 128 or len(api_key) > 512:
            raise ValueError()
        base_url = base_url.strip().rstrip("/")
        model = model.strip()
        if not api_key or api_key == current["api_key"][:3] + "***":
            api_key = current["api_key"]
        config = {"enabled": enabled, "base_url": base_url, "model": model, "api_key": api_key}
        with db() as conn:
            conn.execute("INSERT INTO settings(key,value) VALUES ('llm_refine',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(config),))
        log.info("AI 提炼设置已保存 | 启用=%s | 模型=%s | 地址=%s | Key=%s", enabled, model or "未填写", base_url or "未填写", "已设置" if api_key else "未设置")
        return llm_config()
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, "配置格式无效，请检查地址、模型和 Key")


@app.post("/api/llm-config/test")
def test_llm_config():
    config = llm_settings()
    if not config["api_key"]:
        return {"ok": False, "message": "请先填写 API Key 并保存"}
    try:
        llm_refine.refine("这是一条测试。", config["base_url"], config["model"], config["api_key"], timeout=60)
        return {"ok": True, "message": "连接成功，模型 " + config["model"] + " 已返回测试结果"}
    except llm_refine.RefineError as exc:
        return {"ok": False, "message": str(exc)}


@app.post("/api/jobs/{job_id}/refine")
def refine_job(job_id: str):
    with db() as conn:
        row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "任务不存在或已过期")
    if row["status"] != "done":
        raise HTTPException(409, "转写完成后才能提炼")
    config = llm_settings()
    if not config["enabled"] or not config["api_key"]:
        raise HTTPException(409, "请先在设置中启用 AI 提炼并填写 API Key")
    if not claim_refine(job_id):
        raise HTTPException(409, "正在提炼中，请稍候")
    threading.Thread(target=run_refine, args=(job_id,), daemon=True).start()
    return {"ok": True, "refine_status": "running"}


@app.post("/api/login")
async def login(request: Request):
    ip = request.headers.get("x-real-ip") or request.client.host
    now = time.monotonic()
    attempts = login_attempts[ip]
    while attempts and now - attempts[0] > 900:
        attempts.popleft()
    if len(attempts) >= 10:
        raise HTTPException(429, "尝试次数过多，请 15 分钟后再试。")
    try:
        body = await request.json()
        code = body.get("code", "")
        if not isinstance(code, str) or len(code) > 256:
            raise ValueError()
    except Exception:
        raise HTTPException(400, "请求格式无效")
    if not hmac.compare_digest(code.encode(), ACCESS_CODE.encode()):
        attempts.append(now)
        raise HTTPException(401, "访问口令不正确")
    attempts.clear()
    payload = str(int(time.time() + SESSION_TTL)) + "." + secrets.token_hex(16)
    token = payload + "." + hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()
    response = JSONResponse({"ok": True})
    response.set_cookie("atow_session", token, max_age=SESSION_TTL, secure=COOKIE_SECURE, httponly=True, samesite="strict")
    return response


@app.post("/api/logout")
def logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie("atow_session", secure=COOKIE_SECURE, httponly=True, samesite="strict")
    return response


@app.get("/api/jobs")
def jobs():
    with db() as conn:
        rows = conn.execute("SELECT id,name,status,progress,error,duration,created,finished,started,elapsed,backend,backend_name,worker_note,engine_name FROM jobs ORDER BY created DESC LIMIT 100").fetchall()
    return [dict(row) for row in rows]


@app.post("/api/jobs", status_code=202)
async def upload(file: UploadFile = File(...)):
    if not ready:
        raise HTTPException(503, "识别引擎正在准备，请稍后重试。")
    async with upload_gate:
        with db() as conn:
            count = conn.execute("SELECT count(*) FROM jobs WHERE status NOT IN ('done','error','cancelled')").fetchone()[0]
        if count >= 10:
            raise HTTPException(429, "等待任务较多，请稍后再上传。")
        job_id = secrets.token_hex(16)
        target = DATA / (job_id + ".upload")
        size = 0
        try:
            with target.open("wb") as out:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise HTTPException(413, "单个文件最大 300 MB。")
                    out.write(chunk)
            if not size:
                raise HTTPException(400, "文件是空的")
            name = Path((file.filename or "录音").replace("\\", "/")).name[:180]
            with db() as conn:
                conn.execute("INSERT INTO jobs(id,name,status,created) VALUES (?,?,'queued',?)", (job_id, name, time.time()))
            task_event(job_id, "接收", "录音已上传，等待开始处理")
            return {"id": job_id}
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        finally:
            await file.close()


@app.get("/api/jobs/{job_id}")
def detail(job_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "任务不存在或已过期")
    with db() as conn:
        events = conn.execute("SELECT created,event,message FROM job_events WHERE job_id=? ORDER BY id", (job_id,)).fetchall()
    result = dict(row)
    result["events"] = [dict(event) for event in events]
    return result


@app.get("/api/jobs/{job_id}/text")
def download(job_id: str, part: str = "original"):
    job = detail(job_id)
    if job["status"] != "done":
        raise HTTPException(409, "转写尚未完成")
    if part == "refined":
        if job["refine_status"] != "done" or not job["refined_text"]:
            raise HTTPException(409, "AI 优化原文尚未生成")
        return PlainTextResponse(job["refined_text"], headers={"Content-Disposition": 'attachment; filename="transcript-ai.txt"'})
    if part == "summary":
        if job["refine_status"] != "done" or not job["summary"]:
            raise HTTPException(409, "内容概要尚未生成")
        return PlainTextResponse(job["summary"], headers={"Content-Disposition": 'attachment; filename="transcript-summary.txt"'})
    return PlainTextResponse(job["text"], headers={"Content-Disposition": 'attachment; filename="transcript.txt"'})


@app.post("/api/jobs/{job_id}/cancel")
def cancel(job_id: str):
    with cancel_lock:
        with db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise HTTPException(404, "任务不存在")
            if row["status"] in TERMINAL:
                return {"ok": True, "status": row["status"]}
            queued = row["status"] == "queued"
            cancel_flags.setdefault(job_id, threading.Event()).set()
            conn.execute("UPDATE jobs SET status='cancelling',worker_note='正在终止处理并清理临时音频' WHERE id=?", (job_id,))
    task_event(job_id, "终止请求", "用户请求终止，停止处理后清理临时音频")
    if queued:
        finish_cancel(job_id)
        with cancel_lock:
            cancel_flags.pop(job_id, None)
        return {"ok": True, "status": "cancelled"}
    return {"ok": True, "status": "cancelling"}


@app.delete("/api/jobs/{job_id}")
def delete(job_id: str):
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "任务不存在")
        if row["status"] not in TERMINAL:
            raise HTTPException(409, "请等待转写完成后再删除")
        conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        conn.execute("DELETE FROM job_events WHERE job_id=?", (job_id,))
    return {"ok": True}

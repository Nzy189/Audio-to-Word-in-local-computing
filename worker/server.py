"""Single-job FunASR CUDA worker for a trusted home LAN (single user, no auth)."""
import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import platform
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import wave

parser = argparse.ArgumentParser()
parser.add_argument("--config", default=str(Path(__file__).with_name("worker.env")))
args = parser.parse_args()
for line in Path(args.config).read_text(encoding="utf-8-sig").splitlines():
    if line.strip() and not line.lstrip().startswith("#"):
        name, value = line.split("=", 1)
        os.environ[name.strip()] = value.strip()

DATA = Path(os.getenv("WORKER_DATA", str(Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ShengjianWorker")))
DATA.mkdir(parents=True, exist_ok=True)
log = logging.getLogger("shengjian-worker")
log.setLevel(logging.INFO)
handler = RotatingFileHandler(DATA / "worker.log", maxBytes=5 * 1024 * 1024, backupCount=2, encoding="utf-8")
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
log.addHandler(handler)
if sys.stderr:
    log.addHandler(logging.StreamHandler())
lock = threading.RLock()
jobs = {}
active = None
engine = None
torch = None
engine_ready = False
engine_reason = "initializing"
backend_name = "RTX 5080 GPU"
model_precision = "initializing"
hardware_name = ""
stopping = threading.Event()
MAX_BYTES = 300 * 1024 * 1024
MAX_SECONDS = 10800
# Dynamic batch duration budget; keep FP32 and the existing VAD segment sizes.
BATCH_SIZE_S = 300
ID = re.compile(r"^[a-f0-9]{32}$")


def cpu_name():
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                return winreg.QueryValueEx(key, "ProcessorNameString")[0]
        except OSError:
            pass
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as info:
            for line in info:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or ""


def total_ram_gb():
    if sys.platform == "win32":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return status.ullTotalPhys / (1024 ** 3)
        except Exception:
            pass
        return None
    try:
        with open("/proc/meminfo", encoding="utf-8", errors="replace") as info:
            for line in info:
                if line.startswith("MemTotal"):
                    return int(line.split()[1]) / 1024 / 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def describe_hardware():
    parts = ["%s · %.0f GB 显存" % (torch.cuda.get_device_name(0), torch.cuda.get_device_properties(0).total_memory / 1024 ** 3)]
    cpu = cpu_name()
    if cpu:
        parts.append(cpu)
    ram = total_ram_gb()
    if ram:
        parts.append("%.0f GB 内存" % ram)
    return " · ".join(parts)


class WorkerCancelled(Exception):
    pass


def check_cancel(job_id=None):
    with lock:
        candidate = job_id or active
        if candidate and jobs.get(candidate, {}).get("cancel_requested"):
            raise WorkerCancelled()


def audio_cleanup(job_id):
    for suffix in (".upload", ".wav"):
        try:
            (DATA / (job_id + suffix)).unlink(missing_ok=True)
        except OSError:
            log.warning("Audio cleanup will be retried for %s", job_id)


def save(job):
    path = DATA / (job["id"] + ".json")
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    try:
        os.replace(temp, path)
    except OSError as exc:
        if getattr(exc, "winerror", None) != 17:
            raise
        # Some redirected Windows profile folders reject atomic replacement.
        shutil.copyfile(temp, path)
        temp.unlink(missing_ok=True)


def discard(job_id):
    jobs.pop(job_id, None)
    (DATA / (job_id + ".json")).unlink(missing_ok=True)
    audio_cleanup(job_id)


def janitor():
    while not stopping.wait(30):
        with lock:
            for job_id, job in list(jobs.items()):
                if job_id != active:
                    audio_cleanup(job_id)
                    if time.time() - job.get("finished", job["created"]) > 3600:
                        discard(job_id)
            for pattern in ("*.upload", "*.wav", "*.json.tmp"):
                for path in DATA.glob(pattern):
                    job_id = path.name.split(".", 1)[0]
                    if ID.fullmatch(job_id) and job_id != active:
                        try:
                            if path.suffix in (".upload", ".wav") or time.time() - path.stat().st_mtime > 900:
                                path.unlink(missing_ok=True)
                        except OSError:
                            log.warning("Orphan cleanup will be retried")


def initialize():
    global torch, engine, engine_ready, engine_reason, backend_name, model_precision, hardware_name
    try:
        import torch as torch_module
        from funasr import AutoModel
        torch = torch_module
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is unavailable; NAS will use its CPU")
        torch.set_num_threads(4)
        cache = Path.home() / ".cache/modelscope/models"
        model = cache / "iic--SenseVoiceSmall/snapshots/master"
        vad = cache / "iic--speech_fsmn_vad_zh-cn-16k-common-pytorch/snapshots/master"
        engine = AutoModel(
            model=os.getenv("FUNASR_MODEL", str(model) if model.exists() else "iic/SenseVoiceSmall"),
            vad_model=os.getenv("VAD_MODEL", str(vad) if vad.exists() else "fsmn-vad"),
            vad_kwargs={"max_single_segment_time": 30000, "speech_noise_thres": 0.75}, device="cuda:0",
            disable_update=True, disable_pbar=True, disable_log=True,
        )
        if next(engine.model.parameters()).device.type != "cuda":
            raise RuntimeError("The ASR model is not on CUDA")
        model_precision = str(next(engine.model.parameters()).dtype).removeprefix("torch.")
        # Interrupt eager PyTorch inference at module boundaries, including VAD.
        hooked = set()
        for root in (engine.model, engine.vad_model):
            if root is not None:
                for module in root.modules():
                    if id(module) not in hooked:
                        module.register_forward_pre_hook(lambda module, inputs: check_cancel())
                        hooked.add(id(module))
        warm = torch.ones((256, 256), device="cuda")
        torch.mm(warm, warm)
        torch.cuda.synchronize()
        del warm
        backend_name = torch.cuda.get_device_name(0) + " GPU"
        hardware_name = describe_hardware()
        engine_ready = True
        engine_reason = "ready"
        log.info("GPU transcription service ready on %s | batch_size_s=%s | precision=%s", backend_name, BATCH_SIZE_S, model_precision)
    except Exception:
        engine_reason = "cuda_unavailable"
        log.exception("GPU initialization failed; worker stays unavailable")


def ffmpeg_path():
    configured = os.getenv("FFMPEG_PATH") or shutil.which("ffmpeg")
    if configured:
        return configured
    root = Path(os.environ["LOCALAPPDATA"]) / "Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    matches = sorted(root.glob("ffmpeg-*/bin/ffmpeg.exe"))
    if not matches:
        raise RuntimeError("FFmpeg is unavailable")
    return str(matches[-1])


def process(job_id):
    global active
    started = time.monotonic()
    outcome = {}
    try:
        with lock:
            job = jobs[job_id]
            if job.get("cancel_requested"):
                return
            job.update(status="converting", progress=5)
            save(job)
        converted = DATA / (job_id + ".wav")
        command = [
            ffmpeg_path(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-protocol_whitelist", "file,pipe", "-i", str(DATA / (job_id + ".upload")),
            "-vn", "-t", str(MAX_SECONDS + 1), "-ac", "1", "-ar", "16000",
            "-af", "highpass=f=80,lowpass=f=7500",
            "-c:a", "pcm_s16le", str(converted),
        ]
        converted_process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        conversion_started = time.monotonic()
        try:
            while converted_process.poll() is None:
                check_cancel(job_id)
                if time.monotonic() - conversion_started > 600:
                    raise subprocess.TimeoutExpired(command, 600)
                time.sleep(0.1)
        finally:
            if converted_process.poll() is None:
                converted_process.terminate()
                try:
                    converted_process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    converted_process.kill()
                    converted_process.wait()
        check_cancel(job_id)
        if converted_process.returncode:
            raise ValueError("Audio conversion failed")
        with wave.open(str(converted), "rb") as wav:
            duration = wav.getnframes() / wav.getframerate()
        if not 0.1 <= duration <= MAX_SECONDS:
            raise ValueError("Audio duration is outside the supported range")
        with lock:
            if job.get("cancel_requested"):
                return
            job.update(status="processing", progress=20)
            save(job)
        from funasr.utils.postprocess_utils import rich_transcription_postprocess
        result = engine.generate(input=str(converted), cache={}, language="auto", use_itn=True,
                                 batch_size_s=BATCH_SIZE_S, merge_vad=True, merge_length_s=15,
                                 disable_pbar=True, disable_log=True)
        check_cancel(job_id)
        text = "\n".join(rich_transcription_postprocess(item.get("text", "")).strip() for item in result).strip()
        outcome = {"status": "done", "progress": 100, "text": text or "（未检测到可识别的语音）", "duration": duration}
    except WorkerCancelled:
        log.info("GPU task %s terminated by request; removing temporary audio", job_id)
        if torch is not None:
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
        outcome = {"status": "cancelled"}
    except Exception:
        log.exception("GPU job %s failed", job_id)
        outcome = {"status": "error", "error": "GPU transcription failed"}
        if torch is not None:
            torch.cuda.empty_cache()
    finally:
        audio_cleanup(job_id)
        with lock:
            job = jobs.get(job_id)
            if job:
                if job.get("cancel_requested"):
                    discard(job_id)
                else:
                    job.update(outcome or {"status": "cancelled"}, finished=time.time(), elapsed=time.monotonic() - started)
                    save(job)
            active = None


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 8


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def log_message(self, format, *args):
        pass

    def reply(self, status, data):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def job_id(self):
        prefix = "/v1/jobs/"
        candidate = self.path[len(prefix):] if self.path.startswith(prefix) else ""
        if not ID.fullmatch(candidate):
            self.reply(404, {"error": "Not found"})
            return None
        return candidate

    def do_GET(self):
        if self.path == "/v1/health":
            available = engine_ready
            reason = engine_reason
            if available:
                try:
                    available = torch.cuda.mem_get_info()[0] >= 1536 * 1024 * 1024
                    if not available:
                        reason = "gpu_memory_low"
                except Exception:
                    available = False
                    reason = "cuda_unavailable"
            with lock:
                self.reply(200, {"ready": available, "busy": active is not None, "reason": "busy" if active is not None else reason, "name": backend_name, "protocol": 1, "batch_size_s": BATCH_SIZE_S, "precision": model_precision, "hardware": hardware_name})
            return
        job_id = self.job_id()
        if job_id:
            with lock:
                job = jobs.get(job_id)
                self.reply(200 if job else 404, dict(job) if job else {"error": "Not found"})

    def do_PUT(self):
        global active
        job_id = self.job_id()
        if not job_id:
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 0 < length <= MAX_BYTES:
            self.reply(413, {"error": "Invalid audio size"})
            return
        with lock:
            if not engine_ready or active is not None:
                self.reply(409, {"error": "GPU worker is not available"})
                return
            if job_id in jobs:
                self.reply(409, {"error": "Task already exists"})
                return
            active = job_id
            jobs[job_id] = {"id": job_id, "status": "uploading", "progress": 1, "created": time.time(), "backend_name": backend_name, "hardware": hardware_name}
        try:
            received = 0
            deadline = time.monotonic() + 330
            with (DATA / (job_id + ".upload")).open("wb") as out:
                while received < length:
                    check_cancel(job_id)
                    chunk = self.rfile.read(min(65536, length - received))
                    if not chunk or time.monotonic() > deadline:
                        raise ValueError("Incomplete audio upload")
                    out.write(chunk)
                    received += len(chunk)
            with lock:
                jobs[job_id]["status"] = "queued"
                save(jobs[job_id])
            threading.Thread(target=process, args=(job_id,), daemon=True).start()
            self.reply(202, {"id": job_id})
        except Exception:
            if jobs.get(job_id, {}).get("cancel_requested"):
                log.info("Audio upload cancelled for %s", job_id)
            else:
                log.exception("Audio upload failed for %s", job_id)
            with lock:
                discard(job_id)
                active = None
            self.reply(400, {"error": "Audio upload did not finish"})

    def do_DELETE(self):
        job_id = self.job_id()
        if not job_id:
            return
        with lock:
            if job_id == active:
                jobs[job_id]["cancel_requested"] = True
            else:
                discard(job_id)
        self.reply(200, {"ok": True})


for path in DATA.glob("*.json"):
    if not ID.fullmatch(path.stem):
        continue
    try:
        job = json.loads(path.read_text(encoding="utf-8"))
        audio_cleanup(path.stem)
        if job.get("status") not in ("done", "error", "cancelled"):
            job.update(status="error", error="Worker restarted", finished=time.time())
        if time.time() - job.get("finished", job["created"]) < 3600:
            jobs[path.stem] = job
            save(job)
        else:
            discard(path.stem)
    except Exception:
        log.warning("Invalid expired task metadata ignored")
for pattern in ("*.upload", "*.wav"):
    for path in DATA.glob(pattern):
        if ID.fullmatch(path.stem):
            audio_cleanup(path.stem)

threading.Thread(target=initialize, daemon=True).start()
threading.Thread(target=janitor, daemon=True).start()
address = os.getenv("WORKER_BIND", "0.0.0.0")
port = int(os.getenv("WORKER_PORT", "18788"))
log.info("Worker HTTP listener starting on %s:%s", address, port)
try:
    Server((address, port), Handler).serve_forever()
finally:
    stopping.set()

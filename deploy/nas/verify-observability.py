"""ARM64 integration: zero configuration, precise logs, real GPU and fallback reasons."""
import json
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
import uuid

BASE = "http://127.0.0.1:18787"
CONTAINER = "atow-logs-qa"
PC_URL = "http://192.168.1.73:18788"
access = dict(x.split("=", 1) for x in Path("dist/shengjian-1.4/nas.env").read_text().splitlines() if "=" in x)["ACCESS_CODE"]
cookie = ""
created = []


def req(path, method="GET", data=None, content_type=None, auth=True):
    headers = {"Cookie": cookie} if auth else {}
    if content_type:
        headers["Content-Type"] = content_type
    if isinstance(data, dict):
        data = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read(), response.headers
    except urllib.error.HTTPError as response:
        return response.code, response.read(), response.headers


def ready():
    for _ in range(90):
        try:
            if json.loads(req("/api/health")[1])["ready"]:
                return
        except Exception:
            pass
        time.sleep(1)
    raise AssertionError("NAS QA engine did not become ready")


def settings(url, enabled=True):
    status, raw, _ = req("/api/worker-config", "POST", {"enabled": enabled, "url": url})
    assert status == 200, (status, raw)
    return json.loads(raw)


def task(name, expected_backend, reason=None):
    boundary = uuid.uuid4().hex
    body = ("--" + boundary + '\r\nContent-Disposition: form-data; name="file"; filename="' + name + '"\r\nContent-Type: audio/wav\r\n\r\n').encode() + Path("test-results/zh.wav").read_bytes() + ("\r\n--" + boundary + "--\r\n").encode()
    status, raw, _ = req("/api/jobs", "POST", body, "multipart/form-data; boundary=" + boundary)
    assert status == 202
    job_id = json.loads(raw)["id"]
    created.append(job_id)
    for _ in range(180):
        job = json.loads(req("/api/jobs/" + job_id)[1])
        if job["status"] in ("done", "error"):
            break
        time.sleep(0.5)
    assert job["status"] == "done", job
    assert job["backend"] == expected_backend, job
    assert job["engine_name"] and job["started"] and job["elapsed"] > 0
    assert any(e["event"] == "开始" for e in job["events"])
    assert any(e["event"] == "完成" for e in job["events"])
    if reason:
        assert reason in job["worker_note"], job
        assert any(reason in e["message"] for e in job["events"]), job
    check = "from pathlib import Path; assert not Path('/data/" + job_id + ".upload').exists(); assert not Path('/data/" + job_id + ".wav').exists()"
    subprocess.run(["docker", "exec", CONTAINER, "python", "-c", check], check=True, capture_output=True)
    return job


ready()
assert req("/api/worker-config", auth=False)[0] == 401
status, _, headers = req("/api/login", "POST", {"code": access})
assert status == 200
cookie = headers["Set-Cookie"].split(";", 1)[0]
try:
    current = json.loads(req("/api/worker-config")[1])
    assert current["enabled"] and current["url"] == PC_URL and current["source"] == "默认配置"
    assert "token" not in current
    diagnostic = json.loads(req("/api/worker-config/test", "POST")[1])
    assert diagnostic["ok"] and "电脑在线" in diagnostic["message"], diagnostic
    task("日志检查-零配置直连GPU.wav", "remote_gpu")
    print("PASS zero configuration: default address reaches the real RTX 5080 with no key", flush=True)
    settings("")
    task("日志检查-未配置电脑地址.wav", "local_cpu", "尚未配置电脑地址")
    print("PASS blank address explicitly logged with task name / start time / CPU engine / reason", flush=True)
    settings("http://127.0.0.1:9")
    diagnostic = json.loads(req("/api/worker-config/test", "POST")[1])
    assert diagnostic["code"] == "connection_refused", diagnostic
    task("日志检查-电脑服务未启动.wav", "local_cpu", "拒绝连接")
    print("PASS distinct connection-refused reason in diagnostics and job log", flush=True)
    settings(PC_URL, enabled=False)
    task("日志检查-关闭电脑优先.wav", "local_cpu", "已关闭电脑优先")
    print("PASS explicit local-only setting logged", flush=True)
    settings(PC_URL)
    diagnostic = json.loads(req("/api/worker-config/test", "POST")[1])
    assert diagnostic["ok"], diagnostic
    gpu = task("日志检查-真实RTX5080.wav", "remote_gpu")
    assert "FunASR" in gpu["engine_name"] and "5080" in gpu["backend_name"]
    assert any(e["event"] == "清理" for e in gpu["events"])
    print("PASS web-saved address -> real LAN RTX 5080, correct engine and task events", flush=True)
    subprocess.run(["docker", "restart", CONTAINER], check=True, capture_output=True)
    ready()
    current = json.loads(req("/api/worker-config")[1])
    assert current["source"] == "网页设置" and current["url"] == PC_URL
    assert json.loads(req("/api/worker-config/test", "POST")[1])["ok"]
    assert json.loads(req("/api/jobs/" + gpu["id"])[1])["events"]
    print("PASS settings, session and task logs survive restart without remote environment variables", flush=True)
    output = subprocess.run(["docker", "logs", CONTAINER], capture_output=True)
    text = (output.stdout + output.stderr).decode(errors="replace")
    assert "\x1b[" not in text
    for field in ("日志检查-零配置直连GPU.wav", "开始时间=", "设备=", "引擎=", "未使用电脑", "完成"):
        assert field in text, field
    print("PASS readable container logs, no ANSI escapes, full task/engine/fallback metadata", flush=True)
finally:
    for job_id in created:
        req("/api/jobs/" + job_id, "DELETE")

"""Run only inside an isolated ECS QA container with ATOW_ECS_QA=1.

Requires a public speech sample at /qa/zh.wav. Uses a local SSE stub;
never sends audio/transcripts to an external AI service or prints transcripts.
"""
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid

if os.environ.get("ATOW_ECS_QA") != "1":
    raise SystemExit("Refusing to run without the isolated QA marker")

BASE = "http://127.0.0.1:8787"
cookie = ""


def request(path, method="GET", body=None, content_type=None, auth=True):
    headers = {"Cookie": cookie} if auth and cookie else {}
    if isinstance(body, dict):
        body = json.dumps(body).encode()
        content_type = "application/json"
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.status, response.read(), response.headers
    except urllib.error.HTTPError as response:
        return response.code, response.read(), response.headers


def data(path, method="GET", body=None):
    status, raw, _ = request(path, method, body)
    assert status == 200, (path, status)
    return json.loads(raw)


def wait_job(job_id, refine=False):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        job = data("/api/jobs/" + job_id)
        if job["status"] == "error":
            raise AssertionError("QA transcription failed")
        if refine and job["refine_status"] == "failed":
            raise AssertionError("QA refinement failed")
        if refine and job["corrected_status"] == "failed":
            raise AssertionError("QA correction failed")
        if job["status"] == "done" and (not refine or (job["refine_status"] == "done" and job["corrected_status"] == "done")):
            return job
        time.sleep(0.3)
    raise AssertionError("QA job timed out")


deadline = time.monotonic() + 120
while time.monotonic() < deadline:
    try:
        health = data("/api/health")
        if health["ready"]:
            break
    except (OSError, AssertionError):
        pass
    time.sleep(1)
else:
    raise AssertionError("QA engine did not become ready")
assert health["version"] == "1.6.1" and not health["failed"]
assert health["local_engine"] == "SenseVoice FP32 / sherpa-onnx CPU"
print("PASS ECS 1.6.1 health and native FP32 CPU engine ready", flush=True)

assert request("/api/jobs", auth=False)[0] == 401
assert request("/", auth=False)[0] == 200
status, raw, _ = request("/api/login", "POST", {"code": "definitely-wrong-code"})
assert status == 401, (status, raw)
status, _, headers = request("/api/login", "POST", {"code": os.environ["ACCESS_CODE"]})
assert status == 200
cookie = headers["Set-Cookie"].split(";", 1)[0]
assert "HttpOnly" in headers["Set-Cookie"]
print("PASS authentication and session cookie", flush=True)
entries = data("/api/audit")
events = [entry["event"] for entry in entries]
assert "访问登录页" in events and "登录失败" in events and "登录成功" in events, events
failed_entry = next(entry for entry in entries if entry["event"] == "登录失败")
assert failed_entry["code"] == "definitely-wrong-code", failed_entry
assert all(entry["ip"] for entry in entries), entries
print("PASS access audit records page visits and login attempts with tried codes", flush=True)
assert data("/api/worker-config")["url"] == ""
assert not data("/api/llm-config")["api_key_set"]
print("PASS ECS has no default home-LAN GPU target or AI key", flush=True)

config = {"enabled": True, "url": ""}
data("/api/worker-config", "POST", config)
probe = data("/api/worker-config/test", "POST")
assert not probe["ok"] and probe["code"] == "not_configured"

boundary = uuid.uuid4().hex
body = ("--" + boundary + '\r\nContent-Disposition: form-data; name="file"; filename="ecs-public-qa.wav"\r\nContent-Type: audio/wav\r\n\r\n').encode()
body += Path("/qa/zh.wav").read_bytes() + ("\r\n--" + boundary + "--\r\n").encode()
status, raw, _ = request("/api/jobs", "POST", body, "multipart/form-data; boundary=" + boundary)
assert status == 202
job_id = json.loads(raw)["id"]
job = wait_job(job_id)
assert job["backend"] == "local_cpu" and job["backend_name"] == "ECS CPU"
assert len(job["text"]) > 4 and job["refine_status"] == "none"
assert job["hardware_name"], "识别硬件应为空"
for suffix in (".upload", ".wav"):
    assert not (Path(os.environ.get("DATA_DIR", "/data")) / (job_id + suffix)).exists()
print("PASS public speech upload, ECS CPU routing, hardware detection and temporary audio cleanup", flush=True)

# The companion stub is provided on stdin in a separate docker exec process.
data("/api/llm-config", "POST", {"enabled": True, "base_url": "http://127.0.0.1:18789/v1", "model": "stub-ok", "api_key": "sk-ecs-qa"})
config = data("/api/llm-config")
assert config["api_key_set"] and "api_key" not in config
assert data("/api/llm-config/test", "POST")["ok"]
data("/api/jobs/" + job_id + "/refine", "POST")
refined = wait_job(job_id, refine=True)
assert refined["text"] == job["text"]
assert refined["summary"] == "【测试】\n- 测试要点", repr(refined["summary"])
assert refined["refined_text"] and all(line.startswith("净") for line in refined["refined_text"].split("\n")), repr(refined["refined_text"])
summary_usage = json.loads(refined["refine_usage"])
corrected_usage = json.loads(refined["corrected_usage"])
assert summary_usage["prompt_tokens"] > 0 and corrected_usage["prompt_tokens"] > 0, (refined["refine_usage"], refined["corrected_usage"])
messages = [event["message"] for event in refined["events"]]
assert any("纪要完成" in message for message in messages), messages
assert any("全文净化完成" in message for message in messages), messages
print("PASS two-phase AI refinement with per-phase token usage, key masking and original text preservation", flush=True)

for part in ("original", "refined", "summary"):
    assert request("/api/jobs/" + job_id + "/text?part=" + part)[0] == 200
data("/api/jobs/" + job_id + "/refine", "POST")
wait_job(job_id, refine=True)
print("PASS original/refined/summary downloads and regeneration", flush=True)
assert request("/api/jobs/" + job_id, "DELETE")[0] == 200
assert request("/api/jobs/" + job_id)[0] == 404
print("PASS QA record deletion; production data was never mounted", flush=True)

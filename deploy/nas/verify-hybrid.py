"""Hybrid integration checks: real LAN CUDA, then unavailable/busy/disconnected CPU fallbacks."""
import http.client
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
import uuid

BASE = os.getenv("HYBRID_TEST_URL", "http://127.0.0.1:18787")
CONTAINER = os.getenv("HYBRID_TEST_CONTAINER", "atow-hybrid-qa")
config = dict(line.split("=", 1) for line in Path("dist/shengjian-z2pro/nas.env").read_text().splitlines() if "=" in line)
cookie = ""
created = []


def request(path, method="GET", data=None, content_type=None):
    headers = {"Cookie": cookie}
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.status, response.read(), response.headers
    except urllib.error.HTTPError as response:
        return response.code, response.read(), response.headers


def await_ready():
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            if json.loads(request("/api/health")[1])["ready"]:
                return
        except Exception:
            pass
        time.sleep(1)
    raise AssertionError("QA NAS did not become ready")


def upload(label="test.wav"):
    boundary = uuid.uuid4().hex
    body = ("--" + boundary + '\r\nContent-Disposition: form-data; name="file"; filename="' + label + '"\r\nContent-Type: audio/wav\r\n\r\n').encode() + Path("test-results/zh.wav").read_bytes() + ("\r\n--" + boundary + "--\r\n").encode()
    status, body, _ = request("/api/jobs", "POST", body, "multipart/form-data; boundary=" + boundary)
    assert status == 202, (status, body)
    job_id = json.loads(body)["id"]
    created.append(job_id)
    return job_id


def wait(job_id):
    deadline = time.time() + 90
    states = set()
    while time.time() < deadline:
        status, raw, _ = request("/api/jobs/" + job_id)
        assert status == 200
        job = json.loads(raw)
        states.add(job["status"])
        if job["status"] in ("done", "error"):
            return job, states
        time.sleep(0.5)
    raise AssertionError("QA transcription did not finish")


def no_nas_audio(job_id):
    code = "from pathlib import Path; assert not Path('/data/" + job_id + ".upload').exists(); assert not Path('/data/" + job_id + ".wav').exists()"
    subprocess.run(["docker", "exec", CONTAINER, "python", "-c", code], check=True, capture_output=True)


await_ready()
status, _, headers = request("/api/login", "POST", json.dumps({"code": config["ACCESS_CODE"]}).encode(), "application/json")
assert status == 200
cookie = headers["Set-Cookie"].split(";", 1)[0]
try:
    if os.getenv("HYBRID_FAULT_TESTS"):
        for mode in ("offline", "busy", "error", "drop"):
            subprocess.run(["docker", "exec", CONTAINER, "python", "-c", "from pathlib import Path; Path('/tmp/fault-mode').write_text('" + mode + "')"], check=True, capture_output=True)
            job_id = upload(mode + ".wav")
            result, states = wait(job_id)
            assert result["status"] == "done", result
            assert result["backend"] == "local_cpu" and "NAS" in result["backend_name"], result
            assert len(result["text"]) > 4 and result["elapsed"] > 0
            assert "自动切换" in result["worker_note"]
            no_nas_audio(job_id)
            print("PASS " + mode + " GPU service -> automatic NAS CPU fallback / source retained for retry / final audio removed", flush=True)
    else:
        remote_id = upload("real-gpu.wav")
        result, states = wait(remote_id)
        assert result["status"] == "done", result
        assert result["backend"] == "remote_gpu" and "5080" in result["backend_name"], result
        assert len(result["text"]) > 4 and result["elapsed"] > 0
        no_nas_audio(remote_id)
        pc = Path(os.environ["LOCALAPPDATA"]) / "ShengjianWorker"
        assert not any((pc / (remote_id + suffix)).exists() for suffix in (".upload", ".wav", ".json"))
        print("PASS ARM64 NAS -> 192.168.1.73 LAN -> real RTX 5080 -> NAS result and immediate two-side audio cleanup", flush=True)

finally:
    for job_id in created:
        request("/api/jobs/" + job_id, "DELETE")

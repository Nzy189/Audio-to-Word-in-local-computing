"""Exercise queued, CPU and actual CUDA termination, including audio cleanup."""
import http.client
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
import uuid

BASE = "http://127.0.0.1:18787"
CONTAINER = "atow-logs-qa"
PC_URL = "http://192.168.1.73:18788"
access = Path("dist/shengjian-1.4/nas.env").read_text().strip().split("=", 1)[1]
cookie = ""
created = []


def req(path, method="GET", body=None):
    headers = {"Cookie": cookie}
    if body is not None:
        body = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    try:
        with urllib.request.urlopen(urllib.request.Request(BASE + path, data=body, method=method, headers=headers), timeout=20) as response:
            return response.status, json.load(response), response.headers
    except urllib.error.HTTPError as response:
        return response.code, response.read().decode(), response.headers


def upload(name, source):
    boundary = uuid.uuid4().hex
    head = ("--" + boundary + '\r\nContent-Disposition: form-data; name="file"; filename="' + name + '"\r\nContent-Type: audio/wav\r\n\r\n').encode()
    tail = ("\r\n--" + boundary + "--\r\n").encode()
    conn = http.client.HTTPConnection("127.0.0.1", 18787, timeout=60)
    conn.putrequest("POST", "/api/jobs")
    conn.putheader("Cookie", cookie)
    conn.putheader("Content-Type", "multipart/form-data; boundary=" + boundary)
    conn.putheader("Content-Length", str(len(head) + source.stat().st_size + len(tail)))
    conn.endheaders()
    conn.send(head)
    with source.open("rb") as audio:
        while chunk := audio.read(1024 * 1024):
            conn.send(chunk)
    conn.send(tail)
    response = conn.getresponse()
    body = json.load(response)
    assert response.status == 202, body
    conn.close()
    created.append(body["id"])
    return body["id"]


def wait(job_id, states, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, job, _ = req("/api/jobs/" + job_id)
        assert status == 200
        if job["status"] in states:
            return job
        if job["status"] in ("done", "error", "cancelled"):
            raise AssertionError(job)
        time.sleep(0.15)
    raise AssertionError("Task did not enter " + str(states))


def no_audio(job_id):
    code = "from pathlib import Path; assert not Path('/data/" + job_id + ".upload').exists(); assert not Path('/data/" + job_id + ".wav').exists()"
    subprocess.run(["docker", "exec", CONTAINER, "python", "-c", code], check=True, capture_output=True)
    root = Path(os.environ["LOCALAPPDATA"]) / "ShengjianWorker"
    assert not (root / (job_id + ".upload")).exists()
    assert not (root / (job_id + ".wav")).exists()


for _ in range(90):
    try:
        if req("/api/health")[1]["ready"]:
            break
    except Exception:
        pass
    time.sleep(1)
status, _, headers = req("/api/login", "POST", {"code": access})
assert status == 200
cookie = headers["Set-Cookie"].split(";", 1)[0]
try:
    assert req("/api/worker-config", "POST", {"enabled": False, "url": PC_URL})[0] == 200
    cpu_id = upload("终止检查-CPU一小时.wav", Path("test-results/long-cancel.wav"))
    wait(cpu_id, {"processing"})
    queued_id = upload("终止检查-排队.wav", Path("test-results/zh.wav"))
    assert req("/api/jobs/" + queued_id)[1]["status"] == "queued"
    assert req("/api/jobs/" + queued_id + "/cancel", "POST")[0] == 200
    queued = wait(queued_id, {"cancelled"}, timeout=10)
    no_audio(queued_id)
    print("PASS queued task terminates and removes its uploaded audio", flush=True)
    started = time.monotonic()
    assert req("/api/jobs/" + cpu_id + "/cancel", "POST")[0] == 200
    cpu = wait(cpu_id, {"cancelled"}, timeout=30)
    assert not cpu["text"] and any(e["event"] == "终止" for e in cpu["events"])
    no_audio(cpu_id)
    print("PASS active NAS CPU task stops and clears audio in %.1fs" % (time.monotonic() - started), flush=True)
    assert req("/api/worker-config", "POST", {"enabled": True, "url": PC_URL})[0] == 200
    gpu_id = upload("终止检查-RTX5080一小时.wav", Path("test-results/long-cancel.wav"))
    wait(gpu_id, {"remote_processing"})
    # Wait until the PC is actually in model inference rather than conversion.
    pc = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(100):
        remote = json.load(pc.open(PC_URL + "/v1/jobs/" + gpu_id, timeout=3))
        if remote["status"] == "processing":
            break
        time.sleep(0.05)
    assert remote["status"] == "processing", remote
    started = time.monotonic()
    assert req("/api/jobs/" + gpu_id + "/cancel", "POST")[0] == 200
    gpu = wait(gpu_id, {"cancelled"}, timeout=30)
    assert not gpu["text"]
    no_audio(gpu_id)
    print("PASS active real RTX 5080 inference terminates and both sides clear audio in %.1fs" % (time.monotonic() - started), flush=True)
    assert req("/api/jobs/" + gpu_id + "/cancel", "POST")[1]["status"] == "cancelled"
    next_id = upload("终止检查-后续任务.wav", Path("test-results/zh.wav"))
    following = wait(next_id, {"done"}, timeout=45)
    assert following["backend"] == "remote_gpu" and len(following["text"]) > 4
    no_audio(next_id)
    print("PASS GPU remains usable after cancellation; next task succeeds; cancelled requests are idempotent", flush=True)
finally:
    for job_id in created:
        status, job, _ = req("/api/jobs/" + job_id)
        if status == 200 and job["status"] not in ("done", "error", "cancelled"):
            req("/api/jobs/" + job_id + "/cancel", "POST")
        req("/api/jobs/" + job_id, "DELETE")

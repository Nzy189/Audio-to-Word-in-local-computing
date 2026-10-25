"""Integration check for the local ARM64 QA container. Never prints the access code."""
import io
import json
import subprocess
import time
import urllib.error
import urllib.request
import uuid
import wave
from pathlib import Path

BASE = "http://127.0.0.1:18787"
CONTAINER = "atow-arm64-qa"
code = dict(line.split("=", 1) for line in Path("dist/shengjian-z2pro/nas.env").read_text().splitlines())["ACCESS_CODE"]
cookie = ""
created = []


def request(path, method="GET", data=None, content_type=None, authenticated=True, origin=None, host=None):
    headers = {}
    if authenticated and cookie:
        headers["Cookie"] = cookie
    if content_type:
        headers["Content-Type"] = content_type
    if origin:
        headers["Origin"] = origin
    if host:
        headers["Host"] = host
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, response.read(), response.headers
    except urllib.error.HTTPError as response:
        return response.code, response.read(), response.headers


def ready():
    deadline = time.time() + 180
    while time.time() < deadline:
        try:
            status, body, _ = request("/api/health")
            if status == 200 and json.loads(body)["ready"]:
                return
        except Exception:
            pass
        time.sleep(2)
    raise AssertionError("ARM64 recognition engine did not become ready")


def upload(name, content):
    boundary = uuid.uuid4().hex
    body = ("--" + boundary + '\r\nContent-Disposition: form-data; name="file"; filename="' + name + '"\r\nContent-Type: application/octet-stream\r\n\r\n').encode() + content + ("\r\n--" + boundary + "--\r\n").encode()
    status, body, _ = request("/api/jobs", "POST", body, "multipart/form-data; boundary=" + boundary, origin=BASE)
    assert status == 202, (status, body)
    job_id = json.loads(body)["id"]
    created.append(job_id)
    return job_id


def wait(job_id):
    deadline = time.time() + 180
    while time.time() < deadline:
        status, body, _ = request("/api/jobs/" + job_id)
        assert status == 200
        job = json.loads(body)
        if job["status"] in ("done", "error"):
            return job
        time.sleep(1)
    raise AssertionError("ARM64 transcription did not finish")


ready()
image = json.loads(subprocess.check_output(["docker", "image", "inspect", "shengjian:1.1.0-arm64"]))[0]
assert image["Architecture"] == "arm64" and image["Os"] == "linux"
assert not any(value.startswith("ACCESS_CODE=") or value.startswith("SESSION_SECRET=") for value in image["Config"]["Env"])
arch = subprocess.check_output(["docker", "exec", CONTAINER, "python", "-c", "import platform; print(platform.machine())"], text=True).strip()
assert arch == "aarch64", arch
print("PASS image and running Python are ARM64; no website code or session key embedded in image", flush=True)
status, html, headers = request("/")
assert status == 200 and b"getUserMedia" not in html
assert headers["Permissions-Policy"] == "microphone=(), camera=()"
assert request("/api/jobs", authenticated=False)[0] == 401
assert request("/api/login", "POST", b"{}", "application/json", origin="https://evil.example")[0] == 403
status, body, headers = request("/api/login", "POST", json.dumps({"code": code}).encode(), "application/json", origin=BASE)
assert status == 200, (status, body)
cookie = headers["Set-Cookie"].split(";", 1)[0]
assert "HttpOnly" in headers["Set-Cookie"] and "Secure" not in headers["Set-Cookie"]
assert request("/api/jobs", origin="http://100.114.153.9:18080", host="100.114.153.9:18080")[0] == 200
status, body, _ = request("/api/login", "POST", json.dumps({"code": code}).encode(), "application/json", origin="http://100.114.153.9:18080", host="100.114.153.9:18080")
assert status == 200, (status, body)
print("PASS login over HTTP, dynamic Tailscale origin, private session and cross-origin rejection", flush=True)
try:
    bad = wait(upload("invalid.wav", b"not an audio file"))
    assert bad["status"] == "error" and bad["elapsed"] is not None
    raw = io.BytesIO()
    with wave.open(raw, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 16000)
    silence = wait(upload("silence.wav", raw.getvalue()))
    assert silence["status"] == "done" and "未检测到" in silence["text"]
    print("PASS invalid and silent audio handling", flush=True)
    results = []
    for language in ("zh", "en"):
        result = wait(upload(language + ".wav", Path("test-results/" + language + ".wav").read_bytes()))
        assert result["status"] == "done" and len(result["text"]) > 4, result
        assert result["started"] >= result["created"] and result["finished"] >= result["started"] and result["elapsed"] > 0
        assert abs(result["finished"] - result["started"] - result["elapsed"]) < 0.2
        assert request("/api/jobs/" + result["id"] + "/text")[1].decode() == result["text"]
        results.append(result)
        print("PASS " + language + " speech / timing / TXT download under ARM64 emulation", flush=True)
    sample = "/tmp/arm64-fixture.wav"
    subprocess.run(["docker", "exec", "-i", CONTAINER, "python", "-c", "import sys; open('/tmp/arm64-fixture.wav','wb').write(sys.stdin.buffer.read())"], input=Path("test-results/zh.wav").read_bytes(), check=True, capture_output=True)
    for extension, codec in (("m4a", "aac"), ("mp3", "libmp3lame"), ("webm", "libopus")):
        output = "/tmp/arm64-fixture." + extension
        subprocess.run(["docker", "exec", CONTAINER, "ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", sample, "-c:a", codec, output], check=True, capture_output=True)
        content = subprocess.check_output(["docker", "exec", CONTAINER, "cat", output])
        result = wait(upload("fixture." + extension, content))
        assert result["status"] == "done" and len(result["text"]) > 4, result
        print("PASS ARM64 " + extension.upper() + " conversion and recognition", flush=True)
    status, body, _ = request("/api/jobs")
    assert status == 200 and len(json.loads(body)) == len(created)
    uid = subprocess.check_output(["docker", "exec", CONTAINER, "python", "-c", "from pathlib import Path; print(next(x for x in Path('/proc/1/status').read_text().splitlines() if x.startswith('Uid:')))"], text=True)
    assert uid.split()[1:] == ["10001"] * 4, uid
    secret = subprocess.check_output(["docker", "exec", CONTAINER, "python", "-c", "import os; print(oct(os.stat('/data/.session-secret').st_mode & 0o777))"], text=True).strip()
    assert secret == "0o600", secret
    print("PASS non-root application process and persistent secret permissions", flush=True)
    subprocess.run(["docker", "restart", CONTAINER], check=True, capture_output=True)
    ready()
    for result in results:
        status, body, _ = request("/api/jobs/" + result["id"])
        assert status == 200 and json.loads(body)["text"] == result["text"]
    print("PASS same login session and transcript records survive container restart", flush=True)
    for job_id in created:
        check = "from pathlib import Path; assert not Path('/data/" + job_id + ".upload').exists(); assert not Path('/data/" + job_id + ".wav').exists()"
        subprocess.run(["docker", "exec", CONTAINER, "python", "-c", check], check=True, capture_output=True)
    print("PASS processed audio is removed", flush=True)
finally:
    for job_id in created:
        request("/api/jobs/" + job_id, "DELETE")
print("PASS ARM64 NAS integration checks complete", flush=True)

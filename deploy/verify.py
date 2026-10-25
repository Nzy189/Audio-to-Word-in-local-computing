"""Integration checks on the ECS. Does not print or persist credentials."""
import io
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
import uuid
import wave
from pathlib import Path

BASE = "http://127.0.0.1:8787"
env = dict(line.split("=", 1) for line in Path("/opt/atow/app.env").read_text().splitlines() if "=" in line)
cookie = ""


def request(path, method="GET", data=None, content_type=None, authenticated=True, origin=None):
    headers = {}
    if authenticated and cookie:
        headers["Cookie"] = cookie
    if content_type:
        headers["Content-Type"] = content_type
    if origin:
        headers["Origin"] = origin
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, response.read(), response.headers
    except urllib.error.HTTPError as response:
        return response.code, response.read(), response.headers


def upload(name, content):
    boundary = uuid.uuid4().hex
    body = ('--' + boundary + '\r\nContent-Disposition: form-data; name="file"; filename="' + name + '"\r\nContent-Type: audio/wav\r\n\r\n').encode() + content + ('\r\n--' + boundary + '--\r\n').encode()
    status, data, _ = request("/api/jobs", "POST", body, "multipart/form-data; boundary=" + boundary)
    assert status == 202, (status, data)
    return json.loads(data)["id"]


def wait(job_id):
    deadline = time.time() + 300
    while time.time() < deadline:
        status, data, _ = request("/api/jobs/" + job_id)
        assert status == 200
        job = json.loads(data)
        if job["status"] in ("done", "error"):
            return job
        time.sleep(1)
    raise AssertionError("Transcription did not finish within five minutes")


assert request("/api/jobs", authenticated=False)[0] == 401
assert request("/api/login", "POST", b'{}', "application/json", origin="https://invalid.example")[0] == 403
assert request("/api/login", "POST", b'{"code":"incorrect-test-code"}', "application/json")[0] == 401
status, data, headers = request("/api/login", "POST", json.dumps({"code": env["ACCESS_CODE"]}).encode(), "application/json")
assert status == 200
cookie = headers["Set-Cookie"].split(";", 1)[0]
assert "Secure" in headers["Set-Cookie"] and "HttpOnly" in headers["Set-Cookie"]
print("PASS authentication, cookie flags and origin protection", flush=True)

created = []
try:
    malformed = upload("invalid.wav", b"this is not audio")
    created.append(malformed)
    assert wait(malformed)["status"] == "error"
    print("PASS invalid audio is rejected with a task error", flush=True)
    wav = io.BytesIO()
    with wave.open(wav, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(16000)
        target.writeframes(b"\x00\x00" * 16000)
    silence = upload("silence.wav", wav.getvalue())
    created.append(silence)
    result = wait(silence)
    assert result["status"] == "done", result
    assert "未检测到" in result["text"], result
    print("PASS silent audio completes without invented speech", flush=True)
    root = Path("/opt/atow/models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17/test_wavs")
    for language in ("zh", "en"):
        job_id = upload(language + ".wav", (root / (language + ".wav")).read_bytes())
        created.append(job_id)
        started = time.time()
        result = wait(job_id)
        assert result["status"] == "done" and len(result["text"]) > 4, result
        if language == "zh":
            assert any("\u4e00" <= char <= "\u9fff" for char in result["text"])
        else:
            assert any(ord(char) < 128 and char.isalpha() for char in result["text"])
        status, text, _ = request("/api/jobs/" + job_id + "/text")
        assert status == 200 and text.decode() == result["text"]
        assert not Path("/opt/atow/data/" + job_id + ".upload").exists()
        assert not Path("/opt/atow/data/" + job_id + ".wav").exists()
        print("PASS {} speech / TXT download / audio cleanup: {:.1f}s audio, {:.1f}s wait".format(language, result["duration"], time.time() - started), flush=True)
        print("Sample: " + result["text"][:200], flush=True)
    # Validate real compressed formats, including a minute-long phone-style M4A.
    docker = "/opt/atow/runtime/docker/docker"
    sample = "/models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17/test_wavs/zh.wav"
    for ext, codec in (("m4a", "aac"), ("mp3", "libmp3lame"), ("webm", "libopus")):
        output = "/tmp/atow-format-check." + ext
        extra = ["-stream_loop", "-1"] if ext == "m4a" else []
        command = [docker, "exec", "atow-app", "ffmpeg", "-nostdin", "-loglevel", "error", "-y"] + extra + ["-i", sample]
        if ext == "m4a":
            command += ["-t", "60"]
        command += ["-c:a", codec, output]
        subprocess.check_call(command)
        content = subprocess.check_output([docker, "exec", "atow-app", "cat", output])
        job_id = upload("format-check." + ext, content)
        created.append(job_id)
        result = wait(job_id)
        assert result["status"] == "done" and len(result["text"]) > 4, result
        if ext == "m4a":
            assert 59 < result["duration"] < 61, result
        subprocess.check_call([docker, "exec", "atow-app", "rm", "-f", output])
        print("PASS {} upload and transcription ({:.1f}s audio)".format(ext.upper(), result["duration"]), flush=True)
finally:
    for job_id in created:
        request("/api/jobs/" + job_id, "DELETE")
print("PASS test records removed", flush=True)

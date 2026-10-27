"""ARM64 integration: LLM refine pipeline, env/web config, failure paths, downloads, old-DB migration."""
# 用法：verify-refine.py a  → Phase A（容器不带 LLM 环境变量时运行）
#       verify-refine.py b  → Phase B（容器带 LLM_* 环境变量指向 stub 时运行）
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = "http://127.0.0.1:18787"
CONTAINER = "atow-logs-qa"
LLM_DEFAULT_URL = "https://llm-4qs0qwijnzh269f3.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
access = dict(x.split("=", 1) for x in Path("dist/shengjian-1.4/nas.env").read_text().splitlines() if "=" in x)["ACCESS_CODE"]
cookie = ""
created = []
failures = []


def req(path, method="GET", data=None, content_type=None, auth=True):
    headers = {"Cookie": cookie} if auth else {}
    if content_type:
        headers["Content-Type"] = content_type
    if isinstance(data, dict):
        data = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, response.read(), response.headers
    except urllib.error.HTTPError as response:
        return response.code, response.read(), response.headers


def ready():
    for _ in range(150):
        try:
            if json.loads(req("/api/health", auth=False)[1])["ready"]:
                return
        except Exception:
            pass
        time.sleep(1)
    raise AssertionError("NAS QA engine did not become ready")


def login():
    global cookie
    status, _, headers = req("/api/login", "POST", {"code": access})
    assert status == 200, "login status " + str(status)
    cookie = headers["Set-Cookie"].split(";", 1)[0]


def upload(name):
    boundary = uuid.uuid4().hex
    body = ("--" + boundary + '\r\nContent-Disposition: form-data; name="file"; filename="' + name + '"\r\nContent-Type: audio/wav\r\n\r\n').encode() + Path("test-results/zh.wav").read_bytes() + ("\r\n--" + boundary + "--\r\n").encode()
    status, raw, _ = req("/api/jobs", "POST", body, "multipart/form-data; boundary=" + boundary)
    assert status == 202, (status, raw)
    job_id = json.loads(raw)["id"]
    created.append(job_id)
    job = {}
    for _ in range(360):
        job = json.loads(req("/api/jobs/" + job_id)[1])
        if job["status"] in ("done", "error"):
            break
        time.sleep(0.5)
    assert job["status"] == "done", job
    return job


def wait_refine(job_id, wanted, timeout=120):
    deadline = time.monotonic() + timeout
    job = {}
    while time.monotonic() < deadline:
        job = json.loads(req("/api/jobs/" + job_id)[1])
        if job["refine_status"] == wanted:
            return job
        if job["refine_status"] in ("done", "failed"):
            raise AssertionError("refine_status=" + str(job["refine_status"]) + " but wanted " + wanted + " | " + str(job.get("refine_error")))
        time.sleep(0.5)
    raise AssertionError("refine_status did not become " + wanted + " within " + str(timeout) + "s, now=" + str(job.get("refine_status")))


def llm_config(payload=None):
    if payload is None:
        status, raw, _ = req("/api/llm-config")
    else:
        status, raw, _ = req("/api/llm-config", "POST", payload)
    assert status == 200, (status, raw)
    return json.loads(raw)


def check(name, function):
    try:
        function()
        print("PASS " + name, flush=True)
    except Exception as exc:
        failures.append(name)
        print("FAIL " + name + " " + str(exc)[:400], flush=True)


state = {}


def t0():
    status, raw, _ = req("/api/jobs/old1")
    assert status == 200, (status, raw)
    job = json.loads(raw)
    assert job["text"] == "旧转写文字", repr(job.get("text"))
    assert job["refine_status"] == "none", repr(job.get("refine_status"))


def t1():
    config = llm_config()
    assert config["source"] == "默认配置", config
    assert config["enabled"] is True, config
    assert "maas.aliyuncs.com" in config["base_url"], config
    assert config["model"] == "kimi-k3", config
    assert config["api_key_set"] is False, config


def t2():
    job = upload("提炼检查-无Key不提炼.wav")
    time.sleep(2)
    job = json.loads(req("/api/jobs/" + job["id"])[1])
    assert job["refine_status"] == "none", repr(job["refine_status"])


def t3():
    config = llm_config()
    assert config["source"] == "默认配置", config
    assert config["api_key_set"] is True, config
    assert config["api_key_masked"] == "sk-***", config
    job = upload("提炼检查-env全链路.wav")
    job = wait_refine(job["id"], "done")
    assert job["refined_text"] == "这是优化后的测试原文", repr(job["refined_text"])
    assert job["summary"] == "- 测试要点", repr(job["summary"])
    assert any(e["event"] == "提炼" for e in job["events"]), job["events"]
    state["job"] = job


def t4():
    job = state.get("job")
    assert job, "T3 job unavailable"
    config = llm_config({"enabled": True, "model": "stub-garbage"})
    assert config["source"] == "网页设置", config
    status, raw, _ = req("/api/jobs/" + job["id"] + "/refine", "POST")
    assert status == 200, (status, raw)
    job = wait_refine(job["id"], "failed")
    assert "解析" in (job["refine_error"] or ""), repr(job["refine_error"])
    assert job["status"] == "done", repr(job["status"])


def t5():
    job = state.get("job")
    assert job, "T3 job unavailable"
    llm_config({"model": "stub-ok"})
    status, raw, _ = req("/api/jobs/" + job["id"] + "/refine", "POST")
    assert status == 200, (status, raw)
    job = wait_refine(job["id"], "done")
    assert job["refined_text"] == "这是优化后的测试原文", repr(job["refined_text"])


def t6():
    job = state.get("job")
    assert job, "T3 job unavailable"
    llm_config({"model": "stub-slow"})
    status, raw, _ = req("/api/jobs/" + job["id"] + "/refine", "POST")
    assert status == 200, (status, raw)
    status, raw, _ = req("/api/jobs/" + job["id"] + "/refine", "POST")
    assert status == 409, (status, raw)
    assert "正在提炼中" in raw.decode("utf-8", "replace"), raw
    job = wait_refine(job["id"], "done")
    assert job["refined_text"] == "这是优化后的测试原文", repr(job["refined_text"])


def t7():
    llm_config({"enabled": False})
    job = upload("提炼检查-关闭开关.wav")
    time.sleep(2)
    job = json.loads(req("/api/jobs/" + job["id"])[1])
    assert job["refine_status"] == "none", repr(job["refine_status"])
    state["disabled_job"] = job


def t8():
    job = state.get("job")
    assert job, "T3 job unavailable"
    status, raw, _ = req("/api/jobs/" + job["id"] + "/text?part=refined")
    assert status == 200, (status, raw)
    assert raw.decode("utf-8") == "这是优化后的测试原文", raw
    status, raw, _ = req("/api/jobs/" + job["id"] + "/text?part=summary")
    assert status == 200, (status, raw)
    assert raw.decode("utf-8") == "- 测试要点", raw
    status, raw, _ = req("/api/jobs/" + job["id"] + "/text?part=original")
    assert status == 200, (status, raw)
    assert len(raw.decode("utf-8")) > 4, raw
    disabled = state.get("disabled_job")
    assert disabled, "T7 job unavailable"
    status, raw, _ = req("/api/jobs/" + disabled["id"] + "/text?part=refined")
    assert status == 409, (status, raw)


def t9():
    code = (
        "import urllib.error, urllib.request\n"
        "try:\n"
        "    urllib.request.urlopen('" + LLM_DEFAULT_URL + "/models', timeout=20)\n"
        "    raise SystemExit('unexpected success')\n"
        "except urllib.error.HTTPError as exc:\n"
        "    print('HTTP', exc.code)\n"
        "    raise SystemExit(0 if exc.code == 401 else 1)\n"
    )
    result = subprocess.run(["docker", "exec", CONTAINER, "python", "-c", code], capture_output=True, timeout=90)
    output = (result.stdout + result.stderr).decode(errors="replace").strip()
    assert result.returncode == 0, "exit=" + str(result.returncode) + " " + output
    assert "HTTP 401" in output, output


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else ""
    if phase == "a":
        checks = [("T0 old-db migration keeps old record readable", t0),
                  ("T1 env unset defaults", t1),
                  ("T2 no api key means no refine", t2)]
        label, total = "Phase A", 3
    elif phase == "b":
        checks = [("T3 env config full pipeline", t3),
                  ("T4 web override and parse failure path", t4),
                  ("T5 re-refine after failure", t5),
                  ("T6 concurrent refine rejected with 409", t6),
                  ("T7 web switch off means no refine", t7),
                  ("T8 refined/summary/original downloads", t8),
                  ("T9 outbound https to real model endpoint", t9)]
        label, total = "Phase B", 7
    else:
        raise SystemExit("usage: verify-refine.py a|b")
    ready()
    login()
    for name, function in checks:
        check(name, function)
    if phase == "b":
        try:
            restored = llm_config({"enabled": True, "model": "stub-ok"})
            assert restored["enabled"] is True and restored["model"] == "stub-ok", restored
            print("PASS config restored (enabled=true, model=stub-ok) for browser check", flush=True)
        except Exception as exc:
            failures.append("restore config")
            print("FAIL restore config " + str(exc)[:300], flush=True)
    if failures:
        print("FAILED: " + ", ".join(failures), flush=True)
        raise SystemExit(1)
    print(label + " ALL " + str(total) + " PASS", flush=True)


main()

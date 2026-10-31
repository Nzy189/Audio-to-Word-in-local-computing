"""Build-independent ECS image QA on a local Docker engine; no production access."""
from pathlib import Path
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "atow-transcriber:1.6.2-ecs"
NAME = "atow-ecs-qa-" + uuid.uuid4().hex[:12]


def docker(*args, source=None):
    result = subprocess.run(["docker", *args], input=source, text=True, encoding="utf-8",
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout


print(docker("image", "inspect", "--format", "{{.Os}}/{{.Architecture}} {{.Id}}", IMAGE).strip(), flush=True)
print(docker("run", "--rm", "-i", "--network", "none", "--read-only",
             "--tmpfs", "/tmp:rw,noexec,nosuid,size=128m", IMAGE, "python", "-",
             source=(ROOT / "deploy/migration-check.py").read_text(encoding="utf-8")), flush=True)
created = False
try:
    docker("run", "-d", "--name", NAME, "--cpus", "3", "--memory", "4g",
           "--pids-limit", "256", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
           "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=128m",
           "--tmpfs", "/data:rw,noexec,nosuid,size=512m,uid=10001,gid=10001",
           "--mount", "type=bind,src=" + str(ROOT / "build-assets/models") + ",dst=/models,readonly",
           "--mount", "type=bind,src=" + str(ROOT / "test-results/zh.wav") + ",dst=/qa/zh.wav,readonly",
           "--env", "ACCESS_CODE=isolated-ecs-qa", "--env", "ATOW_ECS_QA=1",
           "--env", "COOKIE_SECURE=false", IMAGE)
    created = True
    docker("exec", "-d", NAME, "python", "-c",
           (ROOT / "deploy/nas/stub-llm.py").read_text(encoding="utf-8"))
    print(docker("exec", "-i", NAME, "python", "-u", "-",
                 source=(ROOT / "deploy/ecs/verify-smoke.py").read_text(encoding="utf-8")), flush=True)
finally:
    if created:
        docker("rm", "--force", NAME)
        print("QA container and tmpfs data removed: " + NAME, flush=True)

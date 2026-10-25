"""Prepare only the application's data directory, then drop root privileges."""
import os
import sys
from pathlib import Path

data = Path(os.getenv("DATA_DIR", "/data"))
uid = int(os.getenv("PUID", "10001"))
gid = int(os.getenv("PGID", "10001"))
if uid <= 0 or gid <= 0:
    raise SystemExit("PUID and PGID must be non-root IDs")
if os.geteuid() == 0:
    data.mkdir(parents=True, exist_ok=True)
    os.chown(data, uid, gid)
    os.setgroups([])
    os.setgid(gid)
    os.setuid(uid)
os.umask(0o077)
if not os.getenv("ACCESS_CODE"):
    raise SystemExit("Set ACCESS_CODE to the website access code before starting")
os.execvp(sys.argv[1], sys.argv[1:])

"""Isolated checks for a cancelled task surviving restart and a disconnect/cancel race."""
import asyncio
import os
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="cancel-recovery-")
os.environ["ACCESS_CODE"] = "isolated-test"
os.environ["SESSION_SECRET"] = "isolated-test-session"
import app
from remote_worker import RemoteUnavailable
app.worker = lambda: None


class DisconnectingWorker:
    def __init__(self):
        self.cancelled = False

    def run(self, job_id, source, progress, stop, check_cancel):
        progress("remote_processing", 10, "Test GPU", "电脑正在处理")
        app.cancel_flags[job_id] = threading.Event()
        app.cancel_flags[job_id].set()
        raise RemoteUnavailable("连接中断", "connection_lost")

    def cancel(self, job_id):
        self.cancelled = True
        return True


async def main():
    async with app.lifespan(app.app):
        recovery = "a" * 32
        with app.db() as conn:
            conn.execute("INSERT INTO jobs(id,name,status,created) VALUES (?,?,'cancelling',?)", (recovery, "recovery.wav", time.time()))
        (app.DATA / (recovery + ".upload")).write_bytes(b"fixture")
        app.clean_expired()
        assert app.detail(recovery)["status"] == "cancelled"
        assert not (app.DATA / (recovery + ".upload")).exists()
        print("PASS interrupted termination is completed after restart, without resuming transcription")
        race = "b" * 32
        with app.db() as conn:
            conn.execute("INSERT INTO jobs(id,name,status,created) VALUES (?,?,'queued',?)", (race, "race.wav", time.time()))
        (app.DATA / (race + ".upload")).write_bytes(b"fixture")
        fake = DisconnectingWorker()
        app.remote_from_settings = lambda config: fake
        app.dispatch(app.detail(race), None)
        assert fake.cancelled and app.detail(race)["status"] == "cancelled"
        assert not (app.DATA / (race + ".upload")).exists()
        print("PASS simultaneous disconnect and termination cancels remote work instead of starting NAS fallback")


asyncio.run(main())

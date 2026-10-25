"""Run in the application image against an isolated temporary database."""
import asyncio
import os
import sqlite3
import tempfile
from pathlib import Path

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="atow-migration-")
os.environ["SESSION_SECRET"] = "isolated-migration-check"
os.environ["ACCESS_CODE"] = "isolated-migration-check"
database = Path(os.environ["DATA_DIR"]) / "jobs.sqlite3"
with sqlite3.connect(database) as conn:
    conn.execute("""CREATE TABLE jobs (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL,
        progress INTEGER DEFAULT 0, text TEXT DEFAULT '', error TEXT DEFAULT '',
        duration REAL DEFAULT 0, created REAL NOT NULL, finished REAL DEFAULT 0)""")
    conn.execute("INSERT INTO jobs(id,name,status,progress,text,duration,created,finished) VALUES ('old','old.wav','done',100,'Preserve the existing result',12,1000,1020)")

import app
app.worker = lambda: None  # This check concerns schema migration, not inference.


async def check():
    for _ in range(2):
        async with app.lifespan(app.app):
            row = app.detail("old")
            assert row["text"] == "Preserve the existing result"
            assert row["duration"] == 12 and row["finished"] == 1020
            assert row["started"] is None and row["elapsed"] is None
            assert len(app.jobs()) == 1
    print("PASS existing records preserved; unknown historical timings remain null; migration is idempotent")


asyncio.run(check())

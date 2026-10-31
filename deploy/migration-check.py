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
    # 1.5 时代的旧库：已有 refine 列，但没有 corrected/hardware 列
    for column in ("refine_status TEXT DEFAULT 'none'", "refined_text TEXT DEFAULT ''",
                   "summary TEXT DEFAULT ''", "refine_error TEXT DEFAULT ''", "refine_at REAL DEFAULT NULL"):
        conn.execute("ALTER TABLE jobs ADD COLUMN " + column)
    conn.execute("INSERT INTO jobs(id,name,status,progress,text,duration,created,finished) VALUES ('old','old.wav','done',100,'Preserve the existing result',12,1000,1020)")
    conn.execute("INSERT INTO jobs(id,name,status,progress,text,duration,created,finished,refine_status,refined_text,summary,refine_error,refine_at) VALUES ('old2','old2.wav','done',100,'旧转写',12,1000,1020,'done','旧修正文','旧纪要','',1234)")

import app
app.worker = lambda: None  # This check concerns schema migration, not inference.


async def check():
    for _ in range(2):
        async with app.lifespan(app.app):
            row = app.detail("old")
            assert row["text"] == "Preserve the existing result"
            assert row["duration"] == 12 and row["finished"] == 1020
            assert row["started"] is None and row["elapsed"] is None
            assert row["refine_status"] == "none" and row["corrected_status"] == "none"
            assert row["hardware_name"] == ""
            legacy = app.detail("old2")
            assert legacy["refine_status"] == "done" and legacy["refined_text"] == "旧修正文"
            assert legacy["summary"] == "旧纪要"
            assert legacy["corrected_status"] == "done", "旧完成记录应回填 corrected_status=done，实际 " + repr(legacy["corrected_status"])
            assert len(app.jobs()) == 2
    print("PASS existing records preserved; legacy refined rows backfilled to corrected done; migration is idempotent")


asyncio.run(check())

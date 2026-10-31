"""Hash existing rows/settings before and after migration; never print their contents.

Run as the database owner. Queries use SQLite read-only mode; the directory
must permit normal WAL/shared-memory access. Keep the reference file in a
protected backup directory on the server.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


parser = argparse.ArgumentParser()
parser.add_argument("mode", choices=("save", "check"))
parser.add_argument("reference", type=Path)
args = parser.parse_args()
reference = None if args.mode == "save" else json.loads(args.reference.read_text(encoding="utf-8"))
with sqlite3.connect("file:/data/jobs.sqlite3?mode=ro", uri=True) as conn:
    columns = [row[1] for row in conn.execute("PRAGMA table_info(jobs)")] if reference is None else reference["columns"]
    quoted = ",".join('"' + column.replace('"', '""') + '"' for column in columns)
    rows = conn.execute("SELECT " + quoted + " FROM jobs ORDER BY id").fetchall()
    ids = [row[columns.index("id")] for row in rows] if reference is None else reference["ids"]
    wanted = set(ids)
    old_rows = [row for row in rows if row[columns.index("id")] in wanted]
    settings = conn.execute("SELECT key,value FROM settings ORDER BY key").fetchall()
    session = Path("/data/.session-secret")
    state = {"columns": columns, "ids": ids, "records_sha256": digest(old_rows),
             "settings_sha256": digest(settings),
             "session_sha256": hashlib.sha256(session.read_bytes()).hexdigest() if session.exists() else None}
    if reference is not None:
        assert len(old_rows) == len(ids), "An existing record is missing"
        for key in ("records_sha256", "settings_sha256", "session_sha256"):
            assert state[key] == reference[key], "Preservation check failed: " + key
        if "corrected_status" not in reference["columns"]:
            pending = conn.execute("SELECT count(*) FROM jobs WHERE refine_status='done' AND refined_text!='' AND corrected_status!='done'").fetchone()[0]
            assert pending == 0, "Legacy refined records were not migrated to corrected done"
if reference is None:
    args.reference.write_text(json.dumps(state, ensure_ascii=False) + "\n", encoding="utf-8")
    args.reference.chmod(0o600)
    print("Preservation reference saved; existing record count=" + str(len(ids)), flush=True)
else:
    print("Existing records, AI settings and session secret preserved; count=" + str(len(ids)), flush=True)

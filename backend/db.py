"""SQLite storage - no external DB. One file, per-device job history."""
import os
import sqlite3
import time
import uuid

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "jobs.db"))


def _connect():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(os.path.abspath(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _connect()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS devices (
            id TEXT PRIMARY KEY,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            short_url TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            progress TEXT NOT NULL DEFAULT 'Queued...',
            gateway TEXT,
            telegram TEXT,
            final_url TEXT,
            error TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_jobs_device ON jobs(device_id, created_at DESC);
        """
    )
    conn.commit()
    conn.close()


def ensure_device(device_id: str) -> str:
    device_id = (device_id or "").strip() or f"dev-{uuid.uuid4().hex[:12]}"
    conn = _connect()
    row = conn.execute("SELECT id FROM devices WHERE id=?", (device_id,)).fetchone()
    if not row:
        conn.execute("INSERT INTO devices (id, created_at) VALUES (?, ?)", (device_id, int(time.time())))
        conn.commit()
    conn.close()
    return device_id


def create_job(device_id: str, short_url: str) -> dict:
    jid = f"job-{uuid.uuid4().hex[:12]}"
    now = int(time.time())
    conn = _connect()
    conn.execute(
        "INSERT INTO jobs (id, device_id, short_url, status, progress, created_at, updated_at)"
        " VALUES (?, ?, ?, 'queued', 'Queued...', ?, ?)",
        (jid, device_id, short_url, now, now),
    )
    conn.commit()
    conn.close()
    return get_job(jid)


def get_job(jid: str):
    conn = _connect()
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_jobs(device_id: str, limit: int = 100):
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM jobs WHERE device_id=? ORDER BY created_at DESC LIMIT ?", (device_id, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_job(jid: str, **fields):
    fields["updated_at"] = int(time.time())
    sets = ", ".join(f"{k}=?" for k in fields)
    conn = _connect()
    conn.execute(f"UPDATE jobs SET {sets} WHERE id=?", (*fields.values(), jid))
    conn.commit()
    conn.close()

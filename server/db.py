import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "kairos.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT UNIQUE NOT NULL,
    google_sub    TEXT UNIQUE,
    refresh_token TEXT,
    token_expiry  TEXT,
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL DEFAULT 1,
    email_id      TEXT,
    dedup_key     TEXT,
    type          TEXT NOT NULL CHECK(type IN ('billing','appointment','deadline','delivery','other')),
    title         TEXT NOT NULL,
    datetime      TEXT NOT NULL,        -- 直接按前端合同存:'2026-08-05' 或 '2026-08-05 19:00'
    status        TEXT NOT NULL DEFAULT 'active',
    source_domain TEXT,
    created_at    TEXT DEFAULT (datetime('now')),
    updated_at    TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_events_user_date ON events(user_id, datetime);
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_dedup ON events(user_id, dedup_key)
    WHERE dedup_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS sync_state (
    user_id            INTEGER PRIMARY KEY,
    last_internal_date INTEGER,
    last_run_at        TEXT,
    last_status        TEXT
);
"""

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row      # 行为可按列名取值的对象
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)

def list_events(user_id: int = 1):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, datetime, type, title FROM events "
            "WHERE user_id = ? AND status = 'active' ORDER BY datetime",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]

def add_event(ev: dict, user_id: int = 1):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO events (user_id, type, title, datetime) VALUES (?,?,?,?)",
            (user_id, ev["type"], ev["title"], ev["datetime"]),
        )
        row = conn.execute(
            "SELECT id, datetime, type, title FROM events WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
    return dict(row)

def upsert_user(email: str, google_sub: str, refresh_token: str | None):
    """按 google_sub 存在则更新,不存在则插入。refresh_token 为 None 时保留旧值。"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE google_sub = ?", (google_sub,)
        ).fetchone()
        if row:
            if refresh_token:
                conn.execute(
                    "UPDATE users SET email = ?, refresh_token = ? WHERE google_sub = ?",
                    (email, refresh_token, google_sub))
            return row["id"]
        cur = conn.execute(
            "INSERT INTO users (email, google_sub, refresh_token) VALUES (?,?,?)",
            (email, google_sub, refresh_token))
        return cur.lastrowid
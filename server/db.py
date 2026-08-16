import os
import secrets
import sqlite3
from pathlib import Path
from fastapi import FastAPI, Body, Cookie, HTTPException, Depends

DB_PATH = Path(os.environ.get("KAIROS_DB_PATH",
                              Path(__file__).resolve().parent / "kairos.db"))

SESSION_DAYS = 30

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
CREATE INDEX IF NOT EXISTS idx_events_dedup ON events(user_id, dedup_key);

CREATE TABLE IF NOT EXISTS sync_state (
    user_id            INTEGER PRIMARY KEY,
    last_internal_date INTEGER,
    last_run_at        TEXT,
    last_status        TEXT
);

CREATE TABLE IF NOT EXISTS extraction_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    email_id      TEXT NOT NULL,
    run_at        TEXT DEFAULT (datetime('now')),
    gate          TEXT,          -- rule_filter | haiku | time_probe | sonnet
    verdict       TEXT,          -- positive | negative | error
    rule_hit      TEXT,
    tokens_in     INTEGER DEFAULT 0,
    tokens_out    INTEGER DEFAULT 0,
    event_ids     TEXT           -- 判正时生成的事件 id,逗号分隔
);
CREATE INDEX IF NOT EXISTS idx_log_user_time ON extraction_log(user_id, run_at);

CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT PRIMARY KEY,          -- 随机串,牌子本体
    user_id     INTEGER NOT NULL,
    created_at  TEXT DEFAULT (datetime('now')),
    expires_at  TEXT NOT NULL,
    last_seen   TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
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

def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)      # 256 位随机,不可猜
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, expires_at) "
            "VALUES (?, ?, datetime('now', ?))",
            (token, user_id, f"+{SESSION_DAYS} days"))
    return token

def get_session_user(token: str | None) -> int | None:
    if not token:
        return None
    with get_conn() as conn:
        row = conn.execute(
            "SELECT user_id FROM sessions "
            "WHERE token = ? AND expires_at > datetime('now')",
            (token,)).fetchone()
        if row:
            conn.execute("UPDATE sessions SET last_seen = datetime('now') "
                         "WHERE token = ?", (token,))
            return row["user_id"]
    return None

def delete_session(token: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
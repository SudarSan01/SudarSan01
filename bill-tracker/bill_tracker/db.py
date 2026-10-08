"""SQLite connection, schema and app settings."""

from __future__ import annotations

import os
import secrets
import sqlite3

DEFAULT_DB = "bill_tracker.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT NOT NULL DEFAULT '',
    callmebot_key TEXT NOT NULL DEFAULT '',
    notify INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS bills (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    amount REAL,
    due_date TEXT NOT NULL,
    repeat_unit TEXT NOT NULL,
    repeat_every INTEGER NOT NULL DEFAULT 1,
    anchor_day INTEGER NOT NULL,
    remind_days TEXT NOT NULL,
    owner_id INTEGER REFERENCES members(id) ON DELETE SET NULL,
    reference TEXT NOT NULL DEFAULT '',
    link TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY,
    bill_id INTEGER NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
    due_date TEXT NOT NULL,
    paid_on TEXT NOT NULL,
    amount REAL,
    paid_by INTEGER REFERENCES members(id) ON DELETE SET NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

-- One row per reminder delivered, so each stage goes out once per person.
CREATE TABLE IF NOT EXISTS reminders_sent (
    bill_id INTEGER NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
    due_date TEXT NOT NULL,
    stage TEXT NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    sent_at TEXT NOT NULL,
    PRIMARY KEY (bill_id, due_date, stage, member_id)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def default_db_path() -> str:
    return os.environ.get("BILL_TRACKER_DB", DEFAULT_DB)


def connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or default_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def secret_key(conn: sqlite3.Connection) -> str:
    """The web session signing key, created on first use and kept in the database."""
    value = get_setting(conn, "secret_key")
    if value is None:
        value = secrets.token_hex(32)
        conn.execute("INSERT INTO settings (key, value) VALUES ('secret_key', ?)", (value,))
        conn.commit()
    return value

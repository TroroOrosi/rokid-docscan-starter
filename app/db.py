"""SQLite storage using the stdlib sqlite3 module (no external ORM)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import DB_PATH

__all__ = ["sqlite3", "connect", "init_db"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT NOT NULL,
    capture_device TEXT,
    status        TEXT NOT NULL DEFAULT 'open',
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_index  INTEGER NOT NULL,
    image_path  TEXT NOT NULL,
    phash       TEXT NOT NULL,
    ocr_text    TEXT,
    ocr_md5     TEXT,
    summary     TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(document_id, page_index)
);
"""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path | None = None) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()

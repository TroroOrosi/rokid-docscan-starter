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

-- Exam-solving mode (案11): a temporary session holding captured questions,
-- extracted structure, model answers and separated confidences.
CREATE TABLE IF NOT EXISTS exam_sessions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    mode          TEXT NOT NULL DEFAULT 'study',   -- study | mock | real
    voice_enabled INTEGER NOT NULL DEFAULT 0,
    subject_hint  TEXT,
    status        TEXT NOT NULL DEFAULT 'open',
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS questions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES exam_sessions(id) ON DELETE CASCADE,
    question_no     TEXT,
    body_text       TEXT,
    choices_json    TEXT,
    figure_refs     TEXT,
    answer_box_json TEXT,
    structure_json  TEXT,
    subject         TEXT,
    read_conf       REAL,
    page_number     INTEGER,
    image_path      TEXT,
    media_json      TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS solutions (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id        INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    solver_name        TEXT,
    answer             TEXT,
    solution_steps_json TEXT,
    rationale          TEXT,
    cautions           TEXT,
    answer_conf        REAL,
    rationale_conf     REAL,
    evidence_pages_json TEXT,
    raw_reasoning      TEXT,
    served_by          TEXT,
    user_confirmed     INTEGER NOT NULL DEFAULT 0,
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Live document explanation mode (scan-free, button-only navigation).
--
-- Design: no camera image is required to navigate pages.  The glasses user
-- presses next-page / prev-page buttons; the server increments or decrements
-- current_page_index and immediately serves the explanation HUD.
--
-- Status transitions:
--   ready      : session created; explanation available immediately.
--   explaining : user has requested at least one page explanation.
--
-- current_page_index : 0-based index of the page currently being viewed.
--                      Clamped server-side to [0, total_pages-1].
CREATE TABLE IF NOT EXISTS explain_sessions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id         INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    voice_enabled       INTEGER NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'ready',
    current_page_index  INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One row per page-explanation view inside an explain_session.
-- Stores HUD lines (paginated) and long-form detail for the history endpoint.
CREATE TABLE IF NOT EXISTS explain_views (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          INTEGER NOT NULL REFERENCES explain_sessions(id) ON DELETE CASCADE,
    page_index          INTEGER NOT NULL,
    verdict             TEXT NOT NULL,
    hud_lines_json      TEXT,
    detail              TEXT,
    evidence_pages_json TEXT,
    confidence          REAL,
    viewed_at           TEXT NOT NULL DEFAULT (datetime('now'))
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

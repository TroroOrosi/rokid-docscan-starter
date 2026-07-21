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
    -- Nullable: with "撮影しない" (no photography) a page has no image; the
    -- on-glass AI recognizes it and sends the reading as text (image_path/phash
    -- stay empty).
    image_path  TEXT,
    phash       TEXT NOT NULL DEFAULT '',
    ocr_text    TEXT,
    -- On-glass AI's multimodal recognition of figures/diagrams/visual layout
    -- (TEXT, not an image). Combined with ocr_text when solving so figure-
    -- dependent and page-spanning problems are answered from the whole material.
    vision_text TEXT,
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
    -- Scan-free document page-move型 exam (added v0.7): bind to a finalized
    -- document and navigate pages by button (no camera). exam_type switches
    -- 筆記(written) ⇄ リスニング(listening); answer_format = mark | written.
    document_id        INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    exam_type          TEXT NOT NULL DEFAULT 'written',
    answer_format      TEXT NOT NULL DEFAULT 'mark',
    current_page_index INTEGER NOT NULL DEFAULT 0,
    audio_path         TEXT,      -- listening: recorded audio (その場で録音)
    transcript         TEXT,      -- listening: transcript (書き起こし or 与値)
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
    evidence_refs_json  TEXT,
    raw_reasoning      TEXT,
    served_by          TEXT,
    user_confirmed     INTEGER NOT NULL DEFAULT 0,
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One short-lived claim per question while a server-side cloud solver is in
-- flight. The claim is committed BEFORE the paid call, preventing concurrent
-- finalize-reading requests from invoking the provider for the same problem.
-- Stale rows are reclaimed by the application after a crash/timeout.
CREATE TABLE IF NOT EXISTS solution_claims (
    question_id INTEGER PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
    claimed_at  TEXT NOT NULL DEFAULT (datetime('now'))
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
    evidence_refs_json  TEXT,
    context_hits_json   TEXT,
    explainer_json      TEXT,
    result_extras_json  TEXT,
    confidence          REAL,
    viewed_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Hot-path lookups: latest solution per question (deck/review/view), a
-- session's questions, and a document's pages. Runs on every init_db, so
-- existing DBs pick these up too.
CREATE INDEX IF NOT EXISTS idx_solutions_question ON solutions(question_id);
CREATE INDEX IF NOT EXISTS idx_questions_session  ON questions(session_id);
CREATE INDEX IF NOT EXISTS idx_pages_document     ON pages(document_id);
"""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Columns added to exam_sessions after its initial release. `CREATE TABLE IF
# NOT EXISTS` won't add columns to a pre-existing DB, so migrate them in.
_EXAM_SESSION_MIGRATIONS = (
    ("document_id", "INTEGER"),
    ("exam_type", "TEXT NOT NULL DEFAULT 'written'"),
    ("answer_format", "TEXT NOT NULL DEFAULT 'mark'"),
    ("current_page_index", "INTEGER NOT NULL DEFAULT 0"),
    ("audio_path", "TEXT"),
    ("transcript", "TEXT"),
)

# Additive result/cache metadata introduced after the original tables. Keeping
# these in a table map makes old persistent volumes upgrade in place.
_TABLE_COLUMN_MIGRATIONS = {
    "solutions": (
        ("evidence_refs_json", "TEXT"),
    ),
    "explain_views": (
        ("evidence_refs_json", "TEXT"),
        ("context_hits_json", "TEXT"),
        ("explainer_json", "TEXT"),
        ("result_extras_json", "TEXT"),
    ),
}


# Rebuild `pages` to the current schema. Used to relax the original
# `image_path TEXT NOT NULL` on databases created before 撮影しない (no
# photography) text-only pages existed — SQLite can't drop a NOT NULL in place,
# so we copy into a fresh table. This also introduces the `vision_text` column.
_PAGES_REBUILD_SQL = """
CREATE TABLE pages_new (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_index  INTEGER NOT NULL,
    image_path  TEXT,
    phash       TEXT NOT NULL DEFAULT '',
    ocr_text    TEXT,
    vision_text TEXT,
    ocr_md5     TEXT,
    summary     TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(document_id, page_index)
);
INSERT INTO pages_new
    (id, document_id, page_index, image_path, phash, ocr_text, ocr_md5, summary, created_at)
    SELECT id, document_id, page_index, image_path, phash, ocr_text, ocr_md5, summary, created_at
    FROM pages;
DROP TABLE pages;
ALTER TABLE pages_new RENAME TO pages;
"""


def _pages_image_path_not_null(conn: sqlite3.Connection) -> bool:
    """True if `pages.image_path` still carries the legacy NOT NULL constraint."""
    for _cid, name, _type, notnull, _dflt, _pk in conn.execute(
        "PRAGMA table_info(pages)"
    ):
        if name == "image_path":
            return bool(notnull)
    return False


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring an existing database up to the current schema (additive + rebuild)."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(exam_sessions)")}
    for name, decl in _EXAM_SESSION_MIGRATIONS:
        if name not in cols:
            conn.execute(f"ALTER TABLE exam_sessions ADD COLUMN {name} {decl}")

    for table, migrations in _TABLE_COLUMN_MIGRATIONS.items():
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in migrations:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

    # pages: on a legacy DB, image_path was NOT NULL — rebuild the table so
    # text-only (撮影しない) pages with image_path=NULL can be recorded. The
    # rebuild also adds vision_text; otherwise just add the column if missing.
    if _pages_image_path_not_null(conn):
        conn.executescript(_PAGES_REBUILD_SQL)
        # `_SCHEMA` created this index on the legacy table before the rebuild;
        # DROP TABLE removes it with that table. Recreate it now rather than
        # leaving the migrated DB unindexed until the *next* process start.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pages_document ON pages(document_id)"
        )
    else:
        pcols = {r[1] for r in conn.execute("PRAGMA table_info(pages)")}
        if "vision_text" not in pcols:
            conn.execute("ALTER TABLE pages ADD COLUMN vision_text TEXT")


def init_db(db_path: Path | None = None) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(_SCHEMA)
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()

"""Migrations on an existing (legacy) database.

Covers the upgrade path Codex flagged: a DB created by the pre-撮影しない schema
had `pages.image_path TEXT NOT NULL` and no `vision_text`. After init_db the
table must accept text-only pages (image_path=NULL) and have vision_text.
"""

import importlib
import sqlite3


def _make_legacy_db(path):
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
            capture_device TEXT, status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            page_index INTEGER NOT NULL,
            image_path TEXT NOT NULL,          -- legacy NOT NULL
            phash TEXT NOT NULL,
            ocr_text TEXT, ocr_md5 TEXT, summary TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(document_id, page_index)
        );
        CREATE TABLE exam_sessions (id INTEGER PRIMARY KEY, mode TEXT);
        CREATE TABLE solutions (
            id INTEGER PRIMARY KEY, question_id INTEGER,
            evidence_pages_json TEXT
        );
        CREATE TABLE explain_views (
            id INTEGER PRIMARY KEY, session_id INTEGER, page_index INTEGER,
            verdict TEXT, hud_lines_json TEXT, detail TEXT,
            evidence_pages_json TEXT, confidence REAL, viewed_at TEXT
        );
        INSERT INTO documents (title) VALUES ('legacy');
        INSERT INTO pages (document_id, page_index, image_path, phash, ocr_text)
            VALUES (1, 0, 'old.png', 'abc123', 'legacy page');
        """
    )
    conn.commit()
    conn.close()


def test_legacy_pages_image_path_becomes_nullable(tmp_path, monkeypatch):
    db_file = tmp_path / "legacy.db"
    _make_legacy_db(db_file)

    monkeypatch.setenv("ROKID_DATA_DIR", str(tmp_path))
    import app.config as config
    importlib.reload(config)
    import app.db as db
    importlib.reload(db)

    db.init_db(db_path=db_file)

    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    cols = {r[1]: r for r in conn.execute("PRAGMA table_info(pages)")}
    # image_path NOT NULL relaxed; vision_text added.
    assert cols["image_path"][3] == 0  # notnull flag cleared
    assert "vision_text" in cols
    solution_cols = {
        r[1] for r in conn.execute("PRAGMA table_info(solutions)")
    }
    assert "evidence_refs_json" in solution_cols
    explain_cols = {
        r[1] for r in conn.execute("PRAGMA table_info(explain_views)")
    }
    assert {
        "evidence_refs_json",
        "context_hits_json",
        "explainer_json",
        "result_extras_json",
    } <= explain_cols
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' "
        "AND name = 'solution_claims'"
    ).fetchone()
    # The legacy-table rebuild drops indexes attached to the old table; the
    # migration must recreate the hot-path document lookup immediately.
    indexes = {r[1] for r in conn.execute("PRAGMA index_list(pages)")}
    assert "idx_pages_document" in indexes
    # legacy row preserved
    row = conn.execute("SELECT image_path, ocr_text FROM pages WHERE id=1").fetchone()
    assert row["image_path"] == "old.png" and row["ocr_text"] == "legacy page"
    # a text-only (撮影しない) page can now be inserted with image_path=NULL
    conn.execute(
        "INSERT INTO pages (document_id, page_index, image_path, phash, ocr_text, vision_text)"
        " VALUES (1, 1, NULL, '', 'text page', '図の読み取り')"
    )
    conn.commit()
    got = conn.execute("SELECT image_path, vision_text FROM pages WHERE page_index=1").fetchone()
    assert got["image_path"] is None and got["vision_text"] == "図の読み取り"
    conn.close()

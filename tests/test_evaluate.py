"""Tests for scripts/evaluate.py — the real-device threshold-tuning tool.

This is the script the user runs against pages captured on the actual glasses
(`--db data/docscan.db`) to get HAMMING_STRONG/WEAK suggestions, so its
percentile math, suggestion logic, and both data sources are pinned offline.
"""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import matching  # noqa: E402
from app.matching import phash_hex  # noqa: E402
from scripts.evaluate import (  # noqa: E402
    _percentile,
    _suggest_thresholds,
    from_db,
    from_synthetic,
    main,
)
from tests.conftest import make_image  # noqa: E402


# --- percentile ---------------------------------------------------------------

def test_percentile_empty_is_zero():
    assert _percentile([], 0.95) == 0.0


def test_percentile_single_value():
    assert _percentile([7], 0.5) == 7


def test_percentile_interpolates():
    assert _percentile([0, 10], 0.5) == 5.0
    assert _percentile([0, 10], 0.0) == 0
    assert _percentile([0, 10], 1.0) == 10


# --- threshold suggestion -------------------------------------------------------

def test_suggest_thresholds_no_data_keeps_defaults():
    s = _suggest_thresholds([])
    assert s["hamming_strong"] == matching.HAMMING_STRONG
    assert s["hamming_weak"] == matching.HAMMING_WEAK
    assert "note" in s


def test_suggest_thresholds_from_spread():
    s = _suggest_thresholds([0, 0, 1, 2])
    assert s["hamming_strong"] >= 2
    assert s["hamming_weak"] > s["hamming_strong"]
    assert "based_on_p95_self_hamming" in s


# --- synthetic source -----------------------------------------------------------

def test_from_synthetic_self_matches_perfectly():
    report = from_synthetic(5)
    assert report["page_count"] == 5
    assert report["self_match_accuracy"] == 1.0
    assert all(r["correct"] for r in report["results"])
    assert report["source"] == {"mode": "synthetic", "n": 5}
    assert "suggested_thresholds" in report


# --- db source (the on-device tuning path) ---------------------------------------

def test_from_db_self_matches_stored_pages(tmp_path):
    db_path = tmp_path / "eval.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE pages (id INTEGER PRIMARY KEY, document_id INTEGER, "
        "page_index INTEGER, phash TEXT)"
    )
    for i, seed in enumerate((11, 42)):
        conn.execute(
            "INSERT INTO pages (id, document_id, page_index, phash) VALUES (?, 1, ?, ?)",
            (i + 1, i, phash_hex(make_image(seed=seed))),
        )
    # 撮影しない text-only page: no visual signal — skipped, not evaluated.
    conn.execute(
        "INSERT INTO pages (id, document_id, page_index, phash) VALUES (3, 1, 2, '')"
    )
    conn.commit()
    conn.close()

    report = from_db(str(db_path))
    assert report["page_count"] == 2
    assert report["self_match_accuracy"] == 1.0
    assert report["source"] == {
        "mode": "db",
        "path": str(db_path),
        "skipped_text_only_pages": 1,
    }


# --- CLI ------------------------------------------------------------------------

def test_main_writes_versioned_report(tmp_path, monkeypatch, capsys):
    out = tmp_path / "report.json"
    monkeypatch.setattr(
        sys, "argv", ["evaluate.py", "--synthetic", "2", "--out", str(out)]
    )
    assert main() == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["report_kind"] == "rokid-docscan-eval"
    assert "matcher_version" in report["versions"]
    assert set(report["current_thresholds"]) == {
        "hamming_strong", "hamming_weak", "conf_ok", "conf_low", "ocr_md5_bonus",
    }
    assert "accuracy=" in capsys.readouterr().out

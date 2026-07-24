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
    assert "based_on_p95_variant_hamming" in s


# --- synthetic source -----------------------------------------------------------

def test_from_synthetic_matches_perturbed_queries():
    report = from_synthetic(5)
    assert report["page_count"] == 5
    assert report["query_count"] == 15
    # Every variant's expected page ranks first — that is the ranking-only
    # diagnostic, not the headline accuracy.
    assert report["variant_top1_accuracy"] == 1.0
    assert all(r["ranked_first"] for r in report["results"])
    # Headline accuracy counts only usable HITs (what the live matcher would
    # actually return), so it equals the hit rate and never exceeds top1. A
    # perturbed variant that ranks first but only earns LOW_CONF must not be
    # counted as a match.
    assert report["variant_match_accuracy"] == report["variant_hit_rate"]
    assert report["variant_match_accuracy"] <= report["variant_top1_accuracy"]
    assert all(
        r["usable"] == (r["ranked_first"] and r["verdict"] == "HIT")
        for r in report["results"]
    )
    assert report["hamming_distribution"]["max"] > 0
    assert any(r["expected_hamming"] > 0 for r in report["results"])
    assert report["source"] == {
        "mode": "synthetic",
        "n": 5,
        "query_kind": "derived_image_variants",
    }
    assert "suggested_thresholds" in report


# --- db source (the on-device tuning path) ---------------------------------------

def test_from_db_matches_variants_of_stored_page_images(tmp_path):
    db_path = tmp_path / "eval.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE pages (id INTEGER PRIMARY KEY, document_id INTEGER, "
        "page_index INTEGER, phash TEXT, image_path TEXT)"
    )
    for i, seed in enumerate((11, 42)):
        path = tmp_path / f"page-{i}.png"
        image = make_image(seed=seed)
        image.save(path)
        conn.execute(
            "INSERT INTO pages (id, document_id, page_index, phash, image_path) "
            "VALUES (?, 1, ?, ?, ?)",
            (i + 1, i, phash_hex(image), str(path)),
        )
    # 撮影しない text-only page: no visual signal — skipped, not evaluated.
    conn.execute(
        "INSERT INTO pages (id, document_id, page_index, phash, image_path) "
        "VALUES (3, 1, 2, '', NULL)"
    )
    conn.commit()
    conn.close()

    report = from_db(str(db_path))
    assert report["page_count"] == 2
    assert report["query_count"] == 6
    assert report["variant_match_accuracy"] == 1.0
    assert report["variant_top1_accuracy"] == 1.0
    assert report["hamming_distribution"]["max"] > 0
    assert report["source"] == {
        "mode": "db",
        "path": str(db_path),
        "query_kind": "derived_image_variants",
        "skipped_text_only_pages": 1,
        "skipped_missing_images": 0,
    }


def test_from_db_scopes_identical_images_to_their_document(tmp_path):
    db_path = tmp_path / "eval.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE pages (id INTEGER PRIMARY KEY, document_id INTEGER, "
        "page_index INTEGER, phash TEXT, image_path TEXT)"
    )
    image = make_image(seed=23)
    image_hash = phash_hex(image)
    for page_id, document_id in ((1, 1), (2, 2)):
        path = tmp_path / f"document-{document_id}-page-0.png"
        image.save(path)
        conn.execute(
            "INSERT INTO pages (id, document_id, page_index, phash, image_path) "
            "VALUES (?, ?, 0, ?, ?)",
            (page_id, document_id, image_hash, str(path)),
        )
    conn.commit()
    conn.close()

    report = from_db(str(db_path))
    assert report["page_count"] == 2
    assert report["query_count"] == 6
    assert report["variant_match_accuracy"] == 1.0
    assert report["variant_top1_accuracy"] == 1.0
    assert {result["matched_page_id"] for result in report["results"]} == {1, 2}
    assert all(result["ranked_first"] for result in report["results"])
    assert set(report) == {
        "page_count",
        "query_count",
        "variant_match_count",
        "variant_match_accuracy",
        "variant_hit_count",
        "variant_hit_rate",
        "variant_top1_count",
        "variant_top1_accuracy",
        "self_match_hits",
        "self_match_accuracy",
        "hamming_distribution",
        "suggested_thresholds",
        "results",
        "source",
    }
    assert set(report["results"][0]) == {
        "expected_page_id",
        "page_index",
        "variant",
        "verdict",
        "matched_page_id",
        "matched_hamming",
        "expected_hamming",
        "confidence",
        "ranked_first",
        "usable",
    }


def test_from_db_keeps_missing_image_pages_as_candidates(tmp_path):
    # A stored page with a pHash but a missing image file is still ranked by the
    # live /v1/match path, so the evaluator must keep it as a candidate (only
    # skipping query generation) instead of dropping it entirely.
    db_path = tmp_path / "eval.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE pages (id INTEGER PRIMARY KEY, document_id INTEGER, "
        "page_index INTEGER, phash TEXT, image_path TEXT)"
    )
    present = tmp_path / "page-0.png"
    image = make_image(seed=11)
    image.save(present)
    conn.execute(
        "INSERT INTO pages (id, document_id, page_index, phash, image_path) "
        "VALUES (1, 1, 0, ?, ?)",
        (phash_hex(image), str(present)),
    )
    # pHash present, but the image file was never written / was removed.
    conn.execute(
        "INSERT INTO pages (id, document_id, page_index, phash, image_path) "
        "VALUES (2, 1, 1, ?, ?)",
        (phash_hex(make_image(seed=42)), str(tmp_path / "gone.png")),
    )
    conn.commit()
    conn.close()

    report = from_db(str(db_path))
    # Both pages are candidates even though only one produced queries.
    assert report["page_count"] == 2
    assert report["query_count"] == 3
    assert report["source"]["skipped_missing_images"] == 1
    # The surviving page's variants still match it as a usable HIT.
    assert report["variant_match_accuracy"] == 1.0


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

#!/usr/bin/env python3
"""Recognized-text page-matching evaluation -> JSON report.

The runtime API never accepts images. This evaluator therefore reads stored
``ocr_text``/``vision_text`` or creates synthetic text pages, then measures
exact and OCR-noise-like matching with :func:`app.matching.match_text`.
No network, credentials, camera input, or visual-media files are used.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import matching  # noqa: E402
from app.matching import Candidate, match_text, ocr_md5  # noqa: E402
from app.version import version_info  # noqa: E402


def _material(ocr_text: str | None, vision_text: str | None) -> str:
    parts = []
    if ocr_text and ocr_text.strip():
        parts.append(ocr_text.strip())
    if vision_text and vision_text.strip():
        parts.append("【図・画像の読み取り】\n" + vision_text.strip())
    return "\n\n".join(parts)


def _add_ocr_noise(text: str) -> str:
    """Deterministic light corruption resembling OCR omission/substitution."""
    if len(text) < 8:
        return text
    chars = list(text)
    positions = range(7, len(chars), 17)
    for index in positions:
        chars[index] = " " if chars[index] != " " else "・"
    return "".join(chars)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * pct
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _eval_candidates(items: list[tuple[int, int, str]]) -> dict:
    candidates = [
        Candidate(
            page_id=page_id,
            page_index=page_index,
            phash="",
            ocr_md5=ocr_md5(text),
            ocr_text=text,
        )
        for page_id, page_index, text in items
    ]
    results = []
    exact_hits = 0
    noisy_hits = 0
    noisy_similarities: list[float] = []
    for page_id, page_index, text in items:
        exact_best, exact_verdict, _ = match_text(text, candidates)
        noisy_query = _add_ocr_noise(text)
        noisy_best, noisy_verdict, _ = match_text(noisy_query, candidates)
        exact_correct = bool(
            exact_best and exact_best.page_id == page_id and exact_verdict == "HIT"
        )
        noisy_correct = bool(
            noisy_best and noisy_best.page_id == page_id and noisy_verdict == "HIT"
        )
        exact_hits += int(exact_correct)
        noisy_hits += int(noisy_correct)
        if noisy_best:
            noisy_similarities.append(noisy_best.ocr_similarity)
        results.append(
            {
                "page_id": page_id,
                "page_index": page_index,
                "exact": {
                    "verdict": exact_verdict,
                    "matched_page_id": exact_best.page_id if exact_best else None,
                    "similarity": exact_best.ocr_similarity if exact_best else 0.0,
                    "correct": exact_correct,
                },
                "noisy": {
                    "verdict": noisy_verdict,
                    "matched_page_id": noisy_best.page_id if noisy_best else None,
                    "similarity": noisy_best.ocr_similarity if noisy_best else 0.0,
                    "correct": noisy_correct,
                },
            }
        )
    total = len(items)
    p05 = _percentile(noisy_similarities, 0.05)
    return {
        "page_count": total,
        "self_match_hits": exact_hits,
        "self_match_accuracy": round(exact_hits / total, 4) if total else 0.0,
        "noisy_match_hits": noisy_hits,
        "noisy_match_accuracy": round(noisy_hits / total, 4) if total else 0.0,
        "noisy_similarity": {
            "min": min(noisy_similarities) if noisy_similarities else None,
            "p05": round(p05, 4),
            "p50": round(_percentile(noisy_similarities, 0.5), 4),
            "max": max(noisy_similarities) if noisy_similarities else None,
        },
        "threshold_note": (
            "Review real-device false positives before lowering TEXT_CONF_OK; "
            f"the synthetic noisy p05 is {p05:.4f}."
        ),
        "results": results,
    }


def from_db(db_path: str) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, page_index, ocr_text, vision_text "
            "FROM pages ORDER BY document_id, page_index"
        ).fetchall()
    finally:
        conn.close()
    items = [
        (row["id"], row["page_index"], text)
        for row in rows
        if (text := _material(row["ocr_text"], row["vision_text"]))
    ]
    report = _eval_candidates(items)
    report["source"] = {"mode": "db", "path": db_path}
    return report


def from_synthetic(count: int) -> dict:
    items = [
        (
            index + 1,
            index,
            f"第{index + 1}ページ 固有資料コード DOC-{1000 + index} "
            f"問{index + 1} 本文中の条件と数値 {index * 7 + 3} を用いて答えよ。",
        )
        for index in range(count)
    ]
    report = _eval_candidates(items)
    report["source"] = {"mode": "synthetic-text", "count": count}
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Recognized-text matching evaluation")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--db", help="path to docscan.db")
    group.add_argument("--synthetic", type=int, help="number of synthetic text pages")
    parser.add_argument("--out", help="write JSON here instead of stdout")
    args = parser.parse_args()

    report = from_db(args.db) if args.db else from_synthetic(args.synthetic)
    report = {
        "report_kind": "rokid-docscan-text-eval",
        "versions": version_info(),
        "current_thresholds": {
            "text_conf_ok": matching.TEXT_CONF_OK,
            "text_conf_low": matching.TEXT_CONF_LOW,
        },
        **report,
    }
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(rendered, encoding="utf-8")
        print(
            f"wrote {args.out} (exact={report['self_match_accuracy']}, "
            f"noisy={report['noisy_match_accuracy']})"
        )
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

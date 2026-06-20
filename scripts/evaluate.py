#!/usr/bin/env python3
"""Matching evaluation -> JSON report.

Run AFTER the user captures real sample pages (or against generated samples)
to sanity-check matching quality and get threshold suggestions before tuning.

Two modes:
  1. --db PATH     : evaluate against pages already stored in a SQLite DB.
                     For each stored page, re-match its own image and check
                     that it returns itself (self-match accuracy).
  2. --synthetic N : generate N synthetic pages, then match each -> expect HIT.

Output: a JSON report (stdout or --out FILE) with version stamps, per-page
results, hamming distribution, and suggested thresholds. No network, no creds.

Examples:
  python scripts/evaluate.py --synthetic 5 --out report.json
  ROKID_DATA_DIR=data python scripts/evaluate.py --db data/docscan.db
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

# allow running as a plain script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import matching  # noqa: E402
from app.matching import Candidate, match, phash, phash_hex  # noqa: E402
from app.version import version_info  # noqa: E402


def _percentile(values: list[int], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _suggest_thresholds(self_hammings: list[int]) -> dict:
    """Suggest HAMMING_STRONG/WEAK from the spread of correct self-matches."""
    if not self_hammings:
        return {
            "hamming_strong": matching.HAMMING_STRONG,
            "hamming_weak": matching.HAMMING_WEAK,
            "note": "no data; keeping current defaults",
        }
    p95 = _percentile(self_hammings, 0.95)
    strong = max(2, int(round(p95)) + 2)
    weak = max(strong + 6, int(round(p95)) + 10)
    return {
        "hamming_strong": strong,
        "hamming_weak": weak,
        "based_on_p95_self_hamming": round(p95, 2),
        "note": "self-matches should sit below hamming_strong",
    }


def _eval_candidates(items: list[tuple[int, int, str]]) -> dict:
    """items: list of (page_id, page_index, phash_hex). Self-match each."""
    candidates = [
        Candidate(page_id=pid, page_index=idx, phash=ph, ocr_md5=None)
        for pid, idx, ph in items
    ]
    results = []
    self_hammings = []
    hits = 0
    for pid, idx, ph in items:
        best, verdict, _ = match(ph, None, candidates)
        correct = best is not None and best.page_id == pid
        hits += int(correct and verdict == "HIT")
        if best is not None:
            self_hammings.append(best.hamming)
        results.append(
            {
                "page_id": pid,
                "page_index": idx,
                "verdict": verdict,
                "matched_page_id": best.page_id if best else None,
                "hamming": best.hamming if best else None,
                "confidence": best.confidence if best else 0.0,
                "correct": correct,
            }
        )
    total = len(items)
    return {
        "page_count": total,
        "self_match_hits": hits,
        "self_match_accuracy": round(hits / total, 4) if total else 0.0,
        "hamming_distribution": {
            "min": min(self_hammings) if self_hammings else None,
            "p50": _percentile(self_hammings, 0.5),
            "p95": _percentile(self_hammings, 0.95),
            "max": max(self_hammings) if self_hammings else None,
        },
        "suggested_thresholds": _suggest_thresholds(self_hammings),
        "results": results,
    }


def from_db(db_path: str) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, page_index, phash FROM pages ORDER BY document_id, page_index"
        ).fetchall()
    finally:
        conn.close()
    items = [(r["id"], r["page_index"], r["phash"]) for r in rows]
    report = _eval_candidates(items)
    report["source"] = {"mode": "db", "path": db_path}
    return report


def from_synthetic(n: int) -> dict:
    from PIL import Image, ImageDraw

    def make(seed: int):
        size = 256
        img = Image.new("RGB", (size, size), "white")
        d = ImageDraw.Draw(img)
        for i in range(6):
            x0 = (seed * 13 + i * 29) % size
            y0 = (seed * 17 + i * 31) % size
            x1 = (x0 + 40 + i * 7) % size
            y1 = (y0 + 30 + i * 11) % size
            d.rectangle(
                [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)],
                fill=(seed * 20 % 256, i * 40 % 256, 60),
            )
        return img

    items = []
    for i in range(n):
        img = make(seed=10 + i * 17)
        items.append((i + 1, i, phash_hex(img)))
        _ = phash(img)  # exercise int path too
    report = _eval_candidates(items)
    report["source"] = {"mode": "synthetic", "n": n}
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="Matching evaluation report")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--db", help="path to docscan.db")
    g.add_argument("--synthetic", type=int, help="number of synthetic pages")
    ap.add_argument("--out", help="write JSON here instead of stdout")
    args = ap.parse_args()

    report = from_db(args.db) if args.db else from_synthetic(args.synthetic)
    report = {
        "report_kind": "rokid-docscan-eval",
        "versions": version_info(),
        "current_thresholds": {
            "hamming_strong": matching.HAMMING_STRONG,
            "hamming_weak": matching.HAMMING_WEAK,
            "conf_ok": matching.CONF_OK,
            "conf_low": matching.CONF_LOW,
            "ocr_md5_bonus": matching.OCR_MD5_BONUS,
        },
        **report,
    }
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out} (accuracy={report['self_match_accuracy']})")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

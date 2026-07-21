#!/usr/bin/env python3
"""Matching robustness evaluation -> JSON report.

Run AFTER the user captures real sample pages (or against generated samples)
to sanity-check matching quality and get threshold suggestions before tuning.

Two modes:
  1. --db PATH     : load each stored page image, derive deterministic
                     crop/rotation/compression variants, and match those
                     variants against the stored pHash index.
  2. --synthetic N : generate N synthetic pages and evaluate the same variants.

The variants are an offline robustness proxy, not a substitute for independent
real-device recaptures. Unlike the old exact self-match, however, they exercise
non-identical query images and produce a usable Hamming-distance spread.

Output: a JSON report (stdout or --out FILE) with version stamps, per-page
results, hamming distribution, and suggested thresholds. No network, no creds.

Examples:
  python scripts/evaluate.py --synthetic 5 --out report.json
  ROKID_DATA_DIR=data python scripts/evaluate.py --db data/docscan.db
"""

from __future__ import annotations

import argparse
import io
import json
import sqlite3
import sys
from pathlib import Path

from PIL import Image

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


def _suggest_thresholds(variant_hammings: list[int]) -> dict:
    """Suggest HAMMING_STRONG/WEAK from expected-page variant distances."""
    if not variant_hammings:
        return {
            "hamming_strong": matching.HAMMING_STRONG,
            "hamming_weak": matching.HAMMING_WEAK,
            "note": "no data; keeping current defaults",
        }
    p95 = _percentile(variant_hammings, 0.95)
    strong = max(2, int(round(p95)) + 2)
    weak = max(strong + 6, int(round(p95)) + 10)
    return {
        "hamming_strong": strong,
        "hamming_weak": weak,
        "based_on_p95_variant_hamming": round(p95, 2),
        "note": "derived variants should sit below hamming_strong",
    }


def _query_variants(image: Image.Image) -> list[tuple[str, Image.Image]]:
    """Return deterministic, non-identical recapture approximations."""
    image = image.convert("RGB")
    width, height = image.size
    margin = min(
        max(1, round(min(width, height) * 0.02)),
        max(0, (min(width, height) - 1) // 2),
    )
    cropped = (
        image.crop((margin, margin, width - margin, height - margin)).resize(
            (width, height), Image.Resampling.LANCZOS
        )
        if margin
        else image.copy()
    )
    rotated = image.rotate(
        1.25,
        resample=Image.Resampling.BICUBIC,
        expand=False,
        fillcolor="white",
    )
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=70, optimize=False)
    buf.seek(0)
    with Image.open(buf) as jpeg:
        compressed = jpeg.convert("RGB").copy()
    return [
        ("center_crop_2pct", cropped),
        ("rotate_1_25deg", rotated),
        ("jpeg_quality_70", compressed),
    ]


def _eval_candidates(
    items: list[tuple[int, int, str]],
    queries: list[tuple[int, str, str]],
) -> dict:
    """Match (expected_page_id, variant_name, pHash) queries to candidates."""
    candidates = [
        Candidate(page_id=pid, page_index=idx, phash=ph, ocr_md5=None)
        for pid, idx, ph in items
    ]
    candidate_hashes = {pid: ph for pid, _idx, ph in items}
    candidate_indexes = {pid: idx for pid, idx, _ph in items}
    results = []
    variant_hammings = []
    matches = 0
    hits = 0
    for expected_pid, variant, query_hash in queries:
        best, verdict, _ = match(query_hash, None, candidates)
        correct = best is not None and best.page_id == expected_pid
        matches += int(correct)
        hits += int(correct and verdict == "HIT")
        expected_hamming = matching.hamming(
            query_hash, candidate_hashes[expected_pid]
        )
        variant_hammings.append(expected_hamming)
        results.append(
            {
                "expected_page_id": expected_pid,
                "page_index": candidate_indexes[expected_pid],
                "variant": variant,
                "verdict": verdict,
                "matched_page_id": best.page_id if best else None,
                "matched_hamming": best.hamming if best else None,
                "expected_hamming": expected_hamming,
                "confidence": best.confidence if best else 0.0,
                "correct": correct,
            }
        )
    total = len(queries)
    accuracy = round(matches / total, 4) if total else 0.0
    hit_rate = round(hits / total, 4) if total else 0.0
    return {
        "page_count": len(items),
        "query_count": total,
        "variant_match_count": matches,
        "variant_match_accuracy": accuracy,
        "variant_hit_count": hits,
        "variant_hit_rate": hit_rate,
        # Kept as compatibility aliases for existing report consumers. These
        # now refer to perturbed variants, never exact source hashes.
        "self_match_hits": hits,
        "self_match_accuracy": hit_rate,
        "hamming_distribution": {
            "min": min(variant_hammings) if variant_hammings else None,
            "p50": _percentile(variant_hammings, 0.5),
            "p95": _percentile(variant_hammings, 0.95),
            "max": max(variant_hammings) if variant_hammings else None,
        },
        "suggested_thresholds": _suggest_thresholds(variant_hammings),
        "results": results,
    }


def from_db(db_path: str) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        # This tool tunes the image-compat pHash thresholds; 撮影しない
        # text-only pages (phash='') carry no visual signal to evaluate.
        rows = conn.execute(
            "SELECT id, page_index, phash, image_path FROM pages WHERE phash != '' "
            "ORDER BY document_id, page_index"
        ).fetchall()
        skipped = conn.execute(
            "SELECT COUNT(*) FROM pages WHERE phash = ''"
        ).fetchone()[0]
    finally:
        conn.close()
    items = []
    queries = []
    skipped_missing_images = 0
    for row in rows:
        path = Path(row["image_path"] or "")
        if not path.is_file():
            skipped_missing_images += 1
            continue
        try:
            with Image.open(path) as source:
                image = source.convert("RGB").copy()
        except (OSError, ValueError):
            skipped_missing_images += 1
            continue
        items.append((row["id"], row["page_index"], row["phash"]))
        queries.extend(
            (row["id"], name, phash_hex(variant))
            for name, variant in _query_variants(image)
        )
    report = _eval_candidates(items, queries)
    report["source"] = {
        "mode": "db",
        "path": db_path,
        "query_kind": "derived_image_variants",
        "skipped_text_only_pages": skipped,
        "skipped_missing_images": skipped_missing_images,
    }
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
    queries = []
    for i in range(n):
        img = make(seed=10 + i * 17)
        items.append((i + 1, i, phash_hex(img)))
        queries.extend(
            (i + 1, name, phash_hex(variant))
            for name, variant in _query_variants(img)
        )
        _ = phash(img)  # exercise int path too
    report = _eval_candidates(items, queries)
    report["source"] = {
        "mode": "synthetic",
        "n": n,
        "query_kind": "derived_image_variants",
    }
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
        print(f"wrote {args.out} (accuracy={report['variant_match_accuracy']})")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

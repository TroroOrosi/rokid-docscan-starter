"""PC-only reference comparisons; never selects a capture mode or approves quality."""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

MAX_BYTES = 8 * 1024 * 1024


def compare_text(reference: str, recognized: str) -> dict:
    """Count NFC code-point edits for one labelled region, without a quality verdict.

    Preserve spaces, punctuation, case and math symbols. The caller owns the
    transcription and reading order; never sort or deduplicate OCR to fit it.
    """
    if (not isinstance(reference, str) or not isinstance(recognized, str)
            or not reference.strip() or max(len(reference), len(recognized)) > 2048):
        raise ValueError("text comparison requires a reference and at most 2048 characters per input")
    reference, recognized = (unicodedata.normalize("NFC", text) for text in (reference, recognized))
    if max(len(reference), len(recognized)) > 2048:
        raise ValueError("normalized text exceeds 2048 characters")
    # ponytail: quadratic work bounded to short regions; use a vetted edit-distance
    # library if whole-document comparisons become necessary.
    row = list(range(len(recognized) + 1))
    for i, expected in enumerate(reference, 1):
        current = [i]
        for j, actual in enumerate(recognized, 1):
            current.append(min(current[-1] + 1, row[j] + 1,
                               row[j - 1] + (expected != actual)))
        row = current
    return {"errors": row[-1], "reference_characters": len(reference),
            "recognized_characters": len(recognized),
            "error_rate": row[-1] / len(reference), "normalization": "NFC"}


def evaluate_trials(records: object) -> dict:
    if not isinstance(records, list) or not 1 <= len(records) <= 10000:
        raise ValueError("records must be a JSON array of 1..10000 trials")
    samples, comparisons = set(), set()
    document_splits, comparison_splits, image_splits = {}, {}, {}
    layouts = {layout: {"count": 0, "unusable_count": 0, "false_accept_count": 0,
                        "usable_count": 0, "usable_hold": 0, "usable_retake": 0}
               for layout in ("single", "spread")}
    pairs = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("each trial must be an object")
        for field in ("sample_id", "document_id", "comparison_id"):
            value = record.get(field)
            if not isinstance(value, str) or not value.strip() or not 1 <= len(value) <= 128:
                raise ValueError(f"invalid {field}")
        split, layout, decision = (record.get(field) for field in ("split", "layout", "decision"))
        if (split not in ("calibration", "validation", "test") or layout not in ("single", "spread")
                or decision not in ("eligible", "hold", "retake")
                or type(record.get("reference_usable")) is not bool):
            raise ValueError("invalid split, layout, decision, or reference label")
        sources = record.get("source_sha256")
        if (not isinstance(sources, list) or not 1 <= len(sources) <= 8
                or any(not isinstance(s, str) or re.fullmatch(r"[0-9a-f]{64}", s) is None for s in sources)
                or len(set(sources)) != len(sources)):
            raise ValueError("source_sha256 must contain 1..8 distinct SHA-256 values")
        sample, document, comparison = (record[field] for field in ("sample_id", "document_id", "comparison_id"))
        key = (document, comparison, layout)
        if sample in samples or key in comparisons:
            raise ValueError("duplicate sample or document/comparison/layout")
        samples.add(sample)
        comparisons.add(key)
        for mapping, values in ((document_splits, [document]), (comparison_splits, [comparison]),
                                (image_splits, sources)):
            for value in values:
                if mapping.setdefault(value, split) != split:
                    raise ValueError("document, comparison, or source image leaks across splits")
        if split != "test":
            continue
        counts = layouts[layout]
        counts["count"] += 1
        if record["reference_usable"]:
            counts["usable_count"] += 1
            if decision in ("hold", "retake"):
                counts["usable_" + decision] += 1
        else:
            counts["unusable_count"] += 1
            counts["false_accept_count"] += decision == "eligible"
        pairs.setdefault((document, comparison), set()).add(layout)
    for counts in layouts.values():
        counts["false_accept_rate"] = (counts["false_accept_count"] / counts["unusable_count"]
                                       if counts["unusable_count"] else None)
    return {"schema": 1, "test_records": sum(v["count"] for v in layouts.values()),
            "layouts": layouts, "paired_comparisons": sum(len(v) == 2 for v in pairs.values()),
            "unpaired_comparisons": sum(len(v) == 1 for v in pairs.values()),
            "winner": None, "profile_approved": False,
            "reference_basis": "caller_supplied_reference_labels_not_model_self_grading"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("records", type=Path)
    args = parser.parse_args(argv)
    try:
        with args.records.open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("trial file exceeds 8 MiB")
        result = evaluate_trials(json.loads(data))
    except (ValueError, OSError) as error:
        parser.exit(2, f"capture evaluation failed: {error}\n")
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

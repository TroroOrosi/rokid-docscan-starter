#!/usr/bin/env python3
"""Validate preparation cases and score supplied results; never call AI or devices."""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from collections import Counter
from pathlib import Path

DEFAULT_PACK = Path(__file__).resolve().parents[1] / "tests/fixtures/fast_scan/cases.json"


def _unique_ids(rows: list[dict], field: str, label: str) -> set[str]:
    values = [row[field] for row in rows]
    if not all(isinstance(value, str) and value.strip() for value in values):
        raise ValueError(f"invalid {label} ID")
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {label}")
    return set(values)


def validate_pack(pack: dict) -> dict:
    if pack["kind"] != "rokid-fast-scan-preflight-v1" or pack["revision"] < 1:
        raise ValueError("unsupported pack kind or revision")
    if pack["evidence"] != "synthetic_design_cases":
        raise ValueError("this preparation pack is not a hardware evidence ledger")
    cases = pack["cases"]
    if not cases:
        raise ValueError("empty case pack")
    _unique_ids(cases, "id", "case")
    questions = 0
    for case in cases:
        if case["mode"] not in {"normal", "listening"}:
            raise ValueError("unknown mode")
        pages, audio = case["input"]["pages"], case["input"]["audio"]
        if not pages or not case["expected"]:
            raise ValueError("pages and expected questions are required")
        if case["mode"] == "normal" and audio:
            raise ValueError("normal mode must not require audio")
        page_ids = _unique_ids(pages, "id", "page")
        audio_ids = _unique_ids(audio, "id", "audio")
        _unique_ids(case["expected"], "question_id", "question")
        for question in case["expected"]:
            if not set(question["page_ids"]) <= page_ids or not set(question["audio_ids"]) <= audio_ids:
                raise ValueError("unknown material reference")
            status, scoring = question["status"], question["scoring"]
            if status == "answered":
                if not question["answer"].strip() or scoring not in {"exact", "manual_rubric"}:
                    raise ValueError("answered question requires an answer and scoring rule")
                if scoring == "manual_rubric" and not question.get("rubric"):
                    raise ValueError("manual question requires a rubric")
            elif status == "needs_material":
                if question["answer"] or scoring != "status" or not question.get("missing"):
                    raise ValueError("missing material requires an empty answer and reason")
            else:
                raise ValueError("unknown expected status")
            questions += 1
    return {
        "report_kind": "fast-scan-pack-check",
        "pack_revision": pack["revision"],
        "cases": len(cases),
        "questions": questions,
        "modes": dict(Counter(case["mode"] for case in cases)),
        "evidence": pack["evidence"],
        "media_status": pack["media_status"],
        "hardware_verified": False,
        "ai_executed": False,
    }


def _normalized(answer: str) -> str:
    # Preserve numbers, units, negation and internal whitespace. No substring match.
    return unicodedata.normalize("NFC", answer).strip()


def evaluate_results(pack: dict, submission: dict) -> dict:
    summary = validate_pack(pack)
    if submission["pack_revision"] != pack["revision"]:
        raise ValueError("pack revision mismatch")
    expected = {
        (case["id"], question["question_id"]): question
        for case in pack["cases"]
        for question in case["expected"]
    }
    received = {}
    for row in submission["results"]:
        key = (row["case_id"], row["question_id"])
        if key not in expected:
            raise ValueError("unknown question in supplied results")
        if key in received:
            raise ValueError("duplicate result")
        if row["status"] not in {"answered", "needs_material", "failed"}:
            raise ValueError("unknown result status")
        if not isinstance(row["answer"], str):
            raise ValueError("answer must be a string")
        if row["status"] == "answered" and not row["answer"].strip():
            raise ValueError("answered result requires text")
        if row["status"] != "answered" and row["answer"]:
            raise ValueError("non-answer result requires an empty answer")
        received[key] = row

    correct = manual = answered = 0
    details = []
    objective = sum(question["scoring"] != "manual_rubric" for question in expected.values())
    for key, question in expected.items():
        row = received.get(key)
        verdict = "missing"
        if row:
            answered += row["status"] == "answered"
            if question["scoring"] == "manual_rubric" and row["status"] == "answered":
                verdict = "manual_review"
                manual += 1
            else:
                matches = row["status"] == question["status"]
                if question["scoring"] == "exact":
                    allowed = [question["answer"], *question.get("accepted_answers", [])]
                    matches = matches and _normalized(row["answer"]) in {
                        _normalized(value) for value in allowed
                    }
                verdict = "match" if matches else "mismatch"
                correct += matches
        details.append({"case_id": key[0], "question_id": key[1], "verdict": verdict})

    return {
        **summary,
        "report_kind": "fast-scan-supplied-results",
        "result_provenance": "supplied_unverified",
        "metric_scope": "synthetic_contract_cases_including_missing_material_checks",
        "total_questions": len(expected),
        "objective_expected": objective,
        "objective_correct": correct,
        "objective_match_rate": correct / objective if objective else None,
        "answered_questions": answered,
        "missing_results": len(expected) - len(received),
        "manual_review_pending": manual,
        "by_question": details,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--results", type=Path, help="supplied JSON; no inference is run")
    parser.add_argument("--out", type=Path, help="save the JSON report")
    args = parser.parse_args()
    try:
        pack = json.loads(args.pack.read_text(encoding="utf-8"))
        if args.results:
            submission = json.loads(args.results.read_text(encoding="utf-8"))
            report = evaluate_results(pack, submission)
        else:
            report = validate_pack(pack)
        output = json.dumps(report, ensure_ascii=False, indent=2)
        if args.out:
            args.out.write_text(output + "\n", encoding="utf-8")
        else:
            sys.stdout.reconfigure(encoding="utf-8")
            print(output)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"preparation check failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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

CAPTURE_KIND = "rokid-fast-scan-preflight-v1"
ANSWER_FORM_KIND = "rokid-answer-form-eval-v1"

# Written-answer shapes the reader has to carry without dropping content.
ANSWER_FORMS = {
    "choice",
    "multi_field",
    "worked_steps",
    "proof",
    "word_limit",
    "english_composition",
    "audio_dependent",
    "figure",
}
# Forms a human must score: a final value alone is never full credit.
RUBRIC_FORMS = {"worked_steps", "proof", "word_limit", "english_composition", "figure"}
USAGE_BUCKETS = {"tuning", "holdout"}
# A published statement of intent or an official answer key is neither of these.
RUBRIC_ORIGINS = {"human_checked_requirements", "drafted_pending_review"}


def _unique_ids(rows: list[dict], field: str, label: str) -> set[str]:
    values = [row[field] for row in rows]
    if not all(isinstance(value, str) and value.strip() for value in values):
        raise ValueError(f"invalid {label} ID")
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {label}")
    return set(values)


def _check_answer_form(case: dict, question: dict, seen_sources: set[tuple]) -> None:
    """Answer-form packs carry the written shape and where the format came from."""
    form = question["form"]
    if form not in ANSWER_FORMS:
        raise ValueError("unknown answer form")
    if form == "audio_dependent" and (case["mode"] != "listening" or not question["audio_ids"]):
        raise ValueError("an audio-dependent question needs listening mode and audio")

    source = question["source"]
    fields = source["field_ids"]
    if (
        not isinstance(source["exam"], str)
        or not source["exam"].strip()
        or not isinstance(source["year"], int)
        or not 2000 <= source["year"] <= 2100
        or not str(source["section"]).strip()
        or not str(source["item"]).strip()
        or not isinstance(fields, list)
        or not fields
        or not all(isinstance(value, str) and value.strip() for value in fields)
        or len(fields) != len(set(fields))
    ):
        raise ValueError("invalid answer-sheet source reference")
    # Reproducing the original wording is out of scope for this repository.
    if source["text_origin"] not in {"synthetic", "paraphrased"}:
        raise ValueError("case text must declare a synthetic or paraphrased origin")
    key = (source["exam"], source["year"], source["section"], source["item"], tuple(fields))
    if key in seen_sources:
        raise ValueError("duplicate answer-sheet field reference")
    seen_sources.add(key)
    if form == "multi_field" and len(fields) < 2:
        raise ValueError("a multi-field question needs more than one answer field")

    if question["status"] != "answered":
        return
    if form in RUBRIC_FORMS and question["scoring"] != "manual_rubric":
        raise ValueError("this written form cannot be scored by exact match")
    if question["scoring"] == "manual_rubric":
        # A published statement of intent is not a model answer or a mark scheme.
        if question["rubric_origin"] not in RUBRIC_ORIGINS:
            raise ValueError("a rubric must come from human-checked requirements")
        if not all(isinstance(item, str) and item.strip() for item in question["rubric"]):
            raise ValueError("invalid rubric requirement")
    if form == "word_limit" and not (
        isinstance(question["limit_chars"], int) and question["limit_chars"] >= 1
    ):
        raise ValueError("a length-limited answer needs its limit")
    if form == "english_composition":
        low, high = question["word_range"]
        if question["language"] != "en" or not 1 <= low <= high:
            raise ValueError("an English composition needs a language and a word range")
    if form == "figure" and not question["figure_elements"]:
        raise ValueError("a figure answer needs verifiable elements")


def validate_pack(pack: dict) -> dict:
    if pack["kind"] not in {CAPTURE_KIND, ANSWER_FORM_KIND} or pack["revision"] < 1:
        raise ValueError("unsupported pack kind or revision")
    if pack["evidence"] != "synthetic_design_cases":
        raise ValueError("this preparation pack is not a hardware evidence ledger")
    cases = pack["cases"]
    if not cases:
        raise ValueError("empty case pack")
    _unique_ids(cases, "id", "case")
    answer_forms = pack["kind"] == ANSWER_FORM_KIND
    seen_sources: set[tuple] = set()
    forms: Counter = Counter()
    usage: Counter = Counter()
    rubrics: Counter = Counter()
    questions = 0
    for case in cases:
        if case["mode"] not in {"normal", "listening"}:
            raise ValueError("unknown mode")
        if answer_forms and case["usage"] not in USAGE_BUCKETS:
            raise ValueError("a case must be marked for tuning or held out")
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
            if answer_forms:
                _check_answer_form(case, question, seen_sources)
                forms[question["form"]] += 1
                usage[case["usage"]] += 1
                rubrics[question.get("rubric_origin", "none")] += 1
            questions += 1
    if answer_forms and (missing_forms := sorted(ANSWER_FORMS - set(forms))):
        raise ValueError(f"answer forms with no case: {', '.join(missing_forms)}")
    if answer_forms and sorted(usage) != sorted(USAGE_BUCKETS):
        raise ValueError("both a tuning and a held-out bucket are required")
    report = {
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
    if answer_forms:
        report["report_kind"] = "answer-form-pack-check"
        report["by_form"] = dict(sorted(forms.items()))
        report["by_usage"] = dict(sorted(usage.items()))
        report["rubric_origins"] = dict(sorted(rubrics.items()))
        report["rubrics_pending_review"] = rubrics["drafted_pending_review"]
        report["sources"] = dict(
            sorted(
                Counter(
                    f"{question['source']['exam']}:{question['source']['year']}"
                    for case in cases
                    for question in case["expected"]
                ).items()
            )
        )
    return report


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
    # Tuning cases and held-out cases are never averaged into one number.
    usage_of = {
        (case["id"], question["question_id"]): case.get("usage")
        for case in pack["cases"]
        for question in case["expected"]
    }
    buckets: dict[str, Counter] = {}
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
        if bucket := usage_of[key]:
            counts = buckets.setdefault(bucket, Counter())
            counts["questions"] += 1
            counts[verdict] += 1
            if question["scoring"] != "manual_rubric":
                counts["objective"] += 1
                counts["objective_correct"] += verdict == "match"

    by_usage = {
        name: {
            **dict(sorted(counts.items())),
            "objective_match_rate": (
                counts["objective_correct"] / counts["objective"] if counts["objective"] else None
            ),
        }
        for name, counts in sorted(buckets.items())
    }
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
        **({"by_usage_results": by_usage} if by_usage else {}),
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

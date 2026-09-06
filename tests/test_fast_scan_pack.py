"""Preparation data must not masquerade as hardware or AI accuracy evidence."""

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.eval_fast_scan import evaluate_results, validate_pack


ROOT = Path(__file__).resolve().parents[1]
PACK_PATH = ROOT / "tests/fixtures/fast_scan/cases.json"


def _pack():
    return json.loads(PACK_PATH.read_text(encoding="utf-8"))


def _submission(*rows):
    return {"pack_revision": 1, "results": list(rows)}


def _result(case_id, question_id, answer, status="answered"):
    return {
        "case_id": case_id,
        "question_id": question_id,
        "status": status,
        "answer": answer,
    }


def test_pack_contains_both_modes_and_declares_missing_real_media():
    summary = validate_pack(_pack())
    assert summary["cases"] == 14
    assert summary["questions"] == 18
    assert summary["modes"] == {"normal": 6, "listening": 8}
    assert summary["evidence"] == "synthetic_design_cases"
    assert summary["hardware_verified"] is False


@pytest.mark.parametrize("field,bad_id", [("page_ids", "P99"), ("audio_ids", "A99")])
def test_unknown_material_reference_is_rejected(field, bad_id):
    pack = _pack()
    pack["cases"][0]["expected"][0][field] = [bad_id]
    with pytest.raises(ValueError, match="material reference"):
        validate_pack(pack)


def test_duplicate_case_or_question_is_rejected():
    pack = _pack()
    pack["cases"].append(deepcopy(pack["cases"][0]))
    with pytest.raises(ValueError, match="duplicate case"):
        validate_pack(pack)
    pack = _pack()
    pack["cases"][0]["expected"].append(deepcopy(pack["cases"][0]["expected"][0]))
    with pytest.raises(ValueError, match="duplicate question"):
        validate_pack(pack)


def test_contrast_pair_changes_audio_and_answer_but_keeps_the_same_paper():
    a, b = [case for case in _pack()["cases"] if case.get("contrast_group") == "timetable"]
    assert a["input"]["pages"] == b["input"]["pages"]
    assert a["input"]["audio"] != b["input"]["audio"]
    assert a["expected"][0]["answer"] != b["expected"][0]["answer"]


def test_wrong_number_is_not_accepted_as_a_substring_match():
    report = evaluate_results(_pack(), _submission(_result("N03", "第1章.Q1", "40")))
    assert report["objective_correct"] == 0
    assert report["objective_match_rate"] == 0
    assert report["missing_results"] == 17


def test_unanswered_items_stay_in_the_denominator():
    report = evaluate_results(_pack(), _submission(_result("N01", "Q1", "36 cm²")))
    assert report["objective_correct"] == 1
    assert report["objective_expected"] == 17
    assert report["objective_match_rate"] == pytest.approx(1 / 17)
    assert report["answered_questions"] == 1
    assert report["total_questions"] == 18


def test_long_proof_requires_manual_review_instead_of_automatic_full_credit():
    case = next(case for case in _pack()["cases"] if case["id"] == "N04")
    proof = case["expected"][0]["answer"]
    assert len(proof) > 64
    report = evaluate_results(_pack(), _submission(_result("N04", "Q1", proof[:64])))
    assert report["objective_correct"] == 0
    assert report["manual_review_pending"] == 1
    proof_result = next(row for row in report["by_question"] if row["case_id"] == "N04")
    assert proof_result["verdict"] == "manual_review"


def test_missing_audio_is_an_explicit_state_not_an_invented_answer():
    report = evaluate_results(
        _pack(), _submission(_result("L06", "Q1", "", status="needs_material"))
    )
    assert report["objective_correct"] == 1
    assert report["answered_questions"] == 0


@pytest.mark.parametrize(
    "submission,match",
    [
        ({"pack_revision": 99, "results": []}, "revision"),
        (_submission(_result("unknown", "Q1", "x")), "unknown question"),
        (_submission(_result("N01", "Q1", "x"), _result("N01", "Q1", "x")), "duplicate result"),
        (_submission(_result("L06", "Q1", "A", status="needs_material")), "empty answer"),
    ],
)
def test_inconsistent_results_are_rejected(submission, match):
    with pytest.raises(ValueError, match=match):
        evaluate_results(_pack(), submission)


def test_check_command_runs_without_device_credentials_or_ai(tmp_path):
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/eval_fast_scan.py"), "--pack", str(PACK_PATH)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    report = json.loads(completed.stdout)
    assert report["report_kind"] == "fast-scan-pack-check"
    assert report["hardware_verified"] is False
    assert "objective_match_rate" not in report

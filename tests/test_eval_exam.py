import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.eval_exam import _synthetic, run_eval  # noqa: E402


def test_run_eval_reports_metrics_for_local():
    samples = _synthetic(4)
    report = run_eval(samples, ["local"])
    assert report["report_kind"] == "rokid-exam-eval"
    assert "versions" in report
    metrics = report["by_solver"]["local"]["metrics"]
    assert metrics["sample_count"] == 4
    # Synthetic samples are choice questions, so the placeholder always answers
    # and the HUD stays within 3 lines.
    assert metrics["answer_rate"] == 1.0
    assert metrics["hud_within_3_lines_rate"] == 1.0
    # No expected_answer in synthetic samples -> accuracy is not scored.
    assert metrics["answer_accuracy"] is None


def test_run_eval_scores_accuracy_when_expected_present():
    samples = [
        {"ocr_text": "問1 計算せよ", "choices": ["A", "B"], "expected_answer": "Z"},
    ]
    report = run_eval(samples, ["local"])
    metrics = report["by_solver"]["local"]["metrics"]
    assert metrics["scored_against_expected"] == 1
    assert metrics["answer_accuracy"] is not None


def test_run_eval_handles_empty_samples():
    report = run_eval([], ["local"])
    assert report["by_solver"]["local"]["metrics"] == {}

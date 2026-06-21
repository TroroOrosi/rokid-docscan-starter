from app.overlay import build_overlay
from app.solvers import SolveResult


def test_overlay_targets_answer_box_in_normalized_range():
    box = {"x": 0.55, "y": 0.72, "w": 0.4, "h": 0.22}
    ov = build_overlay(SolveResult(answer="B: 青"), answer_box=box)
    assert ov["items"]
    item = ov["items"][0]
    assert item["kind"] == "answer_no"
    assert item["box"] == box
    for k in ("x", "y", "w", "h"):
        assert 0.0 <= item["box"][k] <= 1.0


def test_overlay_empty_without_box():
    ov = build_overlay(SolveResult(answer="B"), answer_box=None)
    assert ov["items"] == []


def test_overlay_locked_returns_no_items():
    box = {"x": 0.1, "y": 0.1, "w": 0.1, "h": 0.1}
    ov = build_overlay(SolveResult(answer="B"), answer_box=box, locked=True)
    assert ov["items"] == []
    assert ov["locked"] is True

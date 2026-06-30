from app.glasses_view import STAGES, build_glasses_view, build_locked_view
from app.solvers import SolveResult


def _sol(**kw):
    base = dict(answer="B: 青", rationale="条件②より", cautions="参考値",
                solution_steps=["手順1", "手順2"], answer_confidence=0.8)
    base.update(kw)
    return SolveResult(**base)


def test_view_has_at_most_three_lines():
    """Each page in the paginated view must have <= _MAX_LINES (3) lines.

    Previously this test assumed server-side 24-char splitting would produce
    multiple physical lines per logical line.  Since _wrap() no longer splits
    on character count (client renderer is responsible for reflow), each
    logical line stays as one element.  The invariant is still that every
    *page* returned by _paginate() contains at most _MAX_LINES entries.
    """
    for stage in STAGES:
        v = build_glasses_view(_sol(), stage=stage)
        assert len(v["lines"]) <= 3


def test_view_has_no_audio_or_animation_fields():
    v = build_glasses_view(_sol())
    # Silent contract: payload must not carry sound/animation directives.
    for forbidden in ("sound", "audio", "flash", "animation", "blink"):
        assert forbidden not in v


def test_long_text_is_paginated():
    """Pagination is driven by the number of logical lines, not char count.

    _wrap() no longer splits a single long string into multiple lines;
    it returns the string as-is (one element).  Pagination to total_pages > 1
    therefore requires that _stage_lines() produces more than _MAX_LINES (3)
    logical lines.  The 'solution' stage returns [header] + solution_steps,
    so passing many steps guarantees multi-page output.
    """
    many_steps = [f"手順{i}" for i in range(10)]  # 10 steps -> 11 lines -> 4 pages
    sol = _sol(solution_steps=many_steps)
    v0 = build_glasses_view(sol, stage="solution", page=0)
    assert v0["total_pages"] > 1
    assert v0["nav"]["next"] == 1
    last = build_glasses_view(sol, stage="solution", page=v0["total_pages"] - 1)
    assert last["nav"]["next"] is None


def test_answer_stage_shows_confidence_symbol_and_locator():
    v = build_glasses_view(
        _sol(answer_confidence=0.9),
        stage="answer",
        question_no="問3",
        page_number=2,
        answer_box={"x": 0.6, "y": 0.8, "w": 0.3, "h": 0.1},
    )
    joined = " ".join(v["lines"])
    assert "★★★" in joined
    assert v["locator"].startswith("解答欄")


def test_voice_toggle_changes_hint():
    on = build_glasses_view(_sol(), voice_enabled=True)["nav"]["hint"]
    off = build_glasses_view(_sol(), voice_enabled=False)["nav"]["hint"]
    assert on != off


def test_locked_view_never_reveals_answer():
    v = build_locked_view()
    assert v["locked"] is True
    assert all("青" not in ln for ln in v["lines"])

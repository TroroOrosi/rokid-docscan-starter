from app.explainer import ExplainResult
from app.glasses_view import (
    STAGES,
    _split_sentences,
    build_explain_view,
    build_glasses_view,
    build_locked_view,
    build_reading_done_ack,
    build_review_view,
)
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


def test_voice_toggle_does_not_override_phone_control_hint():
    on = build_glasses_view(_sol(), voice_enabled=True)["nav"]["hint"]
    off = build_glasses_view(_sol(), voice_enabled=False)["nav"]["hint"]
    assert on == off == "操作はスマホ"


def test_locked_view_never_reveals_answer():
    v = build_locked_view()
    assert v["locked"] is True
    assert all("青" not in ln for ln in v["lines"])


# --- Q1 supplement: long prose splits into sentences and paginates -----------

def test_split_sentences_on_terminators():
    parts = _split_sentences("第一文。第二文！第三文？")
    assert parts == ["第一文。", "第二文！", "第三文？"]
    # No terminator -> single line; empty -> empty list.
    assert _split_sentences("見出しだけ") == ["見出しだけ"]
    assert _split_sentences("") == []


def test_long_rationale_paginates_by_sentence():
    """A multi-sentence rationale becomes multiple 3-line teleprompter pages."""
    rationale = "".join(f"根拠文{i}。" for i in range(8))  # 8 sentences
    sol = _sol(rationale=rationale)
    v0 = build_glasses_view(sol, stage="rationale", page=0)
    assert v0["total_pages"] > 1
    assert len(v0["lines"]) <= 3
    last = build_glasses_view(sol, stage="rationale", page=v0["total_pages"] - 1)
    assert last["nav"]["next"] is None


def test_evidence_labels_are_one_based_and_document_qualified():
    sol = _sol(
        evidence_pages=[1, 3],
        evidence_refs=[
            {"document_id": 7, "page_number": 1},
            {"document_id": 9, "page_number": 3},
        ],
    )
    joined = "\n".join(build_glasses_view(sol, stage="rationale")["lines"])
    assert "D7:P01,D9:P03" in joined
    assert "P00" not in joined


def test_legacy_zero_based_evidence_is_shifted_only_for_display():
    sol = _sol(
        evidence_pages=[0, 2],
        extras={"_evidence_pages_base": 0},
    )
    joined = "\n".join(build_glasses_view(sol, stage="rationale")["lines"])
    assert "P01,P03" in joined
    assert "P00" not in joined
    # The API v1 compatibility value remains untouched.
    assert sol.evidence_pages == [0, 2]


def test_explain_detail_paginates_by_sentence():
    """explain-mode long detail paginates into >1 view page (max 3 lines each)."""
    detail = "".join(f"詳細文{i}。" for i in range(8))
    result = ExplainResult(lines=["a", "b", "c"], detail=detail, confidence=0.7)
    v0 = build_explain_view(result, stage="detail", view_page=0)
    assert v0["total_view_pages"] > 1
    assert len(v0["lines"]) <= 3
    assert v0["nav"]["next_view_page"] == 1


# --- review deck view (phase 3 閲覧: merged single stream, no stages) ---------


def _all_review_lines(sol, **kw):
    first = build_review_view(sol, index=0, problem_count=1, **kw)
    lines = []
    for vp in range(first["total_view_pages"]):
        lines += build_review_view(sol, index=0, problem_count=1, view_page=vp, **kw)[
            "lines"
        ]
    return lines


def test_review_view_merges_all_sections_in_one_stream():
    joined = "\n".join(_all_review_lines(_sol(), problem_no="問2"))
    # One stream, ordered: 答え → 解法 → 根拠 → 注意 (no stage cycling).
    for part in ("答え: B: 青", "解法", "手順1", "根拠", "条件②より", "注意", "参考値"):
        assert part in joined
    assert joined.index("答え") < joined.index("解法") < joined.index("根拠") < joined.index("注意")


def test_review_view_pages_have_at_most_three_lines_and_clamp():
    sol = _sol(solution_steps=[f"手順{i}" for i in range(10)])
    v = build_review_view(sol, index=0, problem_count=1)
    assert v["total_view_pages"] > 1
    for vp in range(v["total_view_pages"]):
        page = build_review_view(sol, index=0, problem_count=1, view_page=vp)
        assert len(page["lines"]) <= 3
    # Out-of-range view_page clamps instead of erroring.
    over = build_review_view(sol, index=0, problem_count=1, view_page=999)
    assert over["view_page"] == over["total_view_pages"] - 1
    assert over["nav"]["next_view_page"] is None


def test_review_view_header_shows_deck_position():
    v = build_review_view(_sol(), index=1, problem_count=4, problem_no="問2")
    assert "問2 2/4" in v["lines"][0]


def test_review_view_problem_nav_edges():
    first = build_review_view(_sol(), index=0, problem_count=3)
    assert first["nav"]["prev_problem"] is None
    assert first["nav"]["next_problem"] == 1
    last = build_review_view(_sol(), index=2, problem_count=3)
    assert last["nav"]["prev_problem"] == 1
    assert last["nav"]["next_problem"] is None
    ops = first["nav"]["operations"]
    assert set(ops.values()) == {"phone"}


def test_review_view_omits_empty_sections():
    sol = _sol(rationale="", cautions="", solution_steps=[])
    joined = "\n".join(_all_review_lines(sol))
    for absent in ("解法", "根拠", "注意", "(なし)", "(解法なし)"):
        assert absent not in joined
    assert "答え: B: 青" in joined


def test_review_view_unsolved_placeholder():
    v = build_review_view(
        None, index=2, problem_count=4, problem_no="問3", solved=False
    )
    assert v["solved"] is False
    assert "未解答" in v["lines"]
    assert "問3 3/4" in v["lines"][0]


def test_review_view_is_silent():
    v = build_review_view(_sol(), index=0, problem_count=1)
    for forbidden in ("sound", "audio", "flash", "animation", "blink"):
        assert forbidden not in v


def test_reading_done_ack_reports_camera_off():
    ack = build_reading_done_ack(problem_count=4, total_pages=5)
    assert len(ack["lines"]) <= 3
    assert ack["camera_off"] is True
    assert "読取完了 5ページ" in ack["lines"][0]
    assert "4問" in ack["lines"][1]

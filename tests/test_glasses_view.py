from app import glasses_view
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


def _stream(sol, stage):
    """Every line of a stage, across all view pages, joined without breaks.

    A line now wraps at MAX_COLUMNS columns, so a label can start on one line
    and finish on the next, or on the next view page. Joining with "" asks the
    question these tests mean to ask: does the text reach the operator at all.
    """
    total = build_glasses_view(sol, stage=stage, page=0)["total_pages"]
    return "".join(
        line
        for page in range(total)
        for line in build_glasses_view(sol, stage=stage, page=page)["lines"]
    )


def _sol(**kw):
    base = dict(answer="B: 青", rationale="条件②より", cautions="参考値",
                solution_steps=["手順1", "手順2"], answer_confidence=0.8)
    base.update(kw)
    return SolveResult(**base)


def test_view_has_at_most_three_lines():
    """Each page in the paginated view must have <= _MAX_LINES (3) lines.

    _wrap() splits a logical line that exceeds MAX_COLUMNS columns, so one
    logical line can become several entries. The invariant is unchanged and
    independent of that: every *page* returned by _paginate() carries at most
    _MAX_LINES entries.
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
    """Many short logical lines paginate, independently of wrapping.

    The 'solution' stage returns [header] + solution_steps, so many short
    steps produce more than _MAX_LINES (3) lines without any step being long
    enough for _wrap() to split. Wrapping is covered separately below.
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
    joined = _stream(sol, "rationale")
    assert "D7:P01,D9:P03" in joined
    assert "P00" not in joined


def test_legacy_zero_based_evidence_is_shifted_only_for_display():
    sol = _sol(
        evidence_pages=[0, 2],
        extras={"_evidence_pages_base": 0},
    )
    joined = _stream(sol, "rationale")
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


# --- Column budget (contract 1.11.0) -----------------------------------------
# The HUD renders one TextView at 34sp (HudLayout.fromLines) on a 480x640
# @240dpi logical screen, so ~9 full-width glyphs span a line. The budget is an
# ESTIMATE: the CUSTOMVIEW overlay's text area has never been measured, and
# docs/hardware-measurements.md states the 3-line limit is a property of the
# overlay rather than of the screen size. These tests pin the behaviour the
# budget is supposed to have, not the number itself.

# The answer 物理基礎 問2 returned in the live run of 2026-09-14.
_MEASURED_ANSWER = "②（ア＝比例、イ＝反比例、ウ＝Ω・m）"


def _widest(lines):
    return max((sum(glasses_view._columns(c) for c in ln) for ln in lines), default=0)


def test_a_measured_answer_line_is_wrapped_to_the_column_budget():
    lines = glasses_view._wrap(f"答え: {_MEASURED_ANSWER}")
    assert len(lines) > 1, "the measured answer is wider than one line"
    # A hung closing mark may exceed the budget by at most one full-width glyph.
    assert _widest(lines) <= glasses_view.MAX_COLUMNS + 2


def test_wrapping_loses_no_character():
    """The 1.2.0 regression was truncation. Wrapping must never drop text."""
    text = "答え: " + _MEASURED_ANSWER + "（ただし有効数字2桁、単位はΩ・mとする）"
    assert "".join(glasses_view._wrap(text)) == text


def test_a_full_width_glyph_costs_two_columns():
    assert glasses_view._columns("答") == 2
    assert glasses_view._columns("①") == 2, "answer marks render full-width"
    assert glasses_view._columns("A") == 1
    lines = glasses_view._wrap("あ" * 30)
    assert all(len(ln) <= glasses_view.MAX_COLUMNS // 2 for ln in lines)


def test_a_closing_mark_never_opens_a_line():
    # 9 full-width glyphs fill an 18-column line; the 10th is a closing mark,
    # which hangs rather than starting the next line alone.
    lines = glasses_view._wrap("あいうえおかきくけ、これで終わり。")
    assert lines[0].endswith("、")
    assert not any(ln.startswith("、") or ln.startswith("。") for ln in lines)


def test_zero_columns_restores_the_unwrapped_line(monkeypatch):
    monkeypatch.setattr(glasses_view, "MAX_COLUMNS", 0)
    text = "答え: " + _MEASURED_ANSWER
    assert glasses_view._wrap(text) == [text]


def test_render_contract_reports_the_current_budget(monkeypatch):
    monkeypatch.setattr(glasses_view, "MAX_COLUMNS", 12)
    contract = glasses_view.render_contract()
    assert contract["max_columns_per_line"] == 12
    assert contract["max_lines"] == 3
    assert contract["truncates"] is False
    assert contract["wraps"] is True


def test_a_review_page_never_exceeds_the_budget_or_three_lines():
    sol = _sol(answer=_MEASURED_ANSWER, solution_steps=[], rationale="", cautions="")
    view = build_review_view(sol, index=0, problem_count=1, problem_no="問2")
    total = view["total_view_pages"]
    seen = []
    for page in range(total):
        lines = build_review_view(
            sol, index=0, problem_count=1, problem_no="問2", view_page=page
        )["lines"]
        assert len(lines) <= 3
        assert _widest(lines) <= glasses_view.MAX_COLUMNS + 2
        seen += lines
    assert _MEASURED_ANSWER in "".join(seen)

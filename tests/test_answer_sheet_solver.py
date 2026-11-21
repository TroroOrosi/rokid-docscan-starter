"""Answer-sheet mode preserves written answers and never substitutes a placeholder."""

import json
from types import SimpleNamespace

import pytest

from app.llm import LLMClient
from app.solvers import Question, register_solver, solve_with_fallback
from app.solvers.llm_adapter import (_ANSWER_ONLY_SYSTEM, DIAGRAM_NOT_SHOWN, OUTSIDE_FORMAT_NOT_SHOWN, LLMSolver,
                                     answer_numbers)


def test_printed_numbers_survive_beyond_twenty_blanks_and_three_digits():
    numbers = list(range(1, 22)) + [1000, 2026, 9999]
    assert answer_numbers(numbers) == numbers
    assert answer_numbers(["1000", "2026", "1000"]) == [1000, 2026]


@pytest.mark.parametrize("numbers", [[10000], list(range(1, 1002)), [0, 1], [-1], ["A"], [True]])
def test_unrepresentable_number_lists_fail_instead_of_dropping_printed_labels(numbers):
    with pytest.raises(ValueError, match="answer number"):
        answer_numbers(numbers)


def test_answer_only_system_keeps_the_derivation_for_a_written_solution():
    """The operator's decision: the answer is the full content written on the
    answer sheet; a 記述式 mathematics answer includes the derivation needed
    for credit. This must not be conditioned on the question "explicitly"
    asking for a proof -- a 記述式 answer format implies it. Asserted on the
    prompt constant itself, not on model output.
    """
    assert "記述式" in _ANSWER_ONLY_SYSTEM
    assert "derivation" in _ANSWER_ONLY_SYSTEM
    assert "full credit" in _ANSWER_ONLY_SYSTEM


def test_answer_only_system_judges_the_form_from_the_question_and_gives_result_then_working():
    """The answer sheet is never photographed and no format hint is sent, so the
    working cannot hang on what "the answer sheet itself expects": a bare value
    is right only where the question shows a mark, choice, boxed number or word.
    """
    assert "answer sheet is often not among the images" in _ANSWER_ONLY_SYSTEM
    assert "answer sheet itself expects" not in _ANSWER_ONLY_SYSTEM
    assert "final result first and then" in _ANSWER_ONLY_SYSTEM
    assert "Never shorten an answer to fit a display" in _ANSWER_ONLY_SYSTEM


def test_answer_only_system_keeps_the_working_where_a_box_is_printed_for_the_result():
    """The operator's trial of 2026-11-17: a sheet said on its first side to leave the working, the missed problems of
    its second side were taken again alone, and the answers came back as bare values. Each problem had a blank line or
    a box for its result, which the request until then named as a reason to give no working ("a number in a box").
    A bare answer is right only for a mark sheet, a choice, or a word, reading or phrase to fill in.
    """
    assert "a number in a box" not in _ANSWER_ONLY_SYSTEM
    assert "does not waive the working" in _ANSWER_ONLY_SYSTEM
    assert "may stand on a sheet that was not captured" in _ANSWER_ONLY_SYSTEM
    assert "マーク式" in _ANSWER_ONLY_SYSTEM


def test_answer_only_system_puts_the_working_after_a_line_that_two_reads_can_be_split_at():
    """What two reads are compared by is what stands before the working (codex_cli._mark)."""
    from app.solvers.codex_cli import _WORKING

    assert "式：" in _ANSWER_ONLY_SYSTEM
    assert _WORKING.search("3/8\n式：3/2³＝3/8")


def test_answer_only_system_names_each_answer_box_of_a_question():
    """The same trial: 期待値, 分散 and 標準偏差 came back as three unnamed items, or as one value, and could not be told
    apart on the glasses."""
    assert "its printed name" in _ANSWER_ONLY_SYSTEM
    assert "平均：7/2" in _ANSWER_ONLY_SYSTEM
    # Two reads that each made up a name for an unnamed blank ("期待値 E(X)", "E(X)") were shown as disagreeing.
    assert "no name where none is printed" in _ANSWER_ONLY_SYSTEM


def test_answer_only_system_reads_soft_print_before_it_gives_a_question_up():
    """The same trial: pages a person could read through their blur came back as 不鮮明 for most questions."""
    assert "Photographed print is often soft" in _ANSWER_ONLY_SYSTEM
    assert "never guess a number, a symbol or a choice label" in _ANSWER_ONLY_SYSTEM


def test_answer_only_system_names_a_choice_by_its_printed_label_and_adds_the_words_of_a_short_option():
    """The operator's use of 2026-11-18: a word bank's labels ran ⑩, ⑫, ⑬ (a sheet marked one digit at a time has no
    11), the print was soft, and the answers said ⑪: counted along the row, and nothing on the glasses to check by."""
    assert "printed labels are not always consecutive" in _ANSWER_ONLY_SYSTEM
    assert "never number the options by counting" in _ANSWER_ONLY_SYSTEM
    assert "⑫（光合成）" in _ANSWER_ONLY_SYSTEM
    assert "label alone where the option is a sentence" in _ANSWER_ONLY_SYSTEM


def test_answer_only_system_keeps_a_quotation_in_the_language_it_is_printed_in():
    """The same day: an answer in Japanese quoted an English sentence of the passage in Japanese."""
    assert "stay in the language and the wording they are printed in" in _ANSWER_ONLY_SYSTEM


def test_the_booklet_request_does_not_list_an_answer_sheet_in_view_as_missing():
    """The same day: five items at the end of the answers each said that the rest of a mark sheet at a capture's edge
    had not been captured."""
    from app.solvers.chatgpt_web import _COVERAGE

    assert "is not part of the problems" in _COVERAGE


def test_the_booklet_request_makes_one_item_of_a_numbered_question_and_reads_overlaps_where_they_are_sharp():
    from app.solvers.chatgpt_web import _ALL_TASK, _CAPTURE_CONTEXT

    assert "smallest printed numbered unit" in _ALL_TASK
    assert "are not items of their own" in _ALL_TASK
    assert "sharpest in its middle" in _CAPTURE_CONTEXT
    assert "from the capture that shows it best" in _CAPTURE_CONTEXT


def test_answer_only_system_places_a_drawing_beside_the_printed_figure_and_in_words():
    """The glasses draw a standalone figure, never over the printed one."""
    assert "redraw the axes, points and labels" in _ANSWER_ONLY_SYSTEM
    assert "which points to join, intercepts, what to shade" in _ANSWER_ONLY_SYSTEM


def test_answer_only_system_states_where_a_label_sits_and_how_long_it_may_be():
    """AnswerView draws a label from the left end of its baseline in the 22.4 px
    monospace label font (max(18, 640 * .035); half-width 0.6 em, full-width
    1 em) and replaces one wider than 45% of the figure by "[n]". The figure is
    at most 480 * (1 - 2 * .03) px wide.
    """
    import re

    assert "left end of its baseline" in _ANSWER_ONLY_SYSTEM
    full, half = map(int, re.search(r"(\d+) full-width or (\d+) half-width", _ANSWER_ONLY_SYSTEM).groups())
    room, font = 480 * (1 - 2 * .03) * .45, 640 * .035
    assert full * font <= room and half * font * .6 <= room
    assert full >= 6 and half >= 10, "a limit this short would forbid ordinary axis labels"


def test_answer_only_system_keeps_the_written_part_when_a_drawing_cannot_be_represented():
    assert "return needs_input with the limitation" not in _ANSWER_ONLY_SYSTEM
    assert "describe the drawing in words" in _ANSWER_ONLY_SYSTEM
    assert "needs_input is only for missing or unreadable material" in _ANSWER_ONLY_SYSTEM
    assert "empty answer and identify the missing material separately" in _ANSWER_ONLY_SYSTEM


def solver_for(payload):
    sdk = SimpleNamespace(messages=SimpleNamespace(create=lambda **kwargs:
        SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(payload))])))
    return LLMSolver(name="answer-sheet-test", provider="anthropic",
                     client=LLMClient(sdk, provider="anthropic", model="test"))


def test_written_proof_survives_adapter_and_registry_without_display_length_limit():
    proof = "仮定より、二つの三角形の対応する辺が等しい。\n" * 50 + "よって合同である。"
    register_solver(solver_for({"answer": proof, "status": "ready"}), replace=True)
    result, _ = solve_with_fallback(
        Question(body_text="合同であることを証明せよ", answer_only=True),
        tiers=["answer-sheet-test"],
    )
    assert result.answer == proof


def test_indented_code_fragment_survives_solver_entry():
    answer = "    total_cost += i"
    result = solver_for({"answer": answer, "status": "ready"}).solve(
        question=Question(body_text="空欄に入るコードを記入", answer_only=True))
    assert result.answer == answer


_OUTSIDE_THE_CONTRACT = [
    ("derivation", "2x+3=7 より 2x=4。"),
    ("solution_steps", ["両辺から3を引く。", "両辺を2で割る。"]),
    ("answer_blocks", [{"text": "x=2"}]),
    ("rationale", "理由"),
    ("cautions", "条件を確認"),
    ("raw_reasoning", "2x=4"),
    ("unrecognized_answer", 0),
    ("unrecognized_answer", False),
]


@pytest.mark.parametrize("field,value", _OUTSIDE_THE_CONTRACT)
def test_answer_rejects_nonempty_content_outside_the_answer_contract(field, value):
    """A reply that answers nothing has no text to keep, and Work's quality guard
    relies on a stop not carrying an answer in another field."""
    payload = {"answer": "よって x=2。", "status": "needs_input", field: value}
    original = json.dumps(payload)
    with pytest.raises(ValueError, match="unsupported answer-sheet field"):
        solver_for(payload).solve(question=Question(body_text="方程式を解け", answer_only=True))
    assert json.dumps(payload) == original


@pytest.mark.parametrize("field,value", _OUTSIDE_THE_CONTRACT)
def test_ready_answer_with_content_outside_the_contract_keeps_its_text_for_review(field, value):
    """The other field is not shown and not merged (its order and meaning are
    unknown); the wearer gets the answer text and is told something is missing."""
    payload = {"answer": "よって x=2。", "status": "ready", field: value}
    original = json.dumps(payload)
    result = solver_for(payload).solve(question=Question(body_text="方程式を解け", answer_only=True))
    assert result.answer == "よって x=2。"
    assert result.extras["answer_status"] == "ready"
    assert result.extras["review_note"] == OUTSIDE_FORMAT_NOT_SHOWN
    assert json.dumps(payload) == original


_CIRCLE = {"alt": "円", "aspect_ratio": 1, "elements": [{"type": "circle", "cx": .5, "cy": .5, "r": .3}]}
_INVALID_DIAGRAMS = [
    {"alt": "曲線", "aspect_ratio": 1, "elements": [{"type": "bezier", "points": [[0, 0], [1, 1]]}]},
    {"alt": "線", "aspect_ratio": 1, "elements": [{"type": "line", "x1": 0, "y1": 0, "x2": 1.2, "y2": 1}]},
    {"alt": "線", "aspect_ratio": 1, "elements": [{"type": ["line"]}]},
    "y=x のグラフ",
]


@pytest.mark.parametrize("bad", _INVALID_DIAGRAMS)
def test_invalid_diagram_is_dropped_alone_and_the_written_answer_is_kept_for_review(bad):
    result = solver_for({"answer": "y=x", "status": "ready", "diagrams": [bad, _CIRCLE]}).solve(
        question=Question(body_text="グラフをかけ", answer_only=True))
    assert result.answer == "y=x" and result.diagrams == [_CIRCLE]
    assert result.extras["answer_status"] == "ready"
    assert result.extras["review_note"] == DIAGRAM_NOT_SHOWN


@pytest.mark.parametrize("diagrams,kept", [({"alt": "円"}, []), ([_CIRCLE] * 5, [_CIRCLE] * 4)])
def test_diagrams_that_are_not_a_list_of_at_most_four_keep_the_text_and_what_can_be_drawn(diagrams, kept):
    result = solver_for({"answer": "y=x", "status": "ready", "diagrams": diagrams}).solve(
        question=Question(body_text="グラフをかけ", answer_only=True))
    assert (result.answer, result.diagrams, result.extras["review_note"]) == ("y=x", kept, DIAGRAM_NOT_SHOWN)


@pytest.mark.parametrize("diagrams", [None, [], [_CIRCLE]])
def test_an_answer_with_no_or_valid_diagrams_is_not_marked_for_review(diagrams):
    result = solver_for({"answer": "y=x", "status": "ready", "diagrams": diagrams}).solve(
        question=Question(body_text="グラフをかけ", answer_only=True))
    assert result.answer == "y=x" and result.diagrams == (diagrams or [])
    assert not result.extras.get("review_note")


def test_a_drawing_only_answer_with_nothing_drawable_left_still_fails():
    with pytest.raises(ValueError, match="written answer"):
        solver_for({"answer": "", "status": "ready", "diagrams": [_INVALID_DIAGRAMS[0]]}).solve(
            question=Question(body_text="グラフをかけ", answer_only=True))


def test_both_notes_reach_the_wearer_when_a_diagram_and_a_separate_field_are_left_out():
    result = solver_for({"answer": "y=x", "status": "ready", "diagrams": [_INVALID_DIAGRAMS[0]],
                         "derivation": "傾き1"}).solve(question=Question(body_text="グラフをかけ", answer_only=True))
    assert result.extras["review_note"] == DIAGRAM_NOT_SHOWN + "。" + OUTSIDE_FORMAT_NOT_SHOWN


def test_booklet_item_with_an_invalid_diagram_keeps_its_text_and_fails_only_when_nothing_is_left():
    from app.solvers.chatgpt_web import _booklet_replies

    bad = _INVALID_DIAGRAMS[0]
    replies = _booklet_replies({"questions": [
        {"label": "問1", "status": "ready", "answer": "x=2", "diagrams": [bad]},
        {"label": "問2", "status": "ready", "answer": "", "diagrams": [bad]},
        {"label": "問3", "status": "needs_input", "answer": "", "missing_material": "図2", "diagrams": [bad]},
    ]}, subject=None, extras={})
    assert (replies[0][1].answer, replies[0][1].diagrams) == ("x=2", [])
    assert replies[0][1].extras["review_note"] == DIAGRAM_NOT_SHOWN
    assert isinstance(replies[1][1], ValueError)
    assert replies[2][1].extras["answer_status"] == "needs_input"
    assert replies[2][1].extras["missing_material"] == "図2" and not replies[2][1].extras.get("review_note")


@pytest.mark.parametrize("empty", [None, "", " \n ", [], {}])
def test_selection_accepts_empty_legacy_supplementary_sections(empty):
    result = solver_for({"answer": "イ", "status": "ready", "solution_steps": empty,
                         "rationale": empty, "cautions": empty, "raw_reasoning": empty}).solve(
        question=Question(body_text="記号を記入", answer_only=True))
    assert result.answer == "イ"
    assert result.solution_steps == []
    assert result.rationale == result.cautions == result.raw_reasoning == ""


@pytest.mark.parametrize("field", ["derivation", "solution_steps", "answer_blocks"])
def test_booklet_rejects_separate_body_fields_outside_questions(field):
    from app.solvers.chatgpt_web import _booklet_replies

    data = {"questions": [{"answer": "x=2", "status": "ready"}], field: ["2x=4"]}
    with pytest.raises(ValueError, match="unsupported answer-sheet field"):
        _booklet_replies(data, subject=None, extras={})


def test_booklet_preserves_transport_metadata_and_known_question_metadata():
    from app.solvers.chatgpt_web import ChatGptWebClient, _booklet_replies

    item = {"group": "第1問", "label": "問1", "pages": [1], "answer_no": [101],
            "requires_audio": False, "question_id": "q1", "status": "ready", "answer": "x=2"}
    envelope = {"questions": [item], "batch_id": "batch", "manifest_sha256": "a" * 64,
                "extraction": {"status": "ok", "files": []}, "readability": [], "derivation": ""}
    expected = ("questions", "manifest_sha256", "extraction", "readability")
    batch = {"id": "batch", "final": True, "expect": expected}
    assert ChatGptWebClient._valid_batch(json.dumps(envelope), batch)
    replies = _booklet_replies(envelope, subject=None, extras={}, transport_fields=expected)
    assert replies[0][0] == item
    assert replies[0][1].answer == "x=2"
    assert replies[0][1].extras["answer_no"] == [101]


def test_booklet_receipt_identifier_cannot_contain_a_separate_answer_body():
    from app.solvers.chatgpt_web import _booklet_replies

    data = {"questions": [{"status": "ready", "answer": "x=2"}],
            "batch_id": {"derivation": "2x=4"}}
    with pytest.raises(ValueError, match="invalid answer receipt identifier"):
        _booklet_replies(data, subject=None, extras={})


def test_pending_audio_cannot_hide_nonempty_separate_body_fields():
    from app.solvers.chatgpt_web import _booklet_replies

    data = {"questions": [{"label": "Listening", "requires_audio": True, "status": "pending_audio",
                           "answer": "", "diagrams": [], "solution_steps": ["選択肢は2"]}]}
    with pytest.raises(ValueError, match="unsupported answer-sheet field"):
        _booklet_replies(data, subject=None, extras={}, stage="reading")


def test_missing_material_is_a_separate_state_not_a_written_answer_or_fallback():
    register_solver(solver_for({"answer": "推測値", "status": "needs_input",
                               "missing_material": "図2の下端"}), replace=True)
    result, solver = solve_with_fallback(Question(body_text="図2を参照", answer_only=True),
                                        tiers=["answer-sheet-test"])
    assert solver.name == "answer-sheet-test"
    assert result.answer == ""
    assert result.extras["answer_status"] == "needs_input"
    assert result.extras["missing_material"] == "図2の下端"


def test_unconfigured_answer_sheet_mode_never_returns_local_choice():
    with pytest.raises(RuntimeError, match="answer-sheet"):
        solve_with_fallback(Question(body_text="選べ", choices=["A", "B"], answer_only=True),
                            tiers=["no-such-provider"])


@pytest.mark.parametrize("answer", [None, 42, {"text": "A"}, ""])
def test_invalid_written_answer_is_rejected(answer):
    with pytest.raises(ValueError):
        solver_for({"answer": answer, "status": "ready"}).solve(
            question=Question(body_text="問1", answer_only=True))


def test_legacy_explicit_limit_remains_available():
    result = solver_for({"answer": "abcdef"}).solve(question=Question(body_text="q"),
                                                    max_answer_len=3)
    assert result.answer == "abc"


def test_non_answer_sheet_solver_retains_its_separate_solution_fields():
    result = solver_for({"answer": "x=2", "solution_steps": ["2x=4"],
                         "rationale": "両辺を2で割る", "cautions": "xは実数",
                         "raw_reasoning": "2x+3=7"}).solve(question=Question(body_text="q"))
    assert result.solution_steps == ["2x=4"]
    assert result.rationale == "両辺を2で割る"
    assert result.cautions == "xは実数"
    assert result.raw_reasoning == "2x+3=7"


def test_drawing_only_answer_survives_registry():
    diagram = {"alt": "円", "aspect_ratio": 1, "elements": [
        {"type": "circle", "cx": .5, "cy": .5, "r": .3}]}
    register_solver(solver_for({"answer": "", "status": "ready", "diagrams": [diagram]}), replace=True)
    result, _ = solve_with_fallback(Question(body_text="円を描け", answer_only=True), tiers=["answer-sheet-test"])
    assert result.answer == "" and result.diagrams == [diagram]


def test_uncertain_browser_submission_never_falls_through_to_another_provider(monkeypatch):
    from app.solvers.chatgpt_web import ChatGptWebUncertain
    failing = solver_for({"answer": "not used", "status": "ready"})
    def fail(**_):
        raise ChatGptWebUncertain("unknown send")
    monkeypatch.setattr(failing, "solve", fail)
    register_solver(failing, replace=True)
    with pytest.raises(ChatGptWebUncertain):
        solve_with_fallback(Question(body_text="question", answer_only=True),
                            tiers=["answer-sheet-test", "local"])


def test_a_lost_subject_chat_is_reported_not_hidden_behind_another_tier(monkeypatch):
    # The operator has to learn the subject's chat is gone, not "解析に失敗しました".
    from app.solvers.chatgpt_web import ChatGptWebChatLost
    failing = solver_for({"answer": "not used", "status": "ready"})
    def lost(**_):
        raise ChatGptWebChatLost("could not return to the subject's chat")
    monkeypatch.setattr(failing, "solve", lost)
    register_solver(failing, replace=True)
    with pytest.raises(ChatGptWebChatLost):
        solve_with_fallback(Question(body_text="question", answer_only=True),
                            tiers=["answer-sheet-test", "local"])

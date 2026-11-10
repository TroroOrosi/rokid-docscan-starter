"""Answer-sheet mode preserves written answers and never substitutes a placeholder."""

import json
from types import SimpleNamespace

import pytest

from app.llm import LLMClient
from app.solvers import Question, register_solver, solve_with_fallback
from app.solvers.llm_adapter import _ANSWER_ONLY_SYSTEM, LLMSolver, answer_numbers


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


@pytest.mark.parametrize("field,value", [
    ("derivation", "2x+3=7 より 2x=4。"),
    ("solution_steps", ["両辺から3を引く。", "両辺を2で割る。"]),
    ("answer_blocks", [{"text": "x=2"}]),
    ("rationale", "理由"),
    ("cautions", "条件を確認"),
    ("raw_reasoning", "2x=4"),
    ("unrecognized_answer", 0),
    ("unrecognized_answer", False),
])
@pytest.mark.parametrize("status", ["ready", "needs_input"])
def test_answer_rejects_nonempty_content_outside_the_answer_contract(field, value, status):
    payload = {"answer": "よって x=2。", "status": status, field: value}
    original = json.dumps(payload)
    with pytest.raises(ValueError, match="unsupported answer-sheet field"):
        solver_for(payload).solve(question=Question(body_text="方程式を解け", answer_only=True))
    assert json.dumps(payload) == original


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

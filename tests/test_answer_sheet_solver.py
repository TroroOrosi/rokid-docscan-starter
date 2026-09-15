"""Answer-sheet mode preserves written answers and never substitutes a placeholder."""

import json
from types import SimpleNamespace

import pytest

from app.llm import LLMClient
from app.solvers import Question, register_solver, solve_with_fallback
from app.solvers.llm_adapter import LLMSolver


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


def test_selection_keeps_only_the_written_label_and_excludes_supplementary_sections():
    result = solver_for({"answer": "イ", "status": "ready", "solution_steps": ["補足"],
                         "rationale": "理由", "cautions": "注意", "raw_reasoning": "内部"}).solve(
        question=Question(body_text="記号を記入", answer_only=True))
    assert result.answer == "イ"
    assert result.solution_steps == []
    assert result.rationale == result.cautions == result.raw_reasoning == ""


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


def test_drawing_only_answer_survives_registry():
    diagram = {"alt": "円", "aspect_ratio": 1, "elements": [
        {"type": "circle", "cx": .5, "cy": .5, "r": .3}]}
    register_solver(solver_for({"answer": "", "status": "ready", "diagrams": [diagram]}), replace=True)
    result, _ = solve_with_fallback(Question(body_text="円を描け", answer_only=True), tiers=["answer-sheet-test"])
    assert result.answer == "" and result.diagrams == [diagram]

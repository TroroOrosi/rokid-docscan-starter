from app.solvers import (
    Question,
    SolveResult,
    Solver,
    register_solver,
    solve_with_fallback,
)


class _Raises(Solver):
    name = "raises-tier"
    provider_version = "t-1"
    offline = True

    def solve(self, *, question, max_answer_len=64):
        raise RuntimeError("simulated cloud failure")


class _Empty(Solver):
    name = "empty-tier"
    provider_version = "t-1"
    offline = True

    def solve(self, *, question, max_answer_len=64):
        return SolveResult(answer="   ")  # blank -> unacceptable


class _Good(Solver):
    name = "good-tier"
    provider_version = "t-1"
    offline = True

    def solve(self, *, question, max_answer_len=64):
        return SolveResult(answer="正解X", answer_confidence=0.9)


def test_raising_tier_falls_back_to_local():
    register_solver(_Raises(), replace=True)
    result, solver = solve_with_fallback(Question(body_text="x"), tiers=["raises-tier"])
    assert solver.name == "local"
    assert result.extras["served_by"] == "local"
    assert any("raises-tier" in s for s in result.extras["fallback_from"])


def test_empty_tier_is_skipped():
    register_solver(_Empty(), replace=True)
    result, solver = solve_with_fallback(Question(body_text="x"), tiers=["empty-tier"])
    assert solver.name == "local"
    assert any("empty-tier" in s for s in result.extras["fallback_from"])


def test_good_tier_serves_and_is_recorded():
    register_solver(_Good(), replace=True)
    result, solver = solve_with_fallback(Question(body_text="x"), tiers=["good-tier"])
    assert solver.name == "good-tier"
    assert result.answer == "正解X"
    assert result.extras["served_by"] == "good-tier"
    assert "fallback_from" not in result.extras


def test_local_is_appended_as_final_safety_net():
    # Even with an all-failing tier list, local guarantees an answer.
    register_solver(_Raises(), replace=True)
    result, solver = solve_with_fallback(Question(body_text="x"), tiers=["raises-tier"])
    assert (result.answer or "").strip()

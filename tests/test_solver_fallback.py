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


def test_unknown_tier_does_not_shadow_later_tiers():
    # A mistyped tier name (e.g. "claud") must be skipped, not silently
    # coerced to the local placeholder — the real later tier must still serve.
    register_solver(_Good(), replace=True)
    result, solver = solve_with_fallback(
        Question(body_text="x"), tiers=["no-such-solver", "good-tier"]
    )
    assert solver.name == "good-tier"
    assert result.answer == "正解X"
    assert any("no-such-solver:unknown" in s for s in result.extras["fallback_from"])


# --- out-of-range choices ---------------------------------------------------

class _OutOfRange(Solver):
    """First answer names a choice that does not exist; the re-ask is valid."""

    name = "out-of-range-tier"
    provider_version = "t-1"
    offline = True

    def __init__(self, *, recovers: bool = True):
        self.recovers = recovers
        self.prompts: list[str | None] = []

    def solve(self, *, question, max_answer_len=64):
        self.prompts.append(question.retry_hint)
        if self.recovers and question.retry_hint:
            return SolveResult(answer="B: 青", answer_confidence=0.8)
        return SolveResult(answer="F", answer_confidence=0.8)


def test_out_of_range_choice_is_retried_once_with_the_valid_labels():
    solver = _OutOfRange()
    register_solver(solver, replace=True)
    result, served = solve_with_fallback(
        Question(body_text="選べ", choices=["赤", "青", "緑"]),
        tiers=["out-of-range-tier"],
    )
    assert served.name == "out-of-range-tier"
    assert result.answer == "B: 青"
    assert result.extras["choice_retry"] == "recovered"
    # Exactly one re-ask, and it stated the labels rather than repeating blind.
    assert len(solver.prompts) == 2
    assert solver.prompts[0] is None
    assert "A〜C" in solver.prompts[1]


def test_persistent_out_of_range_answer_is_kept_and_flagged_not_dropped():
    register_solver(_OutOfRange(recovers=False), replace=True)
    result, served = solve_with_fallback(
        Question(body_text="選べ", choices=["赤", "青", "緑"]),
        tiers=["out-of-range-tier"],
    )
    # Still served by the tier: a label slip is not a capability failure, so it
    # must not fall through to the next (paid) tier or to the placeholder.
    assert served.name == "out-of-range-tier"
    assert result.answer == "F"
    assert result.extras["choice_out_of_range"] is True


def test_in_range_choice_is_never_retried():
    solver = _OutOfRange()
    solver.solve = lambda *, question, max_answer_len=64: (
        solver.prompts.append(question.retry_hint)
        or SolveResult(answer="C: 緑", answer_confidence=0.9)
    )
    register_solver(solver, replace=True)
    result, _ = solve_with_fallback(
        Question(body_text="選べ", choices=["赤", "青", "緑"]),
        tiers=["out-of-range-tier"],
    )
    assert result.answer == "C: 緑"
    assert len(solver.prompts) == 1
    assert "choice_out_of_range" not in result.extras

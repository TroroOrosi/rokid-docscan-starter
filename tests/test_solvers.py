from app.solvers import (
    Question,
    Solver,
    SolveResult,
    get_solver,
    list_solvers,
    register_solver,
)
from app.solvers.local_placeholder import LocalPlaceholderSolver


def test_local_solver_registered_and_offline():
    names = [s["name"] for s in list_solvers()]
    assert "local" in names
    assert get_solver().offline is True


def test_local_solver_is_safe_on_empty():
    # Empty input must not raise; returns a low-confidence placeholder.
    r = get_solver("local").solve(question=Question())
    assert r.answer
    assert r.answer_confidence == 0.0


def test_local_solver_is_deterministic_for_choices():
    q = Question(body_text="次のうち正しいものは", choices=["赤", "青", "緑", "黄"])
    a = LocalPlaceholderSolver().solve(question=q).answer
    b = LocalPlaceholderSolver().solve(question=q).answer
    assert a == b
    assert a[0] in "ABCD"  # rendered as a labelled choice


def test_local_solver_marks_low_confidence_placeholder():
    q = Question(body_text="2x+3=7 を解け")
    r = LocalPlaceholderSolver().solve(question=q)
    # Placeholder must never look confident — it is not a real answer.
    assert r.answer_confidence <= 0.3
    assert r.extras.get("placeholder") is True


def test_registry_falls_back_to_local_for_unknown():
    assert get_solver("does-not-exist").name == "local"


def test_register_and_route_custom_solver():
    class DummySolver(Solver):
        name = "dummy-solver"
        provider_version = "t-1"
        offline = True

        def solve(self, *, question, max_answer_len=64):
            return SolveResult(answer="DUMMY", answer_confidence=1.0)

    register_solver(DummySolver(), replace=True)
    assert get_solver("dummy-solver").solve(question=Question()).answer == "DUMMY"
    # default routing still returns local
    assert get_solver().name == "local"

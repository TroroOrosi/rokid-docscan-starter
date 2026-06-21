"""Provider-agnostic question solvers (answer / solve / explain).

The server never talks to a concrete model vendor directly. It asks the
registry for a solver by name and uses the stable `Solver` interface. Swapping
the offline placeholder <-> Gemini <-> OpenAI <-> Claude <-> a future on-device
VLM is a registry change, not an endpoint change. See app/solvers/base.py.
"""

from .base import Question, SolveResult, Solver
from .registry import (
    DEFAULT_SOLVER,
    get_solver,
    list_solvers,
    register_solver,
    solve_with_fallback,
)

__all__ = [
    "Question",
    "SolveResult",
    "Solver",
    "DEFAULT_SOLVER",
    "get_solver",
    "list_solvers",
    "register_solver",
    "solve_with_fallback",
]

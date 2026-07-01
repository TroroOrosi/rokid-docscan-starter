"""Solver registry + model routing (mirrors app/analyzers/registry.py).

A tiny provider registry so the active solver is chosen by name/feature flag,
not hard-coded. Future Gemini/OpenAI/Claude/on-device adapters register here
under their own key; routing picks one based on config without touching
endpoints.

Routing precedence:
  1. explicit `prefer` argument (e.g. per-request hint),
  2. ROKID_SOLVER env var,
  3. DEFAULT_SOLVER.

If the requested solver is missing (e.g. cloud adapter not installed / no
creds), we fall back to the offline local placeholder so the server keeps
working (offline-first / two-tier fallback).
"""

from __future__ import annotations

import os

from .base import Solver
from .claude import LLMSolver
from .local_placeholder import LocalPlaceholderSolver

DEFAULT_SOLVER = "local"

_REGISTRY: dict[str, Solver] = {}


def register_solver(solver: Solver, *, replace: bool = False) -> None:
    if solver.name in _REGISTRY and not replace:
        raise ValueError(f"solver '{solver.name}' already registered")
    _REGISTRY[solver.name] = solver


def list_solvers() -> list[dict]:
    return [s.info() for s in _REGISTRY.values()]


def _select_name(prefer: str | None) -> str:
    return prefer or os.environ.get("ROKID_SOLVER") or DEFAULT_SOLVER


def get_solver(prefer: str | None = None) -> Solver:
    """Return a solver by routing rules, falling back to the local one."""
    name = _select_name(prefer)
    solver = _REGISTRY.get(name)
    if solver is None:
        solver = _REGISTRY.get(DEFAULT_SOLVER)
    if solver is None:  # registry empty -> lazily install the local default
        solver = LocalPlaceholderSolver()
        register_solver(solver, replace=True)
    return solver


def _tier_names(tiers: list[str] | None) -> list[str]:
    """Ordered solver tiers, with the offline default guaranteed as the last
    safety net. Source: explicit `tiers`, else ROKID_SOLVER_TIERS (csv), else
    the single routed solver."""
    if tiers is not None:
        names = list(tiers)
    else:
        env = os.environ.get("ROKID_SOLVER_TIERS")
        names = (
            [t.strip() for t in env.split(",") if t.strip()]
            if env
            else [_select_name(None)]
        )
    if DEFAULT_SOLVER not in names:
        names.append(DEFAULT_SOLVER)
    return names


def _acceptable(result) -> bool:
    """An answer is usable if the tier didn't flag an error and produced text."""
    if result is None or result.extras.get("error"):
        return False
    return bool((result.answer or "").strip())


def solve_with_fallback(
    question, *, tiers: list[str] | None = None, max_answer_len: int = 64
):
    """Two-tier (multi-tier) fallback: try solver tiers in order and return
    `(result, solver)` for the first that yields an acceptable answer, always
    falling back to the offline local solver as a final safety net.

    A tier "fails" if `solve` raises, flags `extras['error']`, or returns an
    empty answer. The winning tier is recorded in `result.extras['served_by']`
    and any skipped tiers in `result.extras['fallback_from']`.
    """
    names = _tier_names(tiers)
    skipped: list[str] = []
    last_result = None
    last_solver = None
    for name in names:
        solver = get_solver(name)
        last_solver = solver
        try:
            result = solver.solve(question=question, max_answer_len=max_answer_len)
        except Exception:  # noqa: BLE001 - one tier failing must not 500
            skipped.append(f"{name}:error")
            continue
        last_result = result
        if _acceptable(result):
            result.extras["served_by"] = solver.name
            if skipped:
                result.extras["fallback_from"] = skipped
            return result, solver
        skipped.append(f"{name}:empty")

    # Nothing acceptable; return the last result (the local default never
    # returns an empty answer, so this is effectively the placeholder).
    if last_result is not None:
        last_result.extras["served_by"] = last_solver.name
        last_result.extras["fallback_from"] = skipped
        return last_result, last_solver
    solver = get_solver(DEFAULT_SOLVER)
    result = solver.solve(question=question, max_answer_len=max_answer_len)
    result.extras["served_by"] = solver.name
    return result, solver


# Register the offline default at import time so the server always has one.
register_solver(LocalPlaceholderSolver(), replace=True)
# Register the real cloud solvers (Anthropic Claude / OpenAI / Google Gemini).
# Each only touches the network when routed to AND its provider API key is set;
# otherwise solve() raises and solve_with_fallback drops back to local.
for _name, _provider in (("claude", "anthropic"), ("openai", "openai"), ("gemini", "gemini")):
    register_solver(LLMSolver(name=_name, provider=_provider), replace=True)

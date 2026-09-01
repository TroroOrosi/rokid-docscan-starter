"""Solver registry + model routing (mirrors app/analyzers/registry.py).

A tiny provider registry so the active solver is chosen by name/feature flag,
not hard-coded (routing rules: app/provider_registry.py — prefer arg >
ROKID_SOLVER > local). On top of the shared registry, solvers add the
multi-tier `solve_with_fallback`: if the requested solver is missing or fails
(e.g. cloud adapter not installed / no creds), it falls back to the offline
local placeholder so the server keeps working (offline-first / two-tier
fallback).
"""

from __future__ import annotations

import os

from .. import config
from ..llm import ADAPTER_PROVIDERS
from ..provider_registry import ProviderRegistry
from .base import Solver
from .llm_adapter import LLMSolver
from .local_placeholder import LocalPlaceholderSolver

DEFAULT_SOLVER = "local"

_registry = ProviderRegistry(
    kind="solver",
    env_var="ROKID_SOLVER",
    default_factory=LocalPlaceholderSolver,
    default_name=DEFAULT_SOLVER,
)


def register_solver(solver: Solver, *, replace: bool = False) -> None:
    _registry.register(solver, replace=replace)


def list_solvers() -> list[dict]:
    return _registry.list()


def _select_name(prefer: str | None) -> str:
    return _registry.select_name(prefer)


def get_solver(prefer: str | None = None) -> Solver:
    """Return a solver by routing rules, falling back to the local one."""
    return config.require_real_provider("solver", _registry.get(prefer))


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
    if not config.REAL_MODE and DEFAULT_SOLVER not in names:
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
        # An unknown/mistyped tier name (e.g. ROKID_SOLVER_TIERS="claud,claude")
        # must not silently coerce to the local placeholder mid-list — that
        # would "answer" before the real later tiers get a chance. Skip it and
        # record it; local stays available as the guaranteed final tier.
        if name not in _registry and name != DEFAULT_SOLVER:
            skipped.append(f"{name}:unknown")
            continue
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

    if config.REAL_MODE:
        raise RuntimeError(
            "ROKID_REAL_MODE=1: every configured real solver tier failed; "
            "placeholder fallback is disabled"
        )

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
# Register the real cloud solvers (OpenAI GPT / Google Gemini / Anthropic
# Claude). Each only touches the network when routed to AND its provider API
# key is set; otherwise solve() raises and solve_with_fallback drops to local.
for _name, _provider in ADAPTER_PROVIDERS:
    register_solver(LLMSolver(name=_name, provider=_provider), replace=True)

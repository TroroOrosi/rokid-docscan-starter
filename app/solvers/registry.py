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


# Register the offline default at import time so the server always has one.
register_solver(LocalPlaceholderSolver(), replace=True)

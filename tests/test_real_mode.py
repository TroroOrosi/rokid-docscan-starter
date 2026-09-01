"""Real-device mode must never degrade to placeholder providers."""

from __future__ import annotations

import pytest

from app import config
from app.analyzers import get_analyzer
from app.analyzers.llm_adapter import LLMAnalyzer
from app.llm import LLMClient
from app.solvers import Question, get_solver, solve_with_fallback


class _FailingModels:
    def generate_content(self, **kwargs):
        raise RuntimeError("provider unavailable")


def test_real_mode_rejects_local_analyzer_and_solver(monkeypatch):
    monkeypatch.setattr(config, "REAL_MODE", True)

    with pytest.raises(RuntimeError, match="analyzer"):
        get_analyzer("local")
    with pytest.raises(RuntimeError, match="solver"):
        get_solver("local")


def test_real_mode_rejects_unknown_provider_fallback(monkeypatch):
    monkeypatch.setattr(config, "REAL_MODE", True)

    with pytest.raises(RuntimeError, match="analyzer"):
        get_analyzer("not-registered")
    with pytest.raises(RuntimeError, match="solver"):
        get_solver("not-registered")


def test_real_mode_solver_failure_does_not_fall_back_to_local(monkeypatch):
    monkeypatch.setattr(config, "REAL_MODE", True)

    with pytest.raises(RuntimeError, match="placeholder"):
        solve_with_fallback(Question(body_text="q"), tiers=["local"])


def test_real_mode_analyzer_provider_failure_is_loud(monkeypatch):
    monkeypatch.setattr(config, "REAL_MODE", True)
    analyzer = LLMAnalyzer(
        name="gemini",
        provider="gemini",
        client=LLMClient(
            type("Sdk", (), {"models": _FailingModels()})(),
            provider="gemini",
            model="test",
        ),
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        analyzer.analyze(ocr_text="page text")

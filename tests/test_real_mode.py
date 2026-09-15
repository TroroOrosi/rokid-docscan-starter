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


def test_real_mode_accepts_explicit_client_ocr_but_still_checks_readiness(monkeypatch):
    monkeypatch.setattr(config, "REAL_MODE", True)
    analyzer = get_analyzer("client-ocr")
    assert analyzer.info()["offline"] is True
    assert analyzer.analyze(ocr_text="問1 1+1を答えよ").text == "問1 1+1を答えよ"
    assert not analyzer.analyze(image_path="photo.png").text
    monkeypatch.setattr(analyzer, "ready", lambda: False)
    with pytest.raises(RuntimeError, match="unready analyzer"):
        get_analyzer("client-ocr")


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


def test_required_images_cannot_fall_back_to_text_or_omit_a_second_page(monkeypatch, tmp_path):
    import app.solvers.registry as registry
    from app.solvers.llm_adapter import LLMSolver

    class Client:
        model = "test"
        fail = True

        def complete_json(self, **kwargs):
            if self.fail:
                raise RuntimeError("image provider unavailable")
            return {"status": "ready", "answer": "2"}

    class TextOnly(LLMSolver):
        accepts_images = False

        def solve(self, **kwargs):
            pytest.fail("required images must not reach a text-only fallback")

    image_client = Client()
    image_solver = LLMSolver(name="image-fails", client=image_client)
    text_solver = TextOnly(name="text-only", client=Client())
    monkeypatch.setattr(registry._registry, "_items", {
        image_solver.name: image_solver, text_solver.name: text_solver,
    })
    monkeypatch.setattr(config, "REAL_MODE", True)
    image = tmp_path / "page.png"
    image.write_bytes(b"test image bytes")
    for required in ([str(image)], [str(image), str(tmp_path / "second.png")]):
        image_client.fail = len(required) == 1
        question = Question(answer_only=True, image_path=str(image), required_image_paths=required)
        with pytest.raises(RuntimeError, match="no configured solver"):
            solve_with_fallback(question, tiers=[image_solver.name, text_solver.name])

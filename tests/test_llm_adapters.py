"""Tests for the real Claude adapters — offline, via an injected fake client.

Covers: (1) each adapter parses a real model reply into its port's result type;
(2) the "claude" adapter is registered and routable in every registry;
(3) graceful degradation when unconfigured — the solver raises so the two-tier
fallback picks local, while analyzer/explainer/extractor fall back internally.
"""

from types import SimpleNamespace

from app.analyzers.claude import ClaudeAnalyzer
from app.analyzers import get_analyzer, list_analyzers
from app.explainer import ExplainRequest
from app.explainers.claude import ClaudeExplainer
from app.explainers import get_explainer, list_explainers
from app.extractors.claude import ClaudeExtractor
from app.extractors import get_extractor, list_extractors
from app.llm import LLMClient
from app.solvers import Question, get_solver, list_solvers, solve_with_fallback
from app.solvers.claude import ClaudeSolver


def _client(reply: str) -> LLMClient:
    sdk = SimpleNamespace(
        messages=SimpleNamespace(
            create=lambda **kw: SimpleNamespace(
                content=[SimpleNamespace(type="text", text=reply)]
            )
        )
    )
    return LLMClient(sdk, model="claude-test")


# --- solver -----------------------------------------------------------------

def test_claude_solver_parses_structured_answer():
    reply = (
        '{"answer": "B: 13", "solution_steps": ["step1", "step2"], '
        '"rationale": "because", "cautions": "check units", '
        '"answer_confidence": 0.8, "rationale_confidence": 0.7, '
        '"raw_reasoning": "long"}'
    )
    solver = ClaudeSolver(client=_client(reply))
    r = solver.solve(question=Question(body_text="2x+3=7", choices=["12", "13"]))
    assert r.answer == "B: 13"
    assert r.solution_steps == ["step1", "step2"]
    assert r.answer_confidence == 0.8
    assert r.extras["source"] == "claude"


def test_claude_solver_served_via_fallback_tiers():
    from app.solvers import register_solver

    register_solver(ClaudeSolver(client=_client('{"answer": "X"}')), replace=True)
    result, solver = solve_with_fallback(
        Question(body_text="q"), tiers=["claude"]
    )
    assert solver.name == "claude"
    assert result.answer == "X"
    assert result.extras["served_by"] == "claude"


def test_claude_solver_unconfigured_falls_back_to_local(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from app.solvers import register_solver

    register_solver(ClaudeSolver(), replace=True)  # no injected client, no key
    result, solver = solve_with_fallback(Question(body_text="q"), tiers=["claude"])
    assert solver.name == "local"
    assert any("claude" in s for s in result.extras["fallback_from"])


def test_claude_solver_registered():
    assert "claude" in [s["name"] for s in list_solvers()]


# --- analyzer ---------------------------------------------------------------

def test_claude_analyzer_parses_summary():
    a = ClaudeAnalyzer(client=_client('{"summary": "設計仕様の概要", "language": "ja"}'))
    res = a.analyze(ocr_text="設計仕様書 第1章 ...")
    assert res.summary == "設計仕様の概要"
    assert res.language == "ja"
    assert res.extras["source"] == "claude"


def test_claude_analyzer_unconfigured_falls_back(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    a = ClaudeAnalyzer()  # no client, no key -> local placeholder
    res = a.analyze(ocr_text="First line\nsecond")
    assert res.summary == "First line"


def test_claude_analyzer_registered():
    assert "claude" in [a["name"] for a in list_analyzers()]


# --- explainer --------------------------------------------------------------

def test_claude_explainer_forces_three_lines():
    reply = '{"lines": ["a", "b"], "detail": "d", "confidence": 0.9}'
    e = ClaudeExplainer(client=_client(reply))
    res = e.explain(ExplainRequest(page_index=0, page_ocr_text="text", page_summary="s"))
    assert len(res.lines) == 3
    assert res.confidence == 0.9


def test_claude_explainer_unconfigured_falls_back(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    e = ClaudeExplainer()
    res = e.explain(ExplainRequest(page_index=0, page_ocr_text="hello world", page_summary=None))
    assert len(res.lines) == 3  # local placeholder always pads to 3


def test_claude_explainer_registered():
    assert "claude" in [e["name"] for e in list_explainers()]


# --- extractor --------------------------------------------------------------

def test_claude_extractor_parses_content():
    reply = '{"kind": "math", "content": "x = 2", "confidence": 0.95}'
    ex = ClaudeExtractor(client=_client(reply))
    res = ex.extract(ocr_text="2x = 4", kind="math")
    assert res.kind == "math"
    assert res.content == "x = 2"
    assert res.confidence == 0.95


def test_claude_extractor_unconfigured_falls_back(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ex = ClaudeExtractor()
    res = ex.extract(ocr_text="y = 2x + 1")
    assert res.kind == "math"  # local placeholder heuristic


def test_claude_extractor_registered():
    assert "claude" in [e["name"] for e in list_extractors()]

"""Tests for the real cloud adapters — offline, via an injected fake client.

Covers: (1) each adapter parses a real model reply into its port's result type;
(2) the claude/openai/gemini adapters are registered and routable in every
registry; (3) graceful degradation when unconfigured — the solver raises so the
two-tier fallback picks local, while analyzer/explainer/extractor fall back
internally.
"""

from types import SimpleNamespace

from app.analyzers.claude import ClaudeAnalyzer, LLMAnalyzer
from app.analyzers import get_analyzer, list_analyzers
from app.explainer import ExplainRequest
from app.explainers.claude import ClaudeExplainer, LLMExplainer
from app.explainers import get_explainer, list_explainers
from app.extractors.claude import ClaudeExtractor, LLMExtractor
from app.extractors import get_extractor, list_extractors
from app.llm import LLMClient
from app.solvers import Question, get_solver, list_solvers, solve_with_fallback
from app.solvers.claude import ClaudeSolver, LLMSolver


def _client(reply: str, provider: str = "anthropic") -> LLMClient:
    """Build an LLMClient wrapping a fake SDK of the given provider's shape."""
    if provider == "anthropic":
        sdk = SimpleNamespace(
            messages=SimpleNamespace(
                create=lambda **kw: SimpleNamespace(
                    content=[SimpleNamespace(type="text", text=reply)]
                )
            )
        )
    elif provider == "openai":
        sdk = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **kw: SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content=reply))]
                    )
                )
            )
        )
    else:  # gemini
        sdk = SimpleNamespace(
            models=SimpleNamespace(generate_content=lambda **kw: SimpleNamespace(text=reply))
        )
    return LLMClient(sdk, provider=provider, model=f"{provider}-test")


# --- solver -----------------------------------------------------------------

def test_claude_solver_parses_structured_answer():
    reply = (
        '{"answer": "B: 13", "solution_steps": ["step1"], "rationale": "because", '
        '"cautions": "check units", "answer_confidence": 0.8, '
        '"rationale_confidence": 0.7, "raw_reasoning": "long"}'
    )
    r = ClaudeSolver(client=_client(reply)).solve(
        question=Question(body_text="2x+3=7", choices=["12", "13"])
    )
    assert r.answer == "B: 13"
    assert r.answer_confidence == 0.8
    assert r.extras["source"] == "claude"
    assert r.extras["provider"] == "anthropic"


def test_openai_and_gemini_solvers_parse():
    for provider in ("openai", "gemini"):
        solver = LLMSolver(name=provider, provider=provider, client=_client('{"answer": "X"}', provider))
        r = solver.solve(question=Question(body_text="q"))
        assert r.answer == "X"
        assert r.extras["provider"] == provider


def test_solver_sends_page_image_when_present(tmp_path):
    png = tmp_path / "q.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"payload")
    calls = []

    def create(**kw):
        calls.append(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text='{"answer": "A"}')])

    sdk = SimpleNamespace(messages=SimpleNamespace(create=create))
    solver = LLMSolver(
        name="claude", provider="anthropic",
        client=LLMClient(sdk, provider="anthropic", model="m"),
    )
    r = solver.solve(question=Question(body_text="q", subject="数学", image_path=str(png)))
    assert r.answer == "A"
    content = calls[0]["messages"][0]["content"]
    assert isinstance(content, list)  # vision: image block + text block
    assert any(b.get("type") == "image" for b in content)
    text_block = next(b for b in content if b.get("type") == "text")["text"]
    assert "解き方" in text_block  # subject-tailored guidance is included


def test_solver_text_only_when_no_image():
    calls = []

    def create(**kw):
        calls.append(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text='{"answer": "B"}')])

    sdk = SimpleNamespace(messages=SimpleNamespace(create=create))
    solver = LLMSolver(
        name="claude", provider="anthropic",
        client=LLMClient(sdk, provider="anthropic", model="m"),
    )
    r = solver.solve(question=Question(body_text="q"))  # no image_path
    assert r.answer == "B"
    assert isinstance(calls[0]["messages"][0]["content"], str)  # text-only


def test_solver_served_via_fallback_tiers():
    from app.solvers import register_solver

    register_solver(LLMSolver(name="openai", provider="openai", client=_client('{"answer": "Y"}', "openai")), replace=True)
    result, solver = solve_with_fallback(Question(body_text="q"), tiers=["openai"])
    assert solver.name == "openai"
    assert result.answer == "Y"
    assert result.extras["served_by"] == "openai"


def test_solver_unconfigured_falls_back_to_local(monkeypatch):
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    from app.solvers import register_solver

    register_solver(LLMSolver(name="gemini", provider="gemini"), replace=True)  # no client, no key
    result, solver = solve_with_fallback(Question(body_text="q"), tiers=["gemini"])
    assert solver.name == "local"
    assert any("gemini" in s for s in result.extras["fallback_from"])


def test_all_providers_registered_solvers():
    names = [s["name"] for s in list_solvers()]
    for n in ("local", "claude", "openai", "gemini"):
        assert n in names


# --- analyzer / explainer / extractor: parse + registration + fallback ------

def test_claude_analyzer_parses_summary():
    a = ClaudeAnalyzer(client=_client('{"summary": "設計仕様の概要", "language": "ja"}'))
    res = a.analyze(ocr_text="設計仕様書 第1章 ...")
    assert res.summary == "設計仕様の概要"
    assert res.language == "ja"
    assert res.extras["source"] == "claude"


def test_openai_analyzer_parses_summary():
    a = LLMAnalyzer(name="openai", provider="openai", client=_client('{"summary": "ok"}', "openai"))
    assert a.analyze(ocr_text="text").summary == "ok"


def test_analyzer_unconfigured_falls_back(monkeypatch):
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    assert LLMAnalyzer(name="openai", provider="openai").analyze(ocr_text="First line\nsecond").summary == "First line"


def test_gemini_explainer_forces_three_lines():
    reply = '{"lines": ["a", "b"], "detail": "d", "confidence": 0.9}'
    e = LLMExplainer(name="gemini", provider="gemini", client=_client(reply, "gemini"))
    res = e.explain(ExplainRequest(page_index=0, page_ocr_text="text", page_summary="s"))
    assert len(res.lines) == 3
    assert res.confidence == 0.9


def test_extractor_parses_and_registers():
    ex = ClaudeExtractor(client=_client('{"kind": "math", "content": "x = 2", "confidence": 0.95}'))
    res = ex.extract(ocr_text="2x = 4", kind="math")
    assert res.kind == "math" and res.content == "x = 2"


def test_all_providers_registered_everywhere():
    for lister in (list_analyzers, list_explainers, list_extractors):
        names = [x["name"] for x in lister()]
        for n in ("local", "claude", "openai", "gemini"):
            assert n in names


def test_default_routing_still_local():
    assert get_solver().name == "local"
    assert get_analyzer().name == "local"
    assert get_explainer().name == "local"
    assert get_extractor().name == "local"


def test_adapters_fall_back_when_sdk_missing(monkeypatch):
    """Key set but provider SDK not installed: get_client raises LLMConfigError.

    analyzer/explainer/extractor must NOT propagate it (their contracts forbid
    raising) — finalize/explain/add_question would otherwise 500. They degrade to
    the offline local placeholder.
    """
    from app.llm import LLMConfigError

    def _raise(*a, **k):
        raise LLMConfigError("provider key set but its SDK is not installed")

    import app.analyzers.claude as an
    import app.explainers.claude as ex
    import app.extractors.claude as xt

    monkeypatch.setattr(an, "get_client", _raise)
    monkeypatch.setattr(ex, "get_client", _raise)
    monkeypatch.setattr(xt, "get_client", _raise)

    # analyzer -> local summary (first non-empty line)
    a = an.LLMAnalyzer(name="openai", provider="openai")
    assert a.analyze(ocr_text="First line\nsecond").summary == "First line"
    # explainer -> local placeholder still yields exactly 3 HUD lines
    res = ex.LLMExplainer(name="gemini", provider="gemini").explain(
        ExplainRequest(page_index=0, page_ocr_text="text", page_summary="s")
    )
    assert len(res.lines) == 3
    # extractor -> local placeholder, no raise
    r = xt.LLMExtractor(name="openai", provider="openai").extract(ocr_text="2x=4", kind="math")
    assert r.kind == "math"

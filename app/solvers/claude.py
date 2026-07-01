"""Cloud-backed question solver (real, model-connected answering).

Production counterpart to ``LocalPlaceholderSolver``. Sends the structured
question (body, choices, retrieved RAG context) to a cloud LLM and parses a
structured :class:`SolveResult` back. Provider-agnostic: one class, selected by
adapter name == provider (``claude`` / ``openai`` / ``gemini``).

Routing: ``ROKID_SOLVER=claude|openai|gemini`` (or those names in
``ROKID_SOLVER_TIERS``). When unconfigured (no provider key / model) or the call
fails, ``solve`` raises so :func:`app.solvers.registry.solve_with_fallback`
transparently drops back to the offline local solver.

The real-exam lock is enforced in ``app/main.py`` regardless of solver, so
wiring a real model here does not weaken it.
"""

from __future__ import annotations

from ..llm import LLMClient, LLMConfigError, get_client
from .base import Question, SolveResult, Solver

_SYSTEM = (
    "You are an exam-study assistant for a Rokid Glasses heads-up display. "
    "Solve the given question and reply with a SINGLE minified JSON object, no "
    "markdown, no prose outside the JSON. Keys: "
    '"answer" (string; for multiple choice use the label form "B: text"), '
    '"solution_steps" (array of short strings), '
    '"rationale" (string), "cautions" (string), '
    '"answer_confidence" (0..1 number), "rationale_confidence" (0..1 number), '
    '"raw_reasoning" (string; longer reasoning kept off the HUD). '
    "Answer in the language of the question. Keep each field concise."
)


class LLMSolver(Solver):
    offline = False

    def __init__(self, *, name: str = "claude", provider: str = "anthropic",
                 client: LLMClient | None = None):
        self.name = name
        self.provider = provider
        self.provider_version = f"{provider}-messages-1.0.0"
        self._client = client

    def solve(self, *, question: Question, max_answer_len: int = 64) -> SolveResult:
        client = get_client(self._client, self.provider)
        if client is None:
            # Unconfigured -> let solve_with_fallback drop to the local solver.
            raise LLMConfigError(f"{self.name} solver requires its provider API key/model")

        data = client.complete_json(system=_SYSTEM, prompt=_build_prompt(question))
        answer = str(data.get("answer", "")).strip()[:max_answer_len]
        return SolveResult(
            answer=answer,
            solution_steps=[str(s) for s in data.get("solution_steps", []) if str(s).strip()],
            rationale=str(data.get("rationale", "")),
            cautions=str(data.get("cautions", "")),
            subject=question.subject,
            answer_confidence=_clamp(data.get("answer_confidence")),
            rationale_confidence=_clamp(data.get("rationale_confidence")),
            raw_reasoning=str(data.get("raw_reasoning", "")),
            extras={"source": self.name, "provider": self.provider, "model": client.model},
        )


class ClaudeSolver(LLMSolver):
    """Back-compat alias: the Anthropic-backed solver registered as ``claude``."""

    def __init__(self, client: LLMClient | None = None):
        super().__init__(name="claude", provider="anthropic", client=client)


def _build_prompt(question: Question) -> str:
    lines = []
    if question.subject:
        lines.append(f"科目/Subject: {question.subject}")
    lines.append("問題/Question:")
    lines.append(question.body_text or "(no text)")
    if question.choices:
        lines.append("選択肢/Choices:")
        for i, choice in enumerate(question.choices):
            label = chr(ord("A") + i) if i < 26 else str(i + 1)
            lines.append(f"{label}. {choice}")
    if question.context:
        lines.append("参考資料/Reference context (from the user's own notes):")
        lines.append(question.context)
    return "\n".join(lines)


def _clamp(value, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default

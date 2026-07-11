"""Cloud-backed question solver (real, model-connected answering).

Production counterpart to ``LocalPlaceholderSolver``. Sends the structured
question (body, choices, retrieved RAG context) to a cloud LLM and parses a
structured :class:`SolveResult` back. Provider-agnostic: one class, selected by
adapter name == provider (``openai`` / ``gemini`` / ``claude``).

Routing: ``ROKID_SOLVER=openai|gemini|claude`` (or those names in
``ROKID_SOLVER_TIERS``). When unconfigured (no provider key / model) or the call
fails, ``solve`` raises so :func:`app.solvers.registry.solve_with_fallback`
transparently drops back to the offline local solver.

The real-exam lock is enforced in ``app/main.py`` regardless of solver, so
wiring a real model here does not weaken it.
"""

from __future__ import annotations

from ..llm import LLMClient, LLMConfigError, clamp01, get_client
from .base import Question, SolveResult, Solver

_SYSTEM = (
    "You are an exam tutor solving a single question captured from a paper exam "
    "for a Rokid Glasses heads-up display. When a page image is attached, treat "
    "the IMAGE as the primary source (read figures, equations, tables, graphs "
    "and choices directly); any provided OCR text is a possibly-imperfect aid. "
    "Work the problem out fully, then give the final answer. "
    "Reply with a SINGLE minified JSON object, no markdown, no prose outside it. "
    "Keys: "
    '"answer" (string; for multiple choice use the label form "B: text"; state '
    "the final answer clearly with units where relevant), "
    '"solution_steps" (array of short step strings), '
    '"rationale" (string, why the answer is correct, cite the passage/figure), '
    '"cautions" (string; note assumptions or anything unreadable/uncertain), '
    '"answer_confidence" (0..1 number), "rationale_confidence" (0..1 number), '
    '"raw_reasoning" (string; longer working kept off the HUD). '
    "Answer in the language of the question. If the problem is unreadable, say so "
    "in cautions and give a low answer_confidence rather than guessing."
)

# Short, subject-tailored solving guidance appended to the user prompt so the
# model works each subject the way a grader expects (共通テスト準拠の実教科).
_SUBJECT_GUIDANCE = {
    "数学": "立式→計算→検算の順に解き、最終解答は単位付きで明示。",
    "物理": "既知量を整理し立式→代入計算→単位付きの数値解。有効数字に注意。",
    "化学": "反応式・物質量(mol)を立て、計算過程と単位付きの数値解を示す。",
    "生物": "図・グラフの読み取りを根拠に、用語を正確に用いて説明。",
    "地学": "図・データを根拠に、現象の因果を説明。",
    "現代文": "本文の該当箇所を根拠に、設問要求(記述/選択)に沿って答える。",
    "古文": "現代語訳を示し、助動詞・敬語・係り結び等の文法を根拠にする。",
    "漢文": "書き下し文と現代語訳を示し、句法・返り点を根拠にする。",
    "英語": "設問に答え、本文の根拠箇所を示す。和訳は自然な日本語で。",
    "世界史": "年代・地域・因果関係を整理して答える。",
    "日本史": "時代・人物・出来事の因果関係を整理して答える。",
    "地理": "地図・統計・気候データの読み取りを根拠に答える。",
    "倫理": "思想家・概念を正確に対応づけて答える。",
    "政治経済": "制度・数値(需給/GDP等)の因果を踏まえて答える。",
    "現代社会": "制度・時事の因果を踏まえて答える。",
    "情報": "擬似言語/2進数/論理演算/アルゴリズムを段階的に処理して答える。",
}


def _subject_guidance(subject: str | None) -> str:
    return _SUBJECT_GUIDANCE.get(subject or "", "")


def _read_image(path: str | None) -> bytes | None:
    if not path:
        return None
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


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

        # Vision: attach the captured page image so the model reads figures /
        # equations / tables directly. Falls back to text-only when absent.
        image = _read_image(question.image_path)
        data = client.complete_json(
            system=_SYSTEM, prompt=_build_prompt(question), image=image
        )
        answer = str(data.get("answer", "")).strip()[:max_answer_len]
        return SolveResult(
            answer=answer,
            solution_steps=[str(s) for s in data.get("solution_steps", []) if str(s).strip()],
            rationale=str(data.get("rationale", "")),
            cautions=str(data.get("cautions", "")),
            subject=question.subject,
            answer_confidence=clamp01(data.get("answer_confidence")),
            rationale_confidence=clamp01(data.get("rationale_confidence")),
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
        guidance = _subject_guidance(question.subject)
        if guidance:
            lines.append(f"解き方/Guidance: {guidance}")
    lines.append("問題(OCR、画像がある場合は画像を優先)/Question (OCR; prefer the image if attached):")
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


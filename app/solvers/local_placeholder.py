"""Local, offline, credential-free solver used by the MVP today.

It performs NO real problem solving. It returns a clearly-marked placeholder so
the server runs end-to-end with zero external dependencies while presenting the
exact interface a real model-backed solver (Gemini/OpenAI/Claude/on-device VLM)
will later implement. Real answering = register a model adapter under another
name and route to it (ROKID_SOLVER / prefer).

Keeping the offline default non-solving is also a deliberate guardrail: the MVP
cannot be used to actually answer a live exam.
"""

from __future__ import annotations

import hashlib

from ..matching import normalize_ocr_text
from .base import Question, SolveResult, Solver


class LocalPlaceholderSolver(Solver):
    name = "local"
    provider_version = "placeholder-1.0.0"
    offline = True

    def solve(self, *, question: Question, max_answer_len: int = 64) -> SolveResult:
        body = normalize_ocr_text(question.body_text)
        if not body and not question.choices:
            return SolveResult(
                answer="(未解答)",
                rationale="問題文を読み取れませんでした",
                cautions="近づけて再撮影してください",
                subject=question.subject,
                answer_confidence=0.0,
                rationale_confidence=0.0,
                extras={"placeholder": True},
            )

        # Deterministic placeholder pick so behaviour is stable and testable.
        seed = int(hashlib.md5((body or "").encode("utf-8")).hexdigest(), 16)
        if question.choices:
            idx = seed % len(question.choices)
            answer = _label_for(idx, question.choices[idx], max_answer_len)
        else:
            answer = "(要モデル接続)"

        return SolveResult(
            answer=answer,
            solution_steps=["プレースホルダ: 実モデル未接続のため解法は生成されません"],
            rationale="(プレースホルダ) 実際の解答にはモデルアダプタの登録が必要です",
            cautions="参考値です。断定しないでください",
            subject=question.subject,
            # Deliberately low: this is not a real answer.
            answer_confidence=0.2,
            rationale_confidence=0.1,
            raw_reasoning="",
            extras={"placeholder": True, "source": "local_placeholder"},
        )


def _label_for(idx: int, choice_text: str, max_len: int) -> str:
    """Render a multiple-choice pick as e.g. 'B: ...' (best-effort)."""
    label = chr(ord("A") + idx) if idx < 26 else str(idx + 1)
    text = (choice_text or "").strip()
    return f"{label}: {text}"[:max_len] if text else label

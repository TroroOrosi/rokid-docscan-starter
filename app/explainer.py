"""Explainer port (a 'port' in ports-and-adapters terms).

An Explainer turns a matched page (OCR text + summary) plus multi-page
RAG context into a short, HUD-friendly explanation.

This is intentionally separate from the Analyzer port:
- Analyzer: page image -> text / summary / embedding  (ingestion time)
- Explainer: matched page + context -> live HUD explanation  (query time)

Concrete adapters (local placeholder today; Gemini/OpenAI/Claude later)
implement this interface and register via ROKID_EXPLAINER env var.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field

_MAX_LINE_CHARS = 24  # mirrors glasses_view.py constant


@dataclass
class ExplainRequest:
    """Input to an Explainer."""

    page_index: int
    page_ocr_text: str | None
    page_summary: str | None
    # Top-k context pages from retrieval.py: [{page_index, snippet, score}]
    context_pages: list[dict] = field(default_factory=list)
    document_title: str | None = None


@dataclass
class ExplainResult:
    """Explainer output."""

    # Exactly 3 short lines for the on-glasses HUD (<=24 chars each).
    lines: list[str]
    # Long-form explanation stored server-side (history endpoint, not HUD).
    detail: str = ""
    # User-facing, 1-based page numbers used as context evidence.
    evidence_pages: list[int] = field(default_factory=list)
    # Structured cross-document references ({document_id, page_number}), with
    # page_number user-facing/1-based.
    evidence_refs: list[dict] = field(default_factory=list)
    # 0..1 confidence (1.0 for placeholder, real LLM may vary).
    confidence: float = 1.0
    # Free-form provider diagnostics; never relied on by the server.
    extras: dict = field(default_factory=dict)


class Explainer(abc.ABC):
    """Provider-agnostic explainer port."""

    #: Stable registry key, e.g. "local", "gemini", "openai", "claude".
    name: str = "base"
    #: Provider/model identity surfaced in responses.
    provider_version: str = "0.0.0"
    #: True if this adapter runs fully offline (no network, no creds).
    offline: bool = True

    @abc.abstractmethod
    def explain(self, req: ExplainRequest) -> ExplainResult:
        """Return an ExplainResult. Must not raise on empty input."""

    def info(self) -> dict:
        return {
            "name": self.name,
            "provider_version": self.provider_version,
            "offline": self.offline,
        }

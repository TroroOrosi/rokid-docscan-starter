"""Claude-backed page explainer (real live document explanation).

Production counterpart to ``LocalPlaceholderExplainer``. Given the current page
(OCR text + summary) plus multi-page RAG context, it produces a genuine 3-line
HUD explanation and a longer stored detail via the Anthropic Messages API.

Routing: ``ROKID_EXPLAINER=claude``. If unconfigured or the call fails, it
falls back to the offline local explainer (the Explainer contract forbids
raising), so the explain-session HUD always renders.
"""

from __future__ import annotations

from ..explainer import ExplainRequest, ExplainResult, Explainer
from ..llm import LLMClient, get_client
from .local_placeholder import LocalPlaceholderExplainer

_SYSTEM = (
    "You explain one page of a document for a tiny monochrome heads-up display. "
    "Reply with a SINGLE minified JSON object, no markdown. Keys: "
    '"lines" (array of EXACTLY 3 short strings, each a HUD line in the page '
    'language), "detail" (a longer paragraph kept off the HUD), '
    '"confidence" (0..1 number). Explain, do not just repeat the text."'
)


class ClaudeExplainer(Explainer):
    name = "claude"
    provider_version = "anthropic-messages-1.0.0"
    offline = False

    def __init__(self, client: LLMClient | None = None):
        self._client = client
        self._fallback = LocalPlaceholderExplainer()

    def explain(self, req: ExplainRequest) -> ExplainResult:
        client = get_client(self._client)
        source = req.page_summary or req.page_ocr_text or ""
        if client is None or not source.strip():
            return self._fallback.explain(req)
        try:
            data = client.complete_json(system=_SYSTEM, prompt=_build_prompt(req))
        except Exception:  # noqa: BLE001 - never break the HUD; degrade to local
            return self._fallback.explain(req)

        lines = [str(x) for x in data.get("lines", []) if str(x).strip()][:3]
        while len(lines) < 3:
            lines.append("")
        evidence = [
            p["page_index"]
            for p in req.context_pages
            if isinstance(p.get("page_index"), int)
        ]
        return ExplainResult(
            lines=lines,
            detail=str(data.get("detail", source[:400])),
            evidence_pages=evidence,
            confidence=_clamp(data.get("confidence"), 1.0),
            extras={"source": "claude", "model": client.model},
        )


def _build_prompt(req: ExplainRequest) -> str:
    lines = []
    if req.document_title:
        lines.append(f"Document: {req.document_title}")
    lines.append(f"Page index: {req.page_index}")
    lines.append("Page text:")
    lines.append(req.page_ocr_text or req.page_summary or "(no text)")
    if req.context_pages:
        lines.append("Related pages (context):")
        for page in req.context_pages:
            snippet = str(page.get("snippet", "")).strip()
            if snippet:
                lines.append(f"- P{page.get('page_index')}: {snippet}")
    return "\n".join(lines)


def _clamp(value, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default

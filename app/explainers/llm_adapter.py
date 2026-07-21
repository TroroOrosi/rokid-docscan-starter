"""Cloud-backed page explainer (real live document explanation).

Production counterpart to ``LocalPlaceholderExplainer``. Given the current page
(OCR text + summary) plus multi-page RAG context, produces a genuine 3-line HUD
explanation and a longer stored detail via a cloud LLM. Provider-agnostic: one
class, selected by adapter name == provider (``openai`` / ``gemini`` / ``claude``).

Routing: ``ROKID_EXPLAINER=openai|gemini|claude``. If unconfigured or the call
fails, it falls back to the offline local explainer (the Explainer contract
forbids raising), so the explain-session HUD always renders.
"""

from __future__ import annotations

from ..explainer import ExplainRequest, ExplainResult, Explainer
from ..llm import LLMClient, clamp01, get_client
from .local_placeholder import LocalPlaceholderExplainer

_SYSTEM = (
    "You explain one page of a document for a tiny monochrome heads-up display. "
    "Reply with a SINGLE minified JSON object, no markdown. Keys: "
    '"lines" (array of EXACTLY 3 short strings, each a HUD line in the page '
    'language), "detail" (a longer paragraph kept off the HUD), '
    '"confidence" (0..1 number). Explain, do not just repeat the text."'
)


class LLMExplainer(Explainer):
    offline = False

    def __init__(self, *, name: str = "claude", provider: str = "anthropic",
                 client: LLMClient | None = None):
        self.name = name
        self.provider = provider
        self.provider_version = f"{provider}-messages-1.0.0"
        self._client = client
        self._fallback = LocalPlaceholderExplainer()

    def explain(self, req: ExplainRequest) -> ExplainResult:
        source = req.page_summary or req.page_ocr_text or ""
        try:
            # get_client may raise LLMConfigError (key set but SDK missing); keep
            # it inside the guard so the explain HUD never 500s (Explainer contract
            # forbids raising) — degrade to the offline local explainer.
            client = get_client(self._client, self.provider)
            if client is None or not source.strip():
                return self._fallback.explain(req)
            data = client.complete_json(system=_SYSTEM, prompt=_build_prompt(req))
        except Exception:  # noqa: BLE001 - never break the HUD; degrade to local
            return self._fallback.explain(req)

        lines = [str(x) for x in data.get("lines", []) if str(x).strip()][:3]
        while len(lines) < 3:
            lines.append("")
        evidence_refs = [
            {
                "document_id": p["document_id"],
                "page_number": p["page_index"] + 1,
            }
            for p in req.context_pages
            if isinstance(p.get("document_id"), int)
            and isinstance(p.get("page_index"), int)
        ]
        return ExplainResult(
            lines=lines,
            detail=str(data.get("detail", source[:400])),
            evidence_pages=[r["page_number"] for r in evidence_refs],
            evidence_refs=evidence_refs,
            confidence=clamp01(data.get("confidence"), 1.0),
            extras={"source": self.name, "provider": self.provider, "model": client.model},
        )


class ClaudeExplainer(LLMExplainer):
    """Back-compat alias: the Anthropic-backed explainer registered as ``claude``."""

    def __init__(self, client: LLMClient | None = None):
        super().__init__(name="claude", provider="anthropic", client=client)


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
                page_number = page.get("page_index", 0) + 1
                lines.append(
                    f"- D{page.get('document_id')}:P{page_number}: {snippet}"
                )
    return "\n".join(lines)

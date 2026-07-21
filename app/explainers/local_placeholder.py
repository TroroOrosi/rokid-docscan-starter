"""Local, offline, credential-free explainer used by default.

It performs no real LLM call: it formats the existing page summary (or
OCR text) into 3 HUD lines and lists context pages as evidence.

This keeps the server runnable with zero external dependencies while
presenting the exact interface a real LLM adapter will later implement.
"""

from __future__ import annotations

from ..explainer import ExplainRequest, ExplainResult, Explainer

_MAX_LINE_CHARS = 24


class LocalPlaceholderExplainer(Explainer):
    name = "local"
    provider_version = "placeholder-1.0.0"
    offline = True

    def explain(self, req: ExplainRequest) -> ExplainResult:
        source = req.page_summary or req.page_ocr_text or ""
        lines = self._split_lines(source)
        detail = source[:400] if source else "(no text)"

        # Build evidence from context_pages supplied by retrieval.py
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
            detail=detail,
            evidence_pages=[r["page_number"] for r in evidence_refs],
            evidence_refs=evidence_refs,
            confidence=1.0,
            extras={"source": "local_placeholder"},
        )

    @staticmethod
    def _split_lines(text: str) -> list[str]:
        """Slice text into at most 3 HUD lines of <= 24 chars each."""
        if not text:
            return ["(no text)", "", ""]
        words = text.split()
        lines: list[str] = []
        current = ""
        for word in words:
            probe = (current + " " + word).strip()
            if len(probe) <= _MAX_LINE_CHARS:
                current = probe
            else:
                if current:
                    lines.append(current)
                if len(lines) >= 3:
                    break
                current = word[:_MAX_LINE_CHARS]
        if current and len(lines) < 3:
            lines.append(current)
        # Pad to exactly 3 lines
        while len(lines) < 3:
            lines.append("")
        return lines[:3]

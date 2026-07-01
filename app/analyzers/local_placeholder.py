"""Local, offline, credential-free analyzer used by default.

It performs no real OCR: it forwards client-provided OCR text and derives a
short summary the same way the original summarize flow did. This keeps the
server runnable with zero external dependencies while presenting the exact
interface a real OCR/LLM adapter will later implement.
"""

from __future__ import annotations

from ..matching import normalize_ocr_text
from .base import Analyzer, AnalyzerResult


class LocalPlaceholderAnalyzer(Analyzer):
    name = "local"
    provider_version = "placeholder-1.0.0"
    offline = True

    def analyze(
        self,
        *,
        image_path: str | None = None,
        ocr_text: str | None = None,
        max_summary_len: int = 48,
    ) -> AnalyzerResult:
        summary = self._summarize(ocr_text, max_summary_len)
        return AnalyzerResult(
            text=ocr_text,
            summary=summary,
            language=None,
            embedding=None,
            extras={"source": "client_ocr_text"},
        )

    @staticmethod
    def _summarize(ocr_text: str | None, max_len: int) -> str:
        if not ocr_text:
            return "(no text)"
        for raw_line in ocr_text.splitlines():
            line = raw_line.strip()
            if line:
                return line[:max_len]
        return normalize_ocr_text(ocr_text)[:max_len] or "(no text)"

"""Cloud-backed page analyzer (real OCR-text summarization).

Production counterpart to ``LocalPlaceholderAnalyzer``. On-device / client OCR
still supplies ``ocr_text``; this adapter turns it into a genuinely useful HUD
summary, language tag, and keyword set via a cloud LLM. Provider-agnostic: one
class, selected by adapter name == provider (``claude`` / ``openai`` / ``gemini``).

Routing: ``ROKID_ANALYZER=claude|openai|gemini``. If unconfigured or the call
fails, it falls back to the offline local analyzer so ``finalize`` never breaks
(the Analyzer contract forbids raising on bad input).
"""

from __future__ import annotations

from ..llm import LLMClient, get_client
from .base import Analyzer, AnalyzerResult
from .local_placeholder import LocalPlaceholderAnalyzer

_SYSTEM = (
    "You summarize a scanned document page for a tiny monochrome heads-up "
    "display. Reply with a SINGLE minified JSON object, no markdown. Keys: "
    '"summary" (one short line, <= {max_len} characters, in the page language), '
    '"language" (BCP-47 code or null), '
    '"keywords" (array of up to 5 short strings). Be faithful to the text.'
)


class LLMAnalyzer(Analyzer):
    offline = False

    def __init__(self, *, name: str = "claude", provider: str = "anthropic",
                 client: LLMClient | None = None):
        self.name = name
        self.provider = provider
        self.provider_version = f"{provider}-messages-1.0.0"
        self._client = client
        self._fallback = LocalPlaceholderAnalyzer()

    def analyze(
        self,
        *,
        image_path: str | None = None,
        ocr_text: str | None = None,
        max_summary_len: int = 48,
    ) -> AnalyzerResult:
        try:
            # get_client may raise LLMConfigError (key set but SDK missing); keep
            # it inside the guard so finalize never 500s — the Analyzer contract
            # forbids raising, so we degrade to the offline local analyzer.
            client = get_client(self._client, self.provider)
            if client is None or not (ocr_text or "").strip():
                return self._fallback.analyze(
                    image_path=image_path, ocr_text=ocr_text, max_summary_len=max_summary_len
                )
            data = client.complete_json(
                system=_SYSTEM.format(max_len=max_summary_len),
                prompt=f"Page OCR text:\n{ocr_text}",
            )
        except Exception:  # noqa: BLE001 - never break finalize; degrade to local
            return self._fallback.analyze(
                image_path=image_path, ocr_text=ocr_text, max_summary_len=max_summary_len
            )
        summary = str(data.get("summary", "")).strip()[:max_summary_len] or "(no text)"
        return AnalyzerResult(
            text=ocr_text,
            summary=summary,
            language=data.get("language") or None,
            embedding=None,
            extras={
                "source": self.name,
                "provider": self.provider,
                "model": client.model,
                "keywords": data.get("keywords", []),
            },
        )


class ClaudeAnalyzer(LLMAnalyzer):
    """Back-compat alias: the Anthropic-backed analyzer registered as ``claude``."""

    def __init__(self, client: LLMClient | None = None):
        super().__init__(name="claude", provider="anthropic", client=client)

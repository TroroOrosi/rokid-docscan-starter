"""Cloud-backed media extractor (real formula / figure / table extraction).

Production counterpart to ``LocalPlaceholderExtractor``. Given OCR text (and a
media kind) it produces a structured representation via a cloud LLM: LaTeX for
math, a flattened cell list for tables, a short description for figures/graphs.
Provider-agnostic: one class, selected by adapter name == provider
(``openai`` / ``gemini`` / ``claude``).

Routing: ``ROKID_EXTRACTOR=openai|gemini|claude``. If unconfigured or the call
fails, it falls back to the offline local placeholder (the MediaExtractor
contract forbids raising).
"""

from __future__ import annotations

from ..llm import LLMClient, get_client
from .base import KINDS, ExtractorResult, MediaExtractor
from .local_placeholder import LocalPlaceholderExtractor

_SYSTEM = (
    "You convert a media region of an exam page into a structured textual form "
    "for downstream solving. Reply with a SINGLE minified JSON object, no "
    'markdown. Keys: "kind" (one of math|figure|graph|table), '
    '"content" (LaTeX for math; a flattened row/cell list for tables; a short '
    'description for figures/graphs), "confidence" (0..1 number).'
)


class LLMExtractor(MediaExtractor):
    offline = False
    kinds = KINDS

    def __init__(self, *, name: str = "claude", provider: str = "anthropic",
                 client: LLMClient | None = None):
        self.name = name
        self.provider = provider
        self.provider_version = f"{provider}-messages-1.0.0"
        self._client = client
        self._fallback = LocalPlaceholderExtractor()

    def extract(
        self,
        *,
        image_path: str | None = None,
        ocr_text: str | None = None,
        kind: str | None = None,
        region: dict | None = None,
    ) -> ExtractorResult:
        try:
            # get_client may raise LLMConfigError (key set but SDK missing); keep
            # it inside the guard so extraction never 500s (MediaExtractor contract
            # forbids raising) — degrade to the offline local extractor.
            client = get_client(self._client, self.provider)
            if client is None or not (ocr_text or "").strip():
                return self._fallback.extract(
                    image_path=image_path, ocr_text=ocr_text, kind=kind, region=region
                )
            data = client.complete_json(
                system=_SYSTEM,
                prompt=f"Requested kind: {kind or 'auto-detect'}\nOCR text:\n{ocr_text}",
            )
        except Exception:  # noqa: BLE001 - never break add_question; degrade to local
            return self._fallback.extract(
                image_path=image_path, ocr_text=ocr_text, kind=kind, region=region
            )
        result_kind = data.get("kind") if data.get("kind") in KINDS else (kind or "figure")
        return ExtractorResult(
            kind=result_kind,
            content=str(data.get("content", "")).strip() or "(no media)",
            confidence=_clamp(data.get("confidence")),
            extras={"source": self.name, "provider": self.provider, "model": client.model},
        )


class ClaudeExtractor(LLMExtractor):
    """Back-compat alias: the Anthropic-backed extractor registered as ``claude``."""

    def __init__(self, client: LLMClient | None = None):
        super().__init__(name="claude", provider="anthropic", client=client)


def _clamp(value, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default

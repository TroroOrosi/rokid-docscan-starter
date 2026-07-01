"""Claude-backed media extractor (real formula / figure / table extraction).

Production counterpart to ``LocalPlaceholderExtractor``. Given the OCR text (and
a media kind) it produces a genuine structured representation via the Anthropic
Messages API: LaTeX for math, a flattened cell list for tables, a short
description for figures/graphs.

Routing: ``ROKID_EXTRACTOR=claude``. If unconfigured or the call fails, it falls
back to the offline local placeholder (the MediaExtractor contract forbids
raising).
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


class ClaudeExtractor(MediaExtractor):
    name = "claude"
    provider_version = "anthropic-messages-1.0.0"
    offline = False
    kinds = KINDS

    def __init__(self, client: LLMClient | None = None):
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
        client = get_client(self._client)
        if client is None or not (ocr_text or "").strip():
            return self._fallback.extract(
                image_path=image_path, ocr_text=ocr_text, kind=kind, region=region
            )
        try:
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
            extras={"source": "claude", "model": client.model},
        )


def _clamp(value, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default

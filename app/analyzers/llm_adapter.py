"""Cloud-backed page analyzer with real image OCR and figure description.

The Android relay always uploads the original Rokid photo and normally also
supplies bundled ML Kit OCR. When the client OCR is empty or incomplete, a
configured vision-capable provider reads the photo here. Provider output is
returned through the stable AnalyzerResult contract:

* ``text`` contains the complete page transcription,
* ``summary`` is a short page label,
* ``extras["vision_text"]`` describes figures, equations, tables and layout.

Routing: ``ROKID_ANALYZER=openai|gemini|claude``. If no provider is configured
or a call fails, the adapter falls back to the credential-free local analyzer.
"""

from __future__ import annotations

from pathlib import Path

from ..llm import LLMClient, get_client
from .base import Analyzer, AnalyzerResult
from .local_placeholder import LocalPlaceholderAnalyzer

_SYSTEM = (
    "You transcribe one photographed document or exam page. "
    "The image is authoritative; client OCR may be incomplete. "
    "Reply with one minified JSON object and no markdown. Keys: "
    '"text" (complete transcription preserving question numbers, choices, '
    'equations and reading order), '
    '"vision_text" (concise textual description of figures, graphs, tables, '
    'diagrams and spatial labels needed to solve the page; empty string when none), '
    '"summary" (one short line, <= {max_len} characters, in the page language), '
    '"language" (BCP-47 code or null), '
    '"keywords" (array of up to 5 short strings). '
    "Do not solve the questions. If part is unreadable, mark that part [unreadable] "
    "instead of inventing content."
)


def _read_image(path: str | None) -> bytes | None:
    if not path:
        return None
    try:
        return Path(path).read_bytes()
    except OSError:
        return None


class LLMAnalyzer(Analyzer):
    offline = False

    def __init__(
        self,
        *,
        name: str = "claude",
        provider: str = "anthropic",
        client: LLMClient | None = None,
    ):
        self.name = name
        self.provider = provider
        self.provider_version = f"{provider}-vision-ocr-1.0.0"
        self._client = client
        self._fallback = LocalPlaceholderAnalyzer()

    def analyze(
        self,
        *,
        image_path: str | None = None,
        ocr_text: str | None = None,
        max_summary_len: int = 48,
    ) -> AnalyzerResult:
        image = _read_image(image_path)
        supplied_text = (ocr_text or "").strip()
        try:
            client = get_client(self._client, self.provider)
            if client is None or (image is None and not supplied_text):
                return self._fallback.analyze(
                    image_path=image_path,
                    ocr_text=ocr_text,
                    max_summary_len=max_summary_len,
                )
            prompt = (
                "Transcribe the attached page image. "
                "Use this client OCR as a hint and correct it against the image:\n"
                + (supplied_text or "(client OCR unavailable)")
            )
            data = client.complete_json(
                system=_SYSTEM.format(max_len=max_summary_len),
                prompt=prompt,
                image=image,
            )
        except Exception:  # noqa: BLE001 - finalization degrades safely
            return self._fallback.analyze(
                image_path=image_path,
                ocr_text=ocr_text,
                max_summary_len=max_summary_len,
            )

        text = str(data.get("text", "")).strip() or supplied_text or None
        vision_text = str(data.get("vision_text", "")).strip()
        summary = str(data.get("summary", "")).strip()[:max_summary_len]
        if not summary:
            summary = self._fallback._summarize(text, max_summary_len)
        return AnalyzerResult(
            text=text,
            summary=summary,
            language=data.get("language") or None,
            embedding=None,
            extras={
                "source": self.name,
                "provider": self.provider,
                "model": client.model,
                "keywords": data.get("keywords", []),
                "vision_text": vision_text,
                "image_analyzed": image is not None,
            },
        )


class ClaudeAnalyzer(LLMAnalyzer):
    """Back-compat alias registered under ``claude``."""

    def __init__(self, client: LLMClient | None = None):
        super().__init__(name="claude", provider="anthropic", client=client)

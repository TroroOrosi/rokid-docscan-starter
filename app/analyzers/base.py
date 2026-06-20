"""Stable analyzer interface (a 'port' in ports-and-adapters terms).

An Analyzer turns a page image (and any client-provided OCR text) into:
- text:    extracted/forwarded OCR text (may be None if the provider is
           summary-only or unavailable),
- summary: a short, HUD-friendly one-liner,
- and optional extras (embedding, language, raw provider payload).

Concrete adapters (local placeholder today; Gemini/OpenAI/Rizon/on-device
later) implement this interface and register themselves. The server depends
only on this contract, identified by version.ANALYZER_API_VERSION.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field


@dataclass
class AnalyzerResult:
    text: str | None
    summary: str
    language: str | None = None
    # Optional dense vector for future semantic matching (kept out of the
    # deterministic matcher for now). None until a provider supplies it.
    embedding: list[float] | None = None
    # Free-form provider diagnostics; never relied on by the server.
    extras: dict = field(default_factory=dict)


class Analyzer(abc.ABC):
    """Provider-agnostic analyzer port."""

    #: Stable registry key, e.g. "local", "gemini", "openai", "rizon".
    name: str = "base"
    #: Provider/model identity surfaced in responses & eval reports.
    provider_version: str = "0.0.0"
    #: True if this adapter runs fully on-device/offline (no network, no creds).
    offline: bool = True

    @abc.abstractmethod
    def analyze(
        self,
        *,
        image_path: str | None = None,
        ocr_text: str | None = None,
        max_summary_len: int = 48,
    ) -> AnalyzerResult:
        """Return an AnalyzerResult. Implementations must not raise on empty
        input; return a best-effort placeholder instead."""

    def info(self) -> dict:
        return {
            "name": self.name,
            "provider_version": self.provider_version,
            "offline": self.offline,
        }

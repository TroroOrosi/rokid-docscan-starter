"""Stable media-extractor interface (a 'port' in ports-and-adapters terms).

A MediaExtractor turns a media region of an exam page (a formula, figure,
graph or table) — referenced by OCR text and/or an image region — into a
structured, HUD/solver-friendly representation:
- kind:    one of "math" | "figure" | "graph" | "table",
- content: a best-effort textual representation (LaTeX-ish for math, a short
           description for figures/graphs, a flattened cell list for tables),
- confidence: 0..1, and optional provider extras.

Concrete adapters (local placeholder today; a real math-OCR / table / chart
model later) implement this interface and register themselves. The server
depends only on this contract, identified by version.EXTRACTOR_API_VERSION.

The default offline adapter does NOT run real computer vision — it returns a
clearly-marked placeholder derived from OCR text so the server runs end-to-end
with zero external dependencies.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field

#: The media kinds this port understands.
KINDS = ("math", "figure", "graph", "table")


@dataclass
class ExtractorResult:
    """One extracted media item."""

    kind: str
    content: str
    confidence: float = 0.0
    # Free-form provider diagnostics; never relied on by the server.
    extras: dict = field(default_factory=dict)


class MediaExtractor(abc.ABC):
    """Provider-agnostic media-extractor port."""

    #: Stable registry key, e.g. "local", "mathpix", "table-transformer".
    name: str = "base"
    #: Provider/model identity surfaced in responses & eval reports.
    provider_version: str = "0.0.0"
    #: True if this adapter runs fully on-device/offline (no network, no creds).
    offline: bool = True
    #: Which media kinds this adapter can handle.
    kinds: tuple[str, ...] = KINDS

    @abc.abstractmethod
    def extract(
        self,
        *,
        image_path: str | None = None,
        ocr_text: str | None = None,
        kind: str | None = None,
        region: dict | None = None,
    ) -> ExtractorResult:
        """Return an ExtractorResult. Implementations must not raise on empty
        input; return a best-effort placeholder instead."""

    def ready(self) -> bool:
        """Whether this adapter can actually run, as opposed to being selected.

        Offline adapters always run. Cloud adapters override this: they fall
        back to the offline placeholder without saying so when no credential is
        present, so "selected" and "will run" are different questions and a
        pre-flight has to be able to ask the second one.
        """
        return True

    def info(self) -> dict:
        return {
            "name": self.name,
            "provider_version": self.provider_version,
            "offline": self.offline,
            "ready": self.ready(),
            "kinds": list(self.kinds),
        }

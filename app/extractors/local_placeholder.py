"""Local, offline, credential-free media extractor used by the MVP today.

It performs NO real computer vision. It inspects the client-provided OCR text
with the same lightweight heuristics used elsewhere (see app/layout.py) to
guess what media is present (formula / figure / graph / table) and returns a
clearly-marked, low-confidence placeholder. This keeps the server runnable with
zero external dependencies while presenting the exact interface a real
math-OCR / chart / table model will later implement. Real extraction = register
a model adapter under another name and route to it (ROKID_EXTRACTOR / prefer).
"""

from __future__ import annotations

import re

from ..matching import normalize_ocr_text
from .base import KINDS, ExtractorResult, MediaExtractor

# Reuse the same surface cues app/layout.py keys on, so detection stays
# consistent across the codebase.
_FIGURE_RE = re.compile(r"図\s*([0-9０-９]+)")
_TABLE_RE = re.compile(r"表\s*([0-9０-９]+)")
_GRAPH_RE = re.compile(r"グラフ")
# Math-ish tokens: an equals sign with surrounding symbols, or common operators.
_MATH_RE = re.compile(r"[0-9A-Za-zα-ωΑ-Ω]\s*[=＝]|[∫∑√±×÷≤≥≠]|\^|√")


class LocalPlaceholderExtractor(MediaExtractor):
    name = "local"
    provider_version = "placeholder-1.0.0"
    offline = True
    kinds = KINDS

    def extract(
        self,
        *,
        image_path: str | None = None,
        ocr_text: str | None = None,
        kind: str | None = None,
        region: dict | None = None,
    ) -> ExtractorResult:
        text = normalize_ocr_text(ocr_text) if ocr_text else ""
        detected = kind or self._detect_kind(text)
        if detected is None:
            return ExtractorResult(
                kind="figure",
                content="(メディアなし)",
                confidence=0.0,
                extras={"placeholder": True, "detected": False},
            )

        label = self._label(detected, text)
        return ExtractorResult(
            kind=detected,
            # Deliberately marked as needing a real model — this is not a real
            # extraction (e.g. no LaTeX, no parsed table cells).
            content=f"(要モデル接続) {label}",
            confidence=0.1,
            extras={"placeholder": True, "source": "local_placeholder"},
        )

    @staticmethod
    def _detect_kind(text: str) -> str | None:
        if _MATH_RE.search(text):
            return "math"
        if _TABLE_RE.search(text):
            return "table"
        if _GRAPH_RE.search(text):
            return "graph"
        if _FIGURE_RE.search(text):
            return "figure"
        return None

    @staticmethod
    def _label(kind: str, text: str) -> str:
        if kind == "table":
            m = _TABLE_RE.search(text)
            return f"表{m.group(1)}" if m else "表"
        if kind == "figure":
            m = _FIGURE_RE.search(text)
            return f"図{m.group(1)}" if m else "図"
        if kind == "graph":
            return "グラフ"
        return "数式"


def detect_media(ocr_text: str | None) -> list[str]:
    """Convenience: which media kinds the heuristics see in this OCR text.

    Used by the question pipeline to decide whether to invoke an extractor.
    Returns kinds in a stable order (subset of base.KINDS).
    """
    text = normalize_ocr_text(ocr_text) if ocr_text else ""
    found: list[str] = []
    if _MATH_RE.search(text):
        found.append("math")
    if _TABLE_RE.search(text):
        found.append("table")
    if _GRAPH_RE.search(text):
        found.append("graph")
    if _FIGURE_RE.search(text):
        found.append("figure")
    return found

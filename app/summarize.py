"""Backward-compatible summarize shim.

The summarization logic now lives behind the provider-agnostic analyzer
interface (app/analyzers). This module is kept so older callers/tests keep
working; it simply delegates to the active analyzer.
"""

from __future__ import annotations

from .analyzers import get_analyzer


def summarize_page(ocr_text: str | None, max_len: int = 48) -> str:
    return get_analyzer().analyze(
        ocr_text=ocr_text, max_summary_len=max_len
    ).summary

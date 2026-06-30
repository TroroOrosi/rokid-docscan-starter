"""Build the 3-line HUD payload shown on the Rokid Glasses display.

Used only by POST /v1/match (document page-matching mode).
Exam-mode and explain-mode views are built in glasses_view.py instead.

The HUD is intentionally minimal: monochrome green Micro-LED overlay.
We always return exactly 3 lines so the on-glass renderer can lay them out
deterministically.  Character-level reflow is the client's responsibility;
the server does NOT truncate or split text.
"""

from __future__ import annotations

from .matching import ScoredCandidate


def build_hud(
    verdict: str,
    best: ScoredCandidate | None,
    total_pages: int,
    summary: str | None = None,
) -> dict:
    """Return {verdict, lines:[l1,l2,l3], confidence}."""
    if verdict == "HIT" and best is not None:
        page_no = best.page_index + 1
        line1 = f"PAGE {page_no}/{total_pages}"
        # No [:24] truncation — the client renderer handles line-wrapping.
        line2 = (summary or "").strip() or f"match {best.confidence:.2f}"
        line3 = f"conf {best.confidence:.2f}  hd {best.hamming}"
    elif verdict == "LOW_CONF" and best is not None:
        page_no = best.page_index + 1
        line1 = "LOW CONF"
        line2 = f"maybe p{page_no} ({best.confidence:.2f})"
        line3 = "hold steady / retry"
    else:  # NO_PAGE
        line1 = "NO PAGE"
        line2 = "not in this doc"
        line3 = "rescan or check title"

    return {
        "verdict": verdict,
        "confidence": round(best.confidence, 4) if best else 0.0,
        "lines": [line1, line2, line3],
    }

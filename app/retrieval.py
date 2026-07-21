"""Lightweight cross-document retrieval (RAG) over previously scanned pages.

When solving a question we can pull supporting context from the user's own
captured study materials (the existing `documents`/`pages` store built by the
page-matching mode). This module returns the most relevant pages as `context` text
plus `evidence_pages`, which the solver uses as grounding and the HUD surfaces
as "根拠".

It is deliberately dependency-free: similarity is `difflib.SequenceMatcher`
ratio over normalized OCR text plus a keyword-overlap bonus (the same
`normalize_ocr_text` the matcher uses). A real dense-embedding retriever is a
drop-in upgrade gated behind `config.ENABLE_EMBEDDING`; until an analyzer
supplies embeddings we fall back to this lexical scorer.
"""

from __future__ import annotations

import sqlite3
from difflib import SequenceMatcher

from . import config
from .matching import normalize_ocr_text

# Pages scoring below this are treated as irrelevant (avoids noise context).
_MIN_SCORE = 0.06
_SNIPPET_LEN = 120

# The display label _page_material / layout prepend to a figure reading. It is
# display-only boilerplate: it must never participate in retrieval scoring, on
# the page side (_scored_material drops it) OR the query side — a question body
# stored via _page_material still carries it, so _strip_display_header removes
# it from the query before scoring (otherwise a short figure query like "42"
# looks long, skips the short-query containment path, and its token denominator
# is inflated by the header's bigrams).
_FIGURE_HEADER = "【図・画像の読み取り】"


def _strip_display_header(text: str | None) -> str:
    """Drop the 【図・画像の読み取り】 display label lines, keep the content."""
    if not text:
        return ""
    kept = [ln for ln in text.splitlines() if ln.strip() != _FIGURE_HEADER]
    return "\n".join(kept).strip()


def _scored_material(ocr_text: str | None, vision_text: str | None) -> str:
    """Raw body + figure reading for SCORING (no display boilerplate).

    The 【図・画像の読み取り】 header used for display is deliberately left OUT
    here: `_score` tokenizes character bigrams, so a fixed header would give
    every vision-bearing page the same overlap and let unrelated figure/table
    pages fill or displace real RAG context. Score on the raw recognized text.
    """
    parts = [t.strip() for t in (ocr_text, vision_text) if t and t.strip()]
    return "\n".join(parts)


def _contains_anchor(text: str, query_tokens: set[str]) -> bool:
    """True when a query term (>=2 chars) occurs in text (case-insensitive)."""
    low = text.lower()
    return any(len(t) >= 2 and t.lower() in low for t in query_tokens)


def _window(text: str, query_tokens: set[str], budget: int) -> str:
    """A <=budget slice of text anchored on the earliest query-term match.

    Prefer longer query terms as case-insensitive anchors, falling back to the
    head when none match, so the returned excerpt actually contains the value
    used by normalized retrieval scoring.
    """
    text = text.strip()
    if len(text) <= budget:
        return text
    search_text = text.lower()
    anchor = None
    for term in sorted(
        (t for t in query_tokens if len(t) >= 2), key=len, reverse=True
    ):
        idx = search_text.find(term.lower())
        if idx != -1 and (anchor is None or idx < anchor):
            anchor = idx
    if anchor is None:
        anchor = 0
    start = max(0, anchor - budget // 4)
    return text[start : start + budget].strip()


def _snippet(body: str, vision: str, query_tokens: set[str]) -> str:
    """Build a snippet that keeps the matched value across body + figure text.

    The budget goes to the component the query actually matched, so evidence is
    never crowded out by the other side:
      - only the body matched  -> the whole budget windows the body (a value
        past the first ~60 chars is no longer dropped to reserve room for
        unrelated vision text),
      - only the figure reading matched -> the whole budget windows it (a value
        in `vision_text` appended after a long body still survives),
      - both (or neither directly — recalled by fuzzy overlap) -> split so each
        side keeps part of the budget.
    """
    body = body.strip()
    vision = vision.strip()
    if body and vision:
        body_hit = _contains_anchor(body, query_tokens)
        vision_hit = _contains_anchor(vision, query_tokens)
        if body_hit and not vision_hit:
            return _window(body, query_tokens, _SNIPPET_LEN)
        if vision_hit and not body_hit:
            return _window(vision, query_tokens, _SNIPPET_LEN)
        v = _window(vision, query_tokens, _SNIPPET_LEN // 2)
        b = _window(body, query_tokens, _SNIPPET_LEN - len(v) - 1)
        return f"{b}\n{v}".strip()
    return _window(body or vision, query_tokens, _SNIPPET_LEN)


def _tokens(text: str) -> set[str]:
    # Whitespace words PLUS character bigrams of the compacted text. Bigrams make
    # overlap meaningful for Japanese, which is not reliably space-separated.
    parts = {t for t in text.split() if t}
    compact = text.replace(" ", "")
    parts |= {compact[i : i + 2] for i in range(len(compact) - 1)}
    return parts


def _score(query_norm: str, query_tokens: set[str], page_text: str) -> float:
    page_norm = normalize_ocr_text(page_text)
    if not page_norm:
        return 0.0
    ratio = SequenceMatcher(None, query_norm, page_norm).ratio()
    query_compact = query_norm.replace(" ", "")
    if len(query_compact) < 3:
        # A 1-2 char query has (almost) no bigrams, so token overlap collapses
        # to zero against every page. Use direct containment instead —
        # otherwise a single-kanji keyword query can never recall anything.
        overlap = 1.0 if query_compact and query_compact in page_norm.replace(" ", "") else 0.0
    else:
        page_tokens = _tokens(page_norm)
        overlap = (
            len(query_tokens & page_tokens) / len(query_tokens) if query_tokens else 0.0
        )
    # Weight token overlap a bit higher; it is more robust for long pages.
    return round(0.4 * ratio + 0.6 * overlap, 4)


def retrieve_context(
    conn: sqlite3.Connection, query_text: str | None, *, top_k: int = 3
) -> dict:
    """Return {context, evidence_pages, hits} for the most relevant pages.

    Safe on an empty store or empty query (returns empty results).
    """
    # A question body stored via _page_material carries the 【図・画像の読み取り】
    # display label; drop it before scoring so it mirrors the header-free page
    # material and a short figure query is not inflated by boilerplate.
    query_norm = normalize_ocr_text(_strip_display_header(query_text))
    empty = {"context": "", "evidence_pages": [], "hits": []}
    if not query_norm:
        return empty

    rows = conn.execute(
        "SELECT id, document_id, page_index, ocr_text, vision_text, summary "
        "FROM pages"
    ).fetchall()
    if not rows:
        return empty

    query_tokens = _tokens(query_norm)
    scored = []
    for r in rows:
        body = (r["ocr_text"] or "").strip()
        vision = (r["vision_text"] or "").strip()
        # Score against the raw body + figure reading: a figure/table
        # question's supporting values may live only in vision_text.
        score_text = _scored_material(body, vision) or (r["summary"] or "")
        score = _score(query_norm, query_tokens, score_text)
        if score >= _MIN_SCORE:
            # Window the snippet around the match so a value in vision_text
            # (appended after a long body) is not truncated away; fall back to
            # the summary only when there is no recognized text at all.
            if body or vision:
                snippet = _snippet(body, vision, query_tokens)
            else:
                snippet = (r["summary"] or "").strip()[:_SNIPPET_LEN]
            scored.append(
                {
                    "page_id": r["id"],
                    "document_id": r["document_id"],
                    "page_index": r["page_index"],
                    "score": score,
                    "snippet": snippet,
                }
            )

    scored.sort(key=lambda h: h["score"], reverse=True)
    hits = scored[:top_k]
    context = "\n".join(h["snippet"] for h in hits)
    return {
        "context": context,
        "evidence_pages": [h["page_index"] for h in hits],
        "hits": hits,
        "retriever": "embedding" if config.ENABLE_EMBEDDING else "lexical",
    }

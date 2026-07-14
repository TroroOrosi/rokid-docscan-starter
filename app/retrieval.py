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


def _page_material(ocr_text: str | None, vision_text: str | None) -> str:
    """Combine a page's body text and figure reading for scoring/snippets.

    Mirrors app.main._page_material's combination (kept local to avoid an
    import cycle): the figure/table reading may hold the values a
    figure-dependent question needs.
    """
    parts = []
    if ocr_text and ocr_text.strip():
        parts.append(ocr_text.strip())
    if vision_text and vision_text.strip():
        parts.append("【図・画像の読み取り】\n" + vision_text.strip())
    return "\n".join(parts)


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
    query_norm = normalize_ocr_text(query_text) if query_text else ""
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
        # Score against the full recognition (body + figure reading): a
        # figure/table question's supporting values may live only in
        # vision_text.
        text = _page_material(r["ocr_text"], r["vision_text"]) or r["summary"] or ""
        score = _score(query_norm, query_tokens, text)
        if score >= _MIN_SCORE:
            snippet = (r["summary"] or text).strip()[:_SNIPPET_LEN]
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

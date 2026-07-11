"""Unit tests for app/hud.py — the /v1/match 3-line HUD payload.

Previously only exercised indirectly through /v1/match; the 3-line contract
and per-verdict formatting are pinned here directly.
"""

import pytest

from app.hud import build_hud
from app.matching import ScoredCandidate


def _cand(confidence=0.91, hamming=3, page_index=1):
    return ScoredCandidate(
        page_id=1,
        page_index=page_index,
        hamming=hamming,
        ocr_match=True,
        confidence=confidence,
        ocr_similarity=0.8,
    )


def test_hit_with_summary():
    hud = build_hud("HIT", _cand(), total_pages=5, summary="第2章 力学")
    assert hud["verdict"] == "HIT"
    assert hud["lines"] == ["PAGE 2/5", "第2章 力学", "conf 0.91  hd 3"]
    assert hud["confidence"] == 0.91


def test_hit_without_summary_shows_match_score():
    hud = build_hud("HIT", _cand(), total_pages=5, summary=None)
    assert hud["lines"][1] == "match 0.91"


def test_low_conf_guidance():
    hud = build_hud("LOW_CONF", _cand(), total_pages=5)
    assert hud["lines"] == ["LOW CONF", "maybe p2 (0.91)", "hold steady / retry"]


def test_no_page_without_candidate():
    hud = build_hud("NO_PAGE", None, total_pages=5)
    assert hud["confidence"] == 0.0
    assert hud["lines"] == ["NO PAGE", "not in this doc", "rescan or check title"]


@pytest.mark.parametrize(
    ("verdict", "best"),
    [("HIT", _cand()), ("LOW_CONF", _cand()), ("NO_PAGE", None)],
)
def test_every_branch_returns_exactly_three_lines(verdict, best):
    # HUD contract: max 3 lines, always exactly 3 for deterministic layout.
    hud = build_hud(verdict, best, total_pages=9)
    assert len(hud["lines"]) == 3
    assert all(isinstance(line, str) for line in hud["lines"])


def test_confidence_rounded_to_four_places():
    hud = build_hud("HIT", _cand(confidence=0.87654321), total_pages=3)
    assert hud["confidence"] == 0.8765

from app import matching
from app.matching import (
    Candidate,
    hamming,
    match,
    normalize_ocr_text,
    ocr_md5,
    phash,
    phash_hex,
    score_candidate,
)
from tests.conftest import make_image


# --- pHash / hamming --------------------------------------------------------

def test_phash_is_deterministic():
    img = make_image(seed=1)
    assert phash(img) == phash(img)


def test_phash_hex_length():
    h = phash_hex(make_image(seed=2))
    assert len(h) == matching.HASH_BIT_LEN // 4  # 16 hex chars for 64 bits


def test_identical_images_zero_hamming():
    a = phash(make_image(seed=3))
    b = phash(make_image(seed=3))
    assert hamming(a, b) == 0


def test_different_images_large_hamming():
    a = phash(make_image(seed=3))
    b = phash(make_image(seed=99))
    assert hamming(a, b) > matching.HAMMING_STRONG


def test_hamming_accepts_hex_strings():
    assert hamming("00", "ff") == 8
    assert hamming("0f", "0f") == 0


def test_small_visual_change_small_hamming():
    base = phash(make_image(seed=5))
    # same shapes plus tiny text overlay -> perceptually close
    near = phash(make_image(seed=5, text="x"))
    assert hamming(base, near) <= matching.HAMMING_WEAK


# --- OCR MD5 normalization --------------------------------------------------

def test_normalize_collapses_whitespace_and_case():
    assert normalize_ocr_text("  Hello   World \n") == "hello world"


def test_ocr_md5_stable_across_whitespace_noise():
    assert ocr_md5("Hello World") == ocr_md5("  hello\tworld ")


def test_ocr_md5_none_for_empty():
    assert ocr_md5("") is None
    assert ocr_md5(None) is None
    assert ocr_md5("   ") is None


def test_ocr_md5_differs_for_different_text():
    assert ocr_md5("page one") != ocr_md5("page two")


# --- scoring ----------------------------------------------------------------

def _cand(idx, ph, ocr_md5=None, ocr_text=None):
    return Candidate(
        page_id=idx + 1,
        page_index=idx,
        phash=ph,
        ocr_md5=ocr_md5,
        ocr_text=ocr_text,
    )


def test_exact_phash_match_high_confidence():
    ph = phash_hex(make_image(seed=7))
    sc = score_candidate(ph, None, _cand(0, ph))
    assert sc.hamming == 0
    assert sc.confidence == 1.0


def test_ocr_bonus_applied_on_md5_match():
    ph_a = phash_hex(make_image(seed=8))
    ph_b = phash_hex(make_image(seed=42))  # visually different
    md5 = ocr_md5("invoice 2026")
    no_bonus = score_candidate(ph_a, md5, _cand(0, ph_b, ocr_md5=None))
    bonus = score_candidate(ph_a, md5, _cand(0, ph_b, ocr_md5=md5))
    assert bonus.ocr_match is True
    assert bonus.confidence >= no_bonus.confidence + matching.OCR_MD5_BONUS - 1e-9 \
        or bonus.confidence == 1.0


# --- graded OCR similarity --------------------------------------------------

def test_ocr_exact_text_gives_full_bonus():
    ph_a = phash_hex(make_image(seed=8))
    ph_b = phash_hex(make_image(seed=42))  # visually different
    text = "invoice 2026 total"
    sc = score_candidate(
        ph_a, ocr_md5(text), _cand(0, ph_b, ocr_md5=ocr_md5(text), ocr_text=text),
        query_ocr_text=text,
    )
    assert sc.ocr_match is True
    assert sc.ocr_similarity == 1.0


def test_ocr_near_text_gives_partial_bonus():
    # Visually different so the OCR signal is what moves confidence.
    ph_a = phash_hex(make_image(seed=8))
    ph_b = phash_hex(make_image(seed=42))
    stored = "invoice 2026 total amount"
    noisy = "invoice 2026 total arnount"  # OCR-style noise (m->rn)
    no_text = score_candidate(ph_a, None, _cand(0, ph_b))
    partial = score_candidate(
        ph_a, ocr_md5(noisy),
        _cand(0, ph_b, ocr_md5=ocr_md5(stored), ocr_text=stored),
        query_ocr_text=noisy,
    )
    # similarity strictly between 0 and 1, and it lifts confidence over no-text
    assert 0.0 < partial.ocr_similarity < 1.0
    assert partial.confidence > no_text.confidence
    # but less than a full exact-match bonus
    assert partial.confidence < no_text.confidence + matching.OCR_MD5_BONUS


def test_ocr_unrelated_text_gives_no_bonus():
    ph_a = phash_hex(make_image(seed=8))
    ph_b = phash_hex(make_image(seed=42))
    no_text = score_candidate(ph_a, None, _cand(0, ph_b))
    unrelated = score_candidate(
        ph_a, ocr_md5("completely different words here"),
        _cand(0, ph_b, ocr_md5=ocr_md5("invoice 2026"), ocr_text="invoice 2026"),
        query_ocr_text="completely different words here",
    )
    assert unrelated.confidence == no_text.confidence
    assert unrelated.ocr_match is False


def test_match_picks_best_and_hits():
    ph0 = phash_hex(make_image(seed=10))
    ph1 = phash_hex(make_image(seed=200))
    cands = [_cand(0, ph0), _cand(1, ph1)]
    best, verdict, scored = match(ph0, None, cands)
    assert best.page_index == 0
    assert verdict == "HIT"
    assert scored[0].confidence >= scored[1].confidence


def test_match_no_candidates_returns_no_page():
    best, verdict, scored = match(phash_hex(make_image(seed=1)), None, [])
    assert best is None
    assert verdict == "NO_PAGE"
    assert scored == []


def test_match_unrelated_query_is_no_page_or_low():
    ph_stored = phash_hex(make_image(seed=11))
    ph_query = phash_hex(make_image(seed=123))
    best, verdict, _ = match(ph_query, None, [_cand(0, ph_stored)])
    assert verdict in {"NO_PAGE", "LOW_CONF"}


# --- text-only matching (撮影しない主経路: どちらかに pHash が無い) ------------

def _ratio(query: str, stored: str) -> float:
    # Same argument order as _ocr_signal (query first) — difflib ratios are
    # not symmetric, so the premise checks must mirror production order.
    import difflib

    return difflib.SequenceMatcher(
        None, normalize_ocr_text(query), normalize_ocr_text(stored)
    ).ratio()


def test_text_only_exact_md5_is_hit():
    text = "問1 次の式を展開せよ (x+1)(x-1)"
    sc = score_candidate(
        None, ocr_md5(text),
        _cand(0, "", ocr_md5=ocr_md5(text), ocr_text=normalize_ocr_text(text)),
        query_ocr_text=text,
    )
    assert sc.hamming is None
    assert sc.confidence == matching.TEXT_EXACT_CONF
    best, verdict, _ = match(None, ocr_md5(text), [
        _cand(0, "", ocr_md5=ocr_md5(text), ocr_text=normalize_ocr_text(text)),
    ], query_ocr_text=text)
    assert verdict == "HIT"


def test_text_only_strong_similarity_hits():
    stored = "invoice 2026 total amount due tomorrow"
    noisy = "invoice 2026 total arnount due tomorrow"  # OCR noise m->rn
    assert _ratio(noisy, stored) >= matching.OCR_MATCH_RATIO  # test premise
    sc = score_candidate(
        None, ocr_md5(noisy),
        _cand(0, "", ocr_md5=ocr_md5(stored), ocr_text=normalize_ocr_text(stored)),
        query_ocr_text=noisy,
    )
    assert sc.hamming is None
    assert sc.confidence >= matching.CONF_OK  # HIT band


def test_text_only_mid_similarity_is_low_conf():
    stored = "alpha beta gamma delta epsilon zeta"
    partial = "alpha beta gamma delta unknown tail"
    r = _ratio(partial, stored)
    assert matching.OCR_SIM_FLOOR <= r < matching.OCR_MATCH_RATIO  # premise
    sc = score_candidate(
        None, ocr_md5(partial),
        _cand(0, "", ocr_md5=ocr_md5(stored), ocr_text=normalize_ocr_text(stored)),
        query_ocr_text=partial,
    )
    assert matching.CONF_LOW <= sc.confidence < matching.CONF_OK  # LOW_CONF band


def test_text_only_unrelated_text_is_no_page():
    stored = "invoice 2026 total"
    unrelated = "zzz qqq unrelated words entirely"
    assert _ratio(unrelated, stored) < matching.OCR_SIM_FLOOR  # premise
    sc = score_candidate(
        None, ocr_md5(unrelated),
        _cand(0, "", ocr_md5=ocr_md5(stored), ocr_text=normalize_ocr_text(stored)),
        query_ocr_text=unrelated,
    )
    assert sc.confidence == 0.0
    best, verdict, _ = match(None, ocr_md5(unrelated), [
        _cand(0, "", ocr_md5=ocr_md5(stored), ocr_text=normalize_ocr_text(stored)),
    ], query_ocr_text=unrelated)
    assert verdict == "NO_PAGE"


def test_text_query_vs_image_candidate_uses_text_signal():
    # Query has no pHash; the candidate does — must not crash in hamming().
    ph = phash_hex(make_image(seed=13))
    text = "page with a chart"
    sc = score_candidate(
        None, ocr_md5(text),
        _cand(0, ph, ocr_md5=ocr_md5(text), ocr_text=normalize_ocr_text(text)),
        query_ocr_text=text,
    )
    assert sc.hamming is None
    assert sc.confidence == matching.TEXT_EXACT_CONF


def test_image_query_vs_textonly_candidate_uses_text_signal():
    # Reverse direction: image query against a 撮影しない text-only page.
    ph = phash_hex(make_image(seed=14))
    text = "page with a table"
    sc = score_candidate(
        ph, ocr_md5(text),
        _cand(0, "", ocr_md5=ocr_md5(text), ocr_text=normalize_ocr_text(text)),
        query_ocr_text=text,
    )
    assert sc.hamming is None
    assert sc.confidence == matching.TEXT_EXACT_CONF


def test_both_phash_scoring_floors_at_text_verdict():
    # With both pHashes present the visual formula still governs, but the
    # recognized text is the primary signal: confidence is floored at the
    # text-only verdict so a weak/stale optional frame cannot suppress an
    # exact recognized-text match. Here seed 8 vs 42 is a weak frame (visual
    # 0.0), so the historical formula would have scored 0.35 (NO_PAGE); the
    # exact text keeps it a HIT at TEXT_EXACT_CONF.
    ph_a = phash_hex(make_image(seed=8))
    ph_b = phash_hex(make_image(seed=42))
    text = "invoice 2026 total"
    sc = score_candidate(
        ph_a, ocr_md5(text),
        _cand(0, ph_b, ocr_md5=ocr_md5(text), ocr_text=normalize_ocr_text(text)),
        query_ocr_text=text,
    )
    d = hamming(ph_a, ph_b)
    visual_formula = min(1.0, matching._phash_confidence(d) + matching.OCR_MD5_BONUS)
    expected = max(visual_formula, matching.TEXT_EXACT_CONF)
    assert sc.hamming == d
    assert sc.confidence == round(expected, 4)
    assert sc.confidence >= matching.CONF_OK  # HIT, not NO_PAGE


def test_pure_image_scoring_unchanged():
    # 画像同士のスコアは数値不変: with no recognized text the text floor is 0.0,
    # so even a weak frame scores by the visual formula alone (no perturbation
    # from the text-primary floor).
    ph_a = phash_hex(make_image(seed=8))
    ph_b = phash_hex(make_image(seed=42))  # visually different -> weak
    sc = score_candidate(ph_a, None, _cand(0, ph_b))
    d = hamming(ph_a, ph_b)
    assert sc.confidence == round(matching._phash_confidence(d), 4)


def test_weak_optional_frame_does_not_suppress_exact_text():
    # Codex review: an optional legacy image that is stale/weak
    # (hamming >= HAMMING_WEAK) must not turn an EXACT recognized-text match
    # into a NO_PAGE. Sending the same text WITHOUT the image HITs at
    # TEXT_EXACT_CONF; attaching a bad frame must not change that verdict.
    ph_a = phash_hex(make_image(seed=8))
    ph_b = phash_hex(make_image(seed=42))
    assert hamming(ph_a, ph_b) >= matching.HAMMING_WEAK  # premise: weak frame
    text = "問1 次の式を展開せよ (x+1)(x-1)"
    with_image = score_candidate(
        ph_a, ocr_md5(text),
        _cand(0, ph_b, ocr_md5=ocr_md5(text), ocr_text=normalize_ocr_text(text)),
        query_ocr_text=text,
    )
    text_only = score_candidate(
        None, ocr_md5(text),
        _cand(0, "", ocr_md5=ocr_md5(text), ocr_text=normalize_ocr_text(text)),
        query_ocr_text=text,
    )
    assert with_image.confidence == text_only.confidence == matching.TEXT_EXACT_CONF


def test_zero_valued_phash_still_compares_visually():
    # A dark/blank page can hash to 0 — presence checks must be explicit,
    # not truthiness, or the visual comparison silently degrades to text.
    zero_hex = "0" * (matching.HASH_BIT_LEN // 4)
    sc = score_candidate(0, None, _cand(0, zero_hex))
    assert sc.hamming == 0
    assert sc.confidence == 1.0


def test_rank_prefers_full_signal_hit_over_partial_exact():
    # A candidate that reached the HIT band on EVERY supplied signal must
    # outrank a higher-confidence match that could not be checked against
    # one of the query's signals (e.g. exact body, no figure to compare).
    partial_exact = matching.ScoredCandidate(
        page_id=1, page_index=0, hamming=None, ocr_match=True,
        confidence=matching.TEXT_EXACT_CONF, ocr_similarity=1.0,
        signal_coverage=0.5,
    )
    full_hit = matching.ScoredCandidate(
        page_id=2, page_index=1, hamming=None, ocr_match=False,
        confidence=0.90, ocr_similarity=0.98, signal_coverage=1.0,
    )
    ranked = matching.rank([partial_exact, full_hit])
    assert [s.page_id for s in ranked] == [2, 1]
    # ...but a full-coverage candidate BELOW the HIT band must not.
    full_low = matching.ScoredCandidate(
        page_id=3, page_index=2, hamming=None, ocr_match=False,
        confidence=0.5, ocr_similarity=0.75, signal_coverage=1.0,
    )
    ranked = matching.rank([partial_exact, full_low])
    assert [s.page_id for s in ranked] == [1, 3]
    # A completed visual comparison counts as full information: an exact
    # pHash match must not lose the tier merely because the page's figure
    # reading was never registered (coverage tracks text signals only).
    visual_exact = matching.ScoredCandidate(
        page_id=4, page_index=3, hamming=0, ocr_match=False,
        confidence=1.0, ocr_similarity=0.0, signal_coverage=0.5,
    )
    full_hit = matching.ScoredCandidate(
        page_id=2, page_index=1, hamming=None, ocr_match=False,
        confidence=0.9, ocr_similarity=0.98, signal_coverage=1.0,
    )
    ranked = matching.rank([full_hit, visual_exact])
    assert [s.page_id for s in ranked] == [4, 2]
    # ...but a merely-NEAR pHash match (visual < 1.0) that dropped a supplied
    # figure signal keeps the coverage penalty, so a full body+figure HIT
    # still wins even at slightly lower confidence.
    near_visual = matching.ScoredCandidate(
        page_id=5, page_index=4, hamming=matching.HAMMING_STRONG + 4,
        ocr_match=False, confidence=0.93, ocr_similarity=1.0,
        signal_coverage=0.5,
    )
    full_hit2 = matching.ScoredCandidate(
        page_id=6, page_index=5, hamming=None, ocr_match=False,
        confidence=0.88, ocr_similarity=0.95, signal_coverage=1.0,
    )
    ranked = matching.rank([near_visual, full_hit2])
    assert [s.page_id for s in ranked] == [6, 5]


def test_visual_match_outranks_equal_text_match():
    # Same confidence -> the candidate with a real hamming sorts first.
    ph = phash_hex(make_image(seed=15))
    visual = _cand(0, ph)
    text = "identical confidence is contrived here"
    text_only = _cand(1, "", ocr_md5=ocr_md5(text), ocr_text=normalize_ocr_text(text))
    best, _, scored = match(ph, ocr_md5(text), [text_only, visual],
                            query_ocr_text=text)
    # visual self-match confidence 1.0 > text ceiling, and it must sort first
    assert scored[0].page_id == visual.page_id
    assert scored[0].hamming == 0
    assert scored[1].hamming is None

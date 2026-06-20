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

def _cand(idx, ph, ocr_md5=None):
    return Candidate(page_id=idx + 1, page_index=idx, phash=ph, ocr_md5=ocr_md5)


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

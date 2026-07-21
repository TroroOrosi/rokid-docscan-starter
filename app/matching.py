"""Deterministic page-matching primitives.

Pure-Python implementation (PIL + stdlib only) so it runs without
numpy / imagehash. Provides:

- pHash: 64-bit DCT-based perceptual hash of an image.
- hamming: bit difference between two hashes.
- normalize_ocr_text + ocr_md5: stable MD5 of normalized OCR text.
- score_candidate / match: combine pHash distance and OCR MD5 bonus into a
  confidence score and a HUD verdict.
"""

from __future__ import annotations

import difflib
import hashlib
import math
import re
from dataclasses import dataclass

from PIL import Image, ImageOps

# --- Tunable thresholds -----------------------------------------------------

PHASH_SIZE = 32          # DCT input is PHASH_SIZE x PHASH_SIZE
PHASH_BITS = 8           # top-left 8x8 low-frequency block -> 64 bits
HASH_BIT_LEN = PHASH_BITS * PHASH_BITS  # 64

# Hamming distance over a 64-bit hash. 0 == identical.
HAMMING_STRONG = 6       # <= this is a confident visual match
HAMMING_WEAK = 16        # > this means visually unrelated

OCR_MD5_BONUS = 0.35     # max confidence added from the OCR text signal

# OCR text similarity (graded). Real OCR output is noisy, so an exact MD5 match
# rarely fires in production. We therefore award a *graded* bonus based on how
# similar the query text is to the candidate text (0..1 ratio), scaled by
# OCR_MD5_BONUS. The exact-MD5 path is kept as a fast full-bonus shortcut.
OCR_SIM_FLOOR = 0.6      # below this similarity, award no bonus (too different)
OCR_MATCH_RATIO = 0.9    # at/above this, treat as a strong textual agreement

# Confidence verdict thresholds (after combining signals).
CONF_OK = 0.62           # >= -> HIT
CONF_LOW = 0.40          # >= but < CONF_OK -> LOW CONF; below -> NO PAGE

# Text-only confidence ceiling (query and/or candidate has no pHash — the
# 撮影しない primary path). Deliberately < 1.0: a text match must never claim
# more certainty than a pixel-identical visual match.
TEXT_EXACT_CONF = 0.95


# --- pHash ------------------------------------------------------------------

def _dct_1d(vector: list[float]) -> list[float]:
    """Naive type-II DCT for a single vector (small N, fine here)."""
    n = len(vector)
    result = []
    factor = math.pi / n
    for k in range(n):
        acc = 0.0
        for i, v in enumerate(vector):
            acc += v * math.cos((i + 0.5) * k * factor)
        result.append(acc)
    return result


def _dct_2d(matrix: list[list[float]]) -> list[list[float]]:
    rows = [_dct_1d(row) for row in matrix]
    # transpose, DCT columns, transpose back
    cols = [list(col) for col in zip(*rows)]
    cols = [_dct_1d(col) for col in cols]
    return [list(row) for row in zip(*cols)]


def phash(image: Image.Image) -> int:
    """Compute a 64-bit perceptual hash, returned as an int."""
    img = ImageOps.grayscale(image).resize(
        (PHASH_SIZE, PHASH_SIZE), Image.Resampling.LANCZOS
    )
    # Pillow >= 12.1 deprecates Image.getdata() in favor of
    # get_flattened_data(); fall back for older Pillow.
    try:
        pixels = list(img.get_flattened_data())
    except AttributeError:
        pixels = list(img.getdata())  # noqa: small image, fine here
    matrix = [
        [float(pixels[r * PHASH_SIZE + c]) for c in range(PHASH_SIZE)]
        for r in range(PHASH_SIZE)
    ]
    dct = _dct_2d(matrix)

    # low-frequency block, excluding the DC term (0,0) from the median
    block = [dct[r][c] for r in range(PHASH_BITS) for c in range(PHASH_BITS)]
    ac = sorted(block[1:])
    mid = len(ac) // 2
    median = (ac[mid] if len(ac) % 2 else (ac[mid - 1] + ac[mid]) / 2.0)

    bits = 0
    for i, value in enumerate(block):
        bits <<= 1
        if value > median:
            bits |= 1
    return bits


def phash_hex(image: Image.Image) -> str:
    return f"{phash(image):0{HASH_BIT_LEN // 4}x}"


def hamming(a: int | str, b: int | str) -> int:
    """Hamming distance between two hashes given as ints or hex strings.

    Defense-in-depth: empty/None inputs raise a clear ValueError instead of a
    confusing int()/TypeError (all in-repo callers already filter these out).
    """
    if a is None or a == "" or b is None or b == "":
        raise ValueError("hamming() requires two non-empty hashes")
    ia = int(a, 16) if isinstance(a, str) else a
    ib = int(b, 16) if isinstance(b, str) else b
    return bin(ia ^ ib).count("1")


# --- OCR normalization ------------------------------------------------------

_WS_RE = re.compile(r"\s+")


def normalize_ocr_text(text: str | None) -> str:
    """Normalize OCR text so trivial whitespace/case noise hashes equally."""
    if not text:
        return ""
    # unify whitespace, strip, lowercase; keep unicode letters intact
    return _WS_RE.sub(" ", text.strip()).lower()


def ocr_md5(text: str | None) -> str | None:
    """MD5 of normalized OCR text. None when there is no usable text."""
    normalized = normalize_ocr_text(text)
    if not normalized:
        return None
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


# --- Scoring ----------------------------------------------------------------

@dataclass
class Candidate:
    page_id: int
    page_index: int
    phash: str
    ocr_md5: str | None
    # Normalized OCR text, when available, for graded similarity matching.
    # Optional/last so existing positional construction keeps working.
    ocr_text: str | None = None
    # Optional second comparison component (the figure reading). When both
    # the query and the candidate provide one, the graded similarity is the
    # equal-weight mean of the two components, so a long shared body cannot
    # mask a mismatched figure reading.
    vision_text: str | None = None


@dataclass
class ScoredCandidate:
    page_id: int
    page_index: int
    # Hamming distance when both sides have a pHash; None when the comparison
    # was text-only (no visual comparison happened at all).
    hamming: int | None
    ocr_match: bool
    confidence: float
    # 0..1 text similarity (1.0 == exact match, 0.0 == no usable text).
    ocr_similarity: float = 0.0
    # Fraction of the query's text signals (body / figure reading) the
    # comparison actually used. 1.0 = full-information match; lower = a
    # fallback that had to ignore a supplied signal because the candidate
    # lacked it. rank() prefers fuller matches on otherwise-equal scores.
    signal_coverage: float = 1.0


def _phash_confidence(distance: int) -> float:
    """Map hamming distance to a 0..1 visual-confidence score."""
    if distance <= HAMMING_STRONG:
        return 1.0
    if distance >= HAMMING_WEAK:
        return 0.0
    span = HAMMING_WEAK - HAMMING_STRONG
    return 1.0 - (distance - HAMMING_STRONG) / span


def _ocr_signal(
    query_ocr_md5: str | None,
    query_ocr_text: str | None,
    candidate: Candidate,
    query_vision_text: str | None = None,
) -> tuple[float, bool, float]:
    """Return (bonus, ocr_match, similarity) from the OCR text signal.

    1. Exact MD5 match -> full bonus (also covers the image-bytes fallback).
    2. Otherwise, if both sides have normalized text, award a graded bonus
       proportional to their similarity (above OCR_SIM_FLOOR). When both
       sides also provide a figure-reading component, the similarity is the
       equal-weight mean of the body and figure ratios — a long shared body
       must not mask a mismatched figure reading.
    3. No usable text -> no bonus.
    """
    if query_ocr_md5 and candidate.ocr_md5 and query_ocr_md5 == candidate.ocr_md5:
        return OCR_MD5_BONUS, True, 1.0

    q = normalize_ocr_text(query_ocr_text)
    c = normalize_ocr_text(candidate.ocr_text)
    if not q or not c:
        return 0.0, False, 0.0

    ratio = difflib.SequenceMatcher(None, q, c).ratio()
    qv = normalize_ocr_text(query_vision_text)
    cv = normalize_ocr_text(candidate.vision_text)
    if qv and cv:
        vision_ratio = difflib.SequenceMatcher(None, qv, cv).ratio()
        ratio = (ratio + vision_ratio) / 2
    if ratio < OCR_SIM_FLOOR:
        return 0.0, False, round(ratio, 4)
    return OCR_MD5_BONUS * ratio, ratio >= OCR_MATCH_RATIO, round(ratio, 4)


def _text_only_confidence(exact: bool, similarity: float) -> float:
    """Map the text signal to a confidence when no visual comparison exists.

    Piecewise-linear over the existing semantic anchors so the verdict bands
    stay meaningful without new tunables:
      exact normalized-text MD5 match      -> TEXT_EXACT_CONF (HIT)
      similarity <  OCR_SIM_FLOOR   (0.6)  -> 0.0             (NO_PAGE)
      similarity == OCR_SIM_FLOOR          -> CONF_LOW        (LOW_CONF starts)
      similarity == OCR_MATCH_RATIO (0.9)  -> CONF_OK         (HIT starts)
      similarity == 1.0                    -> TEXT_EXACT_CONF
    """
    if exact:
        return TEXT_EXACT_CONF
    if similarity < OCR_SIM_FLOOR:
        return 0.0
    if similarity < OCR_MATCH_RATIO:
        span = OCR_MATCH_RATIO - OCR_SIM_FLOOR
        return CONF_LOW + (similarity - OCR_SIM_FLOOR) / span * (CONF_OK - CONF_LOW)
    span = 1.0 - OCR_MATCH_RATIO
    return CONF_OK + (similarity - OCR_MATCH_RATIO) / span * (TEXT_EXACT_CONF - CONF_OK)


def _has_hash(h: int | str | None) -> bool:
    """Explicit presence check: a valid all-zero hash (int 0) is present."""
    return h is not None and h != ""


def score_candidate(
    query_phash: int | str | None,
    query_ocr_md5: str | None,
    candidate: Candidate,
    query_ocr_text: str | None = None,
    query_vision_text: str | None = None,
) -> ScoredCandidate:
    bonus, ocr_match, similarity = _ocr_signal(
        query_ocr_md5, query_ocr_text, candidate, query_vision_text
    )
    exact = bool(
        query_ocr_md5
        and candidate.ocr_md5
        and query_ocr_md5 == candidate.ocr_md5
    )
    if _has_hash(query_phash) and _has_hash(candidate.phash):
        # Visual comparison (both sides carry a pHash): unchanged graded
        # formula. The pHash is a *compat* input, though, and the recognized
        # text is primary — so a weak/stale optional frame must not drag an
        # EXACT recognized-text match below the verdict that same text earns on
        # its own (sending the text without the image HITs at TEXT_EXACT_CONF).
        # No usable text (pure image-vs-image) leaves the score untouched.
        distance: int | None = hamming(query_phash, candidate.phash)
        visual = _phash_confidence(distance)
        confidence = min(1.0, visual + bonus)
        if exact:
            confidence = max(confidence, _text_only_confidence(True, similarity))
    else:
        # 撮影しない text-only comparison: confidence comes from the text
        # signal alone; exact MD5 outranks graded similarity.
        distance = None
        confidence = _text_only_confidence(exact, similarity)
    return ScoredCandidate(
        page_id=candidate.page_id,
        page_index=candidate.page_index,
        hamming=distance,
        ocr_match=ocr_match,
        confidence=round(confidence, 4),
        ocr_similarity=similarity,
    )


def verdict(confidence: float, has_candidates: bool) -> str:
    """Return one of HIT / LOW_CONF / NO_PAGE."""
    if not has_candidates:
        return "NO_PAGE"
    if confidence >= CONF_OK:
        return "HIT"
    if confidence >= CONF_LOW:
        return "LOW_CONF"
    return "NO_PAGE"


def rank(scored: list[ScoredCandidate]) -> list[ScoredCandidate]:
    """Sort candidates by the canonical /match ordering.

    Full-information HITs come first: when the query supplied a signal a
    candidate could not be checked against (signal_coverage < 1), an exact
    match on the remaining signal must not outrank a candidate that reached
    the HIT band on EVERY supplied signal. A STRONG visual match (hamming
    <= HAMMING_STRONG) counts as full information too — that alone puts the
    page's confidence at 1.0 regardless of any unread figure signal, so an
    exact/near-exact pHash match must not lose merely because the page's
    figure reading was never registered. A merely-near pHash match
    (visual < 1.0) still carries the text-coverage penalty, so it cannot
    ignore a supplied figure signal. When every candidate has full coverage
    the tier boundary coincides with the confidence ordering, so
    pure-visual/legacy rankings are unchanged. Within a tier: confidence,
    then a visual match outranks a text-only one (hamming None sorts behind
    every real distance), then text similarity, then coverage; stable sort
    keeps page order after that.
    """
    return sorted(
        scored,
        key=lambda s: (
            not (
                s.confidence >= CONF_OK
                and (
                    s.signal_coverage >= 1.0
                    or (s.hamming is not None and s.hamming <= HAMMING_STRONG)
                )
            ),
            -s.confidence,
            s.hamming if s.hamming is not None else HASH_BIT_LEN + 1,
            -s.ocr_similarity,
            -s.signal_coverage,
        ),
    )


def match(
    query_phash: int | str | None,
    query_ocr_md5: str | None,
    candidates: list[Candidate],
    query_ocr_text: str | None = None,
) -> tuple[ScoredCandidate | None, str, list[ScoredCandidate]]:
    """Score all candidates and return (best, verdict, sorted_candidates)."""
    scored = rank([
        score_candidate(query_phash, query_ocr_md5, c, query_ocr_text)
        for c in candidates
    ])
    best = scored[0] if scored else None
    v = verdict(best.confidence if best else 0.0, bool(scored))
    return best, v, scored

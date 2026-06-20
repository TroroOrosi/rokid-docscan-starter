"""Deterministic page-matching primitives.

Pure-Python implementation (PIL + stdlib only) so the MVP runs without
numpy / imagehash. Provides:

- pHash: 64-bit DCT-based perceptual hash of an image.
- hamming: bit difference between two hashes.
- normalize_ocr_text + ocr_md5: stable MD5 of normalized OCR text.
- score_candidate / match: combine pHash distance and OCR MD5 bonus into a
  confidence score and a HUD verdict.
"""

from __future__ import annotations

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

OCR_MD5_BONUS = 0.35     # confidence added when normalized OCR MD5 matches

# Confidence verdict thresholds (after combining signals).
CONF_OK = 0.62           # >= -> HIT
CONF_LOW = 0.40          # >= but < CONF_OK -> LOW CONF; below -> NO PAGE


# --- pHash ------------------------------------------------------------------

def _dct_1d(vector: list[float]) -> list[float]:
    """Naive type-II DCT for a single vector (small N, fine for MVP)."""
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
    pixels = list(img.getdata())  # noqa: small image, fine for MVP
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
    """Hamming distance between two hashes given as ints or hex strings."""
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


@dataclass
class ScoredCandidate:
    page_id: int
    page_index: int
    hamming: int
    ocr_match: bool
    confidence: float


def _phash_confidence(distance: int) -> float:
    """Map hamming distance to a 0..1 visual-confidence score."""
    if distance <= HAMMING_STRONG:
        return 1.0
    if distance >= HAMMING_WEAK:
        return 0.0
    span = HAMMING_WEAK - HAMMING_STRONG
    return 1.0 - (distance - HAMMING_STRONG) / span


def score_candidate(
    query_phash: int | str,
    query_ocr_md5: str | None,
    candidate: Candidate,
) -> ScoredCandidate:
    distance = hamming(query_phash, candidate.phash)
    visual = _phash_confidence(distance)
    ocr_match = bool(
        query_ocr_md5 and candidate.ocr_md5 and query_ocr_md5 == candidate.ocr_md5
    )
    confidence = visual + (OCR_MD5_BONUS if ocr_match else 0.0)
    confidence = max(0.0, min(1.0, confidence))
    return ScoredCandidate(
        page_id=candidate.page_id,
        page_index=candidate.page_index,
        hamming=distance,
        ocr_match=ocr_match,
        confidence=round(confidence, 4),
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


def match(
    query_phash: int | str,
    query_ocr_md5: str | None,
    candidates: list[Candidate],
) -> tuple[ScoredCandidate | None, str, list[ScoredCandidate]]:
    """Score all candidates and return (best, verdict, sorted_candidates)."""
    scored = [
        score_candidate(query_phash, query_ocr_md5, c) for c in candidates
    ]
    scored.sort(key=lambda s: (-s.confidence, s.hamming))
    best = scored[0] if scored else None
    v = verdict(best.confidence if best else 0.0, bool(scored))
    return best, v, scored

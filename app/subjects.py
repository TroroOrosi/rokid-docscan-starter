"""Heuristic subject detection (科目推定).

A dependency-free first-pass router so the solver can pick a subject-specific
route later (Phase 4). Returns a (subject, confidence) guess from cheap text
features. A real classifier is a drop-in replacement.

Subjects: math / english / classical_jp / physics / chemistry / history /
modern_jp (default).
"""

from __future__ import annotations

import re

from .matching import normalize_ocr_text

_MATH_RE = re.compile(r"[=＝+＋\-−×÷√∫∑πθ]|\d\s*[xyz]\b|方程式|関数|微分|積分|確率")
_ENGLISH_RE = re.compile(r"[A-Za-z]")
_CLASSICAL_RE = re.compile(r"(けり|なり|べし|候|ぞ|なむ|やは|給ふ|つれづれ|いと)")
_PHYSICS_RE = re.compile(r"(速度|加速度|質量|運動量|抵抗|電流|電圧|波長|力\s*N|m/s)")
_CHEM_RE = re.compile(r"(mol|モル|化合物|反応|酸化|還元|H2O|CO2|イオン|原子)")
_HISTORY_RE = re.compile(r"(時代|幕府|天皇|戦争|条約|世紀|[0-9]{3,4}\s*年)")


def detect_subject(text: str | None) -> tuple[str, float]:
    """Return (subject, confidence 0..1) from simple lexical features."""
    raw = text or ""
    if not raw.strip():
        return "unknown", 0.0

    scores: dict[str, int] = {
        "math": len(_MATH_RE.findall(raw)),
        "classical_jp": len(_CLASSICAL_RE.findall(raw)),
        "physics": len(_PHYSICS_RE.findall(raw)),
        "chemistry": len(_CHEM_RE.findall(raw)),
        "history": len(_HISTORY_RE.findall(raw)),
    }

    # English: based on the share of ASCII letters in the text.
    letters = len(_ENGLISH_RE.findall(raw))
    norm = normalize_ocr_text(raw)
    if norm:
        ascii_ratio = letters / max(1, len(norm))
        if ascii_ratio > 0.5:
            scores["english"] = int(ascii_ratio * 10)

    best = max(scores, key=scores.get)
    best_score = scores[best]
    if best_score == 0:
        return "modern_jp", 0.3  # default: nothing distinctive matched

    total = sum(scores.values())
    confidence = round(min(1.0, best_score / total + 0.2), 3) if total else 0.3
    return best, confidence

"""Heuristic subject detection (科目推定) — 共通テスト準拠の実教科.

A dependency-free first-pass classifier that maps exam OCR text to one of the
real Japanese exam subjects, so the solver can apply subject-specific guidance.
Returns a (subject, confidence) guess from keyword scoring. A real classifier
(or a vision model) is a drop-in replacement that fills the same contract.

Subjects (和名 = 実試験教科):
  現代文 / 古文 / 漢文 / 数学 / 英語 /
  物理 / 化学 / 生物 / 地学 /
  世界史 / 日本史 / 地理 / 倫理 / 政治経済 / 現代社会 / 情報
  (＋空入力=unknown、既定=現代文)

基礎科目（物理基礎など）は同一教科に内包し、解答時の深さはプロンプト側で調整する。
英語のリスニングは用紙に現れないため対象外（英語=リーディング相当）。
"""

from __future__ import annotations

import re

from .matching import normalize_ocr_text

#: Stable, machine-readable list of the subjects this classifier can return.
SUBJECTS = (
    "現代文", "古文", "漢文", "数学", "英語",
    "物理", "化学", "生物", "地学",
    "世界史", "日本史", "地理", "倫理", "政治経済", "現代社会", "情報",
)

# Keyword patterns per subject. Order in the dict is the tie-break priority
# (earlier wins on equal score), so more-specific subjects come first.
_PATTERNS: dict[str, re.Pattern] = {
    "漢文": re.compile(r"(返り点|レ点|一二点|書き下し|白文|訓読|再読文字|置き字|漢詩|漢文|[｢「]?而[｣」]?|矣)"),
    "古文": re.compile(r"(けり|なり|べし|給ふ|つれづれ|なむ|やは|係り結び|和歌|枕草子|源氏物語|徒然草|助動詞|傍線部の意味)"),
    "数学": re.compile(r"([=＝×÷√∫∑πθ]|\d\s*[xyzａ-ｚ]|\d\s*[+＋\-−]\s*\d|計算|方程式|不等式|関数|微分|積分|確率|数列|対数|三角比|三角関数|ベクトル|行列|集合|因数分解|座標|図形)"),
    "物理": re.compile(r"(速度|加速度|質量|運動量|運動方程式|力学|抵抗|電流|電圧|磁場|波長|振動|ばね|摩擦|エネルギー保存|m/s|ニュートン|[0-9]\s*N\b)"),
    "化学": re.compile(r"(mol|モル|物質量|化合物|化学反応|酸化|還元|イオン|原子|分子|周期表|中和|pH|溶液|電子配置|H2O|CO2|NaCl)"),
    "生物": re.compile(r"(細胞|遺伝子|DNA|RNA|酵素|光合成|呼吸|タンパク質|進化|生態系|染色体|ホルモン|免疫|神経|代謝)"),
    "地学": re.compile(r"(地層|岩石|火成岩|堆積岩|マグマ|地震|震源|プレート|断層|天体|惑星|恒星|大気|気団|地質)"),
    "情報": re.compile(r"(アルゴリズム|プログラム|擬似言語|フローチャート|2進数|二進数|ビット|バイト|論理回路|論理演算|データベース|IPアドレス|プロトコル|変数|配列|関数呼び出し|情報)"),
    "世界史": re.compile(r"(世界史|王朝|帝国|ローマ|ギリシア|エジプト|十字軍|ルネサンス|産業革命|フランス革命|ヨーロッパ|イスラム|中華|皇帝)"),
    "日本史": re.compile(r"(日本史|幕府|藩|将軍|天皇|摂関|荘園|大化の改新|(江戸|平安|鎌倉|室町|明治|昭和|奈良|飛鳥)時代|武士|条約)"),
    "地理": re.compile(r"(地理|気候|地形|人口|産業|ケッペン|緯度|経度|地図|貿易|都市|農業|工業|プレートテクトニクス|GIS|等高線)"),
    "倫理": re.compile(r"(倫理|哲学|思想|ソクラテス|プラトン|アリストテレス|カント|実存|宗教|仏教|儒教|良心|青年期)"),
    "政治経済": re.compile(r"(政治|経済|憲法|国会|内閣|三権分立|需要|供給|GDP|為替|財政|金融|選挙|市場|インフレ)"),
    "現代社会": re.compile(r"(現代社会|社会保障|少子高齢|グローバル化|情報化社会|環境問題|人権|多文化|持続可能)"),
    "現代文": re.compile(r"(傍線部|筆者|本文|主張|段落|要旨|具体例|次の文章を読ん|空欄|評論|随筆|下線部)"),
}

_ENGLISH_RE = re.compile(r"[A-Za-z]")


def detect_subject(text: str | None) -> tuple[str, float]:
    """Return (subject, confidence 0..1) from keyword scoring over exam text."""
    raw = text or ""
    if not raw.strip():
        return "unknown", 0.0

    scores: dict[str, int] = {}
    for subject, pattern in _PATTERNS.items():
        n = len(pattern.findall(raw))
        if n:
            scores[subject] = n

    # English: share of ASCII letters. Latin script rarely appears in other
    # Japanese-exam subjects, so a high ratio is a strong English signal.
    norm = normalize_ocr_text(raw)
    if norm:
        ascii_ratio = len(_ENGLISH_RE.findall(raw)) / max(1, len(norm))
        if ascii_ratio > 0.5:
            scores["英語"] = max(scores.get("英語", 0), int(ascii_ratio * 10))

    if not scores:
        return "現代文", 0.3  # default: nothing distinctive matched

    # Highest score wins; ties fall to the earlier (more specific) pattern order,
    # then English last. max() over dict keys is stable to insertion order.
    best = max(scores, key=lambda s: scores[s])
    total = sum(scores.values())
    confidence = round(min(1.0, scores[best] / total + 0.2), 3)
    return best, confidence

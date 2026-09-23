"""Heuristic layout / structure extraction for exam pages.

Turns a flat OCR string (and optional client-provided bounding-box hints) into
structured question units: question number, body, choices, figure references,
and an estimated answer-area box. This is a deterministic, dependency-free
heuristic so the server runs offline; a real layout/vision model is a drop-in
replacement that fills the same structures.

Coordinates are normalized 0..1 (x, y from top-left, plus w, h) so they are
resolution-independent. Without a real layout model we ESTIMATE the answer box;
when the client supplies `bbox_hints` for an answer-area token we use it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Question-number patterns (Japanese exam conventions). Order matters: try the
# most specific first.
# 問N carries a lookbehind so 熟語 (学問1/質問3/疑問2/設問…) inside prose never
# fabricates a question boundary — a real boundary is 問 used as a label, not
# as the tail of a compound word.
# 東大 and many 記述式 papers number their 大問 with kanji numerals (第一問),
# so the 大問-level patterns accept both and the number is normalized to
# Arabic: the deck addresses problems by this string, and 第一問 and 第1問 must
# not become two different problems.
_Q_PATTERNS = [
    re.compile(r"大問\s*([0-9０-９]+|[一二三四五六七八九十]+)"),
    re.compile(r"第\s*([0-9０-９]+|[一二三四五六七八九十]+)\s*問"),
    re.compile(r"(?<![学質疑設訪顧諮])問\s*([0-9０-９]+)"),
]
# (n)-style numbering counts only when it LEADS the line — mid-text
# parentheses like 「大戦（1914）」 are years/inline notes, not boundaries.
# Arabic digits realistically run 1-3 digits; the class also matches kanji
# numerals (一-十) and a single Latin capital (A-Z / full-width Ａ-Ｚ), so
# (三) and (A) count as markers too, not just (1). Under a 問N, a letter
# line is that question's choice instead (see parse_layout); elsewhere a
# parenthesized choice list still over-splits, and (1)-style choices do
# everywhere, because text alone cannot tell them from sub-questions.
_PAREN_Q_RE = re.compile(
    r"^\s*[（(]\s*(?:([0-9０-９]{1,3})|([一二三四五六七八九十]{1,3})|([A-ZＡ-Ｚ]))\s*[)）]"
)

# Choice markers: circled digits, katakana enumerals, and A-D / 1-4 list items.
# The 1-4 marker must not be followed by a digit so a decimal-leading line
# (「1.5メートルの棒」) stays in the body instead of becoming a fake choice.
_CHOICE_RE = re.compile(
    r"^\s*(?:[①-⑩]|[ア-オ]|[A-Da-d][.)、]|[1-4][.)、](?![0-9０-９]))\s*(.*\S)?",
    re.UNICODE,
)
_PAGE_RE = re.compile(r"(?:P\.?|ページ|頁)\s*([0-9０-９]+)", re.IGNORECASE)
_FIGURE_RE = re.compile(r"(図\s*[0-9０-９]+|表\s*[0-9０-９]+|グラフ)")
_ANSWER_AREA_RE = re.compile(r"(解答欄|答え|記入欄|解答用紙)")

# Default answer-area estimate when nothing better is known: lower-right of the
# page, where answer columns commonly sit.
_DEFAULT_ANSWER_BOX = {"x": 0.55, "y": 0.72, "w": 0.4, "h": 0.22, "estimated": True}


@dataclass
class QuestionUnit:
    question_no: str | None
    body_text: str
    choices: list[str] = field(default_factory=list)
    figure_refs: list[str] = field(default_factory=list)
    answer_box: dict | None = None


_KANJI_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                 "六": 6, "七": 7, "八": 8, "九": 9}


def _kanji_to_arabic(s: str) -> str:
    """一 -> 1, 十 -> 10, 十二 -> 12, 三十 -> 30. Anything else is returned as is.

    Only 1-99 is supported, which is every 大問 number an exam paper uses.
    """
    if not s or any(c not in _KANJI_DIGITS and c != "十" for c in s):
        return s
    if "十" not in s:
        return str(_KANJI_DIGITS.get(s, s)) if len(s) == 1 else s
    tens, _, ones = s.partition("十")
    return str((_KANJI_DIGITS.get(tens, 1) if tens else 1) * 10
               + (_KANJI_DIGITS.get(ones, 0) if ones else 0))


def _zen_to_han(s: str) -> str:
    """Normalize full-width digits so '問１' and '問1' compare equal."""
    return s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))


def _detect_question_no(line: str) -> str | None:
    for pat in _Q_PATTERNS:
        m = pat.search(line)
        if m:
            num = _kanji_to_arabic(_zen_to_han(m.group(1)))
            if "大問" in pat.pattern:
                return f"大問{num}"
            if "第" in pat.pattern:
                return f"第{num}問"
            return f"問{num}"
    m = _PAREN_Q_RE.match(line)
    if m:
        digits, kanji, letter = m.group(1), m.group(2), m.group(3)
        if digits is not None:
            return f"({_zen_to_han(digits)})"
        return f"({kanji or letter})"
    return None


def _answer_box_from_hints(bbox_hints: list[dict] | None) -> dict | None:
    """If the client tagged an answer-area token with a box, use it."""
    if not bbox_hints:
        return None
    for h in bbox_hints:
        text = str(h.get("text", ""))
        if _ANSWER_AREA_RE.search(text) and "box" in h:
            box = dict(h["box"])
            box["estimated"] = False
            return box
    return None


def parse_layout(
    ocr_text: str | None, *, bbox_hints: list[dict] | None = None
) -> dict:
    """Parse OCR text into {questions, headings, page_number, answer_box}."""
    text = ocr_text or ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    hinted_box = _answer_box_from_hints(bbox_hints)
    answer_box = hinted_box or (
        _DEFAULT_ANSWER_BOX.copy() if _ANSWER_AREA_RE.search(text) else None
    )

    page_number = None
    m = _PAGE_RE.search(text)
    if m:
        page_number = int(_zen_to_han(m.group(1)))

    questions: list[QuestionUnit] = []
    current: QuestionUnit | None = None

    def _flush():
        if current is not None:
            current.body_text = current.body_text.strip()
            questions.append(current)

    for line in lines:
        qno = _detect_question_no(line)
        choice_m = _CHOICE_RE.match(line)
        # RP-12a: under a 小問 (問N), a (A)-style letter line is one of its
        # choices; the whole line is kept so the label survives. Under a 大問
        # or at top level it still splits (東大 1(A)/1(B) are problems).
        paren = _PAREN_Q_RE.match(line)
        if (paren and paren.group(3) and current is not None
                and (current.question_no or "").startswith("問")):
            current.choices.append(line)
            current.figure_refs.extend(_FIGURE_RE.findall(line))
            continue
        if qno is not None and not choice_m:
            _flush()
            current = QuestionUnit(question_no=qno, body_text=line)
        else:
            if current is None:
                current = QuestionUnit(question_no=None, body_text="")
            if choice_m:
                current.choices.append((choice_m.group(1) or line).strip())
            else:
                current.body_text += (" " + line) if current.body_text else line
        current.figure_refs.extend(_FIGURE_RE.findall(line))

    _flush()

    # Attach the (possibly estimated) answer box to each question for overlay.
    box = answer_box or _DEFAULT_ANSWER_BOX.copy()
    for q in questions:
        q.answer_box = dict(box)

    return {
        "questions": questions,
        "headings": [q.question_no for q in questions if q.question_no],
        "page_number": page_number,
        "answer_box": answer_box,  # None if neither hinted nor keyword-detected
    }


def primary_question(parsed: dict) -> QuestionUnit | None:
    """Pick the most relevant question unit (first numbered, else first)."""
    questions: list[QuestionUnit] = parsed.get("questions", [])
    if not questions:
        return None
    for q in questions:
        if q.question_no:
            return q
    return questions[0]


# ---------------------------------------------------------------------------
# Whole-document problem segmentation (3-phase exam flow, phase 2)
# ---------------------------------------------------------------------------

@dataclass
class ProblemUnit:
    """One problem of a whole document, possibly spanning multiple pages."""

    question_no: str | None
    body_text: str
    choices: list[str] = field(default_factory=list)
    start_page_index: int = 0
    page_indexes: list[int] = field(default_factory=list)  # every page it spans


def _figure_block(vision_text: str | None) -> str:
    """Format a page's figure reading for inclusion in a problem body."""
    v = (vision_text or "").strip()
    return f"【図・画像の読み取り】\n{v}" if v else ""


def _is_continuation(problems: list, question_no: str | None) -> bool:
    """True when this number repeats the 大問 already open.

    Only 大問-level numbers (第N問 / 大問N) are treated this way. A repeated
    小問 number (問1 under two different 大問) is a real second question and
    keeps its (2) suffix.
    """
    if not problems or not question_no:
        return False
    if not (question_no.startswith("大問") or question_no.startswith("第")):
        return False
    return problems[-1].question_no == question_no


def segment_problems(
    page_materials: list[tuple[int, str] | tuple[int, str, str | None]],
) -> list[ProblemUnit]:
    """Split a whole document into problems on 問N/大問N/第N問/(n) boundaries.

    ``page_materials`` is ``[(page_index, body_text[, vision_text]), ...]`` in
    page order.  **Boundaries are detected from the BODY text only** — a page's
    figure reading (``vision_text``) is appended to the owning problem AFTER
    segmentation, so figure/table labels like ``(1)`` or ``問1`` inside the
    figure reading can never split one question into several deck problems.
    Each body is scanned with :func:`parse_layout` — a pure per-line scanner —
    so the boundaries are identical to scanning the joined body text, while
    page attribution is preserved.  Merge rules:

    - a numbered unit starts a new problem (``start_page_index`` = that page);
    - a page-leading unnumbered unit has SHARED attribution: it is appended to
      the previous problem (cross-page continuation of its passage) AND, when
      a numbered unit follows on the same page, prepended to that problem's
      body (it may equally be the next problem's prompt/passage — e.g.
      「次の文章を読んで答えよ」 right before 問2; text alone cannot tell the
      two cases apart, and the duplication is harmless because solving always
      receives the whole document as context);
    - unnumbered content before the first numbered problem (cover sheet,
      instructions) is folded into the first problem's body;
    - duplicate question numbers (e.g. 問1 under two 大問) are made unique
      with a suffix (問1(2)) so the review deck / ingest can address them.

    Fallback: a document with no numbered boundary at all becomes ONE problem
    spanning every non-empty page, so the caller always gets >=1 problem for
    a non-empty document.  Deterministic and dependency-free (offline).
    """
    problems: list[ProblemUnit] = []
    preamble_parts: list[str] = []
    preamble_pages: list[int] = []

    for entry in page_materials:
        page_index, material = entry[0], entry[1]
        vision = entry[2] if len(entry) > 2 else None
        units = parse_layout(material)["questions"]
        # Only the first unit of a page can be unnumbered (parse_layout folds
        # later unnumbered lines into the current numbered unit).
        leading = units[0] if units and units[0].question_no is None else None
        numbered = [u for u in units if u.question_no is not None]

        if leading is not None:
            if problems:
                # Continuation of the previous problem onto this page.
                last = problems[-1]
                if leading.body_text:
                    last.body_text = (
                        f"{last.body_text}\n{leading.body_text}"
                        if last.body_text
                        else leading.body_text
                    )
                last.choices.extend(leading.choices)
                if page_index not in last.page_indexes:
                    last.page_indexes.append(page_index)
            else:
                if leading.body_text:
                    preamble_parts.append(leading.body_text)
                if leading.choices:
                    preamble_parts.extend(leading.choices)
                preamble_pages.append(page_index)

        for pos, unit in enumerate(numbered):
            body = unit.body_text
            if _is_continuation(problems, unit.question_no):
                # The same 大問 number again on a later page. Exam booklets
                # print a 第N問 side tab on EVERY page of that 大問, so this is
                # the 大問 continuing, never a second one with the same number.
                # Measured on the 2026 共通テスト 数学Ⅰ・Ａ PDF: without this,
                # 4 大問 across 26 pages became 26 problems, i.e. 26 solver
                # calls instead of 4, each seeing only its own page.
                last = problems[-1]
                if pos == 0 and leading is not None and leading.body_text:
                    body = (
                        f"{leading.body_text}\n{body}" if body else leading.body_text
                    )
                if body:
                    last.body_text = (
                        f"{last.body_text}\n{body}" if last.body_text else body
                    )
                last.choices.extend(unit.choices)
                if page_index not in last.page_indexes:
                    last.page_indexes.append(page_index)
                continue
            # Shared attribution (see docstring): the page-leading block may be
            # the prompt/passage of THIS problem, so the first numbered problem
            # of the page also receives it. (Skipped when it went to the
            # preamble — the preamble is prepended to problems[0] at the end.)
            if pos == 0 and leading is not None and problems and leading.body_text:
                body = f"{leading.body_text}\n{body}" if body else leading.body_text
            problems.append(
                ProblemUnit(
                    question_no=unit.question_no,
                    body_text=body,
                    choices=list(unit.choices),
                    start_page_index=page_index,
                    page_indexes=[page_index],
                )
            )

        # Attach the page's figure reading AFTER boundary detection so its
        # labels never split a question. A page's vision_text is a PAGE-level
        # signal — we cannot reliably tell WHICH same-page problem references
        # the figure — so it is duplicated across EVERY problem this page
        # contributes to. The figure-dependent problem is then guaranteed the
        # values (a sibling problem may get some extra context, which is
        # harmless) instead of the figure landing only on the last problem.
        fig = _figure_block(vision)
        if fig:
            owning = [p for p in problems if page_index in p.page_indexes]
            if owning:
                for target in owning:
                    target.body_text = (
                        f"{target.body_text}\n{fig}" if target.body_text else fig
                    )
            elif problems:
                # Figure-only page (no text units of its own): a trailing
                # figure usually belongs to the most recent problem.
                target = problems[-1]
                target.body_text = (
                    f"{target.body_text}\n{fig}" if target.body_text else fig
                )
                if page_index not in target.page_indexes:
                    target.page_indexes.append(page_index)
            else:
                preamble_parts.append(fig)
                if page_index not in preamble_pages:
                    preamble_pages.append(page_index)

    if not problems:
        # No numbered boundary anywhere: the whole document is one problem.
        # Combine each page's body with its figure reading for the body.
        non_empty: list[tuple[int, str]] = []
        for entry in page_materials:
            pidx, body = entry[0], entry[1]
            vision = entry[2] if len(entry) > 2 else None
            parts = [p for p in ((body or "").strip(), _figure_block(vision)) if p]
            if parts:
                non_empty.append((pidx, "\n".join(parts)))
        if not non_empty:
            return []
        return [
            ProblemUnit(
                question_no=None,
                body_text="\n\n".join(m.strip() for _, m in non_empty),
                start_page_index=non_empty[0][0],
                page_indexes=[i for i, _ in non_empty],
            )
        ]

    if preamble_parts:
        first = problems[0]
        first.body_text = "\n".join(preamble_parts + [first.body_text]).strip()
        first.page_indexes = sorted(set(preamble_pages) | set(first.page_indexes))

    # Disambiguate duplicate numbers: the deck / ingest address problems by
    # this string, so it must be unique within the document.
    seen: dict[str, int] = {}
    for p in problems:
        if p.question_no is None:
            continue
        n = seen.get(p.question_no, 0) + 1
        seen[p.question_no] = n
        if n > 1:
            p.question_no = f"{p.question_no}({n})"

    return problems

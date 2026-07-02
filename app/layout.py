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
_Q_PATTERNS = [
    re.compile(r"大問\s*([0-9０-９]+)"),
    re.compile(r"第\s*([0-9０-９]+)\s*問"),
    re.compile(r"問\s*([0-9０-９]+)"),
    re.compile(r"[（(]\s*([0-9０-９]+)\s*[)）]"),
]

# Choice markers: circled digits, katakana enumerals, and A-D / 1-4 list items.
_CHOICE_RE = re.compile(
    r"^\s*(?:[①-⑩]|[ア-オ]|[A-Da-d][.)、]|[1-4][.)、])\s*(.*\S)?", re.UNICODE
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


def _zen_to_han(s: str) -> str:
    """Normalize full-width digits so '問１' and '問1' compare equal."""
    return s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))


def _detect_question_no(line: str) -> str | None:
    for pat in _Q_PATTERNS:
        m = pat.search(line)
        if m:
            num = _zen_to_han(m.group(1))
            if "大問" in pat.pattern:
                return f"大問{num}"
            if "第" in pat.pattern:
                return f"第{num}問"
            if "問" in pat.pattern:
                return f"問{num}"
            return f"({num})"
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


def segment_problems(page_materials: list[tuple[int, str]]) -> list[ProblemUnit]:
    """Split a whole document into problems on 問N/大問N/第N問/(n) boundaries.

    ``page_materials`` is ``[(page_index, material_text), ...]`` in page order
    (material = the page's recognized text incl. the figure reading).  Each
    page is scanned with :func:`parse_layout` — a pure per-line scanner — so
    the boundaries are identical to scanning the joined text, while page
    attribution is preserved.  Merge rules:

    - a numbered unit starts a new problem (``start_page_index`` = that page);
    - a page-leading unnumbered unit is a cross-page CONTINUATION of the
      previous problem (a problem starting on page N and running into N+1);
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

    for page_index, material in page_materials:
        for unit in parse_layout(material)["questions"]:
            if unit.question_no is not None:
                problems.append(
                    ProblemUnit(
                        question_no=unit.question_no,
                        body_text=unit.body_text,
                        choices=list(unit.choices),
                        start_page_index=page_index,
                        page_indexes=[page_index],
                    )
                )
            elif problems:
                # Only the first unit of a page can be unnumbered -> this is
                # the continuation of the last problem onto this page.
                last = problems[-1]
                if unit.body_text:
                    last.body_text = (
                        f"{last.body_text}\n{unit.body_text}"
                        if last.body_text
                        else unit.body_text
                    )
                last.choices.extend(unit.choices)
                if page_index not in last.page_indexes:
                    last.page_indexes.append(page_index)
            else:
                if unit.body_text:
                    preamble_parts.append(unit.body_text)
                if unit.choices:
                    preamble_parts.extend(unit.choices)
                preamble_pages.append(page_index)

    if not problems:
        # No numbered boundary anywhere: the whole document is one problem.
        non_empty = [(i, m) for i, m in page_materials if (m or "").strip()]
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

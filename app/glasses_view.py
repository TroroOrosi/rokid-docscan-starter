"""Build the on-glasses view payload (silent, monochrome, 3 short lines).

Hardware reality (Rokid Glasses): monochrome green Micro-LED, 480x398/eye,
~23deg FOV, 10-level dimming. So the payload is intentionally minimal and
SILENT-FRIENDLY:

- at most 3 short lines per page (long text is paginated, teleprompter-style),
- NO audio cues and NO animation directives (the client must render with no
  shutter sound, no white flash, no blinking, instant text replace),
- confidence shown as a static symbol (no blinking),
- a `locator` text hint to the answer area (we do NOT world-lock to paper).

Stages:
  exam mode:    answer -> solution -> rationale -> caution
  explain mode: overview -> detail -> evidence

Navigation is always button/touch/swipe — voice is opt-in only.
Swipe left/right  : move between view_page offsets (teleprompter scroll)
Swipe up/down     : move between explain stages
Double long-press : commit scan phase (scanning -> ready)
Single tap        : show explanation for current page
"""

from __future__ import annotations

from .explainer import ExplainResult
from .solvers import SolveResult

STAGES = ("answer", "solution", "rationale", "caution")
EXPLAIN_STAGES = ("overview", "detail", "evidence")

_MAX_LINES = 3
_MAX_LINE_CHARS = 24  # ~Japanese chars that fit one HUD line

# Server-authoritative render contract for the on-glasses display.
RENDER_CONTRACT = {
    "max_lines": _MAX_LINES,
    "silent": True,
    "white_flash": False,
    "animations": False,
    "transition": "instant",
    "blinking": False,
    "brightness": "low",
}

# Capture-path contract. privacy_led is hardware-enforced; always on.
CAPTURE_CONTRACT = {
    "shutter_sound": False,
    "camera_path": "cxr-s/camera2",
    "privacy_led": {"state": "always_on", "tamper": "forbidden"},
}

# Operation mapping advertised to the client (voice_enabled=false branch).
# Matches Rokid touchpad: tap / swipe-left / swipe-right / long-press /
# double-long-press as documented in the official Academy hardware guide.
OPERATION_CONTRACT = {
    "scan_page": "button_press",           # 1-press: scan current page
    "commit_scan": "double_long_press",    # finish scanning, enter ready state
    "show_explain": "tap",                 # show explanation for matched page
    "next_view_page": "swipe_left",        # teleprompter: next 3-line slice
    "prev_view_page": "swipe_right",       # teleprompter: prev 3-line slice
    "next_stage": "swipe_down",            # overview -> detail -> evidence
    "prev_stage": "swipe_up",
    "voice_hint": None,                    # voice disabled by default
}


def build_capture_ack(
    *, page_number: int | None = None, question_id: int | None = None
) -> dict:
    """Silent, no-flash capture confirmation: one short HUD line, ~2 s."""
    if page_number is not None:
        label = f"P{page_number:02d}"
    elif question_id is not None:
        label = f"#{question_id}"
    else:
        label = ""
    line = f"{label} 保存済み".strip()
    return {"lines": [line][:_MAX_LINES], "ttl_sec": 2}


def _confidence_symbol(conf: float) -> str:
    if conf >= 0.66:
        return "★★★"
    if conf >= 0.33:
        return "★★☆"
    return "★☆☆"


def _locator(answer_box: dict | None) -> str:
    if not answer_box:
        return ""
    cx = answer_box.get("x", 0) + answer_box.get("w", 0) / 2
    cy = answer_box.get("y", 0) + answer_box.get("h", 0) / 2
    vert = "上" if cy < 0.4 else ("下" if cy > 0.6 else "中")
    horiz = "左" if cx < 0.4 else ("右" if cx > 0.6 else "中")
    return f"解答欄: {vert}{horiz}"


def _wrap(text: str) -> list[str]:
    """Split a string into <=_MAX_LINE_CHARS chunks (no hyphenation)."""
    text = (text or "").strip()
    if not text:
        return []
    return [text[i : i + _MAX_LINE_CHARS] for i in range(0, len(text), _MAX_LINE_CHARS)]


def _stage_lines(
    stage: str, solution: SolveResult, page_label: str, locator: str
) -> list[str]:
    if stage == "answer":
        head = f"{page_label} {_confidence_symbol(solution.answer_confidence)}".strip()
        lines = [head, f"答え: {solution.answer}"]
        if locator:
            lines.append(locator)
        return lines
    if stage == "solution":
        steps = solution.solution_steps or ["(解法なし)"]
        return ["解法"] + [s for s in steps]
    if stage == "rationale":
        ev = (
            "根拠ページ: " + ",".join(f"P{p:02d}" for p in solution.evidence_pages)
            if solution.evidence_pages
            else ""
        )
        return ["根拠", solution.rationale or "(なし)"] + ([ev] if ev else [])
    # caution
    return ["注意", solution.cautions or "(なし)"]


def _paginate(lines: list[str]) -> list[list[str]]:
    """Wrap each logical line, then chunk into pages of <=_MAX_LINES lines."""
    wrapped: list[str] = []
    for ln in lines:
        wrapped.extend(_wrap(ln) or [""])
    if not wrapped:
        wrapped = [""]
    return [wrapped[i : i + _MAX_LINES] for i in range(0, len(wrapped), _MAX_LINES)]


def build_locked_view(stage: str = "answer") -> dict:
    """Real-exam mode (locked): never reveal an answer."""
    return {
        "stage": stage,
        "page": 0,
        "total_pages": 1,
        "lines": ["本番試験モード", "解答は表示しません", "学習/模試で使用してください"],
        "locator": "",
        "locked": True,
        "nav": {"prev": None, "next": None, "stages": list(STAGES)},
    }


def build_glasses_view(
    solution: SolveResult,
    *,
    stage: str = "answer",
    page: int = 0,
    question_no: str | None = None,
    page_number: int | None = None,
    answer_box: dict | None = None,
    voice_enabled: bool = False,
) -> dict:
    """Return one page of the staged, silent-friendly on-glasses view."""
    if stage not in STAGES:
        stage = "answer"
    page_label = " ".join(
        x
        for x in (
            f"P{page_number:02d}" if page_number is not None else None,
            question_no,
        )
        if x
    )
    pages = _paginate(_stage_lines(stage, solution, page_label, _locator(answer_box)))
    total = len(pages)
    page = max(0, min(page, total - 1))

    return {
        "stage": stage,
        "page": page,
        "total_pages": total,
        "lines": pages[page],
        "locator": _locator(answer_box),
        "locked": False,
        "nav": {
            "prev": page - 1 if page > 0 else None,
            "next": page + 1 if page < total - 1 else None,
            "stages": list(STAGES),
            "hint": "『次の答え』と言う" if voice_enabled else "前面ボタンで次へ",
        },
    }


# ---------------------------------------------------------------------------
# Explain-mode view builder (explain-sessions feature)
# ---------------------------------------------------------------------------

_EXPLAIN_STAGE_LABELS = {
    "overview": "概要",
    "detail":   "詳細",
    "evidence": "根拠",
}


def _explain_stage_lines(
    stage: str,
    result: ExplainResult,
    page_label: str,
) -> list[str]:
    """Build logical lines for the requested explain stage.

    overview : HUD lines from ExplainResult (already <=24 chars each)
    detail   : full detail text split into lines
    evidence : evidence page list
    """
    label = _EXPLAIN_STAGE_LABELS.get(stage, stage)
    if stage == "overview":
        # result.lines is already 3 short lines from the Explainer adapter.
        # Prepend the page label on line-0 only when it fits.
        head = f"{page_label} {_confidence_symbol(result.confidence)}".strip()
        return [head] + (result.lines or [])
    if stage == "detail":
        detail_text = result.detail or "(詳細なし)"
        return [label] + [detail_text]
    # evidence
    if result.evidence_pages:
        ev = ",".join(f"P{p:02d}" for p in result.evidence_pages)
        return [label, f"参照: {ev}"]
    return [label, "(根拠ページなし)"]


def build_explain_view(
    result: ExplainResult,
    *,
    stage: str = "overview",
    view_page: int = 0,
    page_index: int | None = None,
    total_doc_pages: int | None = None,
    voice_enabled: bool = False,
) -> dict:
    """Return one paginated HUD view for an explain-session page.

    Pagination (teleprompter-style):
      - Each logical line is _wrap()ped into <=24-char physical lines.
      - Physical lines are chunked into slices of 3 (view pages).
      - Client navigates with swipe_left (next) / swipe_right (prev).

    Stage navigation (swipe_down / swipe_up):
      overview -> detail -> evidence

    Args:
        result:          ExplainResult from the Explainer adapter.
        stage:           One of EXPLAIN_STAGES.
        view_page:       0-based index of the 3-line teleprompter page.
        page_index:      0-based document page index (for the HUD label).
        total_doc_pages: total pages in the document (for P02/10 label).
        voice_enabled:   If True, hint text uses voice phrasing.
    """
    if stage not in EXPLAIN_STAGES:
        stage = "overview"

    # Build page label: "P02/10" or "P02" depending on available info.
    if page_index is not None:
        if total_doc_pages is not None:
            page_label = f"P{page_index + 1:02d}/{total_doc_pages}"
        else:
            page_label = f"P{page_index + 1:02d}"
    else:
        page_label = ""

    logical_lines = _explain_stage_lines(stage, result, page_label)
    pages = _paginate(logical_lines)
    total_view_pages = len(pages)
    view_page = max(0, min(view_page, total_view_pages - 1))

    # Stage navigation neighbours.
    stage_idx = EXPLAIN_STAGES.index(stage)
    prev_stage = EXPLAIN_STAGES[stage_idx - 1] if stage_idx > 0 else None
    next_stage = (
        EXPLAIN_STAGES[stage_idx + 1] if stage_idx < len(EXPLAIN_STAGES) - 1 else None
    )

    # Build operation hint (silent by default).
    if total_view_pages > 1 and next_stage:
        hint = "← 次ページ / ↓ 次段階"
    elif total_view_pages > 1:
        hint = "← 次ページ / ↑ 前段階"
    elif next_stage:
        hint = "↓ 次段階へ"
    else:
        hint = "↑ 概要へ戻る"

    return {
        "stage": stage,
        "view_page": view_page,
        "total_view_pages": total_view_pages,
        "lines": pages[view_page],
        "page_label": page_label,
        "locked": False,
        "nav": {
            "prev_view_page": view_page - 1 if view_page > 0 else None,
            "next_view_page": view_page + 1 if view_page < total_view_pages - 1 else None,
            "prev_stage": prev_stage,
            "next_stage": next_stage,
            "stages": list(EXPLAIN_STAGES),
            "operations": OPERATION_CONTRACT,
            "hint": hint,
        },
    }


def build_scan_ack(page_index: int, scanned_count: int, total_pages: int) -> dict:
    """Silent HUD feedback shown immediately after each page scan.

    Displayed during the [scanning] phase (before commit).
    Shows: 'P02 読取済 ✓' and progress fraction.
    ttl_sec=2 so it clears automatically before the next scan.
    """
    label = f"P{page_index + 1:02d} 読取済 ✓"
    progress = f"{scanned_count}/{total_pages}ページ完了"
    hint = "完了: ダブル長押し" if scanned_count >= total_pages else "次ページへ"
    return {
        "lines": [label, progress, hint],
        "ttl_sec": 2,
        "scanned_count": scanned_count,
        "total_pages": total_pages,
        "all_scanned": scanned_count >= total_pages,
    }

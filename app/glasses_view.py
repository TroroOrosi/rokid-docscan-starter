"""Build the on-glasses view payload (silent, monochrome, 3 short lines).

Hardware reality (Rokid Glasses): monochrome green Micro-LED, 480x398/eye,
~23deg FOV, 10-level dimming. So the payload is intentionally minimal and
SILENT-FRIENDLY:

- at most 3 short lines per page (long text is paginated, teleprompter-style),
- NO audio cues and NO animation directives (the client must render with no
  shutter sound, no white flash, no blinking, instant text replace),
- confidence shown as a static symbol (no blinking),
- a `locator` text hint to the answer area (we do NOT world-lock to paper).

Stages: answer -> solution -> rationale -> caution, navigated by button/voice.

Explain mode (explain-sessions) adds 3 phases:
  scanning : user sweeps pages; each returns a silent scan_ack only.
  ready    : user double-long-presses; session committed, content unlocked.
  explaining: GET explain?page_index=N&view_page=M returns build_explain_view()
              paginated by swipe (no voice required, button-only).

Operation map (voice_enabled=false, silent/button-only):
  Single tap       -> confirm / next answer
  Swipe left/right -> next / prev HUD view_page
  Long press       -> stage advance (answer->solution->rationale)
  Double long press-> commit scan (scanning->ready) / end session
"""

from __future__ import annotations

from .explainer import ExplainResult
from .solvers import SolveResult

STAGES = ("answer", "solution", "rationale", "caution")
EXPLAIN_PHASES = ("scanning", "ready", "explaining")

_MAX_LINES = 3
_MAX_LINE_CHARS = 24

RENDER_CONTRACT = {
    "max_lines": _MAX_LINES,
    "silent": True,
    "white_flash": False,
    "animations": False,
    "transition": "instant",
    "blinking": False,
    "brightness": "low",
}

CAPTURE_CONTRACT = {
    "shutter_sound": False,
    "camera_path": "cxr-s/camera2",
    "privacy_led": {"state": "always_on", "tamper": "forbidden"},
}


def build_capture_ack(
    *, page_number: int | None = None, question_id: int | None = None
) -> dict:
    """Silent capture confirmation for exam-session questions."""
    if page_number is not None:
        label = f"P{page_number:02d}"
    elif question_id is not None:
        label = f"#{question_id}"
    else:
        label = ""
    line = f"{label} \u4fdd\u5b58\u6e08".strip()
    return {"lines": [line][:_MAX_LINES], "ttl_sec": 2}


def build_scan_ack(*, page_index: int, scanned: int, total: int) -> dict:
    """Silent HUD ack during explain-session scanning phase.

    Shows which page was just registered and scan progress.
    No content is revealed until the user commits (double long-press).

    Example (3 lines):
        P03 \u8aad\u53d6\u6e08 \u2713
        3/5 \u30da\u30fc\u30b8\u5b8c\u4e86
        \u30c0\u30d6\u30eb\u9577\u62bc\u3067\u89e3\u8aac\u958b\u59cb
    """
    p_label = f"P{page_index + 1:02d}"
    line1 = f"{p_label} \u8aad\u53d6\u6e08 \u2713"
    line2 = f"{scanned}/{total} \u30da\u30fc\u30b8\u5b8c\u4e86"
    line3 = (
        "\u5168\u30da\u30fc\u30b8OK \u9577\u62bc\u3057\u3066"
        if scanned >= total
        else "\u30c0\u30d6\u30eb\u9577\u62bc\u3067\u89e3\u8aac\u958b\u59cb"
    )
    return {
        "phase": "scanning",
        "page_index": page_index,
        "scanned": scanned,
        "total": total,
        "lines": [line1, line2, line3],
        "ttl_sec": 2,
    }


def build_commit_ack(*, total: int) -> dict:
    """HUD shown after double-long-press commits the scan (scanning->ready)."""
    return {
        "phase": "ready",
        "lines": [
            "\u30b9\u30ad\u30e3\u30f3\u5b8c\u4e86",
            f"{total}\u30da\u30fc\u30b8\u767b\u9332\u6e08",
            "\u30bf\u30c3\u30d7\u3067\u89e3\u8aac\u958b\u59cb",
        ],
        "ttl_sec": 3,
    }


def _confidence_symbol(conf: float) -> str:
    if conf >= 0.66:
        return "\u2605\u2605\u2605"
    if conf >= 0.33:
        return "\u2605\u2605\u2606"
    return "\u2605\u2606\u2606"


def _locator(answer_box: dict | None) -> str:
    if not answer_box:
        return ""
    cx = answer_box.get("x", 0) + answer_box.get("w", 0) / 2
    cy = answer_box.get("y", 0) + answer_box.get("h", 0) / 2
    vert = "\u4e0a" if cy < 0.4 else ("\u4e0b" if cy > 0.6 else "\u4e2d")
    horiz = "\u5de6" if cx < 0.4 else ("\u53f3" if cx > 0.6 else "\u4e2d")
    return f"\u89e3\u7b54\u6b04: {vert}{horiz}"


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
        lines = [head, f"\u7b54\u3048: {solution.answer}"]
        if locator:
            lines.append(locator)
        return lines
    if stage == "solution":
        steps = solution.solution_steps or ["(\u89e3\u6cd5\u306a\u3057)"]
        return ["\u89e3\u6cd5"] + [s for s in steps]
    if stage == "rationale":
        ev = (
            "\u6839\u62e0\u30da\u30fc\u30b8: "
            + ",".join(f"P{p:02d}" for p in solution.evidence_pages)
            if solution.evidence_pages
            else ""
        )
        return ["\u6839\u62e0", solution.rationale or "(\u306a\u3057)"] + ([ev] if ev else [])
    return ["\u6ce8\u610f", solution.cautions or "(\u306a\u3057)"]


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
        "lines": [
            "\u672c\u756a\u8a66\u9a13\u30e2\u30fc\u30c9",
            "\u89e3\u7b54\u306f\u8868\u793a\u3057\u307e\u305b\u3093",
            "\u5b66\u7fd2/\u6a21\u8a66\u3067\u4f7f\u7528\u3057\u3066\u304f\u3060\u3055\u3044",
        ],
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
            "hint": "\u300c\u6b21\u306e\u7b54\u3048\u300d\u3068\u8a00\u3046" if voice_enabled else "\u524d\u9762\u30dc\u30bf\u30f3\u3067\u6b21\u3078",
        },
    }


def build_explain_view(
    result: ExplainResult,
    *,
    page_index: int,
    total_doc_pages: int,
    view_page: int = 0,
    voice_enabled: bool = False,
) -> dict:
    """Build the HUD payload for one page of an explain-session.

    Layout (teleprompter, swipe to paginate):
      view_page 0 : P02/05 \u2605\u2605\u2605  (header)
                    <detail line 1>
                    <detail line 2>
      view_page 1 : <detail line 3>
                    ...
      last page   : \u53c2\u7167: P01 P03  (evidence footnote, if any)

    Swipe left/right maps to nav.next / nav.prev (no voice required).
    """
    p_label = f"P{page_index + 1:02d}/{total_doc_pages:02d}"
    conf_sym = _confidence_symbol(result.confidence)
    header = f"{p_label} {conf_sym}"

    logical: list[str] = [header]
    for part in (result.detail or "\u89e3\u8aac\u306a\u3057").split("\n"):
        part = part.strip()
        if part:
            logical.append(part)
    if result.evidence_pages:
        ev = "\u53c2\u7167: " + " ".join(f"P{p + 1:02d}" for p in result.evidence_pages)
        logical.append(ev)

    pages = _paginate(logical)
    total = len(pages)
    view_page = max(0, min(view_page, total - 1))

    return {
        "phase": "explaining",
        "page_index": page_index,
        "total_doc_pages": total_doc_pages,
        "view_page": view_page,
        "total_view_pages": total,
        "lines": pages[view_page],
        "locked": False,
        "nav": {
            "prev": view_page - 1 if view_page > 0 else None,
            "next": view_page + 1 if view_page < total - 1 else None,
            "hint": "\u300c\u6b21\u3078\u300d\u3068\u8a00\u3046" if voice_enabled else "\u30b9\u30ef\u30a4\u30d7\u3067\u6b21\u30da\u30fc\u30b8",
        },
    }

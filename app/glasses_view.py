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

Explain-session additions (2-phase document explanation):
- build_explain_scan_ack(): silent ACK shown while scanning (phase 1).
- build_explain_view(): paginated explanation view for ExplainResult (phase 2).
  Operates identically to build_glasses_view() but accepts ExplainResult instead
  of SolveResult.  nav.hint always uses the silent-button wording.
"""

from __future__ import annotations

from .solvers import SolveResult

STAGES = ("answer", "solution", "rationale", "caution")

# Explain-session stages navigated by front-button / touchpad swipe.
# detail -> context are the two stages; "detail" shows the page explanation,
# "context" shows the evidence pages (other pages referenced for context).
EXPLAIN_STAGES = ("detail", "context")

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

CAPTURE_CONTRACT = {
    "shutter_sound": False,
    "camera_path": "cxr-s/camera2",
    "privacy_led": {"state": "always_on", "tamper": "forbidden"},
}

# Button / touchpad operation map (silent mode, no voice).
# Clients must implement these gestures; the server only encodes hints in nav.
# Ref: Rokid Academy — input methods: touch gestures on temple + physical button.
# https://global.rokid.com/pages/academy
BUTTON_HINT_SILENT = "前面ボタンで次へ"
BUTTON_HINT_COMMIT = "ダブル長押しで確定"
BUTTON_HINT_EXPLAIN = "タップで解説開始"


def build_capture_ack(
    *, page_number: int | None = None, question_id: int | None = None
) -> dict:
    """A silent, no-flash capture confirmation: one short HUD line, ~2s."""
    if page_number is not None:
        label = f"P{page_number:02d}"
    elif question_id is not None:
        label = f"#{question_id}"
    else:
        label = ""
    line = f"{label} 保存済".strip()
    return {"lines": [line][:_MAX_LINES], "ttl_sec": 2}


def build_explain_scan_ack(
    *,
    page_index: int,
    total_pages: int,
    scanned_count: int,
    verdict: str,
) -> dict:
    """Silent ACK shown on HUD while the user is scanning pages (phase 1).

    Replaces shutter sound / white flash with a minimal 2-line status.
    No explanation is shown here — that waits until commit (phase 2).

    Example HUD:
        P03 読取済 ✓         <- page label + static check symbol
        3/5 ページ         <- scanned / total progress
        ダブル長押しで確定    <- commit hint (shown when all pages scanned)
    """
    page_label = f"P{page_index + 1:02d}"
    symbol = "✓" if verdict == "HIT" else ("?" if verdict == "LOW_CONF" else "×")
    line1 = f"{page_label} 読取済 {symbol}"
    line2 = f"{scanned_count}/{total_pages} ページ"
    # Hint line: show commit hint only when all registered pages are scanned.
    line3 = BUTTON_HINT_COMMIT if scanned_count >= total_pages else ""
    return {
        "lines": [line1, line2, line3],
        "ttl_sec": 2,
        "phase": "scanning",
    }


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
            "hint": "「次の答え」と言う" if voice_enabled else BUTTON_HINT_SILENT,
        },
    }


def build_explain_view(
    *,
    page_index: int,
    total_doc_pages: int,
    hud_lines_all: list[str],
    evidence_pages: list[int],
    stage: str = "detail",
    view_page: int = 0,
) -> dict:
    """Build the paginated HUD view for the explain-session explanation phase.

    Accepts the full flat list of HUD lines from ExplainResult and paginates
    them into 3-line pages.  The client advances view_page via swipe/button;
    stage switches between 'detail' (explanation text) and 'context' (evidence).

    nav.hint is always the silent-button wording (voice_enabled is not supported
    in explain-sessions: audio-free by design).

    Example (detail stage, view_page=0):
        P03 3/5 ★★★          <- page label + doc position + confidence
        このページは構文を        <- explanation line 1
        説明しています         <- explanation line 2 (wrapped)
    """
    if stage not in EXPLAIN_STAGES:
        stage = "detail"

    page_label = f"P{page_index + 1:02d} {page_index + 1}/{total_doc_pages}"

    if stage == "detail":
        logical_lines = [page_label] + hud_lines_all
    else:  # context
        if evidence_pages:
            ev_str = "根拠: " + " ".join(f"P{p + 1:02d}" for p in evidence_pages)
        else:
            ev_str = "根拠: なし"
        logical_lines = ["関連ページ", ev_str]

    pages = _paginate(logical_lines)
    total = len(pages)
    view_page = max(0, min(view_page, total - 1))

    # When we are on the last view_page of 'detail', the next action is
    # switching to 'context' stage; encode this in next_stage.
    at_last = view_page >= total - 1
    next_stage: str | None = None
    prev_stage: str | None = None
    if stage == "detail" and at_last:
        next_stage = "context"
    if stage == "context":
        prev_stage = "detail"

    return {
        "stage": stage,
        "page": view_page,
        "total_pages": total,
        "lines": pages[view_page],
        "phase": "explaining",
        "nav": {
            "prev": view_page - 1 if view_page > 0 else None,
            "next": view_page + 1 if not at_last else None,
            "next_stage": next_stage,
            "prev_stage": prev_stage,
            "stages": list(EXPLAIN_STAGES),
            # Always silent-button wording; no voice in explain-sessions.
            "hint": BUTTON_HINT_SILENT,
        },
    }

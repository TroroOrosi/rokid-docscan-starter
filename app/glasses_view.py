"""Build the on-glasses view payload (silent, monochrome, 3 short lines).

Hardware reality (Rokid Glasses): monochrome green Micro-LED, 480x398/eye,
~23deg FOV, 10-level dimming. So the payload is intentionally minimal and
SILENT-FRIENDLY:

- at most 3 short lines per page (long text is paginated, teleprompter-style),
- NO audio cues and NO animation directives (the client must render with no
  shutter sound, no white flash, no blinking, instant text replace),
- confidence shown as a static symbol (no blinking),
- a `locator` text hint to the answer area (we do NOT world-lock to paper).

Exam stages:    answer -> solution -> rationale -> caution  (button/swipe).
Explain stages: summary -> detail -> evidence               (button/swipe).

Navigation contract (client-side):
  - Swipe forward / front button tap : move to nav.next page (or next stage).
  - Long-press                        : advance to next stage.
  - Double long-press                 : commit scan (scanning -> ready).
  All operations are SILENT (voice_enabled=false by default).

Public API for the explain-sessions feature:
  build_explain_scan_ack()  -- silent ACK shown while scanning each page.
  build_explain_view()      -- staged HUD for a single explained page.
  build_explain_status()    -- scanning progress (scanned N / total M).
"""

from __future__ import annotations

from .solvers import SolveResult

# --- Exam solver stages (unchanged) ----------------------------------------
STAGES = ("answer", "solution", "rationale", "caution")

# --- Explain session stages -------------------------------------------------
# summary : first-line explanation (what this page is about)
# detail  : expanded explanation (with multi-page context evidence)
# evidence: which other pages were used as context
EXPLAIN_STAGES = ("summary", "detail", "evidence")

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

# Capture-path contract.
CAPTURE_CONTRACT = {
    "shutter_sound": False,
    "camera_path": "cxr-s/camera2",
    "privacy_led": {"state": "always_on", "tamper": "forbidden"},
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

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
    return [text[i: i + _MAX_LINE_CHARS] for i in range(0, len(text), _MAX_LINE_CHARS)]


def _paginate(lines: list[str]) -> list[list[str]]:
    """Wrap each logical line, then chunk into pages of <=_MAX_LINES lines."""
    wrapped: list[str] = []
    for ln in lines:
        wrapped.extend(_wrap(ln) or [""])
    if not wrapped:
        wrapped = [""]
    return [wrapped[i: i + _MAX_LINES] for i in range(0, len(wrapped), _MAX_LINES)]


def _nav(page: int, total: int, hint: str, stages: tuple) -> dict:
    return {
        "prev": page - 1 if page > 0 else None,
        "next": page + 1 if page < total - 1 else None,
        "stages": list(stages),
        "hint": hint,
    }


# ---------------------------------------------------------------------------
# Capture ACK (exam & explain shared)
# ---------------------------------------------------------------------------

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
    line = f"{label} \u4fdd\u5b58\u6e08".strip()
    return {"lines": [line][:_MAX_LINES], "ttl_sec": 2}


# ---------------------------------------------------------------------------
# Explain-session specific HUD builders
# ---------------------------------------------------------------------------

def build_explain_scan_ack(
    *, page_index: int, scanned: int, total: int
) -> dict:
    """Silent ACK displayed each time the user scans one page during scanning
    phase. Shows current progress so the user knows how many pages remain.

    Example HUD::

        P03 \u8aad\u53d6\u6e08 \u2713
        3 / 5 \u30da\u30fc\u30b8
        (\u30c0\u30d6\u30eb\u9577\u62bc\u3057\u3067\u5b8c\u4e86)
    """
    lines = [
        f"P{page_index + 1:02d} \u8aad\u53d6\u6e08 \u2713",
        f"{scanned} / {total} \u30da\u30fc\u30b8",
        "(\u30c0\u30d6\u30eb\u9577\u62bc\u3057\u3067\u5b8c\u4e86)" if scanned < total else "\u5168\u30da\u30fc\u30b8\u5b8c\u4e86!",
    ]
    return {"lines": lines, "ttl_sec": 2, "scanned": scanned, "total": total}


def build_explain_status(*, scanned: int, total: int, status: str) -> dict:
    """Progress banner shown when the client polls session status.

    status values: 'scanning' | 'ready' | 'explaining'
    """
    if status == "scanning":
        remaining = total - scanned
        lines = [
            f"\u8aad\u307f\u53d6\u308a\u4e2d {scanned}/{total}",
            f"\u6b8b\u308a {remaining} \u30da\u30fc\u30b8",
            "\u30c0\u30d6\u30eb\u9577\u62bc\u3057\u3067\u5b8c\u4e86",
        ]
    elif status == "ready":
        lines = [
            f"\u5168 {total} \u30da\u30fc\u30b8 \u6e96\u5099OK",
            "\u30bf\u30c3\u30d7\u3067\u89e3\u8aac\u958b\u59cb",
            "",
        ]
    else:  # explaining
        lines = [
            f"\u89e3\u8aac\u30e2\u30fc\u30c9 ({total}P)",
            "\u30da\u30fc\u30b8\u3092\u6307\u3057\u3066\u30bf\u30c3\u30d7",
            "",
        ]
    return {"lines": lines, "status": status, "scanned": scanned, "total": total}


def build_explain_view(
    *,
    lines: list[str],        # ExplainResult.lines (the explainer's 3-line output)
    detail: str,             # ExplainResult.detail (long-form, for pagination)
    evidence_pages: list[int],
    page_index: int,
    total_pages: int,
    stage: str = "summary",
    view_page: int = 0,
    confidence: float = 1.0,
    voice_enabled: bool = False,
) -> dict:
    """Return one page of the staged, silent-friendly on-glasses explain view.

    stage='summary' : 3-line HUD from ExplainResult.lines
    stage='detail'  : ExplainResult.detail wrapped and paginated
    stage='evidence': list of evidence page numbers

    Navigation:
      - Swipe / tap     : view_page +1  (within current stage)
      - Long-press      : next stage
      - Server returns nav.next/prev so the client knows when pages run out.
    """
    if stage not in EXPLAIN_STAGES:
        stage = "summary"

    page_label = f"P{page_index + 1:02d}/{total_pages:02d}"
    hint = "\u300c\u6b21\u306e\u89e3\u8aac\u300d\u3068\u8a00\u3046" if voice_enabled else "\u30dc\u30bf\u30f3\u3067\u6b21\u3078"

    if stage == "summary":
        # First line always shows page position + confidence symbol
        header = f"{page_label} {_confidence_symbol(confidence)}"
        stage_lines = [header] + (lines or ["(\u7121\u30c6\u30ad\u30b9\u30c8)"]) [:2]
        pages = _paginate(stage_lines)

    elif stage == "detail":
        header = f"{page_label} \u8a73\u7d30"
        detail_lines = [header] + _wrap(detail or "(\u8a73\u7d30\u306a\u3057)")
        pages = _paginate(detail_lines)

    else:  # evidence
        header = f"{page_label} \u6839\u62e0"
        if evidence_pages:
            ev_text = "\u6839\u62e0P: " + ",".join(
                f"P{p + 1:02d}" for p in evidence_pages
            )
        else:
            ev_text = "(\u6839\u62e0\u30da\u30fc\u30b8\u306a\u3057)"
        pages = _paginate([header, ev_text])

    total = len(pages)
    view_page = max(0, min(view_page, total - 1))

    return {
        "stage": stage,
        "page": view_page,
        "total_pages": total,
        "lines": pages[view_page],
        "locked": False,
        "nav": _nav(view_page, total, hint, EXPLAIN_STAGES),
    }


# ---------------------------------------------------------------------------
# Locked view (real-exam guard, unchanged)
# ---------------------------------------------------------------------------

def build_locked_view(stage: str = "answer") -> dict:
    """Real-exam mode (locked): never reveal an answer."""
    return {
        "stage": stage,
        "page": 0,
        "total_pages": 1,
        "lines": ["\u672c\u756a\u8a66\u9a13\u30e2\u30fc\u30c9", "\u89e3\u7b54\u306f\u8868\u793a\u3057\u307e\u305b\u3093", "\u5b66\u7fd2/\u6a21\u8a66\u3067\u4f7f\u7528\u3057\u3066\u304f\u3060\u3055\u3044"],
        "locator": "",
        "locked": True,
        "nav": {"prev": None, "next": None, "stages": list(STAGES)},
    }


# ---------------------------------------------------------------------------
# Exam solver view (unchanged public API)
# ---------------------------------------------------------------------------

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
            "\u6839\u62e0\u30da\u30fc\u30b8: " + ",".join(f"P{p:02d}" for p in solution.evidence_pages)
            if solution.evidence_pages
            else ""
        )
        return ["\u6839\u62e0", solution.rationale or "(\u306a\u3057)"] + ([ev] if ev else [])
    return ["\u6ce8\u610f", solution.cautions or "(\u306a\u3057)"]


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
    hint = "\u300c\u6b21\u306e\u7b54\u3048\u300d\u3068\u8a00\u3046" if voice_enabled else "\u524d\u9762\u30dc\u30bf\u30f3\u3067\u6b21\u3078"

    return {
        "stage": stage,
        "page": page,
        "total_pages": total,
        "lines": pages[page],
        "locator": _locator(answer_box),
        "locked": False,
        "nav": _nav(page, total, hint, STAGES),
    }

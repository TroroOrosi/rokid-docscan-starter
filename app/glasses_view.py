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
"""

from __future__ import annotations

from .solvers import SolveResult

STAGES = ("answer", "solution", "rationale", "caution")

_MAX_LINES = 3
_MAX_LINE_CHARS = 24  # ~Japanese chars that fit one HUD line

# Server-authoritative render contract for the on-glasses display. This governs
# the HUD DISPLAY ONLY (text rendering). The client must honor these when
# drawing: silent, no white flash on update, fade-free instant text replace, no
# large animation, status via static symbols (not blinking), low brightness.
RENDER_CONTRACT = {
    "max_lines": _MAX_LINES,
    "silent": True,          # no shutter / notification / beep sounds
    "white_flash": False,    # the HUD must not flash white when text changes
    "animations": False,     # no large animation
    "transition": "instant", # fade-free instant text replace
    "blinking": False,       # convey state with static symbols (✓ ! ★)
    "brightness": "low",     # default to a low rung of the 10-level dimming
}

# Capture-path contract. IMPORTANT: the camera privacy LED is hardware-enforced
# and MUST stay on whenever the camera is active; the server neither exposes nor
# supports any way to disable it. `privacy_led` is advertised as always_on /
# tamper:forbidden precisely to make that non-negotiable in the contract.
CAPTURE_CONTRACT = {
    "shutter_sound": False,           # silent capture via the custom camera path
    "camera_path": "cxr-s/camera2",   # custom path used for soundless capture
    "privacy_led": {"state": "always_on", "tamper": "forbidden"},
}


def build_capture_ack(
    *, page_number: int | None = None, question_id: int | None = None
) -> dict:
    """A silent, no-flash capture confirmation: one short HUD line, ~2s.

    Replaces an audible shutter / white flash with a quiet on-glass line. Like
    the rest of the HUD payloads it carries NO sound/flash/animation fields.
    """
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
        # No audio / animation fields by design.
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
            # Operation hint adapts to silent (button) vs voice mode.
            "hint": "『次の答え』と言う" if voice_enabled else "前面ボタンで次へ",
        },
    }

"""Build the on-glasses view payload (silent HUD, monochrome, paginated lines).

Hardware reality (Rokid Glasses, web-verified 2026-07; see
docs/cxr-l-integration.md):
  Display : dual-eye (binocular) monochrome-green Micro-LED + diffractive
            waveguide, 480×398 px per eye, FOV ~23° (some reviews cite 30°),
            up to 1 500 nits, adjustable dimming.
  SoC     : Qualcomm Snapdragon AR1 (Gen 1) + NXP RT600 co-processor,
            2 GB RAM / 32 GB ROM.
  Camera  : 12 MP Sony IMX681.  Connectivity: Wi-Fi 6 / Bluetooth 5.3.
  OS      : YodaOS-Sprite (Android 12, API 32).
  SDK     : CXR-L (phone-side plugin SDK: CXRLink(context) binds the Hi Rokid
            app via same-device AIDL and relays HUD text to the glasses over
            the Caps/Bluetooth wire as a CUSTOMVIEW — phone relay required)
            + CXR-S (on-device bridge) + CXR-M (mobile companion).

Design principles (silent HUD; device-controlled capture indicators):
  - HUD payloads contain NO audio cues and NO animation directives.
  - Photography uses CXR-L takePhoto. Shutter sound, flash and firmware capture
    indicators are not controlled or promised by this server contract.
  - Long logical lines are WRAPPED, never truncated, at a column budget
    (MAX_COLUMNS, `ROKID_HUD_MAX_COLUMNS`, full-width glyph = 2 columns).
    Every character survives; a wrapped line simply becomes more lines and
    therefore more view pages.  The earlier 24-char server-side behaviour was
    a truncation ([:24]) that cut problem and answer text off, which is why it
    was removed in contract 1.2.0; this is not that.
    The budget is an ESTIMATE, not a measurement: the CUSTOMVIEW overlay's
    text area has never been measured.  480x640 @240dpi is the glasses'
    logical screen (docs/hardware-measurements.md), and that document states
    the 3-line constraint is a property of the overlay, not of the screen
    size.  18 columns is what 34sp (HudLayout.fromLines) spans across 480 px
    at density 1.5 -- 9 full-width characters.  Set ROKID_HUD_MAX_COLUMNS=0
    to restore unwrapped logical lines.
  - Lines are paginated server-side into slices of <=_MAX_LINES (3) so the
    client always receives a manageable chunk; teleprompter-style scrolling
    lets the user read long explanations line by line.
  - Confidence shown as a static symbol (no blinking).
  - A `locator` text hint to the answer area (no world-locking to paper).

Stages:
  exam mode (secondary): answer -> solution -> rationale -> caution
  explain mode:          overview -> detail -> evidence
  review mode (primary): NO stages — 答え+解法+根拠+注意 merged into one
                         teleprompter stream per problem (一括表示)

Navigation and capture decisions are phone-controlled. CUSTOMVIEW/AI callbacks
are published only as unverified diagnostic mappings and are not operator
actions in the supported relay.
A real page image is captured during the reading phase. After the image
callback and finalize-reading, the application makes no camera request for
answer/problem navigation. Indicator state is a separate physical acceptance
observation and is never inferred from this software state.
"""

from __future__ import annotations

import os
import re
import unicodedata

from .explainer import ExplainResult
from .solvers import SolveResult

# Sentence-ish chunk: run of non-terminator chars plus an optional terminator.
_SENTENCE_RE = re.compile(r"[^。！？!?\n]+[。！？!?]?")

STAGES = ("answer", "solution", "rationale", "caution")
EXPLAIN_STAGES = ("overview", "detail", "evidence")

_MAX_LINES = 3

# Column budget for ONE rendered line.  A full-width glyph costs 2 columns, so
# 18 columns is 9 Japanese characters.  Resolved from the module attribute at
# call time, so a test or an operator can retune it without reimporting.
# 0 disables wrapping and restores one logical line per source line.
MAX_COLUMNS = int(os.environ.get("ROKID_HUD_MAX_COLUMNS", "18"))

# Closing marks that may not open a line.  One of these is allowed to hang
# past the budget (by at most one full-width glyph) rather than start the
# next line alone.
_NO_LINE_START = "、。，．,.!?！？」』）)]｝}：；:;"

# Server-authoritative render contract for the on-glasses display.
# max_columns_per_line is the wrap budget above, NOT a truncation limit, and
# NOT a measured property of the CUSTOMVIEW overlay.  Use render_contract()
# to read it: this dict is frozen at import.
RENDER_CONTRACT = {
    "max_lines": _MAX_LINES,
    "max_columns_per_line": MAX_COLUMNS,
    "column_unit": "full_width_glyph_is_2",
    "wraps": True,
    "truncates": False,
    "silent": True,
    "white_flash": False,
    "animations": False,
    "transition": "instant",
    "blinking": False,
    "brightness": "low",
}

# Capture-path contract for the real-device Android relay. The relay calls
# CXR-L takePhoto and uploads the transport image. Privacy LED, shutter sound,
# flash and capture indicators are hardware/firmware controlled; the application
# never disables or bypasses them and must verify their behavior physically.
CAPTURE_CONTRACT = {
    "mode": "photograph",
    "shutter_sound": "device_controlled",
    "flash": "device_controlled",
    "capture_tone": "device_controlled",
    "camera_path": "cxr-l/takePhoto",
    "audio_record": {"start_tone": False, "stop_tone": False, "silent": True},
    "privacy_led": {"state": "on_while_camera_active", "tamper": "forbidden"},
    "camera_requests_during_review": False,
    "indicator_during_review": "physically_verify_off",
}

# Supported operation mapping. Values describe the authoritative control
# surface, not a gesture hypothesis.
OPERATION_CONTRACT = {
    "capture_read": "phone",
    "finish_reading": "phone",
    "mode_toggle": "phone",
    "record_toggle": "phone",
    "review_next_problem": "phone",
    "review_prev_problem": "phone",
    "scroll_next": "phone",
    "scroll_prev": "phone",
    "close": "phone",
    "exam_next_page": "phone",
    "exam_prev_page": "phone",
    "exam_solve_current": "phone",
    "exam_next_stage": "phone",
    "explain_show": "phone",
    "explain_next_stage": "phone",
    "explain_next_doc_page": "phone",
    "explain_prev_doc_page": "phone",
    "next_view_page": "phone",
    "prev_view_page": "phone",
    "voice_hint": "phone",
}

# Legacy diagnostic map published at GET /v1/settings. It is not an operator
# input contract: the supported workflow routes every action through the phone.
# Names and values are retained only to label device measurements and may not
# represent events delivered by current Global Hi Rokid/CXR-L firmware.
# build_input_contract() applies an optional diagnostic override at call time.
_DEFAULT_GESTURES = {
    "single_tap":             {"keycode": 23,  "keyevent": "KEYCODE_DPAD_CENTER"},
    "double_tap":             {"keycode": 66,  "keyevent": "KEYCODE_ENTER"},
    "long_press":             {"keycode": 170, "keyevent": "KEYCODE_TV"},
    "two_finger_swipe_left":  {"keycode": 21,  "keyevent": "KEYCODE_DPAD_LEFT"},
    "two_finger_swipe_right": {"keycode": 22,  "keyevent": "KEYCODE_DPAD_RIGHT"},
    "two_finger_swipe_up":    {"keycode": 19,  "keyevent": "KEYCODE_DPAD_UP"},
    "two_finger_swipe_down":  {"keycode": 20,  "keyevent": "KEYCODE_DPAD_DOWN"},
    "back":                   {"keycode": 4,   "keyevent": "KEYCODE_BACK"},
    # No standard KeyCode — the AI-activation gesture is handled by the system
    # (launches the onboard AI). Assign a concrete KeyCode via ROKID_KEYMAP if
    # your firmware delivers it as a KeyEvent.
    "two_finger_tap": {"keycode": None, "keyevent": "ai_activation (system gesture)"},
}


def build_input_contract() -> dict:
    """Return the gesture->KeyCode contract, applying any ROKID_KEYMAP override.

    Read at call time so a reloaded config (tests / restart) is reflected.
    """
    from . import config

    gestures = {g: dict(v) for g, v in _DEFAULT_GESTURES.items()}
    overridden = False
    for gesture, keycode in config.KEYMAP.items():
        overridden = True
        if gesture in gestures:
            gestures[gesture]["keycode"] = keycode
        else:
            gestures[gesture] = {"keycode": keycode, "keyevent": None}
    return {
        "operator_actions_enabled": False,
        "role": "diagnostic_only",
        # These legacy values have not been accepted as usable operator input
        # on the current hardware. They are diagnostic labels only.
        "keycodes_verified": False,
        "keycode_source": (
            "legacy Rokid Glass mapping, unverified — measure on device "
            "(docs/device-verification-checklist.md)"
            + (" + ROKID_KEYMAP override" if overridden else "")
        ),
        "overridden": overridden,
        "gestures": gestures,
    }


def build_capture_ack(
    *, page_number: int | None = None, question_id: int | None = None
) -> dict:
    """Short HUD confirmation after a capture callback, with no audio directive."""
    if page_number is not None:
        label = f"P{page_number:02d}"
    elif question_id is not None:
        label = f"#{question_id}"
    else:
        label = ""
    line = f"{label} 読取済み".strip()
    return {"lines": [line][:_MAX_LINES], "ttl_sec": 2}


def build_page_nav_ack(
    *, page_index: int, total_pages: int, direction: str
) -> dict:
    """HUD feedback shown when next-page or prev-page is triggered.

    No camera capture occurred.  Shows current position and a directional hint.
    ttl_sec=1.5 so it clears quickly before the explain view loads.
    """
    arrow = "→" if direction == "next" else "←"
    label = f"{arrow} P{page_index + 1:02d}/{total_pages}"
    at_edge = (
        "最終ページ" if page_index >= total_pages - 1
        else ("先頭ページ" if page_index == 0 else "")
    )
    lines = [label] + ([at_edge] if at_edge else []) + ["解説操作はスマホ"]
    return {
        "lines": lines[:_MAX_LINES],
        "ttl_sec": 1.5,
        "page_index": page_index,
        "total_pages": total_pages,
    }


def _confidence_symbol(conf: float) -> str:
    if conf >= 0.66:
        return "★★★"
    if conf >= 0.33:
        return "★★☆"
    return "★☆☆"


def _evidence_labels(result: SolveResult | ExplainResult) -> list[str]:
    """Human-facing, unambiguous evidence labels.

    Structured cross-document refs win and are always user-facing/1-based.
    Older rows may only carry the legacy bare list. Database readers attach an
    internal ``_evidence_pages_base`` marker after identifying the historical
    write path, so a 0-based page index is shifted for display without mutating
    the opaque API v1 ``evidence_pages`` value. New writes include refs.
    """
    labels: list[str] = []
    for ref in getattr(result, "evidence_refs", []) or []:
        if not isinstance(ref, dict):
            continue
        document_id = ref.get("document_id")
        page_number = ref.get("page_number")
        if isinstance(document_id, int) and isinstance(page_number, int):
            labels.append(f"D{document_id}:P{page_number:02d}")
    if labels:
        return labels
    extras = getattr(result, "extras", {}) or {}
    display_offset = 1 if extras.get("_evidence_pages_base") == 0 else 0
    return [
        f"P{p + display_offset:02d}"
        for p in (result.evidence_pages or [])
        if isinstance(p, int)
    ]


def _locator(answer_box: dict | None) -> str:
    if not answer_box:
        return ""
    cx = answer_box.get("x", 0) + answer_box.get("w", 0) / 2
    cy = answer_box.get("y", 0) + answer_box.get("h", 0) / 2
    vert = "上" if cy < 0.4 else ("下" if cy > 0.6 else "中")
    horiz = "左" if cx < 0.4 else ("右" if cx > 0.6 else "中")
    return f"解答欄: {vert}{horiz}"


def render_contract() -> dict:
    """Return the render contract with the CURRENT column budget resolved."""
    return {**RENDER_CONTRACT, "max_columns_per_line": MAX_COLUMNS}


def _columns(ch: str) -> int:
    """Rendered width of one character, in columns (full-width glyph = 2).

    East Asian Ambiguous counts as 2: the display renders with a Japanese
    font, where the answer marks ①②③④ and ° occupy a full cell.
    """
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F", "A") else 1


def _wrap(text: str) -> list[str]:
    """Split one logical line into lines that fit MAX_COLUMNS columns.

    Wrapping only.  No character is ever dropped: a long line becomes more
    lines, which _paginate then turns into more view pages.  MAX_COLUMNS <= 0
    returns the line unwrapped (the contract 1.2.0 behaviour).
    """
    text = (text or "").strip()
    if not text:
        return []
    budget = MAX_COLUMNS
    if budget <= 0:
        return [text]
    lines: list[str] = []
    line = ""
    used = 0
    for ch in text:
        width = _columns(ch)
        if used + width > budget:
            if line and ch in _NO_LINE_START and used + width <= budget + 2:
                line += ch
                used += width
                continue
            lines.append(line)
            line, used = ch, width
        else:
            line += ch
            used += width
    if line:
        lines.append(line)
    return lines


def _split_sentences(text: str) -> list[str]:
    """Split long prose into sentence-sized logical lines (。！？!? / newlines).

    Each sentence becomes a logical line so _paginate() can chunk long detail /
    rationale text into multiple 3-line teleprompter pages (swipe to read on).
    Short text with no terminator returns as a single line.
    """
    text = (text or "").strip()
    if not text:
        return []
    parts = [p.strip() for p in _SENTENCE_RE.findall(text)]
    return [p for p in parts if p] or [text]


def _paginate(lines: list[str]) -> list[list[str]]:
    """Chunk logical lines into pages of <=_MAX_LINES lines each."""
    flat: list[str] = []
    for ln in lines:
        flat.extend(_wrap(ln) or [""])
    if not flat:
        flat = [""]
    return [flat[i : i + _MAX_LINES] for i in range(0, len(flat), _MAX_LINES)]


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
        # Split any long step into sentence lines so the teleprompter paginates it.
        return ["解法"] + [s2 for s in steps for s2 in (_split_sentences(s) or [s])]
    if stage == "rationale":
        labels = _evidence_labels(solution)
        ev = "根拠ページ: " + ",".join(labels) if labels else ""
        body = _split_sentences(solution.rationale) or ["(なし)"]
        return ["根拠"] + body + ([ev] if ev else [])
    # caution
    return ["注意"] + (_split_sentences(solution.cautions) or ["(なし)"])


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
            "hint": "操作はスマホ",
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
    label = _EXPLAIN_STAGE_LABELS.get(stage, stage)
    if stage == "overview":
        head = f"{page_label} {_confidence_symbol(result.confidence)}".strip()
        return [head] + (result.lines or [])
    if stage == "detail":
        # Split long detail into sentence lines so phone-driven pagination can
        # show multiple 3-line views instead of one long line.
        return [label] + (_split_sentences(result.detail) or ["(詳細なし)"])
    # evidence
    labels = _evidence_labels(result)
    if labels:
        ev = ",".join(labels)
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

    Pagination (phone-controlled teleprompter-style):
      - Each logical line is passed through _wrap() unchanged.
      - Lines are chunked into slices of _MAX_LINES (3) view pages.

    Stage navigation (the phone advances and wraps at evidence->overview):
      overview -> detail -> evidence -> (wrap) -> overview

    Page navigation is performed with phone controls and requests no camera.
    """
    if stage not in EXPLAIN_STAGES:
        stage = "overview"

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

    stage_idx = EXPLAIN_STAGES.index(stage)
    prev_stage = EXPLAIN_STAGES[stage_idx - 1] if stage_idx > 0 else None
    next_stage = (
        EXPLAIN_STAGES[stage_idx + 1] if stage_idx < len(EXPLAIN_STAGES) - 1
        else EXPLAIN_STAGES[0]  # wrap around to overview
    )

    hint = "操作はスマホ"

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
            "operations": {
                "next_view_page": "phone",
                "prev_view_page": "phone",
                "next_stage": "phone",
                "next_doc_page": "phone",
                "prev_doc_page": "phone",
            },
            "hint": hint,
        },
    }


# ---------------------------------------------------------------------------
# Review-deck view builder (phase 3: the application requests no camera image)
# ---------------------------------------------------------------------------


def _review_lines(solution: SolveResult, header: str) -> list[str]:
    """One merged line stream: 答え → 解法 → 根拠 → 注意 (no stages).

    Unlike the staged _stage_lines, empty sections are omitted entirely (no
    "(なし)" filler) so the teleprompter stream stays short.
    """
    lines = [header, f"答え: {solution.answer}"]
    steps = [
        s2 for s in (solution.solution_steps or []) for s2 in (_split_sentences(s) or [s])
    ]
    if steps:
        lines += ["解法"] + steps
    rationale = _split_sentences(solution.rationale)
    labels = _evidence_labels(solution)
    ev = "根拠ページ: " + ",".join(labels) if labels else ""
    if rationale or ev:
        lines += ["根拠"] + rationale + ([ev] if ev else [])
    cautions = _split_sentences(solution.cautions)
    if cautions:
        lines += ["注意"] + cautions
    return lines


# Phone bindings for the reading phase (subset of OPERATION_CONTRACT).
# Returned by finalize-reading when a 0-problem outcome reverts the session to
# the reading phase: the client must keep showing re-scan controls — with the
# review bindings when the user needs reading controls again after re-scanning.
READING_OPERATIONS = {
    key: OPERATION_CONTRACT[key]
    for key in ("capture_read", "finish_reading", "mode_toggle")
}

# Phone bindings for the review phase (subset of OPERATION_CONTRACT). The
# single source used both inside every review view (nav.operations) and by the
# endpoint envelopes (main._review_operations), so a client sees one set.
REVIEW_OPERATIONS = {
    "next_problem": "phone",
    "prev_problem": "phone",
    "scroll_next": "phone",
    "scroll_prev": "phone",
    "close": "phone",
    "mode_toggle": "phone",
}


def build_review_view(
    solution: SolveResult | None,
    *,
    index: int,
    problem_count: int,
    problem_no: str | None = None,
    page_number: int | None = None,
    view_page: int = 0,
    solved: bool = True,
    voice_enabled: bool = False,
) -> dict:
    """Return one teleprompter page of the per-problem review view.

    Phase 3 閲覧: the paper is no longer needed and no camera request is made.
    Answer, solution steps, rationale and cautions are merged into ONE stream
    and chunked into <=3-line pages. The user scrolls and moves between
    problems with the phone controls. An unsolved problem renders a placeholder
    so the deck remains navigable while answers are ingested.
    """
    position = f"{index + 1}/{problem_count}"
    label = problem_no or f"#{index + 1}"
    if solution is not None and solved:
        header = f"{label} {position} {_confidence_symbol(solution.answer_confidence)}"
        lines = _review_lines(solution, header)
    else:
        header = f"{label} {position}"
        lines = [header, "未解答", "本体AIの解答待ち"]

    pages = _paginate(lines)
    total = len(pages)
    vp = max(0, min(view_page, total - 1))

    return {
        "kind": "review",
        "index": index,
        "problem_count": problem_count,
        "problem_no": problem_no,
        "page_number": page_number,
        "view_page": vp,
        "total_view_pages": total,
        "lines": pages[vp],
        "solved": bool(solved and solution is not None),
        "locked": False,
        "nav": {
            "prev_problem": index - 1 if index > 0 else None,
            "next_problem": index + 1 if index < problem_count - 1 else None,
            "prev_view_page": vp - 1 if vp > 0 else None,
            "next_view_page": vp + 1 if vp < total - 1 else None,
            "operations": dict(REVIEW_OPERATIONS),
            "hint": "操作はスマホ",
        },
    }


def build_reading_done_ack(problem_count: int, total_pages: int) -> dict:
    """HUD ack for finalize-reading: reading is over; no camera request follows.

    A 0-problem outcome (e.g. every page was figure-only with no recognized
    text) gets explicit guidance instead of dropping the user into an empty
    review deck with no explanation.
    """
    if problem_count == 0:
        lines = [
            f"読取完了 {total_pages}ページ",
            "問題を検出できません",
            "再読取してください",
        ]
    else:
        lines = [
            f"読取完了 {total_pages}ページ",
            f"{problem_count}問を検出",
            "撮影終了 解答へ",
        ]
    return {
        "lines": lines[:_MAX_LINES],
        "ttl_sec": 2,
        "problem_count": problem_count,
        "total_pages": total_pages,
        "camera_off": True,
    }


def build_scan_ack(
    page_index: int,
    scanned_count: int,
    total_pages: int | None,
) -> dict:
    """Scan progress / completion HUD shown after each page capture.

    Called from POST /v1/documents/{id}/pages (add_page) so the user gets
    real-time feedback.  When the expected total is known and reached, the
    hint changes to a phone-control completion message. Finishing calls
    POST /v1/exam-sessions/{id}/finalize-reading; indicator state remains a
    separate physical observation.

    ``total_pages=None`` = the client never declared an expected count: the
    ack must NOT claim completion (previously it asserted all_scanned after
    the very first page), so it reports plain progress with a neutral hint.
    """
    label = f"P{page_index + 1:02d} 読取済 ✓"
    if total_pages is None:
        return {
            "lines": [label, f"{scanned_count}ページ読取済", "次ページ / 完了はスマホ"],
            "ttl_sec": 2,
            "scanned_count": scanned_count,
            "total_pages": None,
            "all_scanned": False,
        }
    progress = f"{scanned_count}/{total_pages}ページ完了"
    hint = "完了はスマホ" if scanned_count >= total_pages else "次ページへ"
    return {
        "lines": [label, progress, hint],
        "ttl_sec": 2,
        "scanned_count": scanned_count,
        "total_pages": total_pages,
        "all_scanned": scanned_count >= total_pages,
    }

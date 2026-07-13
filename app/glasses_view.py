"""Build the on-glasses view payload (silent, monochrome, paginated lines).

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

Design principles (SILENT-FRIENDLY, no-flash):
  - NO audio cues and NO animation directives.
  - NO character-per-line limit imposed by the server.  The client renderer
    is responsible for reflowing text to fit the physical display.
    (Previous 24-char server-side truncation caused problem text and answer
    text to be cut off and was therefore removed.)
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

Navigation is always touch-gesture based — voice is opt-in only.
Official Rokid Glasses gesture vocabulary (current model; see
docs/glasses-ux-contract.md):
  two_finger_tap              : AI activation → page 視認 (reading phase only)
  single_tap                  : click / show / next stage (secondary flows)
  double_tap                  : exit — phase-modal: reading=finish_reading,
                                review=close
  two_finger_swipe_up/down    : teleprompter scroll (within a view)
  two_finger_swipe_left/right : prev/next document page or review problem
  long_press                  : video⇄audio record toggle → written⇄listening
No camera image is used for page/problem navigation: after finalize-reading
the camera stays closed, so the privacy LED is dark for the whole answer and
review phases (LED lit time is minimized by design).
"""

from __future__ import annotations

import re

from .explainer import ExplainResult
from .solvers import SolveResult

# Sentence-ish chunk: run of non-terminator chars plus an optional terminator.
_SENTENCE_RE = re.compile(r"[^。！？!?\n]+[。！？!?]?")

STAGES = ("answer", "solution", "rationale", "caution")
EXPLAIN_STAGES = ("overview", "detail", "evidence")

_MAX_LINES = 3

# Server-authoritative render contract for the on-glasses display.
# NOTE: No max_chars_per_line is specified here — character-level reflow is
# the client's responsibility.  The server only controls page chunking.
RENDER_CONTRACT = {
    "max_lines": _MAX_LINES,
    "silent": True,
    "white_flash": False,
    "animations": False,
    "transition": "instant",
    "blinking": False,
    "brightness": "low",
}

# Capture-path contract. 撮影しない (no photography): the on-glass AI recognizes
# the page and sends its reading as TEXT — no photo is taken, so there is no
# flash and no shutter. Listening records audio via the microphone, silently.
# privacy_led is hardware-enforced (steady recording indicator, not a flash) and
# is never server-controllable; it lights whenever the camera is active — i.e.
# 視認＝認識＝カメラON＝LED点灯. The 3-phase flow therefore keeps the reading
# phase short; after finalize-reading the camera is closed, so the LED is dark
# for the whole answer and review phases (led_off_during_review).
CAPTURE_CONTRACT = {
    "shutter_sound": False,
    "flash": "off",                # no photographic flash/torch on capture
    "capture_tone": False,         # silent capture (reinforces shutter_sound)
    "camera_path": "cxr-s/camera2",
    # Listening recording is silent: no start/stop tones (microphone, not camera).
    "audio_record": {"start_tone": False, "stop_tone": False, "silent": True},
    "privacy_led": {"state": "on_while_camera_active", "tamper": "forbidden"},
    # Review/answer phases run with the camera closed → LED off (点灯時間最小化).
    "led_off_during_review": True,
}

# Operation mapping for the glasses-only 3-phase exam flow (and the secondary
# flows), using the CURRENT Rokid Glasses official gesture vocabulary:
# two-finger tap = AI activation / single tap = click / double tap = exit /
# two-finger swipe up・down = scroll, left・right = prev/next page /
# long press = video⇄audio record toggle. Every operation below is doable on
# the glasses alone (the phone, if present, is a silent HTTP relay). Gestures
# resolve to KeyCodes via GET /v1/settings.input (overridable with ROKID_KEYMAP).
#
# Design notes (pending on-device UX validation):
#   - Three REQUIRED calls have no gesture of their own: document creation
#     (POST /v1/documents), the all-pages declaration (POST /v1/documents/
#     {id}/finalize) and exam-session creation (POST /v1/exam-sessions).
#     They are the RELAY APP's auto-chain duty — the first two_finger_tap of
#     a reading session creates the document, and finish_reading (double_tap)
#     fires finalize → session create → finalize-reading as one chain (see
#     docs/cxr-l-integration.md §5). The user's input is gestures only;
#     "glasses-only operation" holds through that relay duty, which is why
#     these calls are deliberately absent from OPERATION_CONTRACT.
#   - finish_reading = double_tap reuses the official "exit" gesture and is
#     phase-modal: during reading it declares 読取完了 (finalize-reading);
#     during review it closes the deck. 読取フェーズの終了＝カメラOFF＝LED消灯.
#   - mode_toggle/record_toggle share long_press (the official video⇄audio
#     record toggle) and are phase-modal: written → switch to listening;
#     listening → start/stop the silent recording.
#   - Swipe direction keeps the existing left=next (page-flip) convention;
#     clients may mirror it per user preference.
OPERATION_CONTRACT = {
    # --- Phase 1 読取 (camera ON → privacy LED lit; keep this phase short) ---
    "capture_read": "two_finger_tap",             # AI起動=視認 → POST /documents/{id}/pages
    "finish_reading": "double_tap",               # → POST /exam-sessions/{id}/finalize-reading
    # --- Phase 2 解答 (camera OFF): onboard GPT solves → POST /solutions ---
    "mode_toggle": "long_press",                  # 筆記⇄リスニング → POST /exam-sessions/{id}/mode
    "record_toggle": "long_press",                # listening中: 録音開始/停止 (phase-modal)
    # --- Phase 3 閲覧 (camera OFF, LED off): per-problem review deck ---
    "review_next_problem": "two_finger_swipe_left",   # → GET /review?index=k+1
    "review_prev_problem": "two_finger_swipe_right",  # → GET /review?index=k-1
    "scroll_next": "two_finger_swipe_down",       # teleprompter 送り (view_page+1)
    "scroll_prev": "two_finger_swipe_up",         # teleprompter 戻し (view_page-1)
    "close": "double_tap",                        # exit review
    # --- Secondary/compat: solve-current型 page-move exam ---
    "exam_next_page": "two_finger_swipe_left",    # → POST /exam-sessions/{id}/next-page
    "exam_prev_page": "two_finger_swipe_right",   # → POST /exam-sessions/{id}/prev-page
    "exam_solve_current": "single_tap",           # → POST /exam-sessions/{id}/solve-current
    "exam_next_stage": "single_tap",              # while a solution is shown: next stage
    # --- Secondary/compat: explain-sessions ---
    "explain_show": "single_tap",
    "explain_next_stage": "single_tap",           # while an explanation is shown
    "explain_next_doc_page": "two_finger_swipe_left",   # → POST /explain-sessions/{id}/next-page
    "explain_prev_doc_page": "two_finger_swipe_right",  # → POST /explain-sessions/{id}/prev-page
    # Teleprompter scroll within a staged view (secondary flows)
    "next_view_page": "two_finger_swipe_down",
    "prev_view_page": "two_finger_swipe_up",
    "voice_hint": None,
}

# On-glasses input contract: gesture -> Android KeyCode. Published at
# GET /v1/settings so the CXR-L client has a single authoritative source for
# which KeyEvent to listen for. Gesture NAMES are the current official Rokid
# Glasses vocabulary; the KeyCode VALUES are carried over from the legacy
# monocular Rokid Glass table and are UNVERIFIED on the current hardware
# (keycodes_verified: false — measure with `adb shell getevent -l`, see
# docs/real-device-operation.md §5). A device/firmware difference is absorbed
# via ROKID_KEYMAP (see app/config.py) without any client change.
# build_input_contract() applies the override at call time.
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
        # Honest flag: the KeyCode values come from the LEGACY monocular
        # Rokid Glass table and have NOT been measured on the current
        # binocular Rokid Glasses. Treat them as a starting hypothesis.
        "keycodes_verified": False,
        "keycode_source": (
            "legacy Rokid Glass mapping, unverified — measure on device "
            "(docs/real-device-operation.md §5)"
            + (" + ROKID_KEYMAP override" if overridden else "")
        ),
        "overridden": overridden,
        "gestures": gestures,
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
    lines = [label] + ([at_edge] if at_edge else []) + ["タップで解説"]
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


def _locator(answer_box: dict | None) -> str:
    if not answer_box:
        return ""
    cx = answer_box.get("x", 0) + answer_box.get("w", 0) / 2
    cy = answer_box.get("y", 0) + answer_box.get("h", 0) / 2
    vert = "上" if cy < 0.4 else ("下" if cy > 0.6 else "中")
    horiz = "左" if cx < 0.4 else ("右" if cx > 0.6 else "中")
    return f"解答欄: {vert}{horiz}"


def _wrap(text: str) -> list[str]:
    """Return the logical line as-is (no character-based splitting).

    Character-level reflow is the client renderer's responsibility.
    The server's role is only page-level chunking (_paginate).
    """
    text = (text or "").strip()
    if not text:
        return []
    return [text]


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
        ev = (
            "根拠ページ: " + ",".join(f"P{p:02d}" for p in solution.evidence_pages)
            if solution.evidence_pages
            else ""
        )
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
            "hint": "『次の答え』と言う" if voice_enabled else "縦スワイプで次へ",
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
        # Split long detail into sentence lines so it paginates into multiple
        # 3-line teleprompter pages (two_finger_swipe_down/up) instead of one long line.
        return [label] + (_split_sentences(result.detail) or ["(詳細なし)"])
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
      - Each logical line is passed through _wrap() unchanged.
      - Lines are chunked into slices of _MAX_LINES (3) view pages.
      - Client scrolls with two_finger_swipe_down (next) / _up (prev).

    Stage navigation (single_tap cycles forward; wraps at evidence->overview):
      overview -> detail -> evidence -> (wrap) -> overview

    Page navigation (no camera):
      two_finger_swipe_left  → POST /next-page
      two_finger_swipe_right → POST /prev-page
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

    if total_view_pages > 1:
        hint = "縦スワイプ 送り / タップ 次段階"
    else:
        hint = "タップ 次段階 / 横スワイプ 次ページ"

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
                "next_view_page": "two_finger_swipe_down",
                "prev_view_page": "two_finger_swipe_up",
                "next_stage": "single_tap",
                "next_doc_page": "two_finger_swipe_left",
                "prev_doc_page": "two_finger_swipe_right",
            },
            "hint": hint,
        },
    }


# ---------------------------------------------------------------------------
# Review-deck view builder (3-phase exam flow, phase 3 閲覧: camera OFF, LED off)
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
    ev = (
        "根拠ページ: " + ",".join(f"P{p:02d}" for p in solution.evidence_pages)
        if solution.evidence_pages
        else ""
    )
    if rationale or ev:
        lines += ["根拠"] + rationale + ([ev] if ev else [])
    cautions = _split_sentences(solution.cautions)
    if cautions:
        lines += ["注意"] + cautions
    return lines


# Gesture bindings for the reading phase (subset of OPERATION_CONTRACT).
# Returned by finalize-reading when a 0-problem outcome reverts the session to
# the reading phase: the client must keep showing re-scan controls — with the
# review bindings, double_tap would read as "close" exactly when the user
# needs it to mean "finish_reading" again after re-scanning.
READING_OPERATIONS = {
    key: OPERATION_CONTRACT[key]
    for key in ("capture_read", "finish_reading", "mode_toggle")
}

# Gesture bindings for the review phase (subset of OPERATION_CONTRACT). The
# single source used both inside every review view (nav.operations) and by the
# endpoint envelopes (main._review_operations), so a client sees one set.
REVIEW_OPERATIONS = {
    "next_problem": "two_finger_swipe_left",
    "prev_problem": "two_finger_swipe_right",
    "scroll_next": "two_finger_swipe_down",
    "scroll_prev": "two_finger_swipe_up",
    "close": "double_tap",
    "mode_toggle": "long_press",
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

    Phase 3 閲覧: the paper and the camera are no longer needed (LED off).
    Answer, solution steps, rationale and cautions are merged into ONE stream
    (確定事項: 一括表示) and chunked into <=3-line pages; the user scrolls with
    two-finger vertical swipes and moves between problems with two-finger
    horizontal swipes.  An unsolved problem renders a placeholder so the deck
    is fully navigable before/while the onboard AI's answers are ingested.
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
            "hint": (
                "『次の問題』と言う"
                if voice_enabled
                else "横スワイプ 前後の問 / 縦スワイプ 送り"
            ),
        },
    }


def build_reading_done_ack(problem_count: int, total_pages: int) -> dict:
    """HUD ack for finalize-reading: reading phase over, camera off, LED off.

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
            "カメラOFF 解答へ",
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
    hint changes to the completion message so the user knows to double-tap
    (finish_reading → POST /v1/exam-sessions/{id}/finalize-reading, which
    closes the camera and turns the privacy LED off).

    ``total_pages=None`` = the client never declared an expected count: the
    ack must NOT claim completion (previously it asserted all_scanned after
    the very first page), so it reports plain progress with a neutral hint.
    """
    label = f"P{page_index + 1:02d} 読取済 ✓"
    if total_pages is None:
        return {
            "lines": [label, f"{scanned_count}ページ読取済", "次ページ / 完了はダブルタップ"],
            "ttl_sec": 2,
            "scanned_count": scanned_count,
            "total_pages": None,
            "all_scanned": False,
        }
    progress = f"{scanned_count}/{total_pages}ページ完了"
    hint = "完了: ダブルタップ" if scanned_count >= total_pages else "次ページへ"
    return {
        "lines": [label, progress, hint],
        "ttl_sec": 2,
        "scanned_count": scanned_count,
        "total_pages": total_pages,
        "all_scanned": scanned_count >= total_pages,
    }

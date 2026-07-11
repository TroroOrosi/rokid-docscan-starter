"""Central version & contract identifiers.

Every externally observable contract gets its own version string so clients
(Android / iOS / Rokid / Android XR) can negotiate behavior and so we can
evolve one contract without silently breaking another.

Bump rules (semantic-ish):
- API_VERSION:          the URL/JSON envelope shape of the HTTP API.
- MATCHER_VERSION:      pHash/OCR-MD5 scoring algorithm & thresholds.
- HUD_CONTRACT_VERSION: the on-glass HUD payload shape (line count, fields).
- ANALYZER_API_VERSION: the analyzer plugin interface (app/analyzers/base.py).
- EXPLAINER_API_VERSION: the explainer plugin interface (app/explainer.py).

Clients should treat an unknown *major* bump as "ask the user to update".
"""

from __future__ import annotations

# 0.4.0: real Anthropic Claude adapters shipped for every provider port
#        (analyzer/solver/explainer/extractor). Offline local placeholders
#        remain the default; the cloud path is opt-in via ROKID_*=claude +
#        ANTHROPIC_API_KEY. The HTTP envelope (API_VERSION) is unchanged;
#        /v1/version now additionally lists the "claude" adapters.
# 0.5.0: multi-vendor adapters (claude/openai/gemini) for every port;
#        /v1/settings now publishes an `input` KeyCode contract (overridable via
#        ROKID_KEYMAP); optional bearer auth (ROKID_API_KEY). API_VERSION stays
#        1.6.0 (envelope unchanged; /v1/settings gains an additive block).
# 0.6.0: exam realism — subject detection expanded to the full 共通テスト-aligned
#        subject set (app/subjects.py), and the solver answers from the scanned
#        PAGE IMAGE (vision) with subject-tailored prompts. SOLVER_API_VERSION
#        -> 1.1.0 (Question gained the optional image_path field). API_VERSION
#        stays 1.6.0 (solve response shape unchanged).
# 0.7.0: camera-free operation — pages can be recorded from text alone (image
#        optional on /pages); new document page-move型 exam (/exam-sessions bound
#        to a document with next-page/prev-page/current/solve-current); English
#        listening records audio on the spot (/audio + ROKID_TRANSCRIBER) and
#        筆記⇄リスニング switches via /mode; long detail/rationale now paginates
#        by sentence (GLASSES_VIEW_CONTRACT -> 1.3.0). API_VERSION -> 1.7.0
#        (additive endpoints).
#        Later 0.7.0 additions (all additive, API/contract versions unchanged):
#        pages.vision_text (on-glass AI's figure/image reading as TEXT, 撮影しない);
#        solve-current now passes the WHOLE document (every remembered page) as
#        context so page-spanning problems are read accurately; capture contract
#        publishes flash:off / capture_tone:false / silent audio_record.
# 0.8.0: 3-phase exam flow (読取→一括解答→閲覧), designed to minimize the time
#        the camera is on (= privacy LED lit): finalize-reading segments the
#        whole document into problems and closes the camera; the onboard GPT's
#        per-problem answers are ingested via POST /solutions (primary path;
#        ROKID_SOLVER=openai|gemini|claude adds an optional server solve-all);
#        GET /solutions + /review serve a per-problem deck with 答え+解法+根拠+
#        注意 merged in one teleprompter stream. Operation contract moved to
#        the current official gesture vocabulary; keycodes_verified is now
#        honestly false (legacy table, unmeasured); privacy_led corrected to
#        on_while_camera_active + led_off_during_review. API -> 1.8.0,
#        GLASSES_VIEW_CONTRACT -> 1.4.0.
# 0.9.0: reading-phase recovery + honest-lock consistency + GPT-first code.
#        再読取: POST /pages now REPLACES an existing page_index (response
#        gains `replaced`; frozen once a bound session finished reading), and
#        a 0-problem finalize-reading reverts to the reading phase (response
#        status "reading") so re-scan + finalize again actually recovers.
#        GET /v1/exam-sessions/{id} now honors the mode=real lock (masked
#        solved signals + additive `locked`). Onboard ingest guardrails:
#        ambiguous problem_no (問1 vs 問1/問1(2)) is an actionable 400, and a
#        single-item payload maps onto a single-problem deck (全体) instead of
#        appending a duplicate. Document finalize is idempotent per page; the
#        finalize-reading solve-all closes its check-then-insert race; explain
#        history dedupes same-page rereads; bearer auth compares in constant
#        time. GPT-first alignment: openai/gemini gained DEFAULT_MODELS
#        (key-only setup works for all providers), the multi-provider adapters
#        moved to app/*/llm_adapter.py (claude.py stays as an import shim),
#        and the four registries share one ProviderRegistry. API -> 1.9.0.
APP_VERSION = "0.9.0"

# HTTP API envelope. Path prefix stays "/v1" until a breaking envelope change.
# 1.2.0: /match responses gained the additive `ocr_similarity` field.
# 1.3.0: added exam-solving endpoints (/v1/exam-sessions, /v1/settings).
# 1.4.0: /v1/settings advertises the full render+capture contract (white_flash,
#        transition, brightness, capture.shutter_sound, capture.privacy_led) and
#        add_question returns a silent `capture_ack`.
# 1.5.0: add_question returns extracted `media`; solve returns `evidence` and
#        `served_by`; new .../reasoning endpoint; overlay gains tracking metadata.
# 1.6.0: added /v1/explain-sessions — live multi-page document explanation with
#        per-page RAG context. /v1/version now includes `explainers` list.
# 1.7.0: document page-move型 exam endpoints (/v1/exam-sessions/{id}/next-page,
#        prev-page, current, solve-current, mode, audio); /pages accepts
#        camera-free text pages (image optional). Additive — no envelope change.
# 1.8.0: 3-phase exam endpoints (POST .../finalize-reading, POST+GET
#        .../solutions, GET .../review) — additive. /v1/settings corrections:
#        operations use the official gesture vocabulary, input reports
#        keycodes_verified:false + keycode_source (the old true was wrong),
#        capture reports privacy_led.state=on_while_camera_active and
#        led_off_during_review. Session responses gain phase/problem counts.
# 1.9.0: reading-phase recovery + lock consistency (behavioral, in-envelope):
#        /pages upserts an existing page_index (409 only once a bound session
#        is reviewing, or for NEW indexes after finalize) and returns
#        `replaced`; finalize-reading may return status "reading" when 0
#        problems were segmented (session stays recoverable); session GET
#        gains `locked` and masks solved fields when locked; ingest returns
#        400 for ambiguous problem_no and maps single-item payloads onto a
#        single-problem deck. Path shapes unchanged — no envelope change.
API_VERSION = "1.9.0"

# Matching algorithm identity. Bump when thresholds or hashing change so a
# re-index/eval is triggered. Mirrors thresholds in app/matching.py.
# 1.1.0: OCR signal is now graded text similarity, not exact MD5 only.
MATCHER_VERSION = "1.1.0"

# HUD payload shape: {verdict, confidence, lines:[3]}.
HUD_CONTRACT_VERSION = "1.0.0"

# Analyzer plugin interface (provider-agnostic OCR/summary/embedding).
ANALYZER_API_VERSION = "1.0.0"

# Solver plugin interface (provider-agnostic question answering).
# 1.1.0: Question gained the optional `image_path` field so vision-capable
#        solvers can answer from the scanned page image (additive/back-compat).
SOLVER_API_VERSION = "1.1.0"

# Media-extractor plugin interface (formula/figure/graph/table).
EXTRACTOR_API_VERSION = "1.0.0"

# Explainer plugin interface (live page explanation with RAG context).
EXPLAINER_API_VERSION = "1.0.0"

# On-glasses staged view payload (silent, <=3 lines per page, paginated stages).
# 1.1.0: added the silent `capture_ack` payload (no sound/flash on capture).
# 1.2.0: removed server-side character-per-line truncation (was [:24]).
#        Client renderer is now solely responsible for text reflow.
#        _wrap() returns each logical line as-is; pagination is line-count only.
# 1.3.0: long detail/rationale/solution/caution prose is split into sentence
#        logical lines (。！？!?), so it paginates into multiple 3-line
#        teleprompter view pages instead of one over-long line. Max 3 lines/page
#        is unchanged; this only affects how many view pages long text produces.
# 1.4.0: review-deck view (kind:"review") — 答え+解法+根拠+注意 merged into ONE
#        teleprompter stream per problem (一括表示, no stages) with deck
#        navigation; reading_done ack (camera_off). Operation/gesture names
#        moved to the official vocabulary (two_finger_*, single/double tap,
#        long_press). Max 3 lines/page unchanged.
GLASSES_VIEW_CONTRACT_VERSION = "1.4.0"

# Answer-area overlay payload (box + short answer; 2D image-anchored).
# 1.1.0: added tracking metadata (tracking/fixed_ar/anchor_hint).
OVERLAY_CONTRACT_VERSION = "1.1.0"


def version_info() -> dict:
    """Machine-readable version block embedded in API responses."""
    return {
        "app_version": APP_VERSION,
        "api_version": API_VERSION,
        "matcher_version": MATCHER_VERSION,
        "hud_contract_version": HUD_CONTRACT_VERSION,
        "analyzer_api_version": ANALYZER_API_VERSION,
        "solver_api_version": SOLVER_API_VERSION,
        "extractor_api_version": EXTRACTOR_API_VERSION,
        "explainer_api_version": EXPLAINER_API_VERSION,
        "glasses_view_contract_version": GLASSES_VIEW_CONTRACT_VERSION,
        "overlay_contract_version": OVERLAY_CONTRACT_VERSION,
    }

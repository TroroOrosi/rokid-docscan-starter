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
# 0.10.0: text-first consistency — カメラに映った資料は撮影せずその場で認識
#        (視認=認識) が全経路で成立。/v1/match と /questions は認識テキストを
#        主入力とし、image は互換の任意入力（非推奨）へ降格。照合は pHash の
#        無い側があればテキスト専用モードでスコア（MATCHER -> 1.2.0）。新設
#        GET /v1/documents/{id}/scan-status が読取状態と欠番を報告し中断復帰を
#        支援（画像/pHash 語彙なし）。復旧文言は 再撮影→再読取、取り込み ack は
#        保存済み→読取済み（payload 形状不変のため GLASSES_VIEW は 1.4.0 の
#        まま）。API -> 1.10.0.
# 0.11.0: review hardening — reject sparse page indexes before finalize or
#        navigation, claim solve/explain work before optional paid calls, and
#        cache one explainer result per page visit. Canonical evidence_refs are
#        document-qualified/1-based while legacy evidence_pages semantics stay
#        compatible. Explain history returns stored detail/provider context.
#        Docker defaults to loopback and passes `.env` settings explicitly. The
#        matching evaluator uses perturbed image queries instead of exact pHash
#        self-matches. API -> 1.11.0, solver -> 1.2.0, explainer -> 1.1.0,
#        glasses view -> 1.5.0.
# 0.12.0: real-device Android relay for Global Hi Rokid. Photography is the
#        primary input; cloud analyzers can transcribe the saved image and the
#        resulting text is persisted before segmentation. scan-status reports
#        has_image, and deck solvers receive the originating page image.
#        API -> 1.12.0, glasses view -> 1.6.0.
# 0.13.0: review and media integrity hardening. Page replacement is frozen
#        atomically once review begins, decoded images are bounded to 25 MP,
#        audio persistence/provider metadata share one canonical registry, and
#        the Android relay keeps unknown captures blocked across timeout/IPC
#        failures while rejecting stale callbacks after reconnect.
#        API -> 1.13.0, glasses view -> 1.7.0.
# 0.13.1: review follow-ups. A glasses status change no longer releases an
#        unresolved capture without a new CXR-L callback epoch, Pillow
#        decompression bombs map to 413, and raw AAC is never sent to OpenAI's
#        documented transcription endpoint.
#        API -> 1.13.1, glasses view -> 1.7.1.
# 0.14.0: real-device capture review. Photos remain unregistered until an
#        explicit decision, the glasses show a post-capture preview, short press
#        safely retakes, and long press confirms. Pending captures survive app
#        restarts; CXR-L photography uses its 1920x1080/80 defaults.
#        API unchanged, glasses view -> 1.8.0.
# 0.15.0: real-device capture instrumentation. takePhoto dimensions and JPEG
#        quality became operator-adjustable at runtime so the usable capture
#        size can be measured on the device, the delivered JPEG size is now
#        reported against the async Binder budget, the CXR-L service version is
#        recorded on connect, and OCR results carry a mean symbol confidence.
#        Relay-only; API and glasses view unchanged.
# 0.18.0: manual chat-UI route. The current page can be exported as pasteable
#        answer-only prompt text and a prefilled chatgpt.com link, so a phone
#        browser can answer a page without a configured cloud solver. No answer
#        returns to the session, so this drives no HUD. API -> 1.17.0.
# 0.19.0: ROKID_SOLVER=chatgpt-web — a subscription-only GPT route that needs no
#        API key. The server drives the operator's already-signed-in ChatGPT web
#        session over a Chrome debugging port, so the whole capture -> OCR ->
#        answer -> HUD path runs without hand work on the phone.
#        Solver -> 1.4.0; API unchanged.
# 0.20.0: the chatgpt-web route uploads the page image as its own message part
#        alongside the OCR text, so figures, graphs and equations reach the
#        model instead of surviving only as OCR. Upload confirmation is carried
#        on the result as extras["image_attached"]. API/glasses view unchanged.
# 0.21.0: chatgpt-web hardened against three things measured on the live page
#        (Chrome 152): the composer is waited for instead of assumed, because a
#        signed-out chatgpt.com serves a placeholder shell without one; upload
#        confirmation needs the thumbnail count to RISE, because the selector
#        already matched once on an empty composer; and reply polling went from
#        1.0s x 3 to 0.25s x 4, cutting a fixed 3s per question to 1s. Attaching
#        the browser costs 0.61s measured, so it is not pooled.
# 0.22.0: chatgpt-web verified end to end on the signed-in page. Two defects the
#        stub tests could not see are fixed: `input[type="file"]` matched FIVE
#        inputs and Playwright refused it as a strict mode violation, failing
#        every upload, so the photo input is now addressed by testid; and the
#        streaming stop button now ends the wait, which measured a second faster
#        than text-stability. Measured per question: 7.6s text, 9.0s with image.
# 0.23.0: a 大問 that spans pages now reaches chatgpt-web with EVERY one of its
#        page images, not just the starting page. Measured on the live page: a
#        two-page problem whose conditions and figure are on different pages
#        returned needs_input with one image and the correct answer with both.
#        Solver -> 1.5.0; API unchanged.
# 0.24.0: chatgpt-web no longer ends its wait on a reasoning model's "思考中"
#        placeholder (4 of 5 long prompts returned it as the answer), and each
#        question is retried in a fresh chat, an unconfirmed image upload
#        included. Measured: composer.fill carries 34,205 characters intact.
# 0.25.0: chatgpt-web stops spending generations it does not need. The retry
#        for an unconfirmed upload now happens BEFORE the question is sent, so
#        a moved thumbnail selector costs uploads instead of three answers per
#        question; a reply that is a usage-limit notice ends the question
#        instead of being retried in yet another new chat; and two generations
#        in a row slower than ROKID_CHATGPT_SLOW_S (40s, measured throttle
#        signal: 7-13s clean, degraded to 43/48/130s before the 2026-09-14
#        block) refuse the next send. ROKID_CHATGPT_BUNDLE_PDF=1 sends the 大問
#        as one PDF through the file input instead of one image per page;
#        off by default and UNVERIFIED against the live page.
# 0.26.0: chatgpt-web can share ONE chat per 科目 (ROKID_CHATGPT_CHAT_SCOPE=
#        subject): a deck opens one chat per subject instead of one per 小問,
#        and a page already attached in that chat is not uploaded again. A
#        listening session now sends the recording itself alongside the pages
#        (Question.audio_path -> the general file input; the photo input is
#        image-only), so intonation, speaker turns and numbers no longer have
#        to survive the transcript.
# 0.27.0: the HUD wraps a long line at a column budget instead of handing the
#        renderer one line wider than the glasses display, and the deck bench
#        gives each paper its own database. See GLASSES_VIEW_CONTRACT 1.11.0.
# 0.28.0: an answer reaches the operator as writable text, and an answer that
#        lost an element is no longer reported ready. See API 1.19.0.
# Predevice hardening: exact input identity and durable browser send guard.
# Snapshot reads and recording-retry integrity; no HTTP envelope change.
# Capture evidence diagnostics and honest text-bounds/review labels; HTTP unchanged.
APP_VERSION = "0.35.2"

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
# 1.10.0: text-first /match and /questions (additive): image became optional
#        on both; /match and /questions gained ocr_text/vision_text form
#        fields (fast_ocr_text stays as the legacy /match alias; /questions
#        folds the figure reading into the question material) and /match
#        responses gained query_signals while query_phash/hamming may now be
#        null for text-only comparisons; neither text nor image -> 400. New
#        additive endpoint GET /v1/documents/{id}/scan-status
#        (読取状態の確認・復旧). Path shapes unchanged — no envelope change.
# 1.11.0: solution/explain evidence gains canonical `evidence_refs`
#        ({document_id, 1-based page_number}); legacy `evidence_pages` keeps
#        its API v1 route semantics. Explain responses gain `cached`, and
#        history returns detail, evidence/provider metadata and result extras.
#        Sparse page indexes are rejected with 409 before finalize/navigation.
# 1.12.0: scan-status pages gain has_image; document finalization persists
#        image-analyzer OCR/vision text and rejects unreadable photo-only pages;
#        finalize-reading attaches the problem's starting-page image to solvers.
# 1.13.0: page replacement is atomically rejected after a session enters
#        review; oversized decoded images return 413; audio uploads use
#        allow-listed suffixes and format-correct provider metadata.
# 1.13.1: Pillow decompression-bomb rejections consistently return 413; raw
#        AAC and unrecognized audio are rejected before an OpenAI SDK call,
#        including AAC hidden behind a leading ID3v2 tag.
# 1.16.0: new GET .../answer-bundle — one complete, ordered answer snapshot
#        (大問 groups folding their sub-question rows) for offline glasses
#        reading; 409 during the reading phase or a real-mode lock. Additive.
# 1.17.0: new GET .../paste-prompt — the current page rendered as one block of
#        answer-only prompt text plus a prefilled chatgpt.com link, for solving
#        by hand in a phone browser. Read-only: it sends nothing, persists no
#        question and returns no answer to the session. Additive.
# 1.18.0: new GET .../pages.pdf — every captured page of the session's document
#        as one PDF, so the phone path can attach the material once instead of
#        one photo per page; paste-prompt gains the additive `pages_pdf_url`.
#        404 when the document is text-only. Additive.
# 1.19.0: the answer bundle converts a solver's answer into text the glasses can
#        render (LaTeX fractions, powers, indices, roots, greek, 場合分け) and
#        adds the item status `needs_review`: the answer is still carried, but an
#        element the display cannot hold — a table, a figure, unknown notation —
#        is named in `issue` instead of being dropped from a `ready` answer
#        (tasks/todo.md FS-65). A client that does not know the status must be
#        updated; relaycore 0.3.17 does.
# Adds operation_routes and explicit client-OCR/image-only real-mode behavior.
# Content digest v2; persisted solve failures change the existing bundle revision.
API_VERSION = "1.22.0"

# Matching algorithm identity. Bump when thresholds or hashing change so a
# re-index/eval is triggered. Mirrors thresholds in app/matching.py.
# 1.1.0: OCR signal is now graded text similarity, not exact MD5 only.
# 1.2.0: text-only scoring mode when the query and/or candidate has no pHash
#        (撮影しない pages are first-class candidates): exact normalized-text
#        MD5 -> TEXT_EXACT_CONF (0.95), graded similarity mapped onto the
#        OCR_SIM_FLOOR/OCR_MATCH_RATIO anchors; ScoredCandidate.hamming is
#        None for text-only comparisons. Text comparison shape is aligned per
#        candidate on the signals BOTH sides carry: body+figure on both ->
#        the components are compared separately and averaged with equal
#        weight (a long shared body cannot mask a mismatched figure reading)
#        while the exact-MD5 shortcut hashes the FULL combined material on
#        both sides, even for legacy image queries; figure on both but a
#        body missing -> figure readings alone; body on both -> bodies alone
#        (image sides keep the historical body/raw-bytes MD5 compat); no
#        common signal -> body-first fallback. So a partial
#        query/registration still exactly matches on the shared signal.
#        Ranking: full-information HITs (every supplied signal checked and
#        the HIT band reached) outrank partial-coverage matches even at
#        higher partial confidence; a STRONG pHash match (hamming <=
#        HAMMING_STRONG) counts as full information (a near pHash match still
#        carries the text-coverage penalty, and a candidate that shares NO
#        signal type with the query has 0 coverage — nothing was verified);
#        remaining ties break by similarity, then signal_coverage. pHash
#        presence checks are explicit (a valid all-zero hash still compares
#        visually). Image-vs-image scoring unchanged. RAG retrieval scores
#        pages on the RAW body + figure reading (pages.vision_text, no display
#        header) and windows the snippet around the matched term, so
#        figure-only supporting values are recallable AND surfaced in context
#        without boilerplate overlap. segment_problems detects deck boundaries
#        from the body only and appends the figure reading to EVERY same-page
#        problem, so figure labels never split a question and the
#        figure-dependent problem always gets its values.
MATCHER_VERSION = "1.2.0"

# HUD payload shape: {verdict, confidence, lines:[3]}.
HUD_CONTRACT_VERSION = "1.0.0"

# Analyzer plugin interface (provider-agnostic OCR/summary/embedding).
ANALYZER_API_VERSION = "1.0.0"

# Solver plugin interface (provider-agnostic question answering).
# 1.1.0: Question gained the optional `image_path` field so vision-capable
#        solvers can answer from the scanned page image (additive/back-compat).
# 1.2.0: SolveResult gained canonical, document-qualified, 1-based
#        `evidence_refs`; legacy `evidence_pages` semantics stay unchanged.
# 1.3.0: opt-in answer_only keeps the complete written response, separates
#        missing material and prohibits placeholder fallback in that mode.
# 1.4.0: a solver may be backed by a browser session instead of a credentialed
#        API. `ready()` therefore probes a reachable browser, and provider names
#        are no longer restricted to the API provider set (additive).
# 1.5.0: Question gained `image_paths` — every page of the question's 大問 in
#        reading order. `image_path` stays the primary page for adapters that
#        take one image; multi-page-capable adapters read the list (additive).
# 1.6.0: Question gained the optional `audio_path` field, so a listening
#        question can carry the recording itself and not only its transcript.
#        Adapters that cannot take audio ignore it (additive/back-compat).
SOLVER_API_VERSION = "1.7.1"

# Media-extractor plugin interface (formula/figure/graph/table).
EXTRACTOR_API_VERSION = "1.0.0"

# Explainer plugin interface (live page explanation with RAG context).
# 1.1.0: ExplainResult gained canonical, document-qualified, 1-based
#        `evidence_refs`; legacy `evidence_pages` semantics stay unchanged.
EXPLAINER_API_VERSION = "1.1.0"

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
# 1.5.0: evidence labels are document-qualified and user-facing/1-based
#        (`D{document_id}:P{page_number}`) when structured refs are available.
# 1.6.0: capture contract describes real CXR-L photography and reports shutter,
#        flash and capture cues as device-controlled instead of promising silence.
# 1.7.0: the relay capture lifecycle is fail-closed for timeout and ambiguous
#        Binder starts; reconnect creates a new callback epoch so delayed events
#        from an old service binding cannot complete a new capture.
# 1.7.1: glasses status callbacks retain unresolved captures. Only a terminal
#        image callback or an actual CXR-L service-binding reset releases them.
# 1.8.0: every snapshot enters an explicit capture-review state.
# 1.9.0: unverified CUSTOMVIEW/AI callbacks are diagnostic-only. Capture,
#        registration, completion and navigation are phone-controlled; no
#        automatic registration is advertised.
# 1.10.0: local glassdoc gestures restore sessions after configuration, retry only
#         terminal capture failures, and display tap/swipe instructions.
#         Phone/CUSTOMVIEW controls remain unchanged.
# 1.11.0: a logical line WRAPS at a column budget (MAX_COLUMNS,
#         ROKID_HUD_MAX_COLUMNS, default 18; a full-width glyph costs 2), so a
#         long answer becomes more lines and more view pages instead of one
#         line wider than the display. No character is dropped: this is not the
#         [:24] truncation removed in 1.2.0. GET /v1/settings publishes
#         max_columns_per_line, column_unit, wraps and truncates. The budget is
#         an estimate; the CUSTOMVIEW overlay's text area is not measured.
# Local mode selection, durable page commits, menu BACK and explicit session recovery.
# Local PCM recovery, sample-driven REC, and audio stop independent of photo review.
# Full-display page aiming, readable still previews and visible analysis exit confirmation.
# Upright, magnified still review and phone-side unfold-to-chooser startup.
# Failed CLOSED persistence keeps the answer and shows a retry notice.
# Composition-only review and bounded clipped-shot ranking; 3s timing unchanged.
GLASSES_VIEW_CONTRACT_VERSION = "1.17.2"

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

# rokid-docscan-starter development guide

Status: Current engineering contract. Updated 2026-11-10.

**Start at `.agents/progress/current.md`.** It lists the operator's decisions,
the verified state and the next steps. Do not re-ask what it settles. Keep the
prohibitions below. Treat this file's measurements and "the platform cannot"
statements as past observations: check them against the artifact before relying
on them. Judge every change by one test: does ChatGPT answer correctly from the
image, and can the answer be read on the glasses?

## What this repository is

The operator's 2026-10-29 requirements in `tasks/plan.md` take precedence over
older model, review-display and power preferences below. Venue operation uses
only the always-on phone and glasses on its hotspot: no PC, wired connection or
repeated connection procedure. PC commands in development records are not the
venue topology. Prioritize accurate, fast automatic capture/quality inspection,
ChatGPT app/web Work with every original image and answer return, and minimal
HUD, before subject/year benchmarks. Compare recording/frame selection, native
stills and their combinations, rather than assuming the existing still loop is
the selected design. There is no operator-specified fixed order among capture,
Work and HUD improvements. Work Cloud is under investigation; Drive, the phone's
existing browser and official external triggers must be compared before adopting
a transport. PC-local Work is not a venue alternative. Do not present a component
test as proof that this complete route works. Read the conversation's corrections
and the current section of `docs/requirements-audit.md`; earlier proposals and
historical implementation states are not current decisions. Continue independent
PC work while a manual action remains pending.

Photograph arbitrary problem papers, and let the operator read **what to write
on the answer sheet**, including complete written solutions, on Rokid Glasses.
Subject, year, institution, printed question labels and a known paper size are
not prerequisites. GPT reads the original images and determines the questions,
required answer form, figures and missing material; the app does not impose a
separate subject or question-format classifier before submission. Preserve the
model's complete answer and its association with the source question, including
unlabelled questions and intentionally nonconsecutive printed answer numbers.
The operator's 2026-11-01 request includes remaining physical-paper checks;
an earlier decision to defer them is historical, not a current exclusion.
On 2026-11-05 the operator confirmed both devices connected and requested overall
functional/structural evaluation and improvements before physical capture. Treat
the connection as current fact, not an instruction to start capturing a paper.

The scan-and-match half (`/v1/match`, pHash, page dedup) is the foundation this
was built on, not the goal. Do not describe it as the product.

The intended session, from `tasks/plan.md`:

- Normal: 20-40 pages, ~10 min capture, ~10 min analysis, ~130 min review.
- Listening: ~10 min capture inside a 30 min recording, ~10 min analysis,
  ~110 min review.
- **No PC at the venue.** The phone reaches the internet over 4G/5G and, from
  2026-09-14, also serves a Wi-Fi AP that carries the glasses; the operator
  confirmed this is available. The server process therefore runs on the phone.
  Nothing auto-terminates at 150 minutes.
- **The current implementation uses Termux Chromium**, a private persistent
  profile and loopback CDP. Visible login and later runs use Termux:X11.
  Four Termux services supervise X11, the browser, FastAPI and the watcher,
  with Termux:Boot after first unlock and available tethering. The separate
  `:phonehost` Android app monitors loopback API health after explicit enablement.
  Its connected-device foreground service invokes the fixed existing Termux boot
  script through the public RUN_COMMAND service after an unavailable health check
  and a persisted cooldown. The enabled choice survives service recreation and
  BOOT_COMPLETED. Explicit stop wins over an old in-flight health check. The
  bootstrap retains each runit service's enabled/disabled choice. Termux command
  permission and allow-external-apps are initial setup requirements. On the measured
  phone headless starts encountered HTTP403; visible Work completed original-image
  technical fixtures. This does not establish a platform-wide headless restriction.
  Login persistence and venue operation still need physical acceptance.
  The previous Android Chrome route was measured 2026-09-15
  (`docs/hardware-measurements.md` §F-6-1):
  foregrounding Termux removed `@chrome_devtools_remote` outright, and
  foregrounding Chrome rebuilt it under a new inode in about 2s, with the
  screen awake throughout. The operator's 2026-09-15 decision to keep the
  screen on and the phone face down applied to that earlier route.
  The endpoint also refuses the first probes and then answers (§F-6-2), so one
  refusal is not an absent browser; both `cdp_available()` and
  `app/solvers/cdp.py` retry.

Two cooperating runtimes:

- `app/`: the FastAPI document-analysis and answer server.
- `android-relay/`: the Android-phone relay for Global Hi Rokid and Rokid
  Glasses, plus the glasses-side apps.

The **decided venue topology** (operator, 2026-09-14) is the standalone glasses
app over a phone access point. The operator does not touch the phone during a
session; the glasses' own tap/swipe drive it.

```text
Rokid Glasses (:glassdoc APK) -> phone Wi-Fi AP -> FastAPI on the phone
                                                -> Termux Chromium CDP -> ChatGPT web
Rokid Glasses (:glassdoc AnswerView) <- answer-bundle
```

The operator confirmed on 2026-09-14 that the phone can be an access point,
which retires the "the glasses have no network at the venue" premise that this
file carried until then.

**None of that topology has been run.** What is measured is each piece
separately: the glasses app captures and reaches a server over Wi-Fi
(2026-09-04), and the phone-only CDP/FastAPI/answer component in §F-6 (2026-09-15).
The AP has never carried a complete glasses session.

The **phone-relay topology** below is what this repository has actually
exercised end to end, and it stays as the fallback. Do not extend it.

```text
Rokid Glasses -> Global Hi Rokid -> Android relay -> FastAPI server -> HUD
```

The server still publishes `OPERATION_CONTRACT` as `phone` for every action,
because that is the relay route's contract and the glasses route has not been
wired to it. A document that says the glasses drive the operations is describing
a decision, not the current published contract. Say which one you mean.

Which of each duplicated surface is the route, decided 2026-09-14:

| Role | Route | Kept but frozen |
|---|---|---|
| Capture + page-change observation | `android-relay/glassdoc` | `android-relay/app` (phone relay + OCR) |
| Answer display | `AnswerView` + `AnswerLayout` (measures the real font) | `app/glasses_view.py` wrapping (estimates 18 columns), `app/hud.py` (`/v1/match` only) |
| Answer delivery | `GET /v1/exam-sessions/{id}/answer-bundle` | `/v1/exam-sessions/{id}/paste-prompt` (already rejected; `pages.pdf` beside it was removed on 2026-09-29, since outside Enterprise ChatGPT discards a PDF's images) |

Frozen means the code stays and its tests keep running. It does not get new
features, and a measurement taken on it does not validate the decided route.
`docs/superpowers/specs/2026-09-11-glasses-offline-answer-bundle-design.md` is
the design of the decided route, not a shelved one — its phone-hotspot topology
is now the intended topology and is still unexercised.

## Answer routes

| Route | Status |
|---|---|
| `ROKID_SOLVER=chatgpt-web` | The existing Chat route drives the operator's own signed-in ChatGPT web session over CDP. A booklet is one JPEG per page and two per spread split at the fold. Each photo is first cropped to its paper and a margin when the paper box is certain (at least 15% of the frame, at most one frame side touched, unchanged when the brightness floor is lowered, at most 5% of the paper-like area outside the crop, and at most 65% of the frame kept); otherwise the whole frame is sent as before, and the stored original is never changed. On the 27 distinct real photos on this PC (2026-11-10, each crop looked at) 14 of the 16 whole spreads taken by glassdoc were cropped without losing paper, the 7 taken by the glasses' own camera app stayed whole, and the 4 frames whose box was wrong were sent whole. Before anything is attached, the file count is compared with what is left of a rolling 3-hour window (`ROKID_CHATGPT_UPLOAD_WINDOW_FILES`, default 80, the paid-plan figure read on help.openai.com on 2026-11-10). The window counts every file this server attached, including Work ZIPs and attempts that were never confirmed; uploads made elsewhere on the account are invisible to it. A booklet that does not fit is refused before any send, is not retried or moved to another route, and shows its count and the remaining room on the glasses. PC tests only. |
| `ROKID_SOLVER=chatgpt-work` | The requested phone-local Work consumer sends unchanged image ZIPs, verifies source receipts and returns staged answers. PNG is the default; opt-in native JPEG sources bind explicit rotation and upright RGB evidence to the canonical PNG. Work PNG technical fixtures passed on the signed-in phone. The production model verifier confirmed Sol / Extra High / Fast and its owned-menu closure. Common SEND1 and restarted API/watcher readiness were checked while retaining the browser/X11; this activation sent no diagnostic material. JPEG delivery, full restart and venue acceptance remain unverified. Measured on this PC on 2026-11-10 with the 19 distinct glassdoc photos, processed as an upload is (rotation 270): the upright PNG is 2.41 times its JPEG (median 14.17 MB against 5.93 MB), so 40 photos are 575 MB in 20 ZIPs and 7 messages as PNG, and 238 MB in 8 ZIPs and 3 messages as JPEG. The default stays PNG: every JPEG needs the model to apply rotation 270 and return the upright-pixel hash, a rejected receipt does not switch routes, and no Work run has shown those receipts pass on real photos. That single run decides the default. |
| On-phone local model (F-51F, llama.cpp) | **Not the route.** The operator chose chatgpt-web on 2026-09-14. Its measurements are kept as evidence in `docs/hardware-measurements.md` §E; no further work is scheduled on it. |
| `openai` / `gemini` / `claude` API keys | Supported and config-only. The per-question routes can fall back through `ROKID_SOLVER_TIERS`. They have no one-message booklet answer, so they are not booklet fallback routes. |
| Booklet route fallback (`ROKID_SOLVER_FALLBACKS`) | Requested by the operator on 2026-11-10. When Work returns a usage limit, or cannot send (model or attachment control unusable after one retry), the same booklet goes to `chatgpt-web`. The choice is stored on the deck row, so a restart does not return to the limited route. An unknown send outcome, a shared browser/login/guard failure, a readability or receipt rejection and the listening stage never switch. Observed on the phone's live tab on 2026-11-10 without typing or sending: the new-chat page has two buttons, Chat and Work, and only pressing Chat leaves Work (a click right after the navigation was dropped, so it is repeated until Work is inactive); in Work mode Chat's composer is absent; Chat's effort is a five-position Power slider whose top position is Pro (shown with "Locked" and "Usage limit reached"), so the route moves it to the position labelled Extra High and refuses any other readable position. That preparation ended at GPT-6 / Extra High and Work was restored. Not observed: a real limit notice, a Work task cut short, and a Chat answer after a Work refusal. |
| Local OpenAI-compatible HTTP (`app/llm_http.py`) | Reaches an on-phone `llama-server` without the openai SDK. |

Settled decisions. Do not re-argue them:

- **Automating the ChatGPT web UI is against OpenAI's terms of use** and can get
  the account restricted. This was raised three times and reaffirmed each time.
  It is the operator's decision, and it must be stated in user-facing docs.
- No API key for the primary route; the operator chose the web UI over
  `ROKID_SOLVER=openai` twice.
- No per-question hand work. A `?q=`-prefilled deep link or manual pasting is
  not acceptable.
- Do not build a browser connection pool.

**Open gap.** The current record includes phone-only CDP, FastAPI discovery and a
text answer in `docs/hardware-measurements.md` §F-6-6 through §F-6-10. These are
component measurements, not a glasses → phone AP → answer-bundle session.
That full route, the new capture/power behavior and the model's use of original listening audio remain
unvalidated on hardware. Do not describe chatgpt-web as venue-ready.

The earlier Android Chrome build used an abstract unix CDP socket and an
on-device forward. Those source/device observations remain in
`docs/hardware-measurements.md` §F. The current Termux Chromium launcher opens
loopback CDP directly and does not use a phone-to-itself connection. Verify
visible login persistence and actual public model/effort/speed selection before
switching the physical route.

A throttled account is refused in the message *body*, not by an exception. The
solver's rate-limit markers exist because a retry loop read a refusal as a bad
answer and turned one block into many on 2026-09-14. The slow-generation brake
beside them was removed on 2026-09-29. A booklet now sends single-page JPEGs
in the same chat in batches of at most 20 files including audio. Completed
intermediate receipts precede the next batch; the final batch requests every
answer. Durable progress and the existing uncertain-send guard prevent a
restart from repeating a confirmed or uncertain send. Long generation is normal.
Before attaching files, select the first visible model option: the position
previously named Latest, now GPT-6. The operator wants this same position after
future display-name changes. Immediately before sending, confirm its public
checked/selected state without another model click. Model names and configured
selectors are hints. A readable lower-effort choice, ambiguous
selection, obstructed click or unclosed popup still stops submission.
Close and confirm only a popup the verification itself opened. Login, attachment
and uncertain-send safeguards remain independent of model-name fallback.

Ordinary new Work answer jobs default to Fast for production. Trials and
verification explicitly set `ROKID_WORK_SPEED=standard`; the phone's current
Standard override is a trial setting. Existing sealed jobs, restarted sends and
their later listening stage retain their saved settings. Capture-inspection and
quality requests retain dedicated Standard settings. Actual model, effort and
speed verification and uncertain-send safeguards apply to both answer speeds.

## Real-device contract

- Photographing the physical page is the primary input path. On the decided
  route `:glassdoc` opens `camera2` on the glasses and observes image change; on the
  fallback relay route the phone calls CXR-L `takePhoto`, receives the JPEG,
  performs bundled Japanese ML Kit OCR, and uploads both JPEG and OCR. Both go
  through `relaycore`'s `DocScanController`.
- **The decided capture method is automatic scanning** (operator, 2026-09-15).
  `docs/fast-scan-decisions.md` defines it: the glasses detect the page and
  shoot on their own, the captured image is shown for 3 seconds, no input
  commits it and moves to the next page, and a double tap ends the capture
  phase. Zero phone operations after setup. On 2026-11-12 the operator asked
  for one tap to clear the display and stop the camera and one tap to bring
  them back; in ordinary reading the retake and the manual shot, which the tap
  did until then, moved to the forward swipe. The same rule holds on the
  chooser: a tap turns the display off, a swipe selects, a double tap starts.
  Mixed English and listening keep the earlier assignment while capturing.
  `docs/multimodal-scan.md` holds the operation table.
- **The existing loop is enabled only on `:glassdoc`.** Page change is latched
  until stillness permits one shot; OCR character count and burst scoring are
  not capture conditions. Actual review lasts three seconds, then local save
  waits for another page change. While local capture remains active, page
  observation continues across idle waits without a resume tap. Explicit end,
  lifecycle stop and failure boundaries still stop the camera. A previous
  `manual=true` does not carry over to a normal launch.
  The same preview session supplies the full-size still after fresh supported
  focus/exposure and stillness checks: full-size YUV beside the running
  preview, copied, closed and then encoded to JPEG (quality 98) off the camera
  thread, about 1.0 s from request to bytes with the preview never stopping
  (glassdoc 0.43.13 on the glasses, 2026-11-12, `docs/hardware-measurements.md`
  §M-5). That JPEG carries no EXIF; its provenance stays `native_still`. On
  firmware `1.29.013-20261110` a session holding the camera's JPEG output
  beside any other output never returned the still and the camera provider
  aborted (§M-1), so the camera's own JPEG is used only where the YUV pair is
  refused, on a JPEG-only session of its own with the preview put back
  afterwards. With this, glassdoc 0.43.10 took and saved stills on the glasses
  in 1.5-1.7 s, three runs and four in one session, in a dark scene; what a
  page looks like in them is not measured. In a lit scene that version took an
  unmoving page again and again, because the returning preview starts its
  exposure over; 0.43.12 does not count frames as page evidence until a fresh
  converged result arrives (§M-4). The JPEG-session path leaves about 3 s
  without preview after each still; the YUV path leaves none. Which noise
  reduction and edge setting reads best on a lit page is not measured. The ZSL and recording evaluation
  launches still put the JPEG beside other outputs. Fixed-focus hardware does not
  gain autofocus from an AF trigger. Expired preparation never forces a
  moving shot. Before any camera request it is a cancelled preparation: the
  wearer is told to hold still, the session continues and the same page is
  observed again (2026-11-10; until then it ended the session and required an
  app restart). A failure after the camera request stays UNKNOWN. Evaluation
  modes keep the earlier fatal stop. PC tests only; physical character
  accuracy remains unverified.
  Gyroscope freshness uses the sensor's measurement timestamp, including delayed
  deliveries and gaps in the retained preview stream. On supported fixed-focus
  cameras the still copies the exposure, sensitivity and gain the preview's auto
  exposure measured, and the exposure is shortened only by asking that auto
  exposure for a faster frame-rate range: 60 where one flicker period needs a
  total gain of at most 1600, else 30 where 30 ms needs at most 6400, else the
  template's; leaving a range needs more than entering it. Above a total gain
  of 1600 the still asks for no edge enhancement. Shortening by hand failed
  three ways on the glasses: darker left a dim page at 17 of 255; the preview's
  own 50-70 ms was never still enough on a worn head (§M-6, §M-7); one period
  with the gain raised by hand was colour noise, level over noise 2 against 43
  from the glasses' own camera, because the ISP tunes noise reduction to the
  auto exposure's state (§M-9, §M-10). In one dim desk scene glassdoc 0.43.16
  read 38-40 against that camera's 45 at half its exposure. The dark photos of
  September (8.3-10 ms, sensitivity 50-60) were the app's exposure, about a
  twelfth of the light the glasses' camera used that night, not the room. The
  glasses' camera waits for stillness, takes an auto-exposed exposure bracket
  of five frames and fuses it with a vendor library no third-party app can
  call; glassdoc takes one frame, and averaging four 30 ms frames of a still
  scene passed that camera's noise. A lit page, a worn head, burst alignment
  and the bounds of the ranges are not measured. Preview frames brightened by
  a still in flight are not page evidence. Its JPEG joins the matching capture result
  within the existing deadline. Missing or inconsistent metadata retains the
  original for explicit recapture. Live preview retains at most one queued bitmap.
  The original JPEG budget is 20 MiB across capture, local persistence and image
  upload. The measured camera advertises 18,457,096 bytes as its JPEG maximum.
  An explicit `zsl_evaluation=true` launch evaluates full-resolution YUV
  reprocessing on cameras advertising the required reprocessing, burst and
  realtime timestamp capabilities. It pairs input frames with their own session's
  capture results and the current scene/quiet interval. Default native stills
  remain the ordinary route. Unsupported evaluation is reported instead of
  silently mixing native samples into the measurement. Queue and close work
  must not block the camera handler or falsely acknowledge a completed stop.
  An explicit `video_evaluation=true` comparison keeps maximum native JPEGs
  beside a silent original MP4. It queries MediaRecorder sizes, AVC/HEVC
  encoder capabilities and the exact three-output session without a silent
  profile fallback. Recorder preparation/finalization run off the camera handler;
  stop acknowledgement waits for finalization and retains uncertain originals.
  Its private journal separates selected profiles, actual container metadata,
  camera scene timestamps and unknown video PTS correspondence. The bounded
  local clip is not an automatic whole-booklet recording. An additional explicit
  `video_transfer_evaluation=true` launch enables comparison transfer, without
  persisting that choice or changing the journal's `auto_upload_allowed=false`.
  A separate origin binds the local session, device and generation before
  recorder preparation, then binds the matching server IDs once. A dedicated
  worker streams the sealed original and retains the exact envelope and receipt.
  Stale generations, changed local artifacts and uncertain responses cannot
  acknowledge a transfer. Camera stop and ordinary page uploads do not wait for it.
  Optional phone-side capture inspection keeps the unchanged original PNG in
  each new diagnostic packet, with one overview and at most four native-pixel
  regions when the bounded packet budget permits. An original exceeding that
  comparison budget is retained as unknown; prepared or uncertain old manifests
  are preserved. It uses the existing Work writer and uncertain-send journal.
  Exact decoded-video candidates share that diagnostic
  queue. A current-run origin is fixed before capture; restored legacy originals
  remain usable without invented generations. Results never authorize automatic
  retakes, quality acceptance or wake. PRIVATE reprocessing and live AI inspection
  remain comparison candidates without physical quality or performance acceptance.
  The frozen CUSTOMVIEW route keeps explicit phone controls. The original
  `adf12ee` disable decision belonged to the route without operator taps.
- An explicit, nonpersistent `native_selection=true` comparison launch may take
  one additional maximum-size native JPEG only when the same scene is already
  ready, without waiting for preparation or taking priority over a next page.
  Retain both originals and their provenance before comparing bounded native-pixel
  regions. Unknown or tied comparisons retain the first image. A selected second
  image must receive its own fresh three-second visible review before ordinary
  upload; stale scenes, expired review, generation changes and terminal states
  cannot replace it. Restart must not repeat the extra request. This comparison
  is default-off and exclusive with ZSL, recording and paper-geometry evaluation.
  Physical character accuracy and additional latency are not accepted yet.
- On the local surface the captured still is drawn after its native image is
  closed. The preview session continues observing page changes until pause,
  capture end or failure; physical frame continuity remains unverified. A
  visible acknowledgement starts a fresh 3000ms review. During review, at most
  two future-page originals are retained locally and promoted in order; each
  requires its own visible acknowledgement and review before upload. Observation
  is reserved durably before native start. Unknown captures, failed persistence
  and suspected gaps survive restart; only an acknowledged ordinary stop can
  clear a resolved observation. A forward swipe retakes, no input commits, BACK ends
  capture after the last review. Hidden or stale views cannot commit. A waiting
  forward swipe first waits for the native stop barrier and promotes any saved
  candidate before requesting a manual shot. A tap pauses: the photo in hand is
  saved first, then the camera closes and nothing is drawn until the next tap;
  the same page is not taken again on return (on the glasses, 2026-11-12,
  `docs/hardware-measurements.md` §M-4). One photo remains in flight at most. This
  does not establish whole-booklet coverage or physical readability. See
  `docs/multimodal-scan.md`.
- The standalone app keeps the previous listening-only flow and adds mixed
  English: capture paper first, solve reading from images, then send completed
  original audio to the same chat after the reading reply is durably saved.
  Audio-dependent questions remain pending before audio; missing recording is
  never inferred. Capture/review swipes and reader/analysis/waiting single taps
  toggle mixed recording without shifting answer position. A waiting swipe
  returns to saved reading answers. The phone preserves and verifies all chunks
  before audio analysis. The chatgpt-web route
  sends original images/audio, not OCR or local transcripts, and does not require
  local VAD/ASR. ASR remains for compatible non-browser provider paths.
  Diagram answers use validated vectors and the existing AnswerReader/Canvas.
  Extended figures use schema 3 for arcs, hatched polygons and optional dashed
  strokes/filled circles; legacy figures retain schema 2 and text schema 1.
  Preserve literal program identifiers/indentation and whole mathematical script
  groups. Unsupported Markdown table blocks and matrix-bearing expressions retain
  their source notation and remain needs_review before scalar conversion. This
  source-preservation boundary is not cell-aligned or typeset matrix support.
  The server must not silently truncate printed answer numbers.
  These new behaviors have not passed physical acceptance on the current APK.
- Answer reading is continuous: pack short items on one screen, keep full
  derivations and diagrams, and retain printed answer numbers and position.
  The first final-reader double tap persists writing completion and sleeps
  inside the app; only two further double taps within three seconds exit to home.
  Mixed intermediate reading completion returns to audio waiting and keeps
  recording; a later answer revision updates the same question identities.
  Authenticated device/session/generation/sequence state lets the phone watcher
  request sleep/wake. A completed or closed generation ignores late answers.
  The phone repeats an answer notification until `ack_answer_revision` confirms
  a bundle saved and displayed by that client; generated revisions are not
  receipt acknowledgements. The client suppresses concurrent and duplicate loads.
  Complete answer JSON is bounded to 64 MiB and answer/issue text to 24 Mi UTF-16
  units. These budgets cover the two 8 MiB Work stages and expanded mathematical
  glyphs. Network input and atomic offline saves use bounded streams. Schema
  versions 1, 2 and 3 remain readable, including existing saved cursor state.
  Long-answer layout keeps bounded page-position indexes and constructs visible
  pages when requested. Initial layout waits for the measured view dimensions.
  Saved-answer reads and explicit resume run on the serialized persistence worker.
  A resume canceled before its commit decision rolls back its atomic save.
  Explicit completion waits for durable storage before leaving the reader.
  Keep microphone input while muting output. Do not hold the glasses CPU for
  indefinite analysis or poll answers there; bounded upload work may retain CPU
  only until its timeout or completion. Physical silence and timing are pending.
- Ordinary still review shows the image without text covering it. Keep the
  three-second visible review and the existing retake/end gestures. Preserve
  the operator's system screen-off timeout, including disabled auto-off:
  capture/review/reading hold the app window on. Chooser, recording-only,
  uploading, analysis and other waiting sleep after five seconds without user
  input; network refreshes do not extend that timer. Authenticated phone-watcher
  requests handle sleep/wake. Sleep uses Android's soft-sleep key so the window's
  current screen wake lock is checked when a delayed request reaches the device.
  Old persistent generations cannot release or reacquire the current window's
  display hold. Ordinary chooser updates are not app-entry requests.
  Confirmed wear requests use a fresh persistent generation and an explicit
  chooser entry, explicit wake and no old answer-wake extras. Never restore
  a saved timeout over a later operator choice. For a serial-verified, previously
  running app, a fresh explicit sleep request precedes fold/process diagnostics;
  cold-start and prior in-flight work can still delay delivery. A saved-answer
  hardware trial retained display and cursor through the12.297-second observation
  after SOFT_SLEEP (`GL48-saved-reader-display-hold-20261031.py
  --execute-approved-once`, exit0; independently audited). The operator also
  confirmed that the answer stays visible and readable. On 2026-11-09, the
  updated app emitted chooser sleep requests after 5.012 and 5.016 seconds.
  The phone watcher returned SOFT_SLEEP 0.216 and 0.163 seconds after reading
  those authenticated requests. Android readback changed from Awake at 5.391
  seconds to Asleep at 6.047 seconds in the sampled chooser trial. Saved answers
  remained Awake with a window hold for 12.578 seconds after SOFT_SLEEP, with
  identical before/after screenshots. The external timeout stayed unchanged.
  These are device readback observations. Optical, restart and full-duration
  acceptance remain pending.
- Text-only page upload remains an API compatibility path. Do not describe it
  as the real-device primary path.
- The public CXR-L AIDL surface does not expose arbitrary recognition or
  answer text from the AI running on the glasses. The current production path
  uses a configured server solver; glassdoc observes page images,
  while the frozen relay performs OCR on the phone. On the background
  chatgpt-web route the model lists and answers the questions from the original
  images after ordered attachment receipts and OCR does not segment or gate capture.
- Use the official `com.rokid.cxr:client-l:1.1.1` dependency. Do not commit,
  copy, or redistribute Rokid AAR files.
- Global Hi Rokid uses package `com.rokid.sprite.global.aiapp`. Keep the
  package/action assumptions isolated in `RokidGlobalLink` and revalidate them
  after Hi Rokid or YodaOS updates.
- CUSTOMVIEW operator tap delivery is not a verified control surface. A
  17-minute measurement on 2026-08-29 found no callback aligned with operator
  taps; use phone controls for capture, retake, registration, and completion.
  This is a property of the tested overlay/session, **not of the platform**.
  The CXR-L AAR exposes
  `IMediaStreamService.uploadAndInstallApk` / `openApp` / `stopApp` /
  `uninstallApp` / `queryGlassAppInstalled` in the inspected 1.0.1 and 1.1.1
  artifacts, with `SessionType.CUSTOM_APP` in 1.1.1. A glasses-side Android app
  is therefore a supported SDK route, but this repository has not completed a
  successful hardware install/start validation.
- The same interface carries an arbitrary-`byte[]` channel in **both** 1.0.1 and
  1.1.1: `sendCustomCmd(String, byte[])` phone-to-glasses and
  `ICustomCmdCallback.onCustomCmdResult(String, byte[])` glasses-to-phone
  (`sendCustomCmdStream` is 1.1.1-only). So a glasses-side app does not need its
  own network to return data. Nothing in this repository calls it, the
  glasses-side counterpart API has not been seen, and no payload ceiling has
  been measured. Read `docs/hardware-measurements.md` §B-0-2 before designing
  around it.
- A glasses-side app is validated by the **adb sideload** route, not the SDK
  route, as of 2026-09-04 on build `1.25.012-20260901-150201` (Android 12 /
  API 32). Measured there: a sideloaded app is launcher-visible; `camera2`
  opens and returns `4032x3024` JPEGs in 785-1380 ms holding only
  `android.permission.CAMERA`; the glasses reach the server over their own
  Wi-Fi (`/health` 96-197 ms); and `KEYCODE_BACK` is consumable, so the
  one-finger double tap no longer ends the Activity. `uploadAndInstallApk` /
  `openApp` are still unvalidated on hardware.
- `com.rokid.os.sprite.assistserver` runs a third-party app as a `third_app`
  scene and force-stops it when the temple arms fold (`cancelAllScene`,
  `ignoreSceneList` is `[phone_call]` only). A glasses-side operator surface
  cannot survive folding; keep session state recoverable and read
  `vendor.rkd.glasses.is_spread` (1 spread, 0 folded).
- Treat this file and `docs/` as a record of what was measured, not as a
  statement of what the SDK permits. Before concluding the platform forbids
  something, read the AAR (`javap`) or another primary source.
- On the measured Hi Rokid G1.12.10.0815 / CXR-L service `1.0.0 code 10000`,
  `onAiKeyDown`/`onAiKeyUp` did not fire and CustomView close callbacks did not
  provide trustworthy operator provenance. Treat `AI-exit` and view-close
  callbacks as lifecycle evidence only, never as a shutter or commit command.
- A view swap closes before it reopens and can echo the close. Arm echo
  suppression before the Binder close/open calls, but do not promote the
  remaining close to operator input.
- Never start an auto-registration countdown before the glasses acknowledge the
  review view. Nothing may be uploaded that the operator was not shown.
- CUSTOMVIEW output is a black background, green text, and at most three lines.
  Current Global builds may require close-and-open for a reliable redraw.
- Keep the phone activity awake during a session. Some firmware stops photo
  callbacks after the phone sleeps.

The measurements behind these rules are in `docs/hardware-measurements.md`,
with the device, firmware, and version tuple for each.

## Camera and privacy

The privacy LED is controlled by the glasses hardware/firmware. Supported code
must never disable, obscure, spoof, or bypass it. This boundary holds regardless
of whether a vendor, community post, local script, privileged shell, or private
API claims a way to change it.

The operator waived the external LED audit on 2026-09-15 because the indicator
is system-controlled. It is not an acceptance gate for this route; do not ask
for an external camera again. This does not change the prohibition above or
turn an unobserved physical state into verified evidence. An SDK callback records
application state and never proves physical light state. Shutter sound, flash,
and capture indicators are device-controlled unless a documented public SDK
control is added. Do not claim silent or no-flash capture without physical
verification on the exact firmware.

An earlier branch explored changing the indicator from a diagnostic shell. It
is quarantined: `app/devtools/rokid_led.py` and `scripts/rokid_led.py` are stubs
with no device commands, `tests/test_rokid_led.py` enforces that, and the
procedures are deliberately not kept anywhere in this repository.

OCR文字枠の内側判定は `TEXT_BOUNDS_ONLY`（旧保存token `COMPLETE` も同義）であり、
紙面・未認識文字・図表の合格ではない。glassdocの通常確認は実画像だけを3秒表示し、
無操作で保存する。これは構図の確認で、3秒の無操作を品質承認と説明しない。
PC用の原寸点検・登録条件・比較部品は `docs/capture-quality.md`。画像由来の証拠生成と
撮影／正式登録本流の品質ゲートは未接続。既存の実機試験・導入・送信停止を維持する。

## Capture invariants

- One photo request in flight. A missing callback never authorizes another
  photo.
- A timeout, Binder ambiguity, or disconnect yields `UNKNOWN` — never `IDLE` or
  `LED_OFF` — and blocks further photos until a new session generation exists.
- Require view-open acknowledgement before starting a photo sequence.
- Capture evidence logs version, generation, timing and size, and contains no
  image bytes, OCR text, token, or API key.
- Ask before changing photo dimensions or the retry policy once hardware
  evidence exists.

## Glasses input invariants

`:glassinput` turns physical glasses input into one stream of normalized,
side-effect-free actions. It observes both the official system-broadcast path
and the Activity `KeyEvent` path.

- Emit at most one normalized action per physical gesture, and preserve ordering
  between distinct gestures.
- Use monotonic elapsed time, never wall-clock time, for correlation. The
  correlation window is measured on the current firmware, not guessed, and is
  recorded with its firmware tuple.
- Consume only a verified app-owned event; unregister receivers on destruction.
- Never use input observation to start a photo, upload, registration, or server
  request from this module.
- Never treat lifecycle callbacks, CUSTOMVIEW close, or AI-exit as operator
  input.
- Ask before assigning a normalized action to capture, registration, discard,
  navigation, or app exit.

Only four gestures reach an ordinary app; the rest are system-reserved in
`/system/usr/keylayout/Generic.kl`. The mapping is in
`docs/hardware-measurements.md` §A-2.

## Server invariants

- Store the orientation-corrected, normalized PNG as the authoritative server
  image. A native JPEG with verified capture provenance is also persisted
  unchanged beside that PNG before the page is committed. Compatibility uploads
  without native provenance keep only the PNG. New Work jobs may opt into these
  retained originals through `ROKID_WORK_ORIGINAL_JPEG=1` (default off), binding
  their encoded dimensions, explicit clockwise rotation and upright RGB hash to
  the canonical PNG. Existing jobs retain their sealed format; later checks use
  both byte hashes and immutable pixel evidence. Other solvers use the canonical
  PNG. Physical JPEG delivery accuracy and latency remain unverified.
- Optional native capture provenance must match the received JPEG's actual
  hash, dimensions, page and rotation before persistence. Keep its correspondence
  with the canonical PNG hash on that page and in the sealed Work manifest.
  Native clients require the complete provenance echo before acknowledging an
  upload. Legacy images stay usable without invented sensor metadata. These
  bindings are not physical image-quality or multi-client upload-order proofs.
  Explicit ZSL provenance uses `source_kind=zsl_reprocess` and requires matching
  positive image/result timestamps. The same sixteen-key receipt and canonical
  PNG binding apply. Pending-image format v5 preserves the source kind while
  loading v4 as native and keeping v1-v3 compatibility; missing metadata is not
  invented for legacy images. A ZSL association failure retains the JPEG as an
  unresolved local original and must remain ineligible for upload after restart.
- A configured cloud analyzer may transcribe/correct OCR and describe diagrams
  from the image. Finalization must fail clearly if a photo has no usable text
  and no image-capable analyzer is configured.
- The explicit comparison-video receipt endpoint keeps the original MP4 and
  exact metadata envelope separately from page PNGs. It requires an authenticated,
  current device/session/generation and matching document, verifies stored bytes,
  and publishes a durable receipt only after no-clobber storage succeeds.
  Stored means quality is unevaluated; it does not register pages or invoke Work.
  The explicit Android transfer client and physical video quality still need
  end-to-end acceptance on the glasses and phone.
- Persist analyzer-derived text before segmenting problems.
- Pass the originating page image to image-capable solvers.
- Keep document finalization idempotent and page replacement keyed by
  `(document_id, page_index)`.
- `/v1/glasses/state` always requires a configured API key. Store monotonic
  generation/sequence and terminal states atomically. Use the authenticated
  request's source address for watcher discovery, then check `ro.serialno`
  before device control. If that address is unreachable or state is absent,
  bounded legacy mDNS discovery may identify a candidate for serial-verified
  stopped-app bootstrap only; it must not fabricate authenticated state or a
  session generation. If the native ADB service is unavailable or empty, a bounded
  python-zeroconf child uses the current hotspot IPv4 directly. The measured
  F-51F interface is `ap0`; other phones and actual advertisement reception remain
  unverified. Forwarded headers must not select the target.
- `ROKID_REAL_MODE=1` must reject placeholder analyzer/solver combinations and
  fail explicitly rather than fall back silently.
- Never send unsupported media to a provider: OGG/FLAC are not handed to OpenAI
  unless converted to a documented supported container. A Gemini custom base URL
  is either passed to the SDK explicitly or rejected.
- Never log API keys, Hi Rokid authorization tokens, uploaded page contents, or
  provider credentials.
- Ask before schema changes, raw-upload retention, or new dependencies.

## Android build and device gates

Build and inspect before touching a device:

- Build from a verified ASCII-only path, and record the JDK/SDK/Gradle tuple.
- Check APK identity (`aapt2`), signature (`apksigner`), and SHA-256
  (`Get-FileHash`) against the intended package and activity.
- Never use a stale worktree artifact as evidence for current HEAD.
- Ask before SDK/AAR upgrades, keystore changes, or uninstalling an app.

Then, on a device:

- Enumerate devices read-only first and name the selected transport in every
  command, checking its actual serial. Refuse ambiguous target identity,
  signature mismatch, version downgrade or unknown callback state. Multiple
  listed transports alone do not make an explicitly verified target ambiguous.
- Record the exact phone / glasses / Hi Rokid / service / relay tuple.
- Report the LED result only from external physical observation.
- Ask before uninstalling apps or changing phone security settings.
- "Not connected / not ready" is a legitimate no-go result, not a failure to
  work around.

## Documentation rules

- Every Markdown file in the repository is classified as current runbook,
  frozen measurement, research, implementation plan, or internal progress, and
  `docs/README.md` is the index that does it. `tests/test_documentation_contract.py`
  fails if a file is missing from that index.
- Historical documents keep their evidence and carry an explicit status line
  with the measured tuple (firmware / service / relay / commit).
- Distinguish official API, inspected binary, local implementation, physical
  measurement, and inference. Do not convert an observation into a
  platform-wide guarantee.
- Never call a build or a unit test a physical hardware verification.
- Versions are written in exactly one place: the tuple line in `README.md`,
  checked against `app/version.py` by `test_readme_versions_match_source_of_truth`.
  Do not copy a version into another document; that is how every copy drifted
  before 2026-09-14.
- Work resumes from `.agents/progress/`, indexed under "Internal progress
  records" in `docs/README.md`. Read the whole record, not only its last
  section; the reason a step is blocked is usually not next to the step.
- A record that tells the next session what to do next names the runtime of
  each step, as a `Runs on:` line in that section. A resume list is not
  authorization: a step that does not run on the venue topology measures the
  component, not the route, and that has to be said before it is executed.
- Ask before deleting a historical record. When one is consolidated, move the
  measurements first and verify each value survived.

## Development and verification

Server:

```bash
py -3.12 -m pytest -q tests
py -3.12 -m ruff check .
```

`python` on this machine is 3.14 and has no pytest. Use `py -3.12`.
The explicit `tests` directory excludes ignored device reports and frozen audit
fixtures; run those fixtures separately with their recorded command.

Android relay:

```bash
export JAVA_HOME="C:/Users/Public/rokid-build-tools-20260901/jdk17/jdk-17.0.20.1+1"
export ANDROID_HOME="C:/Users/pupu_/AppData/Local/Android/Sdk"
./android-relay/gradlew --no-daemon test testDebugUnitTest assembleDebug
```

Use the wrapper. There is no `gradle` on this machine's PATH, and the wrapper
already sets the project directory, so adding `-p android-relay` fails with
`Multiple arguments were provided for command-line option '-p'`. From
`android-relay`, `.\gradlew.bat --no-daemon test testDebugUnitTest assembleDebug`
is equivalent. Both measured 2026-09-14: `BUILD SUCCESSFUL`, 199 tasks.

`test` is not redundant: `:glassinput` is a plain `java-library`, so its
tests run under `test` and `testDebugUnitTest` alone would skip them
silently.

The Android project requires JDK 17, Android SDK Platform 36, and internet
access for Google, Maven Central, Rokid Maven, and Gradle dependencies.
`android-relay\gradlew.bat` is a shim over `android-relay/build-windows.ps1`,
which downloads Gradle 9.4.1 once and checks the checkout path is ASCII.

For changes to the real-device path:

1. add or update unit/API tests;
2. build a debug APK;
3. complete the checklist in
   `docs/windows-android-real-device-setup.md`; and
4. record firmware/app versions and any device-dependent behavior in the PR.

An Android build proves compilation only. Do not label hardware behavior as
verified until the physical checklist has been completed.

After any change to the glasses app, and before the wearer is asked to try it,
run `py -3.12 scripts/glasses_device_check.py --glasses <serial> --phone <serial>`.
It drives the installed app over adb as the touchpad does and checks, line by
line, the environment, the chooser, the automatic photo and its exposure, that
an unmoving scene is not taken again, pause and resume, the manual shot and
what reached the phone server. `--paper <seconds>` records a real booklet
being read by the wearer. The unit tests use a fake camera and display: from
2026-11-01 to 2026-11-12 they hid a frame handler 300 times slower on the
device, a still the firmware never returned, one page taken again and again,
and a photo too dark to read. Glasses lying on a desk look across the room, not
at a page; a page's legibility and page turns need the wearer.

The glasses' own camera is the reference for exposure and processing. Over adb
`input keyevent KEYCODE_SPRITE_FUNCTION` takes one photo with it into
`/sdcard/DCIM/Camera` without stopping the foreground app. Before a change to
exposure, gain or still processing is handed to the wearer, take the same scene
both ways seconds apart and compare brightness and noise; `:glassprobe`
`--es camera_variant` takes `fps=`, `scene=` and `ev=` for the camera's own
controls. Do not attribute a dark photo to the room without that comparison,
and do not judge from old photos when a new pair can be taken. The device
check takes the reference itself and reads every app photo at the same flat
places: under 0.3 of the reference's level over noise fails, under 0.6 warns.
Brightness alone passed a photo that was colour noise.

Injected keys do not take the path a real touch takes. A touch on a sleeping
display is consumed by the wake and never reaches the app; the Activity is only
restarted and resumed (§M-12). Write gestures to the touchpad's own input device
(`sendevent /dev/input/event1`, a tap is KEY_DASHBOARD 204 then KEY_ENTER 28;
`scripts/glasses_display_cycles.py <serial> chooser|capture --raw`) and repeat
every cycle at least three times: one cycle with injected keys passed a
display-off that failed from the second use. Never pipe a dump into an
early-closing filter on the device (`dumpsys media.camera | grep -m1` killed the
camera provider while the camera was streaming); read it whole on the PC.
`docs/defect-register.md` lists the known defects by cause layer and their state.

Look at the whole system, not one component. `scripts/system_observation.py`
drives a capture through the touchpad's input device and records load, memory,
temperature and server response on both devices and every log buffer by source;
take it before and after a change to capture or display. Measured on a desk on
2026-11-13 (§M-13): ten minutes of capture took the SoC from 39 to 74 C and the
camera zone to 73.5 C, still rising, with the preview handled at 9-11 frames a
second after the first 30 s; the phone's watcher sends three adb commands a loop
to the glasses at 0.3-2.8 s each; the server's `/health` took up to 1.1 s during
uploads. A start double tap is sent once and confirmed from a time-stamped log
filter, never repeated: a retry loop repeated it into a running capture, which
only an unresolved-scene guard kept from ending and going to the model.

Check the whole use, in the order it is used, not one item. `scripts/e2e_route_check.py`
drives start, photos, end, upload, analysis wait, answers, wake, reading and finish
on the real glasses through the touchpad's input device, with a second package of
the same app (`-PglassdocRouteCheck`, beside the real one, whose saved server, key
and answers it never touches), a server on the PC with `ROKID_SOLVER=recorded`
(a recorded reply; sending off; no browser) and the watcher on the PC. First run
on 2026-11-13: 26 of 27 lines (§M-14). The phone, its hotspot and the browser are
not in that loop: it is not the venue topology. The "use in order" table at the
top of `docs/defect-register.md` says what has and has not been checked.

A check that leaves the model out has not checked the product. "Do not measure
on my account, do not waste usage" was said about repeated model-comparison
runs; it is not a ban on running the real route. The stand-in solver is for
repetition and fault injection only. On 2026-11-13 the real route ran once from
end to end for the first time (§M-15): real app, phone hotspot, phone server,
ChatGPT, answers, the phone's watcher waking the glasses, 6 min 17 s for one
page. The scene was the desk, not a problem page, and the model said so. Run the
real route sparingly: once per change that matters, at Standard speed.

## Versioning

Update `APP_VERSION` for every release. Update `API_VERSION` when HTTP schemas
or behavior change, and update `GLASSES_VIEW_CONTRACT_VERSION` when HUD or
capture semantics change. Keep README examples and tests aligned with those
constants.

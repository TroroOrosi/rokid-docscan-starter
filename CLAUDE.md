# rokid-docscan-starter development guide

Status: Current engineering contract. Updated 2026-11-18 20:00 (§M-44 (18): the answers go out at the first of two reads and the compared ones follow; GPT-6.2 Sol for the Codex CLI and Work, the operator's decision without a comparison; the route's time limit is a backstop; Chat's and Work's failures of the morning found and fixed on the live pages, and neither answers such a booklet inside a test's time; Server 0.88.0 and glassdoc 0.44.18 on the devices, checked on the desk, not worn. Before that, §M-44 (17): the operator ran three subjects in venue conditions; two were answered, the third gave nothing twice (the Codex CLI ran out its 600 s on twelve pages of Japanese and the two routes behind it, never run before, both failed; the second time the glasses stopped answering the phone); a word bank's two-digit labels were read wrongly by both reads alike; Server 0.87.0 on the phone, unit tests and one staged read only. Before that, §M-44 (16): the rest of the register worked off in Server 0.86.1 and glassdoc 0.44.16, a random driver of the capture that found six dead ends nobody had reported, a clip that lost frames in the encoder found by the forty-page desk run; on the phone and the glasses and checked on the desk, not worn; the operator asked what insures a spent allowance once Chat shares it from December, and decided that none is wanted: they will see that it does not run out. Before that, §M-44 (15): the morning's twelve booklets read again from the phone's records and the whole structure read by five audits; seven faults the operator had not reported and about eighty dead ends, eleven fixed in Server 0.85.1 and glassdoc 0.44.13, on the phone and the glasses since 23:15 and checked on the desk, not worn. Before that, §M-44 (14): the operator wore the still route once; it stopped after every photo and could not be ended, fixed in glassdoc 0.44.12 and not worn since; a whole-field still is not read at that night's light. Before that, §M-44: the operator ran three papers on large sheets, twelve booklets on the venue topology; a large sheet in one frame is not read; the blur belongs to the edge of the recorded frame and not to nearness; the frame is the middle half of the field and holds 27-47% of a paper looked at from a seat, which is why the wearer has to back off; Server 0.85.0 gives written answers their working and names answer boxes, glassdoc 0.44.11 shows a bar at each side the paper runs past and clears old readings from the glasses; of those changes only the still route has been worn).

**Start at `.agents/progress/current.md`.** It lists the operator's decisions,
the verified state and the next steps. Do not re-ask what it settles. Then read
the top of `docs/defect-register.md`: the purpose, how far each step of the use
has been checked, and the known defects by cause layer; and
`docs/whole-review-2026-11-14.md`: what has never been observed, the open
problems by stage of use, and every request of the operator with its state.
Keep the prohibitions below. Treat this file's measurements and "the platform cannot"
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

**That topology has run end to end once** (2026-11-13,
`docs/hardware-measurements.md` §M-15): the real app, the phone's hotspot and
server, Work, the answer, the watcher's wake and the reader, with one photo of
a desk, the glasses lying on it and driven from a PC over USB. It has not
carried what it is for: a
booklet photographed by a wearer, or more than one page. The Chat route sent
its first booklet from the phone on 2026-11-14 with page images cut on the PC
(§M-19), not through the glasses. The
pieces measured separately before that are the glasses app reaching a server
over Wi-Fi (2026-09-04) and the phone-only CDP/FastAPI/answer component in
§F-6 (2026-09-15).

The **phone-relay topology** below was exercised end to end earlier and
stays as the fallback. Do not extend it.

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
is the intended topology. It has run once, with the glasses driven from a PC
(2026-11-13, §M-15), and never with the phone and the glasses alone.

## Answer routes

**The operator's requirements of 2026-11-16 (§M-33 (5), §M-34).** Usage is spent by Codex and by Work, on what is sent
and what comes back; when it runs out both stop and Chat still answers. So the order is the Codex CLI, then Work, then
Chat, and each step has its reason: Work is for when the CLI cannot be used for some other cause, Chat is for when the
usage has run out. The CLI and Work answer in Fast mode; Chat has no such choice. Time: an ordinary high-school test
has to fit in its 50 minutes altogether, the wearer's writing included; a common test or a university entrance paper
has to be done with 30 minutes of its time to spare. A choice of model, effort or measure needs outside sources and
enough comparisons; high difficulty is always assumed; image reading accuracy comes first; Chat stays GPT-6 at Extra
High, and the model and effort the CLI and Work share are what has to be weighed. Paper other than a spread, and what
the answers show (working, drawings), are to be covered before a hardware trial, not found in one.

**Built (Server 0.80.0 to 0.80.3):** the order (`ROKID_SOLVER=codex-cli` is followed by `chatgpt-work,chatgpt-web`); a
usage limit on the CLI or on Work closes both and the booklet goes to Chat; Work runs behind another primary with its
sealed job, input fence and commit guard, and is passed over for a session without a registered wearer; the CLI is on
its Fast tier (`-c service_tier=priority`; `ROKID_CODEX_SPEED=standard` for a trial) and the phone's Work is back on
Fast; a CLI run that hangs gives the booklet up after 240 s plus 30 s a page (at least 600 s; it was 3600 s).
**Observed on the phone on 2026-11-16 (§M-34), with rendered pages put in from the PC:** with the operator's display
at 0% a 14-page booklet still passed (86.4 s, 14 of 14); the real limit came right after (exit 1, a notice naming the
time to try again; the CLI's session record carries the service's `rate_limits`); the same booklet then moved to Chat
by itself and, after two faults of the Chat route were fixed, came back answered (2 min 38 s, 14 of 14); the check
before use reported the CLI as `rate_limited`. **Not observed:** Work standing in behind the CLI (it needs a session a
wearer registered, and it draws on the same allowance; on 2026-11-18 it was reached in use for the first time and
stopped at its inventory, fixed in 0.87.0 by a unit test only); the switch with pages the glasses took. **Open:** one send
left uncertain blocks every later browser send until someone clears it, and nobody is at the venue (register 3-17;
cleared by hand once, on the evidence of the page); the Help Center says that from December the allowance is shared
with ChatGPT and only Instant chat stays outside it, which would end Chat as the insurance for a spent allowance
(3-18, the operator's decision); a whole use has never been timed (3-16).

**The night of 2026-11-16 to 11-17 (§M-40; Server 0.84.0 and 0.84.1, glassdoc 0.44.3 to 0.44.5).** Built and seen working: the chooser shows whether answers can come (`経路 ○ 使用4%`, from `/v1/settings` and, when the kept check is over 30 minutes old, one `POST /v1/route-check`; seen on the glasses with the phone's server); the Codex CLI's check returns the share of its allowance used, read from the session record its one request leaves (4.0% of a week on the phone); `POST /v1/route-check?deep=1` sends one small real message through Chat (passed on the live page in 30.0 s; the phone's daily check does it, `ROKID_ROUTE_CHECK_DEEP=1`); a failed browser route leaves the structure of its page (`GET /v1/route-check/failures`). `scripts/scenario_suite.py` sends booklets of synthetic photos through the phone's product route and judges the answers: twelve of the thirteen it ran passed with no unmarked wrong answer (spreads near and far, single pages, a large sheet in parts, a part or a page left out and reported as missing, shuffled, sideways, an answer sheet beside, a hand, English, forty pages). What it found: (1) fourteen dark, noisy pages were not finished by the CLI in its 660 s (160 s without the noise). **Dark pages take the model several times longer; a real booklet of gathered dark pages has not been timed** (register 3-16). (2) Handed to Chat, that booklet stopped five times right before sending ("model selection menu is not usable"): on a slowly loading page the model control comes after the composer and it was read once. It is now waited for; the deep check passes with one file, a booklet of many files is unverified. (3) Every retry uploaded all files again: 70 of the window's 80 files went without one message sent. A set of files uploaded twice without a send is now not uploaded a third time (`ROKID_CHATGPT_UPLOAD_ROUNDS`, 0.84.1, unit tests). (4) Two reads of a mark sheet whose answer boxes are lettered (no answer numbers) did not line up at all: every item of both reads was shown and marked. They are now compared box by box (0.84.1; on the kept reads of forty pages, 100 items and one mark). 0.84.0 is on the phone; 0.84.1 is committed and unit-tested.

From Server 0.88.0 the model of the Codex CLI and Work is GPT-6.2 Sol (released 2026-11-17; the operator's decision of 2026-11-18, without a comparison; the CLI has to be 0.170.0 or newer), at High as before. Everything measured below was measured on GPT-6.1 Sol; how 6.2 Sol reads this system's pages is not measured.
Model and effort were GPT-6.1 Sol at High for the Codex CLI and Work (from Server 0.83.0, the operator's decision of
2026-11-16; they were at Extra High), and GPT-6 at Extra High for Chat. Outside sources
(`docs/model-effort-research-2026-11-16.md`, each claim with its source): reading barely moves with effort (MMMU-Pro
84.9% at high, 85.1% at xhigh; one reading harness equal at low and high), hard reasoning gains a few points at xhigh
(HLE-Diamond 51.9% to 55.8%) for 1.3 to 1.6 times the time and 1.5 times the reasoning tokens, and no other single
model is supported under the one-model rule. The CLI silently reduces any image over 6000 px a side or 10,000 patches
of 32 px (read in its source); the strips this route sends (about 517-690 x 2540) are under that. In-house, on this
system's own pages (§M-36, §M-37, §M-39): characters wrong, twelve reads each at the standard tier, on a dark gathered
page Extra High 3.1%, High 3.3%, Medium 4.8% (about 311 s, 150 s and 78 s a read), on a bright page Extra High 2.0%,
High 2.5%; what two reads both get wrong alike, which their comparison cannot flag, is the same at both (0.60% and
0.55% dark, 0.19% and 0.21% bright); High gave one read in twelve with about 6% wrong on each page, which the other
read contradicts. Hard written mathematics through the product route (Fast, two reads): 21 items of two 東大 papers came
back with the same results at High and at Extra High, in 154 s against 232 s and 378 s against 483 s; sameness is not
correctness (one item was checked by hand). Not compared at High: worn pages, horizontal text, English, figures; and
written answers are not compared between the two reads at any effort, since two writings of one solution differ.
Earlier: Work, 2026-11-09, twenty pages, once each, Extra High 556.6 s and High 339.6 s, both 13 of 13.

| Route | Status |
|---|---|
| `ROKID_SOLVER=chatgpt-web` | The existing Chat route drives the operator's own signed-in ChatGPT web session over CDP. A booklet is one JPEG per page and two per spread split at the fold. Each photo is first cropped to its paper and a margin when the paper box is certain (at least 15% of the frame, at most one frame side touched, unchanged when the brightness floor is lowered, at most 5% of the paper-like area outside the crop, and at most 65% of the frame kept); otherwise the whole frame is sent as before, and the stored original is never changed. On the 27 distinct real photos on this PC (2026-11-10, each crop looked at) 14 of the 16 whole spreads taken by glassdoc were cropped without losing paper, the 7 taken by the glasses' own camera app stayed whole, and the 4 frames whose box was wrong were sent whole. Before anything is attached, the file count is compared with what is left of a rolling 3-hour window (`ROKID_CHATGPT_UPLOAD_WINDOW_FILES`, default 80, the paid-plan figure read on help.openai.com on 2026-11-10). The window counts every file this server attached, including Work ZIPs and attempts that were never confirmed; uploads made elsewhere on the account are invisible to it. A booklet that does not fit is refused before any send, is not retried or moved to another route, and shows its count and the remaining room on the glasses. One set of files under one chat key is uploaded at most twice inside the window without a message sent with it (`ROKID_CHATGPT_UPLOAD_ROUNDS`, default 2; the attempts inside one try count, and Work's ZIPs go through the same check): the third upload does not start and the booklet ends there, not retried and not moved to another route, with a sentence of its own on the glasses, because on the phone on 2026-11-16 five tries that each failed before their send uploaded one 14-page booklet five times, 70 of the window's 80 files, and sent nothing (unit tests only; not seen on the live page). Sent its first booklet from the phone on 2026-11-14 (§M-19): two page images cut on the PC from one worn photo, one message, GPT-6 at Extra High, answered in 2 min 51 s. Until that day it could not attach, confirm an attachment, find the send control or see a reply on the live page (six fixes, each from reading that page); the reply was taken by the read-only recovery. The live wait ran for the first time on 2026-11-16 (§M-34) and failed twice before it worked: it counted a Stop button in a second composer of zero size as a reply being written (its limit is 150 minutes; fixed in 0.80.1 by asking for a drawn control), and the address the page shows right after a send (`/c/local-chatgpt%3A<id>`) was recorded as the chat's, so a restart could not return to it (fixed in 0.80.2). Then 14 rendered pages, taken over from the CLI at its real limit, were answered in 2 min 38 s with 14 of 14. A whole frame whose paper box is uncertain is still sent whole and shrunk by ChatGPT: the worn reference photo was neither cropped nor split. Attaching took 10-13 s for two 250 KB pages; the budget is now 20 s plus 15 s per file (`ROKID_CHATGPT_UPLOAD_PER_FILE_S`), from that one measurement on home Wi-Fi, or 16 s a megabyte when that is longer (`ROKID_CHATGPT_UPLOAD_PER_MB_S`, from 0.87.0: twelve pages gathered from clips are 29.3 MB and were not confirmed in 200 s, twice, on 2026-11-18; the phone's upload speed is unmeasured). |
| `ROKID_SOLVER=chatgpt-work` | The requested phone-local Work consumer sends unchanged image ZIPs, verifies source receipts and returns staged answers. PNG is the default; opt-in native JPEG sources bind explicit rotation and upright RGB evidence to the canonical PNG. Work PNG technical fixtures passed on the signed-in phone. The production model verifier confirmed Sol / Extra High / Fast and its owned-menu closure. Common SEND1 and restarted API/watcher readiness were checked while retaining the browser/X11; this activation sent no diagnostic material. JPEG delivery, full restart and venue acceptance remain unverified. Measured on this PC on 2026-11-10 with the 19 distinct glassdoc photos, processed as an upload is (rotation 270): the upright PNG is 2.41 times its JPEG (median 14.17 MB against 5.93 MB), so 40 photos are 575 MB in 20 ZIPs and 7 messages as PNG, and 238 MB in 8 ZIPs and 3 messages as JPEG. The default stays PNG: every JPEG needs the model to apply rotation 270 and return the upright-pixel hash, a rejected receipt does not switch routes, and no Work run has shown those receipts pass on real photos. That single run decides the default. |
| On-phone local model (F-51F, llama.cpp) | **Not the route.** The operator chose chatgpt-web on 2026-09-14. Its measurements are kept as evidence in `docs/hardware-measurements.md` §E; no further work is scheduled on it. |
| `openai` / `gemini` / `claude` API keys | Supported and config-only. The per-question routes can fall back through `ROKID_SOLVER_TIERS`. They have no one-message booklet answer, so they are not booklet fallback routes. |
| Booklet route fallback (`ROKID_SOLVER_FALLBACKS`) | Requested by the operator on 2026-11-10. When Work returns a usage limit, or cannot send (model or attachment control unusable after one retry), the same booklet goes to `chatgpt-web`. The choice is stored on the deck row, so a restart does not return to the limited route. An unknown send outcome, a shared browser/login/guard failure, a readability or receipt rejection and the listening stage never switch. Observed on the phone's live tab on 2026-11-10 without typing or sending: the new-chat page has two buttons, Chat and Work, and only pressing Chat leaves Work (a click right after the navigation was dropped, so it is repeated until Work is inactive); in Work mode Chat's composer is absent; Chat's effort is a five-position Power slider whose top position is Pro (shown with "Locked" and "Usage limit reached"), so the route moves it to the position labelled Extra High and refuses any other readable position. That preparation ended at GPT-6 / Extra High and Work was restored. Not observed: a limit notice on Work, a Work task cut short, and a Chat answer after a Work refusal (the CLI's real limit and Chat's answer after it were seen on 2026-11-16, §M-34). |
| Local OpenAI-compatible HTTP (`app/llm_http.py`) | Reaches an on-phone `llama-server` without the openai SDK. |
| `ROKID_SOLVER=codex-cli` (the official Codex CLI, `codex exec`, signed in with ChatGPT) | **The phone's route since 2026-11-14**, with Chat behind it. The operator asked whether the present route was rational for the venue; it had never been compared with anything (`docs/whole-review-2026-11-14.md` sections 9 and 10). One request carries every page image; no API key, browser or X11. On Android the server resolves names for the static binary through a loopback CONNECT proxy of its own and names Termux's certificate bundle. A reply is kept per booklet, so a repeat does not pay twice. A usage limit hands the booklet to Chat (Work draws on the same allowance and is closed with the CLI); a failed run, a run that does not finish in its time (a backstop of 45 minutes from 0.88.0, or 300 s plus 50 s a page where that is longer; it was 240 s plus 30 s a page, at least 600 s, twelve gathered pages of vertical Japanese ran that out on 2026-11-18, and no run on record ever hung) or a CLI that is signed out hands it to Work and then Chat (from 0.80.0). Seen at a real limit on 2026-11-16 (§M-34): the booklet moved to Chat and came back answered; with the operator's display at 0% the CLI had answered 14 pages just before. A booklet with audio is refused before anything runs. From 2026-11-15 one small request at low effort first asks where each photo's pages are and which way their lines run; each page is then cut out, enlarged to twice its size and sent in strips or bands along its lines (the paragraph below), and a booklet too large for the model's 500,000-token context is enlarged less. `POST /v1/route-check`, and a daily thread, try every booklet route (this one with a real request of about 5 s; Chat is only looked at) and `/v1/settings` carries the last result; from 0.84.0 the CLI's row carries the share of its allowance used, and `?deep=1` makes Chat send one small real message. Measured on the phone (§M-21 to §M-23): 47 rendered pages through the phone's own server, enlarged, answered 7 min 11 s after registration with 31 of 35 correct; 14 pages in 81 s with 14 of 14; two worn whole-frame photos with 4 of 4, and 3 of 4 with the fourth declared unreadable. Unmeasured: cellular, how long the sign-in lasts unattended, a reboot, how the plan allowance is drawn, photos taken by the app, worn photos of horizontal text. |

**The venue is far darker than every photo the reading was measured on.** The
wearer's own latest photos (2026-11-14 18:46, the glasses' camera) needed 60 ms
at ISO 4032-5688 and nothing in them can be read at native pixels; the reference
photos of 2026-09-22, used for §M-11, §M-22 and §M-23, were 25 ms at ISO 209, 46
to 65 times the light. At that darkness one frame cannot work however it is
exposed or processed: measured on the glasses' sensor with noise reduction off
(§M-24), level over noise is 2.2 for a 10 ms frame and 4.5 for 30 ms, it grows
with the square root of the frames added (11.8 for thirty of 10 ms), and the
model needs about 32 (2.5-3% of characters wrong; 5-36% at 16; nothing at 8).
That is 35 to 190 frames of 30 ms, one to six seconds of light a page. The camera
offers RAW, bursts and manual exposure, analog gain up to ISO 800, and a fixed
1.9 mm f/2.25 lens, so a narrower view adds no detail. Capturing the whole wide
frame as one still, the structure of every build so far, has to be replaced by
gathering frames of the looked-at paper. The operator approved the design on
2026-11-15 (`docs/superpowers/specs/2026-11-15-gathered-capture-design.md`): the
glasses record a few seconds of video a page, the phone selects, places and adds
the frames. Its stage 1 is done (§M-26, plan in `docs/superpowers/plans/`):
`app/gather.py` turns a clip into a page (`python -m app.gather clip.mp4 --out
page.png`; numpy, which the phone has from Termux's package, and ffmpeg), and on
the desk a 40-page cycle of watching and recording levelled the board near 46 C,
clips reached the phone at about 10 MB/s over the hotspot, and the phone gathered
a 5-second clip in 34-35 s, three at once in 39 s. A clip is the whole field and
its frame k is capture result k. Starting a recording takes 1.1-2.4 s (the
session rebuild); stopping it took 3-5.6 s in 7 of 40 until the camera was sent
back to watching first and the recorder stopped off its thread (0.7-1.2 s, 20 of
20, §M-27). **Stage 2, the first real page (2026-11-15, §M-27), failed the
design's first choice as built.** What the camera hands the hardware encoder is
already smoothed whatever is asked (noise reduction off, the camera's own
video-denoise keys, either codec, 57 or 140 Mbit/s: eight settings). A clip's
frame keeps almost none of the print's stroke-sized detail (0.02-0.03 of its
amplitude, §M-28) and a quarter of the noise that reducing alone leaves; 288
gathered frames cannot be read where the mean of 20 direct frames can. Encoders
themselves keep the print (x264/x265 on the PC). The same page showed that
`app/gather.py` dropped well-placed frames of regular print (the peak was judged
against the print's own repeats; fixed, floors re-measured) and that taking
full-size stills in a row ran the glasses out of memory and got the real app
killed and restarted. **Stage 2 continued the same evening (§M-28): the app
copies the camera's YUV frames into the hardware encoder itself** (measurement
app only; no frame dropped, a clip ends in 0.1-0.4 s, heat as the video path).
Read by the model twelve times a condition, the rule fixed before the runs, on
the page as placed and not moving: the mean of 60 direct full-size frames 1.6%
of characters wrong; the whole field recorded at half size 8.4% (fails), 32%
with one second of light, 40% at half the bit rate, 81% at 60 frames a second;
**the paper's own pixels, cut by the app out of the full-size stream and
recorded, 2.9% (passes).** That stream gives 21-24 frames a second, not 30, and
heats no more for a 1920x1080 part (4 C more for 2688x2016). Pictures that
looked readable to the eye, and a first measure that followed only where the
lines lie, both failed to tell what the model would read. The booklet's
characters (24 px apart) are 1.25 times the median of nine worn photos and 1.58
times the smallest; in those photos a spread spans 50-70% of the frame's width
and lies below its centre, and the camera crops at its centre only, so the app
has to find and cut the paper. Half size with a moving head, the form the
design counted on, was stood for by shifting and reducing the direct frames to
the smallest worn size: 60.7% through the glasses' encoder and 6.7% without it,
so that form is dropped (the 2.3% of §M-25 came from a bright photo with noise
added). At that size the paper's own pixels read 3.2% without an encoder and
3.9% through it at 1.24 bit (24 reads; 2.3 points over the direct frames, at the
limit of 2.0 and not a pass), 6.0% at 0.51 bit; and reducing also averaged the
noise, so those 60 frames stand for about 150 real ones (7 s of recording). The
farther the paper, the worse and the slower: the wearer needs a guide to
distance and the recording 0.66 bit a pixel a frame or more. (Not a safe guide for a real page further away: the frames that were reduced carried the blur of where they were taken; §M-42 as corrected by §M-44.) **The operator
approved the change of form on 2026-11-15 (night): record only the line-of-sight
frame, in the sensor's own pixels, cut by the app out of the full-size stream,
with a guide to distance; the whole field at half size and the camera's video
output are dropped.** Built in stage 3 (below). Measured after the approval, page after
page as the app would (§M-29): the full-size stream leaves 165-305 MB of memory
free while it records (1.8 GB device), and forty pages of it failed at the
ninth, the system killing the real app in the background on the way; **the
half-size stream at zoom 2, which is the centre of the field in the sensor's
own pixels (2016x1512), leaves 530 MB free and levelled the board near 45 C**,
so the frame becomes the centre of the field at single-page size and a spread no
longer fits one clip. After a spell of watching, a clip's brightness is steady
from its first frames (the first six at zoom 2). **The form is settled (§M-29, 2026-11-16): the half-size stream at zoom 2, manual
30 ms, digital gain at most 5.0, 95 Mbit/s (about 1.35 bit a pixel a frame), one
short clip a page (60 frames after the first six, about 40 MB).** In that shape
forty pages ran on the desk with no frame dropped, 1.14 s to the first frame,
0.61 s back to watching, the board level at 46-47 C and the real app left alone;
a page gathered from such a clip read 3.1% wrong against 2.0% for the direct
frames (twelve reads each). What the camera taught on the way, each from a
failure: (1) a session must be changed only after `stopRepeating()` and that
session's `onReady`; changed at once, frames in flight get no buffer and the
camera fails to drain (after 16 and after 28 pages); waiting also halves the time
to the first frame; (2) frames are taken on a thread other than the one that
changes sessions; on one thread a failed change left the camera service hung
until the glasses were restarted, on two it could be reopened; (3) above a
digital gain of about 5.5 this stream lifts its blacks (and the gain stops near
7): pages read 4.1-6.8% there; (4) giving a tone curve (`TONEMAP_MODE`) makes
the camera fail; (5) the glasses write about 9 MB a second: 95 Mbit/s for five
seconds a page could not be kept up for forty pages, three seconds could; at 50
Mbit/s the page read 5.7%; (6) the full-size stream with a single-page part ran
forty pages but took the board to 52.4 C. **Stage 3 is built and has passed the desk checks
(§M-30, 2026-11-16, from glassdoc 0.44.0); stills stay the default. The clip
route was worn once (stage 4, below).** `--es capture clip` (saved) makes a page of ordinary
written reading a clip: `ClipCamera` records it, one frame of it travels as the
page (`clip_frame`) through the flow every photo takes, the clip follows it
(`POST /v1/documents/{id}/pages/{index}/clip`) and worker threads on the phone
gather it into the page's image; a page whose clip could not be gathered stays
that one frame and is named in the answers. More frames do not help a dark scene:
half the desk's light at 30 ms and a gain of 5.0 read 6.6% wrong with four times
the frames. Where 30 ms would need a gain over 7.05 (`--ei long_above`, saved) the
clip therefore takes 60 ms at 15 frames a second, the first 15 frames left out,
half the bit rate; that read 3.0% with the paper as bright as in the clip that
passed, and the venue's own light is still unread. From 0.44.1 the long exposure
is taken only once a gain is saved (`--ei long_above N`; 0 turns it off): worn,
hardly a frame is still at 60 ms (below). On the desk: the whole route
with the stand-in solver (38 of 38 lines, also with 60 ms forced); the real app
with the phone's own server (43-44 lines without failure, pause and resume
included); forty pages at fifteen seconds a page on that route, every clip whole,
sent, and gathered on the phone (22.6 s a clip, keeping pace). Three more things
the camera taught, each from a failure: (7) the frame-rate range is one of its
session keys: a session created without session parameters is configured a second
time by its first request, behind a wait for idle that ran out once in eleven
clips (camera error 4), so a session is created from a `SessionConfiguration`
carrying the request it will repeat; (8) the watch preview's frames too are taken
on the frames' thread: on the camera's thread, which opens the clip's file and the
codec, they were not returned for over a second once in about eighty clips and the
camera never drained; (9) writing a clip's 36 MB out stalls the whole system on
memory and storage for seconds (a page's review image came up to 5.6 s late in
about one page in three, the camera's thread stood 2.6 s once): the camera
survives it, the wearer waits. Neither failure showed in three runs of three
pages; both needed tens of clips on the route that sends. A camera that reports
an error or cannot make a session is closed and opened again and the page looked
for again; three in a row with no page between end the capture. A clip's exposure
is matched to the preview's only once that has settled (at most 1.5 s of waiting).
An independent read of the code after all the desk checks had passed found a page
silently left out of a booklet ended while its clips were still being sent, and
three smaller faults; all four are fixed, the first reproduced in a test. Heat on the desk
at fifteen seconds a page: board 49.5 C with stills, 51 C with clips not sent,
55-56.5 C with clips sent (36 MB a page); how that feels worn is unknown. The
Codex route never reduced a page, so more than about twenty gathered pages
(3024x4032 each) would have gone out over the model's context; it now brings all
pages to the largest common long side that fits, only when the booklet does not
fit unreduced (unit tests only; a reduced page's reading is unmeasured). Not done:
figures, horizontal text, the real model through the product route, a worn page
read against a known text. **Stage 4, the first worn pass (2026-11-16, §M-31:
three minutes, the test package and the stand-in server, ten clips, all gathered
again on the PC afterwards).** As built it failed: of seven pages four were
gathered, from half their still frames, and three clips at 60 ms had no still
frame at all. Distance was not the cause (characters 19-22.5 px apart, 24 on the
desk that passed) and the glasses did not feel hot. A worn head does what the
desk never showed. It moves the picture 46-301 px between runs of 13-38 still
frames (four frames in ten are under 2 px of smear at 30 ms; 6 and 1 of some 133
at 60 ms), where a frame was looked for within 16 px of the last one added:
every frame is now placed against the frame before it and the moves are added
up. And it tilts and sees the page from another side: against a move of 44 px
the edges lay another 15-19 px off, so a page added at one shift was sharp in
its middle and double at its edges, however many frames it had taken. One shift
left 11.4 px (rms over 25 pieces), a plane 1.7, a homography 0.6; following such
a map from frame to frame through the smeared frames failed (5-19 px off), and
finding it against the page, coarse to fine, held (0.0-0.5 px inside the paper).
A frame further than 8 px from the clip's first is therefore laid on the page by
a homography of its own, pixel by pixel into the nearest cell (`app/gather.py`,
Server APP 0.78.0), and a frame that no single shift places (a head that came
back from further away) is tried by a map from where the picture was followed
to. A clip of glasses lying still takes the old path and gathers to the same
page bit for bit (twelve desk clips). The ten worn clips then gave 60, 41, 60,
61, 61, 49, 6, 5, 28 and 1 frames, and page 4 can be read by eye to its edges.
A page laid this way shows about 0.67 of the old level over noise for the same
light (22 where 32): do not compare it with the 32 above. Read by the model three times each, with no known text for that page: the
old gathering of page 4 came back with 58-69% of its characters marked unreadable
(two reads 18.9% apart, and 70% from the new page's reads; until 2026-11-17 this
said "not one character marked": the count missed the full-width mark); the new
page's reads lie 10.4% apart, which the same measure on desk reads with a known
text (3.0% apart at 2.0% wrong, 3.9 at 3.1, 6.3 at 6.6) puts at roughly 7-10%
wrong: readable, not at the bar. Of its 61 frames 45 carry 1-2 px of smear (a
desk clip has none); which smear limit reads best can be settled on a recorded
page with a known text.
Found on the way: a frame during whose exposure no gyroscope reading had
arrived was written as 0 px of smear and counted as the stillest (8 of 296
frames; 999 and not counted from glassdoc 0.44.1). On the phone a worn clip is
gathered in 50-63 s alone and 24 s each three at once, against a page every
18 s when worn: beyond about 25 pages the last ones would not be gathered within
the 150 s the booklet waited then (200 s from 0.87.0; open; six at once was no faster and left 1.7 GB of
memory). The wear sensor read "far" while worn and the capture did not start
by itself; the wearer could not tell the distance from the far mark. The phone's server
now runs 0.78.1 (the gathering from 0.78.0) and the glasses 0.44.1 (both packages), and the desk checks
passed again (whole route 38 of 38; the real app with the phone's server 44 of
44 on clips and 38 of 38 on stills): none of it worn.
Unmeasured: a worn page read against a known text (the one page with a known
text was recorded with the head moving throughout), the venue's darkness worn
(30 ms is too dark there and 60 ms is not still). **Worn a second time the same
evening (§M-33, ten pages from the first problem page, glassdoc 0.44.1):** the
record now holds the gyroscope's readings, and they show why pages fail. On the
first three pages the head turned at 0.12-0.145 rad/s (7-8 px in 30 ms) and 5
to 8 frames of 290 were still; on the pages that were gathered it turned at
0.04-0.05 rad/s and four frames in ten were. The page with the known text was
again one of the restless ones. The route asks the wearer to hold still for
some seconds a page and does not tell them so (register 2-25). A tap did not
clear the display: it only books a pause for after the page in hand, which is
up to 13 s on this route, and the taps that followed were taken as the double
tap that ends the capture (register 1-16; fixed in glassdoc 0.44.2 and checked on the desk, §M-35; not worn). I had asked the wearer not
to touch the touchpad: the worn check had left out how the thing is used. **From glassdoc 0.44.3 to 0.44.5 (§M-40; on a desk, not worn):** while a clip is recorded a bar on the top edge of the small window fills as still frames count and stands still while the head moves (seen filling in screen captures); a clip that ends with fewer than 40 of its 60 frames keeps that bar over its page's review (the rule was right on all 17 worn clips offline; a desk cannot show it); the "paper too far" mark is off unless `--ef far_share` is saved, and no distance mark is built: a frame's character pitch can be measured (16 strips, 100% of 698 frames within 10%), but a 20 px limit would be on for 58% of the wearer's time and a 16 px limit never, and no record says where reading fails. On the still route, in the dark, a step of the preview's own exposure (60 ms watching, 30 ms preparing a photo) was counted as a page turn and an unmoving scene was photographed again and again; the reference is now brought to the frame's exposure first (register 2-29; 38 of 38 on the dark desk).

**The operator's trial of 2026-11-17 and what its records took back (§M-44).** The operator reproduced the venue and ran
three papers printed on large sheets (two columns or two faces a sheet): twelve booklets, 35 recorded pages, the real app,
the phone's server, the Codex CLI. The whole use worked in their hands ("easy to use, except the capture"). Mathematics B,
each sheet taken whole, did not fit in its 50 minutes (seven attempts, at most 22 of 39 items answered); Japanese, each sheet
taken whole, was read only where the print is large (the kanji page); mathematics A, taken one face at a time, was read
except at the top and the sides of each capture, and a retake of the missed problems came back as bare values, because the
instruction to leave the working stood on the other face. What the records show: every frame of a clip is as soft as the
next (76 frames, the picture moving 0 to 3 px a frame), so it is neither motion nor the laying; the clip's stream is the
sensor's own pixels (its noise is as fine as a full-size frame's); **the blur belongs to the place in the frame**: edges of
print are 3.8-4.5 px wide in the middle and lower part, 5.0-5.8 at the left, 6.1-8.5 in the top fifth, which is the far end
of the paper and so cannot be defocus by nearness. **"Too near" was not the cause** (the paragraph below and §M-42, §M-43 keep
their measurements; their conclusion about distance is withdrawn): a nearer page spreads into the edge of the frame, and the
morning's unreadable clips show the edge's blur. Pages whose characters came out largest (about 25 px) read best; 20-22 px
and 13 px did not. Estimated, not measured: the lens's opening is 0.84 mm and its focus is fixed far away, so the blur on the
paper hardly changes with distance and small print loses. **Taking the blur back out of the gathered page (a Wiener filter
against a disc of 8 page px) looks crisper and reads far worse** (a known text, the rule fixed before the reads: 89.2% to
48.1%, 80.9% to 56.3%, 24.6% to 0.0%, 63.8% to 36.1%): not adopted, the second time a step after gathering made reading
worse. **Built:** Server 0.85.0 (an answer reached by calculation or reasoning gives its result and then its working on
lines that begin with 式：, with or without an instruction in view and although a box is printed for the result; the answer
boxes of one question stand under their printed names in that question's one item; soft print is read with its context
before a question is given up; two reads are compared by the result before the working, without regard to case) and glassdoc
0.44.8 (a bar outside each side of the small window past which the paper runs out of the camera's view; the "too near" frame
is gone, the line distance is only logged). **Seen:** the same pages sent again through a staged copy of the server on the
phone: the retake's seven problems with their working (checked by hand), mathematics A 29 of 33 with no item split in two,
mathematics B 14 of 21 with the boxes named, Japanese 28 of 44 with 16 still unreadable; the whole-use check on the desk
38 of 38; the lower bar on the glasses' own screen. **Not seen:** any of it worn; a large sheet taken in parts and read;
the upper and side bars on the device. A large sheet is to be taken a part at a time, about a B5 page a capture, what is
read in the middle of the window, the print large; how small print may be is not measured (register 2-33 to 2-35).
**Why the wearer has to back off (§M-44 (11); the operator said it on 11/14, 11/16 and 11/17).** The clip's frame is the
middle half of the field (43 by 56 degrees). In the wearer's own whole-field photos (twenty, 9/22 and 11/14) a paper looked
at from a seat spans 73-100% of the field's width and 64-92% of its height, and the frame holds 27-47% of its area; moved
down a quarter of the field it holds less. To fit the paper the wearer backs off to about twice the distance and the print
halves. No way of holding the glasses solves that. The whole field in the sensor's own pixels could not be recorded (memory
and heat, §M-29); the still route takes it in one photo.
**The still route worn (2026-11-17 21:21, §M-44 (14); the real app 0.44.11, the phone's server).** Two things failed. (1) The capture stopped after every photo and could not be ended. A worn head's own motion is counted as pages turned (261 page changes in about five minutes; none in 15 s on a desk as dark). Only the still camera watched for a next page during the three-second review, each review therefore ended as a "missed page", automatic capture stopped behind a prompt written when a tap still took a photo, and that state refused the double tap. glassdoc 0.44.12: the still camera watches no page during a review (`GlassCamera.supportsFuturePages()` is false, as the clip camera's always was), and a reading that still carries the mark is freed of it when loaded. Unit tests and the desk checks only: a desk cannot make a page change during a review. The counting itself is unchanged, so looking on at one paper takes it again (register 2-38; the clip route counts the same way). (2) The five photos were not read. The room was near the darkness of 11/14 (30 ms needed a total gain of 5800-7100; the morning's clips had ISO 800 times 1.0-1.56). The paper lay well inside the field (about 75% of its width), characters of 18-20 px, and the camera's noise reduction had flattened their strokes; the model (Standard, two reads, once) returned all five pages as unreadable. A whole-field still at the morning's light is not measured. The gate for stillness behaved as replayed beforehand from the morning's gyroscope records (photos 1.8-4.0 s after the request, two waits of ten seconds ran out; `data/gather-stage2/scripts/still_gate_1118.py`). The real app's saved capture mode is clip again. What is left for a large sheet is the clip route a face at a time; whether clips are read at that night's light is not measured (register 2-36 to 2-39, 4-16).
**The morning read again, and the structure (2026-11-17 night, §M-44 (15)).** The operator's point: a fault they find is already a failure; latent ones they cannot find, so they have to be found beforehand. Until then I had read the records of a use only where the operator's report pointed. Read whole and in the order of use (the phone's log of the glasses' states, the watcher's log, the database, the 35 clips; the glasses' own log had been lost to a reboot before I pulled it), the morning held: the first three booklets went out as pages gathered from 4 to 46 still frames of about 293 (the clip ran to its ten seconds, the page was saved all the same, the answers were 0, 7 and 0; register 2-40, open); one clip was "not placed" because the paper was moved while it was recorded and the page was put where the first frames lay (the gyroscope saw no turn; the still count is the gyroscope's alone; 2-41); 27 of one clip's 58 still frames were refused at an area limit by a hair (2-42, open); 113 frames of one clip were lost while the clip before, 156 MB, was being sent (2-43, open); one booklet was ended 51 s in, closed twice during the wait and its answers never seen, by register 3-1, listed as unfixed since 11/13; printed sub-question numbers "(1)" were cut from 5 to 21 labels a booklet of mathematics (3-33). Five read-only audits (texts against gestures, capture dead ends under worn inputs, the chain after the end, the server's booklet route, what the checks cannot produce) returned about eighty findings; several were named by two or three of them independently. **Fixed, each with a test seen to fail first** (Server 0.85.1, glassdoc 0.44.13): a double tap with no page saved no longer leaves a dead capture; a reading closed during the wait stays under 中断した読取 (marked 答え待ち) until its answers are saved on the glasses; a review is never shown without its three seconds after a retake that did not start, a return from a pause or a late guide; a guide drawn late no longer stops automatic capture; a reading taken up at a page under review goes on taking pages; a retake after the end keeps the end; the end is acknowledged at once (終了待ち) while a page is being taken; the texts name today's gestures and an error names the way out; a clip begun on another view is gathered where its still frames are (`begun_again` in `app/gather.py`: the failed clip gives 57 frames, the other 34 of the morning are unchanged to the frame); a printed "(1)" stays in the label; a Codex reply that cannot be used hands the booklet to the next route. **On the devices since 23:15, seen on the desk:** the whole-use check on stills 28 of 28; the real app with the phone's server 44 of 44 on its second run (the first was void: the light before the glasses changed and they were moved, and a clip of 296 frames with 2 still ones was saved as a page, 2-40 again); a reading closed during the wait listed as 答え待ち, taken up, its answers shown, then gone from the list; a double tap with no page not taken as the end; the morning's labels with their "(1)" on the phone. Not worn; the fixes that need an input a desk cannot make rest on unit tests. **Open and serious:** 2-40; two double taps on the waiting screen close the app (1-25); a wear-sensor crossing returns to the chooser from any phase (1-26); an abandoned booklet keeps being solved (3-35); routes that wait without end (3-36). The checks cannot make a worn head's inputs; what they cannot make is listed and four ways to make it without a wearer are proposed, none built (4-17). (As of that night. In the night that followed, below: 2-40, 1-25 and 1-26 were fixed, 3-35 and 3-36 for the most part, and three of the four ways were built.)
**The night of 2026-11-17 to 11-18 (§M-44 (16); Server 0.86.1, glassdoc 0.44.15).** The operator: remove what the phone and the PC no longer need; fix and improve everything found. Removed: 56.33 GB on the phone, 24.31 GB on the PC; the measurements' originals stay. **Fixed, each with a test seen to fail first:** a clip that runs out its ten seconds with fewer than two thirds of its still frames is recorded again, the third in a row is kept, a clip the wearer cut is the page (2-40); after the end no gesture reaches the capture, and a double tap within five seconds of the end is that end, not a step towards leaving the app (1-25, 1-27); a wear-sensor crossing changes nothing while a reading is in hand (1-26); five dead ends of the still camera and the end, and the hand-over of the booklet retried when the connection drops; six faults of the Codex route (a locating request that does not come back goes to the next route; a read that hangs behind a finished one is ended after that read's time again, two minutes at least; a usage limit is taken from the CLI's own sentence or an error line; unnumbered questions named differently by the two reads are compared in order) and one item behind the answers when one read of two answered alone (照合なし); eight dead ends of the booklet routes (Work behind the CLI that cannot take a booklet hands it to Chat at once; a start resumes the session the glasses are on, not every booklet of three hours); the gathering takes the booklet in hand first, and clips are removed three days after they were gathered, failed ones after a week (`app/retention.py`). **`CaptureInvariantsTest`** drives the real controller with random gestures, camera answers, display reports and passing time and checks six invariants after every step: it found four dead ends at once and two more with 3000 sequences, one of them made by my own fix of the first; all fixed, 3000 sequences find nothing. **Found by the forty-page desk run, not by three pages:** one clip in forty lost its second and third frames between the encoder and the file (the encoder's statistics said all were done; the cause is not known), the frames behind them could not be decoded, and the page went out as whole. The glasses now compare the frames the encoder took with the frames the file holds and record such a clip again; the server sends the decoder's complaints to a file (read from a pipe only at the end they stalled it for 30 s on Windows) and refuses a clip that does not decode to every frame its file holds, where it would have gathered the rest out of step with the record. **Not a defect after all (2-42):** the area limit of a frame's map stays 0.8 to 1.25; widened, the 27 refused frames were added and lay 12 px off the page at one edge, which a count (33 to 60 frames) and level over noise (39.0 to 47.5) had hidden. **Measured, not built (2-38):** no whole-thumbnail measure tells "the same page after the head moved" from another sheet; a block-wise one does on the morning's clips, with no margin; the app never compares the settled picture with the page it took. **glassdoc 0.44.16 adds a shadow log and changes no decision:** when a settled page asks for a recording, the watch picture is compared block by block with the one the page taken last was asked with, and one line of numbers is written (`same_page score= blocks= since_ms=`), so that one worn pass shows whether the measure of 2-38 holds on the watch picture; the line was seen on the glasses (in a dark room: no blocks). Forty pages with 0.44.16 in that dark room: every clip whole on the glasses (no frame dropped, first frame after 1288 ms on average), none gathered, as nothing was to be seen; the real app with the phone's server 42 of 44, the two lines being the gathering in the dark. The gathering with 0.44.16 in light is not checked. **Seen on the desk:** the whole-use check on stills 28 of 28 and on clips 38 of 38, three times in a row. Forty pages on clips: with 0.44.14 one clip of forty was not gathered (the lost frames above); with 0.44.15 149 of 149, every clip whole and gathered. The loss did not recur, so the glasses' new check has not been seen at work. Eight clips of about 127 MB in a row (`--clip-frames 250`): over USB no frame dropped and all gathered; over the phone's hotspot no frame dropped either, but one clip's first frame came after 4.1 s where the others took 1.1 s. The loss of 113 frames (2-43) was not reproduced. Not worn; what a desk cannot make (short clips, a wear crossing, the repeated double tap, the route changes) rests on unit tests. **Open:** the operator's question of 2026-11-18: from December the allowance is shared by ChatGPT and Codex, so Chat no longer insures a spent allowance; the routes' order then guards only against other failures. A booklet costs about 0.25% of the weekly allowance; the limit of 11/16 was spent by my measurement reads. Asked: reserve management with credits bought beforehand, or reserve management alone. **The operator's decision (2026-11-18): they will see that it does not run out; no insurance outside the allowance is wanted** (register 3-18). The routes' order stays as insurance against other failures, and my measurement reads must not spend the allowance. Replayed against the morning's worn records, the rule of 0.44.14 would have recorded 8 of the 35 clips again (4 to 38 still frames in ten seconds; both pages of two booklets of the restless first three).
**The operator's three subjects of 2026-11-18 (§M-44 (17); glassdoc 0.44.17, Server 0.87.0).** Before them, 06:10 to 06:45, one worn pass with the test package: automatic capture never fired in 221 s of watching. The 32x24 grid a page change is judged on was one pixel of each cell, and in a dim room (gain 4 to 5) pixel noise alone made 6 to 11 "changes" a second; glassdoc 0.44.17 judges on the mean of each cell (unit test and a replay over the clips; the real app's desk check was never run). Then the operator ran three subjects in venue conditions (the real app 0.44.17, the phone's server 0.86.1, the Codex CLI). The glasses' log was lost to a reboot at 12:08 before I pulled it; what follows is from the phone's records. Two subjects were answered (8 pages 267 s after the booklet was finalized, 12 pages 191 s). **The third gave nothing, twice.** First: twelve gathered pages of vertical Japanese took a read over ten minutes, the CLI gave the booklet up at 600 s, and both routes behind it, running on the live pages for the first time, failed: Work's inventory for a new job read the tab as it stood, on the conversation of the daily check's Chat message, where there is no Work entry; Chat uploaded the twelve pages (29.3 MB as JPEG) twice without confirming them in the 200 s their count allowed. A failure on the glasses 22 minutes after the end. Second: the answers were saved at 12:00:01 from one read, and the glasses had stopped answering the phone at 11:59:37 (cause not known). The day before I had written that five such pages took 481 s against the 600 s limit, and changed nothing. What else the records showed: a word bank's printed labels run 10, 12, 13 (a sheet marked one digit at a time; a hypothesis from the page's pixels, to be confirmed by the wearer), both reads counted along the row and agreed on 11, so twelve answers were wrong and unmarked; the boxes of one question were compared only while all of them together fit 24 characters; paper running out of the frame at the bottom, five items lost to it; an English sentence quoted in Japanese; a mark sheet at a capture's edge listed five times as missing; a twelfth clip gathered 165 s after the end against a wait of 150 s. **Server 0.87.0, each change with a test seen to fail first:** the CLI may take 300 s and 50 s a page, 900 s at least, and a read behind a finished one waits 240 s at most; Work's inventory leaves a conversation for the new-chat page first; Chat's attach budget grows with the files' size (16 s a megabyte) and an upload not confirmed logs how many files were showing; the gathering is waited for 200 s; a choice is named by its printed label, never by counting, with the words of a short option after it; a quotation keeps its printed language; an answer sheet in view is not missing material; boxes are compared line by line, a choice by its label whatever words follow, a note names the boxes that differ, and a circled label of two digits always asks to be checked on the paper. **One read of the first subject again through a staged copy on the phone (Standard, 476 s):** the two reads agreed on the words of every option and differed on every two-digit label. Soft two-digit labels are not read, with any prompt tried; the words let the wearer find the option. **On the phone since 16:26; none of it seen in use.** Not fixed: paper that does not fit or runs out of the frame, the overlap between parts of a large sheet, why the glasses stopped answering.
**The evening of 2026-11-18 (§M-44 (18); Server 0.88.0, glassdoc 0.44.18).** The operator: never again let them find a defect; the process has to be faster; the second booklet of the morning was not lost to the glasses, they closed them when the test's time ran out. And: what is a strict time limit for, why is the capture still blurred, is this design for many pages, and GPT-6.2 should have been known. **Where the time went (the phone's records):** capture 105 to 263 s (15 to 18 s a page), from the last page to the last clip gathered 91 to 174 s, the model 191 to 635 s. A clip is gathered 55 to 168 s after it arrives and the lag grows through a booklet: alone on the phone a clip of 60 frames takes 38.3 s (decoding 4.4 s of it) and clips arrive every 15 s. **Changed, each with a test seen to fail first:** the answers go out when the first of the two reads is back, with one item 照合中 behind them, and the compared answers follow over the same questions as a newer revision the glasses take where the wearer is reading (glassdoc 0.44.18 is needed: an older one refuses the revision and is notified every five seconds); the Codex route's limit is a backstop of 45 minutes, because no run on record ever hung and the two ended as hung were slow ones with nothing behind them that answers sooner; a read behind a finished one waits fifteen minutes at most; parts of a question the reads name differently ("(1)（Ⅰ）" against "（Ⅰ）") are paired between questions both name, where they had come out twice (47 items for some 34 questions). **GPT-6.2 Sol** was released for Codex and Work on 2026-11-17 and I had not looked; the phone's CLI 0.169.0 did not know it. The operator: use it, no comparison. CLI 0.170.0 (the old package is kept), the default model of the CLI and Work is gpt-6.2-sol, the phone's stale Work settings (6.1 at xhigh, fixed in its environment file since before 2026-11-16) are 6.2 at high. The twelve pages of vertical Japanese that ran out the old limit: both reads back in 514.7 s and 545.8 s (staged copy on the phone, Fast, once), 37 items with 34 answered where the morning's one read had 21 of 33; a read still takes eight and a half minutes. **The routes behind the CLI, run on the live pages:** Chat's failure of the morning was reproduced and was not the files' size: the product renames a file the account holds many times to `name(YYYYMMDD-HHMMSS).ext`, the matcher knew only `name(N).ext`, and twelve uploaded pages were counted as ten. Fixed, the message was sent, and after about an hour of "Thinking" the product showed "Message delivery timed out" and no reply; the route took that for a send of unknown outcome, would have waited 150 minutes and left the mark that blocks every later browser send. That notice is now a known failure. Work's first step passed on the live page (GPT-6.2 Sol, high, fast, 2.4 s) after one more fault found there (a single press on a page still mounting); its send has never run. **Neither Chat nor Work answers such a booklet inside a test's time: the CLI is the only route that does.** **Seen on the devices:** the whole-use check 38 of 38, and 40 of 40 with the stand-in standing for two reads (`ROKID_RECORDED_REPLY_2`; the screen showed the first answer and then, on the same page, the mark with the other read's answer); the real app with the phone's server 42 of 42 (capture not ended). `scripts/replay_booklet.py` replays a booklet a wearer recorded through a server as the glasses sent it (four replays on the PC, all PASS; not yet on the phone). **Corrected:** I told the operator a single still would do at that day's light; from the numbers in hand it would not (60 frames gave 1.5 to 3 times the level needed, so 8 to 27 frames, not one). **The gathering is faster and gives the same pages** (the same night): the arrays that place a frame are kept for the clip instead of made anew for every step. Identical output on 22 worn clips on the PC and 4 on the phone; alone on the phone a clip of 60 frames takes 25.3 s where it took 38.3. Replayed on the phone's staged server at the recorded pace, the morning's twelve-page booklet had its clips gathered 32 to 65 s after they arrived where it was 49 to 142 s, and the lag no longer grows through the booklet; the wait at the end was 32 s where it was 53. **A booklet is read in three parts at the same time on the phone** (`ROKID_CODEX_PARTS=3` in its environment file; the code's default is 1, a whole read): each part's request carries every image and answers only the questions that begin on its own pages, and the parts are joined into one read before anything else sees them. One run each with the real model: the twelve pages of Japanese had their first read back in 253 s where it took 515, the eight pages of world history took 169 s in all where the morning took 267, the twelve pages of English were as fast as before; on the two booklets with printed answer numbers both reads in parts filled exactly the numbers the whole reads had (79 and 77), with no duplicate at a boundary. Replayed end to end on the phone's staged server with the real model, the eight-page booklet had its first read's answers 128 s after it was finalized and the compared ones 29 s later: about 300 s from the first page, where the morning took 506. One run a booklet: the size of the gain is a guide, and six requests at once have not met a rate limit in three runs. **Not done:** ending a read that really stalls; Work's send; a still against a clip in bright light; fewer frames in bright light; paper that does not fit the frame.
**Old readings on the glasses (§M-44 (12), (13); glassdoc 0.44.11).** The app never removed a finished reading's folder and
kept every reading left unfinished with its unsent clips: 1.4 GB. At each start it now clears finished readings and ones left
unfinished for over a day; the one in hand stays. The first build of this (0.44.10) killed the real app as it started: the
chooser sorted the folders by their time while they were being emptied. The desk check had passed on a package whose store
I had just cleared.

**The camera does not focus where the pages were held (2026-11-17, §M-41, §M-42; its conclusion about distance is withdrawn, see above).** The third worn pass (the real app,
the phone's server, the real model) ran the whole use for the first time: ten pages, eight of them with all 60 still
frames, answers on the glasses five minutes after the capture ended; and every answer said it could not be read. The
camera's own description (`dumpsys media.camera`, read whole on the PC): fixed focus, 1.9 mm, f/2.25, hyperfocal
distance 0.80 m, pixels of 1.0 um (1900 px a radian). It is sharp from 0.40 m; nearer, the blur disc is 1.7 px across
at 0.43 m, 3.4 at 0.30 m and 3.9 at 0.27 m. That night's pages and the desk bench on which every gathered page had been
read (lines 48 px apart, characters of 24-26 px) both stood 27-32 cm away; the wearer's photos of September that were
read (characters of 15.8 px) were taken from 43-50 cm, the spread in the middle of the field, seen from almost straight
above. Worn, one page filled the recorded frame and was seen at a slant (characters 79-85% as tall as wide): its middle
reads like the desk page, its near, far and left parts are blurred. The same part of the same print, twelve reads each:
the desk page 4.8% of characters wrong, the worn page 63.7%, most of it marked unreadable by the model itself (43-67% of a read's characters; 0.6-5.2% on
the desk page).
Flattening the page's light and taking the blur back did not help (53-71%) and made the desk page worse (8.3%): not
adopted. Ruled out by measurement: the laying (six free numbers a frame at full size gave the same page), warmth (board
31 to 52 C: no more blur), the camera's processing in the dark, frames blended in the camera (neighbours' fine noise is
not shared), smear under 2 px. The measure of §M-41's analysis counts the sensor's fixed pattern as detail in a clip
that does not move, so its desk figures are 10-30% too high and "the desk 0.27 against worn 0.15" overstates the gap.
The distance was then tried worn (2026-11-17, §M-43; the test package and the stand-in server): fifteen clips of
that page, lines of print 39 to 50 px apart. The camera cannot be focused: one camera, `afAvailableModes [0]`. Of a
known text, twelve reads each found 0.1% and 1.7% at 44 and 50 px (90-96% of the characters marked unreadable), and
80.9%, 24.6% and 63.8% at 39, 41 and 42 px (the desk page: 92.2%). The page's own detail in fourteen clips: 0.18-0.28
at 41.6 px and under, 0.11-0.16 at 44.3 px and over. So 42-44 px is where reading stops; under it the clips still
differ, and neither their line distance, nor how their frames were laid, nor the gyroscope's smear says why (register
2-32). Flattening the page's light was tried on those sharper pages too and is not adopted (+6, +3, 0 points; the
desk page -3). The small window had never shown distance: its picture is cut to the paper, so a page looks the same
size from anywhere, and "fill half the window" could not be done. glassdoc 0.44.7 showed a thick frame around the
small window while the lines of print lay more than 42 px of the frame apart (`PrintPitch` on the watch picture's
middle 128x128 px; within 0.7 px of the full frame's figure on 25 worn clips). **That mark was taken out in 0.44.8:** the
two unreadable clips had the blur of the frame's edge, and the operator's trial of the same day read best where the print
was largest (§M-44). `PrintPitch` still measures and the figure is logged (`watch_status lines=`); nothing is shown from it.
What it rests on, measured on the desk and the PC on 2026-11-15 (§M-25):
the 2016x1512 stream is the whole field at half size and the only whole-field
size at 60 frames a second; streaming it heats the glasses by 17.7 C in 150 s
with no work done and 24.9 C with one Java pass over each frame, which alone
takes 22.5 ms; the hardware encoder is refused beside the YUV preview and
accepted alone or beside a small display-format stream, and recording 2400x1800
at 30 a second heats by 15.7 C; video compression keeps what adding needs
(software encoders on the PC, 0.985 at 40 Mbit/s; that is true of encoders and
not of the glasses' video output, see above); textbook phase correlation cannot place frames this noisy and a
band-passed correlation against the running sum can; half-size frames read as
well as full-size ones only when added on a finer grid (simulated, six reads
each: 2.3% against 3.3%, and 21.2% without the finer grid; with real dark
frames shifted to stand for a moving head it was 6.7% against 3.2%, §M-28).
Placing on a worn head was unmeasured then: worn, one shift a frame did not
hold and a frame is laid by a map (stage 4, above). The paragraph below holds
for bright photos only.

What a page needs to be read, measured on the phone with worn photos of one page
from the glasses' own camera (§M-22, §M-23). One input read twice differs by up
to 6.5 points of 199 characters: only repeated reads count, and two conclusions
drawn from single reads on 2026-11-15 were wrong. Characters of 15.8 px were
read with 18% wrong as photographed (one read) and, at twice the size, with
4.10% as one image and 1.59% as two strips cut along the lines (six reads each,
the rule fixed before the runs); cut across the lines it was no better than one
image, and larger or sharpened no better. Wrong characters come back as other
plausible words, not as gaps. Pixel count is not the limit: a sharp photo
reduced to 8 px a character was still read with 2% wrong. Blur and smear are:
a smear of 10% of a character's height cost nothing, 20% doubled the errors and
the time, 30% broke the answers and 44% left nothing readable (one read each),
as two of the seven worn photos were. No simple image measure told those two
from the rest; the model returns such a page as unreadable by itself. The Codex
route therefore sends each page at twice its size in parts along its lines
(implemented 2026-11-15). On a second photo (17 px) that cut read worse than one
larger image, three reads against two; that is open. The route also reads each
booklet twice at the same time and compares the two answer lists answer number
by answer number (`ROKID_CODEX_READS`, 2): a short answer the reads disagree on,
or that only one gave, keeps an answer and is shown for review with the other
one; writing is not compared. Through the phone's server: 24 answers from worn
whole-frame photos with no unnoticed wrong answer (one wrong and four right
ones marked); 35 answers of 47 rendered pages, run twice, each with one
unnoticed (three or four read once) and two wrong ones marked, and three and
no right ones marked; the wait is the slower read's (365.8 s and 586.1 s for
the 47 pages), at twice the allowance. Both reads wrong alike stays unnoticed. Not implemented: more than
one photo a page and choosing by the gyroscope.

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
component measurements. The glasses → phone AP → answer-bundle route ran once
on 2026-11-13 through Work with one photo of a desk (§M-15). A wearer's paper
capture, a booklet of several pages, a correct answer from a photo the app itself
took, the
capture/power behavior over a whole session and the model's use of original
listening audio remain unvalidated on hardware. Do not describe chatgpt-web as
venue-ready.

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
A trial with the real model goes through Chat, not Work ("Development and
verification" below), so the Standard setting matters only when Work itself is
what is being tried.

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
  The still is full-size YUV taken beside the running preview after fresh
  supported focus/exposure and stillness checks, copied, closed and then
  encoded to JPEG (quality 98) off the camera thread (glassdoc 0.43.13,
  2026-11-12, `docs/hardware-measurements.md` §M-5). From 0.43.23 the
  full-size output is in the session only while a photo is prepared and taken,
  and the preview that merely watches for a page runs at 15 frames a second:
  held all along at 30, the full-size output took the board from 38.5 to 62.2 C
  in three minutes on a desk and the frame handler from 21 to 9 frames a
  second; now the same three minutes take it from 37.7 to 43.8 C with 10-11
  frames handled steadily (§M-18). Ten minutes on the desk with a photo every 20 s (31 stills, 62 rebuilds) levelled off near 48 C on the board, with no spurious page change, no error and no restart of the camera services. The session is rebuilt on the same
  open camera, about 0.45 s each way, and nothing of the session being replaced
  counts meanwhile; from a detected page to its photo is about 2 s. A still
  0.3 s after the rebuilt preview restarted read the same as one from a
  session held all along, while the camera's own JPEG on a session of its own
  read a third of it (10.5 against 33.3 where the glasses' own camera read
  39.7), so that path is not a way to save heat. Comparison launches keep the
  full-size output throughout. That JPEG carries no EXIF; its provenance stays
  `native_still`. On
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
  without preview after each still; the YUV path about half a second at each
  rebuild. Which noise
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
  total gain of at most 1600 (leaving it needs more than entering), else 30
  wherever the camera has that range, however dark. Until 0.43.20 a scene
  needing a gain over 6400 at 30 ms fell back to the template's 50-60 ms, where
  the stillness limit is 0.02 rad/s and a worn head never passed; smear cannot
  be undone and noise can be averaged out. On the desk of 2026-11-14 (60 ms at
  3320 by the glasses' own camera) the app took 30 ms at a gain of about 6600
  and read 35.5-37.4 against that camera's 42.6-44.1 (§M-17). Above a total gain
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
- During capture a bar stands outside each side of the small window past which the paper
  runs out of the camera's view, and beside the review of the page taken that way (glassdoc
  0.44.8, §M-44): what is printed beyond that side is not in the picture. It assumes a desk
  darker than the paper; with no edge of paper in view it stands on all four sides. The lower
  bar was seen on the device; the others and worn use were not.
- With `--es capture clip` saved, ordinary written reading takes each page as a
  short clip instead (`ClipCamera`, from glassdoc 0.44.0; the paragraph on the
  venue's light above and §M-30). Stills are the default until a worn page has
  been read (worn once, §M-31). On that route a double tap during a recording ends that clip at
  once and what it has is the page (on the glasses: 36 frames, the capture ended
  with that one double tap); a tap ends the clip at once, what it has is the page, and that page waits unsaved for the return (0.44.2; until then
  the tap let the clip finish and saved the page before pausing). Pages turned to during a recording or its review are
  not kept. From 0.44.14 a clip that runs out its ten seconds with fewer than two thirds of its still frames is
  deleted and recorded again (the third in a row is kept; a clip the wearer cut is the page), and from 0.44.15 a
  clip whose file holds fewer frames than the encoder took is a failed capture: deleted, the camera opened again
  (one desk clip of forty had lost two frames, §M-44 (16)). The booklet is finalized only when no page and no clip is unsent: a
  page saved while clips were on their way was once left out (found by review,
  not by the desk checks).
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
  visible acknowledgement starts a fresh 3000ms review. From glassdoc 0.44.12 no
  page is watched for during a review on the glasses: a page turned to meanwhile
  is found when the review is over. Until then the still camera kept at most two
  future-page originals and marked a page it saw and could not take as a gap; worn,
  a head's own motion made every review end in a gap that stopped the capture and
  refused its end (§M-44 (14)). The controller's code for that watching and its
  tests stay; no camera of the glasses reaches it, and a reading that still carries
  a gap is freed of it when loaded. Unknown captures and failed persistence still
  survive restart. A forward swipe retakes, no input commits, BACK ends
  capture after the last review. Hidden or stale views cannot commit; the one exception, from 0.44.14, is a still
  whose review picture cannot be made at all (it does not decode): it gets its three seconds without a view and is
  then saved, where it used to stand for good. A waiting
  forward swipe first waits for the native stop barrier and promotes any saved
  candidate before requesting a manual shot. A tap pauses at once (glassdoc 0.44.2): the display clears in the turn of the tap and the camera stops. A still
  already asked for lands first and a clip being recorded ends there; either page is held unsaved, and on the next tap
  it gets its own fresh three-second review and is then saved. Behind a cleared display a double tap only brings the
  display back; it ends the capture only while the capture is showing. The same page is not taken again on return, and
  a page whose clip had no frame yet is looked for again. Until 0.44.1 the tap only booked the pause for after the
  page in hand, up to 13 s away on the clip route: worn on 2026-11-16 the display stayed on and the follow-up taps
  ended the capture (register 1-16). Checked on the glasses lying on a desk (§M-35): the still route's 38 lines, five
  pauses on the clip route at different moments, the whole use in order. Not worn yet. One photo remains in flight at most. This
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
- What the reader draws (glassdoc 0.44.3 to 0.44.5, Server 0.84.0; §M-40): the answer typeface is monospace, whose fallback
  chain has the script digits and the superscript n and no script sign or other script letter (`scripts/glasses_font_coverage.py`
  reads the fonts' own tables; run it again after a firmware update). The server writes anything else out as `^(...)` or
  `_(...)`; a figure's labels are not covered. Before a figure only the labels the figure shows as numbers are listed. A line
  does not break inside a bracketed group when the formula can start the next line, and no line begins with a closing mark.
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
  capture/review/reading hold the app window on. The chooser stays ten
  seconds (the operator, worn, 2026-11-17, from glassdoc 0.44.6; it was thirty from 2026-11-13, when at five it was
  gone before a wearer could choose). Recording-only, uploading, analysis and other waiting
  sleep after five seconds without user input; network refreshes do not extend that timer. Authenticated phone-watcher
  requests handle sleep/wake. Sleep uses Android's soft-sleep key so the window's
  current screen wake lock is checked when a delayed request reaches the device.
  Old persistent generations cannot release or reacquire the current window's
  display hold. Ordinary chooser updates are not app-entry requests.
  Confirmed wear requests use a fresh persistent generation and an explicit
  chooser entry, explicit wake and no old answer-wake extras. From glassdoc 0.44.14 a confirmed wear changes nothing
  while a reading is in hand (capturing, analyzing, waiting, reading) on a living screen of the app; the first
  wear after the glasses started and a phase left behind by a screen that is gone open the chooser as before. Never restore
  a saved timeout over a later operator choice. For a serial-verified, previously
  running app, a fresh explicit sleep request precedes fold/process diagnostics;
  cold-start and prior in-flight work can still delay delivery. A saved-answer
  hardware trial retained display and cursor through the12.297-second observation
  after SOFT_SLEEP (`GL48-saved-reader-display-hold-20261031.py
  --execute-approved-once`, exit0; independently audited). The operator also
  confirmed that the answer stays visible and readable. On 2026-11-09, when
  the chooser's timeout was still five seconds (thirty from 0.43.18, ten from 0.44.6), the
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
- A recorded page (`clip_frame`) keeps its clip beside it. The gathered image
  takes the place of the page's PNG only while the booklet still takes pages and
  only for the capture the page holds; finalization waits for the clips at most
  `ROKID_GATHER_WAIT_S` (200 s; the glasses' finalize call reads for 240 s); a page left ungathered is named in the answers,
  never dropped. Clips are kept on the phone (about 36 MB a page, 70-146 MB worn) for three
  days after they were gathered, failed ones for a week (`app/retention.py`, at a start and after each finalize;
  rows stay). A clip that does not decode to every frame its file holds is refused with that reason (0.86.1). A frame that lies away from the clip's first is laid
  on the page by a map of its own; a clip of glasses lying still must keep
  gathering to the same page (§M-31).
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
- The repository is public. A prompt, a test or a record never carries a paper's own text, options or answers:
  examples are made up, and what was read from a paper stays in untracked `data/`. On 2026-11-18 a prompt example
  and three tests used the day's paper; it was caught before the push, and the same example had spoilt one box
  of the read that was to check the prompt.
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

### Order of verification on hardware

This list is the rule. The paragraphs after it are the reasons and the
records; each was learned from a failure the operator found.

1. Place the work in the flow first. `docs/defect-register.md` opens with the
   purpose and where each step of the use stands. A remark from the operator
   is one observation of that flow, not a new goal: the goal and the step in
   hand do not change because of it.
2. Characterise before building: the glasses' own camera for exposure and
   processing, the recorded head motion (`scripts/head_motion_report.py`) for
   stillness, the project's records for what is already known. The camera's own
   description comes first (`dumpsys media.camera`, saved whole on the PC: focal
   length, aperture, hyperfocal distance, pixel size): the desk bench stood inside
   the lens's blur for two days because it was not read (§M-42).
3. After every change to the glasses app, on the desk: compile the installed
   package; `glasses_device_check.py`; gestures through the touchpad's input device,
   every cycle three times; `system_observation.py` before and after a change
   to capture or display; `e2e_route_check.py` with the stand-in solver for
   the whole use in order. Both take `--capture clip`. A change to a camera,
   or to what runs beside it, is run for forty pages on the route that sends,
   not three: on 2026-11-16 two camera failures came once in eleven and once
   in about eighty clips (§M-30). A change that touches what the app keeps on the glasses is checked on the
   real app's own store as well (old readings in it), started several times: on 2026-11-17 a clearing of old
   readings passed the whole-use check on a package whose store had just been emptied and killed the real app
   at its next start (§M-44 (13)). A change to the capture controller is run through `CaptureInvariantsTest` once with 3000
   sequences (its 300 did not reach a dead end my own fix had made, 2026-11-18), and the log pulled after a desk
   run through `scripts/capture_log_invariants.py`. `e2e_route_check.py --clip-frames 250` makes the ten-second
   clips a worn head makes. A change to how a booklet is answered is run through
   `scripts/scenario_suite.py` (synthetic photos, the phone's product route, the real model) for paper other than a
   plain spread; its photos are flat and still, so it stands for no worn page.
4. Put the desk bench where the use is: the distance and the angle a wearer has
   (September's photos: 43-50 cm, from above), not where the print looks large.
   Say what the desk cannot show. Glasses on a desk look across the room and
   do not move; on 2026-11-14 that view was about thirty times darker than the
   page a wearer photographed on 9/22. Look at what the camera sees (a photo
   with the glasses' own camera) before reading a desk number as a condition
   of use. The light on a page a wearer looks at and the motion of a
   reading head exist only when worn. A stand-in for them tests the stand-in:
   until 2026-11-16 a moving head was stood for by shifting the picture, the
   gathering passed every desk check, and worn it placed four pages of seven,
   because a head also tilts and sees the page from another side (§M-31). And
   a count is not the picture: with the frames followed, 60 of 60 were added
   and the page was double at its edges. Look at the page at its own pixels.
   And one thing moved in a trial is a correlation until what moved with it is
   told apart: on 2026-11-17 "too near" went to the operator as the cause and
   into a mark in the morning, and their own trial took it back in the afternoon;
   a nearer page had also spread into the frame's edge, where the blur is (§M-44).
   No step on the image is adopted by eye: the deblurring that looked crisper
   halved what the model read.
5. An item whose state is "the operator's decision" is put to them as a question, with its options and a
   recommendation, in the same report; nothing more is built on the premise it questions until it is answered
   (register 3-18 sat for two days, 2026-11-16 to 11-18).
   After every use by the operator, the same hour: pull the glasses' log (a reboot loses it) and read every record of
   that use in the order it was used (`data/gather-stage2/scripts/morning_timeline_1118.py` is the form): frames used a
   clip, failed gatherings, dropped frames, the order of states, what was never read. The operator's report is one
   reading of it. On 2026-11-17 the morning's records held seven faults nobody had reported, one of them a register
   item marked unfixed for four days (§M-44 (15)). An open register item on the path of a use that is about to happen
   is fixed or told to the operator before that use. When work starts on a day, the models in use are checked
   against the vendor's announcements and the CLI's own model list (`codex --version`; on 2026-11-18 GPT-6.2 had
   been out a day and the operator had to point it out), and what can be said with a number in hand is said
   only after the number is worked out. A number I recorded as near a limit is fixed that day, and a
   fallback that has never run on the live page is not counted as one: on 2026-11-18 a limit noted the day before
   as thin ran out and the two routes behind it, both "not observed", both failed (§M-44 (17)).
   A route that has not been worn in its present form is worn first with the test package and the stand-in server
   (`e2e_route_check.py --paper`), where nothing reaches the model and a capture that cannot be ended harms nothing.
   On 2026-11-17 the operator was moved to the still route on the real app after desk checks alone and landed in a
   capture that stopped after every photo and could not be ended (§M-44 (14)). What only a worn head produces (page
   changes during a review) is read in the code before the switch.
   When the wearer is needed, say so plainly: what they do, for how long,
   what the one pass decides, and what was checked first so that it cannot
   fail for a reason findable on the desk. Not before that, and not silently
   never. A worn pass is the use in order, operated by the wearer (choose,
   capture, tap to clear the display and back, end, read, finish): on
   2026-11-16 two passes asked for "pages only, do not touch the touchpad",
   and the tap that does not clear the display was found by the wearer
   outside the check (§M-33). What to photograph is asked in the wearer's
   terms ("from the first problem page"), not by a printed page number.
6. A run with the real model is the operator's decision: once, through Chat,
   under the conditions below.
7. A rule or measurement added to this file or to another record is added by
   reading the whole document again and correcting, in the same change, what
   it has made stale.

What is known about worn capture (2026-11-14): one attempt, 37 seconds on
glassdoc 0.43.14 with the preview at 50-60 ms, where the stillness limit was
0.02 rad/s, took no photo (§M-7); in September, at 10 ms and 0.12 rad/s, worn
photos were taken. The exposure rules since (0.43.15, 0.43.16) have never been
worn, and neither a worn head's turning speed nor the light on a worn page had
been recorded. From 0.43.21 the app records the gyroscope at 200 Hz for as
long as its camera is open (a trace named head-motion.bin in the app's
external files directory, which adb can read; the build is not debuggable;
read by `scripts/head_motion_report.py`) and logs, for each photo, the turning during
its own exposure (`still_motion`); neither changes a decision. The stillness
gate itself is unchanged: it allows a photo after 300 ms in which every
reading is under 0.12 rad/s x 10 ms / exposure, then stops listening, and the
exposure comes 0.3-0.7 s later. The clip route was worn on 2026-11-16 (§M-31,
the paragraph on the venue's light above). Its camera does not write the
head-motion trace, and the ten worn clips' records hold each frame's time and
smear only; from glassdoc 0.44.1 a clip's record also keeps the gyroscope's
readings taken while it was recorded (`gyro`: time and the turn about three
axes, about 202 a second). The ten worn clips and their records are kept on
this PC, untracked (`data/gather-stage2/worn1/clips`), and can be gathered
again; `app.gather` logs each frame's fate at debug level.

After any change to the glasses app, and before the wearer is asked to try it,
run `py -3.12 scripts/glasses_device_check.py --glasses <serial> --phone <serial>`.
After each install run `cmd package compile -m speed -f <package>` on the
glasses; the check fails an uncompiled app, which is slower and hotter. It
writes gestures to the touchpad's own input device (from 2026-11-14; its
injected keys had drifted from the app and started mixed English, where a tap
takes a photo) and reads the chooser's marker from the screen, because the
chooser opens on the kind of reading used last. It checks, line by
line, the environment, the chooser, the automatic photo and its exposure, that
an unmoving scene is not taken again, pause and resume, the manual shot and
what reached the phone server. The PC reaches the glasses without a cable
through the phone: `scripts/glasses_over_phone.py start --phone <transport>`
runs a relay on the phone and prints an adb transport of the glasses (this PC,
the phone on the home network, the glasses on the phone's hotspot), which
every script takes as `--glasses`; `adb reverse` works over it. Use it by
default: a cable is not part of the use, and on 2026-11-14 a worn recording
was asked for over USB and could not be done. A worn recording is taken with
`scripts/e2e_route_check.py --paper <seconds>` over that transport; it waits
for the wear sensor before it counts (a first attempt recorded two minutes of
a desk): the test-only package and the
stand-in server, the real app force-stopped, the capture never ended, so
nothing can reach the model whatever the wearer touches; it reports the light,
the head's turning and every photo, and keeps the head-motion trace. The unit tests use a fake camera and display: from
2026-11-01 to 2026-11-12 they hid a frame handler 300 times slower on the
device, a still the firmware never returned, one page taken again and again,
and a photo too dark to read. Glasses lying on a desk look across the room, not
at a page; a page's legibility and page turns need the wearer.

The glasses' own camera is the reference for exposure and processing. Over adb
`input keyevent KEYCODE_SPRITE_FUNCTION` takes one photo with it into
`/sdcard/DCIM/Camera` without stopping the foreground app; the photo stays in
the glasses' gallery (`--no-reference` on both check scripts takes none). Before a change to
exposure, gain or still processing is handed to the wearer, take the same scene
both ways seconds apart and compare brightness and noise; `:glassprobe`
`--es camera_variant` takes `fps=`, `scene=` and `ev=` (and, for streams and
clips, `still=WxH`, `stream=<s>`, `record=<s>`, `pages=<n>`, `iso=`, `boost=`) for the camera's own
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
2026-11-13 (§M-13, glassdoc 0.43.17, before the heat was dealt with in 0.43.23):
ten minutes of capture took the SoC from 39 to 74 C and the camera zone to
73.5 C, still rising, with the preview handled at 9-11 frames a second after
the first 30 s; the phone's watcher sends three adb commands a loop
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

A real run with the model spends the operator's usage and is decided by the
operator, not by the agent. On 2026-11-13 the agent first carried "GPT sends: 0"
as a blanket premise (an instruction about repeated model comparisons, widened
without thought), and then, told that this made no sense, swung the other way
and ran the real route at once: a Work task on a photo of the desk, not a
problem page, while capture was known to be broken (§M-15). The operator called
that waste: such a run is not to be repeated and was not to be done then; Fast
is production's setting and is waste in a trial, and Work is costly too.
Before proposing a real run, all of these hold: capture has passed the desk
checks against the glasses' own camera; a real problem page is in view; the
question the run answers is written down and cannot be answered by a cheaper
means (the stand-in solver, the standard camera, the PC); it is one run at
Standard speed, with the route and effort named. Then ask, once, and wait.
The stand-in solver (`ROKID_SOLVER=recorded`) carries every other route check.

Which route costs what was already in the record and was not consulted before
that run. Work shares one allowance with Codex ("ChatGPT Work usage inside
ChatGPT uses the same pricing, credits, and usage limits as Codex"; Plus: an
estimated 15-160 messages per five hours for GPT-6.1 Sol, weekly limits may
apply; Fast uses 2.5 times the included usage; learn.chatgpt.com/codex/pricing,
read again 2026-11-13). Ordinary chat is outside that allowance; in Chat the
Pro position has its own allowance and the others are GPT-6 Sol
(`docs/requirements-audit.md`, 2026-11-12). The operator's point: a trial with
the real model goes through Chat (`ROKID_SOLVER=chatgpt-web`), which does not
draw on the Work allowance; its own limit is the upload window (80 files per
three hours). The Chat booklet route sent its first booklet from the phone on
2026-11-14 (§M-19) after six fixes found on the live page; the switch from Work
into it has still never run. A page whose questions need a passage on another
page comes back `needs_input`, as the prompt requires: a trial that is to judge
answers needs pages that can be answered from what is sent. The phone's solver
setting is changed on the phone; since 2026-11-14 it is `codex-cli`.

## Versioning

Update `APP_VERSION` for every release. Update `API_VERSION` when HTTP schemas
or behavior change, and update `GLASSES_VIEW_CONTRACT_VERSION` when HUD or
capture semantics change. Keep README examples and tests aligned with those
constants.

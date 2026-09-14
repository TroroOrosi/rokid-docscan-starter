# rokid-docscan-starter development guide

Status: Current engineering contract. Updated 2026-09-14.

## What this repository is

Photograph an exam booklet (共通テスト and similar), and let the operator read,
per 小問, **what to write on the answer sheet** on Rokid Glasses.

The scan-and-match half (`/v1/match`, pHash, page dedup) is the foundation this
was built on, not the goal. Do not describe it as the product.

The intended session, from `tasks/plan.md`:

- Normal: 20-40 pages, ~10 min capture, ~10 min analysis, ~130 min review.
- Listening: ~10 min capture inside a 30 min recording, ~10 min analysis,
  ~110 min review.
- Glasses have no Wi-Fi; the phone is on 4G/5G and may be locked. **No PC, no
  self-hosted server, and no tethering at the venue.** Nothing auto-terminates
  at 150 minutes.

Two cooperating runtimes:

- `app/`: the FastAPI document-analysis and answer server.
- `android-relay/`: the Android-phone relay for Global Hi Rokid and Rokid
  Glasses, plus the glasses-side apps.

The supported real-device topology is:

```text
Rokid Glasses -> Global Hi Rokid -> Android relay -> FastAPI server -> HUD
```

## Answer routes

| Route | Status |
|---|---|
| `ROKID_SOLVER=chatgpt-web` | **Current primary.** Drives the operator's own signed-in ChatGPT web session over CDP. |
| On-phone local model (F-51F, llama.cpp) | **Not the route.** The operator chose chatgpt-web on 2026-09-14. Its measurements are kept as evidence in `docs/hardware-measurements.md` §E; no further work is scheduled on it. |
| `openai` / `gemini` / `claude` API keys | Supported and config-only. Kept as a fallback tier via `ROKID_SOLVER_TIERS`. |
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

**Open gap.** Every chatgpt-web measurement so far ran against Chrome on a PC
(Chrome/152.0.7977.83, 2026-09-13). That is not the venue topology. The venue
requires no PC, so the route has to reach a phone-side browser instead;
`ROKID_CHATGPT_CDP` accepts any CDP endpoint, so nothing in the design blocks
it, but **this has never been run**. Do not describe chatgpt-web as venue-ready.

Chrome for Android does not hand out a CDP endpoint the way a PC does, and the
difference is not a configuration detail. It listens only on a unix
abstract-namespace socket, never on TCP, and it authorizes the connecting
process by peer UID: `root`, `shell`, or its own. A phone-side app is neither,
and SELinux gives each app its own MCS categories on top of that. The route
therefore needs an on-device `adb forward` (adbd runs as `shell`) to turn that
socket into `127.0.0.1:9222`. Measured, with the source and device evidence, in
`docs/hardware-measurements.md` §F.

A throttled account is refused in the message *body*, not by an exception. The
solver's rate-limit markers and slow-generation brake exist because a retry loop
read a refusal as a bad answer and turned one block into many on 2026-09-14.

## Real-device contract

- Photographing the physical page is the primary input path. The relay calls
  CXR-L `takePhoto`, receives the JPEG, performs bundled Japanese ML Kit OCR,
  and uploads both JPEG and OCR.
- Text-only page upload remains an API compatibility path. Do not describe it
  as the real-device primary path.
- The public CXR-L AIDL surface does not expose arbitrary recognition or
  answer text from the AI running on the glasses. The current production path
  therefore uses the phone OCR and a configured server analyzer/solver.
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

A real-device acceptance run must physically confirm:

1. the LED is lit while `takePhoto` is active;
2. it turns off after the image callback; and
3. it remains off during analysis and answer review.

The indicator is observed with an independent camera. An SDK callback records
application state and never proves physical light state. Shutter sound, flash,
and capture indicators are device-controlled unless a documented public SDK
control is added. Do not claim silent or no-flash capture without physical
verification on the exact firmware.

An earlier branch explored changing the indicator from a diagnostic shell. It
is quarantined: `app/devtools/rokid_led.py` and `scripts/rokid_led.py` are stubs
with no device commands, `tests/test_rokid_led.py` enforces that, and the
procedures are deliberately not kept anywhere in this repository.

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
  image. The relay upload may be a JPEG, but the raw upload bytes are not
  persisted. Never claim raw JPEG is persisted when it is not.
- A configured cloud analyzer may transcribe/correct OCR and describe diagrams
  from the image. Finalization must fail clearly if a photo has no usable text
  and no image-capable analyzer is configured.
- Persist analyzer-derived text before segmenting problems.
- Pass the originating page image to image-capable solvers.
- Keep document finalization idempotent and page replacement keyed by
  `(document_id, page_index)`.
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

- Enumerate devices read-only first and name the serial in every command. Stop
  on multiple devices, signature mismatch, version downgrade, unknown callback
  state, or a missing external-video setup.
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
py -3.12 -m pytest -q
py -3.12 -m ruff check .
```

`python` on this machine is 3.14 and has no pytest. Use `py -3.12`.

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

## Versioning

Update `APP_VERSION` for every release. Update `API_VERSION` when HTTP schemas
or behavior change, and update `GLASSES_VIEW_CONTRACT_VERSION` when HUD or
capture semantics change. Keep README examples and tests aligned with those
constants.

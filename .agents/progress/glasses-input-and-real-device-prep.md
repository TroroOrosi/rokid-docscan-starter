# Glasses input + real-device preparation

> **Status (2026-09-01): historical progress plus current checkpoint.** The
> 2026-08-29 narrative below records hypotheses and earlier decisions; it is
> not an operating guide. The final section, current runbooks under `docs/`,
> and `CAPABILITY-MAP-safe-real-device-readiness.md` supersede conflicting
> claims. Privacy-indicator bypass is not implemented or tested.

Updated 2026-08-29. Branch `agent/real-device-test-prep`, HEAD `482ad3f`,
1 commit ahead of `origin` at the time of writing (`3eb64ce` and earlier are
pushed).

## Objective

Make the Rokid Glasses usable as the operator's control surface for page
capture, and finish the preparation a real-device acceptance run needs.

**Non-goals.** The privacy-LED question is the user's to decide on hardware; the
working tree carries their uncommitted doc edits that delete the "never
disable/bypass/hide/misrepresent" rule. Do not act on them, do not commit them,
do not re-open the argument. Every commit below was staged hunk-by-hunk to keep
them out; grep the staged diff for the LED tamper rule and expect no hits.

## The finding that changes the plan

**A glasses-native app is supported, and this repo never used the API.**
Verified by `javap` over the AARs, present in **both** `client-l:1.0.1` (the
long-standing pin) and `1.1.1`, on
`com.rokid.sprite.aiapp.externalapp.IMediaStreamService`:

```java
void uploadAndInstallApk(String pkg, ParcelFileDescriptor apk, IGlassAppCallback cb)
void openApp(String pkg, String activity, IGlassAppCallback cb)
void uninstallApp(String pkg, IGlassAppCallback cb)
void stopApp(String pkg, IGlassAppCallback cb)
void queryGlassAppInstalled(String pkg, IGlassAppCallback cb)
```

1.1.1 also has `SessionType{CUSTOM_VIEW, CUSTOM_APP}` and a `SessionConfig`
carrying `glassesApkPath`, `glassesPackageName`, `glassesActivityName`.
YodaOS-Sprite is Android 12, so the glasses run ordinary APKs.

Every constraint recorded in `CLAUDE.md` and `docs/` — CUSTOMVIEW is the only
output, the phone owns the UI, YodaOS reserves the gestures so a third-party app
cannot receive them — describes life *inside a CUSTOMVIEW overlay*. It is not a
platform limit. **Those documents are not a trustworthy source for what the
platform can do; the AAR is.**

## Measured on hardware (F-51F, Hi Rokid G1.12.10.0815, CXR-L service 1.0.0 code 10000)

- **Operator taps produce no callback at all.** Over a 17-minute session: 18
  `AI-exit`, of which 15 were echoes of our own view pushes and the rest were
  minutes away from any tap; 4 closes scored `userInitiated=true`, of which 3
  were the glasses dismissing the view on a timer at **29.7 / 30.1 / 30.1 s**.
  Nothing lines up with a tap.
- `userInitiated=true` is `CustomViewCloseTracker`'s own verdict ("not a close we
  issued"). It does **not** mean the operator. Reading it as the tap fired the
  shutter on the 30s timer and registered a page nobody asked for (`d206f7d`,
  reverted by `1a2e74c`).
- CXR-L 1.1.1 changed nothing observable here: the service still reports
  `1.0.0 (code 10000)` and `onInterruptAiWake` never fired.

## Completed and verified

| Commit | What | Evidence |
|---|---|---|
| `de27b09` | Sweep ladder now `DEFAULT → 1920x1080 q95 → 4032x3024 q80`; the disproved `q50` probe is gone and a test forbids buying resolution with quality | 24 classes / 153 tests |
| `87adee6` | `/v1/settings` reports the selected analyzer/solver and whether it can actually run; the adapters fail open to the offline placeholder in silence | 447 passed, ruff clean; API 1.13.1 → 1.14.0 |
| `9aa1def` | Phone screen shows `Rokid DocScan Relay <version> (build <code>)` | confirmed on device via `uiautomator dump` |
| `dc6b40a` | Menu-exit recovery no longer re-arms on the echo of its own restore | **user confirmed the blinking stopped** |
| `149d579` | CXR-L 1.0.1 → 1.1.1 plus the 5 callback methods 1.1.x added | 156 tests; resolved to `client-l:1.1.1` |
| `1a2e74c` | Reverts the AIMING close-as-input mistake; a refused close now arms recovery | 159 tests; **user confirmed the view is re-presented again** |
| `3eb64ce` | Checkpoints the glasses-input work; stops `CLAUDE.md` overstating the platform | docs only |
| `482ad3f` | Phase 0 probe: `GlassAppProbe` + `RokidGlobalLink.probeGlassApp` + a phone button with an editable package | 26 classes / 171 tests; APK `0.3.14` / code 19 assembled. **No firmware has answered the call** |

Relay on the phone: **0.3.13 / versionCode 18**. `pending-capture-v1.bin`
(149,406 bytes, 2026-08-28 02:49) survived every reinstall.

### Phase 0 ran on hardware, 2026-08-29 — the API answers

F-51F, Android 16, relay `0.3.14` / code 19 installed 07:26. Hi Rokid bound and
the glasses live: `Hi Rokid service connected=true CXR-L 1.0.0 (code 10000)`,
`custom view opened on glasses`.

| Probed package | On phone | On glasses | Verdict | Latency |
|---|---|---|---|---|
| `com.android.settings` | yes | expected yes | `ANSWERED installed=true` | 195 ms |
| `dev.rokid.definitely.absentd.settings` (nonsense) | no | no | `ANSWERED installed=false` | 173 ms |
| `dev.rokid.docscanrelay` (**discriminator**) | **yes, running** | no | `ANSWERED installed=false` | 269 ms |

**`queryGlassAppInstalled` is implemented on this firmware, it discriminates,
and it queries the glasses — not the phone.** Neither `CALL_FAILED` nor
`NO_RESPONSE` ever occurred. Phase 0's stop condition did not trigger.

The third row settles it. The relay was the foreground process making the call
(pid 22668) and is unquestionably installed on the phone, yet the answer was
`false`. A phone-local `PackageManager` lookup could not return that. So the
first row is a real statement about the glasses: YodaOS-Sprite carries
`com.android.settings`, consistent with it being Android 12.

Latency corroborates: 173–269 ms throughout, far above a local lookup (~1 ms)
and about right for a round trip to the glasses.

**The glasses-app route is open.** Every documented claim that it was not
described life inside a CUSTOMVIEW overlay and was never a platform limit.

### How Phase 0 was driven

`adb` over wireless debugging is unreliable here — the transport dropped between
almost every invocation. What worked: `adb connect <ip>:<port>` and the real
work in **one** shell invocation, re-connecting each time. The phone advertised
`192.168.0.30:33991` and `:41709` over mDNS; only `33991` ever connected, and
`adb connect` printing `failed connect` while `adb devices` shows `device` is
normal — trust `adb devices`. A 57 MB `install -r` failed once mid-transfer with
an empty error and succeeded on retry.

Driving the UI: the button is at `[600,1426][1155,1561]`, the package field at
`[45,1427][600,1560]`. A tap with the IME open hits the keyboard, not the
button, and produces no log at all — dismiss it with `input keyevent 111` first.
`input keyevent 67` (DEL) in a loop does **not** reliably clear the field;
`input keycombination 113 29` (Ctrl+A) then one DEL does.

### Phase 0, as built

`GlassAppProbe` keeps the timeout verdict provisional on purpose: Hi Rokid can
refuse the transaction (`CALL_FAILED`), or accept it and never call back
(`NO_RESPONSE` after 5 s), and a callback arriving later still resolves to
`ANSWERED`. Only `ANSWERED` answers Phase 0's question; `installed` is
secondary. The probed package is an on-screen `EditText` so another package
costs a button press rather than a rebuild and a fresh Hi Rokid authorization,
and it defaults to `com.android.settings` — YodaOS-Sprite is Android 12, so a
`true` there means the query really reached the glasses rather than being
answered locally.

Read the verdict on the phone log line or with
`adb logcat -s DocScanRokid | grep glass-app-probe`.

## Environment

- Build only from the ASCII worktree `C:\Users\Public\rokid-docscan-build`
  (synced to `9df5b09` + working copies); `JAVA_HOME` = Android Studio `jbr`.
- `gradlew.bat` wraps a PowerShell script: do **not** pass `-p`, and the project
  dir comes from the script's own location.
- adb reaches the phone over mDNS. `adb mdns services` can print nothing while
  the device is reachable — issuing any `adb connect` makes the daemon resolve
  it. Export `MSYS_NO_PATHCONV=1` before any `adb shell` path like `/sdcard/x`.
- Server: started with `py -3.12 -m uvicorn app.main:app --host 0.0.0.0 --port
  8000` after `unset OPENAI_BASE_URL ANTHROPIC_BASE_URL`. It was **down** for
  the first half of the session, which is why the relay logged
  `Failed to connect to /192.168.0.32:8000` and nothing downstream happened.
- **No `.env` and no provider API key.** `/v1/settings` reports
  `analyzer: {name: "local", offline: true}`. Real analysis is not configured.

## Next steps, in order

1. ~~**Phase 0**~~ — **done 2026-08-29.** The API is implemented, it
   discriminates, and it queries the glasses. Nothing here is blocking any more.
2. **Phase 1 — a minimal glasses APK**: **built 2026-08-29, never run on
   hardware.** See "Phase 1, as built" below for the procedure and for how to
   read each failure. Remember the phone's Wi-Fi must be on for Hi Rokid to join
   the glasses hotspot during install.
3. **Phase 2** — if taps arrive, move capture/HUD/input ownership to the glasses
   app and leave the phone as network + OCR relay.
4. Unrelated and still open: the operator has to create `.env` with a real
   provider key before any acceptance run, and the three-shot parameter sweep
   (`docs/capture-timing-findings.md` §5) has never been run.

## Phase 1 ran on hardware 2026-08-29 — the install is refused

F-51F, relay `0.3.15` / code 20 installed 22:13. Hi Rokid reconnected without a
fresh authorization: `Hi Rokid service connected=true CXR-L 1.0.0 (code 10000)`,
`custom view opened on glasses ... purpose=capture-review`.

| Step | Result | Time |
|---|---|---|
| `adb push` of `glassapp.apk` | 112,995 bytes landed at `/sdcard/Android/data/dev.rokid.docscanrelay/files/` | — |
| `queryGlassAppInstalled dev.rokid.docscanglass` | `ANSWERED installed=false` | 0.4 s |
| **`uploadAndInstallApk`** | **`glass-app-install target=dev.rokid.docscanglass verdict=FAILED`** | **43 s** |

**What `FAILED` rules out.** Not `CALL_FAILED`: Hi Rokid accepted the Binder
transaction. Not `NO_RESPONSE`: it called back. This is
`onInstallAppResult(false)` from the far side, 43 s after the request — long
enough that a transfer plausibly happened before the refusal. Hi Rokid logged
no reason; the full logcat for the window carries nothing from the Rokid
packages.

**The APK is not obviously at fault.** `aapt2 dump badging` and `apksigner`:
package `dev.rokid.docscanglass`, `minSdk 28`, `targetSdk 36`, no required
features beyond the implied `android.hardware.faketouch`, no native code.
But two properties are worth one experiment each:

- **signed with v2 only** — no v1 (JAR), no v3. Android 12's own PackageManager
  accepts v2 alone, so this is only a suspect if the glasses use a vendor
  installer that checks JAR signatures.
- **`application-debuggable`** — some vendor installers refuse debuggable APKs.

**And one property of the session, not the APK.** A capture-review CUSTOMVIEW
was open on the glasses for the whole attempt. `client-l:1.1.1` has
`SessionType{CUSTOM_VIEW, CUSTOM_APP}` and the wrapper has
`configCXRSession(CXRSession(sessionType, customAppPackageName))`; the raw AIDL
this relay calls has no session concept at all. Installing a CUSTOM_APP while a
CUSTOM_VIEW session is live may simply not be allowed.

**Next experiment: one variable at a time**, re-querying `installed` after each
so a success is not inferred from the absence of an error. Do not change the
signing, the debuggable flag and the session in one build.

## Phase 1, as built (2026-08-29)

New Gradle module `:glassapp`, applicationId `dev.rokid.docscanglass`,
`minSdk 28` / `targetSdk 36`, **zero dependencies** — no androidx, no CXR-S, no
native libraries. Every dependency added here is another way for a negative
result to mean something other than "no input arrived".

`TapProbeActivity` draws black-on-green on the glasses and counts what reaches
it. It watches **both** input paths — `dispatchTouchEvent` and `onKeyDown` —
because the working reference implementation handles the same gesture on either,
which suggests the touchpad can surface as `KEYCODE_DPAD_*` rather than as a
`MotionEvent`. It also watches `dispatchGenericMotionEvent`, since a touchpad
reporting as a non-touchscreen source would never reach `dispatchTouchEvent` at
all. A probe watching one path could report an absence of input that is really
an absence of one source.

Text is sized from the view rather than from a constant, because **the glasses
display resolution has never been measured by this repo**. The header prints it,
so the run also settles that.

### Why the result is read off the glasses, not from a log

> **Corrected 2026-08-29, after the hardware run.** The claim below that adb on
> the glasses is undocumented is **wrong**, and it was asserted from one web
> search instead of from the vendor SDK documentation. Rokid's CXR-L docs say
> plainly: *"When using Rokid CXR-S SDK, you need enable ADB on Rokid Glasses
> through Rokid AI APP"* — the toggle is 歯車 → グラス設定 → 開発者 →
> 「グラスADBデバッグ」 — after which a **5-pin development cable** gives
> ordinary `adb devices` / `adb install`. The retail box ships a **3-pin
> charging cable that carries no data**; the dev cable is the "Cable only"
> option on `global.rokid.com/products/rokid-glasses-prototype` at **$39.99**,
> about two weeks' delivery, or from the developer assistant.
>
> Consequences: (a) the on-glasses readout is still the right design for a
> probe that must work without a cable, but it is a workaround, not the only
> option; (b) **the ADB toggle has never been enabled on this device**, and it
> is the cheapest untested variable behind the install failure. Enable it
> before spending more hardware cycles.

Nothing can carry it off the device. There is **no documented adb** on the
glasses (the firmware is a `user/release-keys` build and no developer-mode
sequence is documented), and **no documented CXR-S to CXR-L message channel** —
the community documentation's transport table has a CXR-M↔CXR-S row and no
CXR-S↔CXR-L row. `IMediaStreamService.sendCustomCmd(String, byte[])` and
`ICustomCmdCallback.onCustomCmdResult(String, byte[])` do exist in the AAR and
the relay has never used either; whether they pair with CXR-S
`sendMessage`/`subscribe` is **unverified**. Wiring that in now would drag in
five native libraries and an unverified channel, so a silent probe could no
longer be told from a broken transport. It belongs in the iteration *after*
input is confirmed.

### Procedure

Build in the ASCII worktree; `gradlew.bat` is not directly invocable from Git
Bash, so call the script it wraps:

```bash
export JAVA_HOME="C:/Program Files/Android/Android Studio/jbr"
powershell -NoProfile -ExecutionPolicy Bypass \
  -File "C:\Users\Public\rokid-docscan-build\android-relay\build-windows.ps1" \
  testDebugUnitTest assembleDebug
```

Then, with `MSYS_NO_PATHCONV=1` exported for any `adb shell` path:

1. `adb install -r app/build/outputs/apk/debug/app-debug.apk` — relay 0.3.15 /
   versionCode 20.
2. `adb push glassapp/build/outputs/apk/debug/glassapp-debug.apk
   /sdcard/Android/data/dev.rokid.docscanrelay/files/glassapp.apk`. That
   directory is writable by the shell user and readable by the relay with no
   storage permission. The APK is **not** bundled as an asset: a throwaway probe
   must not ship inside a relay build.
3. On the phone: 「Hi Rokid認可・再接続」, then 「計測アプリ名」 to fill the
   package field.
4. 「グラス側アプリ調査」 → expect `installed=false`.
5. 「グラスへ導入」 → expect `glass-app-install ... verdict=SUCCEEDED`.
6. 「グラス側アプリ調査」 again → **expect `installed=true`. This is the
   discriminator**: it is the only evidence the APK landed on the glasses rather
   than the call merely returning.
7. 「グラスで起動」 → expect `glass-app-open ... verdict=SUCCEEDED`.
8. Look through the glasses. Expect `TAP PROBE <w>x<h>`, a counter line, and
   `waiting for input`.
9. Tap the temple. Then try, one at a time, long press / double tap / two-finger
   tap / horizontal swipe, and record which of `DOWN TAP SWIPE KEY EVT` moves.

### How to read each failure

| Symptom | Meaning |
|---|---|
| `APKがありません` / `APKではありません` | The push did not land or was truncated. The relay checks this **before** calling, so a bad file can never be mistaken for the firmware refusing the route. |
| install `CALL_FAILED` | Hi Rokid refused the transaction at the Binder boundary. |
| install `FAILED` | The call ran and the glasses rejected the APK — signing, ABI, or space. |
| install `NO_RESPONSE` (120 s) | Accepted and never answered. Provisional: a late callback still resolves. |
| open `FAILED` | Possibly the activity string's form. The AIDL takes it as a bare second `String` and neither its form nor whether it may be empty is documented; a fully qualified class name is what the relay sends. Do not guess a second form in the same run — that would make the verdict unreadable. |
| App visible, counters stay `0` | Input does not reach a glasses-side app either. Output works, input does not, and Phase 2 needs a different control surface. |

The install timeout is 120 s and the launch timeout 15 s, against the query's
5 s: an install ships an APK across the link and then runs a package install on
the far side, so holding it to 5 s would report a working install as
`NO_RESPONSE`.

## Open risks

- ~~Phase 1 needs a second Gradle module and a signing story for the glasses
  APK.~~ **Investigated 2026-08-29.** A second module is the right shape — the
  reference implementation is exactly that — and there is no signing story to
  have: its `release` block sets no `signingConfig` at all. See
  `docs/glasses-app-route-findings.md`.
- **The relay uses none of the SDK's session layer.** `client-l:1.1.1` ships
  `CxrSessionManager` / `CxrSession` / `SessionConfig` / `CapabilityBroker`
  above the raw AIDL this repo calls directly, including `SessionType.CUSTOM_APP`
  and an `AiInterceptMode.BLOCK_AI` that may bear on the gesture-reservation
  problem the whole UX contract is built around. Untested; do not design on it
  until it is.
- **There is no known way to read anything off the glasses.** Searched
  2026-08-29: no documented adb or developer-mode sequence for YodaOS-Sprite
  (the firmware is a `user/release-keys` build), and no documented CXR-S↔CXR-L
  message path. Phase 1 therefore reports on the glasses display. If a run needs
  more than that, the candidates are, in order: the unverified
  `sendCustomCmd`/`onCustomCmdResult` ↔ CXR-S `sendMessage`/`subscribe` pairing;
  plain HTTP from the glasses app, if the glasses share a network with the
  server; and a development cable the retail package does not include (the
  magnetic charging port doubles as a data port) — that last one is procurement
  lead time.
- **`cxr-service-bridge` ships native libraries**, `arm64-v8a` and
  `armeabi-v7a`: `libcaps`, `libcxr-bridge-jni`, `libcxr-sock-proto-jni`,
  `libflora-cli`, `libmutils`. `docs/glasses-app-route-findings.md` records "no
  ABI filter" — that is accurate for the reference implementation, which uses no
  Rokid SDK, but it does **not** hold for a glasses app that adopts CXR-S. The
  Phase 1 probe uses no SDK, so it is unaffected.
- `ROKID_REAL_MODE` in `CLAUDE.md` is still unimplemented — `refactor-instructions.md`
  D06 holds it until its scope and fail-fast policy are decided. Nothing rejects
  a placeholder analyzer today; `/v1/settings` only reports.

## Checkpoint — 2026-09-01 safe device-ready artifact

Branch: `agent/real-device-test-prep` (working tree intentionally not committed
at this checkpoint because it contains pre-existing user edits interleaved with
the requested documentation corrections).

### Completed and verified

- All 29 Markdown files are classified from `docs/README.md`; current runbooks
  use phone controls and separate application camera-request state from the
  externally observed privacy indicator.
- Executable privacy-indicator manipulation code was replaced with explicit
  compatibility stubs. Focused quarantine tests pass.
- `ROKID_REAL_MODE=1` rejects placeholder/unready analyzer and solver choices,
  startup validates both ports, analyzer failures do not silently degrade, and
  solver tiers do not append the local placeholder.
- CUSTOMVIEW/AI callbacks and close events are lifecycle diagnostics only.
  Capture, shutter, registration, retake, discard, completion, and review
  navigation require explicit phone controls; automatic capture/registration
  is disabled.
- Python: `425 passed`, one known Starlette/httpx deprecation warning; `ruff
  check .` passes; `git diff --check` passes.
- Android: 72 relevant source/config files hash-identical between the repository
  and ASCII build copy. Microsoft OpenJDK 17.0.20.1 was SHA-256 verified. JDK 17
  `testDebugUnitTest assembleDebug` passes.
- Relay APK: package `dev.rokid.docscanrelay`, versionCode `21`, versionName
  `0.3.16`, SHA-256
  `C96BF67F51CC64BA0F581ABF97D09E73B9272243376DA2F2FBBB3D31F7E16A52`.

### Exact blocker / safe resume point

The Android device-bridge inventory returned no devices. No relay APK was
installed and no photo was requested. `ROKID_REAL_MODE`, analyzer/solver
selections, server bearer key, and all supported cloud-provider keys were absent
from process/user/machine environment checks (only presence booleans printed).

Resume only after one unlocked Android phone is attached and its USB-debugging
prompt is accepted. Require exactly one connected serial, inspect the installed
relay version/signature before updating it, and configure a real analyzer and
solver without printing credentials. A capture run additionally requires a
second observer/camera to record the physical indicator during `takePhoto`,
after callback, and throughout analysis/review.

## Checkpoint — 2026-09-01 read-only phone inventory

Branch `agent/real-device-test-prep`, HEAD `2f3179e`. At 20:12 JST, wireless
debugging enumerated exactly one device. The network serial is intentionally
omitted from this record; every device-specific command used the explicit
serial.

### Sanitized inventory evidence

- Phone: FCNT F-51F, Android 16 / API 36, build
  `W1VHS36H.80-34-2-2-1-5`, security patch `2026-07-01`.
- Global Hi Rokid: `com.rokid.sprite.global.aiapp`, versionName
  `G1.12.10.0815`, versionCode `10120010`, signing scheme v3; its process was
  running.
- Installed relay: `dev.rokid.docscanrelay`, versionName `0.3.15`, versionCode
  `20`, SHA-256
  `BD13F5A1EF21849EEE7CF2C2B9499B332E157CC3503387177FDD0DA8F22BB83B`;
  its process was not running.
- Verified update candidate:
  `C:\Users\Public\rokid-docscan-build-current-20260901a\android-relay\app\build\outputs\apk\debug\app-debug.apk`,
  versionName `0.3.16`, versionCode `21`, SHA-256
  `C96BF67F51CC64BA0F581ABF97D09E73B9272243376DA2F2FBBB3D31F7E16A52`.
- Installed and candidate signer SHA-256 is identical:
  `906307478018E09E2937CFD8042A674D27598767577E08A304472AAE407CCACC`.
  The update is signature-compatible and versionCode increases from 20 to 21.
- A stale APK under `C:\Users\Public\rokid-docscan-build` is byte-identical to
  installed `0.3.15`; it is not the update candidate and must not be installed.
- No install, app launch, photo request, or phone setting change occurred during
  this inventory. The relay was not running, so the glasses connection and
  CXR-L service version were not re-observed; both remain Task 6 evidence.

The sanitized sequence enumerated devices; read system properties, package
metadata, package paths, and process presence with an explicit serial; copied
the installed base APK read-only to a temporary local directory; and compared
local hashes, package metadata, and signing certificates. No credentials,
tokens, page contents, OCR, or provider payloads were read or recorded.

Checkpoint verification: `git diff --check` passes. Four focused documentation
contract tests pass. The full documentation-contract module has one known
environmental failure: its repository-wide Markdown scan sees 57 untracked
generated OpenSpec/Spec Kit skill, command, and template files as unclassified.
The same audit found zero unclassified tracked Markdown files. Those pre-existing
untracked tool assets were not deleted, moved, indexed, staged, or modified.

### Safe resume point

Task 5 is complete. Before Task 6 capture validation, confirm the external
camera/observer setup and fail-closed real-mode server configuration. Install
only the verified `0.3.16` candidate above, then re-observe Hi Rokid
authorization, glasses link, CXR-L service version, and CUSTOMVIEW acknowledgement
before any phone-controlled photo request.

## Checkpoint — 2026-09-01 verified relay update

The user explicitly authorized updating the phone relay. With exactly one
F-51F selected by its explicit wireless-debugging serial, the verified
`0.3.16` / versionCode `21` candidate was installed as an in-place update. The
package manager returned `Success`; no uninstall, downgrade, app launch, or
photo request occurred.

Post-install read-only verification found:

- package `dev.rokid.docscanrelay`, versionName `0.3.16`, versionCode `21`;
- installed base APK SHA-256
  `C96BF67F51CC64BA0F581ABF97D09E73B9272243376DA2F2FBBB3D31F7E16A52`,
  exactly matching the verified candidate;
- unchanged `firstInstallTime` (`2026-07-25 23:18:48`) and unchanged app-data
  inode, confirming the update preserved the existing installation state;
- relay process not running after installation.

Task 6 remains incomplete. The server is not listening on port 8000, and the
checked process/user/machine environments contain no real-mode selection,
server bearer key, analyzer/solver selection, or supported provider key. Do not
launch a capture until a fail-closed real-mode server is configured and an
independent camera/observer can keep the physical indicator continuously in
frame.

## Checkpoint — 2026-09-01 glasses app installed, launched, and receives input

The user connected the glasses directly and explicitly authorized installing
and launching the existing no-permission tap probe. Two Android devices were
present and unambiguous: the F-51F phone and a directly attached `RG_glasses`;
every command named the intended device serial.

### Exact glasses tuple

- Hardware: Rokid `RG-glasses`, physical display `480x640` at 240 dpi.
- OS: Android 12 / API 32, user/release-keys build
  `1.25.012-20260901-150201`, build ID `SKQ1.240613.001`.
- Security patch: `2024-07-05`.
- Glasses CXR service: package `com.rokid.cxrservice`, versionName `12`,
  versionCode `32`, signing scheme v3, process running.
- Launcher: `com.rokid.os.sprite.launcher` versionName `0.3.7`, versionCode
  `3717`, process running.

### Probe installation and input proof

- Installed package `dev.rokid.docscanglass`, versionName `0.1.0`, versionCode
  `1`, directly on the glasses.
- The installed base APK SHA-256 is
  `78347FFDF836F516764ADA977C02E040BCEA2AFD9FBC87F218C7A439E1FA0443`,
  exactly matching the verified build artifact.
- `TapProbeActivity` launched successfully and held the foreground input/window
  focus. It requests no Android permissions and did not open a camera or make a
  network request.
- The physical input device identifies as `ROKID,PSOC-TP-R`. Raw events included
  `KEY_ENTER`, `KEY_DASHBOARD`, `KEY_PROG1`, `KEY_BACK`, `KEY_RIGHT`, and
  `KEY_DOWN`. Long presses were distinguishable from the DOWN-to-UP interval
  (observed around 0.8–0.9 seconds for `KEY_PROG1`).
- The app recorded 33 `onKeyDown` events under tag `DocScanGlass`. This proves
  physical glasses input reaches an ordinary glasses-side Android Activity on
  this exact tuple. It does not prove a production command mapping or a
  glasses-to-phone transport yet.

This result supersedes the earlier hardware blocker: direct installation,
launch, foreground rendering, and physical input delivery are now verified.
The next change must specify and implement the production glasses app as the
operator control surface, keeping the phone as OCR/network relay until a
source-grounded transport and capture contract are verified. No photo was
requested during this probe.

## Checkpoint — 2026-09-01 GI-1 local implementation; hardware calibration pending

The user accepted `SPEC-glasses-input.md` and authorized continuing with an
app-based glasses control surface. GI-1 now has a locally verified,
side-effect-free dual-path calibration implementation. This checkpoint does
not claim a new hardware result.

### Implemented and verified locally

- The exact 11 official Rokid custom-app input actions are held in one immutable
  catalog and registered dynamically by `TapProbeActivity`.
- Official broadcasts and Activity key DOWN/UP events enter one bounded,
  newest-first diagnostic sequence using `SystemClock.elapsedRealtime()`.
- Diagnostics contain only sequence, monotonic elapsed time, source, phase,
  action/key name, and allow-list status. No intent extras are read, no
  broadcast is aborted, and no capture, network, upload, OCR, or registration
  call was added.
- Unknown input signals remain representable with `known=false` and cannot emit
  a workflow action; GI-1 intentionally contains no normalizer or business
  mapping.
- TDD RED failed only because the new calibration types were absent. The
  focused test then passed after the minimal implementation.
- From the current ASCII build copy,
  `:glassapp:testDebugUnitTest :glassapp:assembleDebug`, full
  `testDebugUnitTest assembleDebug`, and `:glassapp:lintDebug` all pass.
- The seven changed source/config/test files are SHA-256 identical between the
  repository and the current ASCII build copy. `git diff --check` passes.

### Candidate and exact blocker

- Candidate package `dev.rokid.docscanglass`, versionName `0.1.1`, versionCode
  `2`, signer SHA-256
  `906307478018E09E2937CFD8042A674D27598767577E08A304472AAE407CCACC`.
- Candidate APK SHA-256:
  `344242C989FAD1479B164C9A251B1719379DC64E677998CDBC9202EC55E7348A`.
- At the hardware gate, the device bridge enumerated only the F-51F phone; the
  previously direct-attached `RG-glasses` was absent from both the bridge and
  matching Windows USB-device inventory. No APK was transferred or launched in
  this checkpoint.

Resume by reconnecting the glasses with its data-capable development cable and
confirming it appears as `RG-glasses`. Then deploy only the candidate hash above
to the explicit glasses device, launch `TapProbeActivity`, and record a
controlled gesture sequence against raw input, official broadcast, and Activity
KeyEvent timing. Do not choose the GI-2 deduplication bound until that physical
correlation evidence exists.

## Checkpoint — 2026-09-01 GI-A hardware calibration complete

The user reconnected the directly attached `RG-glasses` and performed each
named physical gesture separately while the raw input stream and content-free
`DocScanGlass` callbacks were recorded on a shared monotonic clock. Every
device command selected the glasses explicitly; no command was redirected to
the phone. The hardware/OS/CXR tuple is unchanged from the preceding glasses
checkpoint.

### Measured gesture rows

| User-confirmed gesture | Raw device sequence | App observation | Timing and disposition |
|---|---|---|---|
| Short tap | `KEY_DASHBOARD`, then `KEY_ENTER` | `KEYCODE_NOTIFICATION`, then `KEYCODE_ENTER`; no official broadcast | raw DOWN gap 544 ms in calibration; final 0.1.2 smoke-test app gap 516 ms |
| About-one-second long press | `KEY_DASHBOARD`, then `KEY_PROG1` DOWN/UP | `KEYCODE_NOTIFICATION`; `ACTION_AI_START`; no `KEY_PROG1` Activity event | `PROG1` began 507 ms after dashboard, official broadcast followed 315 ms later, raw hold was 799 ms |
| Double tap | `KEY_DASHBOARD` twice, then `KEY_BACK` | `KEYCODE_NOTIFICATION` twice, then `KEYCODE_BACK`; no official double-click broadcast | dashboard DOWN gap 207 ms; back followed the second by 312 ms and closed the Activity because BACK remains unconsumed |
| Back-to-front swipe | `KEY_DASHBOARD`, `KEY_RIGHT`, `KEY_DOWN` | `KEYCODE_NOTIFICATION`, `KEYCODE_DPAD_RIGHT`, `KEYCODE_DPAD_DOWN`; no official forward-swipe broadcast | right began 426 ms after dashboard; down followed right-UP immediately |
| Front-to-back swipe | Initial attempt: `KEY_DASHBOARD`, then `KEY_ENTER`; three user-requested retries: `KEY_DASHBOARD`, `KEY_LEFT`, `KEY_UP` every time | Retry sequence: `KEYCODE_NOTIFICATION`, `KEYCODE_DPAD_LEFT`, `KEYCODE_DPAD_UP`; no official back-swipe broadcast | The initial attempt was not a completed swipe. Retry dashboard-to-left gaps were 469/370/396 ms; left-to-up gaps were 86/48/23 ms |

Raw-to-Activity delivery was approximately 2–10 ms in the isolated short-tap
run. The only official broadcast observed across the controlled sequence was
`ACTION_AI_START` during the physical long press. These are properties of build
`1.25.012-20260901-150201`, not platform-wide constants.

### Final artifact and verification

- The calibration run used 0.1.1 / versionCode 2, SHA-256
  `344242C989FAD1479B164C9A251B1719379DC64E677998CDBC9202EC55E7348A`.
- The measured `KEY_DASHBOARD → KEYCODE_NOTIFICATION` mapping was added to the
  tested allow-list using a RED-then-GREEN unit-test increment.
- Final package `dev.rokid.docscanglass`, versionName `0.1.2`, versionCode 3,
  signer SHA-256
  `906307478018E09E2937CFD8042A674D27598767577E08A304472AAE407CCACC`.
- Final APK SHA-256:
  `41092B73ADCAF2E651D202BEDF3D88874EAF4ED20036AA04EE613180D197B915`.
  The device-resident APK matched this hash exactly, and the preserved first
  deployment time proved an in-place update.
- On 0.1.2, a final user-confirmed short tap recorded both
  `KEYCODE_NOTIFICATION` and `KEYCODE_ENTER` as `known=true`.
- Full Android unit tests and both debug APK builds pass; glassapp lint passes;
  the seven mirrored source/config/test files match the current ASCII build
  copy byte-for-byte.

The user identified that the initial front-to-back attempt might not have been
performed successfully and repeated it three times. All three retries produced
the same LEFT/UP sequence, distinct from short tap and the RIGHT/DOWN forward
sequence. GI-2 may therefore normalize short tap and both swipe directions.
Double tap remains a system-owned BACK sequence and must stay unconsumed. The
correlation policy may use only the measured rows above and must fail closed for
absent official broadcasts and unknown sequences.

## Checkpoint — 2026-09-01 GI-2 normalization complete

The user confirmed that short tap must remain a supported normalized gesture.
After the repeated front-to-back measurements distinguished LEFT/UP from the
short-tap ENTER sequence, the implemented side-effect-free vocabulary is:

- `SHORT_TAP` from `NOTIFICATION → ENTER` or an official click report;
- `LONG_PRESS` from official long-press or AI-start;
- `SWIPE_FORWARD` from `NOTIFICATION → RIGHT → DOWN` or its official report;
- `SWIPE_BACK` from `NOTIFICATION → LEFT → UP` or its official report.

Double tap ends in system-owned BACK and produces no normalized action. Unknown,
UP-only, reordered, incomplete, and late sequences also produce no action.
Nothing in this module assigns capture, navigation, registration, discard,
network, or exit semantics.

### Correlation and test evidence

- The first 816 ms bound failed closed on a deliberately slow physical back
  swipe whose notification-to-terminal interval was 970 ms. The test was
  changed RED-first so 970 ms is inclusive and 971 ms is rejected; the
  firmware-scoped constant is now exactly 970 ms.
- Pure-Java tests cover KeyEvent-only and broadcast-only recognition, paired
  callback deduplication, repeated and distinct actions, an intervening
  different action, late/reordered/unknown signals, ambiguous/incomplete input,
  and system BACK.
- Deduplication tracks the last emission per action type. A different normalized
  action between two reports cannot re-enable a duplicate from the earlier
  physical gesture.
- `TapProbeActivity` shows and logs a numbered normalized action but invokes no
  workflow operation.

### Hardware and artifact evidence

- On 0.1.4 / versionCode 5, SHA-256
  `B8E8A0532887BB51426B55BBD685A0166787451089575294155C4CE7A9AB0EB5`,
  one controlled sequence emitted exactly four rows:
  `SWIPE_BACK #1`, `SHORT_TAP #2`, `LONG_PRESS #3`, and
  `SWIPE_FORWARD #4`. No extra normalized row appeared.
- A later RED-first interleaved-action deduplication test changed only the pure
  normalizer. The final package is 0.1.5 / versionCode 6, signer SHA-256
  `906307478018E09E2937CFD8042A674D27598767577E08A304472AAE407CCACC`,
  APK SHA-256
  `5BCCA4D5DC66B0844FC22A2C2356132024DBBC0FEF3E7B16588A96DD065555E3`.
- The device-resident 0.1.5 APK matched that hash exactly and retained the
  original first-deployment time. Its Activity launched and a user-performed
  short tap emitted exactly `normalized #1 action=SHORT_TAP`.
- Full Android unit tests and both debug APK builds pass; glassapp lint passes;
  the six changed source/config/test files match the current ASCII build copy.

The direct USB transport was intermittent during deployment. Commands always
named the intended glasses device, and a failed attempt was never reinterpreted
as success. One retry reached the device before Android's package service was
ready and failed without changing the package; the successful retry first
confirmed OS boot completion and package-service availability.

## Checkpoint — 2026-09-02 GI-3 lifecycle hardening complete

GI-3 adds an exact-once receiver lifecycle boundary and an explicit normalizer
reset without changing the four side-effect-free actions or assigning workflow
semantics to them.

### Lifecycle and test evidence

- `GlassesInputReceiver` registers and unregisters its platform operation at
  most once, changes its internal state only after the platform operation
  succeeds, and forwards content-free official or unknown action names only
  while registered.
- `TapProbeActivity` uses that lifecycle boundary, unregisters it during
  destruction, and never calls `abortBroadcast()`.
- `GlassesInputNormalizer.reset()` clears incomplete correlation and per-action
  deduplication history without emitting an action. Activity destruction and
  every window-focus transition invoke the reset.
- Tests cover exact-once registration and cleanup, failed registration, gated
  delivery, partial-sequence clearing, deduplication clearing, and no replay.
  Existing tests continue to prove that BACK and unknown, incomplete,
  reordered, late, and UP-only input remain unconsumed or unnormalized.
- Full Android `testDebugUnitTest assembleDebug` and `:glassapp:lintDebug` pass
  from the verified ASCII build path.

### Final artifact and hardware restart evidence

- Final package `dev.rokid.docscanglass`, versionName `0.1.6`, versionCode 7,
  signer SHA-256
  `906307478018E09E2937CFD8042A674D27598767577E08A304472AAE407CCACC`.
- Candidate and device-resident APK SHA-256 both equal
  `C370A2457B12DB31C652758982325468AF73E1AB10A5F0335EB801C848B9CC98`.
  The preserved first-install timestamp proves an in-place update.
- An app-process-only restart changed PID 3165 to PID 3218. The new process
  logged `tap probe started` and a focus-gain reset before any normalized
  action, with no replay from the previous process.
- Two user-performed short taps after that restart emitted exactly
  `SHORT_TAP #1` and `SHORT_TAP #2`, one action per physical tap. No duplicate
  or numbering/state carry-over occurred. Combined with the GI-2 controlled
  four-gesture run, this completes the install/restart hardware acceptance for
  the module on the recorded tuple.
- The glass app still requests no Android permissions and contains no camera,
  network, upload, OCR, or document-registration operation. GI-3 observed no
  such side effect.

During the first GI-3 hardware attempt the glasses restarted unexpectedly. No
reboot command had been sent. Read-only diagnosis found a generic `reboot`
reason, no pstore record, no `SYSTEM_RESTART` dropbox entry, no contemporaneous
app crash, and only older low-memory process exits. A 30-second baseline with
the app stopped and a further 30-second run with the Activity foregrounded were
stable, so the restart was not reproduced and is not attributed to the app.

All technical items in Checkpoint GI-B are now satisfied. The separate human
review gate for moving to `custom-app-session` remains intentionally open.

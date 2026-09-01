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

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

  > **Corrected 2026-09-03.** Both halves of this risk are now false.
  > (a) The data-capable cable was obtained and used: from 2026-09-01 the
  > glasses appear as `RG_glasses` over direct `adb`, and every glasses build
  > from 0.1.0 to 0.1.6 was installed, launched, and read back through it.
  > `adb logcat` is the channel, not the glasses display.
  > (b) A CXR-S↔CXR-L message path is documented by a working third party:
  > `TakanariShimbo/RokidGlassesAppCenter` runs JSON over `Caps` on a CXR-L
  > `CUSTOMAPP` session, phone `sendCustomCmd("appmgr.req", ...)` to glasses
  > `CXRServiceBridge` `subscribe`/`sendMessage`, and back on `appmgr.res`.
  > Rokid does not publish the pairing, but it is not unknown.
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

## Checkpoint — 2026-09-02 GI-B human review accepted

The user explicitly approved moving from the completed `glasses-input` module
to `custom-app-session`. Checkpoint GI-B is therefore fully closed. The user
then intentionally restarted the glasses; this is not the unexplained restart
from the preceding hardware attempt. Read-only verification after that restart
found the explicit `RG_glasses` device online, Android boot complete, and
`dev.rokid.docscanglass` 0.1.6 / versionCode 7 still installed.

Specification research for `custom-app-session` found that the linked
`client-l:1.1.1` bytecode supports Global Hi Rokid selection through
`AuthorizationHelper.isConnectHiRokid()`. The existing manual token flow does
not establish that SDK-owned selection and permission state, so the new module
must use the official authorization helper before creating its one-process
`CUSTOMAPP` `CXRLink`. No session implementation or device mutation was made in
this checkpoint.

### PR checkpoint state

- Repository: `TroroOrosi/rokid-docscan-starter`; branch
  `agent/real-device-test-prep`; pre-checkpoint HEAD
  `b92940bb5377d68e53a70065c0f026bd17e6f85d`.
- Existing pull request: #30, `Harden and document the Rokid real-device
  workflow`, targeting `main`. Do not open a duplicate PR.
- Checkpoint paths are limited to `SPEC-custom-app-session.md`,
  `tasks/todo.md`, `docs/README.md`, and this progress record. Tool-generated
  untracked directories remain excluded.
- Verified before checkpoint: the focused documentation contract is 4 passed /
  1 deselected, `git diff --check` passes, the restarted glasses reports boot
  complete, and glass app 0.1.6 / versionCode 7 remains installed. The prior
  implementation HEAD passed the full Android unit/build/lint gate and PR CI.
- The new spec is a review draft, not an accepted implementation contract. Its
  open decision is whether the first increment uses only the already-installed
  glasses app and omits runtime install/update/uninstall.

Resume in this order:

1. obtain human approval or revision of `SPEC-custom-app-session.md`;
2. mark the spec accepted and use `agent-skills:planning-and-task-breakdown` to
   extend `tasks/plan.md` and `tasks/todo.md`;
3. inspect the resolved stable CXR-S 1.0 AAR, correct the superseded Global
   CXR-L note, and implement each task with
   `agent-skills:incremental-implementation` plus
   `agent-skills:test-driven-development`;
4. build from the verified ASCII copy and perform explicit-phone plus direct-
   glasses hardware acceptance without invoking capture or custom commands.

## Checkpoint - 2026-09-03 published sources reviewed; capability spike built

The user supplied three articles and three Reddit threads and asked whether the
approach was still rational before continuing. The review found that several
decisions here were taken from this repository's own notes rather than from
sources that were already public, and that one hardware session re-derived a
published table.

### What was already public and did not need measuring

- Two-finger gestures and the one-finger long press never reach an ordinary app
  because `/system/usr/keylayout/Generic.kl` maps them to vendor codes
  (`SPRITE_SWIPE_FORWARD`, `SPRITE_SWIPE_BACK`, `SPRITE_DOUBLE_TAP`,
  `PROG_BLUE`) with no AOSP `KeyEvent` equivalent. One `adb shell cat` answers
  what the GI-A session spent a controlled gesture run establishing.
- Exactly four inputs reach an app: `KEYCODE_ENTER`, `KEYCODE_DPAD_*`,
  `KEYCODE_BACK`, `KEYCODE_NOTIFICATION` (83, scan 204).
- The display is 480x640 at 240 dpi. `docs/glasses-app-route-findings.md` still
  called it unknown.
- The glasses reach the network over their own Wi-Fi in several community apps,
  while the Open risks here said nothing could be read off the device at all.
- Phone-to-glasses custom commands are implemented publicly by
  `TakanariShimbo/RokidGlassesAppCenter` as JSON over `Caps` on a CXR-L
  `CUSTOMAPP` session.

GI-A recorded that the double tap "closed the Activity because BACK remains
unconsumed" and left it. That is the defect the user hit.

### Checked against the artifact, 2026-09-03

`javap` over the linked `client-l:1.1.1` AAR: `AuthorizationHelper`
(`requestAuthorization`, `hasGlassPermission`, `isConnectHiRokid`,
`canLaunchApp`), `GlassPermission{MICROPHONE, CAMERA, MEDIA, DEVICE_MANAGE}`,
`ExternalAppClient.configCXRSession(CXRSession, ICXRSessionCbk)`,
`CXRSessionType{NONE, CUSTOMVIEW, CUSTOMAPP}`, and `CxrSession.takePhoto`
alongside `CxrSession.sendCustomCmd`. The relay calls none of this layer; grep
finds zero references. Rokid Maven `maven-metadata.xml` reports `client-l`
release **1.1.2** (`lastUpdated 20260828083628`); this repository pins 1.1.1.

### Implemented

- `:glassapp` 0.1.7 / versionCode 8. `GlassesInputAction.BACK` is normalized
  from the measured `NOTIFICATION, NOTIFICATION, BACK` sequence, and
  `BackExitPolicy` turns the first BACK into an armed confirmation and a second
  within 3000 ms into an exit. The interception point is `onBackPressed`, not a
  consumed `KEYCODE_BACK`: the key must still reach `Activity.onKeyDown` so the
  framework tracks it. The measured build is API 32, where
  `OnBackInvokedDispatcher` does not exist, so the lint request to migrate to
  the AndroidX dispatcher is suppressed with an expiry condition recorded at
  the call site.
- New `:glassprobe` module 0.1.0 / versionCode 1, applicationId
  `dev.rokid.docscanglass.probe`. Separate from `:glassapp` so that adding
  CAMERA and INTERNET cannot weaken the no-permission record of the app under
  test. It reports display metrics, camera enumeration, one explicitly
  requested camera2 still into app-private cache, one `GET /health` plus one
  `GET /v1/settings` against a `--es server` extra, and a BACK counter. It
  uploads nothing, recognizes nothing, registers nothing, and does not touch
  the privacy indicator.
- Documents corrected in the same change: the unknown display size, the
  superseded `client-l` release, the resolved gesture question, and both halves
  of the "nothing can be read off the glasses" risk. New index
  `docs/glasses-primary-sources-2026-09-03.md` records what is already known so
  the next session does not re-search or re-measure.
- `SPEC-custom-app-session.md` is retained as a draft but is no longer the next
  increment; its Open Questions now carry the decision table the spike feeds.

### Verified locally (commands and results)

- `py -3.12 -m pytest -q`: **424 passed, 1 failed**. The failure is the known
  environmental one: the repository-wide Markdown scan counts 57 untracked
  tool-generated OpenSpec/Spec Kit files. Zero tracked Markdown files are
  unclassified, and the new document is registered.
- `ruff check .`: all checks passed. `git diff --check`: clean.
- Android, from the ASCII copy with
  `JAVA_HOME=C:/Users/Public/rokid-build-tools-20260901/jdk17/jdk-17.0.20.1+1`
  (Android Studio `jbr` is openjdk 25 and AGP rejects it):
  `testDebugUnitTest assembleDebug :glassapp:lintDebug :glassprobe:lintDebug`
  -> **BUILD SUCCESSFUL**, 135 actionable tasks. `:app` 182 tests, `:glassapp`
  31 tests, `:glassprobe` 6 tests, all 0 failures and 0 errors. Both lint tasks
  pass.
- Artifacts:
  - `dev.rokid.docscanglass` 0.1.7 / 8, 140,364 B, SHA-256
    `3F435131149A985B9E4015A603CC110C4ABFEC8E327B4DA05B16EA405415D6B1`.
    `aapt2 dump badging` shows **no `uses-permission` at all**.
  - `dev.rokid.docscanglass.probe` 0.1.0 / 1, 158,710 B, SHA-256
    `60C9356B0A5497BD226A02ADB2CEDB4A1430F5084A0781F3F20780935D7715C6`,
    `uses-permission` exactly CAMERA and INTERNET.
  - `dev.rokid.docscanrelay` unchanged at 0.3.16 / 21, SHA-256
    `C96BF67F51CC64BA0F581ABF97D09E73B9272243376DA2F2FBBB3D31F7E16A52`.

### Not verified

**Nothing was installed, started, or run on any device in this checkpoint.** The
device bridge was not invoked and no photo was requested. A build proves
compilation. Specifically unverified on hardware: that consuming the double tap
keeps the Activity alive; that camera2 opens on the glasses; that the privacy
indicator lights during and clears after a capture; that the glasses reach the
server over Wi-Fi; and whether a sideloaded app appears in the glasses launcher.

### Resume, with the approval each step needs

1. Ask the user before any device write. `adb install` changes device state.
2. Read-only first, no approval needed:
   `adb -s SERIAL shell cmd package query-activities -a android.intent.action.MAIN
   -c android.intent.category.LAUNCHER | grep docscanglass`. If absent, phone-side
   `openApp` becomes mandatory and `SPEC-custom-app-session.md` is promoted.
3. With approval, install only the two hashes above to the explicit
   `RG_glasses` serial, then
   `adb -s SERIAL shell am start -n
   dev.rokid.docscanglass.probe/.CapabilityProbeActivity --es server
   "http://HOST:8000"` and read `adb logcat -s DocScanGlassProbe`.
4. Run P2 only with an independent observer keeping the privacy indicator
   continuously in frame. If that is not arranged, skip P2 and report it as not
   run rather than as a negative result.
5. Record the outcome against the decision table in
   `SPEC-custom-app-session.md`, then choose the architecture.

## Checkpoint — 2026-09-04 hardware acceptance run; the spike is settled

The user connected the glasses on request and approved the installs. Every
device write below was run against the explicit serial `1904092623381086`
(`RG-glasses`), never a bare `adb install`.

### Device, read-only, before any write

`ro.build.fingerprint=Rokid/glasses/glasses:12/SKQ1.240613.001/1.25.012-20260901-150201:user/release-keys`,
Android 12 / API 32, `ro.config.low_ram=true`. `dev.rokid.docscanglass` was
present at 0.1.6 / versionCode 7.

**Launcher visibility was answered without installing anything.**
`cmd package query-activities -a android.intent.action.MAIN -c android.intent.category.LAUNCHER`
returns 18 activities across 9 packages, and
`dev.rokid.docscanglass/.TapProbeActivity` is one of them, beside
`com.android.camera2`, `com.android.settings`, `com.rokid.os.sprite.launcher`,
`com.eg.android.AlipayGGlasses` and `com.tencent.glasswxpay.glassapp`. A
sideloaded app is launcher-visible, so **phone-side `openApp` is not a
precondition** and `SPEC-custom-app-session.md` is not promoted.

### Installed

Hashes were re-computed immediately before the install and matched the recorded
build exactly.

| APK | Version | SHA-256 | Result |
|---|---|---|---|
| `dev.rokid.docscanglass` | 0.1.7 / 8 | `3F435131149A985B9E4015A603CC110C4ABFEC8E327B4DA05B16EA405415D6B1` | `Success`, confirmed 0.1.7 / 8 on device |
| `dev.rokid.docscanglass.probe` | 0.1.0 / 1 | `60C9356B0A5497BD226A02ADB2CEDB4A1430F5084A0781F3F20780935D7715C6` | `Success`, confirmed 0.1.0 / 1 on device |

### P1 display — OK

`480x640 240dpi heap256MB`, read from inside the app. Matches the 2026-09-01
`dumpsys` measurement and the published figure.

### P2 camera — OK, and the privacy indicator behaves

Seven consecutive stills, every one at the sensor maximum:

| Time | Size | Bytes | Elapsed |
|---|---|---|---|
| 18:15:40 | 4032x3024 | 5,718,125 | 1380 ms |
| 18:15:54 | 4032x3024 | 5,915,983 | 922 ms |
| 18:16:01 | 4032x3024 | 5,929,367 | 785 ms |
| 18:16:22 | 4032x3024 | 6,127,682 | 811 ms |
| 18:16:26 | 4032x3024 | 6,081,992 | 796 ms |

`camera2` opens from an ordinary third-party app holding only
`android.permission.CAMERA`. The phone relay `takePhoto` was measured at 5.2 s;
glasses-direct capture is roughly six times faster at full resolution.

**Privacy indicator, corroborated two independent ways.** An observer watching
the physical LED reported it lit only while the capture was pending. The kernel
LED driver log shows the same on all seven captures:

```
CameraService: connectDevice                   18:15:38.593
aw2110x chan=3 brightness=0xFF   <- lit        18:15:38.624   (+31 ms)
finishCameraStreamingOps                       18:15:39.748
aw2110x chan=3 brightness=0x00   <- cleared    18:15:39.767   (+19 ms)
CameraService: disconnect                      18:15:40.091
```

Channel 3 is the white privacy LED. It is driven by the camera pipeline in
firmware and clears **before** the client disconnects; the app never touches it.
All three `CLAUDE.md` acceptance conditions hold on this firmware.
`run-as ... ls cache/` after `onDestroy` shows the directory empty, so
`probe-capture.jpg` was deleted as designed. Nothing was uploaded, recognized,
or registered.

### P3 network — OK, and this is the finding that decides the architecture

The glasses reach the FastAPI server over their own Wi-Fi, twice, independently:

```
18:12:27  link=wlan0=192.168.0.5  /health 200 in 197ms   /v1/settings 200 in 17ms
18:15:03  link=wlan0=192.168.0.5  /health 200 in  96ms   /v1/settings 200 in 1037ms
```

Server was `app 0.16.0 / API 1.15.0` on `192.168.0.32:8000`. The phone is not
required in the data path.

### P4 BACK — OK

```
18:18:35.238  probe P4 BACK OK consumed x1, again to exit
18:18:40.346  probe P4 BACK OK consumed x2, again to exit   (+5.11 s, window expired, re-armed)
18:18:43.870  probe P4 BACK OK consumed x3, again to exit   (+3.52 s, window expired, re-armed)
18:18:46.014  back confirmed after 4 reports; finishing     (+2.14 s, inside the window)
```

`KEYCODE_BACK` is consumable by an ordinary app. Three of four deliveries were
consumed without finishing the Activity, and the timeout re-arm behaved as the
unit tests specify.

### `:glassapp` 0.1.7 on hardware — the double-tap exit is fixed

```
18:21:15.229  KEYCODE_NOTIFICATION DOWN  #39
18:21:15.246  KEYCODE_NOTIFICATION UP    #40
18:21:15.412  KEYCODE_NOTIFICATION DOWN  #41
18:21:15.430  KEYCODE_NOTIFICATION UP    #42
18:21:15.720  KEYCODE_BACK DOWN          #43
18:21:15.720  normalized #7 action=BACK          <- emitted exactly once
18:21:15.744  back armed; a second BACK within 3000 ms exits
```

`topResumedActivity` remained `dev.rokid.docscanglass/.TapProbeActivity`: the
Activity survived. The measured correlation span is 491 ms, inside the 970 ms
bound the normalizer enforces. Deduplication also confirmed on a forward swipe —
two `KEYCODE_DPAD_RIGHT` events produced a single
`normalized #6 action=SWIPE_FORWARD`.

**This closes the defect the user identified.** On 0.1.6 a single mis-tap ended
the session; on 0.1.7 it does not.

### New platform constraint: folding the temples kills a third-party app

Found by diagnosing an unexpected close, and not recorded anywhere in this
repository before. `com.rokid.os.sprite.assistserver` (pid 2041) manages a
third-party app as a `third_app` scene and cancels it when the temple arms fold:

```
ACTION_LEG_STATUS_CHANGED  leg status: 0   vendor.rkd.glasses.is_spread: 0
SceneManager -> glassLegStatusChange spread[false]
SceneManager -> cancelAllScene()  ignoreSceneList -> [[phone_call]]
   closeMark = SceneCloseMark(initiator=glass_use_event, param=glassLegStatusChange fold)
ThirdAppScene -> isSceneRunning: true, useTime: 3
SceneManager -> stopSceneAndSendToMobile sceneList -> [[third_app]]
-> ActivityManager kills dev.rokid.docscanglass.probe
-> topResumedActivity = com.rokid.os.sprite.launcher
```

Only `phone_call` is exempt. A glasses-side operator surface cannot survive the
glasses being folded, so any session state it holds must be recoverable.
`getprop vendor.rkd.glasses.is_spread` reads the current state (1 spread,
0 folded). Keep the temples spread for the whole of any measurement.

### Architecture decision

Row 1 of the `SPEC-custom-app-session.md` decision table applies:
**glasses-direct**. The camera opens, the privacy indicator behaves, the glasses
reach the server on their own Wi-Fi, and the app is launcher-visible.
CUSTOMVIEW, the Hi Rokid AIDL path, echo suppression, close tracking, and the
keep-the-phone-awake constraint are not required for the capture path.
`SPEC-custom-app-session.md` stays a Draft as the documented CUSTOMAPP +
CustomCMD transport, to be revived only if the operating network makes the
glasses Wi-Fi unusable.

### Not verified

Battery life, thermal behaviour, and Wi-Fi retention over a long operating
session were not measured; P3 measured reachability, not endurance. No OCR,
upload, analysis, or page registration was exercised on the glasses-direct path
— no such code exists yet. `AiInterceptMode.BLOCK_AI` and the `boolean` in
`appStart(String, boolean, IGlassAppCbk)` remain unknown. The relay
(`dev.rokid.docscanrelay` 0.3.16 / 21) was not changed, reinstalled, or run.

## Checkpoint — 2026-09-04 (late) suspended by the user for a design rethink

**Status: paused mid-task at the user's instruction.** The glasses-side app
`:glassdoc` builds and unit-tests clean but is **not fit for use**, and the
reason is an architectural mistake described below. Do not continue building on
it without re-reading "The mistake" first.

### What the user stopped the work to say

Three criticisms, all correct, recorded verbatim in substance:

1. **Hardware runs were used to discover things the repository already knew.**
   The exposure regression and the framing check are both examples: reading
   `PageFraming` and the relay's capture path first would have prevented both
   without touching a device.
2. **Referencing an existing element does not justify rebuilding around it.**
3. **Why was a glasses-only app written from scratch when the existing relay
   could be reused, given the control keys do not conflict?**

### The mistake

`:glassdoc` reimplemented, from nothing, what `dev.rokid.docscanrelay` already
does and already tests: the server client, the Japanese ML Kit wrapper, the
capture state machine, and a framing check that measured **worse** than the one
the relay has had all along.

The relay is an ordinary Android app at `minSdk 31`. The glasses report
**API 32**. The only part of the relay bound to the phone is the capture call
itself — `link.takePhoto(width, height, quality)` through CXR-L. Everything
downstream of the JPEG is device-independent: `JapaneseOcr`, `PageFraming`,
`ShotScore`, `CaptureReviewStore`, `DocScanApi`, the exam and explain session
flows, the HUD contract. 182 tests cover it.

**The route not taken, and the one to evaluate first next session:** run the
existing relay on the glasses and replace only the capture seam — CXR-L
`takePhoto` becomes a local `camera2` still. `:glassdoc`'s own classes would
then reduce to that seam plus whatever the glasses HUD genuinely needs.

This has not been designed or costed. It is a hypothesis, not a decision. Points
that must be checked against the code before committing to it, none of which
need hardware:

- what in `:app` actually depends on `com.rokid.cxr:client-l` and whether that
  dependency can be isolated behind an interface;
- whether `MainActivity`'s phone-sized UI can be separated from the pipeline;
- whether the relay's gesture handling collides with `:glassinput`'s normalizer
  (the user's "操作キーが被らないなら" premise — verify, do not assume);
- what `ROKID_REAL_MODE` and the exam/explain flows assume about the device.

### Verified on hardware this session

Serial `1904092623381086` (`RG-glasses`, build `1.25.012-20260901-150201`,
Android 12 / API 32), phone `F-51F` relay `0.3.16` / 21.

**The CXR-L app-control route works. This contradicts the earlier record.**

| Call | Result | Latency |
|---|---|---|
| `queryGlassAppInstalled` | `ANSWERED installed=true` | **106 ms** |
| `openApp` | `SUCCEEDED`, and the glasses foreground really became `dev.rokid.docscanglass/.TapProbeActivity` | **300 ms** |
| `uploadAndInstallApk` | **not run.** It reads `glassapp.apk` from the phone; no such file is staged | — |

The previous record — "no firmware has answered the call", two attempts ending
in `onInstallAppResult(false)` after a constant 43-44 s — no longer holds. The
untested variable named in the memory note was the **Hi Rokid glasses ADB
debugging toggle**, which is now on (that is why the cable adb works). An
earlier `openApp` `FAILED` in this session was a wrong activity name
(`com.android.settings.MainActivity` does not exist; it is
`com.android.settings.Settings`), not an API failure.

`SPEC-custom-app-session.md`'s precondition is therefore demonstrated, not
merely supported by bytecode.

### Defects found in `:glassdoc`, and their state

| Defect | Evidence | Fixed? |
|---|---|---|
| Two taps created two documents (3 and 4) | the guard sat on the response, not the request | **yes**, `ScanSession.beginOpenDocument()`, with a test |
| Pages stored 180 degrees from upright, so the recognizer read Japanese as noise | `SENSOR_ORIENTATION=270`, `JPEG_ORIENTATION=0`; rotating the stored PNG 180 makes the exam paper legible | **yes**, `ReviewFrame.MEASURED_ROTATION_DEGREES`, applied to upload, OCR and review |
| Mean luminance 16-24 of 255 against ~200 for a lit page | three stored PNGs measured | **not fixed.** See below |
| `+2 EV` exposure bias **stopped capture completing** | four consecutive 15 s timeouts, zero images, where the untouched template had returned seven stills in 785-1380 ms | **reverted.** The relay never sets exposure either |
| `FAILED` showed a blank HUD | operator could not see what to change | **yes**, the still now stays on screen through a failure |
| Home-grown border-luminance framing check, worse than the relay's | operator judgement on hardware, and it is true: `PageFraming` works from recognized-line bounding boxes and names the cut side | **partly.** `PageFraming` extracted to `:pagequality` and wired in, unverified on hardware |
| **Killed by `lowmemorykiller` at 118 MB RSS** | `Kill 'dev.rokid.docscanglass.doc' ... to free 121300kB rss`, `oom_score_adj 900` | **not fixed.** `PageOcr.MAX_EDGE_PIXELS = 2048` never subsamples: `4032/2 = 2016 < 2048`, so it decodes full 4032x3024 |
| Aiming guide is sensor-shaped, not paper-shaped | camera is 4:3 (1.33); A4/B4 is 1:1.41. A portrait page cannot fill a 4:3 guide | **not fixed** |

Measured framing of the first upload: the page filled **70.2% of frame width,
82.8% of height**, and its bounding box reached **y=3016 of 3024** — cut at the
bottom.

### Repository state

Branch `agent/real-device-test-prep`, HEAD `ce38e9e`, **nothing committed**.
PR #30 exists; do not open a duplicate.

New modules, all registered in `android-relay/settings.gradle.kts`:

- `:glassinput` — plain `java-library`. The whole `input` package moved out of
  `:glassapp` (every class was already free of android imports). Shared so
  `:glassdoc` uses the normalizer `:glassapp` validated, not a copy.
- `:pagequality` — plain `java-library`. `PageFraming` and `ShotScore` moved out
  of `:app` **keeping package `dev.rokid.docscanrelay`**, so `:app` needed no
  edit at all.
- `:glassprobe` — the throwaway spike, its four questions answered.
- `:glassdoc` — the glasses document scanner. See the defect table.

Versions: `:glassapp` 0.1.8 / 9 (behaviourally identical to 8; the input classes
moved). `:glassdoc` 0.5.0 / 5, installed on the glasses. `:glassprobe` 0.1.0 / 1.
Relay unchanged at 0.3.16 / 21.

### Verification actually run

- Android, ASCII worktree, `JAVA_HOME=C:/Users/Public/rokid-build-tools-20260901/jdk17/jdk-17.0.20.1+1`:
  `test testDebugUnitTest assembleDebug :glassdoc:lintDebug :glassapp:lintDebug`
  -> **BUILD SUCCESSFUL**. `:app` 164, `:pagequality` 18, `:glassinput` 25,
  `:glassdoc` 51, `:glassapp` 6, `:glassprobe` 6 = **270 tests, 0 failures,
  0 errors**. 164 + 18 = the 182 `:app` had before the move, so nothing was
  lost.
- `py -3.12 -m pytest -q` -> 424 passed, 1 failed. The failure is the standing
  environmental one: 57 untracked tool-generated markdown files, verified to be
  entirely inside tool directories and none tracked by git.
- `ruff check .` -> all checks passed. `git diff --check` -> clean.
- **`test` is not redundant in that command.** `:glassinput` and `:pagequality`
  are plain `java-library` modules; `testDebugUnitTest` alone silently skips
  them. `CLAUDE.md` was corrected accordingly.

### Not verified

`:glassdoc` 0.5.0 has **never completed a page on hardware**. Neither the
`PageFraming` integration, nor the 180-degree rotation as applied to a real
upload, nor the review display in its current form, has been confirmed by a
successful capture-to-upload cycle. The last hardware attempt ended with the
process killed for memory. `uploadAndInstallApk` remains unrun. Battery,
thermals and Wi-Fi endurance were measured for `:glassprobe`, not for
`:glassdoc`, whose memory profile is different.

### Resume, in order

1. **Do not touch hardware first.** Answer from `:app`'s source whether the
   relay can run on the glasses with only the capture seam replaced. That
   decides whether `:glassdoc` shrinks to a seam or is abandoned.
2. Ask the user for the paper size to design the aiming guide around; A4
   portrait was proposed and not confirmed.
3. Fix `PageOcr` subsampling regardless of route — full-resolution decode on a
   `ro.config.low_ram=true` device is what the `lowmemorykiller` acted on.
4. Underexposure is an operating condition, not a code defect: the relay's own
   earlier finding was that contrast, not resolution, limits recognition. Light
   the page rather than biasing the sensor; the bias broke capture outright.
5. Only then return to hardware, with the specific question each run answers
   written down before the cable goes in.

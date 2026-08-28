# Glasses input + real-device preparation

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
2. **Phase 1 — a minimal glasses APK**: one Activity that draws something and
   logs touch events. Install with `uploadAndInstallApk`, launch with `openApp`.
   This is the first opportunity to find out whether a tap is receivable at all.
3. **Phase 2** — if taps arrive, move capture/HUD/input ownership to the glasses
   app and leave the phone as network + OCR relay.
4. Unrelated and still open: the operator has to create `.env` with a real
   provider key before any acceptance run, and the three-shot parameter sweep
   (`docs/capture-timing-findings.md` §5) has never been run.

## Open risks

- Phase 1 needs a second Gradle module and a signing story for the glasses APK.
  Nothing about that has been investigated.
- `ROKID_REAL_MODE` in `CLAUDE.md` is still unimplemented — `refactor-instructions.md`
  D06 holds it until its scope and fail-fast policy are decided. Nothing rejects
  a placeholder analyzer today; `/v1/settings` only reports.

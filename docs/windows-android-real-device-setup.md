# Windows and Android real-device setup

Status: Current pre-device runbook. Updated 2026-09-01.

This runbook prepares the supported phone-controlled topology. It does not
modify a camera/privacy indicator and does not treat a build as device proof.

## Requirements

For the standalone `:glassdoc` review fixes, additionally verify on the target
glasses after approving installation and launch:

- Start with an explicit server, save a reading session, then restart without
  extras and confirm the same page count. Repeat from answer review.
- While the Activity is alive, deliver another Intent with a test server/key
  and guide value; confirm the new destination and visible guide. A guide-only
  update must preserve an active aiming/review state.
- Tap twice from READY: prepare capture, then shutter/stabilization. Confirm
  that a completed camera failure permits tap-to-retry and an unresolved
  capture still blocks a new shutter.
- Read the READY, READING and capture-review hints on the HUD and exercise
  their tap/swipe instructions. Confirm the full text fits the display.
- Physically observe the privacy LED during capture, after the image callback,
  and during analysis/answer review. Record APK version/hash and firmware.

These steps are pending until performed on the connected device; unit tests
and a successful APK build do not establish hardware acceptance.

- Windows with Python 3.12 available as `py -3.12`
- JDK 17 for the Android build
- Android SDK Platform 36, build tools, and platform tools
- An ASCII-only Android build path
- Android phone with Global Hi Rokid installed and signed in
- Rokid Glasses paired to Global Hi Rokid
- Private LAN shared by phone and server PC
- Internet access for Gradle, Google, Maven Central, Rokid Maven, and providers

The project pins `com.rokid.cxr:client-l:1.1.1`. The package/action assumptions
for Global Hi Rokid are isolated in `RokidGlobalLink` and must be revalidated
after Hi Rokid or YodaOS updates.

## 1. Verify the server before device access

In PowerShell, set the provider credentials and project variables in the current
process, then run the repository checks:

```powershell
py -3.12 -m pytest -q
ruff check .
```

For a physical session, configure `ROKID_REAL_MODE=1`, a non-empty
`ROKID_API_KEY`, an image-capable `ROKID_ANALYZER`, and a real
`ROKID_SOLVER`. Start the service on the private LAN:

```powershell
py -3.12 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

From the PC and phone, check `/health`. Check `/v1/settings` with the API key and
stop if either selected provider is not ready or is offline. Do not expose port
8000 to a public network.

## 2. Build in an ASCII-only path

This checkout is `C:okid-docscan-starter`, which is already ASCII, so build
it in place. Android Gradle Plugin rejects a non-ASCII path such as the
former OneDrive `ドキュメント` copy, which is not this repository. A
build copy/worktree must include the current changes; a stale worktree is not
evidence. Use JDK 17 and run from its `android-relay` directory:

```powershell
.\gradlew.bat testDebugUnitTest assembleDebug
```

Record the resulting APK path, SHA-256, versionName/versionCode, and signing
certificate fingerprint before installation. Compilation proves only the APK
was built.

## 3. Install and connect the phone

Enable Android developer options and USB debugging on the test phone. Connect
only after the server and APK gates pass. Confirm that the listed device is the
intended phone before installing the debug APK. Do not uninstall an existing
app merely to bypass a version downgrade: uninstalling erases its stored state
and requires explicit approval.

If wireless debugging is used, pair only on a trusted LAN and turn it off after
the session. Do not weaken unrelated device security settings as an automatic
setup step; record any device policy that prevents side-loading and ask the
owner how to proceed.

## 4. Configure the relay

1. Confirm the glasses are connected in Global Hi Rokid.
2. Open Rokid DocScan Relay.
3. Enter `http://<PC-private-IPv4>:8000` and the matching API key.
4. Start with rotation `90`, width `1920`, height `1080`, and quality `80`.
5. Run the server check.
6. Select Hi Rokid authorization/reconnect and grant only the requested
   permissions.
7. Wait for CXR-L connection and CUSTOMVIEW acknowledgement.

Authorization tokens and API keys must not be logged. Keep the relay activity
awake because some firmware stops photo callbacks after the phone sleeps.

## 5. Operate from the phone

Use phone controls for capture preparation, shutter, cancellation, registration,
retake, discard, reading completion, and review navigation. CUSTOMVIEW close and
`AI-exit` are lifecycle/diagnostic evidence, not operator input.

The supported capture sequence is:

```text
phone capture preparation -> acknowledged AIMING -> phone shutter
-> acknowledged stabilization -> one takePhoto -> callback -> phone review
-> explicit phone register/retake/discard
```

The `4032x3024` no-callback observation is historical and its cause was not
proven. Do not attribute it conclusively to Binder size. Start with the supported
`1920x1080 q80` setting and change one variable at a time only in a separately
recorded capture-quality experiment.

## 6. Physical acceptance

Before the first photo, arrange an independent camera so the physical indicator
stays visible before, during, and after capture. Complete
`docs/device-verification-checklist.md`, including three successful captures,
the cancellation case, timeout/disconnect handling, normalized PNG persistence,
provider readiness, and HUD/recovery checks.

Do not claim silent/no-flash capture or guaranteed indicator timing from a build
or callback log. Those behaviors require physical confirmation on the exact
recorded firmware and app tuple.

# Android relay for Rokid Glasses

This module is the phone-side executable that was previously missing from the
repository. It connects a Global Hi Rokid installation to the FastAPI server:

```text
Rokid Glasses --CXR-L/BT--> Global Hi Rokid --AIDL--> Android relay
    --JPEG + ML Kit OCR/HTTP--> DocScan server --3-line JSON--> CUSTOMVIEW HUD
```

It does not copy or redistribute Rokid's SDK. Gradle resolves the official
`com.rokid.cxr:client-l:1.0.1` AAR from Rokid's Maven repository, and
`RokidGlobalLink` binds its AIDL surface to the Global package
`com.rokid.sprite.global.aiapp`.

The Android client is version `0.3.2` and implements glasses-view contract
`1.8.0`.

## Build on Windows

Prerequisites:

- Android Studio compatible with Android Gradle Plugin 9.2.1
- Android SDK Platform 36
- JDK 17 (the Android Studio bundled runtime is suitable)
- internet access to Google Maven, Maven Central, Rokid Maven and Gradle

PowerShell:

```powershell
cd android-relay
.\gradlew.bat testDebugUnitTest assembleDebug
adb install -r .\app\build\outputs\apk\debug\app-debug.apk
```

`gradlew.bat` uses `build-windows.ps1`, downloads Gradle 9.4.1 once, and verifies
its pinned SHA-256 before execution. If neither `ANDROID_HOME`,
`ANDROID_SDK_ROOT`, nor `local.properties` is configured, the script uses the
standard Android Studio SDK location under `%LOCALAPPDATA%\Android\Sdk` when it
exists. Android Studio can also open this directory as an independent project.

On Windows, the physical checkout path must contain ASCII characters only.
Android Gradle Plugin rejects paths such as a localized OneDrive
`ドキュメント` directory, and disabling its path check is not sufficient:
Gradle test workers then fail to load the compiled test classes. Create an
ASCII-only worktree when the main checkout is under a localized path:

```powershell
git worktree add C:\Users\Public\rokid-docscan-build HEAD
cd C:\Users\Public\rokid-docscan-build\android-relay
.\gradlew.bat testDebugUnitTest assembleDebug
```

## Runtime requirements

- Android phone: Android 12 / API 31 or newer
- Global Hi Rokid installed and signed in
- Rokid Glasses paired and connected in Hi Rokid
- phone can reach the Windows server address over the LAN
- server is started with a real analyzer/solver for useful answers, for example
  `ROKID_ANALYZER=openai` and `ROKID_SOLVER=openai`

The bundled Japanese ML Kit model performs local OCR. The original JPEG and the
rotation applied by ML Kit are uploaded together; the server stores a normalized
PNG in that same orientation as the authoritative source. If local OCR is empty,
a configured server-side vision analyzer can recover it from the photo.

Photography is deliberately two-stage. A user touchpad tap closes the current
CustomView and enters `AIMING`, where the glasses show a composition reticle.
An `AI-assist-start` long action starts a 1.5-second stabilization countdown and only then
requests `takePhoto(1920, 1080, 80)`. The countdown starts only after the
replacement CustomView's open callback acknowledges the current generation.
A short or double-short action in `AIMING` cancels and returns without a photo;
any gesture in `STABILIZING` cancels the countdown. An open fault or
acknowledgement timeout fences the callback epoch, cancels the armed capture,
and requires **Hi Rokid認可・再接続** before another view request. It never
captures on the first tap or after a failed acknowledgement.

After the JPEG and local OCR arrive, the relay enters `CAPTURE_REVIEW`; the
photo is still local and unregistered. A short or double-short action returns to
`AIMING` for a same-page retake; only a long action from that state starts the
delayed capture. A long action in `CAPTURE_REVIEW`, delivered as
`AI-assist-start`, uploads the pending photo.
The phone provides three fallback buttons:
**この写真を登録**, **同じページを撮り直す**, and **未登録写真を破棄**.
OCR 0 characters is shown as a warning but does not prevent an explicit
registration. Until registration succeeds, the target server page and next page
index do not advance. The document itself may already exist because it is created
before the first photo request.

The unregistered JPEG, OCR result, page index, and rotation are kept in app-private
storage and restored to `CAPTURE_REVIEW` after an app restart. Restoration never
uploads or registers the photo automatically. Once the server confirms a
registration, a page-index plus JPEG-SHA-256 commit marker prevents a failed
local cleanup from resurrecting that registered JPEG as pending.

## Controls

The public CXR-L surface does not deliver the dedicated camera shutter-button
event. The relay uses two observable sources instead: a user-initiated CustomView
close as a discrete touchpad tap, and `AI-assist-start` as the long action.
Programmatic closes used to refresh a view are classified within the acknowledged
callback generation and do not become input. View callbacks are accepted only for
that generation. If one physical gesture produces both a close and an AI event, the
short/long interpreter debounces and coalesces them. Every accepted source is
written to the phone log for device verification.

| Phase | Short / double-short | Long / `AI-assist-start` |
|---|---|---|
| Ready / Reading | Short: arm the next page; delivered double-short uses the compatibility mapping below | Finalize and solve when Reading |
| Aiming | Cancel and return without taking a photo | After view acknowledgement, wait 1.5 seconds and request one photo |
| Stabilizing | Cancel without taking a photo | Cancel without taking a photo |
| Capture review | Arm a same-page retake and show the reticle | Register the pending photo |
| Review | Short: next text/problem; delivered double-short: previous | Close and start a new document |

For normal two-stage capture, use a short action to open the reticle and a
separated long action to start stabilization. Short/double-short in Aiming and
every gesture in Stabilizing are fail-safe cancellation paths.
Rokid's system-level double tap exits the current view, so an accidental rapid
double tap can return to the default glasses menu instead of reaching the relay
twice. After the resulting `AI-exit`, the relay waits for the system transition
and re-presents the current DocScan view without requesting or registering a
photo. The close used to enter the system menu is discarded instead of being
replayed later as a shutter/registration command. Only firmware that actually
delivers a coalesced `DOUBLE_SHORT` to the
app uses the compatibility mapping: previous page in Reading, same-page retake
in Capture review, previous view in Review, or cancel in Aiming.

Equivalent register and same-page retake actions, plus an unregistered-photo
discard action, are available as phone fallback controls for setup, diagnostics,
and recovery. After connection, capture, same-page retake, registration,
Reading finalization, and review can be completed on the glasses. The phone
activity must remain visible because current Hi Rokid builds can stop photo
callbacks after the phone sleeps; this activity applies `FLAG_KEEP_SCREEN_ON`.

## Capture safety lifecycle

`client-l:1.0.1` exposes one-shot `takePhoto` plus success/error callbacks, but
no documented still-photo cancel or camera-close method. The relay therefore
uses a fail-closed capture lease:

- all required callbacks must register successfully before photography is enabled;
- only one `takePhoto` may be in flight;
- a success or error callback releases the lease;
- if Binder fails before the `takePhoto` result is known, the request is treated
  as potentially active and is blocked immediately;
- after the 30-second watchdog expires, another photo, finalization, workflow
  reset, and configuration changes are blocked because camera completion is
  unknown;
- a late callback is discarded but releases the block; otherwise the CXR-L
  service binding must be reset. A glasses connected/disconnected status event
  alone retains the block because callbacks from that binding may still arrive.
  Re-running **Hi Rokid認可・再接続** explicitly unbinds the old service first;
- every bind owns a separate callback epoch. Callbacks already dispatched by an
  old service binding are ignored after disconnect/reconnect and cannot release
  or upload data for a newer capture.

The timeout is not treated as proof that the camera or privacy LED is off. This
prevents a retry from opening a second capture while the first request may still
be active.

The native sensor resolution is not a safe setting for this API. On the verified
Hi Rokid build, `takePhoto(4032, 3024, 80)` made the JPEG callback exceed the
Binder transaction limit and no usable callback arrived. Keep the verified
`1920 x 1080 / 80` request unless a different transport is implemented.

## Known device-dependent behavior

- Hi Rokid authorization may show an unverified-app confirmation. It must be
  accepted on the phone once.
- `customViewUpdate` may acknowledge without redrawing on client-l 1.0.1. The
  relay closes and reopens the same black-background view as a reliable update.
  These app-requested closes are tracked and never treated as user taps.
- After a photo callback, the relay renders a downsampled capture preview in the
  glasses CustomView as well as on the phone. The public CXR-L still-photo
  surface exposes neither a pre-capture live camera preview nor an autofocus
  command/status callback. The reticle helps framing but does not indicate focus.
- The public `client-l:1.0.1` surface does not provide the dedicated camera
  shutter-button event. Use the touchpad/CustomView interaction documented above.
- Photo orientation differs by firmware. The verified device defaults to 90
  degrees. A phone rotation selection of 0/90/180/270 degrees is applied to the
  next same-page re-photograph; it does not rewrite the pending photo.
- The camera has fixed focus. Rokid specifies a 34 cm-to-infinity depth of
  field. Operate at 40-60 cm, align the paper center with the `+`, and hold still
  from the 1.5-second countdown through the callback. Display and camera fields
  of view differ, so the reticle is not an exact capture boundary; verify all
  four corners in the post-capture preview.
- The relay performs neither automatic photography nor automatic registration.
  Each photo requires an explicit long action from an acknowledged Aiming view,
  and each upload requires an explicit long action or phone fallback.
- The privacy LED is hardware-controlled. This app never disables or bypasses
  it. Confirm that it lights during `takePhoto` and turns off after the image
  callback on the actual firmware.
- The separate ADB LED utility is never imported or invoked by this Android
  relay. It has no Android setting, intent, environment switch, or HTTP hook.

See
[`../docs/windows-android-real-device-setup.md`](../docs/windows-android-real-device-setup.md)
for the complete server, firewall, installation and validation procedure.

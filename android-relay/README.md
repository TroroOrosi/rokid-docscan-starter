# Android relay for Rokid Glasses

Status: Current relay contract. Updated 2026-09-01.

This module is the phone-side executable that was previously missing from the
repository. It connects a Global Hi Rokid installation to the FastAPI server:

```text
Rokid Glasses --CXR-L/BT--> Global Hi Rokid --AIDL--> Android relay
    --JPEG + ML Kit OCR/HTTP--> DocScan server --3-line JSON--> CUSTOMVIEW HUD
```

It does not copy or redistribute Rokid's SDK. Gradle resolves the official
`com.rokid.cxr:client-l:1.1.1` AAR from Rokid's Maven repository, and
`RokidGlobalLink` binds its AIDL surface to the Global package
`com.rokid.sprite.global.aiapp`.

The Android client version and the glasses-view contract it implements are
recorded once, in `README.md`; the sources are `app/version.py` and
`android-relay/app/build.gradle.kts`.

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
ASCII-only worktree only when the main checkout is under a localized path.
`C:okid-docscan-starter` is not, and builds in place:

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

The bundled Japanese ML Kit model performs local OCR. The transport JPEG and the
rotation used for OCR are uploaded together; the server stores a normalized PNG
in that same orientation as the authoritative source. It does not separately
retain the raw upload as an original-file archive. If local OCR is empty,
a configured server-side vision analyzer can recover it from the photo.

Photography is deliberately two-stage and phone-controlled. The phone enters
`AIMING`, where the glasses show a composition reticle. A phone shutter action
opens stabilization guidance and requests `takePhoto(1920, 1080, 80)` only
after the replacement CustomView's open callback acknowledges the current
generation. A phone cancellation before the request returns without a photo.
An open fault or acknowledgement timeout fences the callback epoch, cancels the
armed capture, and requires **Hi Rokid認可・再接続** before another view request.

After the JPEG and local OCR arrive, the relay enters `CAPTURE_REVIEW`; the
photo is still local and unregistered. CUSTOMVIEW/AI callbacks do not change
state. The phone provides three authoritative buttons:
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

The inspected CXR-L surface does not deliver a dedicated camera shutter-button
event, and CUSTOMVIEW close/`AI-exit` callbacks do not provide trustworthy
operator provenance. They are lifecycle evidence only. The supported control
surface is therefore the phone.

| Phase | Glasses CUSTOMVIEW | Phone controls |
|---|---|---|
| Ready / Reading | Status only | Arm next/previous page; finalize reading |
| Aiming | Reticle only | Request one photo after view acknowledgement; cancel |
| Stabilizing | Hold-still guidance only | Cancel before `takePhoto` |
| Capture review | Status/preview only | Register, retake, or discard pending photo |
| Review | HUD output only | Previous/next/new document |

For normal capture, the phone opens the reticle, waits for the matching open
callback, then starts stabilization and one photo request. A view close or
`AI-exit` never requests, cancels, registers, or navigates a document.

Register, same-page retake, pending-photo discard, reading finalization, and
review navigation are phone controls. The phone
activity must remain visible because current Hi Rokid builds can stop photo
callbacks after the phone sleeps; this activity applies `FLAG_KEEP_SCREEN_ON`.

## Capture safety lifecycle

The inspected `client-l:1.1.1` exposes one-shot `takePhoto` plus success/error callbacks, but
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
Hi Rokid build, `takePhoto(4032, 3024, 80)` produced no usable callback. Binder
buffer pressure is a plausible cause, not a proven root cause. Keep the measured
`1920 x 1080 / 80` request unless a different transport is implemented.

## Known device-dependent behavior

- Hi Rokid authorization may show an unverified-app confirmation. It must be
  accepted on the phone once.
- `customViewUpdate` may acknowledge without redrawing on the measured service. The
  relay closes and reopens the same black-background view as a reliable update.
  These app-requested closes are tracked and never treated as user taps.
- After a photo callback, the relay renders a downsampled capture preview in the
  glasses CustomView as well as on the phone. The public CXR-L still-photo
  surface exposes neither a pre-capture live camera preview nor an autofocus
  command/status callback. The reticle helps framing but does not indicate focus.
- The inspected `client-l:1.1.1` surface does not provide the dedicated camera
  shutter-button event. Use the phone controls documented above.
- Photo orientation differs by firmware. The verified device defaults to 90
  degrees. A phone rotation selection of 0/90/180/270 degrees is applied to the
  next same-page re-photograph; it does not rewrite the pending photo.
- Start testing at 40-60 cm, align the paper center with the `+`, and hold still
  from stabilization through the callback. This is an operating heuristic, not
  a focus guarantee for every SKU. Display and camera fields
  of view differ, so the reticle is not an exact capture boundary; verify all
  four corners in the post-capture preview.
- The relay performs neither unattended photography nor automatic registration.
  Each photo and upload requires an explicit phone action.
- The privacy LED is hardware-controlled. This app never disables or bypasses
  it. Confirm that it lights during `takePhoto` and turns off after the image
  callback on the actual firmware.
- No indicator-modification utility is imported or invoked by this relay.

See
[`../docs/windows-android-real-device-setup.md`](../docs/windows-android-real-device-setup.md)
for the complete server, firewall, installation and validation procedure.

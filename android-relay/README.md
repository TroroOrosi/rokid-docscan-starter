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
its pinned SHA-256 before execution. Android Studio can also open this directory
as an independent project.

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

## Controls

The public CXR-L AIDL surface exposes AI key down/up but not the complete touch
gesture stream. The relay therefore uses timing patterns that are actually
observable:

| Phase | Short press | Two short presses | Long press |
|---|---|---|---|
| Reading | Photograph next page | Re-photograph previous page | Finalize and solve |
| Review | Next text/problem | Previous text/problem | Close and start a new document |

The same actions are available as phone buttons for setup and diagnostics.
After connection, ordinary capture/review does not require touching the phone,
but the activity must remain visible. Current Hi Rokid builds can stop photo
callbacks after the phone sleeps, so this activity applies `FLAG_KEEP_SCREEN_ON`.

## Known device-dependent behavior

- Hi Rokid authorization may show an unverified-app confirmation. It must be
  accepted on the phone once.
- `customViewUpdate` may acknowledge without redrawing on client-l 1.0.1. The
  relay closes and reopens the same black-background view as a reliable update.
- Photo orientation differs by firmware. Select 0/90/180/270 degrees on the
  setup screen and verify OCR before a multi-page run.
- The privacy LED is hardware-controlled. This app never disables or bypasses
  it. Confirm that it lights during `takePhoto` and turns off after the image
  callback on the actual firmware.

See
[`../docs/windows-android-real-device-setup.md`](../docs/windows-android-real-device-setup.md)
for the complete server, firewall, installation and validation procedure.

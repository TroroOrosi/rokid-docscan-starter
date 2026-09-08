# rokid-docscan-starter development guide

Status: Current engineering contract. Updated 2026-09-01.

This repository contains two cooperating runtimes:

- `app/`: the FastAPI document-analysis and answer server.
- `android-relay/`: the Android-phone relay for Global Hi Rokid and Rokid
  Glasses.

The supported real-device topology is:

```text
Rokid Glasses -> Global Hi Rokid -> Android relay -> FastAPI server -> HUD
```

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

## Camera and privacy

The privacy LED is controlled by the glasses hardware/firmware. Supported code
must never disable, obscure, spoof, or bypass it.
A real-device acceptance run must physically confirm:

1. the LED is lit while `takePhoto` is active;
2. it turns off after the image callback; and
3. it remains off during analysis and answer review.

Shutter sound, flash, and capture indicators are device-controlled unless a
documented public SDK control is added. Do not claim silent or no-flash capture
without physical verification on the exact firmware.

## Server invariants

- Store the orientation-corrected, normalized PNG as the authoritative server
  image. The relay upload may be a JPEG, but the raw upload bytes are not
  persisted.
- A configured cloud analyzer may transcribe/correct OCR and describe diagrams
  from the image. Finalization must fail clearly if a photo has no usable text
  and no image-capable analyzer is configured.
- Persist analyzer-derived text before segmenting problems.
- Pass the originating page image to image-capable solvers.
- Keep document finalization idempotent and page replacement keyed by
  `(document_id, page_index)`.
- `ROKID_REAL_MODE=1` must reject placeholder analyzer/solver combinations.
- Never log API keys, Hi Rokid authorization tokens, uploaded page contents, or
  provider credentials.

## Development and verification

Server:

```bash
python -m pytest -q
ruff check .
```

Android relay:

```bash
gradle --no-daemon -p android-relay test testDebugUnitTest assembleDebug
```

`test` is not redundant: `:glassinput` is a plain `java-library`, so its
tests run under `test` and `testDebugUnitTest` alone would skip them
silently.

The Android project requires JDK 17, Android SDK Platform 36, and internet
access for Google, Maven Central, Rokid Maven, and Gradle dependencies. The
Windows bootstrap is `android-relay\gradlew.bat`.

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

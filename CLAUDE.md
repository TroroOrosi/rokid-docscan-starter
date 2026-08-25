# rokid-docscan-starter development guide

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
- The public CXR-L 1.0.1 AIDL surface does not expose arbitrary recognition or
  answer text from the AI running on the glasses. The current production path
  therefore uses the phone OCR and a configured server analyzer/solver.
- Use the official `com.rokid.cxr:client-l:1.0.1` dependency. Do not commit,
  copy, or redistribute Rokid AAR files.
- Global Hi Rokid uses package `com.rokid.sprite.global.aiapp`. Keep the
  package/action assumptions isolated in `RokidGlobalLink` and revalidate them
  after Hi Rokid or YodaOS updates.
- YodaOS reserves long press (record/audio toggle), double tap (exit), two-finger
  tap (AI) and two-finger swipes for itself. A third-party app cannot receive
  them, so never assign a relay action to one. See the official gesture table in
  `docs/glasses-ux-contract.md`.
- Measured on Hi Rokid G1.12.10.0815 with CXR-L service `1.0.0 code 10000`:
  `onAiKeyDown`/`onAiKeyUp` never fire, and CustomView closes always arrive
  `userInitiated=false`. A user-originated `AI-exit` is the only glasses input
  the relay receives, and it carries no press duration. Treat it as the short
  action only. Committing actions (登録 / 読取完了 / シャッター) stay on the
  phone until a second signal is proven on hardware.
- CUSTOMVIEW output is a black background, green text, and at most three lines.
  Current Global builds may require close-and-open for a reliable redraw.
- Keep the phone activity awake during a session. Some firmware stops photo
  callbacks after the phone sleeps.

## Camera and privacy

The privacy LED is controlled by the glasses hardware/firmware. Application
code must never attempt to disable, bypass, hide, or misrepresent it. A
real-device acceptance run must physically confirm:

1. the LED is lit while `takePhoto` is active;
2. it turns off after the image callback; and
3. it remains off during analysis and answer review.

Shutter sound, flash, and capture indicators are device-controlled unless a
documented public SDK control is added. Do not claim silent or no-flash capture
without physical verification on the exact firmware.

## Server invariants

- Store the original page image as the authoritative source.
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
gradle --no-daemon -p android-relay testDebugUnitTest assembleDebug
```

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

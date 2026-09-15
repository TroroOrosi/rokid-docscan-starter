# Rokid DocScan real-device verification checklist

Status: Current acceptance form. Updated 2026-09-15.

A build is not hardware verification. Complete every applicable item on the
exact version tuple; otherwise report “build verified, device verification
pending.”

## Evidence record

| Item | Recorded value |
|---|---|
| Date/time and tester | |
| Phone model / Android / API | |
| Global Hi Rokid version / versionCode | |
| Glasses model / YodaOS build | |
| CXR-L service version / versionCode | |
| APK version / SHA-256 / signing fingerprint | |
| Server commit / APP / API version | |
| Glasses View contract | |
| Analyzer / model / readiness | |
| Solver / model / readiness | |
| Capture width / height / quality / rotation | |
| PC LAN address / network profile | |

Never record credentials, authorization tokens, page content, or provider
request/response bodies.

## Static and build gates

- [ ] `py -3.12 -m pytest -q` passes.
- [ ] `ruff check .` passes.
- [ ] JDK 17, Android SDK Platform 36, and Android build tools are selected.
- [ ] The Android checkout/build path contains ASCII characters only.
- [ ] `gradlew.bat testDebugUnitTest assembleDebug` passes in that checkout.
- [ ] The APK version and checksum above match the installed artifact.
- [ ] The supported relay/runtime has no import or UI/API/intent route to the
      quarantined indicator experiment.

## Server and network gates

- [ ] Server runs with `ROKID_REAL_MODE=1` and a non-empty API key.
- [ ] `/health` is reachable from the PC and phone on the intended private LAN.
- [ ] `/v1/settings` reports the intended analyzer and solver ready and
      `offline=false`; a placeholder causes startup/request failure.
- [ ] An incorrect bearer token returns 401.
- [ ] Port 8000 is not exposed to a public network or the internet.

## Hi Rokid and lifecycle gates

- [ ] Authorization succeeds and the required CXR-L callbacks all register.
- [ ] A registration failure prevents capture.
- [ ] CUSTOMVIEW open acknowledgement is recorded before stabilization starts.
- [ ] Close, `AI-exit`, and AI key callbacks never invoke capture, cancellation,
      registration, finalization, or navigation.
- [ ] A CUSTOMVIEW ACK error/timeout prevents `takePhoto` and requires a new
      callback epoch.
- [ ] Service disconnect returns the relay to disconnected state.
- [ ] The phone activity remains awake and callbacks continue during a session.

## Capture and data gates

- [ ] Phone capture preparation shows `AIMING` with zero photo requests.
- [ ] One phone shutter action produces exactly one photo request after the
      acknowledged stabilization view/delay.
- [ ] Phone cancellation before the request produces zero photo requests.
- [ ] A non-empty image callback produces a correctly oriented phone/glasses
      preview and OCR result.
- [ ] Register, retake, and discard are explicit phone actions.
- [ ] Registration success advances the page; failure does not.
- [ ] Re-upload of the same `(document_id, page_index)` replaces the page.
- [ ] The server stores an orientation-corrected normalized PNG and does not
      claim a separately retained raw JPEG archive.
- [ ] Analyzer-derived text is persisted before segmentation.
- [ ] The solver receives the originating page image when image capable.
- [ ] A photo with no usable text and no image-capable analyzer fails clearly.
- [ ] Photo timeout/disconnect blocks another request until a new binding epoch;
      a late callback is discarded and cannot complete a newer request.

## Physical indicator and device-controlled cues

The operator waived the external LED audit on 2026-09-15 because the indicator
is system-controlled. The LED observations below are optional evidence, not an
acceptance gate. Leave unobserved items unchecked. Do not request an external
camera as a prerequisite. Application logs do not prove physical light state;
the code must never disable, obscure, spoof, or bypass the indicator.

- [ ] Indicator is visibly off for at least five seconds before capture.
- [ ] Indicator is visibly lit while the camera is active.
- [ ] Indicator turns off after the image callback.
- [ ] Indicator remains off through OCR, upload, analysis, and answer review.
- [ ] Successful capture is repeated at least three times.
- [ ] Cancellation before `takePhoto` never lights the indicator.
- [ ] Timeout/disconnect is treated as unknown, not as proof of indicator-off.
- [ ] Actual shutter sound, flash, and capture-indicator behavior is recorded
      for this firmware without claiming application control.

## HUD and recovery

- [ ] HUD is black, green, and at most three lines.
- [ ] A redraw does not turn a lifecycle callback into an operator action.
- [ ] Registered-page state resumes from `/scan-status` after reconnect.
- [ ] App restart/reconnect does not automatically take or register a photo.
- [ ] No sensitive content appears in logs.

## Result

| Area | Pass / fail / N/A | Evidence reference |
|---|---|---|
| Server tests and real mode | | |
| Android tests and APK | | |
| Hi Rokid connection/lifecycle | | |
| Capture/OCR/data persistence | | |
| Physical indicator/cues | | |
| HUD/recovery | | |

Any failed or unperformed applicable item blocks “real-device verified.”

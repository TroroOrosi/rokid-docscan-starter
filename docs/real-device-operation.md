# Real-device operation

Status: Current supported path. Updated 2026-09-01.

The supported topology is:

```text
Rokid Glasses -> Global Hi Rokid -> Android relay -> FastAPI server -> HUD
```

The phone is the operator control surface. CUSTOMVIEW close, `AI-exit`, and AI
key callbacks are lifecycle/diagnostic evidence only and must not trigger a
photo, cancellation, registration, finalization, or navigation.

## Before a session

1. Record the phone, Android, Global Hi Rokid, YodaOS, glasses, CXR-L service,
   relay APK, server commit, and configured provider versions.
2. Start the server with `ROKID_REAL_MODE=1`, an API key, an image-capable
   analyzer, and a non-placeholder solver.
3. Confirm `/health` and `/v1/settings` from the phone. Do not proceed if the
   intended analyzer or solver is not ready or reports `offline=true`.
4. Open the relay, keep its activity awake, authorize Hi Rokid, and wait for
   the CXR-L connection and CUSTOMVIEW open acknowledgement.

## Capture one page

1. On the phone, select capture preparation. `AIMING` opens on the glasses;
   this does not call `takePhoto`.
2. Hold the whole page in view. The reticle is an alignment aid, not a camera
   boundary or focus indicator.
3. On the phone, request the shutter. Only after the requested view generation
   is acknowledged does the stabilization delay begin, followed by one
   `takePhoto(1920, 1080, 80)` call.
4. Keep still until an image or explicit image-error callback arrives. A
   timeout does not prove the camera stopped; reconnect the CXR-L binding before
   another attempt.
5. Inspect the phone preview, orientation, all four corners, blur, and OCR. Use
   phone buttons to register, retake, or discard. Nothing is uploaded merely
   because a CUSTOMVIEW callback arrived.

The relay uploads the captured JPEG, rotation, and phone OCR. The server stores
an orientation-corrected normalized PNG as the authoritative page image; the
transport JPEG is not separately retained as an original-file archive.

## Finalize and review

Use the phone to finish reading. The configured analyzer persists corrected
text and diagram descriptions before problem segmentation, and an image-capable
solver receives the originating normalized page image. Use phone controls for
review navigation and a new document. HUD output remains black, green, and at
most three lines.

## Camera state and indicator evidence

Supported code never changes, obscures, spoofs, or bypasses the camera/privacy
indicator. A second camera must continuously record the physical indicator:

- off before the request;
- lit while the device camera is active;
- off after the image callback; and
- still off during OCR, upload, analysis, and review.

These observations are acceptance evidence for the exact recorded version
tuple, not a guarantee for another firmware. Callback timestamps alone are not
physical-light evidence. See
`docs/hardware-measurements.md`.

## Stop conditions

Stop without taking another photo if a required callback registration fails,
CUSTOMVIEW acknowledgement fails, a photo callback times out, the service
disconnects during capture, the indicator state is uncertain, or the server is
not using the intended real providers. Preserve content-free timing/error logs,
recreate the binding, and begin a new capture generation only after the state is
known.

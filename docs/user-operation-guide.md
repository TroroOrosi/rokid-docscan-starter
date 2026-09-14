# User operation guide

Status: Current phone-controlled workflow. Updated 2026-09-14.

## What this system does

Rokid Glasses capture a physical page through CXR-L. The Android relay runs
bundled Japanese ML Kit OCR and sends the photo, rotation, and OCR to the
FastAPI server. The server normalizes the image, optionally corrects/transcribes
it with an image-capable analyzer, segments problems, solves them, and returns a
compact HUD view.

Text-only upload remains API compatibility support; it is not the real-device
primary path. The public CXR-L surface inspected for this project does not
provide arbitrary text or answers produced by an AI running on the glasses.
`POST /solutions` therefore ingests answers produced elsewhere; it is not the
glasses answering by themselves.

## Answer route and what it costs you

The configured server solver answers the problems. The current primary route is
`ROKID_SOLVER=chatgpt-web`, which drives your own signed-in ChatGPT web session
through a Chrome debugging port. It needs no API key.

**Automating the ChatGPT web UI is against OpenAI's terms of use, and the
account can be restricted.** This is your decision to make, and it is recorded
here because the route is the default one. `ROKID_SOLVER=openai|gemini|claude`
with an API key is the supported alternative, and `ROKID_SOLVER_TIERS` orders
the fallbacks.

Every chatgpt-web measurement this repository owns was taken against Chrome on
a PC. Pointing `ROKID_CHATGPT_CDP` at a phone-side browser has never been run.
Do not plan a session that assumes it works.

## Start

1. Connect the glasses in Global Hi Rokid.
2. Start the configured server and verify it from the phone.
3. Open Rokid DocScan Relay, enter the LAN server URL and API key, and authorize
   Hi Rokid.
4. Wait for both the CXR-L connection and the glasses display acknowledgement.

Do not expose the FastAPI port to the public internet. Do not put API keys,
authorization tokens, page content, or provider credentials in logs or test
records.

## Read pages

For each page:

1. Press the phone's capture-preparation control.
2. Center the complete page in the reticle and hold still.
3. Press the phone shutter control once.
4. Wait for the callback and local OCR.
5. Inspect the phone preview. Register it only if orientation, corners, text,
   and blur are acceptable; otherwise retake or discard from the phone.

CUSTOMVIEW taps and close/`AI-exit` callbacks are not a supported control path.
They do not trigger capture or commit data. The phone is required for capture,
retake, registration, completion, and review navigation.

After registration, the server retains the normalized orientation-corrected PNG
as the authoritative page image and the persisted analyzer-derived text. A new
upload with the same `(document_id, page_index)` replaces that page.

## Finish and review

After the last registered page, press the phone's reading-complete control.
If the server reports that no usable text or image-capable analyzer exists,
retake the page or configure the analyzer; do not treat placeholder output as a
real-device result. Navigate answers and start a new document with phone
controls.

## Physical camera indicator

Do not modify or cover the camera/privacy indicator. During acceptance testing,
have another person or an independent camera observe it continuously before,
during, and after capture. It must be lit while the camera is active and off
after the image callback, throughout analysis and review. If a callback times
out or the indicator state is uncertain, stop and reconnect rather than taking
another photo.

Shutter sound, flash, and capture indicators are device-controlled unless a
future public SDK control is separately documented and physically verified for
the exact firmware.

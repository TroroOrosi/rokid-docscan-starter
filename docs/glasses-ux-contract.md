# Glasses operator contracts

Status: Current phone and standalone surface contracts. Updated 2026-09-16.

The intended startup and complete operator flow are in the current section of
[`tasks/plan.md`](../tasks/plan.md). The on-glasses mode chooser and normal-mode
capture without HTTP are implemented. Listening also starts locally before HTTP.
Progressive answer updates remain planned. A phone-side watcher has returned the
chooser after one physical fold/unfold; wearing-only and disconnected transitions
remain unverified (see the runbook for its limits).
[`requirements-audit.md`](requirements-audit.md) retains the pre-change audit;
the current implementation and checks are recorded in
[`multimodal-scan.md`](../.agents/progress/archive/multimodal-scan.md).

**The `:glassdoc` table below is the decided operator surface** (operator,
2026-09-14): the venue runs the standalone app over a phone access point and the
phone is not touched during a session. The phone/CUSTOMVIEW rules above it
describe the frozen relay route, which stays as the fallback. Neither surface
has passed the physical checklist; the `:glassdoc` gestures are implemented and
unit-tested, not accepted on hardware.

Earlier revisions mapped tap, double tap, long press, and two-finger swipes to
capture, completion, and review actions. Those mappings were based on platform
gesture descriptions and incomplete callback observations. Later testing on Hi
Rokid `G1.12.10.0815` / CXR-L service `1.0.0 code 10000` did not establish a
trustworthy CUSTOMVIEW operator-input channel.

The phone/CUSTOMVIEW route retains these rules under the current Glasses View
contract (`app/version.py`):

- CUSTOMVIEW close, `AI-exit`, and AI key callbacks are lifecycle/diagnostic
  events only.
- The Android relay maps every such event to no operator command.
- Capture preparation, shutter, cancellation, registration, retake, discard,
  reading completion, and navigation are phone controls.
- HUD output remains black, green, static, and at most three lines.
- The relay makes no camera request during analysis/review. The physical
  indicator is system-controlled; the operator waived the external LED audit on 2026-09-15.

`GET /v1/settings.operations` publishes `"phone"` for every supported action.
`GET /v1/settings.input` retains a legacy/unverified KeyCode map only for
diagnosis and explicitly publishes `operator_actions_enabled:false`.
`GET /v1/settings.operation_routes.glassdoc` publishes the separate standalone
controls and explicitly marks physical acceptance as pending.

The standalone `:glassdoc` APK has a separate local input adapter
(its version is in `android-relay/glassdoc/build.gradle.kts`).

Automatic capture is enabled only on `:glassdoc`. A tap requests a manual shot while
waiting; during the visible still review it retakes. No input commits after 3 seconds.
BACK ends capture after the last review; in listening mode a later BACK ends audio.
Two BACK gestures within three seconds exit answer reading. Reader-menu BACK returns
one level. Distinct rapid KeyEvent gestures are retained; physical correlation is
still unverified on the new APK. A second BACK during the last photo review ends
audio while preserving the still. Retaking does not restart audio. Event-time
cancellation across the commit boundary is pending.
Full operation and power/error behavior:
[`multimodal-scan.md`](multimodal-scan.md). Physical acceptance is pending.

Startup shows normal/listening choices; capture starts only after selection.
Unfinished captures and the latest saved answers can be selected explicitly.
Starting another capture preserves earlier records and their pending photos.
Normal-mode photos are committed locally before background HTTP upload, and
unacknowledged revisions remain available after restart. Storage errors retain
originals and stop processing; transient upload failures retry separately from capture.
Listening starts locally before the server document is available. REC appears only
after valid PCM samples arrive; natural zero-valued samples remain valid audio.
Missing samples, read failures, OS silencing, or an observed input-device change stop
recording and preserve the interrupted originals. These checks need hardware calibration.

Launching without a `server` extra reuses the saved URL. A new Intent applies
explicit `server`/`key` overrides; a guide-only Intent updates and saves the
guide without restarting the workflow. URL and key are encrypted together with
an Android Keystore key in app-private no-backup storage. A key is reused only for
the same server. Initial provisioning can use the private `setup.properties` file;
matching plaintext setup is removed after encrypted persistence succeeds.
Configuration changes during capture are rejected and preserve the active
workflow. Pending photos cannot be redirected to another server.

A camera failure or unresolved timeout keeps UNKNOWN and blocks another photo until
a fresh app/session generation. Two BACK gestures remain available to exit ERROR. HUD hints on
this local surface name these gestures instead of phone buttons; the phone
relay's CUSTOMVIEW input policy is unchanged. This patch still requires the
physical acceptance checklist on the installed APK and firmware.

Intent handling follows the Android [Activity.onNewIntent contract](https://developer.android.com/reference/android/app/Activity#onNewIntent(android.content.Intent)):
the Activity stores the received Intent with `setIntent` before applying its extras.

See `docs/cxr-l-integration.md`, `docs/real-device-operation.md`, and
`docs/device-verification-checklist.md` for the current behavior.

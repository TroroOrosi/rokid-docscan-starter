# Glasses operator contracts

Status: Current phone and standalone surface contracts. Updated 2026-09-09.

Earlier revisions mapped tap, double tap, long press, and two-finger swipes to
capture, completion, and review actions. Those mappings were based on platform
gesture descriptions and incomplete callback observations. Later testing on Hi
Rokid `G1.12.10.0815` / CXR-L service `1.0.0 code 10000` did not establish a
trustworthy CUSTOMVIEW operator-input channel.

The phone/CUSTOMVIEW route under Glasses View `1.10.0` retains these rules:

- CUSTOMVIEW close, `AI-exit`, and AI key callbacks are lifecycle/diagnostic
  events only.
- The Android relay maps every such event to no operator command.
- Capture preparation, shutter, cancellation, registration, retake, discard,
  reading completion, and navigation are phone controls.
- HUD output remains black, green, static, and at most three lines.
- The relay makes no camera request during analysis/review. The physical
  indicator must still be observed independently.

`GET /v1/settings.operations` publishes `"phone"` for every supported action.
`GET /v1/settings.input` retains a legacy/unverified KeyCode map only for
diagnosis and explicitly publishes `operator_actions_enabled:false`.

The standalone `:glassdoc` 0.6.1 APK has a separate local input adapter:

| State | Tap | Forward swipe | Backward swipe |
| --- | --- | --- | --- |
| Ready | Prepare capture | — | — |
| Aiming | Shutter | — | Cancel |
| Capture review | Register | — | Retake |
| Reading | Prepare next page | Finish reading | Retake previous page |
| Answer review | New document | Next | Previous |

Configuration and session restoration run together on the controller queue.
Launching without a `server` extra reuses the saved URL. A new Intent applies
explicit `server`/`key` overrides; a guide-only Intent updates and saves the
guide without restarting the workflow. An omitted key retains the current
in-memory key only for the same server. Keys are not persisted across process
death, so authenticated servers require the key again on restart.
Configuration changes during capture are rejected and preserve the active
workflow. Pending photos cannot be redirected to another server.

A terminal camera failure releases the capture lease and permits a tap to
prepare another capture. An unresolved timeout remains stopped. HUD hints on
this local surface name these gestures instead of phone buttons; the phone
relay's CUSTOMVIEW input policy is unchanged. This patch still requires the
physical acceptance checklist on the installed APK and firmware.

Intent handling follows the Android [Activity.onNewIntent contract](https://developer.android.com/reference/android/app/Activity#onNewIntent(android.content.Intent)):
the Activity stores the received Intent with `setIntent` before applying its extras.

See `docs/cxr-l-integration.md`, `docs/real-device-operation.md`, and
`docs/device-verification-checklist.md` for the current behavior.

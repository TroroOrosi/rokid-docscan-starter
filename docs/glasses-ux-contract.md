# Legacy glasses gesture proposal

Status: Superseded design record. Not an operator contract.

Earlier revisions mapped tap, double tap, long press, and two-finger swipes to
capture, completion, and review actions. Those mappings were based on platform
gesture descriptions and incomplete callback observations. Later testing on Hi
Rokid `G1.12.10.0815` / CXR-L service `1.0.0 code 10000` did not establish a
trustworthy CUSTOMVIEW operator-input channel.

The current contract is Glasses View `1.9.0`:

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

A future glasses-side APK may define a separate input adapter only after its
install/start path and input events pass the physical checklist on the exact
recorded hardware/software tuple. That future result must not silently
reactivate the legacy CUSTOMVIEW mapping.

See `docs/cxr-l-integration.md`, `docs/real-device-operation.md`, and
`docs/device-verification-checklist.md` for the current behavior.

# Recording-indicator experiment (quarantined)

Status: Unsupported historical experiment. Quarantined 2026-09-01.

An earlier development branch explored whether diagnostic shell access could
change a camera recording indicator. That experiment is not part of the
supported product, server, Android relay, build, or device-acceptance path.
Operational commands and modification procedures are intentionally not kept in
the runbook because they would bypass a safety signal to people nearby.

What remains valid:

- The inspected `com.rokid.cxr:client-l:1.0.1` and `1.1.1` public AAR surfaces
  expose photo capture but no camera-indicator control.
- A successful SDK callback is application evidence, not proof of the physical
  indicator state.
- The supported test observes the indicator continuously with an independent
  camera before, during, and after `takePhoto`.
- Timeout or disconnect leaves camera state unknown. Do not issue another photo
  request until the CXR-L binding has been recreated and the indicator has been
  physically checked.

Use
`docs/research-safe-led-and-device-readiness-2026-09-01.md` and
`docs/device-verification-checklist.md` for the current, non-modifying evidence
procedure. The legacy implementation files are not imported by supported
runtime code and must not be exposed through an API, intent, UI, or build task.

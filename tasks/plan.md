# Implementation Plan: Safe real-device readiness

## Overview

Implement the accepted capability map in risk order. Documentation truth and
fail-closed contracts land before building or connecting a device.

## Architecture Decisions

- Normalized, orientation-corrected PNG is the authoritative server image.
- `ROKID_REAL_MODE=1` is fail-closed and never silently selects placeholders.
- CUSTOMVIEW operator tap is unverified; current supported controls are on the
  phone until a glasses app is physically proven.
- Camera/privacy indicator state is externally observed, never modified or
  inferred from SDK callbacks.
- CXR-L remains pinned to 1.1.1 for this run; 1.1.2 is a separate upgrade.

## Task List

See `tasks/todo.md` for acceptance criteria and verification commands.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Existing user edits overlap safety docs | High | Patch only targeted claims; inspect every diff |
| Old tap assumptions remain in code/HUD | High | Repository-wide search plus focused JVM tests |
| Non-ASCII checkout blocks Gradle | High | Create a clean ASCII-path build copy/worktree after source verification |
| Unknown photo callback state | High | Fail closed; no automatic retry in the same generation |
| APK signature/vendor installer mismatch | High | Inspect signature and hash before device access; preserve callback evidence |
| Physical device unavailable | Medium | Stop at read-only inventory and report no-go without guessing |

## Open Questions

- Physical device results cannot be known until the static gates pass and a
  device is attached.

## Extension: Glasses app operation — `glasses-input`

The user accepted `CAPABILITY-MAP-glasses-app-operation.md` and
`SPEC-glasses-input.md` after the direct glasses-side probe proved physical
KeyEvents reach the foreground Activity. This extension does not discard the
incomplete controlled-device validation above; it changes the next supported
control surface from phone-only to a glasses app, then returns to the same
capture/LED/server acceptance gates.

### Architecture decisions

- Calibrate official system broadcasts and Activity KeyEvents before choosing
  a deduplication window or production gesture mapping.
- Keep callbacks as data sources only. A pure-Java normalizer owns ordering,
  correlation, deduplication, and unknown-event handling.
- Emit normalized, side-effect-free actions. Capture/navigation semantics belong
  to later capability modules.
- Observe broadcasts without `abortBroadcast()` until target-firmware behavior
  proves that consuming an ordered broadcast is safe.
- Preserve exact hardware tuple, APK hash, event names, and timing, but never
  record content or credentials.

### Dependency graph and build order

```text
GI-1 dual-path calibration
  -> measured event pairs and timing
  -> GI-2 pure-Java normalization/deduplication
  -> GI-3 lifecycle hardening and final hardware acceptance
```

### Task list

Detailed acceptance criteria, verification commands, dependencies, and likely
files are appended to `tasks/todo.md` under `glasses-input`.

### Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| One gesture reports both a broadcast and KeyEvent | Duplicate destructive action later | Calibrate both streams, then prove one normalized result in unit and hardware tests |
| Firmware key names differ from physical semantics | Wrong operation mapping | Record exact gesture order and raw/app events; raw key name never defines business meaning alone |
| `abortBroadcast()` suppresses system behavior | Launcher or safety control regression | Do not abort in this module; measure before any future change |
| App loses focus or receiver lifecycle leaks | Missed or duplicated input after restart | Explicit register/unregister lifecycle plus restart hardware test |
| Unknown future action is treated as known | Unexpected side effect | Exhaustive allow-list; unknown actions are content-free diagnostics only |

### Open questions resolved by GI-1

- Which official broadcast and KeyEvent pairs describe the same gesture on
  build `1.25.012-20260901-150201`?
- What is the smallest observed timing bound that safely correlates those pairs?
- Which keys remain system-owned and must stay unconsumed?

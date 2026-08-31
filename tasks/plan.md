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

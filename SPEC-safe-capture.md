# Spec: safe-capture

## Objective

Make capture fail closed: only one request may be in flight, a missing callback
never authorizes another photo, and logs provide content-free evidence that can
be aligned with an independent video of the physical indicator.

## Tech Stack

Java 17 source compatibility, Android SDK 36, CXR-L `client-l:1.1.1`, JUnit 4.

## Commands

- Focused tests: `gradle --no-daemon -p android-relay testDebugUnitTest`
- Build: `gradle --no-daemon -p android-relay assembleDebug`

## Project Structure

- `android-relay/app/src/main/java/dev/rokid/docscanrelay/`: capture state,
  diagnostics, relay UI, and CXR-L boundary.
- `android-relay/app/src/test/java/dev/rokid/docscanrelay/`: unit tests.
- `app/glasses_view.py`: server-advertised capture contract.

## Code Style

```java
if (captureLease.state() != CaptureLease.State.IDLE) {
    return PhotoStartResult.BLOCKED;
}
```

State names describe evidence, not assumptions. A timeout produces `UNKNOWN`,
not `IDLE` or `LED_OFF`.

## Testing Strategy

Unit-test state transitions, stale callback fencing, timeout/disconnect behavior,
and redaction of image/OCR/token contents from evidence strings. Physical LED
behavior is a manual acceptance test with an external camera.

## Boundaries

- Always: wait for the matching terminal callback; require view-open
  acknowledgement before a photo sequence; log version/generation/timing/size.
- Ask first: changing photo dimensions or retry policy after hardware evidence.
- Never: write to LED nodes/properties, hide the indicator, infer physical LED
  state from a callback, or retry an unknown in-flight request.

## Success Criteria

- A timeout, Binder ambiguity, or disconnect blocks more photos until a new
  session generation is established.
- Evidence logs contain no image bytes, OCR text, token, or API key.
- Current HUD/runbooks use phone controls unless glass-app input is physically
  verified.

## Open Questions

Exact LED transition timing and glass-app input remain physical test results.

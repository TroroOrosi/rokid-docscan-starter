# Spec: glasses-input

Status: Accepted by the user on 2026-09-01.

## Objective

Convert physical Rokid glasses input into a single stream of normalized,
side-effect-free operator actions. The module must observe both the official
system-broadcast path and Activity KeyEvent path, deduplicate reports generated
by one physical gesture, and leave all capture/navigation semantics to later
modules.

The immediate user-visible outcome is a production-grade input diagnostic on
the glasses that reports exactly one normalized action for each supported
physical gesture and never starts a photo or network operation.

## Tech Stack

- Java 17 source compatibility.
- Android application module `:glassapp`, compile/target SDK 36.
- Measured runtime: Rokid Android 12 / API 32.
- Android `BroadcastReceiver`, `IntentFilter`, `KeyEvent`, and monotonic
  `SystemClock` timestamps.
- JUnit 4.13.2 for pure-Java normalization and deduplication tests.
- No new runtime dependency in this module.

## Commands

- Unit tests:
  `gradle --no-daemon -p android-relay :glassapp:testDebugUnitTest`
- Debug APK:
  `gradle --no-daemon -p android-relay :glassapp:assembleDebug`
- Full Android gate:
  `gradle --no-daemon -p android-relay testDebugUnitTest assembleDebug`
- Repository whitespace gate: `git diff --check`

Run Gradle from the verified ASCII-only Windows build path when the repository's
OneDrive path triggers Android Gradle Plugin path validation.

## Project Structure

- `android-relay/glassapp/src/main/java/dev/rokid/docscanglass/input/` — input
  signals, normalized actions, correlator/deduplicator, and broadcast adapter.
- `android-relay/glassapp/src/main/java/dev/rokid/docscanglass/TapProbeActivity.java`
  — temporary UI host and KeyEvent adapter until the production Activity is
  introduced by a later module.
- `android-relay/glassapp/src/test/java/dev/rokid/docscanglass/input/` — pure
  JVM tests for ordering, mapping, deduplication, and unknown events.
- `.agents/progress/glasses-input-and-real-device-prep.md` — exact hardware
  calibration evidence without content or credentials.

## Code Style

Keep platform callbacks thin and put deterministic decisions in pure Java:

```java
Optional<GlassesInputAction> accept(InputSignal signal) {
    if (!mapping.supports(signal)) {
        return Optional.empty();
    }
    return deduplicator.firstActionFor(signal);
}
```

- Immutable input/action value objects.
- Monotonic elapsed time, never wall-clock time, for correlation.
- Exhaustive enum/switch mapping with unknown values ignored safely.
- Content-free diagnostics: source, action type, sequence, and elapsed time
  only.
- No camera, network, storage, or CXR transport call from this module.

## Testing Strategy

1. Unit-test each official action and measured KeyEvent independently.
2. Feed broadcast + KeyEvent pairs representing one gesture and assert exactly
   one normalized action.
3. Assert distinct gestures outside the measured correlation window remain
   distinct.
4. Assert reordered, repeated, unknown, and late events do not create an
   unintended action.
5. Build and install the debug APK on the explicit glasses serial.
6. On the exact recorded hardware tuple, perform a controlled gesture sequence
   and compare raw input, app callbacks, and normalized-action logs.

The correlation window is not guessed. Measure the broadcast/KeyEvent timing on
the current firmware first, then encode the smallest passing bound in tests and
record it with the firmware tuple.

## Boundaries

- Always: dynamically register every official key broadcast documented for the
  current CXR-S sample; also observe Activity KeyEvents; unregister the receiver
  on destruction; consume only a verified app-owned event.
- Always: emit at most one normalized action per physical gesture and preserve
  ordering for distinct gestures.
- Ask first: assigning a normalized action to capture, registration, discard,
  navigation, or app exit; changing the production gesture vocabulary.
- Never: use input observation to start a photo, upload, registration, or server
  request in this module.
- Never: treat lifecycle callbacks, CUSTOMVIEW close, or AI-exit as operator
  input.
- Never: log page content, credentials, tokens, images, OCR, or provider data.

## Success Criteria

- The module recognizes the official `CLICK`, button down/up, double-click,
  long-press, two-finger tap/swipe, AI-start, and settings-key broadcasts without
  crashing on an unknown future action.
- Activity KeyEvents observed on the measured hardware are represented without
  assuming that a raw key name alone defines its business meaning.
- One controlled physical gesture produces exactly one normalized action even
  when both broadcast and KeyEvent paths report it.
- A long press remains distinguishable from a short gesture using an official
  long-press report or a hardware-calibrated down/up duration; no arbitrary
  threshold is promoted as a platform constant.
- Unsupported and system-owned inputs have no application side effect.
- Pure-Java unit tests pass, the glass APK builds, and the controlled hardware
  sequence is recorded against the exact firmware/APK hash.

## Open Questions

- Which official broadcasts and Activity KeyEvents co-report the same physical
  gesture on build `1.25.012-20260901-150201`? This is the first calibration
  task and determines the deduplication window.
- Does calling `abortBroadcast()` interfere with launcher/system behavior on
  this firmware? Default to observing without aborting until measured.
- Which system-owned keys should be consumed by the production Activity? The
  input module will initially ignore rather than capture ambiguous keys.

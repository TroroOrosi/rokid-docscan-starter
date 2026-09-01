# Spec: device-validation

## Objective

Connect to the Android phone only after all static gates pass, inventory the
environment read-only, then install and exercise verified artifacts with a
reversible, evidence-producing procedure.

## Tech Stack

Android platform tools, Hi Rokid, Rokid Glasses, relay APK, optional glass probe
APK, and an external camera for indicator observation.

## Commands

- Enumerate attached devices read-only and require one explicit device serial.
- Read OS/app/package versions with explicit per-device commands.
- Install the verified relay only after package, signature, and version
  compatibility are known.

## Project Structure

- `docs/device-verification-checklist.md`: evidence form.
- `docs/real-device-operation.md`: supported operation.
- `.agents/progress/`: sanitized run result and continuation state.

## Code Style

Every device command names the serial. Evidence records versions and hashes but
redacts tokens, API keys, images, and OCR content.

## Testing Strategy

Read-only inventory first. Installation is followed by Hi Rokid authorization,
link/Bluetooth callbacks, one controlled photo, OCR/upload/HUD verification, and
external-video inspection of the physical indicator.

## Boundaries

- Always: stop on multiple devices, signature mismatch, version downgrade,
  unknown callback state, or missing external-video setup.
- Ask first: uninstalling apps or changing phone security settings.
- Never: run LED mutation commands, log credentials/content, or call hardware
  behavior verified without the physical checklist.

## Success Criteria

- The exact phone/glasses/Hi Rokid/service/relay tuple is recorded.
- Relay installation and supported phone-controlled capture succeed or fail with
  a preserved, sanitized error record.
- LED result is reported only from external physical observation.

## Open Questions

The device may not be connected or ready; this is a legitimate no-go result.

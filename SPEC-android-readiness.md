# Spec: android-readiness

## Objective

Produce and inspect relay/glass APKs in a reproducible ASCII-path build before
any device mutation.

## Tech Stack

AGP 9.2.1, Gradle 9.4.1 wrapper bootstrap, Android SDK/Build Tools 36, Java 17
source compatibility, pinned CXR-L 1.1.1.

## Commands

- Tests/build: `gradle --no-daemon -p android-relay testDebugUnitTest assembleDebug`
- Verify signatures with the Android SDK `apksigner` tool.
- Inspect APK identity with the Android SDK `aapt2` tool.
- Record SHA-256 with PowerShell `Get-FileHash`.

## Project Structure

- `android-relay/app`: phone relay.
- `android-relay/glassapp`: glasses-side probe.
- `docs/windows-android-real-device-setup.md`: reproducible Windows runbook.

## Code Style

Build tooling remains declarative in Gradle. Environment discovery emits facts
and fails non-zero on a missing gate; it does not install anything.

## Testing Strategy

Run JVM tests and both debug builds from a verified ASCII path. Inspect each APK
for identity, version, signature schemes/certificate, and SHA-256.

## Boundaries

- Always: record exact artifact and dependency hashes.
- Ask first: SDK/AAR upgrades, keystore changes, or uninstalling an existing app.
- Never: use a stale worktree artifact as evidence for current HEAD.

## Success Criteria

- Current HEAD builds from an ASCII path with a recorded JDK/SDK/Gradle tuple.
- APK identity/signature/hash match the intended package and activity.
- No device command is run before these gates pass.

## Open Questions

Whether the vendor installer requires v1 signing remains a device measurement.

# Tasks: Safe real-device readiness

## Task 1: Freeze truthful contracts

- [x] Classify all Markdown as current, historical, research, plan, or internal progress.
- [x] Synchronize versions and remove unsupported current-operation claims.
- [x] Add automated documentation-contract checks.
- Verify: focused pytest for the new checks; repository-wide search audit.
- Files: documentation plus one focused test module.

## Task 2: Implement server fail-closed boundaries

- [x] Add failing tests for real-mode placeholder rejection.
- [x] Correct OpenAI audio formats and Gemini custom endpoint behavior.
- [x] Keep normalized PNG authority explicit in API/docs.
- Verify: focused tests, then full pytest and Ruff.
- Files: server config/provider modules and focused tests.

## Checkpoint: server and evidence contracts

- [x] Focused tests pass.
- [x] Full Python suite and Ruff pass.
- [x] Progress record updated.

## Task 3: Align Android capture and controls

- [x] Add failing tests for any missing fail-closed capture transition.
- [x] Remove current HUD/operator guidance that depends on unverified CUSTOMVIEW taps.
- [x] Preserve content-free capture diagnostics and single in-flight policy.
- Verify: Android unit tests.
- Files: focused relay policy/controller/messages and tests.

## Task 4: Build and inspect APKs

- [x] Establish an ASCII-path current-tree build environment.
- [x] Run unit tests and assemble both debug APKs.
- [x] Record package/activity/version/signature/hash for each artifact.
- Verify: Gradle and Android SDK artifact-inspection tools.

## Checkpoint: device-ready artifacts

- [x] Python and Android suites pass.
- [x] APK provenance record is complete.
- [x] Current docs match the built versions.
- [x] Progress record updated.

## Task 5: Read-only phone inventory

- [x] Enumerate devices and require exactly one explicit serial.
- [x] Record phone, Hi Rokid, existing relay, and connection state without secrets.
- [x] Stop on version/signature/no-device/multiple-device conflicts.
- Verify: sanitized command transcript.

## Task 6: Controlled device validation

- [x] Install only the verified relay artifact if update-compatible.
- [ ] Complete authorization/link/Bluetooth and one phone-controlled capture.
- [ ] Record external physical LED, callback, OCR/upload, and HUD evidence.
- Verify: completed checklist with exact version/hash tuple.

## Checkpoint: complete

- [ ] All automated checks pass.
- [ ] Physical results are clearly separated from unverified items.
- [ ] Five-axis code review has no Critical or Required findings.
- [ ] Documentation and progress record reflect the final state.

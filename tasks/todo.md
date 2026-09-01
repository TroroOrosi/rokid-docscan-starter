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

## Extension: Glasses app operation — module `glasses-input`

This accepted module is implemented before resuming the remaining controlled
capture items in Task 6. It adds no camera, server, upload, or registration side
effect.

## Task GI-1: Calibrate official broadcasts and Activity KeyEvents

**Description:** Add a content-free, dual-path calibration adapter to the
existing tap probe. It records official broadcast action, Activity key code,
down/up phase, monotonic elapsed time, and sequence without normalizing or
triggering an operation.

**Acceptance criteria:**

- [ ] Every official action named by the accepted spec is registered
      dynamically and represented by an allow-listed signal type.
- [ ] KeyEvent down/up and broadcast observations use one monotonic timeline and
      log no content, credentials, tokens, images, or OCR.
- [ ] Unknown actions/keys are observable but produce no normalized action or
      side effect.

**Verification:**

- [ ] Failing tests are added first for the official action catalog, event
      ordering, and unknown-event behavior.
- [ ] `gradle --no-daemon -p android-relay :glassapp:testDebugUnitTest`
      passes.
- [ ] `gradle --no-daemon -p android-relay :glassapp:assembleDebug` passes.
- [ ] On the explicit glasses serial, a controlled gesture sequence records the
      raw device event, broadcast (if any), and Activity KeyEvent with exact
      timing and the APK/firmware tuple.

**Dependencies:** Accepted `SPEC-glasses-input.md`; no implementation task.

**Files likely touched:**

- `android-relay/glassapp/src/main/java/dev/rokid/docscanglass/input/InputSignal.java`
- `android-relay/glassapp/src/main/java/dev/rokid/docscanglass/input/OfficialKeyBroadcasts.java`
- `android-relay/glassapp/src/main/java/dev/rokid/docscanglass/input/InputCalibrationLog.java`
- `android-relay/glassapp/src/main/java/dev/rokid/docscanglass/TapProbeActivity.java`
- `android-relay/glassapp/src/test/java/dev/rokid/docscanglass/input/InputCalibrationLogTest.java`

**Estimated scope:** Medium (5 files).

## Checkpoint GI-A: Hardware calibration

- [ ] GI-1 focused tests and glass APK build pass.
- [ ] Controlled physical gestures are matched to raw/broadcast/KeyEvent rows.
- [ ] No photo, network request, upload, or registration occurs.
- [ ] Correlation evidence and exact version/hash tuple are checkpointed before
      choosing a deduplication bound.

## Task GI-2: Normalize and deduplicate one physical gesture

**Description:** Encode the measured event pairs in a pure-Java normalizer. One
gesture emits at most one `GlassesInputAction`; distinct gestures preserve order,
and late/repeated/reordered events fail closed.

**Acceptance criteria:**

- [ ] The correlation window is derived from GI-1 evidence and recorded as a
      firmware-scoped decision, not a platform constant.
- [ ] Broadcast-only, KeyEvent-only, paired, repeated, reordered, late, and
      unknown cases have deterministic unit tests.
- [ ] The Activity displays/logs one normalized action without assigning it to
      capture, navigation, registration, or app exit.

**Verification:**

- [ ] Failing correlator tests are added before implementation.
- [ ] `gradle --no-daemon -p android-relay :glassapp:testDebugUnitTest`
      passes.
- [ ] A controlled hardware sequence produces exactly one normalized action per
      supported physical gesture.

**Dependencies:** GI-1 and Checkpoint GI-A.

**Files likely touched:**

- `android-relay/glassapp/src/main/java/dev/rokid/docscanglass/input/GlassesInputAction.java`
- `android-relay/glassapp/src/main/java/dev/rokid/docscanglass/input/GlassesInputNormalizer.java`
- `android-relay/glassapp/src/main/java/dev/rokid/docscanglass/TapProbeActivity.java`
- `android-relay/glassapp/src/test/java/dev/rokid/docscanglass/input/GlassesInputNormalizerTest.java`

**Estimated scope:** Medium (4 files).

## Task GI-3: Harden receiver lifecycle and unknown input handling

**Description:** Make registration/unregistration, Activity restart, focus loss,
and unknown future actions safe while retaining content-free diagnostics.

**Acceptance criteria:**

- [ ] Receiver registration is paired exactly once with lifecycle cleanup and
      does not call `abortBroadcast()`.
- [ ] Restart/focus recovery clears transient correlation state and never replays
      a normalized action.
- [ ] Unknown/system-owned inputs remain unconsumed and have no application side
      effect.

**Verification:**

- [ ] Focused lifecycle/normalizer tests pass.
- [ ] `gradle --no-daemon -p android-relay testDebugUnitTest assembleDebug`
      passes from the verified ASCII build path.
- [ ] Install/restart/gesture hardware check passes on the recorded tuple.

**Dependencies:** GI-2.

**Files likely touched:**

- `android-relay/glassapp/src/main/java/dev/rokid/docscanglass/input/GlassesInputReceiver.java`
- `android-relay/glassapp/src/main/java/dev/rokid/docscanglass/input/GlassesInputNormalizer.java`
- `android-relay/glassapp/src/main/java/dev/rokid/docscanglass/TapProbeActivity.java`
- `android-relay/glassapp/src/test/java/dev/rokid/docscanglass/input/GlassesInputNormalizerTest.java`

**Estimated scope:** Medium (4 files).

## Checkpoint GI-B: `glasses-input` complete

- [ ] All `:glassapp` unit tests pass.
- [ ] Full Android unit/build gate passes.
- [ ] Controlled hardware sequence emits exactly one normalized action per
      supported gesture after install and restart.
- [ ] No camera/network/upload/registration side effect is observed.
- [ ] Specs, evidence, and progress record match the implemented behavior.
- [ ] Human review approves moving to `custom-app-session`.

# PR37 camera research and delivery hardening

Date: 2026-09-17. Start from this note, then read `pr37-offline-remediation.md`,
`CLAUDE.md`, the complete `multimodal-scan.md` and `pr37-predevice-handoff.md`,
and the current sections of `tasks/plan.md` / `tasks/todo.md`.

## Scope and implementation plan

Base: `68c19853e5e4567e0ec0a961ed6100a67e4f83d3` on `feature/multimodal-scan`.
Research/design: `docs/rokid-capture-research.md`. Implementation is restricted
to the existing standalone Camera2 seam and PC saved-photo diagnostics.
The frozen CXR-L surface, model selection, DB, credentials and capture policy remain unchanged.

- First reproduce delivery failures with `GlassCameraDeliveryTest`: image-before-reader close,
  empty/oversized/non-JPEG buffers, memory failure, close failure, generation-bound camera
  failure/abort/buffer loss, and metadata-only delivery. This uses fake HAL buffers, not hardware.
- Implement the minimal delivery lifetime fix in `GlassCamera.java`, retaining UNKNOWN/no-retry.
  Add allowlisted numeric capability/result logging without changing the capture request.
- Reproduce missing offline sampling/glyph/detail/EXIF behavior in `tests/test_capture_preflight.py`,
  then implement `scripts/capture_sampling.py` and extend `scripts/capture_preflight.py`.
  Preserve source bytes, explicit rotation, bounded opt-in outputs and non-acceptance labels.
- Correct the `JapaneseOcr` comment: measured column pitch does not establish glyph resolution.
  Keep the actual decoder, OCR model, thresholds and memory policy unchanged.
- Run Python regression/documentation gates and Android CI, inspect actual JUnit reports,
  and link exact commit/run evidence in PR37. A build is not camera/optical acceptance.

## Evidence and remaining gates

The unchanged baseline documentation/preflight/version/surface subset passed 43 tests locally.
The new offline diagnostic tests first failed 15 cases with 15 original cases passing.
The first Android test-only commit `c36f0b1` failed to compile because Android's Image and Plane
constructors are package-private. This was a fixture error, NOT evidence of a production regression.
Commit `3e9b1d5` moves the fake buffer into a test-only android.media package. Do not skip tests or
count a compiler error as a successful reproduction.
Android run `35164851530` then executed all 12 new tests: 12 expected failures, 0 errors/skips.
The report shows missing generation callbacks, wrong close order, unbounded/invalid buffer delivery,
unhandled synthetic OOM and lost close-failure notification. Existing CI run `35164851489` passed.
Consult subsequent PR checks for the final implementation results.

No physical camera, saved Windows photographs, live OCR, audio, installation or ChatGPT submission
was used here. Automatic tests use synthetic images and fake HAL buffers only.
All real capture/installation/submission stop conditions from the prior handoff remain in force.

## Windows Codex next action

Read `docs/rokid-capture-research.md` and `docs/capture-preflight.md`, inspect existing saved originals
first, and record actual glyph dimensions and source-scale detail crops. Do not start by asking for
more photographs. Preserve all keys, old APKs, source JPEGs, pending data, manifests and DB.
After explicit release, compare the same B5 spread and single-page source with stable illumination
and pose, record CameraCharacteristics/CaptureResult values, and assess actual optical results.
Missing AF/AE metadata, a small HUD preview, or a successful upload is not proof of readable text.

CameraResult logs may be absent when JPEG arrives first and the camera is closed immediately;
never retain/reopen the camera just to fill diagnostics. Resource close attempts are not asynchronous
onClosed or physical LED evidence. The application-wide low-memory and 20–40-page gates remain open.

## Local verification before final CI

- Offline diagnostic/documentation/version/surface subset: 59 tests passed (including 16 added cases).
- `python -m scripts.check_capture_memory`: invalid save preserves original; 20 saves/equality checks
  of a synthetic 7MiB fixture under `-Xmx16m`, PASS. This excludes camera/ML Kit native memory.
- Local full-suite JUnit recorded 663 tests, 0 failures/errors, 1 intentional live-test skip.
  However, the local process did not exit before the 120-second command deadline. This is NOT a
  clean full-suite command pass; use the final GitHub CI matrix and its clean job conclusions.
- Ruff is not installed in this container; lint is verified by the existing CI lane rather than
  silently claiming a local lint pass or changing project dependencies.
- Android tests/builds run in the existing JDK17/SDK36 GitHub Actions environment. No local SDK,
  physical device, Windows keystore or installed APK is available here.
- Camera implementation commit: `b3044e5982c7da952d593bc2359d46e6e90aa99d`.
  Final CI evidence is recorded in the PR37 verification comment after the documentation/tool commit.

## Primary-source refinement and fixture correction

A fresh full-text read of the official Rokid Glasses product page confirmed AF not supported,
depth of field 34cm to infinity, H77/V94/D109 field of view and 3-degree inward tilt. This supersedes
initial search snippets/FAQ-only uncertainty; do not carry the earlier AF-unknown or angle-axis-unknown
conclusion forward. The page's "1.9 m" focal-length unit is not silently converted to mm.
The research runbook separates published optics, geometric assumptions, HAL values and measured quality.
An optional operator-measured `--distance-cm` is diagnostic only and cannot approve a capture.
Nine new distance cases failed before implementation, then passed with the existing diagnostic suite.

Android run `35165473273` executed 384 tests: 381 passed, 3 fixture failures. All five diagnostic
logging tests passed. The three remaining failures depended on an unavailable hidden CaptureFailure
constructor; the fixture now shadows only the public wasImageCaptured/getReason contract. No
production check was disabled. Final CI must execute the corrected tests before claiming success.

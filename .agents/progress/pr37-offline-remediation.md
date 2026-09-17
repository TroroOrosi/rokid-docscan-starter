# PR37 — offline remediation restart point

2026-09-17追記: 最新の撮影仕様調査・配送修正・診断の入口は
`.agents/progress/pr37-camera-research.md`。本記録の停止条件は継続する。

Status: Current continuation entry, 2026-09-16. Start here, then read the previous records in full.

## Authority and baseline

Runs on: Repository inspection and isolated Linux/JDK/Python tests, GitHub Actions. No devices or live model.

User request: prepare the actual features and UX before further capture tests. Baseline is PR37
head `0be008a25d74c1e6e88b27378b177c1c3ddd874d`, tree `44084caa0f0fd7096bc0052d23274975a8a9ac0a`.
Its CI source archive was checked against this Git tree before edits. The old PR body pointed
at an earlier head and is not evidence about the device's current APK.

Read `CLAUDE.md`, `.agents/progress/pr37-predevice-handoff.md` and
`.agents/progress/multimodal-scan.md` completely, including the later stop/LOW_MEMORY records.
Their hardware observations, original hashes, pending records and unmet requirements remain in place.
Use `docs/capture-preflight.md` for the new offline commands.

**STOP remains: no additional capture, live ChatGPT sending or APK installation is authorized by this record.**
An earlier permission or a green CI job does not undo the operator's later stop.
Do not re-ask the known phone topology, LED-audit waiver, paper conditions or primary solver choice.

## Implemented scope

Runs on: Shared persistence/OCR code and standalone glassdoc UI. API schemas, server configuration and original images unchanged.

- Reject invalid pending metadata/payload sizes before replacing the previous recoverable file.
- Stream original JPEG comparison and validate the tail, instead of decoding/allocating another
  entire JPEG for local commit/contains. Keep record compatibility, immutable revisions and SHA-256 checks.
- Dispose queued thumbnails on supersede/close/rejected UI post; detach recycled images from
  the HUD; dispose the first decode if rotation allocation fails.
- Defer opening ML Kit until recognition. Release the decoded bitmap before the downstream
  callback on completed tasks, and also on synchronous processing errors. No lower OCR resolution.
- Explain the aiming cross as a direction cue, not a paper frame. A capture-end gesture can
  update only the review footer; it neither replaces the image nor starts a fresh 3-second clock.
- Add an offline saved-image tool and a repeatable low-heap persistence probe. Perspective/tone
  correction produces explicit four-corner derivatives only. No automatic cropping, OCR or upload.

The standalone APK identifier is bumped in its Gradle source. No server release, HTTP payload,
operation mapping, review timing or frozen HUD contract is changed. Shared fixes are not new
features on the frozen phone-relay route.

## Reproduction and evidence boundaries

Runs on: Isolated Linux, JDK 21 and Python 3.13; CI uses the configured JDK/Python matrix. These are component tests.

- Before production changes, commit `f3049c1b938d0a3814faed3b66c97f39a84456e2` added regression tests.
  Android Actions run `35108032471` failed with four expected assertions: invalid original replacement,
  accepting a review after close, retaining a recycled HUD bitmap, and accepting a rejected UI post.
- The unchanged local 7MiB persistence fixture failed with OutOfMemoryError under `-Xmx16m`
  before the streaming change. Afterwards 20 commits/equality checks and invalid-save preservation passed.
  The repeatable repository command is `python -m scripts.check_capture_memory`.
- Offline-image tests: 15 passed locally on synthetic images. They test source preservation,
  explicit rotation, EXIF non-duplication, bounded previews, explicit corner validation, derivatives,
  offline behavior and CLI. They do not run OCR or see the user's existing Windows photos.
- Android memory-fix commit `7ac5c88cc88ae39c7c1c7d4294783d7036a7ab34` passed the original four
  regressions. Added ML Kit lifecycle tests initially stopped in InputImage creation because the
  manifest-free test runtime lacked ML Kit initialization, not because a photo was unreadable.
  Keep the tests and their assertions; supply the SDK test context rather than skip them.
- Local full pytest hit the command timeout; the specific stalled test was not established. This is not a
  local full-suite pass. Final PR CI links/results, the exact head and Android report counts must
  be read from the PR checks/comment. Never reuse previous successful run counts for a new head.

## Remaining work before asking for another photograph

Runs on: Windows PC, first using only already-saved originals and the existing toolchain.

1. Preserve local uncommitted changes; update the PR branch without force/reset. Read this record
   and the two earlier records. Do not replace the local signing key, tokens, DB, manifest or pending originals.
2. Run the offline preflight on existing raw JPEGs and normalized PNGs with the corresponding
   rotation. Compare complete source frame, display-only correction and optional explicitly chosen
   paper derivative. Keep all outputs local; do not treat JSON warnings as a pass/fail classifier.
3. Run the persistence probe and Android/Python tests; build without installing. Record the new
   APK identity separately from the installed one, which this session never read or changed.
4. Summarize what can and cannot be recovered from the existing images. Only after the operator
   lifts the stop may a limited physical test be planned. Maintain the real-device safety checks
   and the decided glasses → phone AP → phone server/browser route.

Still unproved: whole-process LOW_MEMORY elimination, optical alignment/readability, usable ML Kit
recognition on the problem photos, 20–40-page/long-audio endurance and AP plus cellular acceptance.
RP tasks for idempotent document creation, long HTTP progress separation, additional answer retrieval,
question hierarchy and broader capture calibration remain open. No automatic recovery from an
ambiguous live send, automatic resend, model switch, new capture mode or complete exactly-once is added.

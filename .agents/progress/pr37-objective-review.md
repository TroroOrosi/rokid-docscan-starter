# PR37 objective review — 2026-09-17

Status: Engineering review and bounded corrective changes. **Not physical acceptance.**

## Authority and scope

Baseline PR head: `4f7dcfa7d1801bdcf859a9e7aa1b1099b43dec8e`.
Baseline tree: `a7829f352dbe49adc61aeb436132119eefa9033e`.
The source snapshot from CI run 35166488590 was reconstructed and its Git tree matched.
The PR body's older `68c1985` entry was not used as the source revision.
All tracked source was inventoried; focused manual review covered the active capture,
input/lifecycle, persistence, upload, audio, browser guard and answer-delivery boundaries.
This is not a claim that every line or every possible race was independently verified.

Read this record first, then `.agents/progress/pr37-camera-research.md`,
`.agents/progress/pr37-offline-remediation.md`, `CLAUDE.md`,
`.agents/progress/pr37-predevice-handoff.md` and `.agents/progress/multimodal-scan.md`
**in full, including their final stop records**, and the current RP sections of
`tasks/plan.md` and `tasks/todo.md`.

The active route is glassdoc Camera2 + bundled Japanese OCR -> phone hotspot ->
phone-hosted API/local ASR -> phone Chrome/CDP -> chatgpt-web -> offline AnswerView.
The CXR-L phone relay is frozen, not the venue route. Its shared components still need tests.
Model/provider selection, keys, original sources, database schema, camera parameters,
review deadlines, gestures and the existing physical stop are not changed by this review.

## Review verdict

**Do not treat PR37 as production-accepted or merge it solely because CI passes.**
Four newly reproduced correctness defects are addressed below. The primary route still
lacks end-to-end physical acceptance, has known long-request/progress limitations,
and has an external service-terms risk. These are not solved by adding more unit tests.
No numeric quality score is assigned without a measured acceptance rubric.

## Newly reproduced findings and bounded fixes

| ID / priority | Before the fix and impact | Change and evidence |
|---|---|---|
| RV-01 / P1 | `app/main.py`, `exam_answer_bundle`: items and revision came from separate implicit reads. An answer committed between them produced old items with a newer revision. `AnswerReader.accept` would then reject the real update with that same revision. | Start one explicit read transaction before the first SELECT. Deterministic test commits through a second connection between item assembly and revision lookup: old code fails, fixed code returns the old complete snapshot, then the new complete snapshot. WAL is enabled **only in the test**, not in deployment. |
| RV-02 / P1 | `app/listening.py`, `complete_recording`: only the immediately next chunk was checked. With chunks 0 and 2 retained, finishing a one-chunk recording silently excluded chunk 2 from the assembled original/manifest. | Reject every numbered WAV or metadata file at or beyond the declared end, including a nonadjacent/orphan chunk. Reject without rewriting originals. Valid out-of-order input still completes and removes only the defined overlap. |
| RV-03 / P1 | `app/listening.py`, `store_chunk`: an existing metadata file was enough to ACK a retry even when its original WAV was missing; metadata digest, sequence, offset and sample count were not checked. | Require a real matching original and matching metadata before ACK. A partial restore or corrupted metadata now fails closed with a fixed integrity error. No silent reconstruction, ASR rerun or evidence overwrite. |
| RV-04 / P1 | `DocScanGlassActivity`: the worker caught IOException and its Future still completed normally. Both close and exit discarded the reader / claimed CLOSED after a failed disk write. | Return the actual persistence result through Future<Boolean>. Failed CLOSED leaves the reader, answer and position in place, disarms stale exit confirmation, and shows a short index-row failure notice. Only a successful close may mark the Activity exited. Preserve thread interruption. |

P1 here means a blocker for a correctness claim under the stated failure condition;
it does not mean these failures were observed on the user's actual recording or answers.
The tests use synthetic material. No existing user data was deliberately corrupted.

The Android reproduction uses a real AnswerStore and a non-directory save path to
produce IOException, not a mocked successful writer. Red evidence: isolated branch
commit `bbaac233dcb59cab3fea0b640732a6924702aa8c`,
[Android run 35193398261](https://github.com/TroroOrosi/rokid-docscan-starter/actions/runs/35193398261).
Its JUnit XML reports exactly two new assertion failures: reader released after a
failed CLOSED write, and sessionClosed set before durable acknowledgement. No compilation
error was used as evidence of the product defect.

One older gesture test opened an unsaved bundle through reflection. Its fixture now
writes the initial bundle, matching the production precondition; its timing assertions
are retained. The new failure tests continue to exercise unavailable storage.

Behavioral patch identifiers and the standalone APK identifier are updated in their
source definitions. Read `app/version.py`, `README.md` and the glassdoc Gradle file;
do not copy version tuples into more progress documents. No HTTP envelope changed.
A stale README tree comment and the Gradle comment excluding the phone from the data
path were also corrected; the frozen relay's version is not the standalone APK version.

## Boundaries the fixes do not cross

- RV-01 is a consistent **database** snapshot, not an atomic transaction spanning arbitrary
  filesystem replacement and SQLite. Original-source revision protection still matters.
  A longer read transaction can delay writers in rollback-journal mode; phone latency is
  unmeasured. Do not enable WAL globally as an undocumented performance workaround.
- RV-03 validates a chunk retry. It does not claim complete media-file recovery or repair.
  The preexisting completed-manifest retry path still needs its own corruption/partial-
  restore audit. Automatic audio regeneration has not been introduced.
- RV-04 fixes false success. CLOSED still waits synchronously for ordered persistence.
  It does **not** solve main-thread waiting or the cost of rewriting an entire answer
  bundle for every position update. Ordinary queued position writes are not durable ACKs.
- A retry message preserves operator choice; it is not automatic retry or permission
  to reopen a closed session. Existing capture-session and answer-store lifecycles remain
  separate; no cross-file transaction is claimed.

## Remaining findings and decisions

| Priority / area | Source evidence and consequence | Next bounded work / existing RP |
|---|---|---|
| P1 / photo acceptance and LOW_MEMORY | Final physical records report dark/weak OCR and a low-memory process death. Later offline memory fixes and Camera2 diagnostics cannot prove that the installed device is now reliable. | Compare the **already saved** spread / close-spread / single-page originals first. Record actual character pixels, sharpness, glare, crop, orientation and per-stage memory. RP-01/09/10/22; no new shooting during the stop. |
| P1 / server acknowledgement vs completion | Long-running calls in `DocScanApi` disable read/call timeouts. Finalization and ASR may tie up a request; an AP disruption can leave apparent indefinite waiting. A blind retry can duplicate an external send. | Separate local/durable receipt from expensive work and query its state using stable request identity. Preserve UNKNOWN and send journal. RP-06/07/15/20. |
| P1 / progressive answers | Activity fetch is effectively once per session and existing saved data can take precedence; `AnswerReader.accept` is not a complete progressive-delivery implementation in the Activity. | Deliver newer saved revisions while preserving cursor and CLOSED. Test stale, duplicate, out-of-order and post-exit replies. RV-01 is a prerequisite, not completion of RP-15/16. |
| P1 / browser integration viability | Primary chatgpt-web uses browser automation and reads generated output. Current individual-service Terms prohibit automated/programmatic extraction of data or Output; DOM changes are a separate engineering risk. | Resolve supported/authorized integration before operational acceptance. An official API or manual supported workflow is a design option, not an automatic provider switch. Confirm cost/capability separately. Do not bypass restrictions. |
| P2 / document creation identity | Creation still lacks the planned idempotency key across uncertain HTTP outcomes. Local recovery and server creation are not a fully atomic operation. | Persist a client request identity before sending and bind repeat requests to the same server document. Fault-inject response loss. RP-03/06. |
| P2 / exit latency and cursor storage | Single-threaded writes preserve order, but each gesture can rewrite the full saved bundle. CLOSED waits on that queue from the UI thread. | Coalesce replaceable cursor updates, preserve CLOSED as a durable barrier, and expose asynchronous pending/failure state. Do not solve by dropping the final write. RP-16/17. |
| P2 / question structure | Current grouping and input revisions do not prove faithful nested questions or original choice symbols on real papers. | Golden cases for shared passages, continued pages, nested questions, figures and original choice labels; visual comparison and coverage checks. RP-12/14. |
| P2 / browser result-to-DB gap | The durable send guard reduces duplication but there is no complete transaction across a received browser answer and the answer DB commit. | Explicit recovery/import of an already received answer, never automatic resend after an unknown outcome. Keep journal/evidence. Existing predevice handoff. |
| P2 / long audio and phone runtime | Synthetic PCM/ASR stubs, Linux compatibility CI and successful compilation are not 150-minute recording, Termux installation or AP-plus-cellular acceptance. | Stage retained-source recovery tests before long physical runs; measure actual ASR lag, energy, space, memory and interruption recovery. RP-07/13/20/22. |
| P3 / code structure | Main server and Controller/Activity span several domains; source-string contract tests are not behavioral coverage. | After the correctness boundaries settle, extract cohesive units behind current interfaces. Do not rewrite the app or add duplicate surfaces during acceptance. |

Existing safeguards worth retaining: local originals before network transmission;
separate capture/review identity; stale-callback epochs; visible-image ACK before the
three-second decision window; durable browser UNKNOWN guard; immutable input identity;
offline saved answers; documentation/surface inventory gates; Python, Windows and Android CI.
These reduce specific risks, but do not cancel the unresolved acceptance conditions above.

## Web research used to evaluate the design

Checked on 2026-09-17. Official primary sources only:

- SQLite [isolation](https://www.sqlite.org/isolation.html) and
  [transactions](https://www.sqlite.org/lang_transaction.html): multiple statements need
  a deliberate transaction to constitute one read snapshot. Separate SELECT success is
  not proof that an assembled response is internally consistent.
- Google [ML Kit Android text recognition](https://developers.google.com/ml-kit/vision/text-recognition/v2/android):
  focus and sufficient character pixels matter; the guideline is approximately 16x16
  pixels per character. Upscaling or brightening a preview cannot recover missing detail.
- Rokid [Glasses official specification](https://global.rokid.com/ja/products/rokid-glasses):
  use the exact Glasses model, not Style/Max/Glass 3. Reconcile the camera/display and
  fixed-focus constraints recorded in `docs/rokid-capture-research.md`; do not blindly
  enable AF or treat a HUD cross as calibrated paper bounds.
- Android [responsiveness guidance](https://developer.android.com/topic/performance/anrs/keep-your-app-responsive):
  blocking the main thread on I/O is a responsiveness risk even if the actual write ran
  on another executor. This supports the deferred cursor/exit work, not an ANR measurement.
- OpenAI [Terms of Use](https://openai.com/policies/terms-of-use/), effective January 1,
  2026: automated/programmatic extraction of data or Output is prohibited for the listed
  individual services. This is an integration/release risk; account-specific permissions
  were not investigated, and this review is not a definitive legal opinion.

## Verification record

Baseline exact source: local Python 3.13.5, **671 passed, 1 skipped**, exit 0.
Initial Python regression run: **8 failed, 19 passed**; the same tests after the first
server fixes: **27 passed**. Additional positive/out-of-order and orphan-file cases were
then added. Android red evidence is pinned above. Final-source test totals and commit/tree
must be recorded in the PR review or run artifacts; do not transplant earlier successes
onto a new HEAD. The initial final-suite attempt also exposed two intentionally pinned
version expectations; these were updated with the declared behavioral patch identifiers.

Runs on: isolated Linux / GitHub Actions; synthetic material only.

```sh
ROKID_CHATGPT_LIVE=0 python -m pytest -q
python -m compileall -q app scripts tests
python -m scripts.check_capture_memory
# Ruff and Android need their tooling; the committed CI runs both.
python -m ruff check .
sh android-relay/gradlew --no-daemon test testDebugUnitTest assembleDebug
git diff --check
```

No live ChatGPT submission, actual ASR/model inference, physical display/camera test,
installation, key replacement, provider change, DB migration, data deletion or merge to
main was performed. Synthetic camera/storage tests do not establish optical usability.

## Resume here — PC-connected Codex

Runs on: Windows PC initially, **saved files and builds only**. Preserve the stop on
additional photography, installs and real-material submission until explicitly lifted.

1. Reconcile branch/HEAD with the PR's final review and check the associated CI run;
   do not use the old PR description's historical HEAD as current. Preserve the existing
   working tree, keys, originals, pending, manifests, database and browser journal.
2. Read the source/authority records above. The existing spread/closer-spread/single-page
   comparisons were already shot; both OCR and darkness remained problematic. Do not
   reclassify them as never tested or demand a repeat before examining saved sources.
3. Use `docs/capture-preflight.md` and `docs/rokid-capture-research.md` on copies of the
   retained photos. Record what is in the original, not just the enhanced preview.
4. Rebuild with the PC's existing signing identity and compare signatures. A CI debug APK
   is an artifact for verification, not permission to replace the installed app. Do not
   uninstall or clear app data to work around a signing mismatch.
5. Prioritize progressive delivery / bounded waits / cursor persistence as separate
   tests-first changes. Carry the source and test evidence into the existing RP tasks;
   don't tick RP-01 through RP-22 complete based on this review.
6. Only after an explicit stop release: a small complete capture/answer/exit/recovery run
   on the exact artifact, followed by repeat/page-count/audio-duration escalation if it
   passes. Do not begin with a 40-page or 150-minute acceptance attempt.

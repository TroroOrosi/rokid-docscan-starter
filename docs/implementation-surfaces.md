# Implementation surfaces

Status: Current inventory of every runnable surface. Updated 2026-09-15.

**Read this before adding anything.** It exists because the same role kept
getting a second implementation: a session would grasp the feature it was asked
for, not the repository, and build alongside something that already worked.
`tests/test_surface_inventory.py` fails when a Gradle module, an Android
`Activity` or a server display module is missing from the tables below, so this
file cannot quietly go stale the way prose guidance does.

A surface listed here is not automatically wanted. Each row carries a status:

- **route** — part of the decided venue route. Extend this.
- **frozen** — kept and tested, gets no new features. A measurement taken on a
  frozen surface does not validate the route (`CLAUDE.md`).
- **probe** — a throwaway spike kept for its evidence. Never ship behaviour here.
- **shared** — a library both routes use. Changing it touches both.

The decisions behind the statuses are in `CLAUDE.md` ("decided venue topology")
and `tasks/plan.md`. Do not restate them here; this is the map, not the reason.

## Gradle modules (`android-relay/settings.gradle.kts`)

| Module | Status | Role |
|---|---|---|
| `:glassdoc` | route | The glasses-side scanner. Owns capture, OCR and the server connection; the phone hosts its server over the phone AP. |
| `:relaycore` | shared | The capture pipeline both apps run: `DocScanController`, OCR, upload, review. The automatic-scan loop lives here; enabled only for the local glasses surface. |
| `:pagequality` | shared | `PageFraming` (OCR text-box margins, not the physical sheet outline) and `ShotScore` (rank an automatic burst). Built for hands-free capture. |
| `:glassinput` | shared | The gesture contract. Plain `java-library`, so its tests run with no Android runtime. |
| `:app` | frozen | The phone relay over CXR-L/CUSTOMVIEW. The only module with CXR-L imports. |
| `:glassapp` | probe | Tap-delivery spike. Deliberately holds no permissions; keep its no-side-effect record intact. |
| `:glassprobe` | probe | Capability spike (camera, network). Separate module so its CAMERA/INTERNET grants cannot weaken `:glassapp`. |

## Android activities

| Activity | Module | Status |
|---|---|---|
| `DocScanGlassActivity` | `:glassdoc` | route |
| `MainActivity` | `:app` | frozen |
| `TapProbeActivity` | `:glassapp` | probe |
| `CapabilityProbeActivity` | `:glassprobe` | probe |

## Things that render for the operator

Three implementations wrap text for the same 480x398 display. That is settled,
not an open question: `AnswerLayout` measures the real font, the server ones
estimate.

| Surface | Where | Status |
|---|---|---|
| `AnswerView` + `AnswerLayout` | `:glassdoc` | route — measures the real font |
| `HudView`, `GlassesHudText`, `FramingGuide` | `:glassdoc` | route — aiming and status on the glasses |
| `app/glasses_view.py` | server | frozen — review HUD, wraps at an estimated column budget |
| `app/hud.py` | server | frozen — the fixed three lines of `/v1/match` only |

## Automatic scanning: built, gated

Named here because "is it implemented?" was answered wrongly from a single
function body on 2026-09-15.

`relaycore/DocScanController` holds the whole loop: `AUTO_BURST_SHOTS=3` at
`AUTO_SHOT_INTERVAL_MILLIS=400`, `AUTO_PAGE_TURN_MILLIS=2500`, the best frame
picked with `:pagequality`, `AUTO_DUPLICATE_BURST_LIMIT=20`,
`AUTO_UNREADABLE_RETRY_LIMIT=40` then `AUTO_UNREADABLE_BACKOFF_MILLIS=1200`,
and auto-commit after `AUTO_COMMIT_COMPLETE_MILLIS=4000`
(`AUTO_COMMIT_UNVERIFIED_MILLIS=12000` when unverified).

`adf12ee` (2026-09-01) made `startAutoCapture()` answer `"Automatic capture is
disabled; use explicit phone controls"`. The reason was the CUSTOMVIEW route's
missing operator tap, not the loop. `:glassdoc` has that tap
(`docs/hardware-measurements.md` §A-2), so the reason does not carry over.

The local surface now replaces the historical commit delays with 3000ms after a visible
still acknowledgement. `ListeningRecorder` / `ListeningService` belong to `:glassdoc`;
`app/local_asr.py` / `app/listening.py` run on the phone. No new Activity/module was added.

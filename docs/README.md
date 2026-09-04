# Documentation index and authority

Status: Current documentation map. Updated 2026-09-01.

When two documents disagree, use this order:

1. current implementation and automated tests;
2. current runbooks listed below;
3. versioned official API or inspected artifact evidence;
4. dated device measurements with a complete version/hash tuple;
5. research, historical notes, and hypotheses.

A build proves compilation only. A repository note proves that an observation
was recorded, not that it applies to another device or firmware.

## Current contracts and runbooks

- `README.md` — project entrypoint and supported topology.
- `CLAUDE.md` — engineering invariants.
- `android-relay/README.md` — relay implementation contract.
- `docs/cxr-l-integration.md` — current CXR-L boundary.
- `docs/device-verification-checklist.md` — physical acceptance evidence form.
- `docs/real-device-operation.md` — supported phone-controlled operation.
- `docs/user-operation-guide.md` — operator and data-handling guide.
- `docs/windows-android-real-device-setup.md` — Windows/Android setup.
- `docs/explain-sessions.md` — server explain-session API.
- `docs/future-proof-architecture.md` — extension boundaries; current where it
  agrees with the implementation and module specs.

Current version tuple:

- Server APP `0.16.0`
- HTTP API `1.15.0`
- Android relay `0.3.16` (`versionCode 21`)
- Glasses input app `0.1.8` (`versionCode 9`; 9 is behaviourally identical to 8
  and differs only because the input classes moved to `:glassinput`)
- Glasses capability probe `0.1.0` (`versionCode 1`, throwaway spike; its four
  questions were answered on hardware 2026-09-04)
- Glasses document scanner `0.1.0` (`versionCode 1`); the glasses own capture,
  Japanese ML Kit recognition and the server connection, and the phone is not in
  the data path. Built and unit-tested; the review flow, the +2EV exposure and
  the 180-degree rotation are **not yet confirmed on hardware**.
- `:glassinput` is a plain `java-library` shared by the glasses apps, so its
  tests run under `test`, not `testDebugUnitTest`
- Glasses View contract `1.9.0`
- CXR-L tested/pinned dependency `1.1.1`; the current Rokid Maven release is
  `1.1.2` and the latest coordinate is `1.2.X-SNAPSHOT`

## Historical measurements and superseded designs

- `docs/capture-timing-findings.md` — relay 0.3.6-era measurements; later input
  measurements supersede its tap hypothesis.
- `docs/exam-solver-architecture.md` — earlier onboard/text-first design.
- `docs/glasses-ux-contract.md` — legacy gesture/UI proposal, not the current
  CUSTOMVIEW input contract.
- `docs/implementation-notes.md` — implementation history; not a runbook.
- `docs/rokid-led-dev-utility.md` — quarantined historical experiment; no
  operational indicator-modification instructions are retained.

Historical files preserve what was believed or measured at the named time.
They must not be used to override a current runbook.

## Research and evidence ledgers

- `docs/documentation-evidence-audit-2026-08-31.md`
- `docs/research-safe-led-and-device-readiness-2026-09-01.md`
- `docs/glasses-app-route-findings.md`
- `docs/glasses-primary-sources-2026-09-03.md` — published-source index for the
  glasses-side route; read before booking another hardware session.
- `report-source.md` — internal claim ledger behind the 2026-08-31 audit.

Research can identify a supported SDK capability without proving that it works
on the measured hardware. Unresolved claims remain explicitly unverified.

## Draft specifications

- `SPEC-custom-app-session.md` — review draft for the official CXR-L
  `CUSTOMAPP` session and glasses-side CXR-S lifecycle foundation. It is not an
  implementation contract until the user accepts its deliberate preinstalled-
  app-only first increment.

## Accepted specifications and implementation plan

- `CAPABILITY-MAP-glasses-app-operation.md` — accepted module boundaries and
  build order for moving the operator control surface into a glasses app.
- `SPEC-glasses-input.md` — accepted first-module specification for normalizing
  and deduplicating glasses input without capture/network side effects.
- `CAPABILITY-MAP-safe-real-device-readiness.md`
- `SPEC-evidence-contract.md`
- `SPEC-safe-capture.md`
- `SPEC-server-contract.md`
- `SPEC-android-readiness.md`
- `SPEC-device-validation.md`
- `tasks/plan.md`
- `tasks/todo.md`
- `refactor-instructions.md` — an older refactor snapshot; individual items may
  already be resolved and must be rechecked against current code.

## Internal progress record

- `.agents/progress/glasses-input-and-real-device-prep.md` — append-only internal
  work history across several commits; never a current operator contract.

## Indicator and input boundary

Supported code and runbooks do not disable, obscure, spoof, or bypass a camera
or privacy indicator. The physical indicator is observed with an independent
camera. SDK callbacks record application state but do not prove physical light
state.

CUSTOMVIEW operator tap delivery is not a current verified control surface. Use
the phone controls until a glasses-side app and its input path pass the physical
checklist on the exact recorded version tuple.

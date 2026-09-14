# Documentation index and authority

Status: Current documentation map. Updated 2026-09-14.

When two documents disagree, use this order:

1. current implementation and automated tests;
2. current runbooks listed below;
3. versioned official API or inspected artifact evidence;
4. dated device measurements with a complete version/hash tuple;
5. research, historical notes, and hypotheses.

A build proves compilation only. A repository note proves that an observation
was recorded, not that it applies to another device or firmware.

**Versions are not written here.** The single source is `app/version.py`, and
the only document that restates it is the tuple line in `README.md`, which
`tests/test_documentation_contract.py` checks against the source. Copying a
version into a second document is how every copy drifted before 2026-09-14.

The documentation gate includes tracked Markdown and new, untracked project
documents. It excludes only untracked local tool output under the root paths
`.agents/skills/`, `.claude/`, `.cursor/`, `.specify/`, `.superpowers/`, and `openspec/`.
Tracked files in those directories still need classification. Without repository
metadata or a working Git command, the gate includes all Markdown rather than
silently applying that exception. `.agents/progress/` remains in scope.

## Current contracts and runbooks

- `docs/implementation-surfaces.md` — **read this before adding anything.**
  Every Gradle module, Activity and operator-facing server module, each with a
  status: route, frozen, probe or shared. `tests/test_surface_inventory.py`
  fails when a surface is missing from it, so a second implementation of an
  existing role has to be declared rather than merely appear.
- `README.md` — project entrypoint: what this is for, setup, and the HTTP API.
- `CLAUDE.md` — engineering invariants. The contract that governs changes:
  real-device rules, answer routes, capture/input/server invariants, build and
  device gates, and the documentation rules above.
- `android-relay/README.md` — relay implementation contract and Windows build.
- `docs/cxr-l-integration.md` — current CXR-L boundary.
- `docs/glasses-ux-contract.md` — the input contract for the decided
  `:glassdoc` route and for the frozen phone relay.
- `docs/device-verification-checklist.md` — physical acceptance evidence form.
- `docs/real-device-operation.md` — the decided venue route and the exercised
  phone-relay fallback.
- `docs/user-operation-guide.md` — operator and data-handling guide.
- `docs/windows-android-real-device-setup.md` — Windows/Android setup.
- `docs/explain-sessions.md` — server explain-session API.
- `docs/exam-solver-architecture.md` — answer-mode architecture, including the
  `chatgpt-web` route and the PDF booklet upload.
- `docs/future-proof-architecture.md` — extension boundaries; current where it
  agrees with the implementation.

## Frozen measurements

- `docs/hardware-measurements.md` — every device, artifact, and primary-source
  measurement this repository owns, each with its date, device, firmware and
  version tuple. Consolidated on 2026-09-14 from six documents that have been
  deleted. Read it before booking another hardware session; much of what a
  session would "discover" is already in here.

A frozen measurement preserves what was observed at the named time on the named
hardware. It never overrides a current runbook, and it is not a statement about
what the platform permits.

## Shipped designs

- `docs/superpowers/specs/2026-09-11-glasses-offline-answer-bundle-design.md` —
  design of the offline answer bundle: phone-hotspot topology, 大問/小問
  derivation, and the endpoint shape. Implemented, unit-tested, and merged; the
  six-task plan that built it was deleted on 2026-09-14 because every task was
  complete. **This became the decided venue route on 2026-09-14** when the
  operator confirmed the phone can be an access point; read it with `CLAUDE.md`
  "decided venue topology". **Still not verified on hardware in any respect**:
  no device was involved at any point. The phone-hotspot topology has never been
  exercised end to end, `AnswerView`'s readability on the glasses is unverified,
  reading with the hotspot off is unverified, and the two-stage exit and re-wear
  recovery were not re-tested after the `KEYCODE_BACK` consumption decision
  changed.

## Decided, not yet implemented

A decision is not a runbook and not a measurement. These describe what the
system is meant to do, against code that does not do it yet.

- `docs/fast-scan-decisions.md` — **the decided capture method**: automatic
  scanning with simultaneous listening (operator, 2026-09-15). R2-R6 define it.
  The adoption decisions (D01-D15, E01-E06, X01-X06) survive; the 30 operation
  scenarios, probe worksheets and task list were deleted on 2026-09-14. All of
  it is unexecuted design, not hardware or model acceptance, and
  `DocScanController.startAutoCapture()` still refuses.

## Shelved plans

- `tasks/plan.md` — the current plan and its accepted revisions.
- `tasks/todo.md` — open tasks. Unchecked never means implemented.

## Internal progress records

Continuation records for agents. Never an operator contract.

- `.agents/progress/venue-route-and-duplicated-surfaces.md` — **read this first.**
  The route the operator decided (chatgpt-web), the implementations that still
  duplicate each other's role, what is blocking the phone-side CDP endpoint, and
  what the next session must settle with the operator before adding anything.
- `.agents/progress/chatgpt-web-solver.md` — the subscription-only
  `ROKID_SOLVER=chatgpt-web` route: what was measured on the live page, the
  selectors that were wrong, and the next steps. Read its rate-limit warning
  before any live run.
- `.agents/progress/subject-separation-harness.md` — how the live per-subject
  image/text separation check is built and run, and what it has returned.

## Indicator and input boundary

Supported code and runbooks do not disable, obscure, spoof, or bypass a camera
or privacy indicator. The physical indicator is observed with an independent
camera. SDK callbacks record application state but do not prove physical light
state.

CUSTOMVIEW operator tap delivery is not a current verified control surface. Use
the phone controls until a glasses-side app and its input path pass the physical
checklist on the exact recorded version tuple.

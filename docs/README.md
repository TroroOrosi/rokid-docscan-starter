# Documentation index and authority

Status: Current documentation map. Updated 2026-09-23.

実機確認前の入口は [目的・機能の全体整理](requirements-audit.md)。
目的／採否と全機能の不足 → [実装配置図](implementation-surfaces.md) → [設計](../tasks/plan.md)・
[既存CQ/RPタスク](../tasks/todo.md) → [継続記録](../.agents/progress/pr37-capture-quality.md) の順で読む。
実機操作・導入・GPT送信の停止は継続する。文書の保存やPC検査は停止解除ではない。

Separate the intended requirement from evidence of what works:

- User decisions and the current section of `tasks/plan.md` define intended behavior.
  Implementations and passing tests do not override an unmet requirement.
- Current source and tests establish implemented behavior. Current runbooks describe
  that behavior and its limits; a plan does not prove implementation.
- Versioned official APIs and inspected artifacts establish the supported surface.
- Device claims require dated measurements with the exact version/hash tuple.
- Historical plans and research retain context. Their superseded resume instructions
  are not current work; use the RP list in `tasks/todo.md`.

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

- `docs/capture-quality.md` — PC用の原寸点検・補正候補・登録条件・方式比較。本流の品質ゲートは未接続。

- `docs/capture-geometry.md` — PC用の単ページ角度補正・鮮鋭度診断部品。capture-qualityから再利用する既存部品。本流未接続。

- `docs/rokid-capture-research.md` — Rokid公式仕様・Camera2/OCRの境界、保存写真の細部診断、停止解除後の限定確認。

- `docs/capture-preflight.md` — PR37の撮影再開前チェック。保存写真の無送信検査、原本保全、制限ヒープ試験。

- `docs/implementation-surfaces.md` — **read this before adding anything.**
  Repository map covering the server, Android, scripts, tests, CI, configuration and records.
  Every Gradle module, Activity and operator-facing server module carries a
  status: route, frozen, probe or shared. `tests/test_surface_inventory.py`
  fails when a surface is missing from it, so a second implementation of an
  existing role has to be declared rather than merely appear.
- `docs/multimodal-scan.md` — standalone capture, diagrams, original image/audio input; ASR only on the compatibility route; physical acceptance pending.
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
- `docs/exam-solver-architecture.md` — answer-mode architecture, including
  original image/audio input, chatgpt-web, and unfinished segmentation/delivery connections.
  The superseded architecture is retained in an explicitly historical section.
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

## Implementation plans and adoption decisions

- `tasks/plan.md` — current rationalized plan first; superseded plans preserved in a historical section.
- `tasks/todo.md` — active RP tasks with acceptance criteria; older checkboxes are history.
- `docs/requirements-audit.md` — 目的・使用条件・全機能の現状・採否・実機前の順序と5方向の点検。
  旧FS/R/S/Xの対応と2026-09-15の調査履歴も保持。実装／物理受け入れの完了ではない。
- `docs/fast-scan-decisions.md` — automatic/manual scan and listening decisions.
  The current implementation is described in `docs/multimodal-scan.md`.
  D/E/X comparisons retain their original evidence; physical/model acceptance is pending.

## Internal progress records

- `.agents/progress/pr37-capture-quality.md` — **撮影品質作業の再開入口（PR37→PR38）。** 31件対応表、利用者訂正、画像比較・露出準備の検証と本流未接続の残作業。

- `.agents/progress/pr37-objective-review.md` — **2026-09-17時点のレビュー。** 整合性・録音・終了保存の回帰修正、客観的な未解決事項。実機停止は維持。

- `.agents/progress/pr37-camera-research.md` — **objective-reviewの次に読む。** 撮影仕様調査、配送・診断修正、検証の範囲。追加撮影は停止のまま。

- `.agents/progress/pr37-offline-remediation.md` — **新しいcamera-research記録の後に読む。** 追加修正と停止条件。続いて既存2記録の全文を読む。

- `.agents/progress/pr37-predevice-handoff.md` — PR37の実機前修正、検証範囲、Windows Codexへの引き継ぎと未実装の対応表。

- `.agents/progress/multimodal-scan.md` — **read this in full after the PR37 handoff.** 保存・停止時の実機状態と経緯。
  以前の実装・実機導入・ASRの測定と、追加実装を始める前の境界を保持する。

Continuation records for agents. Never an operator contract.

- `.agents/progress/venue-route-and-duplicated-surfaces.md` — earlier continuation context.
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
or privacy indicator. The operator waived the external LED audit on 2026-09-15.
This is not a physical observation; SDK callbacks do not prove light state.

CUSTOMVIEW operator tap delivery remains unverified; its frozen relay uses phone
controls. The decided glassdoc route uses its own input adapter. Its complete
operation still requires acceptance on the exact installed APK and firmware.

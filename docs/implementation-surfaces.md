# Implementation surfaces

Status: Current repository map and runnable-surface inventory. Updated 2026-09-23; source baseline `7a05928`.

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
- **probe** — a diagnostic or experiment. Its output alone does not validate the product route.
- **shared** — reusable code or tooling. Check every consumer before changing it.

採否・目的・残作業は [requirements-audit](requirements-audit.md)、設計は [plan](../tasks/plan.md)。
本書は所在を所有する。routeという分類は、会場で動作確認済みという意味ではない。

## リポジトリ全体の配置

| 範囲 | Status | 責務・実行場所・境界 |
|---|---|---|
| `app/` | route | スマホ上のFastAPI。取得資料・設問・解析・答案・入力版を管理。旧APIとoptional providerも同居するため、下の区分で扱う |
| `android-relay/` | shared | グラス本流、共用library、凍結したスマホrelay、探針。Gradle単位の区分は下表 |
| `scripts/capture_*.py` | probe | PC上の原寸点検・geometry・sampling・preflight・admission・evaluation。正式登録の品質ゲートは未接続 |
| `scripts/check_capture_memory.py` | probe | PCの保存画像によるメモリ条件検査。グラスの実撮影精度・電池の証明ではない |
| `scripts/eval_exam.py` / `scripts/eval_fast_scan.py` / `scripts/evaluate.py` / `scripts/run_exam_deck.py` / `scripts/make_sample_pages.py` | probe | 合成資料作成・部品／答案評価。実providerを呼ぶ設定とオフライン検査を区別し、送信停止中に実モデル試験を実行しない |
| `scripts/prepare_local_asr.py` / `scripts/build_local_asr.sh` / `scripts/benchmark_local_asr.py` | probe | 互換ASRの準備・測定。chatgpt-webの起動・解析の必須条件ではない |
| `scripts/watch_glasses.py` | probe | スマホ側での再装着・起動の部分測定。実機状態を変更し得るため、リポジトリ点検で起動しない |
| `app/devtools/rokid_led.py` / `scripts/rokid_led.py` | frozen | デバイスコマンドを持たないstub。インジケータを操作する経路に戻さない |
| `tests/` / Android各moduleの `src/test/` | shared | PC／CIの回帰、fixture、契約検査。合成試験と実資料正答率・物理受け入れを区別する |
| `.github/workflows/` | shared | Python、スマホ依存stack、Windows、Androidの検査と成果物保存。端末導入・会場検証ではない |
| `requirements*.txt` / `constraints-phone.txt` / `android-relay/gradlew*` | shared | PCとスマホの依存を分け、Androidは指定wrapperを使用。依存更新・端末導入は別の変更 |
| `Dockerfile` / `docker-compose.yml` | shared | PC等でサーバを起動する既存構成。会場のスマホ起動手順として扱わない |
| `.env.example` | shared | 設定例。実鍵・ログイン情報は入れない。環境変数が存在するだけでは本流での採用を意味しない |
| `docs/` / `tasks/` / `.agents/progress/` | shared | 文書索引／現在の設計とtask／コマンド出力と再開状態。過去の計画は現行作業から分離する |
| `data/` / `.env` / Android `build/` | shared | Git管理外の資料・機密設定・生成物。コードの所在と混同せず、無断削除・資料の公開をしない |
| `.agents/skills/` / `.claude/` / `.cursor/` / `.specify/` / `.superpowers/` / `openspec/` | shared | Git管理外のローカル作業支援。存在だけで製品機能・採用済みworkflowと判断しない |

## スマホサーバ内の役割

| 実装 | Status | 接続と制限 |
|---|---|---|
| `app/main.py` / `app/db.py` / `app/config.py` / `app/input_identity.py` / `app/glassdoc_contract.py` | route | API、永続化、実運用設定、入力版とグラス契約。finalizeは設問ごとに保存するがHTTPは全問待ち |
| `app/layout.py` / `app/subjects.py` | route | 現状のOCR由来の小問・教科推定。原本の設問一覧としての正確性は未達、RP-12の整理対象 |
| `app/source_bundle.py` / `app/page_pdf.py` | route | 原本画像・原音の添付生成。全画像が既定、PDFは比較用。同じ確認済み会話では再生成を省く |
| `app/solvers/chatgpt_web.py` / `app/solvers/cdp.py` / `app/browser_guard.py` | route | ログイン済みChromeへの送信、応答・添付確認、送信不明／制限時の停止。ブラウザpoolは作らない |
| `app/listening.py` / `app/audio_formats.py` | route | chunk保存・連続性・完了・原音。主経路はASRを起動・待機しない。原音がGPTで利用されたかは別評価 |
| `app/answer_text.py` / `app/answer_diagrams.py` | route | 表示可能な答案・図の検査。配送はanswer-bundle、表示はAnswerView。生成内容の正答を保証する検査ではない |
| `app/provider_registry.py` / `app/solvers/registry.py` / `app/solvers/base.py` | shared | provider選択・共通契約。互換fallbackで必要な画像・音声を落とさない |
| `app/analyzers/` / `app/extractors/` / `app/explainers/` / `app/explainer.py` / `app/llm.py` / `app/llm_http.py` / solverのAPIアダプタ | shared | 既存API／optional provider。独立した再認識・解説・ローカルLLMを本流の前処理として追加しない |
| `app/local_asr.py` / `app/transcribe.py` | shared | 他providerの互換文字起こし。chatgpt-webへ文字起こしを送るためには使わない |
| `app/retrieval.py` / `app/matching.py` / `app/summarize.py` / `app/overlay.py` | shared | 既存検索・照合・要約・画像上の位置情報。冊子原本の代替や紙固定ARの実証とは扱わない |
| `app/version.py` | shared | 版の正本。文書で版を再掲するのはREADMEのtupleのみ |

本流の処理順は [exam-solver-architecture](exam-solver-architecture.md) の現行節を参照。
この配置図とtableの検査は全関数の正しさの証明ではない。変更時には対象の呼出元・試験を実ソースで照合する。

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
| `AnswerView` + `AnswerLayout` | Viewは`:glassdoc`、Layoutは`:relaycore` | route — measures the real font |
| `HudView`, `GlassesHudText`, `FramingGuide` | `:glassdoc` | route — aiming and status on the glasses |
| `app/glasses_view.py` | server | frozen — review HUD, wraps at an estimated column budget |
| `app/hud.py` | server | frozen — the fixed three lines of `/v1/match` only |

## Automatic scanning: implemented loop, missing quality gate

Named here because "is it implemented?" was answered wrongly from a single
function body on 2026-09-15.

`relaycore/DocScanController` holds the whole loop: `AUTO_BURST_SHOTS=3` at
`AUTO_SHOT_INTERVAL_MILLIS=400`, `AUTO_PAGE_TURN_MILLIS=2500`, the best frame
picked with `:pagequality`, `AUTO_DUPLICATE_BURST_LIMIT=20`,
`AUTO_UNREADABLE_RETRY_LIMIT=40` then `AUTO_UNREADABLE_BACKOFF_MILLIS=1200`,
on the automatic path. The unreadable retry limit introduces a backoff, not a final stop.
These OCR/text-box heuristics do not detect the full sheet or prove readability.

`adf12ee` (2026-09-01) made `startAutoCapture()` answer `"Automatic capture is
disabled; use explicit phone controls"`. The reason was the CUSTOMVIEW route's
missing operator tap, not the loop. `:glassdoc` has that tap
(`docs/hardware-measurements.md` §A-2), so the reason does not carry over.

The local surface uses 3000ms after a visible still acknowledgement. This is a composition
review; it is not quality approval. The old 4000/12000ms delays are not its current contract.
`GlassCamera` now meters before requesting a JPEG; it is not a page-detection preview.
`JapaneseOcr` runs before candidate selection/registration, but calibrated readability admission
is still disconnected. `LocalCaptureSession` saves committed photos before background upload.
`ListeningRecorder` / `ListeningService` belong to `:glassdoc`; `app/listening.py` preserves
originals on the phone. Compatibility ASR is separate from the primary route.

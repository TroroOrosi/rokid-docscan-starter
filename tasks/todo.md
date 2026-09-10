# Tasks: Safe real-device readiness

**2026-09-10 夜の再開順:** FS-59 → FS-60 → FS-61/62（実機ゲート）→ FS-63/64 →
FS-65 → 既存FS-12/20/35〜38/42/47を統合。現行契約は [plan.md](plan.md#answer-sheet-20260910)。
今回の追加は計画保存まで。未チェック項目を実装済みとは扱わない。

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

- [x] Every official action named by the accepted spec is registered
      dynamically and represented by an allow-listed signal type.
- [x] KeyEvent down/up and broadcast observations use one monotonic timeline and
      log no content, credentials, tokens, images, or OCR.
- [x] Unknown actions/keys are observable but produce no normalized action or
      side effect.

**Verification:**

- [x] Failing tests are added first for the official action catalog, event
      ordering, and unknown-event behavior.
- [x] `gradle --no-daemon -p android-relay :glassapp:testDebugUnitTest`
      passes.
- [x] `gradle --no-daemon -p android-relay :glassapp:assembleDebug` passes.
- [x] On the explicit glasses serial, a controlled gesture sequence records the
      raw device event, broadcast (if any), and Activity KeyEvent with exact
      timing and the APK/firmware tuple.

**Dependencies:** Accepted `SPEC-glasses-input.md`; no implementation task.

**Files likely touched:**

- `android-relay/glassapp/src/main/java/dev/rokid/docscanglass/input/InputSignal.java`
- `android-relay/glassapp/src/main/java/dev/rokid/docscanglass/input/OfficialKeyBroadcasts.java`
- `android-relay/glassapp/src/main/java/dev/rokid/docscanglass/input/InputCalibrationLog.java`
- `android-relay/glassapp/src/main/java/dev/rokid/docscanglass/input/GlassKeyEvents.java`
- `android-relay/glassapp/src/main/java/dev/rokid/docscanglass/TapProbeActivity.java`
- `android-relay/glassapp/src/test/java/dev/rokid/docscanglass/input/InputCalibrationLogTest.java`

**Estimated scope:** Medium (6 files plus the glasses-app version).

## Checkpoint GI-A: Hardware calibration

- [x] GI-1 focused tests and glass APK build pass.
- [x] Controlled physical gestures are matched to raw/broadcast/KeyEvent rows.
- [x] No photo, network request, upload, or registration occurs.
- [x] Correlation evidence and exact version/hash tuple are checkpointed before
      choosing a deduplication bound.

## Task GI-2: Normalize and deduplicate one physical gesture

**Description:** Encode the measured event pairs in a pure-Java normalizer. One
gesture emits at most one `GlassesInputAction`; distinct gestures preserve order,
and late/repeated/reordered events fail closed.

**Acceptance criteria:**

- [x] The correlation window is derived from GI-1 evidence and recorded as a
      firmware-scoped decision, not a platform constant.
- [x] Broadcast-only, KeyEvent-only, paired, repeated, reordered, late, and
      unknown cases have deterministic unit tests.
- [x] The Activity displays/logs one normalized action without assigning it to
      capture, navigation, registration, or app exit.

**Verification:**

- [x] Failing correlator tests are added before implementation.
- [x] `gradle --no-daemon -p android-relay :glassapp:testDebugUnitTest`
      passes.
- [x] A controlled hardware sequence produces exactly one normalized action per
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

- [x] Receiver registration is paired exactly once with lifecycle cleanup and
      does not call `abortBroadcast()`.
- [x] Restart/focus recovery clears transient correlation state and never replays
      a normalized action.
- [x] Unknown/system-owned inputs remain unconsumed and have no application side
      effect.

**Verification:**

- [x] Focused lifecycle/normalizer tests pass.
- [x] `gradle --no-daemon -p android-relay testDebugUnitTest assembleDebug`
      passes from the verified ASCII build path.
- [x] Install/restart/gesture hardware check passes on the recorded tuple.

**Dependencies:** GI-2.

**Files likely touched:**

- `android-relay/glassapp/src/main/java/dev/rokid/docscanglass/input/GlassesInputReceiver.java`
- `android-relay/glassapp/src/main/java/dev/rokid/docscanglass/input/GlassesInputNormalizer.java`
- `android-relay/glassapp/src/main/java/dev/rokid/docscanglass/TapProbeActivity.java`
- `android-relay/glassapp/src/test/java/dev/rokid/docscanglass/input/GlassesInputNormalizerTest.java`

**Estimated scope:** Medium (4 files).

## Checkpoint GI-B: `glasses-input` complete

- [x] All `:glassapp` unit tests pass.
- [x] Full Android unit/build gate passes.
- [x] Controlled hardware sequence emits exactly one normalized action per
      supported gesture after install and restart.
- [x] No camera/network/upload/registration side effect is observed.
- [x] Specs, evidence, and progress record match the implemented behavior.
- [x] Human review approves moving to `custom-app-session`.


---

<a id="fast-scan-tasks"></a>

# Tasks: グラス自動スキャン・同時リスニング・スマホのモバイル回線AI

Status: **実機前準備まで実施。FS-02完了、FS-01一部準備済み。アプリ機能と実機評価は未着手**。2026-09-07。
再開時の訂正に従い「グラスWi-Fi未接続、スマホのモバイル回線あり、PC/自前サーバ不要」を本番条件にする。
完全オフライン解答をP0から外し、外部AIと非API処理を組み合わせる。
仕様と根拠は [詳細計画](plan.md#glasses-autoscan-listening-20260906)。
先行の未完了項目を削除せず、この拡張の完了判定はR1〜R13で行う。
見直し・事例・試験票は [実機前の準備ノート](../docs/fast-scan-preflight.md#start)。

**追加要望（2026-09-07）:** 内部例に加え、[外部6アプリの公式資料・公開実装](../docs/fast-scan-external-examples.md)を参考にする。
各該当FSの着手時に参照E01〜E06の採用/変更/見送り理由を記録し、
[X01〜X06](../docs/fast-scan-preflight.md#external-derived-cases)を検証へ組み込む。
外部事例の調査完了と、実装・実機評価の合格は別に管理する。タスクIDと既存の依存順は維持する。

## パス表記と検証方法

以下の接頭辞は既存ソースへの相対パス。新しいクラス名は計画名であり、現時点で存在するとは限らない。

| 略記 | ディレクトリ |
|---|---|
| GD / GDT | android-relay/glassdoc/src/main/java/dev/rokid/docscanglass/doc / 同androidTest/javaの同package（純粋テストはsrc/test） |
| GP | android-relay/glassprobe/src/main/java/dev/rokid/docscanglass/probe |
| PA | android-relay/app/src/main/java/dev/rokid/docscanrelay |
| RC / RCT | android-relay/relaycore/src/main/java/dev/rokid/docscanrelay / 同src/test/javaの同package |
| GI / GIT | android-relay/glassinput/src/main/java/dev/rokid/docscanglass/input / 同src/test/javaの同package |
| PQ / PQT | android-relay/pagequality/src/main/java/dev/rokid/docscanrelay / 同src/test/javaの同package |

| ID | コマンド/手順 |
|---|---|
| V-PY | py -3.12 -m pytest -q（個別指定は末尾にtests/対象.pyを追加） |
| V-LINT | ruff check . および git diff --check |
| V-JVM | ASCIIの最新Androidソースで .\gradlew.bat --console=plain test testDebugUnitTest |
| V-APK | 同環境で .\gradlew.bat --console=plain test testDebugUnitTest assembleDebug :glassdoc:lintDebug :glassapp:lintDebug |
| V-INST | 適切なテストrunnerを設定した対象モジュールの connectedDebugAndroidTest。端末IDを固定し実機手順に記録 |
| V-FIELD | plan.md §11と既存の実機checklistに従う。版/hash/入力/ネットワーク/音源/目視LEDと結果を記録 |

各タスクは原則1〜5ファイルのS/M規模。ファイル表は責任境界であり、
ビルド設定・fixture追加で超える場合は着手前に小分けする。
実装前の失敗テスト→変更→関連テスト→2〜3タスクごとの結合確認を行う。
実機インストールやモデル取得は計画作成では実施していない。

小さい結合確認の区切りはFS-01〜03、04〜05、06〜07、08〜10、11〜12、
13〜15、16〜17、18〜20、21〜23、24〜25、26〜27、28〜30、31〜32、33〜34、
35〜37、38〜39、40〜42、43〜44、45〜46、47〜49、50〜51とする。
各区切りで関連テスト、必要なビルド、直前の動作経路を確認する。
下記のM0〜M5は、この小確認に加える実機・機能単位の判定点。

## FS-01: 評価用資料と再現手順を固定する

- [ ] 実装・検証完了

**目的:** 速度・精度・ページ欠落を同じ条件で比較できる基準を作る。

**完了条件:** 調整用/評価用を分ける。B5/A4・図表・跨ぎ問題・音声の正解と期待ページ順を記録する。

**外部事例の反映:** E01〜E06の根拠と採用判断、X01〜X06の期待結果を準備済み。各ケースを対応するFSの実試験へ落とし、独立した保持資料の出典/利用条件/媒体hashを記録する。内部の合成18問を外部ベンチマーク実績に数えない。

**検証:** V-PY: tests/test_fast_scan_pack.py、py -3.12 scripts/eval_fast_scan.py。実媒体の使用範囲と保存場所は評価開始時に確認。

**依存:** なし。 **規模:** M。

**対象:** tests/fixtures/fast_scan/cases.json / scripts/eval_fast_scan.py / tests/test_fast_scan_pack.py / docs/fast-scan-preflight.md。

**準備済み:** 合成14ケース18問、原音用の台本、正解・人手採点基準、参照/結果の照合CLI、新規回帰14件。実写/実録音と独立した品質評価セットは未作成なので、FS-01全体は未完了。

## FS-02: 文書検査の既知の失敗を直す

- [x] 実装・検証完了

**目的:** ツール生成文書57件による既知の検査失敗を解消する。

**完了条件:** 本体の未分類文書を検出する能力は残す。未追跡ツール生成物の境界を明示し、全pytestを成功させる。

**検証:** V-PY全体＋V-LINT。新しい本体文書の未分類を検出する反例も検査。

**依存:** なし。 **規模:** S。

**対象:** tests/test_documentation_contract.py / docs/README.md。

**実績:** 既知57件と境界の反例を再現後に修正。通常の未追跡本体文書、追跡済みツール配下文書、Git不在時の検査を保持。全pytest 427 passed、文書テスト7 passed、Ruff成功。commit 9b6da5f。

## FS-03: グラスで解析フレームと撮影と録音を同時検証する

- [ ] 実装・検証完了

**目的:** カメラとマイクの同時動作という最も重要な未確認点を先に解く。

**完了条件:** YUV取得→JPEG撮影20回中も録音サンプルが続く。対応stream/format、メモリ、LED目視、失敗条件を記録する。

**検証:** V-APK。実機5分の既知音源＋撮影。データで途切れを照合する。

**依存:** FS-01。 **規模:** M。

**対象:** GP/ConcurrentCaptureProbe.java / GP/CapabilityProbeActivity.java / android-relay/glassprobe/src/main/AndroidManifest.xml / android-relay/glassprobe/build.gradle.kts / docs/glasses-primary-sources-2026-09-03.md。

## FS-04: Wi-FiなしのCXR転送を実証する

- [ ] 実装・検証完了

**目的:** バイナリAPIの存在を、対象端末で使える転送経路へ進める。

**完了条件:** 小さい要求/応答、JPEG、音声を相互検証。グラスWi-Fi未接続、スマホWi-Fiオフ/モバイル回線オンで帯域・最大payload・再送を計測する。

**検証:** V-APK。Global Hi Rokidの版を記録し、hash一致・送受信時間・欠番を確認。

**依存:** FS-01。 **規模:** M。

**対象:** PA/RokidGlobalLink.java / GP/TransportProbe.java / android-relay/glassprobe/build.gradle.kts / android-relay/glassprobe/src/main/AndroidManifest.xml / docs/glasses-primary-sources-2026-09-03.md。

## FS-05: スマホをロックしたまま接続を維持できるか検証する

- [ ] 実装・検証完了

**目的:** 日常のスマホ操作0回を成立させる背景実行方法を確認する。

**完了条件:** 消灯・ポケット内・Hi Rokid背景化・再起動後にグラスから接続/結果表示できる条件を記録。モバイル通信も継続し、毎回スマホを開く方式を合格にしない。

**検証:** V-APK。Android15/16の前景サービス開始条件と30分のロック中受信を照合。

**外部比較:** E06 / X05。ローカル保存と画面消灯中の同期を分け、スマホ再表示後だけ成功する方式を合格にしない。

**依存:** FS-04。 **規模:** M。

**対象:** PA/CompanionRuntimeService.java / PA/MainActivity.java / android-relay/app/src/main/AndroidManifest.xml / android-relay/app/build.gradle.kts / docs/windows-android-real-device-setup.md。

## FS-06: スマホのモバイル回線で音声認識を評価する

- [ ] 実装・検証完了

**目的:** 自前サーバなしで読み上げの原音を認識できる公式経路を確認する。

**完了条件:** F-51Fの4G/5Gから実AIで日本語/英語・数字・否定を認識。認証、時刻精度、遅延、上りMB、末尾欠落を記録。

**検証:** V-APK。既知の1分/10分音源を参照文字列・時刻と比較。グラス/スマホにWi-Fiを使わない。

**依存:** FS-01。 **規模:** M。

**対象:** PA/CloudAsrProbe.java / PA/AiProbeSettings.java / android-relay/app/build.gradle.kts / android-relay/app/src/main/AndroidManifest.xml / docs/glasses-primary-sources-2026-09-03.md。

## FS-07: 画像＋音声の解答をスマホ経由で評価する

- [ ] 実装・検証完了

**目的:** 自前サーバ不要のAI経路をアプリ全体を作る前に実証する。

**完了条件:** Firebase AI Logic等の公式経路で画像と原音が両方必要な問題を解く。構造化結果、入力制限、対象APKの認証、初回/定常遅延と正誤を記録。

**検証:** V-APK。Wi-Fiなし＋スマホ4G/5Gで画像なし/音声なし/音声だけ条件変更の対照を比較。長い入力の分割も試す。

**依存:** FS-01, FS-06。 **規模:** M。

**対象:** PA/MultimodalAiProbe.java / PA/AiProbeSettings.java / android-relay/app/src/main/assets/ai-provider-capabilities.json / android-relay/app/build.gradle.kts / docs/glasses-primary-sources-2026-09-03.md。

### Checkpoint M0: 実現可能性

- [ ] FS-01〜07の証拠が揃う。グラスWi-Fiなし＋スマホ4G/5G・ロックで、紙面と音声が必要な1問を解く。Bluetoothの帯域不足は未解決と記録して設計を先に見直す。
- [ ] 関連テスト/ビルドを確認し、既存の進捗記録へ根拠と次の作業を記録する。

## FS-08: セッションの純粋な状態と永続状態を定義する

- [ ] 実装・検証完了

**目的:** モード、ページ改訂、録音、完了/中断を1つの明確な契約にする。

**完了条件:** UUID/generationと独立したcapture/audio/completionを保持。CLOSED/INTERRUPTEDを区別し、未確認画像を送信しない。録音終了後の取り直しでマイクを再開しない。

**検証:** V-JVM: SessionStateTest。各状態へのイベントと保存失敗を表で検査。

**依存:** FS-01。 **規模:** M。

**対象:** RC/SessionState.java / RC/SessionEvent.java / RC/SessionStore.java / RCT/SessionStateTest.java / RCT/SessionStoreTest.java。

## FS-09: 相関窓と入力の重複排除を分ける

- [ ] 実装・検証完了

**目的:** 速い連続操作を残したまま同じ物理操作の二重配送だけを抑える。

**完了条件:** 970ms以内の別のスワイプ/ダブルタップを保持。同じgesture IDの複数配送は1回。BACK/UPの残りで次状態を終了しない。

**検証:** V-JVM: GlassesInputNormalizerTest、GestureIdentityTest。実機の記録済み列と近接した別ジェスチャを再生。

**依存:** FS-08。 **規模:** M。

**対象:** GI/GlassesInputNormalizer.java / GI/InputSignal.java / GI/GlassesInputAction.java / GIT/GlassesInputNormalizerTest.java / GIT/GestureIdentityTest.java。

## FS-10: モード選択と完了後の初期画面を実装する

- [ ] 実装・検証完了

**目的:** 要求された最初の画面と、閲覧終了後に迷わない起動を先に作る。

**完了条件:** 通常/リスニングの選択を保存し開始。CLOSED後はダブルタップ2回の終了消灯を維持し、再装着起動で選択画面、途中は再開候補。終了保存にネットワークを必要としない。消灯/装着の実機条件はFS-61/62に従う。

**検証:** V-APK＋V-INST: LaunchFlowTest。新規・暖機・kill後・一時フォーカス喪失を検査。

**依存:** FS-08, FS-09。 **規模:** M。

**対象:** GD/DocScanGlassActivity.java / GD/HudView.java / RC/SessionStore.java / GDT/LaunchFlowTest.java。

## FS-11: 写真の描画完了通知を正しくする

- [ ] 実装・検証完了

**目的:** 実画像が見えていない時間を3秒の確認時間に数えない。

**完了条件:** デコード失敗・未描画・画面不可視でACKしない。onDraw後に対象generationを通知し、古いACKを拒否する。

**検証:** V-APK＋V-INST: ReviewPresentationTest。主スレッド遅延とフォーカス喪失を注入。

**依存:** FS-08。 **規模:** M。

**対象:** GD/GlassesCaptureSurface.java / GD/HudView.java / GD/DocScanGlassActivity.java / GDT/ReviewPresentationTest.java。

## FS-12: 全文を保持する解答レイアウトを作る

- [ ] 実装・検証完了

**目的:** 本番solverを待たず、長い答えを最後まで読める描画を成立させる。

**完了条件:** 64字超/1000字/長単語/式を幅で折り返し、ページを連結すると全文一致。文字を三点リーダで省略しない。

**検証:** V-JVM＋V-INST: AnswerLayoutTest。480×640の画面と大きい文字で実表示確認。

**依存:** FS-10。 **規模:** M。

**対象:** GD/AnswerLayout.java / GD/HudView.java / GDT/AnswerLayoutTest.java / GDT/AnswerRenderingTest.java。

### Checkpoint M1: 操作と画面

- [ ] 選択画面、別ジェスチャの認識、描画後の通知、全文レイアウトが通る。CLOSEDの再起動で古い解答が復活しない。
- [ ] 関連テスト/ビルドを確認し、既存の進捗記録へ根拠と次の作業を記録する。

## FS-13: 共有制御から外部HTTP必須依存を外す

- [ ] 実装・検証完了

**目的:** 既存の撮影/保存資産をスマホ管理の保存・外部AI処理へ接続する小さい境界を作る。

**完了条件:** DocScanBackendを注入でき、旧HTTPのlong IDと新UUIDの対応はアダプタに閉じ込める。操作実行器が同期通信でブロックされない。

**検証:** V-JVM: BackendRoutingTest、既存RCテスト。V-PYはHTTP互換の回帰。

**依存:** FS-08。 **規模:** M。

**対象:** RC/DocScanBackend.java / RC/DocScanApi.java / RC/DocScanController.java / RCT/BackendRoutingTest.java / PA/MainActivity.java。

## FS-14: スマホ内の資料保存先を作る

- [ ] 実装・検証完了

**目的:** 自前サーバなしでページをスマホに正規化して保存する。

**完了条件:** (document,page_index)とrevisionで更新。端末内の原本は向き補正済みPNG。失敗した置換で前の確定版を失わない。

**検証:** V-JVM/V-INST: PhoneDocumentStoreTest。Python参照出力との寸法/向き/hash条件照合。

**依存:** FS-13。 **規模:** M。

**対象:** RC/PhoneDocumentStore.java / RC/PhoneBackend.java / RC/PageNormalizer.java / RCT/PhoneDocumentStoreTest.java / tests/fixtures/fast_scan/normalization.json。

## FS-15: 転送プロトコルを固定する

- [ ] 実装・検証完了

**目的:** グラスとスマホの再送・重複・取り違えの規則を共通化する。

**完了条件:** ID/版/hash/連番/ACKを定義。古いセッション、未知の版、異なるhashの同一IDを拒否する。

**検証:** V-JVM: TransferProtocolTest。順序逆転、欠番、重複、上限超過を試験。

**依存:** FS-04, FS-08。 **規模:** M。

**対象:** RC/TransferEnvelope.java / RC/TransferProtocol.java / RC/ChunkLedger.java / RCT/TransferProtocolTest.java / RCT/ChunkLedgerTest.java。

## FS-16: スマホのCXR受信を背景サービスに接続する

- [ ] 実装・検証完了

**目的:** 画面がなくても資料を受信し、状態をグラスへ返す。

**完了条件:** 前景サービス等の実証済み寿命で動作。ペア端末を照合し保存完了後ACK。MainActivityの終了だけで受信を止めない。

**検証:** V-APK＋ロック中の受信再試験。サービス再作成で同じ要求を二重保存しない。

**依存:** FS-05, FS-14, FS-15。 **規模:** M。

**対象:** PA/CompanionRuntimeService.java / PA/RokidGlobalLink.java / PA/PhoneTransferReceiver.java / android-relay/app/src/main/AndroidManifest.xml / android-relay/app/src/test/java/dev/rokid/docscanrelay/PhoneTransferReceiverTest.java。

## FS-17: グラスの送受信アダプタを接続する

- [ ] 実装・検証完了

**目的:** CXRServiceBridgeによる転送をグラスのセッション状態と結ぶ。

**完了条件:** 接続世代を管理し、切断中は端末保存。再接続で採用ページのみ再送し、解答を正しいセッションに戻す。

**検証:** V-APK＋V-INST: GlassTransferTest。SDK依存を模した障害注入と実機hash一致。

**依存:** FS-15, FS-16。 **規模:** M。

**対象:** GD/GlassCompanionLink.java / GD/DocScanGlassActivity.java / android-relay/glassdoc/build.gradle.kts / GDT/GlassTransferTest.java。

## FS-18: AI接続と認証の準備状態を確認する

- [ ] 実装・検証完了

**目的:** 初回設定後、スマホを取り出さずモバイル回線でAIを使えるようにする。

**完了条件:** SDK/モデル/能力、外部送信先、利用枠を設定。秘密キーをAPKへ埋め込まず実APKのApp Checkとロック中/翌日の認証更新を確認。未設定/期限切れを成功扱いにしない。

**検証:** V-JVM/V-INST: AiProviderReadinessTest。無効設定/認証失敗/利用枠超過/通信断を注入。デバッグ認証だけで本番合格にしない。

**依存:** FS-06, FS-07。 **規模:** M。

**対象:** PA/AiProviderSettings.java / PA/AiProviderReadiness.java / PA/MainActivity.java / android-relay/app/src/test/java/dev/rokid/docscanrelay/AiProviderReadinessTest.java / android-relay/app/src/main/assets/ai-provider-capabilities.json。

## FS-19: クラウドの画像・音声対応solverを組み込む

- [ ] 実装・検証完了

**目的:** M0で選んだ公式スマホ連携を問題入力から全文解答を返す実行先にする。

**完了条件:** 非同期に複数画像と音声を入力し構造化した全文を返す。容量/音声数/MIME制限を送信前に検査し413/認証エラーを区別。

**検証:** V-APK＋CloudMultimodalSolverTestと実AI評価。文字列チャット成功を両入力の証拠にしない。

**依存:** FS-07, FS-13, FS-18。 **規模:** M。

**対象:** PA/CloudAiProvider.java / PA/CloudMultimodalSolver.java / PA/AiRequestBudget.java / android-relay/app/src/test/java/dev/rokid/docscanrelay/CloudMultimodalSolverTest.java / android-relay/app/src/test/java/dev/rokid/docscanrelay/AiRequestBudgetTest.java。

## FS-20: 既存の設問分割をスマホへ移す

- [ ] 実装・検証完了

**目的:** サーバにある有効な問題分割の知識を、端末内の同じ契約へ移す。

**完了条件:** 小問/図/ページ跨ぎ/重複番号の対応を保持。Python参照と同じfixtureから同じ問題IDと対応ページを得る。

**検証:** V-JVM: ProblemSegmentationTest＋V-PYのlayout/レビュー回帰。

**依存:** FS-01, FS-14。 **規模:** M。

**対象:** RC/ProblemSegmentation.java / RC/ProblemRecord.java / RCT/ProblemSegmentationTest.java / tests/fixtures/fast_scan/segmentation.json / tests/test_layout.py。

### Checkpoint M2-A: スマホ経由の小さい解析経路

- [ ] グラス→スマホ保存→モバイル回線のAIで1問解答→グラス表示が通る。自前HTTPサーバなし、設定済み認証で動く。
- [ ] 関連テスト/ビルドを確認し、既存の進捗記録へ根拠と次の作業を記録する。

## FS-21: カメラの低解像度フレームを解析できるようにする

- [ ] 実装・検証完了

**目的:** 手動静止画のみのカメラに、バックプレッシャー付き解析経路を追加する。

**完了条件:** 最新フレーム1つを処理し古い画像を閉じる。静止画と解析のサイズはM0で使えた組合せを採用し、確認中はストリーム停止。

**検証:** V-APK＋フレーム漏れ/タイムアウト/再開の実機確認。

**依存:** FS-03。 **規模:** M。

**対象:** GD/GlassCamera.java / GD/AnalysisFrameSource.java / GD/GlassesCaptureSurface.java / GDT/CameraStreamLifecycleTest.java。

## FS-22: 紙面外周検出を実装する

- [ ] 実装・検証完了

**目的:** 文字枠だけでは分からないページ全体の収まりを判定する。

**完了条件:** 紙の四辺・余裕・遮蔽を評価。図だけ/余白/白い机を含む保留データで判定し、UNKNOWNをCOMPLETEにしない。

**検証:** V-JVM: PageGeometryTest＋200ページの検出評価。必要な依存だけ比較後に固定。

**外部比較:** E03/E05 / X02/X04。外周検出と安定判定を分け、検出失敗の方向に合う短い案内を評価する。

**依存:** FS-01, FS-21。 **規模:** M。

**対象:** PQ/PageGeometry.java / PQ/PageDetector.java / PQT/PageGeometryTest.java / PQT/PageDetectorTest.java / android-relay/pagequality/build.gradle.kts。

## FS-23: 静止と新しいページの検知を実装する

- [ ] 実装・検証完了

**目的:** 見続けた同じ紙を連写せず、ページ入替時にすぐ再開する。

**完了条件:** 安定継続時間と画質を評価。OCR類似度だけで同一ページと判断せず、同じテンプレートの別ページも受け入れる。

**検証:** V-JVM: AutoCapturePolicyTest、PageTransitionTest。揺れ/反射/重複ページの記録フレームを再生。

**外部比較:** E03 / X02。公開実装の撮影前の待機・取消・再発火抑制を比較する。四辺形の近さだけで別ページを捨てず、3秒の撮影後確認とは別の時計で検証する。

**依存:** FS-22。 **規模:** M。

**対象:** PQ/AutoCapturePolicy.java / PQ/PageTransitionTracker.java / PQ/ShotScore.java / PQT/AutoCapturePolicyTest.java / PQT/PageTransitionTest.java。

## FS-24: 3秒確認と取り直しを状態機械で実装する

- [ ] 実装・検証完了

**目的:** 自動撮影から確認・確定・同じページの取り直しを通す。

**完了条件:** 描画ACK後3000ms。期限前の接触を優先し、撮り直し画像のrevisionを変更。未表示画像のアップロード0件。

**検証:** V-JVM: AutoReviewPolicyTest＋V-INST。2999/3000ms、遅延ACK、デコード失敗、フォーカス喪失を検査。

**外部比較:** E01/E02 / X01。自動撮影後の取り直しを同じページへ反映。毎ページの保存タップを増やさず、確定後の修正はFS-39へ接続する。

**依存:** FS-08, FS-09, FS-11, FS-23。 **規模:** M。

**対象:** RC/AutoReviewPolicy.java / RC/DocScanController.java / RC/CaptureReviewStore.java / RCT/AutoReviewPolicyTest.java / GDT/ReviewPresentationTest.java。

## FS-25: 採用ページをディスクへ保存して非同期送信する

- [ ] 実装・検証完了

**目的:** 電話への転送完了を待たず次のページを撮れるようにする。

**完了条件:** 画像をキューに耐障害保存してから次へ。再送は不足チャンクだけ。同時撮影1枚、破棄revisionの送信0件。

**検証:** V-JVM/V-INST: PendingPageQueueTest。保存直後/ACK前後のkillを試験。

**外部比較:** E06 / X06。端末内保存・スマホ保存・AI待機を別状態として観測し、保存できただけで同期成功としない。

**依存:** FS-14, FS-15, FS-17, FS-24。 **規模:** M。

**対象:** RC/PendingPageQueue.java / RC/TransferScheduler.java / RC/DocScanController.java / RCT/PendingPageQueueTest.java / RCT/TransferSchedulerTest.java。

## FS-26: 通常撮影の終了と最後のページを確定する

- [ ] 実装・検証完了

**目的:** ダブルタップで新規撮影を止め、最終ページを落とさずスマホ解析へ進める。

**完了条件:** 撮影中/確認中/無ページの終了を明示的に扱う。最後の3秒を保証し、終了解除後の取り直しも同じ番号で行える。

**検証:** V-JVM: ScanFinishPolicyTest。遅延した画像/再送ACKが届く順序を入れ替える。

**依存:** FS-09, FS-19, FS-20, FS-25。 **規模:** M。

**対象:** RC/ScanFinishPolicy.java / RC/CaptureActionRouter.java / RC/DocScanController.java / RCT/ScanFinishPolicyTest.java / GD/DocScanGlassActivity.java。

## FS-27: 通常撮影の最小完走を検証する

- [ ] 実装・検証完了

**目的:** モード選択からスマホ経由の完成済み通常解答と終了までを、最小表示で実機につなぐ。未完了結果の混在・到着順不同の閲覧はFS-38で追加する。

**完了条件:** グラスWi-Fiなし＋スマホ4G/5G・ロックで通常20ページを完走。3秒、取り直し、最後の1枚、全文表示、閲覧終了後の選択画面を確認。

**検証:** V-FIELD通常20ページ、V-APK、関連V-JVM。速度を撮影/転送/推論に分けて記録。

**依存:** FS-10, FS-12, FS-16, FS-19, FS-20, FS-26。 **規模:** M。

**対象:** GDT/NormalScanEndToEndTest.java / android-relay/app/src/androidTest/java/dev/rokid/docscanrelay/PhoneBackendTest.java / docs/device-verification-checklist.md。

### Checkpoint M2-B: 通常モード

- [ ] 通常20ページを選択→自動撮影→3秒→終了→全文解答→初期画面まで完走。転送待ち中も操作が反応する。
- [ ] 関連テスト/ビルドを確認し、既存の進捗記録へ根拠と次の作業を記録する。

## FS-28: 連続録音と録音開始の通知を実装する

- [ ] 実装・検証完了

**目的:** リスニング選択後、撮影開始前からグラスのマイクを記録する。

**完了条件:** 音声サンプル受信後にREC表示。カメラ/HTTPとは別スレッド。権限拒否、silenced、経路変更を区別する。

**検証:** V-INST: ContinuousRecorderTest＋既知音源の実機録音。通常モードでは録音しない。

**依存:** FS-03, FS-08, FS-10。 **規模:** M。

**対象:** GD/ContinuousRecorder.java / GD/RecordingHealth.java / GD/DocScanGlassActivity.java / android-relay/glassdoc/src/main/AndroidManifest.xml / GDT/ContinuousRecorderTest.java。

## FS-29: 音声を停止せず分割保存する

- [ ] 実装・検証完了

**目的:** 長い録音をメモリに保持せず、強制終了後も復旧できるようにする。

**完了条件:** 1〜2秒単位でサンプル数/連番/hashを保存。ファイル切替で録音を再起動しない。最後の未保存区間を識別する。

**検証:** V-JVM/V-INST: AudioChunkStoreTest。30分相当、途中kill、満杯、末尾flushを検査。

**依存:** FS-28。 **規模:** M。

**対象:** RC/AudioChunkStore.java / RC/AudioManifest.java / GD/ContinuousRecorder.java / RCT/AudioChunkStoreTest.java / GDT/AudioRecoveryTest.java。

## FS-30: 音声を優先して送る転送制御を実装する

- [ ] 実装・検証完了

**目的:** 写真転送で音声や終了操作のメッセージが滞らないようにする。

**完了条件:** 制御→音声→画像の優先度と公平性を定義。codecと実効帯域をM0に合わせ、再送時にも音声サンプルの順序を保つ。

**検証:** V-JVM: TransferSchedulerTest＋帯域制限下の実機同時転送。圧縮前後の重要語認識も比較。

**依存:** FS-04, FS-15, FS-25, FS-29。 **規模:** M。

**対象:** RC/TransferScheduler.java / RC/AudioTransferCodec.java / GD/GlassCompanionLink.java / RCT/TransferSchedulerTest.java / RCT/AudioTransferCodecTest.java。

## FS-31: スマホ側で音声の完全な受信を管理する

- [ ] 実装・検証完了

**目的:** 単一ファイル上書きではなく、録音の欠番と完了を管理する。

**完了条件:** 保存済みACKを返し、同一連番の異なる内容を拒否。total_samplesと最終連番が一致するまで完成扱いにしない。

**検証:** V-JVM/V-INST: PhoneAudioStoreTest。重複、順序逆転、欠番、古い録音IDを検査。

**依存:** FS-14, FS-16, FS-29, FS-30。 **規模:** M。

**対象:** RC/PhoneAudioStore.java / RC/PhoneBackend.java / PA/PhoneTransferReceiver.java / RCT/PhoneAudioStoreTest.java / RCT/AudioManifestTest.java。

## FS-32: リスニングの二段階終了を実装する

- [ ] 実装・検証完了

**目的:** 第1ダブルタップで撮影だけ、第2ダブルタップで録音を終える。

**完了条件:** 第1操作後も録音継続。同じgesture IDを2段階へ使わず、待機中の別の第2操作も終了として受理。終了後の取り直しでも音声終了を保持し、最後の画像確認/保存と音声flush後に解析可能にする。

**検証:** V-JVM: ListeningFinishTest＋実機の近接ダブルタップ。撮影中/3秒確認中にも試験。

**依存:** FS-09, FS-26, FS-28, FS-31。 **規模:** M。

**対象:** RC/ListeningFinishPolicy.java / RC/CaptureActionRouter.java / RC/DocScanController.java / GD/DocScanGlassActivity.java / RCT/ListeningFinishTest.java。

## FS-33: 音声認識を連続録音とモバイル通信に統合する

- [ ] 実装・検証完了

**目的:** 録音中から文字起こしを進め、終了後の待ち時間を減らす。

**完了条件:** 時刻付き文字起こしと原音対応を保存し、窓の重なりを二重化しない。通信断/429/ASR失敗を空文字で成功にせず、欠番を再処理。

**検証:** V-APK＋CloudAsrIntegrationTest。数字・否定・無音・末尾発話と回線復旧を比較。音声数/要求容量の制限も検査。

**依存:** FS-06, FS-18, FS-31。 **規模:** M。

**対象:** PA/CloudTranscriber.java / PA/AudioRequestBuilder.java / RC/TranscriptStore.java / android-relay/app/src/test/java/dev/rokid/docscanrelay/AudioRequestBuilderTest.java / android-relay/app/src/androidTest/java/dev/rokid/docscanrelay/CloudAsrIntegrationTest.java。

## FS-34: 音声区間と設問を関連付ける

- [ ] 実装・検証完了

**目的:** 撮影順と読み上げ順が違っても、必要な音声を問題へ渡す。

**完了条件:** 時刻はヒントに留め、問題番号/内容/全体の文脈で対応する。複数設問にまたがる音声を欠かさない。

**検証:** V-JVM: ListeningAlignmentTest。音声先行/撮影先行/ページ跨ぎのfixtureで照合。

**外部比較:** E04 / X03。記録時刻から原音へ戻せる対応を保持し、時刻のみの割当と内容を含む割当を比較。前ページへの訂正や複数問題で共有する会話を欠かさない。

**依存:** FS-20, FS-33。 **規模:** M。

**対象:** RC/ListeningAlignment.java / RC/QuestionMaterial.java / RCT/ListeningAlignmentTest.java / tests/fixtures/fast_scan/listening-alignment.json。

### Checkpoint M3-A: 同時録音

- [ ] 撮影/取り直し/終了時も録音が続き、最後のダブルタップでのみ止まる。スマホへ欠番なく届き、時刻付きASRが残る。
- [ ] 関連テスト/ビルドを確認し、既存の進捗記録へ根拠と次の作業を記録する。

## FS-35: 複数ページの画像と音声を問題入力へ渡す

- [ ] 実装・検証完了

**目的:** 最初のページの画像だけで解く制限をなくす。

**完了条件:** 全関連画像/図表、文字起こし、必要な原音区間と入力版を渡す。長い録音の分割でも問題間の共通文脈を欠かさず、要求上限を守る。

**検証:** V-JVM: QuestionMaterialTest＋実モデルの両入力依存問題。資料のみ/音声のみの対照を取る。

**依存:** FS-19, FS-20, FS-34。 **規模:** M。

**対象:** RC/QuestionMaterial.java / RC/QuestionMaterialBuilder.java / PA/CloudMultimodalSolver.java / RCT/QuestionMaterialTest.java / tests/fixtures/fast_scan/multimodal-questions.json。

## FS-36: 答えを全文で保存し形式と材料不足を検証する

2026-09-10改訂: 記入用解答のみを生成・表示する。答案に必要な途中式/証明/理由/作図を含める。
互換APIの従来モードを保ち、新契約では補足解説を除外し、資料不足と仮回答を区別する。
着手: Python solverのanswer_onlyモードと回帰9件。スマホの本番統合・実AI評価は未完。

- [ ] 実装・検証完了

**目的:** 正確さと完全性を画面より前の段階で確保する。

**完了条件:** 64文字制限なし。小問数・選択肢・単位・数値の検査を行い、材料不足や未準備モデルを答えと区別。推論途中の文字列を完成結果にしない。

**検証:** V-JVM: AnswerValidationTest＋参照fixture。記述式/証明/長い式で欠落と余計な解説を検査。

**依存:** FS-35。 **規模:** M。

**対象:** RC/AnswerRecord.java / RC/AnswerValidator.java / RC/PhoneBackend.java / PA/CloudMultimodalSolver.java / RCT/AnswerValidationTest.java。

## FS-37: 解析ジョブを永続化して重複と古い答えを防ぐ

- [ ] 実装・検証完了

**目的:** スマホの再起動や再送後も同じ資料への解析を正しく再開する。

**完了条件:** 入力digest＋モデル/プロンプト版で識別し改訂時に古い答えを無効化。回線断/429/5xxは上限付き再試行、認証/利用上限は区別。事業者の保証なしに二重課金ゼロとしない。

**検証:** V-JVM/V-INST: AnalysisJobStoreTest。AI応答だけの喪失、送信中kill、音声差替え、重複ANALYZE、回線復旧を試験。

**依存:** FS-14, FS-31, FS-36。 **規模:** M。

**対象:** RC/AnalysisJobStore.java / RC/AnalysisCoordinator.java / PA/CompanionRuntimeService.java / RCT/AnalysisJobStoreTest.java / RCT/AnalysisCoordinatorTest.java。

## FS-38: 完成した問題からグラスに返す

- [ ] 実装・検証完了

**目的:** 全問題の解析完了を待たず、全文が確定した問題を読めるようにする。

**完了条件:** 問題の順序を固定し、後着結果で閲覧位置を動かさない。解法/根拠/自信度を常時表示せず答えだけを返す。

**検証:** V-JVM/V-INST: AnswerReaderTest。未完了が混ざるデッキと通信断でも移動/終了が反応する。

**依存:** FS-12, FS-17, FS-36, FS-37。 **規模:** M。

**対象:** RC/AnswerReader.java / RC/TransferProtocol.java / GD/HudView.java / GD/DocScanGlassActivity.java / GDT/AnswerReaderTest.java。

## FS-39: 過去ページの取り直しを全工程へ反映する

- [ ] 実装・検証完了

**目的:** 直前の間違った確定をグラスだけで修正可能にする。

**完了条件:** 同じpage_indexの新revisionへ置換。失敗時は旧版を維持し、成功後は影響する問題だけ新入力版で解く。

**検証:** V-JVM/V-INST: PageRevisionTest。送信中/解析中/未接続の取り直しを試験。

**外部比較:** E01/E02 / X01。3秒を過ぎて気付いた欠けも、グラスだけで過去ページを選んで修正できることを確認する。

**依存:** FS-25, FS-35, FS-37。 **規模:** M。

**対象:** RC/PageRevisionPolicy.java / RC/PhoneDocumentStore.java / RC/DocScanController.java / RCT/PageRevisionTest.java / GDT/RetakeFlowTest.java。

### Checkpoint M4: 画像と音声から解答

- [ ] 両入力を必要とする評価問題をスマホのモバイル回線経由で解く。改訂画像や古い音声に基づく答えが出ない。
- [ ] 関連テスト/ビルドを確認し、既存の進捗記録へ根拠と次の作業を記録する。

## FS-40: 事前準備と現場の状態を分かりやすくする

- [ ] 実装・検証完了

**目的:** 認証や接続不備で現場に入ってから行き詰まることを減らす。

**完了条件:** 初回に権限/ペア/AI認証/利用枠/空き容量/背景動作を確認。診断をモード画面へ並べずスマホ接続待ち・AI通信待ち等の短い状態を表示。

**検証:** V-APK。認証切れ、mic拒否、Bluetooth断、モバイル不通、利用枠超過を個別に注入。

**依存:** FS-16, FS-18, FS-28, FS-38。 **規模:** M。

**対象:** PA/AiProviderReadiness.java / PA/MainActivity.java / RC/SessionReadiness.java / GD/HudView.java / RCT/SessionReadinessTest.java。

## FS-41: 背景復帰と接続寿命を本番向けに固める

- [ ] 実装・検証完了

**目的:** スマホ画面を操作しないまま、2回目以降の利用を安定させる。

**完了条件:** 初回準備後のロック/省電力/サービス再作成を扱う。対応する起動条件を実装し、Hi Rokidの状態も復旧可能にする。

**検証:** V-APK＋実機30分、グラスを閉じて再度開く/スマホ再起動後の明示した条件を確認。

**外部比較:** E06 / X05。自動同期の存在を背景動作の根拠にせず、消灯中の受信から結果返却までを実測する。

**依存:** FS-05, FS-16, FS-32, FS-37。 **規模:** M。

**対象:** PA/CompanionRuntimeService.java / PA/RokidGlobalLink.java / PA/CompanionLifecycle.java / android-relay/app/src/main/AndroidManifest.xml / android-relay/app/src/test/java/dev/rokid/docscanrelay/CompanionLifecycleTest.java。

## FS-42: 全状態で中断復旧と完了済み分離を検証する

- [ ] 実装・検証完了

**目的:** force-stopを通常の現場条件として扱う。

**完了条件:** 各保存境界で復旧し、未確認ページを再表示。CLOSEDは復活せず、INTERRUPTEDは選択可能。録音を無操作で再開しない。

**検証:** V-JVM/V-INST: SessionRecoveryTest。確定前後のkillを網羅し、保存失敗を含めて検査。

**依存:** FS-08, FS-29, FS-32, FS-37, FS-38。 **規模:** M。

**対象:** RC/SessionStore.java / RC/SessionRecovery.java / GD/DocScanGlassActivity.java / RCT/SessionRecoveryTest.java / GDT/ProcessDeathTest.java。

## FS-43: Bluetooth条件で転送量を最適化する

- [ ] 実装・検証完了

**目的:** Wi-Fiが使えない現場の待ち時間を、画質を保ったまま減らす。

**完了条件:** S/T＋Aと帯域を測る。JPEGサイズ/解像度/チャンクサイズを比較し、文字/図/数式の品質を合格させる。転送遅延を隠さない。

**検証:** V-FIELD: BTのみの20ページ＋録音、画質評価。高解像度が必要なページの劣化を比較。

**依存:** FS-23, FS-25, FS-30, FS-36。 **規模:** M。

**対象:** GD/GlassCamera.java / RC/PhotoCaptureSettings.java / RC/TransferScheduler.java / tests/fixtures/fast_scan/transfer-profiles.json / docs/device-verification-checklist.md。

## FS-44: AIの精度・速度・モバイル通信量を最適化する

- [ ] 実装・検証完了

**目的:** 実際のモバイル回線で現場用モデルと問題単位の送信方針を確定する。

**完了条件:** 受信/保存を優先し並列要求を制限。評価資料の正答率/回答率、遅延、上り/再送MB、費用、電池/熱を記録。設定上限後の追加要求を止め品質未達は未達とする。

**検証:** V-FIELD: Wi-Fiなし＋スマホ4G/5Gの100問以上。調整用資料と分離し弱電波・通信断・サービス制限も確認。

**依存:** FS-01, FS-19, FS-33, FS-35, FS-36, FS-37。 **規模:** M。

**対象:** PA/CloudMultimodalSolver.java / PA/CloudTranscriber.java / PA/AiUsageBudget.java / RC/AnalysisCoordinator.java / docs/device-verification-checklist.md。

## FS-45: 残容量と保存期間を制御する

- [ ] 実装・検証完了

**目的:** 長い録音や転送待ちで突然資料を失わないようにする。

**完了条件:** 録音用空き領域を確保。未送信は自動削除せず、採用済み/受信済み/完了済みで保持方針を区別。満杯時に中断保存できる。

**検証:** V-JVM: StorageBudgetTest。写真/音声の各保存先を満杯にし、既存資料が残ることを確認。

**依存:** FS-14, FS-25, FS-29, FS-31, FS-42。 **規模:** M。

**対象:** RC/StorageBudget.java / RC/RetentionPolicy.java / RC/AudioChunkStore.java / RCT/StorageBudgetTest.java / RCT/RetentionPolicyTest.java。

## FS-46: 読みやすさと高速操作を調整する

- [ ] 実装・検証完了

**目的:** グラスで無理なく正しい問題の答えを読めるようにする。

**完了条件:** 文字サイズ変更でも全文保持。先頭/最後の問題とページ境界で迷わず往復でき、速いスワイプを取りこぼさない。

**検証:** V-INST＋操作者評価。数式/長文/表、明るい現場、左右の視認性を確認。

**外部比較:** E05 / X04。撮影時の短い案内も操作者評価に含め、音声案内の常時追加でリスニングを妨げない。

**依存:** FS-09, FS-12, FS-38。 **規模:** M。

**対象:** GD/AnswerLayout.java / GD/HudView.java / RC/AnswerReader.java / GDT/AnswerRenderingTest.java / docs/user-operation-guide.md。

### Checkpoint M5-A: 現場耐性

- [ ] 切断、ロック、熱、容量、kill、長文、速い入力の試験を満たす。モデル性能が未達なら未達のまま報告する。
- [ ] 関連テスト/ビルドを確認し、既存の進捗記録へ根拠と次の作業を記録する。

## FS-47: サーバ互換の全文契約と文書の差分を整える

- [ ] 実装・検証完了

**目的:** 旧64文字制限やphone専用の説明が新しい経路へ流入するのを防ぐ。

**完了条件:** 任意のHTTP経路でも新契約は全文を保持。既存phone経路の挙動を無断変更しない。端末ごとの操作/原本/モデルの意味を記録。

**検証:** V-PY: test_solvers/test_review_flow/test_glasses_view/test_versioning。API変更時だけ版を更新。

**依存:** FS-36, FS-38。 **規模:** M。

**対象:** app/solvers/llm_adapter.py / app/solvers/registry.py / app/glasses_view.py / tests/test_glasses_view.py / tests/test_solvers.py。

## FS-48: 版数と運用手順を実装に合わせる

- [ ] 実装・検証完了

**目的:** 将来の作業が古いSDK/画面/モデルの前提で進まないようにする。

**完了条件:** glassdoc/relay/protocol/HUD/APIの適切な版を更新。openApp成功記録とSDK install未確認を区別し、露出補正やsdk_hintの古い説明を整理。

**検証:** V-PYの文書/版数検査＋git diff --check。原証拠と新APKのtupleを照合する。

**依存:** FS-41, FS-42, FS-47。 **規模:** M。

**対象:** app/version.py / README.md / docs/README.md / docs/user-operation-guide.md / CLAUDE.md。

## FS-49: 自動テストとAPK検証を完了する

- [ ] 実装・検証完了

**目的:** 実機へ渡す成果物の出所と既存機能の回帰を確認する。

**完了条件:** 全pytest/Ruff/Android test・testDebugUnitTest・assemble・lint成功。新SDKの版/ライセンス/対象Androidを固定しAPK署名/hash/版を記録。

**検証:** V-PY全体＋V-LINT＋V-APK。品質レビューで重大な未解決事項を残さない。

**依存:** FS-43, FS-44, FS-45, FS-46, FS-48。 **規模:** M。

**対象:** android-relay/app/build.gradle.kts / android-relay/glassdoc/build.gradle.kts / android-relay/README.md / docs/windows-android-real-device-setup.md。

## FS-50: 両モードの現場受入試験を完了する

- [ ] 実装・検証完了

**目的:** 実際の条件で、速さ・正確さ・スマホを触らないことを確認する。

**完了条件:** 通常20ページ×5回、録音30分＋20ページ。グラスWi-Fiなし、スマホ4G/5G、端末間Bluetooth、ロック中で完走。最終画像/発話・録音連続性・LEDを外部観察。

**検証:** V-FIELD全項目。撮影/Bluetooth転送/携帯上り/ASR/解答の時間と正誤を記録。通信断からの復旧は別試験。

**依存:** FS-27, FS-32, FS-38, FS-41, FS-49。 **規模:** M。

**対象:** docs/device-verification-checklist.md / docs/windows-android-real-device-setup.md / docs/glasses-primary-sources-2026-09-03.md。

## FS-51: 終了と再利用の最終受入・進捗記録を残す

- [ ] 実装・検証完了

**目的:** 一度動いた後も繰り返し使える状態で完了する。

**完了条件:** 閲覧終了→次回選択を50回確認。失敗/中断/完了の保持状態と未確認事項を明示し、採用モデルと通信profileを確定する。

**検証:** V-FIELD: コールド/暖機/kill/つる折りと再開。R1〜R13に結果を対応付ける。

**依存:** FS-42, FS-48, FS-50。 **規模:** M。

**対象:** docs/user-operation-guide.md / tasks/plan.md / tasks/todo.md / .agents/progress/glasses-input-and-real-device-prep.md。

### Checkpoint 完了

- [ ] R1〜R13の合格を証拠で示す。自動テスト/実機試験/AI精度を分け、未検証の機能を完成扱いしない。
- [ ] 関連テスト/ビルドを確認し、既存の進捗記録へ根拠と次の作業を記録する。

## 追加機能：必須経路の後に評価

下記も改善候補として残す。モバイル回線のAI利用と同時録音が必須経路。完全オフライン推論は追加評価にする。

### FS-52: 録音中の目印と撮影の再開

- [ ] 録音のみ状態のタップで目印、後スワイプで撮影へ戻す。録音を止めず、どのページ/音声位置かを保存する。

**依存:** FS-51。 **対象の目安:** ListeningFinishPolicy / AudioManifest / CaptureActionRouter / ListeningFinishTest。

**検証:** 関連する純粋ロジックの回帰＋対象条件の実機試験。新しい依存や未確認SDK能力を使う場合は一次資料と小さい能力試験から始める。

### FS-53: 履歴と失敗問題だけの再解析

- [ ] 直近資料をグラスで開く。入力版を確認して失敗問題だけ再解析し、新規開始の最短経路を増やさない。

**依存:** FS-51。 **対象の目安:** AnswerReader / SessionStore / AnalysisCoordinator / HistoryFlowTest。

**検証:** 関連する純粋ロジックの回帰＋対象条件の実機試験。新しい依存や未確認SDK能力を使う場合は一次資料と小さい能力試験から始める。

### FS-54: 見開き・反り・台形への対応を拡張

- [ ] 原本と派生画像を区別し、左右分割・冊子の補正で設問順を維持する。実資料の評価で改善がある場合だけ有効化する。

**依存:** FS-51。 **対象の目安:** PageDetector / PageNormalizer / ProblemSegmentation / PageGeometryTest。

**検証:** 関連する純粋ロジックの回帰＋対象条件の実機試験。新しい依存や未確認SDK能力を使う場合は一次資料と小さい能力試験から始める。

### FS-55: スマホ内AIによる非API・圏外経路を評価

- [ ] スマホ内ASRや画像対応推論を比較し、精度/速度/通信量に利益がある部分から組み込む。完全ローカル解答は実機品質基準を満たした場合のみ有効にし、実装時にASR/画像推論/モデル保存へ小分けする。

**依存:** FS-51。 **対象の目安:** LocalInferenceProbe / ModelStore / 評価fixture / 実機記録。

**検証:** 関連する純粋ロジックの回帰＋対象条件の実機試験。新しい依存や未確認SDK能力を使う場合は一次資料と小さい能力試験から始める。

### FS-56: 端末間Wi-Fiによる任意の高速転送

- [ ] 将来グラスのWi-Fi利用が許容された場合だけ別環境で比較する。今回の本番条件を満たす方法としてテザリングを要求せず、必須のBluetooth経路を保持する。

**依存:** FS-51。 **対象の目安:** LocalWifiTransport / TransferScheduler / CompanionLifecycle / TransportSwitchTest。

**検証:** 関連する純粋ロジックの回帰＋対象条件の実機試験。新しい依存や未確認SDK能力を使う場合は一次資料と小さい能力試験から始める。

### FS-57: Rokid標準AI/AIUIの連携を一次資料から検証

- [ ] 任意の画像と録音の入力、構造化結果のアプリ返却、Global対応、利用条件を実証する。画面を開けるだけでは合格にしない。

**依存:** FS-51。 **対象の目安:** 公式資料の記録、隔離した能力probe、入出力fixture。

**検証:** 関連する純粋ロジックの回帰＋対象条件の実機試験。新しい依存や未確認SDK能力を使う場合は一次資料と小さい能力試験から始める。

### FS-58: スマホ不在時のグラス単体推論を評価

- [ ] 将来用。low_ram端末で実ASR/解答を測り、精度・熱・メモリが不十分なら保存/後送の代替状態を明示する。

**依存:** FS-51。 **対象の目安:** 能力probe、モデルmanifest、評価fixture。

**検証:** 関連する純粋ロジックの回帰＋対象条件の実機試験。新しい依存や未確認SDK能力を使う場合は一次資料と小さい能力試験から始める。

## 2026-09-10追加：答案・GPT・消灯と再装着（優先実施）

### FS-59: 途中のローカル解答実装を再開可能な単位にする

- [ ] 検証完了

**目的:** 既存 `relaycore/.../study/` の5クラス・4テストを再利用し、未実装の画面と区別する。
**完了条件:** 既存AnswerViewTestの参照先AnswerViewがないことを再確認し、削除せず実装待ちとして管理。共通データ/保存/閲覧のテスト結果とhashを保存する。答案の式を落とさない契約に照合する。
**検証:** JDK17のASCIIビルドコピーへ対象ソースをhash照合して同期後、`gradlew.bat --no-daemon :relaycore:testDebugUnitTest --tests 'dev.rokid.docscanrelay.study.*'`。画面テストはFS-12/65で実装後に実行する。
**依存:** なし（既存途中成果物）。 **規模:** S（検証と進捗更新）。
**対象:** `study/` の既存成果物、既存進捗記録。新しい同等reader/storeを作らない。

### FS-60: 共通テスト・東大形式の答案評価を固定する

- [ ] 実装・検証完了

**目的:** 「答案の全内容だけ」を検証可能にし、撮影品質だけの評価から脱する。
**完了条件:** 選択/複数欄/途中式/証明/字数指定/英作文/音声依存/作図を含む評価表を作る。元資料の年度・大問・小問・欄IDを保持し、調整用と未使用評価を分離。記述式は人が確認した要件表で採点し、出題意図を模範解答と偽らない。
**検証:** `py -3.12 -m pytest -q tests/test_answer_sheet_solver.py` に加え、評価manifestの欠番・参照切れ・形式別集計を確認。実AI未実行と実行済みを分離して記録する。
**依存:** FS-01の既存評価資産。 **規模:** M。
**対象:** 既存評価script、評価manifest、答案fixture、`tests/test_answer_sheet_solver.py`、実機試験票（5ファイル以内に区切る）。

### FS-61: ホームを出さず実際に消灯する経路を確定する

- [ ] 実装・実機検証完了

**目的:** `finish()` や黒表示を消灯と扱う誤りを防ぐ。
**完了条件:** 公式SDKの候補とDevicePolicyManagerの機能/有効化条件を確認。二回目のダブルタップでCLOSED保存→資源解放→実消灯し、保存失敗を隠さない。権限不足・lockNow無作用・画面ロックがある場合を未達として返す。
**検証:** 終了窓2999/3000/3001ms・同一gesture重複・別操作解除の単体試験。承認範囲を確認した実機試験でDisplay OFF/目視/ホームのちらつきと消灯までの時間を記録する。
**依存:** FS-08/09の終了・入力契約。probeは端末確認から先行可能。 **規模:** M。
**対象:** GD/DocScanGlassActivity.java、必要な消灯adapter、manifest、最小権限XML、終了試験（最大5ファイル）。管理者有効化は今回の計画承認を端末設定変更承認へ拡張しない。

### FS-62: 再装着から一回だけアプリを起動する

- [ ] 実装・実機検証完了

**目的:** 終了したグラスアプリ自身の常駐に依存せず、スマホ操作0回で再利用する。
**完了条件:** wearing通知をスマホの既存epoch検査から状態処理へ渡し、終了後のfalse→trueでのみopenAppを要求。重複true/旧epoch/再接続/装着中終了で再起動しない。つる開閉と実着脱を別に評価し、起動後はモード選択、録音は停止を保持する。
**検証:** 状態表の単体試験→ロック中スマホ＋グラスWi-Fiなしで着脱/つる開閉/サービス再作成を含む50回。通知到着と実起動・前景・操作可能までを区別する。
**依存:** FS-05/41の背景動作、FS-61の閉じた状態。 **規模:** M。
**対象:** PA/RokidGlobalLink.java、PA/CompanionRuntimeService.java、装着状態policyと試験、実機試験票（最大5ファイル）。

### Checkpoint A: 答案とライフサイクルの前提

- [ ] FS-59/60の自動検証結果とFS-61/62の実機結果を区別して記録。実機未接続でも契約側作業は継続可能。
- [ ] 消灯/再装着が未達なら、ホームへ戻る等の代替を要件達成扱いせず、残る条件を記録する。

### FS-63: GPT中継の認証と利用境界を固定する

- [ ] 実装・検証完了

**目的:** 管理型クラウドからGPTを使い、秘密キーを端末へ渡さない。
**完了条件:** 配置先/リージョン/利用予算/アプリ認証を確定し、利用者・セッションごとの入力/結果アクセスを検査。モデル/入力サイズ/要求数の許可範囲と利用量管理をサーバ側で強制。APK・エラー・ログにキー/資料本文を含めない。
**検証:** 認証なし/期限切れ/他セッション/サイズ超過/連続要求を拒否するHTTPテスト、secretなしの設定検査。クラウド公開前に対象・設定・費用をレビュー可能にする。
**依存:** FS-18、今回の管理型中継候補の承認。 **規模:** M。
**対象:** 中継認証module、API契約module、対応テスト、配置設定、運用文書（最大5ファイル）。既存認証を比較し、管理者APIキーをAPKへ配らない。

### FS-64: 一大問をGPTで解き、完全な小問答案を保存する

- [ ] 実装・検証完了

**目的:** 原画像・共通文脈から完成答案を返す最小の本番経路を通す。
**完了条件:** 全入力終了のmanifestを確認してから解析し、複数画像＋必要な文字起こしから小問別の構造化答案を保存。永続ジョブの再照会/重複/入力版を扱い、不完全応答・資料不足・拒否を完成答案と分離。Astraを品質基準、Terraを同一資料の比較に使い、採用モデル/設定/費用/時間を記録する。
**検証:** fake SDKで境界回帰後、実APIの一大問をスマホモバイル回線で往復。応答喪失→同一ジョブ照会、改訂画像、全入力前の解析禁止を確認。次に未使用100問以上と20/40ページ負荷へ進む。
**依存:** FS-60/63、FS-20/33/35/37の資料・ジョブ契約。 **規模:** M（永続台帳の実装は既存FS-37として別増分）。
**対象:** 既存Python solver、対応テスト、スマホCloudMultimodalSolver、ジョブ連携、API結果契約（最大5ファイル）。試験中の課金上限・credential作成を別途具体化してから実行する。

### FS-65: 数式・表・必要な作図を答案表示へつなぐ

- [ ] 実装・検証完了

**目的:** 文字列が保存できるだけで「記述内容全て」を満たしたとしない。
**完了条件:** 既存全文文字列と互換な答案ブロックを必要箇所だけ追加。指数/分数/場合分け/表/図を読みやすい幅で全文表示し、答案の順序を保持。未対応要素を落としたREADYを禁止し、ラベルと答案を分離する。
**検証:** 1000字/数式の全文復元＋答案画像の確認。`AnswerViewTest` を実装後に通し、実機で読める最小文字/数式/作図サイズを検証。解説混入と必須式欠落の対照を使う。
**依存:** FS-59/60、FS-12/36の全文契約。 **規模:** M。
**対象:** study/AnswerItem.java、study/AnswerLayout.java、GD/AnswerView.java、既存AnswerViewTest.java、答案fixture（最大5ファイル、必要な依存追加は別増分）。

### Checkpoint B: 実装再開後の統合

- [ ] FS-63/64/65から既存FS-38/42/47へ接続し、全自動テスト・APK・lintを確認する。
- [ ] 実AIの答案精度、全文表示、終了消灯/再装着、スマホ操作0回、両150分の電池試験を別々に判定する。
- [ ] 検証済み増分だけをcommitし、既存の進捗記録に次のFSと未検証条件を残す。

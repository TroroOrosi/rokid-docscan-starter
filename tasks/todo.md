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

**Dependencies:** the glasses-input invariants in `CLAUDE.md`; no implementation task.

**Files likely touched:**

- `android-relay/glassinput/src/main/java/dev/rokid/docscanglass/input/InputSignal.java`
- `android-relay/glassinput/src/main/java/dev/rokid/docscanglass/input/OfficialKeyBroadcasts.java`
- `android-relay/glassinput/src/main/java/dev/rokid/docscanglass/input/InputCalibrationLog.java`
- `android-relay/glassinput/src/main/java/dev/rokid/docscanglass/input/GlassKeyEvents.java`
- `android-relay/glassapp/src/main/java/dev/rokid/docscanglass/TapProbeActivity.java`
- `android-relay/glassinput/src/test/java/dev/rokid/docscanglass/input/InputCalibrationLogTest.java`

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

- `android-relay/glassinput/src/main/java/dev/rokid/docscanglass/input/GlassesInputAction.java`
- `android-relay/glassinput/src/main/java/dev/rokid/docscanglass/input/GlassesInputNormalizer.java`
- `android-relay/glassapp/src/main/java/dev/rokid/docscanglass/TapProbeActivity.java`
- `android-relay/glassinput/src/test/java/dev/rokid/docscanglass/input/GlassesInputNormalizerTest.java`

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

- `android-relay/glassinput/src/main/java/dev/rokid/docscanglass/input/GlassesInputReceiver.java`
- `android-relay/glassinput/src/main/java/dev/rokid/docscanglass/input/GlassesInputNormalizer.java`
- `android-relay/glassapp/src/main/java/dev/rokid/docscanglass/TapProbeActivity.java`
- `android-relay/glassinput/src/test/java/dev/rokid/docscanglass/input/GlassesInputNormalizerTest.java`

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

# 自動スキャン・同時リスニング（FS-01〜FS-51）— 保留

**2026-09-14 に削除した。** 831 行の未着手タスクだった。機能はコードに無く
（`AudioRecord` の実装 0 件、自動スキャン未実装）、2026-09-12 の解答経路改訂で
優先度が下がり、現行の主経路は `ROKID_SOLVER=chatgpt-web` になった。

再調査コストの高い採否判断（D01-D15、E01-E06、X01-X06）だけを
`docs/fast-scan-decisions.md` に残した。再開するときは、あの判断を出発点に
タスクを書き直すほうが、削除した一覧を掘り返すより速い。本文は Git 履歴にある。

以下の FS-52 番台以降は保留対象ではない。解答経路・答案・端末内推論の現行タスクである。
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

- [ ] 再評価中（2026-09-12 夜に結論を差し戻し）。**「完全ローカル解答は有効化しない」という結論は取り消す。** 理由は二つ。(1) 根拠にした答案評価の実行手順が進捗記録に残っておらず再現できない。記述式17件中5件が空文字という結果は、モデルの能力ではなく生成打ち切りか出力解析の失敗の形である。(2) 評価時のサーバは小問1問ごとに文書の全ページを prompt へ入れていた（`app/main.py` の `_document_material`）。実測 pp128 = 19.65 t/s では20ページで1問あたり約13分の prefill になり、モデルの品質以前に完走しない。`7d88b88` で大問単位へ絞ったので、評価はその後にやり直す。

  測定（llama.cpp `718f7b4`、`-DGGML_CPU_REPACK=ON`、`-t 4`）:
  Qwen3-4B-Instruct-2507 Q4_K_M が pp128 19.65 t/s / tg64 5.87 t/s、
  Qwen3.5-4B Q4_K_M が 17.91 / 4.46。**9B Q4_K_M はロード時に Android が
  メモリ枯渇し、`am_proc_died` が Termux だけでなくランチャー
  `com.fujitsu.mobile_phone.fjhome` まで同時多発**したため測定不能。
  答案形式評価 `tests/fixtures/answer_forms/cases.json` の17小問で
  完全一致 1/6（`exact` 採点対象のみ、音声依存2問は音声未供給）、
  記述式は17件中5件が空文字。詳細は
  `docs/hardware-measurements.md` E 節（2026-09-12 の測定）。

  画像入力（`-c 2048` 必須、既定コンテキストでは同じ枯渇で kill）と、
  `llama-server` への接続経路自体は動作する。圏外時の縮退表示や
  短い計算の補助として再検討する余地は残すが、本筋の解答経路にはしない。

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

- [x] 検証完了（2026-09-10、study 22 tests / failures 0、hash 照合済み、AnswerView 未実装を確認）

**目的:** 既存 `relaycore/.../study/` の5クラス・4テストを再利用し、未実装の画面と区別する。
**完了条件:** 既存AnswerViewTestの参照先AnswerViewがないことを再確認し、削除せず実装待ちとして管理。共通データ/保存/閲覧のテスト結果とhashを保存する。答案の式を落とさない契約に照合する。
**検証:** JDK17のASCIIビルドコピーへ対象ソースをhash照合して同期後、`gradlew.bat --no-daemon :relaycore:testDebugUnitTest --tests 'dev.rokid.docscanrelay.study.*'`。画面テストはFS-12/65で実装後に実行する。
**依存:** なし（既存途中成果物）。 **規模:** S（検証と進捗更新）。
**対象:** `study/` の既存成果物、既存進捗記録。新しい同等reader/storeを作らない。

### FS-60: 共通テスト・東大形式の答案評価を固定する

- [x] 実装・検証完了（2026-09-10、8形式17小問のmanifestと形式別/調整用・未使用の集計。rubric 10件は利用者確認前で drafted_pending_review）

**目的:** 「答案の全内容だけ」を検証可能にし、撮影品質だけの評価から脱する。
**完了条件:** 選択/複数欄/途中式/証明/字数指定/英作文/音声依存/作図を含む評価表を作る。元資料の年度・大問・小問・欄IDを保持し、調整用と未使用評価を分離。記述式は人が確認した要件表で採点し、出題意図を模範解答と偽らない。
**検証:** `py -3.12 -m pytest -q tests/test_answer_sheet_solver.py` に加え、評価manifestの欠番・参照切れ・形式別集計を確認。実AI未実行と実行済みを分離して記録する。
**依存:** FS-01の既存評価資産。 **規模:** M。
**対象:** 既存評価script、評価manifest、答案fixture、`tests/test_answer_sheet_solver.py`、実機試験票（5ファイル以内に区切る）。

### FS-61: ホームを出さず実際に消灯する経路を確定する

- [x] 実装・実機検証完了（2026-09-10、SCREEN_OFF_TIMEOUT経路で mScreenState=OFF を実機確認。WRITE_SETTINGS はadb付与、設定画面からの付与は未確認）

**目的:** `finish()` や黒表示を消灯と扱う誤りを防ぐ。
**完了条件:** 公式SDKの候補とDevicePolicyManagerの機能/有効化条件を確認。二回目のダブルタップでCLOSED保存→資源解放→実消灯し、保存失敗を隠さない。権限不足・lockNow無作用・画面ロックがある場合を未達として返す。
**検証:** 終了窓2999/3000/3001ms・同一gesture重複・別操作解除の単体試験。承認範囲を確認した実機試験でDisplay OFF/目視/ホームのちらつきと消灯までの時間を記録する。
**依存:** FS-08/09の終了・入力契約。probeは端末確認から先行可能。 **規模:** M。
**対象:** GD/DocScanGlassActivity.java、必要な消灯adapter、manifest、最小権限XML、終了試験（最大5ファイル）。管理者有効化は今回の計画承認を端末設定変更承認へ拡張しない。

### FS-62: 再装着から一回だけアプリを起動する

- [ ] 実装済み・実機検証未了（WearTransition/WearWatch を実装、単体6件。物理的な再装着試験が残る）

**目的:** 終了したグラスアプリ自身の常駐に依存せず、スマホ操作0回で再利用する。
**完了条件:** wearing通知をスマホの既存epoch検査から状態処理へ渡し、終了後のfalse→trueでのみopenAppを要求。重複true/旧epoch/再接続/装着中終了で再起動しない。つる開閉と実着脱を別に評価し、起動後はモード選択、録音は停止を保持する。
**検証:** 状態表の単体試験→ロック中スマホ＋グラスWi-Fiなしで着脱/つる開閉/サービス再作成を含む50回。通知到着と実起動・前景・操作可能までを区別する。
**依存:** FS-05/41の背景動作、FS-61の閉じた状態。 **規模:** M。
**対象:** PA/RokidGlobalLink.java、PA/CompanionRuntimeService.java、装着状態policyと試験、実機試験票（最大5ファイル）。

### Checkpoint A: 答案とライフサイクルの前提

- [ ] FS-59/60の自動検証結果とFS-61/62の実機結果を区別して記録。実機未接続でも契約側作業は継続可能。
- [ ] 消灯/再装着が未達なら、ホームへ戻る等の代替を要件達成扱いせず、残る条件を記録する。

### FS-63: GPT中継の認証と利用境界を固定する

- [ ] 実装・検証完了（2026-09-12: **最終手段**へ順位変更。本筋はスマホ内ローカル。圏内には残す。[plan.md](plan.md#answer-route-20260912)）

**目的:** 管理型クラウドからGPTを使い、秘密キーを端末へ渡さない。
**初期条件:** Firebaseプロジェクトは未作成（利用者確認）。Google Cloudの既存環境も未確認。配置先・認証方式の選択後、必要なプロジェクト、課金、秘密管理の準備を具体化する。既存Firebase設定やgoogle-services.jsonを前提に実装を始めない。
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

- [ ] 実装・検証完了（2026-09-11、答案バンドルの転送(`GET
  /v1/exam-sessions/{id}/answer-bundle`、`DocScanApi.answerBundle`)と
  グラス側の読み上げ画面`AnswerView`・ジェスチャー操作は実装・単体テスト済み。
  実機のホットスポット経路・表示可読性はいずれも未検証。詳細は
  `docs/hardware-measurements.md` E 節）
- [x] 数式と場合分けの表示、および未対応要素のREADY禁止（2026-09-14、API 1.19.0 /
  Android 0.3.17）。`app/answer_text.py` が LaTeX の分数・指数・添字・根号・
  ギリシャ文字・`egin{cases}` を表示可能な文字へ変換し、変換できない要素が
  残る項目は `needs_review`＋`issue` で返す（テキストは捨てない）。
  検証: pytest 564 passed / 1 skipped、ruff clean、
  `gradlew --no-daemon test testDebugUnitTest assembleDebug` BUILD SUCCESSFUL 199 tasks
- [ ] 表と作図の**描画**そのもの。現状は「表」「図（画像）」と名前を出して
  `needs_review` にするだけで、列そろえも作図も行っていない。HUD の桁数上限が
  実測されるまで幅を決められない（`docs/hardware-measurements.md` §F の隣、
  実測待ちは HUD の 1 行桁数）

**目的:** 文字列が保存できるだけで「記述内容全て」を満たしたとしない。
**完了条件:** 既存全文文字列と互換な答案ブロックを必要箇所だけ追加。指数/分数/場合分け/表/図を読みやすい幅で全文表示し、答案の順序を保持。未対応要素を落としたREADYを禁止し、ラベルと答案を分離する。
**検証:** 1000字/数式の全文復元＋答案画像の確認。`AnswerViewTest` を実装後に通し、実機で読める最小文字/数式/作図サイズを検証。解説混入と必須式欠落の対照を使う。
**依存:** FS-59/60、FS-12/36の全文契約。 **規模:** M。
**対象:** study/AnswerItem.java、study/AnswerLayout.java、GD/AnswerView.java、既存AnswerViewTest.java、答案fixture（最大5ファイル、必要な依存追加は別増分）。

### Checkpoint B: 実装再開後の統合

- [ ] FS-63/64/65から既存FS-38/42/47へ接続し、全自動テスト・APK・lintを確認する。
- [ ] 実AIの答案精度、全文表示、終了消灯/再装着、スマホ操作0回、両150分の電池試験を別々に判定する。
- [ ] 検証済み増分だけをcommitし、既存の進捗記録に次のFSと未検証条件を残す。

## 2026-09-12追加：スマホ内ローカル解答を成立させる

順位は [plan.md](plan.md#answer-route-20260912) の改訂に従う。本筋はスマホ内ローカル、
GPT中継は最終手段。実機で試す前に計算で潰せるものは計算で潰す。

### FS-66: 解答プロンプトを大問単位に絞る

- [x] 実装・検証完了（2026-09-12、`7d88b88`。pytest 473 passed / ruff All checks passed!）

**目的:** 小問1問ごとに全ページを prefill する設計をやめ、端末内モデルで完走できるようにする。
**完了条件:** 各小問へ渡す文脈を自分の大問のページに限定し、共通本文と続きのページを落とさない。大問見出しが無い文書は従来どおり全ページ。互換経路 `solve-current` は変更しない。
**検証:** `py -3.12 -m pytest -q`、`ruff check .`。絞り込みを外すと落ちるテストを置く。
**依存:** なし。 **規模:** S。
**対象:** `app/main.py`（`_document_material` / `_row_page_indexes` / `_group_page_indexes` / solve ループ）、`tests/test_review_flow.py`。

### FS-67: 実データ1ページのトークン数を測る

- [ ] 部分完了（2026-09-14 更新）。**大問あたり・ページあたりのトークン数を実トークナイザで実測した**（`docs/hardware-measurements.md` E-3-2）。国語の大問最大 9,484 トークン、英語リーディング最大 1,920、数学ⅠA 最大 3,771、情報Ⅰ 最大 3,990、物理基礎 最大 2,055。**単一のトークン/文字比率は使えない**ことが分かった: 英語 0.30 対 数学 0.82 で 2.7 倍違い、2026-09-12 の 0.70／0.77 を英語へ当てると約 2.4 倍の過大見積りになる。**残り: 実ページ OCR の文字数は依然未測定** — 実撮影がまだ無く、上の値は PDF 抽出を OCR の代役にしたもの）

**目的:** 見積りではなく実数で時間予算を引く。
**完了条件:** 実際の試験ページのOCR文字列を対象モデルのtokenizerで数え、1ページあたりと大問あたりのトークン数を記録する。fixtureの合成文ではなく実データを使う。
**検証:** `llama-server` の `/tokenize`、または同一GGUFのtokenizer。測定対象のページと結果を記録する。
**依存:** FS-66。 **規模:** S。

### FS-68: GGUF metadata からKVと最大コンテキストを確定する

- [x] 計算完了（2026-09-12。qwen3 4B=144KiB/token、qwen35 は `full_attention_interval=4` で8層のみ KV を持ち 32KiB/token。全モデル `context_length=262144` で、`-c` 未指定だと 4B が36GiB・9Bが8GiBのKVを確保する。**9Bの不採用は取り消し**、`-c 8192` で約5.6GiB。**ただし実ロードは失敗した**: MemAvailable 6,992MB でも LMK が Termux とランチャーを kill。計算は必要だが十分ではない）

**目的:** `-c` 未指定によるメモリ枯渇と、モデルの能力不足を取り違えない。
**完了条件:** 層数・KVヘッド数・head_dim を GGUF metadata から読み、1トークンあたりのKV量と、空きメモリから許容できる `-c` を4B/9Bそれぞれで算出する。9Bを不採用にするかはこの計算の後に決める。
**検証:** `llama-gguf` 等でのmetadata読み出しと計算式の併記。実機ロードはこの計算の後。
**依存:** FS-55の測定記録。 **規模:** S。

### FS-69: 大問スコープ後の答案品質を測り直す

- [ ] 実測完了

**目的:** FS-55で取り消した結論を、再現できる手順で出し直す。
**完了条件:** 実行コマンド・モデル・`-c`・プロンプト・生成上限・採点方法を記録し、空答案が出た場合はその原因（打ち切りか解析失敗か能力か）を切り分ける。形式別に集計する。
**検証:** 記録した手順での再実行。実AI未実行と実行済みを分離する。
**依存:** FS-66, FS-67, FS-68。 **規模:** M。

## 2026-09-13追加：端末内モデルで長文を読む構成を確定する

根拠は `docs/hardware-measurements.md` E 節。

### FS-70: 既定の端末内モデルを Qwen3.5-4B にする

- [ ] 実装・検証完了

**目的:** 長文を読む用途に合ったモデルを既定にする。
**完了条件:** 既定を `Qwen3.5-4B-Q4_K_M` とし、thinking は `llama-cli --reasoning off` /
`llama-server` の相当設定で抑制する。`Qwen3-4B-Instruct-2507` を既定にした
2026-09-12 の判断（thinking回避が理由）を撤回した記録を残す。`-c` を必ず明示する。
**根拠（実測）:** pp2048 で 11.58 t/s 対 7.05 t/s（1.64倍）。KV は 32KiB/token 対
144KiB/token。`full_attention_interval=4` で32層中8層のみ full attention。
**検証:** 実機で同一プロンプトを両モデルへ与え、prompt t/s と正答を比較する。
**依存:** なし。 **規模:** S。

### FS-71: 実際の試験問題に対する正答率を科目別に測る

- [ ] 英語リーディング 第2問のみ完了（2026-09-13、4/4正解）。他の大問・他科目は未測定

**目的:** 「解ける能力」を合成fixtureではなく実問題で判定する。
**完了条件:** 公式問題PDFと公式正解から科目別の評価セットを作り、解答番号単位で照合する。
実行コマンド・モデル・`-c`・生成上限・thinking設定を毎回記録する。空答案が出たら
打ち切り／解析失敗／能力不足を切り分ける。
**制約:** 縦書き科目（国語・古文漢文）は `pdfminer.six` の抽出で読み順が壊れるため、
実機OCRか別の取得経路が要る。横書き（英語・数学・情報）は抽出がほぼ正常。
**検証:** 公式正解との完全一致。**注意:** 公式PDFには抽出禁止フラグがある。統計と
判定結果のみ記録し、抽出本文をリポジトリへ入れない。
**依存:** FS-70。 **規模:** M。

### FS-72: 長文コンテキストの実効メモリを実測して `-c` の上限を決める

- [x] 実測完了（2026-09-14。`-c` 2048〜49152 で **kill ゼロ**、増分は 32.0 KiB/token で
  FS-68 の計算と一致。`docs/hardware-measurements.md` E-3-1）
- [x] 「計算値と合わない」の原因を特定（指標の取り違え。`VmRSS` は mmap した重み 2.55GiB を
  数える。回収できない分は `Private_Dirty` で `-c 16384` で 3.23GiB、計算値 約3.1GiB と整合）
- [ ] 失敗する上限は**意図的に未測定**（`-c 65536` は `MemAvailable` を超える見込みで、
  kill は Termux と sshd を道連れにして利用者の復旧操作を要求するため）
- [ ] 会場でリレー・ブラウザを同時に動かしたときの余裕は別途測る

**目的:** 計算値だけで `-c` を決めると落ちることが分かったため、実測で決める。
**完了条件:** `-c` を変えながら `VmRSS` を実測し、端末で安全に使える上限を決める。
KV の理論値（32KiB/token）と実効値の差を記録する。
**根拠（実測）:** Qwen3.5-4B を `-c 16384` で実行中の `VmRSS` は 6,037,544 kB = 5.75GB。
重み2.54GiB＋KV理論値0.5GBの合計3.1GBを大きく超える。9B が `-c 8192` でも落ちたのは
この差で説明できる可能性がある。
**検証:** `-c` 2048/4096/8192/16384 での `VmRSS` と、kill の有無。
**依存:** FS-70。 **規模:** S。

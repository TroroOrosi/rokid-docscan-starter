# タスク：起動から記入用答案まで

Status: Current implementation task list。2026-09-15の認識合わせ後、追加実装の依頼を受けRP項目を実装中。
Runs on: 開発・自動試験はWindows。実機受け入れはglassdocとF-51F AP／FastAPI／ASR／Chrome。

仕様は[plan](plan.md)、採否と旧IDの対応は[requirements-audit](../docs/requirements-audit.md)。
下の旧チェックボックスはその時点の記録を保持したもので、現在の再開順ではない。
実機の英語リスニング試験は利用者の追加指示で後回し。用紙から答案までを優先する。

## 共通の進め方

- 既存コードと試験を再利用。以下の対象は製品コードの目安で、試験を含め約5ファイルを超える場合は
  当該task内を独立して検証できる小工程へ分ける。先に汎用基盤を作らない。
- 各taskは記載した境界のunit/API回帰を通してから完了チェックを入れる。
  関連Java試験はwrapperの該当module、Python試験は `py -3.12 -m pytest -q <対象test>` で実行する。
- 実機書込み、撮影／録音、ChatGPTへの資料送信は対象・入力・操作を具体化し、既存承認の範囲と照合する。
  新依存・schema・認証・撮影条件変更の承認境界を守る。LED外部監査は利用者指定で省略。
- 実機試験は前提を満たす場合だけ実行する。PCで測った部品の結果を会場の合格にしない。
- 共通最終gate: `py -3.12 -m pytest -q`、`py -3.12 -m ruff check .`、
  指定JDK17／SDK36で `./android-relay/gradlew --no-daemon test testDebugUnitTest assembleDebug`、
  `git diff --check`、aapt2／apksigner／SHA-256による対象APK照合。

## A. 未成立の能力と評価基準を先に確かめる

### RP-01 実資料の評価枠と主経路の小さい能力試験（M）

Runs on: 評価準備はWindows。実モデル試験はF-51F Chrome、同時取得はグラス＋F-51F。

- [ ] 既存8 case／17問のfixtureを再利用し、未採点rubricを確定。実写真・実音声・人手正解、調整用と未使用評価用を分離する。
- [ ] 小さい大問で「OCR＋画像＋原音／transcript」が届き、原音が必要な設問に利用できるか測る。
- [ ] グラスcamera/micを5分同時取得し、元サンプル連続性と写真待ち・ASR負荷を測る。
- 検証: 入力・モデル・添付数／容量・誤読・最終正答を記録。合成fixtureの実行を実答案評価としない。
- 依存: なし。接続準備不足はRP-20の最小準備を先行。能力不成立時は後続の該当設計を見直す。
- 対象: 既存eval CLI、評価fixture、測定記録。新しい評価frameworkは作らない。

### RP-18 即消灯・再装着の能力を先に測る（Sの探針→成立時のみMの接続）

Runs on: 指定グラス。スマホの協力が必要な既存経路だけF-51Fで試験。

- [ ] 終了→物理消灯、解析中再装着、CLOSED後再装着、foldによるforce-stopを別々に検査する。
- [ ] 目標1秒消灯／3秒操作可能を実測。既存公開APIで成立する経路が分かってからActivityへ接続する。
- 検証: 外部からの画面観察と時刻、Activity起動回数、CLOSED・録音非再開。黒画面と物理消灯は区別する。
- 依存: 探針はなし。製品接続はRP-04/17。15秒timeout・生存Activity内通知のみなら未達のまま報告する。
- 対象: DisplaySleep、WearWatch、Activity、対応試験。frozen phone relayを拡張して先に基盤を作らない。

## B. 取得を待たせない操作の一周

### RP-02 実OCRとplaceholderの契約を分ける（M）

Runs on: WindowsでAPI試験、適用後F-51F。

- [x] REAL_MODEで実クライアントOCRを受け付け、placeholder solver/analyzerは引き続き拒否する。
- [x] 空OCRの写真を捨てず、画像対応solverで読める入力として扱う。画像非対応なら資料不足を明示する。API試験で確認、実モデル評価はRP-01。
- 検証: 実OCR＋chatgpt-web、空OCR＋画像、placeholder／未準備の正負API試験。REAL_MODE=0への逃げを入れない。
- 依存: なし。対象: config、analyzer境界、main、既存real-mode／photo試験。schema変更が必要なら適用前に具体化。

### RP-03 最小の保存状態と初回設定を整える（M）

Runs on: Windows、glassdoc。

- [x] ローカル記録と後から得るHTTP文書IDの対応、選択モード、撮影／音声phase、CLOSEDを保存する。音声chunkの復旧はRP-07。
- [x] URLと認証をKeystore暗号化で保存し、起動ごとのkey入力をなくす。既存HTTPのlong IDは維持。実鍵設定・実機再起動は未検証。
- 検証: 書込み途中kill、認証ありでプロセス再起動、別serverへの未送信資料混入なし。秘密をログへ出さない。
- 依存: なし。対象: 既存Controller保存、Activity設定、AnswerStore周辺の必要範囲と試験。認証の実設定はRP-20。

### RP-04 二択から取得へ直行する（M）

Runs on: Windows、glassdoc。

- [x] 起動で通常／リスニングを表示、前回選択を強調しタップで開始する。中断資料・直近答案は任意項目。実機の起動時間は未測定。
- [ ] カメラ／マイクは選択前に開始しない。通信確認を二択やローカル取得の待ち条件にしない。
  通常撮影とchooserはHTTPを待たない。リスニング開始のHTTP待ちはRP-07/08で解消する。
- 検証: 新規・再起動・未接続・中断・CLOSEDの起動試験。準備済み選択→最初の取得の3秒目標を実機で測る。
- 依存: RP-03。対象: Activity、既存HUD、Controller起動境界と対応試験。

### RP-05 別の速い操作を落とさず一操作を一度だけ通す（M）

Runs on: Windowsの純Java試験、同じAPK／firmwareのグラス。

- [x] broadcast／KeyEventの同一操作の相関と、異なる操作の連続を分ける。970ms内の別BACKを保持。純Java試験で確認、実機照合は未実施。
- [x] 取得時の単調時計を維持し、focus喪失時は相関と二段階終了の一時状態を消す。取消期限への接続はRP-09。
- 検証: S14/15、順序逆転、重複、遅延、未知event。既存の相関実測を保持して実機の物理操作数と照合。
- 依存: なし。対象: normalizer／InputSignalの必要境界、Activity、既存入力試験。

### RP-06 写真を保存してから独立送信する（M）

Runs on: Windows、glassdoc → F-51F API。

- [x] 可視確認が終わったページを端末に原子的に保存。保存後はHTTPを待たず次ページと操作を受ける。自動試験済み、物理試験未了。
- [x] 未ACKページを保持し、同じ文書／page ID／内容で再送する。確定前は送らない。ACK不明の再生成・再送を自動試験、実AP断は未測定。
- 検証: 遅いHTTP中の次操作、ACK前後kill、重複再送、保存失敗時の旧写真保全。S20/23、X06。
- 依存: RP-03。対象: Controller、既存CaptureReview保存／API、回帰試験。汎用queue製品を追加しない。

### RP-07 原音と再送位置を耐中断保存する（M、保存→再送の順）

Runs on: Windows、グラス録音 → F-51F音声API／ASR。

- [ ] 現行WAV／30秒chunk／重複1秒を再利用し、書込み中断の末尾回収と未ACK再送を可能にする。
- [ ] sync間隔・原音保全・空き容量を測る。容量不足は写真から止める。ASR失敗でも原音を残す。
- 検証: 逆順／同一再送／違うhash／欠番／短い末尾、保存・ACK前後kill、original PCM一致、S22/23/30。
- 依存: RP-03。対象: ListeningRecorder、listening API、既存録音／API試験。保存ACKとASR完了分離は遅延測定で判断。

### RP-08 実録音開始と二段階終了を画面状態から分ける（M）

Runs on: Windows、glassdoc。入力停止監視は実機確認を併用。

- [ ] 有効サンプル後だけREC。OS無音化・入力停止／経路変更は検出可能な公開通知と読取り結果で扱う。
- [ ] 第1BACKは撮影終了、第2の別BACKは最後の写真確認中でも音声終了。取り直しで音声を再開しない。
- 検証: 通常は録音なし、S09～19、録音開始失敗、長い自然無音と停止の区別。5分同時取得結果を保持。
- 依存: RP-04/05/07。対象: Activity、Controllerの終了境界、ListeningRecorder／既存service、対応試験を小工程に分割。

### RP-09 3秒境界と最後の1枚を守る（M）

Runs on: Windows、glassdoc。

- [ ] 可視ACK・写真世代・取得時刻を照合し、2999msの遅延操作を元写真へ結ぶ。期限後入力は次写真へ流さない。
- [ ] 描画待ち・非可視・JPEG/OCR中・取り直し中・0枚の終了でも確認機会と復旧操作を残す。
- 検証: S02～05、S09～11、保存後の遅延取消。実機で実画像3秒と入力時点を確認する。
- 依存: RP-05/06/08。対象: Controller、GlassesCaptureSurface、既存review保存と試験。

### RP-20 APとスマホ起動の準備をまとめる（M、準備→認証→復旧）

Runs on: F-51FのTermux／Chrome／AP、接続するglassdoc。会場にPCなし。

- [ ] REAL_MODE、ASR実推論、ログイン・CDP・利用可能状態を初回確認。placeholderや「CDP接続可」だけで準備完了にしない。
- [ ] API認証・接続先を設定しAPへ公開。携帯回線と同居し、無断で公衆internetへ公開しない。
- [ ] スマホ再起動後の立上げをPCなしで行える手順にし、セッション中はChrome前景／点灯・スマホ操作0回。
- 検証: AP断／携帯回線断を分ける。再接続、端末再起動、鍵保持、サーバ／ASR／CDP状態、実際の到達性を記録。
- 依存: 最小接続確認は先行可能。最終受入はRP-02/03/04。対象: 既存起動script・設定読取・手順・最小試験。
- 承認境界: 新しい認証鍵、AP／security設定、実機への適用を具体化して確認する。

### Checkpoint B

Runs on: Windows gate後、グラス→F-51F AP→Chrome→answer-bundle。

- [ ] 通常の数ページと短いリスニングを、一回の選択から答案まで通す。
- [ ] HTTP待ちでも取得／終了が反応し、重複BACKと独立終了が正しい。保存後の切断から復旧する。
- [ ] 基礎の不成立を新機能で埋めず、この一周を直してから拡張する。

## C. 実資料の精度と閲覧

### RP-10 同じ紙・似た別紙・図だけの紙を扱う（M）

Runs on: Windows、グラスで同じ照明／距離の実写真比較。

- [ ] 既存camera／OCR／ShotScoreを使い、空OCRの図ページを保全。同じ紙の自動連写を止め、別紙を類似度だけで捨てない。
- [ ] B5の単頁／見開きを同じ紙面で比較し、細字・数式・綴じ目・左右の設問順・最終正答と時間から既定を決める。
  guideの画角、四辺・余白・短い欠け／反射案内を校正する。別サイズや意図した同一紙は手動追加可能。
- 検証: S06～08・X02/04、取得時間、撮影枚数、欠け、微小文字。輪郭消失・静止・ページ交換の実写真で判定。
- 依存: RP-01/09。対象: Controller、pagequality、FramingGuide、試験。新preview／MLは現行方式の限界を数値化してから。
- 測定済み寸法・burst／retryを変える場合は具体案を事前確認する。

### RP-11 過去ページを確認・訂正する（M）

Runs on: Windows、glassdoc。

- [ ] 撮影を一時停止して取り込み済みページ一覧から訂正できる。取り直し中も旧版を残す。
- [ ] 解析前の訂正を通常経路とする。解析後はRP-12の新入力文書へ進むと示し、音声は再録音しない。
- 検証: 新規写真／過去ページの区別、保存失敗・送信中・期限遅延取消。X01、新版採用後のページ順維持。
- 依存: RP-06/09。対象: Activity、Controller、既存保存、対応試験。ジェスチャ割当はplanの確認後に接続する。

### RP-12 共通資料・設問と入力版を整える（Mを二工程）

Runs on: WindowsのAPI／fixture試験、F-51F。

- [ ] 12a: 既存分割で選択肢を小問と誤認せず、同じ問番号・複数ページ・共通資料のIDと順序を保持する。
- [ ] 12b: 解析後の訂正は新しい入力文書で全再解析。旧文書／答案を保全し、現在版へ混入させない。
- 検証: 同じ小問番号・共通図表・撮影順逆転、画像変更でdigest変化、旧応答・重複要求、S24・X01。
- 依存: RP-02/11。対象: main、layout、source bundle／digest境界、対応試験。既存DBとHTTP IDを再利用する。

### RP-13 音声の内容と紙面を結び、誤認識を測る（M）

Runs on: F-51F ASR／Chrome、入力はグラスの実録音・実写真。

- [ ] 数字・否定・末尾の訂正・複数話者・共通会話・読み上げ順逆転を評価。overlap由来のtranscript重複を扱う。
- [ ] ページ／小問と音声根拠を内容で対応し、原音が必要なのに利用できなければneeds_inputにする。
- 検証: 正解と根拠区間、否定／数値の誤認識、ASR backlogと終了後待ち。S19・X03。
- 依存: RP-01/07/08/12。対象: local_asr／listening、solverの資料指定、既存fixture。専用話者分離基盤は作らない。

### RP-14 解答欄に必要な全文を返す（M）

Runs on: Windowsのsolver／API試験、実モデル採点はF-51F Chrome。

- [ ] 選択・数値・記述・証明・理由・指定言語・作図ごとに出力を検査。記述式数学の必要な途中式を抑止しない。
- [ ] 未対応形式・根拠欠落・解答失敗を完成にしない。教材的な解説を記入本文へ混ぜない。
- 検証: 既存answer_formsと図fixture、1000文字の証明、単位／場合分け／必要図の欠落、人手rubric。
- 依存: RP-01/12。対象: 共通solver prompt、answer text／diagram検査、対応試験。

### RP-15 保存済み小問を順次届ける（Mをserver→clientの順）

Runs on: Windows、F-51F FastAPI → glassdoc。

- [ ] SQLite claimと小問保存を再利用して一教科1チャットを逐次処理。例外の理由と終了状態を保持する。
- [ ] Activityからbundleを再取得し既存AnswerReader.acceptへ接続。位置保持・終了／非可視時の取得制御を行う。
- 検証: 部分成功＋失敗、pendingの取り残し、到着順不同、再起動・再送、旧入力版、CLOSED後の結果。S24/25/27。
- 依存: RP-12/14。対象: mainの最終化、Activity／API、既存bundle／reader試験。browser pool・新job基盤なし。

### RP-16 メニュー・前回答案・図表の閲覧を接続する（M）

Runs on: Windowsの描画／入力試験、グラスで可読性確認。

- [ ] 既存大問／小問メニューのBACKは一段戻る。本文だけ2回BACKで終了を要求する。
- [ ] 直近答案を任意に開く。本文・必要な図・表の項目値を欠落なくページ送りし、追加結果でも位置を保つ。
- 検証: 長文、図ラベル、表、オフラインの前回答案、CLOSEDの明示的再開、実フォント・視認範囲。
- 依存: RP-03/05/15。対象: Activity、AnswerGestures、AnswerView／AnswerReaderの必要範囲と試験。

### RP-17 CLOSEDと待機・復帰を全phaseへ通す（M）

Runs on: Windows、glassdoc。

- [ ] CLOSED保存後に終了し、保存失敗は明示する。途中phaseも勝手に再開せず、中断資料として選べるようにする。
- [ ] 解析待ちの消灯要求、結果表示可能時の復帰、終了後の遅延callback抑止を接続する。
- 検証: S28/29、保存前後kill、部分答案到着、エラー状態、wear、fold。物理消灯と自動起動はRP-18で別判定。
- 依存: RP-03/16。対象: Activity、既存保存、DisplaySleep／WearWatch境界と試験。

### RP-19 入力方式の比較で既定を決める（M）

Runs on: 会場経路の同一PNG／OCR／実音声、同じF-51F Chrome・モデル。PCの準備は部品作業。

- [ ] 全文OCR＋関連画像を基準にPDF／結合画像と比較。OCR・transcript・原音の情報量の差を統制または明記する。
- [ ] 細字・数式・図表の誤読、小問の最終正答、添付容量／数、応答時間・拒否を記録し、良い方式を一つ既定にする。
- 検証: 調整に使っていない資料を含む反復。同じモデル／入力を固定し、rate-limitで無制限に試行しない。
- 依存: RP-01/12/13/14。対象: 既存source_bundle、eval CLI／fixture、測定記録。方式を日常UIへ追加しない。

## D. 最終gateと実使用

### RP-21 公開契約・資料・APKの整合（Sの契約変更→検査）

Runs on: Windows。実機操作前のAPK検査。

- [x] 21a: settingsにglassdocの操作主体を公示する経路別契約を追加し、frozen phone契約は維持。API／view挙動の版と試験を揃えた。物理受け入れはpending。
- [ ] 21b: plan・runbook・README tuple・進捗を実装へ合わせ、共通最終gateとAPK identity／署名／hash照合を行う。
- 検証: settings／sessionの経路別API回帰、全文書gate、全pytest／Ruff／Java test／assemble、APK検査出力。
- 依存: RP-02～17/20の採用範囲。対象: 契約定義とAPI、version／README、対応試験を分割。新しい表面を重複実装しない。

### RP-22 短い完走から反復・150分へ進む（測定）

Runs on: グラス → F-51F AP → 同スマホFastAPI／ASR／Chrome → answer-bundle。会場PCなし。

- [ ] 通常20ページを5回、リスニング30分＋20ページを実施。40ページ側の容量と時間も確認する。
- [ ] 終了→再装着を50回。1秒消灯／3秒操作可能は物理結果で判定し、未達を隠さない。
- [ ] 通常／リスニングの150分運用で電池・温度・空き容量・ASR backlog・待ち時間・誤操作／欠落を記録。
  初期電池目標は終了時10%以上。150分で自動終了させない。
- [ ] 調査表S01～30／X01～06の所有taskの結果を揃え、未解決の入力欠落・旧答案混入・無断再録音がない。
- 検証: 撮影／分析の約10分目標、スマホ操作0回、実答案採点、図表可読性、AP／携帯回線断と復旧。
- 依存: RP-18/19/21。正答の合格基準はRP-01の採点表で事前固定。未達なら該当taskへ戻し保留機能を無条件に増やさない。
- 対象: 測定記録と進捗。既存の実測tupleを保持し、今回のAPKと端末状態を明記する。

### Checkpoint 完了

Runs on: Windowsの検査証跡＋指定実機の受け入れ結果。

- [ ] 採用範囲の条件が通り、未測定と不成立を分けて報告した。
- [ ] 前回の部品実装完了と、会場経路の完了を混同しない記録になっている。
- [ ] 保留機能を追加せず、今回の採用範囲で止める。

## 改訂前のタスク（保存した履歴）

<details>
<summary>旧チェックボックスを表示。RPタスクの代わりに実行しないでください。</summary>

# Tasks: Safe real-device readiness

## 2026-09-15 現行実装: multimodal-scan

Runs on: MS-1～6はWindowsで実装・試験。MS-7はWindowsの統合検査後、指定実機とスマホAP上。
仕様・依存順は `tasks/plan.md` の2026-09-15改訂。旧項目は履歴として保持。

- [x] MS-1 capture-review: 既存自動ループをglassdocに接続。単タップ手動/取消、
  描画後3秒、最終写真と終了の競合をJUnit/Robolectricで検査。
- [x] MS-2 display-power: 既存DisplaySleepの待機/復帰/終了を統合。
  CLOSED後の遅延応答、権限拒否、繰返し消灯の設定復元を検査。
- [x] MS-3 source-bundle: OCR MarkdownとPage対応、個別画像/結合/PDFを実装。
  欠番・空OCR・20添付境界・画素保持・大問範囲・添付確認をpytestで検査。
- [x] MS-4 answer-diagrams server: 形式検証、生成指示、保存、bundle配送をAPI試験。
- [x] MS-5 answer-diagrams glasses: 既存AnswerViewで図を表示、本文・図の移動と
  オフライン再開をJUnit/Robolectricで検査。
- [x] MS-6 listening-stream: 選定ASR、録音/撮影の独立終了、原音保持、区間/設問参照。
  無音・発話境界・再送・末尾・欠落・不確実な対応を自動試験。
- [ ] MS-7 統合: 全pytest/Ruff/Gradle、APK identity/signature/SHA-256、資料の整合。
  - [x] Windows自動検査とAPK検査。pytest `600 passed, 1 skipped`、Ruff `All checks passed!`、
    Gradle `BUILD SUCCESSFUL`。コマンドと条件は進捗記録に保存。
  - [x] APK導入、F-51FでASRの短いサンプル速度・2チャンクAPI原音保全を実測。
    条件と出力は `docs/hardware-measurements.md` §G。LED監査は利用者指定で省略。
  - [ ] グラスのマイク、撮影との同時処理、実機消灯/復帰、AP全経路、長時間運用。
  - [ ] OCR＋画像／結合画像／PDFの精度比較。実写真で別途記録。


**再開位置の正本は `.agents/progress/` です。** このファイルは作業項目の一覧であって、
次に何をするかの決定ではありません。

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

# 自動スキャン・同時リスニング（FS-01〜FS-51）— **決定済み・未実装**

**2026-09-15 に「保留」から格上げ。** これが本番の撮影方式である（利用者の決定）。
方式の定義は [`docs/fast-scan-decisions.md`](../docs/fast-scan-decisions.md) の R2〜R6。
タスク一覧そのものは 2026-09-14 に削除済みで、**書き直しが要る**。

**2026-09-14 に削除した。** 831 行の未着手タスクだった。機能はコードに無く
（`AudioRecord` の実装 0 件、自動スキャン未実装）、2026-09-12 の解答経路改訂で
着手順が下がっていた。解答経路は `ROKID_SOLVER=chatgpt-web` で確定しており、
撮影方式とは独立である。「保留」は着手順の話であって、方式の不採用ではなかった。

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

- [ ] 実装・検証完了（2026-09-14: 決まった経路は chatgpt-web。本項目は API キー経路の
      `ROKID_SOLVER_TIERS` フォールバック段として残すが、着手予定は無い。
      [plan.md](plan.md#answer-route-20260914)）

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

## 2026-09-12追加：スマホ内ローカル解答を成立させる（**撤回済み**）

> **2026-09-14 撤回。** 決まった経路は `ROKID_SOLVER=chatgpt-web`
> （[plan.md](plan.md#answer-route-20260914)）。本節と次節の未着手項目
> （FS-67 / FS-69 / FS-70 / FS-71 / FS-72）は**予定に入らない**。完了済みの
> FS-66 / FS-68 と実測値は証拠として残す（`docs/hardware-measurements.md` E 節）。
> 未チェックの項目を再開待ちと読まないこと。

（撤回前の前提）順位は [plan.md](plan.md#answer-route-20260912) の改訂に従う。本筋はスマホ内ローカル、
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

## 2026-09-13追加：端末内モデルで長文を読む構成を確定する（**撤回済み**）

> **2026-09-14 撤回。** 上節と同じ理由で FS-70 / FS-71 / FS-72 は予定に入らない。
> 実測の再利用案（CDP 喪失時のフォールバック、縦書きの OCR 補正 等）は
> `.agents/progress/venue-route-and-duplicated-surfaces.md` の提案節にあり、
> 採用は利用者の決定を待つ。

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

</details>

# 要件と実装の照合・採否判断

Status: Implementation plan / adoption decisions。2026-09-15、認識合わせのための再整理。追加実装はまだ行わない。
Runs on: 調査はWindows。採用案の運用先はglassdoc → F-51F AP → 同スマホのFastAPI・ASR・Chrome CDP。

## 結論

起動後に通常／リスニングを選び、取得をすぐ始め、完成した小問から読む一本の流れにする。
既存の撮影、OCR、録音、answer-bundle、保存を再利用する。操作と通信の結合、入力の取りこぼし、
資料の対応付けを先に直す。旧タスクを全部復活させることは目的にしない。
現在の部品実装・部品測定と、この計画の受け入れは別である。

- 現行仕様・採用理由の正本: [plan](../tasks/plan.md)。実施順・合格条件: [todo](../tasks/todo.md)。
- 実装済みの操作・制限: [runbook](multimodal-scan.md)。既存の実測: [hardware-measurements](hardware-measurements.md)。
- 調査基準: commit `97ef5b8e02d06436406543ad2d6de3672b43088b`。
  旧FS-01～51とS01～30は `git show 398bd87^:tasks/todo.md` および
  `git show 398bd87^:docs/fast-scan-preflight.md` から回収し、下表で現在の経路へ対応させた。
  旧設計を仕様の一次資料とはせず、利用者の訂正と現在の実ソースに照合した。
- codebase-memory索引は2026-09-14T07:22:29Z。coverageは多くがmetadata_changed、追加ファイルは
  not_trackedだったため、根拠は現在の実ソース。索引がcleanであることを完全性の証拠にしない。

## 操作・精度に効く不足

下表の「不足」はソース上の確認であり、実機で発生頻度を測った結果ではない。

| 項目 | 既存実装と不足 | 採用する最小修正 |
|---|---|---|
| 起動 | ActivityはIntent／保存フラグで録音を選び、そのままresumeする。グラス上の二択がない。認証キーもプロセスを越えて残らない | 二択を起点にする。前回選択を強調し、タップで開始。初回設定は保持し、中断再開と前回答案は任意項目にする（RP-03/04/20） |
| 即開始 | `startLocalCapture` はASR準備確認とサーバ文書作成を待って録音を始める | 取得用のローカル記録を先に作り、HTTPの文書IDを後で対応付ける。録音は最初の有効サンプル後にREC。通常起動の通信待ちを操作から外す（RP-03/04/08） |
| 入力 | normalizerが同じactionを970ms内で抑止するため、異なる速いBACKも失われる。Activityは配送時刻を渡す | 物理イベントの組を重複排除し、別操作は通す。KeyEventの単調時計時刻と写真世代をレビュー期限へ渡す。測定済み相関幅を単純に短縮しない（RP-05/09） |
| 撮影速度 | `uploadCapturedPage` がControllerの直列queueでHTTPを待ち、次ページも入力も遅れる。保存は未確定1枚が中心 | 確定ページを端末へ先に保存し、送信を別queueにする。保存済み／送信済みを区別し、再起動後も未ACK分を送る（RP-06） |
| 自動判定 | 3枚burst・OCR・ShotScore・文字枠判定がある。用紙外周／静止検出ではない。空OCRの図だけのページは再試行へ回り、重複はOCR類似度に依存 | 図だけのページを落とさず、同じ紙の保持と似た別紙を区別する。既存判定の限界を実写真で測り、軽い差分／静止判定から補う（RP-10）。カメラ新基盤は条件付き |
| 二段階終了 | 第2BACKで音声終了するのは画面がLISTENINGになった後。最終写真の確認中は再び撮影終了扱い | 画面とは別に撮影終了要求と録音終了要求を保持する。最後の写真を残し、音声終了後の取り直しでマイクを再開しない（RP-08/09） |
| 音声保全 | WAVと重複1秒の結合・ハッシュ検証は既存。グラス側syncは主に30秒境界、再送cursorは未保存。OSによる無音化／入力経路変更を見ていない | 原音保全を優先し、未ACKの再送・中断末尾の回収・実入力監視を追加。録音プロセス死を連続録音として偽装しない（RP-07/08） |
| 実運用gate | REAL_MODEはofflineのanalyzerを一律拒否する。既存local analyzerはクライアントOCRを返すがplaceholder扱い | 実OCR受領とplaceholderを区別する既存境界の契約に直す。空OCRでも画像を保全し、画像対応solverへ渡す。REAL_MODEを下げて合格にしない（RP-02） |
| 設問・入力版 | 問番号の正規表現と大問画像範囲はある。選択肢の誤分割、共通資料の欠落に精度評価が必要。解析後の同一文書へのページ更新は409 | 既存ID・参照を保ち、解析前の訂正を優先。解析後の訂正は新しい入力文書で全再解析し、旧答案を現在版から外す。影響範囲だけの再計算は保留（RP-11/12） |
| 音声の解答利用 | 原音とtranscriptをsolverへ渡す実装はある。ASRは英語用、原音の実モデル利用・内容による設問対応は未評価 | 数字・否定・訂正・複数話者と紙面参照を採点。原音受理と必要箇所を聞けるかを早期能力試験で確認。時刻だけで切り分けない（RP-01/13） |
| 答案の完全性 | 記入本文と図Canvasはある。一方、共通promptは明示的な証明要求以外の途中式を抑える。一般の表描画はない | 解答欄形式に応じ、記述式数学に必要な導出を含める。表はまず項目と値の全文表示。汎用rendererは実答案が読めない場合のみ（RP-14/16） |
| 順次閲覧 | サーバは小問ごとに保存する。`AnswerReader.accept` はあるがActivityから接続されず、取得は一度。solver例外後に未解決がpendingのまま残り得る | 既存SQLite claimを使い、成功・失敗・資料不足を区別する。bundleを追加取得して閲覧位置を保つ。同じ教科の1チャットで逐次処理（RP-15） |
| 戻る・終了 | readerには一段戻る処理があるがActivityが全BACKを終了判定へ送る。CLOSEDの保存失敗時も終了し得る | メニューは一段戻る、答案本文では2回BACKで終了。CLOSED保存と遅延応答抑止を全phaseへ通す（RP-16/17） |
| 消灯・再装着 | DisplaySleepは15秒timeout経路。WearWatchは生存Activity内でのみ働き、CLOSEDでは復帰しない | 即消灯と再装着からの自動起動は早期に別能力試験。既存APIで成立した経路だけ接続する。不成立なら未達と報告し、勝手に要求を緩めない（RP-18） |
| 会場運用 | スマホ内CDP/FastAPI/文字答案と短いASRは測定済み。現配布サーバはloopback、AP全経路・30分同時入力・150分は未測定 | 初回準備をまとめ、Chrome前景／点灯、APと携帯回線の同居、再起動後の無PC起動を測る。グラスAPK導入済みを完走と呼ばない（RP-20/22） |

ソース位置:
[起動・入力・reader接続](../android-relay/glassdoc/src/main/java/dev/rokid/docscanglass/doc/DocScanGlassActivity.java)、
[撮影と通信](../android-relay/relaycore/src/main/java/dev/rokid/docscanrelay/DocScanController.java)、
[入力相関](../android-relay/glassinput/src/main/java/dev/rokid/docscanglass/input/GlassesInputNormalizer.java)、
[録音](../android-relay/glassdoc/src/main/java/dev/rokid/docscanglass/doc/ListeningRecorder.java)、
[保存](../android-relay/relaycore/src/main/java/dev/rokid/docscanrelay/study/AnswerStore.java)、
[reader](../android-relay/relaycore/src/main/java/dev/rokid/docscanrelay/study/AnswerReader.java)、
[実運用判定](../app/config.py)、[最終化とbundle](../app/main.py)、
[入力資料](../app/source_bundle.py)、[答案prompt](../app/solvers/llm_adapter.py)、
[音声受信](../app/listening.py)、[消灯](../android-relay/glassdoc/src/main/java/dev/rokid/docscanglass/doc/DisplaySleep.java)、
[再装着](../android-relay/glassdoc/src/main/java/dev/rokid/docscanglass/doc/WearWatch.java)。

## 新旧機能の採否

| 判断 | 対象 | 理由／再検討条件 |
|---|---|---|
| 採用・接続 | 起動二択＋前回選択、即取得、背景転送、段階的答案、任意の前回答案 | 毎回の操作と待ち時間に直接効く。新しい画面階層を増やさない |
| 採用・補強 | 3秒確認、単タップ手動／取り直し、独立した終了、入力版、原音保全 | 一度しか取れない音声と誤ったページ対応を守る。速度のために省略しない |
| 統合 | 全文OCR＋大問画像＋必要な音声根拠、同一教科の1チャット | 文書全体の文脈と細部を併用。既存大問選択と添付再利用を活用 |
| 比較用に限定 | PDF／2～3ページ結合 | 利用者の設定メニューにしない。同一資料・同一モデルの誤読と正答で既定方式を決める |
| 最小範囲を採用 | 過去ページの訂正、前回答案、表、状態案内 | 訂正後の全再解析、直近一件、全文の項目値、短いHUDから始める |
| 条件付き保留 | YUV常時preview・新しいML用紙検出・反り補正・音声の限定区間添付 | 現行撮影の遅さ／欠け、実画像の誤読、全原音の上限が測定で支配要因になった場合だけ |
| 保留 | 全履歴検索、ブックマーク、失敗問だけ再解析、話者分離専用基盤、可変font UI | 必須流れと実答案の評価後。現在の短い経路を複雑にしない |
| 廃止する計画 | 新CXR-L転送protocol、PythonのAndroid全面移植、別クラウド構築、ローカルLLM本流、ブラウザpool | AP＋スマホFastAPI＋ChatGPT Webで役割が重複する。既存fallback・実測は消さない |
| 更新する条件 | スマホ消灯／ロック・グラスWi-Fiなし、150分での強制終了 | 前者はAP＋Chrome前景／点灯へ変更済み。150分は試験時間であり自動終了条件ではない |

## 旧タスクの行き先（番号の欠落を防ぐ索引）

全FS番号を下表で処理する。「統合」は同名の新クラスを作る指示ではない。
MS-1～6は部品実装の履歴として保持し、MS-7の未測定分はRPの受け入れへ統合する。
GIの実測は入力相関の証拠として保持し、速い別操作の欠落はRP-05で修正する。

| 旧ID | 判断・現在の行き先 |
|---|---|
| FS-01 | 評価枠組みを再利用 → RP-01/19/22 |
| FS-02 | 文書検査の既知不具合は完了履歴として保持。現行文書gate → RP-21 |
| FS-03 | camera/mic同時成立の早期測定 → RP-01/08 |
| FS-04 | CXR-L媒体転送の新規実装は廃止。AP成立確認 → RP-20 |
| FS-05 | ロックスマホ条件は更新。初回準備・無PC再起動 → RP-20 |
| FS-06 | クラウドASR案は廃止。採用済み端末内ASRの品質 → RP-07/13 |
| FS-07 | 別provider試作は廃止。主経路の紙＋音声能力試験 → RP-01 |
| FS-08 | 状態復元 → RP-03/17 |
| FS-09 | ジェスチャ相関と期限 → RP-05/09 |
| FS-10 | 起動二択 → RP-04 |
| FS-11 | 既存可視ACKを再利用 → RP-09 |
| FS-12 | 既存readerを再利用 → RP-14/16 |
| FS-13 | 新Backend／全IDのUUID化は廃止。ローカル記録と既存HTTP IDの対応だけ → RP-03 |
| FS-14 | Python全面移植は廃止。端末の保存先と原子的更新 → RP-03/06/07 |
| FS-15 | 独自binary protocolは廃止。既存HTTP・hash・連番・ACK → RP-06/07 |
| FS-16, FS-17 | CXR-Lのchunk転送実装は廃止。独立した写真／音声HTTP送信へ統合 → RP-06/07/20 |
| FS-18 | 実運用準備・認証・明確な失敗 → RP-02/20 |
| FS-19 | 新provider SDK追加は廃止。既存chatgpt-webを使用 |
| FS-20 | 分割処理のAndroid移植は廃止。分割精度は既存Pythonで改善 → RP-12 |
| FS-21, FS-22 | preview／検出基盤は条件付き。既存カメラ・枠校正・短い案内 → RP-10 |
| FS-23 | 同一紙・似た別紙・品質 → RP-10 |
| FS-24 | 実装済みレビューを補強 → RP-09 |
| FS-25 | 保存と転送を分離 → RP-06 |
| FS-26 | 最後の1枚・0枚終了 → RP-08/09 |
| FS-27 | 通常モードの短い通し試験 → RP-21/22 |
| FS-28 | 最初の実サンプル・連続録音 → RP-07/08 |
| FS-29 | 原音の耐中断保存 → RP-07 |
| FS-30 | 制御を待たせない転送・音声保全優先 → RP-06/07 |
| FS-31 | 既存音声結合・連続性検査を再利用 → RP-07/13 |
| FS-32 | 第2BACKと音声終了 → RP-05/08 |
| FS-33 | 採用済みlocal ASR/VADの重複・欠落・負荷 → RP-07/13 |
| FS-34 | 内容による音声と設問の対応 → RP-13 |
| FS-35 | 関連画像と音声の解答利用 → RP-12/13/19 |
| FS-36 | 答案形式・検証・全文 → RP-14 |
| FS-37 | 既存SQLite claimを活用、失敗と再開 → RP-15 |
| FS-38 | 順次更新・位置保持・メニュー → RP-15/16 |
| FS-39 | 訂正を採用、改訂後は全再解析。細粒度再計算は保留 → RP-11/12 |
| FS-40 | 新規状態UI基盤は作らず短い案内に統合 → RP-04/08/10/16 |
| FS-41 | スマホ常駐・再起動・復旧 → RP-20 |
| FS-42 | CLOSED・kill・遅延応答 → RP-03/17/22 |
| FS-43 | Bluetooth媒体最適化は廃止。AP再接続・通信量を測る → RP-20/22 |
| FS-44 | OCR／ASR／根拠／最終答案の評価 → RP-01/13/19 |
| FS-45 | 容量・熱・電池・保全。無断削除なし → RP-07/22 |
| FS-46 | 可読性・疲労・図表全文 → RP-16/22。font設定追加は実測後 |
| FS-47 | 経路別OPERATION_CONTRACT → RP-21 |
| FS-48 | 現行仕様・版・手順整合 → RP-21 |
| FS-49 | unit/API・build・APK検査 → RP-21 |
| FS-50 | 通常20ページ／リスニング30分＋20ページ → RP-22 |
| FS-51 | 反復50回・150分・端末状態 → RP-22 |
| FS-52 | 録音ブックマーク・録音中の任意再開は保留。必須の取り直しと無断再録音防止はRP-08/11 |
| FS-53 | 直近答案だけ採用 → RP-16。全履歴・失敗問限定再解析は保留 |
| FS-54 | 反り／見開き補正は誤読測定後 → RP-10/19 |
| FS-55 | ローカルLLMの本流再評価は廃止。既存測定を保存 |
| FS-56 | 任意Wi-Fiを主経路APへ更新 → RP-20/22 |
| FS-57, FS-58 | 標準AI連携・standalone内推論は追加候補として保留、本流の予定外 |
| FS-59 | 既存答案基盤を再利用 → RP-12/14/15/16 |
| FS-60 | fixture整備は部分完了、実写真・実音声・人手rubricは未了 → RP-01/19 |
| FS-61 | timeout部品は既存、即消灯は未達 → RP-18/17 |
| FS-62 | 生存Activity内のwear部品は既存、終了後の自動起動は未達 → RP-18 |
| FS-63 | クラウド中継構築は廃止。スマホAPI認証・初回準備 → RP-03/20 |
| FS-64 | chatgpt-web部品は既存、主経路通し・利用可能状態 → RP-01/20/22 |
| FS-65 | 図の実装を再利用、本文・表・実表示を補完 → RP-14/16 |
| FS-66 | 大問資料と同一チャット再利用 → RP-12/19 |
| FS-67, FS-68, FS-70, FS-72 | ローカルLLMの入力量・KVメモリ・モデル選定の調査／調整は廃止。実測は保存 |
| FS-69, FS-71 | ローカルモデル前提は廃止。答案精度の目的はChatGPT評価へ統合 → RP-01/14/19 |

## 要求・境界シナリオの網羅表

R1～13は[fast-scan-decisions](fast-scan-decisions.md)の利用者要求を参照する。
R1→RP-04、R2→10、R3/R4→05/09/11、R5→06/10、R6→08/09、R7/R8→07/08、
R9→12/13/19、R10→14/15/16、R11→03/17/18、R12→03/06/07/12/15、R13→20/22。
「起動後すぐ」と「前回答案を任意に開く」もRP-04/16/20に含む。

| 旧試験 | 現在残す受け入れ条件 | 所有task |
|---|---|---|
| S01 | 通常モードは音声を起動せず自動撮影 | RP-04/08 |
| S02 | 描画2秒遅延でも、その後に可視3秒 | RP-09 |
| S03 | 2999msのタップが3050msに届いても元ページを訂正 | RP-05/09/11 |
| S04 | 3000msちょうどを含む期限後入力は次ページの誤撮影に使わない | RP-09 |
| S05 | 非可視では確定せず、復帰後に3秒 | RP-09 |
| S06, S07, S08 | 同じ紙は自動再登録しない、似た別紙は落とさない、意図した同一紙は手動追加可能 | RP-10 |
| S09, S10, S11 | JPEG待ち／取り直し待ち／0枚で終了しても最後の入力と戻る経路を失わない | RP-08/09 |
| S12, S13 | 最初の実サンプルからREC、撮影20枚の間も連続録音 | RP-08/22 |
| S14, S15 | 同じBACKの二重配送は1回、970ms内の異なる操作は2回 | RP-05 |
| S16, S17 | 最終写真確認中でも別の第2BACKで録音終了、取り直しで音声を再開しない | RP-08 |
| S18, S19 | OSによる無音化と長い自然な無音を区別、原音を保全 | RP-07/08 |
| S20 | 旧Bluetooth断をAP断へ更新。取得は継続し保存分だけ再送 | RP-06/07/20 |
| S21 | 携帯回線だけの断ではAP上の保存・ASRと保存答案閲覧を継続 | RP-20/22 |
| S22, S23 | 音声逆順・重複・欠番、保存前ACKを拒否 | RP-07 |
| S24 | 入力版の変更後、古い答案を現在の答えとして表示しない | RP-12/15 |
| S25 | AI応答を見失ったら同じチャットを確認、無制限に再送しない | RP-15/19 |
| S26, S27 | 長い証明の全文保持、到着順不同でも閲覧位置安定 | RP-14/15/16 |
| S28, S29 | CLOSED保存後のkill・遅い結果・折りたたみforce-stopで勝手に再開しない | RP-03/17/18 |
| S30 | 容量不足時は原音と既存資料を守り、新規写真を止めて通知 | RP-07/22 |
| X01 | 過去ページ訂正、旧版保全、新版の答案のみ採用 | RP-11/12 |
| X02 | 同じ紙の再静止／似た別紙／安定待ち中の輪郭消失 | RP-10 |
| X03 | 読み上げ順逆転／後からの訂正／共通会話を内容で結ぶ | RP-13 |
| X04 | 欠け・反射の短いHUD案内が役立ち、音声案内を録音へ混ぜない | RP-10/22 |
| X05 | 旧スマホ消灯・Wi-Fiなしは撤回。AP＋Chrome前景／点灯・30分・スマホ操作0回 | RP-20/22 |
| X06 | AP断と携帯回線断を分け、保存／ACK前後killで二重登録・CLOSED復活なし | RP-06/07/17/22 |

## 調査中に実行した確認

Runs on: Windows。実機受け入れ／ChatGPT採点は実行していない。

`py -3.12 scripts/eval_fast_scan.py --pack tests/fixtures/answer_forms/cases.json` の出力は
8 cases / 17 questions、synthetic_design_cases、hardware_verified=false、ai_executed=false、
rubrics_pending_review=10。既存fixtureの存在は高精度の実績ではない。

現在のglassinputビルドに対する次のJShell入力で、異なる2組のBACKの抑止を再現した。
`jshell.exe -q --class-path android-relay/glassinput/build/classes/java/main -` に入力する。
JDKはプロジェクト指定のJDK17。これは不具合の再現で、合格試験ではない。

```java
import dev.rokid.docscanglass.input.*;
var n = new GlassesInputNormalizer();
n.accept(InputSignal.key(1000, "DOWN", "KEYCODE_NOTIFICATION", true));
System.out.println("first=" + n.accept(InputSignal.key(1020, "DOWN", "KEYCODE_BACK", true)));
n.accept(InputSignal.key(1500, "DOWN", "KEYCODE_NOTIFICATION", true));
System.out.println("second_distinct_500ms=" + n.accept(InputSignal.key(1520, "DOWN", "KEYCODE_BACK", true)));
/exit
```

出力: `first=Optional[BACK]`、`second_distinct_500ms=Optional.empty`。
既存の相関幅の実測を保持したまま、異なる物理操作の回帰試験へ置き換える。

## 受け入れの限界

追加実装前に本計画の認識を合わせる。即消灯・再装着自動起動・原音のモデル利用は未成立の能力を含むため、
早期試験で判断する。成立しない場合は要求が未達と伝え、代替の操作を利用者と決める。
性能や正答率の未測定値は作らない。既存の短いスマホASR測定を30分同時取得の証拠に流用しない。

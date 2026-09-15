# 手動併用スキャン・省電力・OCR/画像/音声/図

Status: Internal progress。実装・自動試験を完了。実機適用と精度比較は未実施。
Runs on: Windowsで実装・試験。運用先はglassdocとスマホAP/FastAPI/Chrome。

## 依頼・決定

自動＋単タップ撮影、表示後3秒取消、確認中のカメラ停止、解析待ち/終了消灯、
OCR＋画像とPDFの比較、図付き答案、並行録音と端末内ASR/VADが依頼範囲です。
単タップ＝待機中撮影／3秒中取消、視界と同じ＝撮影範囲の一致、と確認済み。
ASRは**端末内**を選択。解答はChatGPT Webのままです。原音と正規化PNGを保全し、
時刻だけで設問対応を断定しません。手動貼付け、PCを必要とする会場運用、
クラウドASRへの自動切替は選択していません。「再開」を受けて同じ実装を継続しました。
仕様は [現行計画](../../tasks/plan.md) の2026-09-15改訂、実装項目は
[MS-1～7](../../tasks/todo.md)、操作・設定・制限は
[現行runbook](../../docs/multimodal-scan.md) を参照してください。

## 作業木とレビュー

- 作業木 `C:/rokid-docscan-starter`、branch `feature/multimodal-scan`。
  基準HEAD `f6e7364d475e9f430ef3bae8c9325abd856a5b71`。開始時clean。
  本記録を含む変更はこの依頼に属します。確定commitはこのファイルのGit履歴で特定できます。
- 変更面は `android-relay/{glassdoc,relaycore}`、`app/{source_bundle,answer_diagrams,local_asr,listening}.py`、
  `app/{main,db}.py`、`app/solvers`、対応試験、ASR準備/測定script、現行資料です。
  録音、画像、ASRモデル、ダウンロードしたCLIはGit対象外です。
- graph project `rokid-docscan-starter`、索引世代2026-09-14T07:22:29Z。
  根拠ファイル51件はmetadata_changedまたは未索引で、coverage確認後に実ソースへfallback。
- local code-reviewの仕様/標準レビューで見つかった、レビュー再送の無応答、ERRORからの終了、
  長い図ラベルの欠落、録音失敗後の遅いOCR、原音参照の並行上書きを修正しました。
  最後の並行更新修正はAPI試験で競合を再現し、全pytestに含めています。

## 実装済み

Runs on: 以下の実装確認と自動試験はWindows。物理挙動の証明ではありません。

- MS-1: 既存自動ループをlocal surfaceだけで有効化。単タップ手動/取消、最後の写真を
  保留した撮影終了、可視ACKから3000ms、隠蔽時タイマー停止、旧callback抑止とUNKNOWN保持。
  選択写真の撮影要求時刻を保存・送信。撮影範囲用の外枠と既存guide設定を保持します。
- MS-2: 解析/録音終了待ちのDisplaySleepとpartial wake lock、結果/エラー時の復帰要求、
  解答表示中のダブルタップ2回によるCLOSED保存・終了。local finalizeのHTTP5分上限を外し、
  閉鎖後は応答で再表示しません。物理消灯には既存timeout経路を使います。
- MS-3: 全文OCR Markdown＋対象大問画像、2～3ページ結合、PDF比較モード。
  Page/question_id/撮影時刻を保持し、20添付にMarkdownと原音も含めます。
  添付未確認送信、画像欠落、容量超過の切捨てを拒否。PNGが大きい場合は原寸高品質JPEGで
  添付し、正本PNGを維持します。資料・原音・文字起こし変更は入力digestへ反映します。
- MS-4/5: 線分・折れ線・円・文字の図形式を検証・保存してanswer-bundleで配送。
  図付きschema 2、文字のみschema 1。本文と図をページ送りし、長いラベル全文と説明も
  表示・再開。資料不足の理由を保存し、readyと扱いません。
- MS-6: グラスAudioRecordとスマホ向けwhisper.cpp＋Silero VAD。30秒チャンクに前の1秒を
  重ね、撮影と別キューで送信・ASR。原音再送は冪等で、ハッシュ、サンプル数、欠番、時計を
  検査してoriginal.wavへ結合。区間は元録音時刻と要音声確認フラグを保持し、solverに
  Page/question_idとの内容対応を要求。ASR未設定は録音前に拒否、録音失敗はERRORを維持。
- runbook、操作表、実装面台帳、バージョン契約を更新。古い「自動ループ不存在」
  「グラスにWi-Fiなし」を現行説明から訂正しました。過去の測定は維持します。

## 検証結果

Runs on: Windows、ASCIIパス `C:/rokid-docscan-starter`、2026-09-15。

| 実行コマンド | 出力 |
|---|---|
| `py -3.12 -m pytest -q` | `600 passed, 1 skipped, 1 warning in 70.77s` |
| `py -3.12 -m ruff check .` | `All checks passed!` |
| `py -3.12 -m pytest -q tests/test_documentation_contract.py tests/test_versioning.py` | 進捗更新後 `21 passed in 4.82s` |
| `git diff --check` | exit 0、出力なし |
| `./android-relay/gradlew --no-daemon test testDebugUnitTest assembleDebug` | `BUILD SUCCESSFUL in 46s`、199 tasks: 19 executed, 180 up-to-date |
| `bash -n scripts/build_local_asr.sh` | exit 0、出力なし |

基準pytestは `583 passed, 1 skipped in 70.16s` でした。
GradleはJDK `C:/Users/Public/rokid-build-tools-20260901/jdk17/jdk-17.0.20.1+1`、
SDK `C:/Users/pupu_/AppData/Local/Android/Sdk`、Platform 36、wrapper Gradle 9.4.1。
ネイティブ描画試験の `android-relay/glassdoc/build/outputs/diagram-review.png` を目視し、
三角形と端の参照ラベルが範囲内にあることを確認しました。実機表示ではありません。

### 最終APK

Runs on: Windows。上記46秒の最終ビルド直後に検査。

対象 `android-relay/glassdoc/build/outputs/apk/debug/glassdoc-debug.apk`。
SDK Build Tools 36.0.0の次のコマンドを実行しました。

- `aapt2 dump badging <対象APK>` → package `dev.rokid.docscanglass.doc`、versionCode `8`、
  versionName `0.7.0`、minSdk `28`、targetSdk `36`、
  activity `dev.rokid.docscanglass.doc.DocScanGlassActivity`。
- `apksigner verify --verbose --print-certs <対象APK>` → `Verifies`、v2 `true`、v1 `false`。
  証明書SHA-256 `906307478018e09e2937cfd8042a674d27598767577e08a304472aae407ccacc`。
- `Get-FileHash -Algorithm SHA256 -LiteralPath <対象APK>` →
  `599BC0CC4F8151373B0EEFD0B8A62D71C089ABC9383AFA6C1BF60A2EFCC2E4A6`。

### ASR部品測定

Runs on: Windowsの公式whisper.cpp CLI。スマホ速度と会場運用の証拠には使いません。

`py -3.12 scripts/prepare_local_asr.py --windows-cli`で固定資産を取得・SHA-256照合しました。
URL、revision、ハッシュはscriptを正本とします。環境変数はrunbookの通り、Windows CLIは
`data/local-asr/windows-v1.8.3/Release/whisper-cli.exe` を指定しました。

- `py -3.12 scripts/benchmark_local_asr.py data/local-asr/jfk.wav` → audio 11秒、
  wall 2.0秒、real_time_factor 0.182、segment 150–10790ms。
- `py -3.12 scripts/benchmark_local_asr.py data/local-asr/jfk-padded.wav` →
  前後3秒の無音を加えた17秒、wall 2.359秒、ASR 2.344秒、real_time_factor 0.138、
  segment 3160–13620ms。VAD後も元録音の時間軸を保持しました。
- 入力は固定whisper.cppの公式[サンプル音声](https://github.com/ggml-org/whisper.cpp/blob/2eeeba56e9edd762b4b38467bab96c2517163158/samples/jfk.wav)。試験音声はignored data内です。
  撮影OCR精度や本番リスニングの正答率は評価していません。

## 残る範囲と再開順

### 1. 対象・承認・外部観察

Runs on: Windowsのadb読み取り。その後の書込み先は明示したグラスとF-51F。

`adb devices -l` の直近出力はグラス `192.168.0.4:5555` (`RG_glasses`)、
F-51F `192.168.0.30:38615`、別の `adb-ZY22LWGDCV-gAfvon._adb-tls-connect._tcp` です。
複数endpointのため個別実機操作へ進んでいません。導入・起動・設定変更の承認は未取得。
接続を再列挙し、対象の同一性、署名/ダウングレード、外部LED動画の準備を確認してください。
APK再ビルド時は上のハッシュを流用せず再検査します。

### 2. スマホASRを導入して測る

Runs on: 指定F-51FのTermux。実機適用の承認後。

runbookのビルドscript、モデル取得、環境設定を実行します。撮影時刻・図・資料不足
メタデータの加算DB移行があるので、起動前に既存DBを保全して適用対象を確認します。
実DBへの適用は本変更では実行していません。Chromeを前景/点灯で保持し、録音・撮影と
同居させて処理速度と待ち行列を測ります。ファイル存在だけのreadinessを速度合格と扱いません。

### 3. APKと会場経路を受け入れる

Runs on: 指定グラス → F-51F AP → F-51F FastAPI/CDP/Chrome。外部カメラでLEDを観察。

自動/手動撮影、3秒確認/取消/最後の1枚、画角校正、録音独立終了、図の可読性、消灯と
結果復帰、ダブルタップ2回での終了を確認します。既存15秒timeoutは瞬時消灯ではありません。
録音プロセス死亡後の途切れを連続音声として再開する機能はなく、原音を保全して開始を
拒否します。新文書で再録音が必要です。連続運用と折りたたみ復帰は未検証です。

以前のスマホ単独CDP/FastAPIと文字答案の測定は `docs/hardware-measurements.md` §F-6-6～10に
あります。「スマホでは一度も動いていない」と戻さないでください。グラスAPからの今回の
全経路はまだ測っていません。phone relayやPC Chromeの結果を代用しません。

### 4. 資料方式を比較する

Runs on: 会場経路で取得した同じ正規化PNG/OCRと同じChatGPTモデル。
PCでの準備・単体比較は部品比較と明記。ChatGPT実送信は対象資料の承認後。

runbookの3モードで添付数/容量、準備/解答時間、文字・数式・図の誤読と最終正答を比較します。
原音添付の受理・音声参照も未検証です。needs_input指示はモデルの実音声理解を保証しません。
原寸画像保存もモデル内部の縮小を防ぐ保証ではありません。

## 一次資料と再開用skill

OpenAI FAQはplanのリンク、Android公開wake APIはAndroid12 AOSP PowerManager.java、
whisper.cpp CLI/VAD時刻変換とCMakeはscriptが固定する公式revisionを確認しました。
Context7 library IDは `/websites/developer_android`。有効な既存測定を再利用し、
変更した条件だけ測り直します。工程spineはAgent Skills、最小実装はPonytail。
再開には `progress-checkpoint`、実機適用前には `verifying-premises` を使用します。

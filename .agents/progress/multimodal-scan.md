# 手動併用スキャン・省電力・OCR/画像/音声/図

Status: Internal progress。実装・自動試験、APK導入、スマホ更新・ASRの部品試験済み。AP全経路は未実施。
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

Runs on: Windows、ASCIIパス `C:/rokid-docscan-starter`、2026-09-15。ASR scriptの構文検査はTermux。

| 実行コマンド | 出力 |
|---|---|
| `py -3.12 -m pytest -q` | `600 passed, 1 skipped, 1 warning in 70.77s` |
| `py -3.12 -m ruff check .` | `All checks passed!` |
| `py -3.12 -m pytest -q tests/test_documentation_contract.py tests/test_versioning.py` | 進捗更新後 `21 passed in 4.82s` |
| `git diff --check` | exit 0、出力なし |
| `./android-relay/gradlew --no-daemon test testDebugUnitTest assembleDebug` | `BUILD SUCCESSFUL in 46s`、199 tasks: 19 executed, 180 up-to-date |
| `bash -n scripts/build_local_asr.sh` | LF修正後の配布物をTermuxで検査、exit 0 |

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
利用者がこのグラスへのAPK導入とF-51Fのサーバ更新・ASR設定を承認しました。
さらに「LEDの監査はシステム固定のため不要」と指定したため、今回のLED監査は省略します。
物理LEDを観察済みという意味ではなく、制御コードも変更しません。
接続を再列挙して上記対象を確認しました。以後も対象の同一性と署名/ダウングレードを確認します。
APK再ビルド時は上のハッシュを流用せず再検査します。

### 2. スマホ更新・ASRの部品試験（実施済み）

Runs on: 指定F-51FのTermux。利用者の適用承認後に実行済み。

ビルド、モデル取得、環境保存、DB保全・加算移行、サーバ起動、ASRと2チャンクAPI試験を実施。
実測のコマンド・出力・tupleは [hardware-measurements.md §G](../../docs/hardware-measurements.md#g-local-asr)。
11秒音声を5.109秒、17秒を5.814秒で処理。34秒音声の再送と原音一致を確認しました。
グラス実録音と撮影の同居、長時間運用は未測定です。

サーバのappはcommit `12004a4`、PID記録はスマホの `~/rokid-server/data/server-12004a4.pid`、
ログは同ディレクトリのserver-12004a4.log。設定は `~/rokid-server/multimodal.env`。
端末内CDP forwardは `emulator-5554` → 127.0.0.1:9222。SSHが停止しても再インストールせず、
端末の既存Termux/sshdを復旧してください。Chromeは前景に戻します。

### 3. APKと会場経路を受け入れる

Runs on: 指定グラス → F-51F AP → F-51F FastAPI/CDP/Chrome。LED監査は利用者指定で省略。

現在のサーバは部品試験用の127.0.0.1:8000待受で、AP公開は未適用です。
API認証キー未設定、REAL_MODEは既定0、cloud analyzer未設定です。`REAL_MODE=1` は
現行 `config.require_real_provider` / `main.lifespan` でlocal analyzerを拒否します。
この条件を解消してから経路の実機受け入れへ進みます。利用者が選択した主解答経路は
ChatGPT Webのままで、検査を通すためにAPI課金ルートへ勝手に変更しないでください。
新しい認証鍵の設定とAP設定変更は、対象を明示した承認を必要とします。

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

## 実機適用中の記録（2026-09-15）

Runs on: Windowsから指定グラスとF-51Fへ適用。まだ会場経路の通し試験ではありません。

- `adb -s 192.168.0.4:5555 pull <既存APK> data/glassdoc-installed-before-multimodal.apk`
  で旧APKを保全。`apksigner verify --print-certs` のSHA-256が上記証明書と一致。
- `$env:AGENT_APPROVED=1; adb -s 192.168.0.4:5555 install -r <最終APK>` → `Success`。
  `dumpsys package dev.rokid.docscanglass.doc` → versionCode 8、versionName 0.7.0。
  導入前の `dumpsys media.camera` は `Active Camera Clients: []`。
- F-51FのSSHが接続拒否。Termuxが空のプロンプトにあることを画面で確認し、承認範囲内で
  `termux-wake-lock` と `sshd` を入力。再接続後のPythonは3.14.6、空きメモリ約5.8GB。
- スマホの `~/rokid-backups/pre-multimodal-8163b5f` に旧app/requirementsとSQLite backupを保全。
  `PRAGMA quick_check` → `ok`。既存9テーブルの行数は全て0。サーバは更新前に停止状態。
- commit 8163b5fのappとASR scriptを `~/rokid-server` へ配置。
  転送tar SHA-256 `9f322753bc068c15aae7b1c6105dda25c92351a5905203b6855bee6142618a4e` を照合。
- ASR buildは `set: pipefail CR: invalid option name` で停止。Git blobはCRLF 0件なのに
  Windows `git archive` がCRLF 17件へ変換していました。`.gitattributes` に
  `*.sh text eol=lf` を加え、`git archive --worktree-attributes` から取り出したscriptが
  CRLF 0件、LF 17件であることを確認。修正版をcommit `12004a4` として再配布しました。
- 修正版をスマホで `bash -n` → exit 0、`bash scripts/build_local_asr.sh` →
  `[100%] Built target whisper-cli` と2モデルのハッシュ照合出力。
  以後の実測値と成果物ハッシュはhardware-measurements.md §Gを正本にしました。
- スマホのテスト文書document_id 1には公式サンプルから作った音声だけが入り、撮影ページは0件。
  `data/asr-smoke-12004a4.json` とoriginal.wavを保全。ChatGPTへの実送信はしていません。
- 文書とLED監査方針の更新後、`py -3.12 -m pytest -q tests/test_documentation_contract.py tests/test_rokid_led.py`
  → `15 passed in 0.81s`。`py -3.12 -m ruff check .` → `All checks passed!`。
  原音試験の結果JSONをPCの `data/f51f-asr-smoke-12004a4.json` にも保全しました。

# PR37: 実機接続PCのCodexへの引き継ぎ

Status: Internal progress。実機前のサーバ修正・回帰試験・CI整備を追加。実機受け入れは未実施。
Runs on: この追補の実装・ローカル試験は隔離Linux環境。CIはGitHub Actions。
運用先はglassdoc → F-51F AP → 同スマホFastAPI／ASR／Chrome。Windows PCは開発・導入・測定用。

## 読む順序と今回の境界

Runs on: 実機接続Windows PCのCodex。最初はリポジトリ確認だけを行う。

この記録、CLAUDE.md、.agents/progress/multimodal-scan.md全文、tasks/plan.mdの現行部分、
tasks/todo.mdを読む。既存の停止記録と原本を削除しない。最新のブランチは
`feature/multimodal-scan`、PRは37。mainへのマージは依頼されていない。

この追補の親となる確認済み基準は cce86cbbc6cd457712b093b82eb9ac73c0ebde30。
そのツリー 178b3f3fdd19c25d837a255a5bb2f1e9623ed148 と復元した全ファイルを照合した。
以前の会話にあった「627件成功」は今回の検証記録ではない。新しいHEADのCI結果を採用する。

今回、カメラ寸法、露出、burst、再撮影間隔、ジェスチャ割当、3秒レビュー、LED、
署名鍵、端末設定、主経路のモデル選択は変更していない。端末へ接続・導入・撮影・録音していない。
実機確認前に、資料をモデルへ送信するライブ試験を勝手に実行しない。

## 追加した修正

Runs on: サーバはF-51F、テストはLinux／Windows CI。テストは合成資料・ブラウザスタブのみ。

| 項目 | 変更と証拠 |
|---|---|
| 生成物の文書検査 | `tests/test_documentation_contract.py` のディレクトリ規則が `**` を扱う。存在しないソース参照は引き続き失敗する。生成PNG/APKをGitへ追加して誤魔化していない。 |
| 入力版 | `app/input_identity.py` でファイルを分割読込してSHA-256計算。`app/main.py` の答案入力版に画像の内容・OCR本文・図の読取・順序・原音・文字起こしを含める。pHashは類似判定用のまま。 |
| Python互換 | 音声ハッシュでPython 3.11以降専用の関数に依存しない。ファイル内容だけが変わる場合も回帰試験。 |
| ブラウザ排他 | `app/browser_guard.py` は同じDATA_DIRのプロセス／スレッド間で一つの書込だけを許可。LinuxとWindowsのOSロックを使う。新しい依存やブラウザpoolはない。 |
| 送信結果不明 | 送信直前に小さな私的journalを確定。クリック結果不明や返信取得失敗後は再送せず、サーバ再起動でも停止を維持。元のチャットを確認するまで解除しない。 |
| 添付と返信の対応 | 未確認の添付は最終試行でも送らない。他のチャットへ移動した場合は添付キャッシュを捨てる。送信前から存在したassistant返信を新答案として採用しない。 |
| 失敗の表示 | 小問の既存構造メタデータへ固定の失敗コード・回数を保存。本文・資格情報を例外から転記しない。失敗だけの更新も答案revisionへ反映。送信不明では別providerへ自動移行せずバッチを止める。 |
| 環境検証 | `requirements-phone.txt` と `constraints-phone.txt` は記録済みFastAPI系の互換レーン。全依存の完全lockではない。Linux CIの互換試験はTermuxでのインストール成功を証明しない。 |
| CI | 純Java試験と両APKの生成・署名/identity/hash記録は既存CI修正を維持。Windowsの排他・journal・入力版試験、phone互換レーン、Ruffを追加。 |

DBに新しい表や列は追加していない。入力digestのアルゴリズムは変わるため、旧digestと新digestを
同一入力とみなして結果を混ぜない。旧オフライン答案は削除しない。最初の通し試験は新しい読取で行う。
読み込み時のハッシュ計算コストは未実測であり、速度改善済みとは扱わない。

ブラウザの全ワーカーは同一のROKID_DATA_DIRを共有すること。同じChromeを別DATA_DIRや別ホストから
同時に操作する構成は対象外。排他競合は待ち続けず停止する。送信とサーバの答案DB保存を跨ぐ
完全なexactly-onceは保証していない。受信済み結果の自動回収・取り込みは今後の別工程である。

## 検証記録を照合する

Runs on: Linuxの隔離作業環境とGitHub Actions。Windows実機の検査結果とは区別する。

修正前に以下を再現した。

- 文書の生成PNG/APK参照の誤判定。
- 同じpHash/OCRの画像差替え、図の読取変更でdigestが変わらないこと。
- Python 3.10相当のhashlibで音声digestが失敗すること。
- 送信結果不明の2呼出しで合計6回送信を試みること。
- チャット移動後の添付省略、前問の返信が次問の答案になること。
- 解析例外がpendingのままで理由が保存されないこと。

修正後の正確な全件数、実行環境、CI run、結果はPRの最新の検証コメントを参照する。
局所テストの件数を全体テストの件数として転記しない。CIが失敗している場合はログを読んでから進める。
Androidの既存試験は以前一度RejectedExecutionExceptionで失敗し、次回同じ本体コードで成功した記録がある。
再発時は終了後のexecutor待機を含む試験の順序を調査し、無条件リトライで成功扱いしない。

この環境では端末SDK・JDK17・Ruff取得用ネットワークが使えないため、Androidビルドと追加環境の
結果はGitHub Actionsで確認する。自動テストは実機写真、実音声、光学表示、携帯回線の検証ではない。

## 次工程1: Windowsで更新・検査する

Runs on: 実機と接続するWindows PC。まだ端末操作はしない。

1. `C:/rokid-docscan-starter` のbranch、origin、未commit変更を確認する。
   `git fetch origin feature/multimodal-scan` 後、ローカルが同ブランチか照合する。
   cleanかつfast-forward可能な場合だけ `git merge --ff-only origin/feature/multimodal-scan`。
   差分があれば保全して照合し、reset --hard、clean、強制push、無断stashはしない。
2. `ROKID_CHATGPT_LIVE` を無効にして、`py -3.12 -m pytest -q` と
   `py -3.12 -m ruff check .`。到達可能なChromeだけを根拠にライブ試験を起動しない。
3. CLAUDE.mdのJDK17／Android SDKを使い、ASCII-onlyのルートから
   `.\android-relay\gradlew.bat --no-daemon test testDebugUnitTest assembleDebug`。
   Python/Java/SDK/Gradleの実際の版、HEAD、作業差分、終了コードを記録する。
4. 生成したglassdoc APKをaapt2、apksigner、Get-FileHashで検査する。
   packageとActivityが既存停止記録の対象であること、署名が既存端末と一致することを確認。
   **CIのdebug署名はPCの既存鍵と同じとは限らない。CI APKをそのまま上書き導入しない。**
5. 旧APKと今回のAPK、サーバソース、ローカル原本バックアップを区別して保全する。
   古い作業フォルダのAPKを新HEADの成果として使わない。

## 次工程2: 原本を保全して同一端末へ導入する

Runs on: Windows PC、Rokid本体、F-51F。対象端末は既存停止記録と照合する。

1. adbをread-onlyで列挙し、各コマンドに検証済みserialを指定する。
   IPは以前の値を固定しない。未知の端末、署名不一致、downgrade、UNKNOWNな撮影状態なら停止する。
2. 既存停止記録のグラス、F-51F、保存原本、送信ACKと解析状態を再確認する。
   ローカルに保存されたAPK・tarはGitHubから取得できるとは限らない。
3. private原本・pending・manifestを保全後、同一端末への通常の更新導入を行う。
   uninstall、アプリデータ消去、署名鍵更新、SDK更新、権限・AP/セキュリティ設定変更は
   この引き継ぎだけでは承認されない。必要なら具体的変更を利用者に確認する。
4. 起動は選択画面で止める。用紙・利用者の準備を確認してから撮影を開始する。
   新しいサーバコードをF-51Fへ反映する際も既存環境を保全し、Web/ASRを含む実行構成を照合する。
   新しいrequirementsファイルを理由に、動いているTermux環境を無条件で上書きしない。

## 次工程3: 通常の読取を短く通す

Runs on: グラスとF-51F。まず既存Wi-Fiで部品を切り分け、最後にF-51F AP＋携帯回線で経路を確認する。

1. 実画像表示から2.5～2.9秒に単タップし、P1の取り直しがP2へ流れないことをログと光学表示で確認。
   早い取り直し直後の別タップ、無操作確定、期限後入力、最後の一枚でも確認する。
2. 同じB5冊子の見開きと片側単頁を実際に撮り分ける。同じ見開きを2回撮った結果を比較済みとしない。
   四辺、傾き、湾曲、文字サイズ、暗さ、ブレ、OCR、図/数式、最終正答を比較する。
   270度の向き修正は台形歪み補正ではない。露出・寸法・retryを闇雲に変更しない。
3. 2～3ページから答案まで通す。同じチャットで2つ以上の小問を解き、次問が前問の返信を拾わず、
   完全な添付が確認されていることを確認する。同じ答えの文字列になっても別の返信である必要がある。
4. 写真保存後の通信断と復旧を試す。撮影や終了の操作がHTTP待ちに阻害されず、原本・順序が保持されること。
5. 送信直後の通信断は、利用者の同意のもとで一回の限定試験にする。
   アプリの再起動でjournalが消えず、追加送信されず、理由が表示されることを確認する。
6. F-51F AP＋携帯回線で同じ短い一周を通す。Windows PCを運用経路へ代入しない。
   Chromeの前景・点灯、サーバ認証、携帯回線/APそれぞれの切断を分けて記録する。

英語リスニングの実音声・長時間運転は、この通常経路の確認後。電池、温度、ASR backlog、
光学的な可読性、即時消灯、反復着脱、150分は今回未検証で、目標値を実測値として記載しない。
LED外部監査は既存の利用者判断どおり追加要求しない。LEDへ介入せず、未観測を観測済みにしない。

## 送信不明時の復旧

Runs on: サーバと同じF-51F Termux／DATA_DIR。Windowsでの実行は部品検証だけ。

`python -m app.browser_guard status` でjournal状態とrequest_idを確認する。
秘密鍵や入力本文は出力されない。これはネットワーク要求を行わず、モデル送信もしない。
.envは自動では読まないため、必ずサーバと同じROKID_DATA_DIRを明示的に引き継ぐ。
別ディレクトリでidleだったことを解除済みの根拠にしない。

元のチャットを確認し、生成中なら待つ。回答が完成している場合は、対象資料・設問・入力版と対応を照合する。
既知の回答を取り込むか、その要求を中止するかを決めてから、該当request_idに対し
`python -m app.browser_guard acknowledge --request-id <確認したID> --confirm-reviewed` を実行する。
このコマンドは答案の取り込みや再送をしない。自動で全未完小問を再実行する前に対応関係を確認する。

journal破損、書込失敗、対象不明では削除せず保全して停止する。全ロックを無効化する設定や、
時間経過だけで不明要求を消す仕組みを足さない。利用制限・ログイン問題は別原因として確認する。

## 以前の改善案の採否・残作業

Runs on: 計画照合はWindows。物理採否は実グラス＋F-51F。既存RPタスクを継続し二重実装しない。

| 改善案 | 今回の状態／残る作業 |
|---|---|
| CIと主経路APK | 反映済み。最新runの成否と署名はPRを参照。物理導入は上記手順。 |
| 環境再現性 | phone API互換profileとWindows試験を反映。全依存freeze・端末再構築の実証は残る。 |
| 入力の同一性 | 内容SHAと音声互換を反映。文書作成の冪等キー・保存時ハッシュキャッシュは未実装。 |
| 解析ジョブ | 失敗理由とrevisionを反映。長時間HTTPの受付/進捗分離は未実装、RP-15と合わせて設計。 |
| ブラウザ | 排他・不明時再送停止・元返信除外を反映。実ChromeのDOM検証と受信済み結果の自動回収は残る。 |
| 撮影品質 | 既存の取り直し修正を維持。用紙輪郭とOCR文字枠の区別、誤解を招く表示、倍率比較はRP-09/10。 |
| 設問・選択肢 | 階層、原文記号、共通資料の対応はRP-12。既存の括弧選択肢の過分割は未修正。 |
| 閲覧・保存 | 追加取得とカーソル保存軽量化はRP-15/16/17。現状一回取得を完了扱いしない。 |
| 添付作成の再利用 | 送信重複防止は維持。再エンコードcacheは未実装。入力版が崩れない設計を先に固定。 |
| 評価 | 既存fixtureとRP-01/19を利用。PDF/画像で渡す情報差を統制し、合成試験を写真精度の証拠にしない。 |
| 起動・認証・音声 | 手順を本書へ反映。端末再起動/AP運用、原音保存ACKとASRの分離はRP-07/08/20。 |
| 構造・文書 | 再開入口・現行差分・残タスクを本書へ整理。main/Activityの大規模分割は短い一周の後。 |

今回の「PRへ反映」はこの修正群と引き継ぎを指し、RP-01～22全ての実装完了や実用完成を意味しない。
未実装を実機試験待ちへ書き換えない。短い一周が不成立なら該当箇所を直し、別機能を増やして埋めない。

## Windows再開実行（2026-09-16、実機試験継続中）

Runs on: ビルド・照合はWindows。実機はRG_glassesとF-51F上のFastAPI/CDP/Chrome。
今回は既存家庭内Wi-Fi経由であり、電話AP＋携帯回線の会場経路の検証ではない。

### ソース・自動試験

- 開始時 `git status --porcelain=v1 --untracked-files=all` は空。
  branch `feature/multimodal-scan`、origin `https://github.com/TroroOrosi/rokid-docscan-starter.git`。
  既存のignoredデータを保全し、fetch後に祖先関係と新規追跡パス衝突なしを確認。
  `git merge --ff-only origin/feature/multimodal-scan` → `Fast-forward`。
  `f4f1b1032fff746d502eee121a88ba52c45a7643` → `3e4b777fdbc71463c38659f4659f0d5974c275c4`。
  tree `08ea0ab8742d7ac8d7005f3e9cc7226e4cde918e`。製品コードは変更していない。
- 指定順で本書、CLAUDE.md、multimodal-scan進捗全文、plan現行部分、todo全文、
  [PR検証コメント](https://github.com/TroroOrosi/rokid-docscan-starter/pull/37#issuecomment-5692888458)を読んだ。
- Python 3.12.10、`ROKID_CHATGPT_LIVE=0`、一時データディレクトリで
  `py -3.12 -m pytest -q` → `631 passed, 1 skipped, 1 warning in 88.85s`。
  `py -3.12 -m ruff check .` → `All checks passed!`。`git diff --check` → exit 0。
- JDK 17.0.20.1+1、SDK Platform 36 rev2、Build Tools 36.0.0、Gradle wrapper 9.4.1。
  ASCII checkout `C:\rokid-docscan-starter` で
  `.\android-relay\gradlew.bat --no-daemon --rerun-tasks test testDebugUnitTest assembleDebug`
  → `BUILD SUCCESSFUL in 1m 37s`、199 executed、exit 0。
  再実行JUnit XMLは353件、failures/errors/skipped各0。
  glassinput32/pagequality18/glassdoc60/relaycore184/app47/glassapp6/glassprobe6。

### 原本保全と更新導入

Runs on: Windowsのadbから役割・実serialを確認した2端末。各コマンドで接続先を指定。
利用者の当初の更新導入・選択画面起動の承認範囲で実行した。

- glasses接続先 `192.168.0.4:5555`、実serial `1904092623381086`、
  build `1.25.015-20260903-150201`、API 32。
- F-51F接続先 `adb-ZY22LWGDCV-gAfvon._adb-tls-connect._tcp`、実serial `ZY22LWGDCV`、
  IP `192.168.0.30`、build `W1VHS36H.80-34-2-2-1-5` / incremental `64c964-a8f54`、API 36。
  Hi Rokid `G1.13.8.0828`、Chrome `153.0.8010.36`。CXR serviceは今回未再取得。
- ローカル証拠はignoredの `data/device-setup/pr37-windows-3e4b777-20260916-200352/`。
  `pr37-current-evidence-path.txt` がその絶対パスを指す。鍵・画像・OCR内容をGitへ入れない。
- 更新前にアプリ停止・camera clients空を確認。`exec-out run-as ... tar -cf - files no_backup shared_prefs`
  でprivate全体を `private-before-pr37.tar` へ保全（76,836,352 bytes、25 files）。
  SHA-256 `9c86e365a446ea88191d9ef964f5ab1a18230335149852325e328e04d1770b52`。
  7読取、11確定写真、pending 2件とmanifest・接続設定を保持。
- 既存APK・旧ビルド・過去backupも残した。旧導入APK SHA-256
  `29CFF4401AA1CC44B746B2B00FC5DDDC978F5BE5DD83ACAA947451E838AB0E3A`。
- `aapt2 dump badging` → package `dev.rokid.docscanglass.doc`、activity
  `dev.rokid.docscanglass.doc.DocScanGlassActivity`、versionCode 13、min 28 / target 36。
  `apksigner verify --verbose --print-certs` → `Verifies`、v2 true。
  旧導入APK・再ビルドAPKの証明書SHA-256はともに
  `906307478018e09e2937cfd8042a674d27598767577e08a304472aae407ccacc`。
  `Get-FileHash`で新APKと保存コピーが一致:
  `68813958166FF82DC79E079320A78CBB7D8E84D7C42719CC604197DA862740D3`。
- `$env:AGENT_APPROVED=1; adb -s 192.168.0.4:5555 install -r <照合済APK>` → `Success`。
  導入後のprivate 25/25ファイルhash一致。起動後もcapture 20/20一致。
  接続情報binの再暗号化のみ差分。起動は `am start -W` → `Status: ok`、選択画面をスクリーンショット確認。
  アンインストール、消去、無断stash、鍵変更、CI APK導入、main mergeはしていない。

### F-51Fサーバ・watcherの復旧

Runs on: F-51FのTermux。Chromeは利用者が前景へ戻した。PCサーバへの代替はしていない。

- 当初SSH拒否、旧server/watcher PIDは不在。利用者がTermuxでwake-lock/sshdを実行した。
  phone adbの `emulator-5554` は実serial `ZY22LWGDCV` を再確認。
  phone側 `forward tcp:9222 localabstract:chrome_devtools_remote` 後の `/json/version` → HTTP 200。
- 旧ログ `data/server-8cc1ad2.log` は3,021,080,685 bytesで保持。
  末尾64KiBにsocket.acceptの `OSError [Errno 22] Invalid argument` を92回観測。
  発生根因・再発条件は未解決。再起動だけを修正済みとしない。
- HEADのapp/scripts/phone requirementsをgit archiveしたtarのSHA-256:
  `2C333C5FC38071C99C0EABEED9D94104C114F14E866209C56C9788CE5C68F9C7`。
  phoneバックアップ:
  `/data/data/com.termux/files/home/rokid-backups/pre-pr37-3e4b777-20260916T112048Z`。
  旧app、env、requirements、scripts、SQLite整合backup、images/audio全17ファイルを保全。
  db.py同一、schema変更なし。モデル・巨大旧ログは元位置に保持。
- 更新スクリプト出力 → `imports_and_adapter_preflight=ok`、`health=200`、
  `db_rows_preserved=true`、`environment_unchanged=true`、`dependencies_unchanged=true`、
  `media_files_preserved=17`。新app 55ファイルがsource tarとbyte一致。
  documents8/pages11/exam_sessions1/questions1/solutions0の既存行数を保持。
- server PID 7903、`data/server-3e4b777.log`、`data/server-current.pid`。
  phone Python 3.14.6、fastapi0.99.1/pydantic1.10.26/uvicorn0.52.4等の既存依存は変更なし。
  保存envとprocess環境一致、認証付きsettings → HTTP 200。
  `python -m app.browser_guard status` → `{"schema":1,"state":"idle"}`。
  旧未完文書の解析を勝手に再送していない。
- 既存 `scripts/watch_glasses.py --serial 192.168.0.4:5555 --expected-serial 1904092623381086`
  を復旧、PID 7988。実ファイルSHA-256は
  `903c94dc39777cbac8fd3b6e7032093758dfc3a277e402f6498a7b75b0dd63fa` でHEADと一致。
  利用者が開閉後の選択画面復帰を1回確認（物理確認）。自動撮影開始は行わない。

### 実機の部分結果と現在の停止点

Runs on: 同じglasses＋F-51F、家庭内Wi-Fi。用紙・装着の準備は利用者が確認済み。

- 最初の「撮影失敗」報告時、camera2のJPEG返却9回を観測したが、OCRは0–4文字。
  保存画像を確認すると紙面が端に寄りPC/机が大部分。四辺・文字の読取は未成立。
  UUID `1fa209d0-9adb-4e92-8480-306db2f633f2` の確定P1とpending P2をtarで別途保全した。
  server未稼働で送信待ち、20:17:30にsystem force-stop。開閉復帰はwatcher復旧後に上記の確認。
- 20:24の試験で利用者は「P1のまま取り直せた、四辺も見えた」と確認。
  `adb ... logcat -d -v time -s DocScanGlassDoc` に
  20:24:20.551 review表示ACK → 20:24:22.533 SHORT_TAP → page index 0再撮影。
  約1.98秒の取り直しは物理確認。約2.5秒の端境界試験とは区別する。
- 利用者は「ダブルタップで終了できず撮影する」と報告。20:25:11以降にはBACKも到着し
  `Review last photo before finishing` に遷移する一方、3秒経過前のSHORT_TAPで再撮影へ戻る。
  入力の欠落・誤配送と断定せず、最終確認の表示/待ち時間と終了中の取り直し動作を調べる。
  ログは `retake-doubletap-report.log` に保全。試験を止め、テンプルを閉じたまま待つよう案内した。
  見開き/単頁の質問には「まずB5見開き、単頁は後に比較」と回答。
- B5比較、短い読取から答案表示、通信途絶復帰、AP経路、listeningは未確認。
  実装・自動試験の合格をこれらの実機合格へ書き換えない。
- 利用者の補足: 見えた四辺は冊子ではなく緑の枠だった。したがって上記の四辺表示の
  報告は紙面撮影の合格ではない。最後のpending画像は今回もPC中央・冊子が端だった。
  `7adf492d-7ae8-4d4c-9450-7ed4a29240f8` の原本/manifest/pendingを
  `retake-doubletap-session.tar`（11,959,296 bytes）へ保全。
  SHA-256 `03f15a30bb3e91cd25f384a4ccc13c27bab0d4cdeb0e3763458e4348914b62cb`。
  document 9、確定P1（OCR 0、ACK一致）、pending P2（OCR 7）、phase CAPTURE。
  phoneのread-only SQLite照合 → documents9/pages12、document9 open、solutions0。
  `/health` → 200、submission journalなし、新serverログ200bytes/Traceback0。
  今回の資料はChatGPTへまだ送られていない。
- `manualCaptureNow()` は最後の確認中の単タップで終了予約を解除する既存動作。
  最後の確認表示も通常の撮影確認と同じため、終了予約の状態は画面で分かりにくい。
  現在は変更せず、見開きを正面に置く→顔を紙面へ向ける→P1確認後にダブルタップ1回→
  手を離して5秒待つ、の短い再試験を利用者へ依頼中。緑の枠を紙面検出と扱わない。
- 本記録の追加後 `py -3.12 -m pytest -q tests/test_documentation_contract.py`
  → `14 passed in 0.82s`。製品コード変更なし。

### 着座ガイドの変更と送信確認の停止点

Runs on: 表示修正・自動試験はWindows。写真・入力・サーバ状態は上記家庭内Wi-Fiの実機。

- 20:34:47.442にP1確認を表示、20:34:49.124 BACK、20:34:50.628原本確定、
  20:34:50.635 `Local capture finished; analysis queued`。利用者も撮影停止・保存解析への遷移を確認。
  ダブルタップ1回の後に触らず待てば終了することを1回物理確認。入力割当・終了処理は変更していない。
- UUID `ccb68598-2d5e-4f20-b7b3-508d65a08a89`、document10/session2、1枚ACK済み、phase ANALYSIS。
  `spread-stop-session.tar` は5,958,144 bytes、SHA-256
  `982d4e6c39c0b1f2efe69b71ef1b3823105b7033fafde9bb329cdb9dd165cb40`。
  原本JPEGは5,953,586 bytes、4032×3024、rotation270、OCR49文字。
  サーバ正本 `data/images/10_0_080428c8.png` もWindowsへ保全し、見開き全体は写っていると確認。
  暗さ・文字の細部は未合格。単頁比較はまだ行っていない。
- 利用者は「緑の枠が小さく、着座で合わせられない」と申告。
  private XMLの限定読取 → `guide=1.0, spread=true`。最大の480×339の描画枠であっても
  実物の四辺に合わせる根拠がなかった。利用者は「小さな中央の目印＋紙面へ顔を向ける」を選択。
  HudViewの撮影前の括弧を中央の小さな十字と当該文言へ変更した。
  既存guide/spread設定、確認写真、カメラ寸法・向き・露出・retry・タップ操作は保持。
- 既存HudView描画試験へ「中央に目印、周囲に用紙形の枠なし」の回帰確認を追加。
  修正前 `:glassdoc:testDebugUnitTest --tests '*HudViewTest'`
  → `3 tests completed, 1 failed`（新規中央目印のassert）。
  修正後 `test testDebugUnitTest assembleDebug` → `BUILD SUCCESSFUL in 51s`、199 tasks。
  JUnit合計354件、failures/errors/skipped各0（glassdoc61、他は上記同数）。
  `py -3.12 -m pytest -q tests/test_documentation_contract.py` → `14 passed in 0.71s`、ruff → `All checks passed!`。
- 中央目印APKのaapt2は同じpackage/activity、versionCode13。
  apksigner → `Verifies`、v2 true、同じ既存証明書。
  `Get-FileHash` → `C08C5253FAD5D021DA94ABC26BDDF630D48CEECBE978D0F4773BA1B296A65A35`。
  この段階では未導入・光学表示未確認。新しいソース変更はHudView/HudViewTestと本書・runbookのみ。
- 答案は失敗: read-only DBにq2の `solve_failure.code=solver_failed`、solutions0。
  正しいBearer認証でGET answer-bundle → HTTP200、1項目 `status=failed, answer_chars=0`。
  以前のX-API-Key付きsettings HTTP200は公開設定への到達であり、認証成功の証拠ではない。
  protected endpointはAuthorization Bearerを使う。鍵そのものは出力・変更していない。
- phone側source_bundle準備の部分試験は成功（document.md 443 bytes、page001.png 14,808,685 bytes）。
  Chrome CDP接続は0.088秒、ログイン済みcomposerも確認。新しい空のチャットの準備は3.15秒。
  元の失敗原因はまだ特定していない。新serverログにtracebackはない。F-51F ChromeはAwake/前景。
- 部分試験の `attach_images` は `False, 15.8秒`、DOMにdocument.mdあり、画像なしを観測したが、
  **利用者がGPTチャットに付いた画像を削除したと申告したため、添付失敗との因果判断を撤回**。
  その部分試験は添付だけで質問文・送信ボタンの操作はしていない。
  利用者は送信の有無は分からないとのこと。入力欄の添付か、履歴の画像かを確認中。
  ここからは再送・新規チャットへの移動・削除を止め、元の送信状態を確認する。
  submission.jsonは存在せず、アプリ経由の送信予約/完了journalはない。
  ただし手動操作の有無はこのjournalだけで断定しない。ブラウザ側ソースは一切変更していない。

### 中央目印の導入と添付件数の現物照合

Runs on: APK導入はWindows → 同じ実グラス。添付条件の設定はF-51Fの既存Termuxサーバ。

- 中央目印のソースは `aabad555d15a41caea0658f2ab85bd0f7919d410` でcommit/push済み。
  `git push origin HEAD:feature/multimodal-scan` → `3e4b777..aabad55`。mainは触っていない。
- 更新前のfull private tarは最初50秒でtimeout（部分ファイル98,113,536 bytesも保持）。
  新しい名前で時間枠を広げ、`private-before-center-mark-complete.tar` の読み出しを完了。
  106,981,376 bytes、33 files、SHA-256
  `b6fdf7682e9adecb27c727c15bc0b5d8850313bea2a1427161ff19b90f067545`。
  全ファイルのhash一覧を `private-before-center-mark-hashes.json` に保存。
- 再列挙、実serial一致、camera clients `[]`、停止済み、installed versionCode13を確認。
  `$env:AGENT_APPROVED=1; adb -s 192.168.0.4:5555 install -r <glassdoc-center-mark.apk>` → `Success`。
  `sha256sum`照合 → `after_center_install_private_identical 33`。
  開閉後の選択画面復帰を利用者が確認。中央目印自体の光学確認はまだ。
- 利用者は消した画像が「下の入力欄の添付」だったと回答。履歴の発言の削除ではない。
  直近の部分試験で送信操作はしていない。元アプリのsubmission.jsonも存在しない。
  続く確認は共有BrowserGuardを保持し、空のtask chat・user messages0を確認して添付だけを実行。
- 画像単独の再添付 → 9.88秒、従来selector count1、user messages0。
  文章を追加後、画面の削除ボタンに `page001.png` と `document.md` がそれぞれ存在。
  それでも旧 `form img, [data-testid*="attachment"]` は1件。
  **文章ファイルのカードを旧確認条件が数えない**ことを、利用者操作がない状態で再現した。
  画像添付そのものの失敗という前の仮説とは区別する。
- 実ChromeのDOMで `form button[aria-label^="ファイル "][aria-label*=" を削除"]`
  →2件、送信ボタン有効、user messages0。`assert count == 2` → `attachment_dom_check=passed`。
  設定用の既存 `ROKID_CHATGPT_ATTACHMENT_SEL` にこの条件を入れた。
  日本語Chromeの今回のDOMに対する測定で、他言語・他版の保証ではない。
  Pythonソース・依存・鍵・写真・再試行回数は変えていない。
- env変更前backup:
  `/data/data/com.termux/files/home/rokid-backups/attachment-selector-20260916T120200Z/multimodal.env`。
  空の送信journal・solution claims0・旧PIDのcmdlineを確認し、旧serverを通常終了して再起動。
  新PID **21172**、`data/server-3e4b777-attachments.log`、`data/server-current.pid`。
  出力 → health200、変更envキーは上記1個、credentials/source unchanged。
  watcher PID7988はそのまま。appのソースは引き続き3e4b777。
- 次はグラスの「中断した読取」→「9/16 20:35 通常 1枚」でdocument10/session2を
  利用者操作により再開するよう依頼中。今回の同じ資料の送信状態を照合してからの1回であり、
  過去の全未完読取を一括再送しない。新規撮影・単頁比較・答案の物理確認はまだ。

### 保存済み解析の再開結果と紙面品質の再申告

Runs on: F-51Fとグラス、同じ家庭内Wi-Fi。会場のphone AP経路の合格ではない。

- 利用者が20:35の記録を選択。`adb -s 192.168.0.4:5555 logcat -d -v time -s DocScanGlassDoc`
  → 21:05:20.390 `FINALIZING: Resumed saved analysis`、21:08:39.055
  `REVIEW: Local session analysis finished`。後者は処理終了を表し、答案成功ではない。
- read-only SQLite → question2のsolutions0、solution_claims0、solve_failures2、
  `solve_failure.code=browser_outcome_unknown`。Bearer GET
  `http://192.168.0.30:8000/v1/exam-sessions/2/answer-bundle` → HTTP200、1項目status failed、answer空。
  serverはこのLANアドレスにbindしており、127.0.0.1:8000への拒否はserver停止を意味しない。
- `adb -s 192.168.0.4:5555 exec-out screencap -p` の画像は
  「解析できません／送信結果の確認待ち。」。`glasses-current.png` と
  `resumed-analysis-glasses.log` を既存のignored evidence directoryへ保全した。
- submission.jsonはstate uncertain、request_id
  `3894a56d08253c7d1c6d9785496a0b92cebe046d8f4579f1feb92fdd39fd00f0`。
  初回の送信処理中はclaim1、終了後は0。自動再送・journalのacknowledge/削除は行っていない。
  添付確認を通って送信予約まで進んだことと、送信・回答完了は区別する。
- 元のtask tabのNavigationHistoryには会話パス候補が1件あった。BrowserGuardを保持し、
  現composer空・添付0を確認して当該会話だけを開いたが、読み込み後はトップへ戻り、
  user/assistant turnはいずれも0。これで「未送信」「削除済み」とは断定しない。
  CDP Network.responseReceived → document HTTP200、当該conversation API HTTP404。
  今回の送信先との同一性も確定できず、journalを保留したままにする。
- 利用者が「画像が暗く、紙面の面積が小さく、広く撮りすぎ」と申告。
  `spread-server-normalized.png` の現物でも、見開きが下寄りで、机と周囲が大きく写ることを確認。
  原本JPEGのPillow EXIF読取 → 4032×3024、ExposureTime 0.008333333、FNumber2.25、
  ISO60、ExposureBias0.0、FocalLength1.9。暗さの原因まではこの値だけで断定しない。
- GlassCamera現ソースは最大JPEGでTEMPLATE_STILL_CAPTUREを1回要求し、JPEG_ORIENTATION以外の
  設定変更はない。中央目印は撮影範囲・露出を変えていない。今回も未変更。
  過去の露出変更timeoutのコメントを、現firmwareでの制御不可能という一般論へ広げない。
- 利用者は現在「大問を選択」と回答し、着座したまま冊子を近づける/持ち上げることは可能と回答。
  同じB5見開きを約40cm目安で顔へ近づけ、紙面へ正面から顔を向け、影を避けて撮る比較を依頼。
  開閉→通常読取→P1確認後ダブルタップ1回→5秒触らず、の既存操作。
  今回は写真品質の部分試験であり、解析の確認待ちでも再開を選ばないよう案内した。
  BrowserGuardの送信停止は保持。紙面の読みやすさ、単頁比較、実答案表示はまだ未合格。
- 本追記後 `py -3.12 -m pytest -q tests/test_documentation_contract.py`
  → `14 passed in 1.01s`、`git diff --check` → exit0（既存設定によるLF/CRLF警告のみ）。

### 近づけた見開きの比較（1回）

Runs on: 同じグラス・F-51F、家庭内Wi-Fi。写真品質の部分試験。

- 利用者は「大きく写り、四辺と文字が見えた」と回答。これは確認画面の光学的な見やすさの申告。
  保存原本を見て、文字認識・答案品質まで合格したとは扱わない。
- `adb -s 192.168.0.4:5555 logcat -d -v time -s DocScanGlassDoc` →
  21:17:31.744 review ACK、21:17:34.209 BACK、21:17:36.136 local commit、
  21:17:36.144 FINALIZING、21:17:53.969 REVIEW。今回は終了操作後に追加タップなし。
- UUID `6239deec-faf0-473c-b6c4-9ff1f55c8fd5`、document11/session3、P1 ACK済み。
  read-only tar → `spread-raised-session.tar` 5,847,040 bytes、SHA-256
  `939dfb70eb57a8a47b6ddf45cca8103e3c3c9e50737d551b89e74a5c1d9c8937`。
  サーバ正本 `data/images/11_0_7e5881cb.png` を `spread-raised-normalized.png` として保全。
  全体の原本では、紙面の四辺はあるが、まだ周囲が大きく暗い。OCRは6文字。
- read-only DB → question3 solve_failure.code browser_outcome_unknown、solutions0。
  submission.jsonは同じuncertain barrierを保持し、解析を再送していない。
  次は同冊子の片側1頁を約30cm目安で撮り、既存の操作で終了する比較を利用者へ依頼中。

### 単頁比較と送信確認の利用者訂正

Runs on: 同じ実機・家庭内Wi-Fi。撮影比較のみで、実答案試験ではない。

- 利用者は単頁についても「文字が大きく、四辺も見えた」と回答。
  サーバ正本 `data/images/12_0_e3f57cd8.png` を `single-page-normalized.png` として保全。
  原本で右側の単頁の四辺を確認。隣頁も一部写っており、右側だけへ自動cropした画像ではない。
  暗さは残り、OCR3文字なので、読取品質は合格としていない。
- UUID `9b0f1286-9385-485f-942b-82413181e9ec`、document12/session4、P1 ACK済み。
  read-only tar → `single-page-session.tar` 5,948,928 bytes、SHA-256
  `d77befd067021dd29179a6bf9a0f8468d7c39c8463c9b81037dd211058e861b0`。
  manifestのbin名のSHA-256と内容を照合し、既存DSCP v3形式からJPEGを別ファイルへ読み出した。
  5,944,677 bytes、rotation270、ExposureTime0.008333333、ISO60。原本の変更なし。
- `single-page-logcat.log` に、OCR0で確認写真を出せず再試行する区間がある。
  21:22:26.785 review ACK、21:22:29.821 BACK、21:22:31.181 local commit、
  21:22:31.189 FINALIZING、manifest更新21:22:47にREVIEW。
  認識が安定せず確認写真まで待たされる点は未解決。撮影寸法・retry・露出は変更していない。
- read-only submission.json → 同じrequest_id/state uncertain。
  近づけた見開き・単頁試験の間も、元の送信結果不明の記録を上書きしていない。
- 利用者が**20:35記録の解析再開後にも「画像または会話を削除した」**と回答。
  21:05の送信結果不明を、利用者の操作がない条件で再現したアプリ不具合とは扱わない。
  入力欄の添付だけ／送信済み発言／会話自体のどれだったかを確認中。
  削除対象を確認するまでjournalは保留し、追加の削除・送信を依頼しない。
- 実答案試験に向け、同冊子の設問・選択肢ページを準備できるか利用者へ確認中。
  ここまでの写真は本文ページであり、解答に必要な設問がそろったという証拠はない。

### 会話削除の照合後、次の短い答案試験を準備

Runs on: F-51Fの既存サーバ。次の撮影は同じグラス・家庭内Wi-Fi。

- 利用者は解析再開後に削除したのが「チャットの会話自体」と回答。
  既知の履歴候補へのHTTP404と併せ、当該結果を回収できない状態として照合した。
  削除時刻と180秒待機終了の前後関係までは分からず、timeoutの全原因とは断定しない。
- BrowserGuard lock下で同じrequest_id・uncertain、solution_claims0を確認。
  journalのbyte一致backupとSQLite consistent backupを
  `~/rokid-backups/deleted-chat-reconciliation-20260916T122746Z` へ保存。
  journal backup SHA-256
  `4c442a359ce4df1e2d5d1b2926dec7a463cf6a0c84095cb27958fac57d8fc5dc`。
  利用者の削除対象の確認後、既存 `BrowserGuard.acknowledge(request_id)` を実行し、
  出力 → `state_after {schema: 1, state: idle}`。原本・過去のfailed記録はそのまま。
  これは結果の照合による送信停止解除であり、答案成功への書き換えではない。
- 利用者は同じ冊子の設問ページを準備可能と回答。本文と問1〜2の設問・全選択肢が
  そろうページ番号を確認中。次の試験はその紙面だけとし、過去の未完記録をまとめて再送しない。
  今回は答案がグラスへ戻るまで、スマホのChatGPT・添付・会話を操作せず残すよう説明した。

### 現在の停止点

Runs on: 次の実答案試験はグラス → F-51F → 同じF-51F Chrome。家庭内Wi-Fiの部分試験。

- ページ番号の問いに利用者は「ない」と回答。「設問・選択肢のページが手元にない」か、
  「設問はあるがページ番号が分からない」かを確認中。新規撮影・解析は開始していない。
  後者ならページ番号の申告を必須にせず、設問と対応する本文の現物から短い試験範囲を決める。
  前者なら実答案試験は必要な紙面が用意できるまで未実施として残す。
- 同じグラスのread-only `pm path dev.rokid.docscanglass.doc` で導入先を特定し、
  `sha256sum <installed base.apk>` →
  `c08c5253fad5d021da94abc26bddf630d48ceecbe978d0f4773ba1b296a65a35`。
  検査済み既存署名の中央目印APKと一致。`dumpsys media.camera` → `Active Camera Clients: []`。
- `gh pr checks 37 --repo TroroOrosi/rokid-docscan-starter` → build、lint、source-snapshot、
  phone-stack-compatibility、Python各版、windows-predeviceはいずれもpass（4a9e218時点）。
  これらを実機の読取品質・答案表示の合格には数えない。
- 本追記前の同一製品ソースで `py -3.12 -m pytest -q tests/test_documentation_contract.py`
  → `14 passed in 0.80s`、`py -3.12 -m ruff check .` → `All checks passed!`、
  `git diff --check` → exit0。追加実装なし。

### 次の試験範囲の確定

Runs on: 同じグラス → F-51Fサーバ → F-51F Chrome。家庭内Wi-Fi。

- 「ない」は資料欠如と確定した返答ではなく、撮影対象の説明が伝わっていなかった。
  「問題文と選択肢の全文が載っているページ」を撮る意味だと説明し直した。
  利用者は**その1ページに問題文と全選択肢がそろっている問題**を準備可能と回答。
  ページ番号の申告は不要とし、当該1ページだけで短い答案試験を行うことにした。
- 開閉→通常読取→P1確認後ダブルタップ1回→以後操作せず保存解析を待つ、を依頼中。
  今回は送信停止解除後の新しい試験。スマホのChatGPT・添付・会話を操作せず残すよう説明済み。
  元の不明送信や本文のみの過去セッションを自動再解析するものではない。

### 実機試験を停止：LOW_MEMORYと表示の再指摘

Runs on: 終了原因の読取は同じグラス。以後の修正・検証はWindowsのみ。

- 利用者から「アプリが終了」「全体表示が邪魔」「撮影範囲が広すぎる」「傾き」「少し暗いと
  見えない」と再申告。未整備の状態で実機操作を繰り返し依頼し、時間と使用量を消費したとの指摘。
  **実機試験・ChatGPT送信を停止した。追加の撮影依頼や実機への更新導入を行わない。**
  保存済み写真による事前検証を先に行い、現状を実機試験の準備完了と扱わない。
- `dumpsys activity exit-info dev.rokid.docscanglass.doc` →
  21:36:01.045、PID19153、`reason=3 (LOW_MEMORY)`、PSS215MB、RSS255MB、importance100。
  直前の21:35:59.736には撮影要求があり、画像callbackの前にprocessが終了した。
  その後のread-only確認ではspread0、processなし、camera clients `[]`。
  今回の終了原因は開閉やダブルタップの操作失敗とは扱わない。
- 新しい試験のUUID `1beccff9-0219-4e84-805d-427a02827316` はdocument0/session0/count0、
  phase CAPTURE。P1取り直し前のpendingが残っており、解析・送信には到達していない。
  `question-page-interrupted.tar` → 5,933,056 bytes、SHA-256
  `83de637273454169dd5f2ccc24c096d5c908a841d1b72978d3193977587ff15d`。
  pending JPEGは5,929,690 bytes、rotation270、OCR0文字。
  `question-page-pending.jpg` と `question-page-interrupted.log` を既存ignored evidenceへ保全。
- 原本には設問の紙面が写るが、暗さ・周囲の広さが残り、ケーブルが紙面にかかる。
  これを認識・答案試験に適した原本とは扱わない。追加撮影で取り繕わない。
- 現ソースで、確認用Bitmapは次のaiming/statusでもSurfaceに保持され、2016pxまで復号していた。
  「全体」小窓は主画像へ重ね描きされる。回帰試験を先に追加し、
  最初の対象試験 → 4 tests / 2 failed（重なり・画像未解放）。
  全画面表示・復号上限の条件を含めた修正前試験 → 4 tests / 3 failed。
- ローカル修正: 原本全体を1枚で表示し、中央2倍の切抜き・全体小窓・画像上のラベルを除去。
  表示用復号を長辺1280px以内とし、4032px原本では1008pxへ縮小する。
  次のaiming/statusを描いた時点で、前の確認Bitmapを解放する。
  原本JPEG・カメラの撮影寸法・露出・回転・retry・入力割当は変更していない。
  **画像の重なりと保持を修正しただけで、LOW_MEMORYの全原因・撮影品質の解消は未証明。**
- `test testDebugUnitTest assembleDebug` → `BUILD SUCCESSFUL in 53s`、199 tasks、7 executed。
  JUnit合計355件、failures/errors/skipped0（glassdoc62、他は上記同数）。
  `py -3.12 -m pytest -q tests/test_documentation_contract.py` → `14 passed in 1.29s`、
  ruff → `All checks passed!`、diff check → exit0。
- `glassdoc-fullframe-review.apk` を既存evidence directoryへ別名で保全。
  aapt2 → 同じpackage/activity、versionCode13。apksigner → `Verifies`、同じ既存証明書。
  SHA-256 → `95968CEF6C5389D40BD16B9B4577FD89BB0CD9E9ED2CE3A7B32C38EB4E1CD5F4`。
  **このAPKは未導入。実機は前のC08C5253…のAPKのまま。**
- 保存済みの単頁・設問JPEGをWindowsのRobolectric native Canvasで実際のSurface/HudViewへ通した。
  ignored evidence内の単発render用testとinit scriptを使用し、実機・ChatGPTは使っていない。
  `:glassdoc:testDebugUnitTest --tests '*OfflineReviewRenderTest'`（`--init-script` 指定）
  → `BUILD SUCCESSFUL in 39s`、1 test / failures0。
  両画像とも `decoded=756x1008 allocation=1524096` bytes。これはWindows上のBitmap測定で、
  グラスprocessのPSS/RSS測定ではない。
  `single-page-0-offline-hud.png` と `question-page-pending-offline-hud.png` を目視確認し、
  全体小窓・ラベルの重なりがなく、元画像が1枚で収まることを確認した。
- 全体表示では原本中の紙面の小ささもそのまま見える。紙面を大きく撮ること、低照度での文字品質、
  視点による傾き、camera/OCR/表示を含む全processのメモリ不足は**未解決**。
  このローカル変更を、それらの合格や実機試験再開の根拠にしない。
- 次の作業は、保存済み実写真で紙面の範囲・傾き・明暗と文字認識を検証すること、および
  camera/OCR/表示の同時保持を含むメモリ予算の確認。利用者に再撮影を繰り返してもらう進め方は停止。
  問題文・選択肢からの答案表示、phone AP経路、長時間・リスニングの実機合格は依然として未了。

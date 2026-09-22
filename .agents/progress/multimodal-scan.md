# 手動併用スキャン・省電力・OCR/画像/音声/図

Status: Internal progress。計画の認識合わせ後、利用者が追加実装・実機操作を依頼。RP実装を開始。
Runs on: Windowsで実装・試験。運用先はglassdocとスマホAP/FastAPI/Chrome。

## 実機前修正の追補（2026-09-16）

Runs on: 今回は隔離Linux環境とGitHub Actions。端末への適用は未実施。

PR37へサーバ入力版・ブラウザ排他・送信不明時の再送停止・回帰試験を追加する。
現在の差分とWindowsでの再開手順は [PR37引き継ぎ](pr37-predevice-handoff.md) を先に確認する。
以下の停止記録、原本保全、実機の照合条件を変更せず維持する。

## 再開地点 — 利用者の依頼で保存・停止（2026-09-16）

Runs on: 今回の修正・最終gate・APK保全はWindows。修正版の実機適用は再開後に行う。

利用者は「P1を撮りなおしタップを行ってもP2に行く」と報告。ずれの意味は
「用紙が斜めに傾いて写る」と明確化した。その後「キリがいいところで保存して停止し、
再開時に実機確認できるように」と指示したため、撮影・モデル送信・実機適用を進めず停止する。
**再開前に実機試験を自動で始めない。** この節が下記の過去の次工程より優先する。

### 保存する修正と根拠

Runs on: Windowsの実装とRobolectric、原因の一次ログは§Lの実グラス。

- f8ce0faは前節記録後に同じグラスへ導入済み。270度・中央2倍・見開き初期値を反映。
  旧4件のmanifest byte一致、導入Success、起動Status okを確認済み。今回の修正版は未導入。
- 単タップの物理開始NOTIFICATIONは確認表示から2485ms、確定ENTERは3003msだった。
  3秒タイマーが先行し、実行時の次ページへタップを適用していた。過去のP1→P2も同じ経路（§L）。
- 新修正は開始時刻と確認世代を結び、期限内に始まった入力の分類待ちだけ既存の実測970msまで
  保存を保留する。確定済みでserial実行待ちの取り直しも優先。期限後・旧世代は次写真へ流さない。
  明示取り直しで旧windowを退役させ、直後の新しい撮影タップが古い期限に捕まらないようにした。
- 物理確認は未実施。取得イベント自体がlocal保存後まで届かない場合の元写真再取得など、
  RP-09全項目が終わったとは扱わない。単タップ／ダブルタップの割当、無操作3秒、カメラ寸法・露出・retryは維持。
- 実ログ再現testはP1期待0／実際1で `1 test completed, 1 failed` → 修正後 `BUILD SUCCESSFUL in 25s`。
  独立レビューの「早い取り直し直後の次タップ」も `expected STABILIZING but was AIMING` でREDを確認して修正。
- 最終 `./android-relay/gradlew.bat --no-daemon test testDebugUnitTest assembleDebug`
  → `BUILD SUCCESSFUL in 51s`、199 tasks。上記レビュー修正と版更新を含む。
  ASCII root `C:/rokid-docscan-starter`、JDK17.0.20.1+1／SDK Platform36 rev2／Gradle9.4.1。
- `py -3.12 -m pytest -q tests/test_documentation_contract.py tests/test_versioning.py tests/test_rokid_led.py tests/test_watch_glasses.py`
  → `26 passed in 0.93s`。`py -3.12 -m ruff check .` → `All checks passed!`。`git diff --check` → exit0。
- `aapt2 dump badging` → `dev.rokid.docscanglass.doc`、`DocScanGlassActivity`、versionCode13、target36。
  `apksigner verify --verbose --print-certs` → `Verifies`／v2=true、証明書SHA-256は
  `906307478018e09e2937cfd8042a674d27598767577e08a304472aae407ccacc`、§Kと同じ。
- 次回用APK: `data/device-setup/glassdoc-retake-review-20260916.apk`。
  build出力と保全コピーを `Get-FileHash -Algorithm SHA256` で照合し、両方
  `F8FEFBD15FF05D4E378715AA6061EA35585729472458E9D68793F55D4FEB9EC4`。
  private data tarのSHA-256は `DCF08B583B5403B3B2C15ABC7B90074B1552E68A2F38D1FB360813E553961E78`。
- 対象rootは `C:/rokid-docscan-starter`、branchは `feature/multimodal-scan`、
  originは `https://github.com/TroroOrosi/rokid-docscan-starter.git`。
  このチェックポイントの変更はController／Activity／LocalReviewTest、版、runbook／測定／進捗に限定。
  APKと私的原本はローカル保全のみ。実機はf8ce0fa、F-51F appは8cc1ad2のまま。

### 未解決の実画像

Runs on: 既存Wi-Fiのglassdoc → F-51F。AP・携帯回線セッションの測定ではない。

- 同じ見開きを繰り返した写真があり、**単頁と見開きの比較はまだ行っていない**。
  doc6の2枚はOCR 78／0文字、doc7は6文字、doc8は0／38文字。新しいrotation=270を保存済み。
  少し近い姿勢、確認画面の光学可読性、ブレの判別、解答精度も未確認。
- 保存画像で上下の辺が平行にならない形も見える。一律の角度補正を入れて解決扱いしない。
  台形歪み・湾曲・文字の小ささ・暗さ・OCR復号倍率は未切分け。斜め補正コードは追加していない。
  Google ML Kit docsはContext7で `/websites/developers_google_ml-kit` を特定しただけで本文未取得。
- 原本は端末に保持。Windowsにも `data/device-setup/before-retake-prefix-local-scans.tar` を保全。
  document2～8の7読取、確定写真11枚とpendingを含む。doc2/6はANALYSIS、他はCAPTURE。
  このtarから抽出した `latest-doc-{6,7,8}-page-*.jpg`、`retake-report-live.log` と
  `after-visibility-bde4f09.log` はGit対象外のまま。OCR本文・画像をコミットしない。

### 再開時の順序

Runs on: 1はWindows／グラス、2～4はグラスとF-51F。会場経路の検証はその後のAP試験。

1. `feature/multimodal-scan` のこの記録・現diffと検査済みAPKを照合。実機をread-onlyで列挙し、
   グラス本体serial `1904092623381086`、F-51F `ZY22LWGDCV` を確認。IPは変わり得る。
   同一実機への通常のAPK適用・起動は既に承認済み。UNKNOWN撮影や別機種なら進めない。
   最終APKと既存署名、旧f8ce0fa APK hashを照合し、原本を保全して更新する。
2. 選択画面で待機。用紙と利用者の準備を確認してから通常読取を開始する。
   実画像表示の2.5～2.9秒付近に単タップし、P1がP1のまま取り直すことをログと見え方の両方で確認。
   早い取り直し直後のタップ、無操作の確定、期限後入力、最後の1枚も続けて確認する。
3. **同じB5冊子の見開き→片側1ページ**を実際に撮り分ける。傾き・欠け・ブレ・OCR・最終解答を比較する。
   まだ比較画像がないことを忘れず、見開き2枚の反復を比較完了として扱わない。
   手元の原本へ保存済み画像から原因を切り分け、撮り直しや露出変更を闇雲に重ねない。
4. F-51F側はapp `8cc1ad2` のまま。CDPは直前 `/json/version` 200でChrome前景だったが、
   解析結果は未取得。doc6等のupload/ACK・未完解析を確認してから同じ資料の解答確認を再開する。
   watcherはF-51Fの `~/rokid-server/scripts/watch_glasses.py`、PID/logは `data/watch-glasses.*`。
   閉→開で選択に戻る1回は利用者確認済み。今回停止依頼で常設server/watcher設定は変更していない。

実英語音声の試験は利用者指定どおり後回し。RP残件全体は `tasks/todo.md` を維持する。
選択skillは Agent Skills spine／diagnosing-bugs、固定点レビューとprogress-checkpoint。

## 直前の現在地 — 見開き・確認写真・開閉復帰（2026-09-16）

Runs on: 実装/build/描画QAはWindows。watcherはF-51F Termux、グラスは既存Wi-Fi接続。

bde4f09を導入して設定復号と保存原本維持を確認後、利用者は「枠は改善、確認写真は小さい」
「角度が違う」「単頁／見開き比較がまだ」「閉じて開いてもホーム」と申告。
F-51Fの既存adbから閉→開時にchooserを一度起動するscriptを追加し、利用者が物理開閉で
「選択画面に戻った」と確認した。スマホで稼働中。撮影・原音は自動開始しない。
通信断中に閉状態を見逃す開閉は未対応。AP・着脱だけ・CLOSED後・50回・時刻目標は未検証（§K）。

実保存JPEGのAndroid native描画で270度が正立、旧180度が横向きと確認。
新規撮影のOCR／確認表示／server PNGへ同じ270度を渡し、旧pendingは書き換えない。
中央2倍＋右下全体像、RGB_565の2016px復号で細部を残す。原本・カメラ寸法／露出／retry・3秒・ジェスチャは維持。
利用者の最新指定で見開きを初期値にし、「B5 見開き」と横幅最大の枠を表示。
近づける距離、光学表示のブレ判別、単頁／見開き精度はこれから実写で確認する。

- Hud拡大試験 RED `1 test completed, 1 failed` → 既存込み `BUILD SUCCESSFUL in 33s`。
- 一時実写真QA `BUILD SUCCESSFUL in 28s`。一時テストを除去し、一般のHudViewTestを残した。
- watcher境界 RED `1 failed, 1 passed` → `2 passed in 0.03s`。
- 全Android `test testDebugUnitTest assembleDebug` → `BUILD SUCCESSFUL in 54s`、199 tasks。
- 見開き初期値・ラベル後 `:glassdoc:testDebugUnitTest :glassdoc:assembleDebug` → `BUILD SUCCESSFUL in 50s`、63 tasks。
- Python watcher/doc/version/LED → `26 passed in 1.09s`、Ruff → `All checks passed!`。
- APK identity／署名／hashはhardware-measurements §K。旧APK hash一致と保存4件の退避を確認。
- 独立レビューで起動応答UNKNOWNの繰返しを修正。通信断中の開閉欠落は制限を明記。
  Hud／向き／復号のRequired所見はない。光学可読性・OCR精度の合格ではない。

この節の後、f8ce0fa APKの導入と見開き設定の反映を実施済み。上の再開地点を参照。
同じB5紙面の見開き→単頁比較は未実施。実英語音声は後回し。phone appは8cc1ad2。
RP-09以降を今回の表示修正で完了扱いしない。下記は直前の履歴で、上記を優先する。

## 直前の不具合対応（2026-09-16）

Runs on: Windowsの実装・自動試験。実機ログはグラス、サーバはF-51Fの既存Wi-Fi経路。

利用者の「停止」で撮影比較を止め、その後の「取消後の読み込み待ち」「小さい枠で着座撮影できない」
「折りたたみ後に選択へ戻れない」「確認写真も見づらい」の申告を優先して修正している。
ジェスチャは利用者へ再質問せずログで確認した。保存の直後のBACKで撮影終了へ移っており、
期限内の単タップ取消は観測されなかった。紙面比較の新たな撮影・解答送信は再開していない。

- 認証とサーバの更新は承認後に実施済み。旧記述の「鍵生成待ち」は解消。phoneのappは8cc1ad2。
- 解析待ちのBACKに終了確認と画面復帰を追加。最初の操作で解析のwake lockは保持し、
  3秒以内の第2BACKで既存の保存・終了処理へ進む。終了後の結果通知で答案は再表示しない。
- B5単頁ガイドは表示へ直接合わせる。255×360を作っていたセンサー比率の制限と、
  光学校正済みと誤解させる外枠・面積推定を削除。表示倍率の校正値は引き続き設定できる。
- 確認写真の明暗をグラス表示だけで緑色へ拡げ、操作案内は下端へ小さく移動。
  原本JPEG・OCR・送信PNG、カメラ寸法・露出・retry、3秒の確認期間は変えていない。
- 再現: 対象Activity/FramingGuide試験 → `4 tests completed, 2 failed`、
  HudView描画試験 → `1 test completed, 1 failed`。修正後のglassdoc全単体試験 →
  `BUILD SUCCESSFUL in 47s`。操作案内を下端へ移した後のHudView/実写真描画 → `BUILD SUCCESSFUL in 32s`。
- 実写真の描画QAは保存JPEGを既存decodePreview(rotation=180)とHudViewへ渡して実行。
  `android-relay/glassdoc/build/outputs/reported-photo-{review,guide}.png`を確認。
  私的画像を読む一時テストは除去し、一般化したHudView回帰試験だけを残す。
- 実機ホームのアプリ一覧からDocScan Glassesを起動し、選択画面に戻る経路を確認。
  測定とログ時刻はhardware-measurements §J。再装着だけでの自動起動は未実装。

- 独立レビューの必須所見は描画のright/bottom境界だけ。native試験で`1 test completed, 1 failed`を再現し、
  描画座標だけ1px内側へ補正した。ほかのRequired/Critical所見はない。
- `./android-relay/gradlew --no-daemon test testDebugUnitTest assembleDebug` →
  `BUILD SUCCESSFUL in 1m 5s`、199 tasks。境界修正後の
  `./android-relay/gradlew --no-daemon :glassdoc:testDebugUnitTest :glassdoc:assembleDebug` →
  `BUILD SUCCESSFUL in 48s`、63 tasks。
- `py -3.12 -m pytest -q tests/test_documentation_contract.py tests/test_versioning.py tests/test_rokid_led.py`
  → `24 passed in 1.34s`。`py -3.12 -m ruff check .` → `All checks passed!`。
- ASCII checkout `C:/rokid-docscan-starter`、JDK17.0.20.1+1／SDK Platform36 rev2／Gradle9.4.1。
  `aapt2 dump badging` → `dev.rokid.docscanglass.doc`、DocScanGlassActivity、versionCode11。
  `apksigner verify --verbose --print-certs` → `Verifies`、v2=true、既存証明書と一致。
  `Get-FileHash` → `8DBBE3702744FABA03C7456AB8439D6C81615DE61FDE446142E389D7452301C3`。
- 導入前の実機APKを`sha256sum`で再照合し§IのAPKと一致。カメラは`Active Camera Clients: []`。
  保存読取はdocument2／session1／count1／ANALYSISのまま。

次は承認済みのグラスへこのAPKを反映し、選択画面・設定復号・保存資料の維持を確認する。
着座位置の画角校正、光学表示での写真可読性、B5単頁／見開きの精度比較は未検証。
RP-09以降の残件を今回の表示修正で完了と扱わない。英語実音声試験は引き続き後回し。

## 追加実装の開始（2026-09-15）

Runs on: 実装・回帰試験はWindows。実機操作は同一性を確認したグラスとF-51F。

利用者が「追加実装・実機操作を行ってください」と明示したため、下の認識合わせ待ちは解消した。
基準は `ed708b4`、branchは `feature/multimodal-scan`。RP計画の採用範囲を実装する。
物理試験の用紙は準備可能。追加指示で英語リスニングの実音声試験は後回しになった。
今回は用紙の撮影から答案表示までを優先し、録音側は実装と自動試験を進める。
実音声の再生／収録／モデル送信はその後に行う。撮影開始のタイミングを事前に伝える。
追加指定で、自動スキャンの用紙はB5。他サイズは手動撮影で扱う。利用者は見開き2ページの同時撮影を希望し、
その後「従来は1ページずつ。見開きで精度に問題がないか」と確認した。同じ紙面の単頁／見開き比較で
細字・数式・綴じ目・左右の設問順・最終正答と時間を測り、既定を決める。精度維持はまだ未検証。
FramingGuideは既にB5比率。PageFramingはOCR文字枠の端接触だけを見ており、紙外周を検出していない。
B5指定だけで全体取得の証明にせず、RP-10で四辺・余白と実距離の校正を扱う。
比較準備として、設定Intentの `spread=true/false` で単頁／見開きのガイドを選択・保存する。
既定は比較前の単頁のまま。カメラの最大JPEG寸法は変えず、外側の4:3枠は紙の形から独立させた。
`./android-relay/gradlew --no-daemon :glassdoc:testDebugUnitTest --tests '*FramingGuideTest' --tests '*DocScanGlassActivityIntentTest'`
は追加のIntent確認後 `BUILD SUCCESSFUL in 30s`。`py -3.12 -m pytest -q tests/test_documentation_contract.py`
は `12 passed in 1.05s`、Ruffは `All checks passed!`。実写真比較はまだ行っていない。

- `adb devices -l` は3接続だが、IP／mDNS側のF-51Fをそれぞれ `getprop ro.serialno` で照合し、
  両方 `ZY22LWGDCV` と確認。操作対象はIP側 `192.168.0.30:38615` に統一する。
  グラス `192.168.0.4:5555` はserial `1904092623381086`、build `1.25.015-20260903-150201`、spread=1。
  F-51F build `64c964-a8f54`。読み取り時はTermux前景・Awake、SSH接続可能。
  まだこの追加実装段階では実機状態を変更していない。
- RP-05の入力相関: 異なる速いBACK／tap／swipeをテストで再現。最初の
  `./android-relay/gradlew --no-daemon :glassinput:test` は `32 tests completed, 2 failed`。
  同一KeyEvent組の重複と別のNOTIFICATION→terminal組を分離する修正後は
  `BUILD SUCCESSFUL in 16s`。相関幅970msは維持。broadcastだけの曖昧な重複は保守的な扱いを維持する。
- RP-05のActivity接続: KeyEvent発生時刻をelapsed clockへ変換し、終了確認の間隔を維持。
  focus変化で相関と終了確認を解除。readerメニューのBACKは一段戻り、本文だけ終了確認へ進む。
  メニュー試験の修正前は `1 test completed, 1 failed`。修正後の
  `./android-relay/gradlew --no-daemon :glassdoc:testDebugUnitTest --tests '*DocScanGlassActivityAnswerReadingTest'`
  は `BUILD SUCCESSFUL in 38s`。実機ジェスチャ照合と取消期限への接続は未実施。
- RP-02前半: `ROKID_ANALYZER=client-ocr` を明示的に登録。offlineとplaceholderを分け、
  未準備／既定placeholderの拒否を維持。新試験の修正前は `1 failed, 4 passed`、修正後の
  `py -3.12 -m pytest -q tests/test_real_mode.py tests/test_llm_adapters.py tests/test_provider_registry.py`
  は `40 passed in 5.20s`。
- RP-02後半: 空OCRの正本PNGを保存したまま、OCRを捏造せず画像参照を分割入力へ渡す。
  画像非対応solverは422で資料不足を明示。fallbackも必須画像を捨てず、単画像adapterは
  第2の必須画像を黙って落とさない。新しいAPI試験の修正前は `2 failed, 1 passed`、
  修正後のphoto／real_mode／llm_adapters／provider_registry／source_bundleは `60 passed in 8.15s`。
  fallback試験追加後のreal_mode／photoは `17 passed in 1.64s`。
  `py -3.12 -m pytest -q` は `605 passed, 1 skipped, 1 warning in 65.23s`。
  `py -3.12 -m ruff check .` は `All checks passed!`。実ChatGPT送信はまだ行っていない。
  公開契約／APKの版と全体buildは導入用のまとまりで更新・検査する。

### ローカル先行の通常撮影と起動選択（2026-09-16）

Runs on: Windowsの実装・自動試験。その後のグラス導入は下記、AP受け入れは未実施。

LocalCaptureSessionはHTTPより先にUUID記録を作り、送信先、モード、phase、CLOSED、後から得た
HTTPのlong IDを保存する。既存CaptureReviewのバイナリ形式を再利用し、確定写真の各版を保持して
atomic manifestで採用版とACKを選ぶ。未ACKは同じ文書／page番号／内容で再送する。
通常撮影のHTTPは別executorへ移し、サーバ待ちで次のグラス操作を止めない。
ローカル破損・保存失敗・認証や形式の拒否は原本を保持して停止する。解析を自動で繰り返さない。

起動は通常／リスニング二択と明示再開。以前の中断記録は新規開始後も一覧から選べる。
再開が受理されるまでchooserを維持し、別originや破損記録の拒否後に他の記録をCLOSEDにしない。
前回答案を開いて閉じる場合も、選ばなかった撮影記録は変更しない。旧形式の保存資料は
送信先を上書きせず、元のURLでの復元を要求する。リスニングはまだ開始前のHTTP待ちが残る。

初回設定はprivate領域のsetup.propertiesから受け、URLと鍵をKeystoreで暗号化して保存後に
一致する平文設定を除去する。実鍵はまだ発行・設定していない。
GET /v1/settingsにoperation_routes.glassdocを追加し、既存phone契約は維持する。
API／view／APKの版とREADME tupleを更新。公開契約はphysical_acceptance=pending。

- 保存破損試験は修正前 `1 test completed, 1 failed`。
- `./android-relay/gradlew --no-daemon :relaycore:testDebugUnitTest --tests '*LocalReviewTest'`
  → `BUILD SUCCESSFUL in 1m 29s`。遅いHTTP中の操作、終了前ACK不明の再起動と同じ写真の再送を含む。
- `./android-relay/gradlew --no-daemon :glassdoc:testDebugUnitTest --tests '*DocScanGlassActivityIntentTest'`
  → `BUILD SUCCESSFUL in 2m 4s`。起動待機・明示選択・再開拒否後の他記録保全・前回答案終了を含む。
- `py -3.12 -m pytest -q` → `606 passed, 1 skipped, 1 warning in 340.04s`。
  `py -3.12 -m ruff check .` → `All checks passed!`。既存httpx deprecation warningを保持。
- 旧形式origin保護の追加後、`./android-relay/gradlew --no-daemon test testDebugUnitTest assembleDebug`
  → `BUILD SUCCESSFUL in 3m 35s`、199 tasks。JDK 17.0.20.1+1、SDK Platform 36 revision 2、Gradle 9.4.1。
  `py -3.12 -m pytest -q tests/test_documentation_contract.py tests/test_versioning.py` → `21 passed in 8.45s`。
  `git diff --check` → exit 0。
- aapt2でpackage=dev.rokid.docscanglass.doc、launchable=DocScanGlassActivityを照合。
  apksignerは`Verifies`、v2=true、証明書SHA-256=`906307478018e09e2937cfd8042a674d27598767577e08a304472aae407ccacc`。
  Get-FileHashでAPK SHA-256=`A375A10D71CD158D5A98568289A1D75F59F39774CC6A5B2043A4E8ACADD4156A`。
  このbuild検査後に新APKを導入。撮影の物理試験はまだ実行していない。

読み取りでF-51FのAPIはlocalhost health=200、実行appは従来の版、REAL_MODE／analyzerは未設定、
API鍵なしを再確認。データは~/rokid-server/data。AP interfaceはまだ起動していない。
cmd wifiのAP照会は権限例外を併記して「他interfaceを破棄せず作成可能」と返しただけで、
APと携帯回線の同時接続を物理検証した結果ではない。

### 起動二択のグラス導入（2026-09-16）

Runs on: Windows → 指定グラス。同じ家庭Wi-Fiでの準備であり、会場AP経路の受け入れではない。

commit `db4255d` をorigin/feature/multimodal-scanへpush。新APKと、その後の入力ログ2行を加えた
診断APKをそれぞれidentity／署名／SHA-256照合後に導入した。`adb install -r` → `Success`。
導入前からAsleepだったため、起動後にwakeして通常／リスニング二択を確認した。
診断キーは `input -d 0` で指定すると届き、往復の選択後は通常モードを選択したまま待機。
`dumpsys media.camera` → `Active Camera Clients: []`。撮影・録音は始めていない。
正確な成果物ハッシュ・コマンドと限界は [hardware-measurements §H](../../docs/hardware-measurements.md#h-起動二択と診断キー入力2026-09-16)。

F-51FにAPI鍵を新規設定して `192.168.0.30:8000` で待受、同じ鍵をグラスへ暗号化保存する
具体案は利用者が2026-09-16に承認し、適用済み。`REAL_MODE=1`／`client-ocr`／`chatgpt-web`、
dataは既存のまま。実鍵の値は記録しない。再起動復号とアプリUIDからの認証401/200を確認。
詳細はhardware-measurements §I。AP切替は未適用。英語実音声試験は後回し。

### 原音の回収と再送位置（2026-09-16）

Runs on: Windowsの実装・自動試験。グラスでの録音・負荷測定は未実施。

RP-07の保存工程を実装。ListeningRecorderは`.part`へPCMを保存し、暫定1秒分ごとにsync、
確定WAVへatomic move後にshaとACKをatomic propertiesへ保存する。明示再開時に末尾の
完全サンプルをWAVへ回収し、元の`.part`も保全する。未ACKだけ同じsequence／時刻で再送。
途切れた録音はinterruptedのまま、正常に停止した記録だけaudio-completeへ進める。
録音停止位置はASR待ちより先に保存する。容量不足時の写真停止とsync実負荷はまだ未測定。

保存先はLocalCaptureSessionのUUID配下。Controllerが保存originと現在originを照合して渡す。
HTTP document番号だけを使う旧フォルダは自動移動・再送しない。別originの同じ番号から
原音を誤送信する問題をレビューで確認して修正した。

現段階の制限: pending写真が残るresumeLocalSessionは音声ready callbackを呼ばない。
この再開経路、新規／再開の区別、HTTP前の録音開始、有効サンプル後のREC、入力停止検出、
第2BACKでの音声終了は次のRP-08で接続する。RP-07のcheckboxは未完のまま。
旧形式の録音原本は削除しない。実機にはこの録音変更をまだ導入していない。

- 追加試験の最初はfixtureのAPI誤用でcompile失敗。修正後、未実装のrestoreに対して
  `:glassdoc:testDebugUnitTest --tests '*ListeningRecorderTest'` → `2 tests completed, 1 failed`。
- 回収実装後、multipartのfixtureを修正し、停止後のcomplete再試行を追加して同コマンド
  → `BUILD SUCCESSFUL in 1m 32s`。
- origin修正後、`./android-relay/gradlew --no-daemon :relaycore:testDebugUnitTest --tests '*LocalReviewTest' :glassdoc:testDebugUnitTest`
  → `BUILD SUCCESSFUL in 2m 44s`。未ACK末尾だけ再送、回収PCM一致、元part不変、
  ACK済み原音の破損拒否、停止後complete再試行、異なるoriginの同じ文書番号拒否を含む。
- `py -3.12 -m pytest -q tests/test_documentation_contract.py` → `12 passed in 2.21s`。
  `py -3.12 -m ruff check .` → `All checks passed!`、`git diff --check` → exit 0。

### 録音開始から通信待ちを分離（2026-09-16）

Runs on: Windowsの実装・自動試験。まだグラスへは導入していない。

RP-08の接続工程。Controllerは選択後、HTTP応答より先にUUID保存先と新規／再開をActivityへ通知。
文書作成は既存localNetworkで行い、文書番号をLocalCaptureSessionへ永続保存してからRecorderへ渡す。
Recorderは番号0でも`listening/`へ保存し、正の番号を自身の記録へ保存後に送信する。
同じUUID内の従来`listening-{id}`はそのまま使用し、二重記録は拒否する。
保存済み録音の文書番号を別番号へ変更しない。再開では録音が無ければ失敗し、新規録音へ切り替えない。
pending写真が残る明示再開でも音声復元を呼び、再送だけならマイク権限を要求しない。

- 通信応答を止めた新規リスニング試験は修正前 `1 test completed, 1 failed`。
- `./android-relay/gradlew --no-daemon :relaycore:testDebugUnitTest --tests '*LocalReviewTest' :glassdoc:testDebugUnitTest`
  → `BUILD SUCCESSFUL in 2m 20s`。番号未取得時のHTTP0件、遅いHTTP前の開始通知、
  pending写真＋音声復元、番号binding後の再送・別番号拒否を確認。
- 続くRP-08: 有効サンプル後のREC／入力停止検出、第2BACK、可視確認を隠さない音声終了、
  番号到着待ちで停止した録音の完了再試行を接続する。最後の写真確認中の表示はまだ未完。

### 有効サンプルのRECと独立した音声終了（2026-09-16）

Runs on: WindowsのJVM試験とAPK build。録音変更はグラス未導入、実音声試験は利用者指示で後回し。

RP-08を実装。AudioRecordの非blocking読取りでPCMを受けてからRECと自動撮影を開始する。
ゼロPCMは自然な無音として保存し、2秒のサンプル欠落、読取り異常、公開通知で確認できる
OS無音化／マイク経路変更では中断状態にする。2秒と原音sync間隔は同時撮影負荷で未校正。
第1BACKで撮影を終え、第2の別BACKは最後の写真確認中でも録音を止める。写真を隠さず、
取り直しで録音を再開しない。文書番号の到着前に停止しても、番号が保存されれば同じ原音から送信する。

レビューで、番号待ちとして開始したHTTP失敗の誤再試行と、録音停止通知が停止位置保存より先に
サービスを終了する競合を修正した。未bindingだけをDocumentPendingとして区別する。
WAV確定とSHA保存、stoppedの同期・atomic保存を終えてから停止を通知する。
送信再試行もforeground serviceを開始し、DocumentPending中は維持、成功／実エラー時に停止する。
録音用microphoneと保存音声用dataSyncを同じ既存serviceで切り替える。
Context7の既存Android IDから公開APIを確認し、
[Android公式service types](https://developer.android.com/develop/background-work/services/fgs/service-types)
でdataSyncのupload用途と権限条件を照合。SDK/AAR・依存・DB schemaの変更はない。

- 第2BACKの追加試験は修正前 `6 tests completed, 1 failed`。修正後の単独試験は
  `BUILD SUCCESSFUL in 1m 12s`。
- 停止位置保存と未binding例外の回帰試験は修正前 `6 tests completed, 2 failed`。
- 遅いbinding後のサービス再開試験は修正前 `1 test completed, 1 failed`。
- 最終修正後 `./android-relay/gradlew --no-daemon :glassdoc:testDebugUnitTest`
  → `BUILD SUCCESSFUL in 2m 34s`、41 tasks。REC前後、自然なゼロPCM、入力停止／OS無音化、
  中断末尾PCM、文書binding、最後の写真保持、再送サービスの種別を確認。
- JVMの録音サービス模擬がnullリストを返す失敗は、実行jarのjavapとstackで原因を確認し、
  テストのBinder応答を空リストにした。実機コードで例外を黙殺する回避は加えていない。
- 独立レビューの最終再確認に追加所見なし。実機の録音継続・入力停止検出・省電力は未検証。
- `./android-relay/gradlew --no-daemon test testDebugUnitTest assembleDebug`
  → `BUILD SUCCESSFUL in 2m 12s`、199 tasks: 13 executed, 186 up-to-date。
  JDK 17.0.20.1+1／SDK Platform 36 revision 2／Gradle 9.4.1、ASCII checkout。
- `py -3.12 -m pytest -q tests/test_documentation_contract.py tests/test_versioning.py`
  → `21 passed in 5.45s`。Ruff → `All checks passed!`、`git diff --check` → exit 0。
  view契約／APP／APKの版更新後、同じPython試験 → `21 passed in 8.49s`、Ruff → `All checks passed!`。
- 版更新後 `./android-relay/gradlew --no-daemon :glassdoc:assembleDebug`
  → `BUILD SUCCESSFUL in 1m 59s`、57 tasks: 11 executed, 46 up-to-date。
  `aapt2 dump badging` → package `dev.rokid.docscanglass.doc`、activity `DocScanGlassActivity`。
  `apksigner verify --verbose --print-certs` → `Verifies`、v2=true、証明書SHA-256
  `906307478018e09e2937cfd8042a674d27598767577e08a304472aae407ccacc`。
  `Get-FileHash -Algorithm SHA256` → APK
  `98A87A0E642E0E32CA9DD3F745A1155DC28ED13488B309ACCE10AFBC14D45B1C`。
  この時点ではAPK未導入・認証承認待ちだった。その後の承認と導入はhardware-measurements §Iに記録。

### Next steps — 追加実装

Runs on: 以下の認証保存はWindowsの自動試験。Android Keystoreの実機確認はAPK導入後。

RP-03の認証保存を追加。glassdocはURLと鍵をAES-GCMで一組として保存し、暗号鍵は
Android Keystore、暗号化ファイルはno-backup領域に置く。Controllerが設定変更を受理してから
永続化し、保存失敗時は送信先を変えない。別URLへ前の鍵を流用せず、配送済みIntentから鍵を除去。
破損ファイルを勝手に削除／再生成しない。Context7に該当資料はなく、
[Android公式AES-GCM例](https://developer.android.com/reference/android/security/keystore/KeyGenParameterSpec)
の公開APIを確認した。追加依存なし。

`./android-relay/gradlew --no-daemon :glassdoc:testDebugUnitTest --tests '*ConnectionSettingsTest' --tests '*DocScanGlassActivityIntentTest'`
は `BUILD SUCCESSFUL in 25s`。Activity試験の初期化を更新した後の
`./android-relay/gradlew --no-daemon :relaycore:testDebugUnitTest :glassdoc:testDebugUnitTest`
は `BUILD SUCCESSFUL in 55s`。再生成したstoreからの復元、毎回異なる暗号文、改変検出、
中断tmpの非採用、起動時の認証、送信先変更／拒否時の保存維持を確認。実鍵設定・実機再起動は未実施。

Runs on: WindowsでRP-05のActivity接続、RP-02の実OCR契約、起動・保存・録音を順次実装。
実機の短い通し試験は指定グラス→F-51F AP→F-51F Chrome。

1. 起動二択・通常写真のローカル保存と独立送信まで実装。全Android gateとAPK identity／署名／hashを確認。
   グラス導入とスマホapp・実鍵の承認後適用を実行。最新の再起動認証はhardware-measurements §I。
   RP-07/08の録音保存・開始表示・独立終了は自動試験まで実装。実機負荷・容量保護と、
   取消期限へ時刻を渡すRP-09が残る。これらは実装済みと扱わない。
2. 用紙経路の準備後、同じB5紙面の単頁／見開きを撮り、実OCRと最終答案の差を測る。
   ガイド切替だけで外周検出が実装されたとは扱わない。カメラ寸法・retryは変更しない。
3. RP-01/18の未成立能力を小さく検査する。実英語音声は利用者指示で後回し。
   既存スマホ側CDP／ASR測定を未実施と誤認しない。新しい認証・AP設定は準備を具体化して承認範囲を照合。

## 現在の依頼と再開境界（2026-09-15）

Runs on: 今回の照合・文書更新はWindowsだけ。実機への書込み・ChatGPT送信はしていない。

利用者は残作業の前に認識合わせを求め、通常／リスニングの選択と起動直後の開始を再確認した。
さらに「抜けを徹底確認」「全て実装せず、新旧を組み合わせて使用感と精度を高める」と指定した。
そのため追加実装を止め、旧FS-01～72・R1～13・S01～30・X01～06と現コードを照合した。

正本は [現行plan](../../tasks/plan.md)、[RPタスク](../../tasks/todo.md)、
[ソース根拠・採否対応表](../../docs/requirements-audit.md)。旧planとtodoは全文を履歴区画へ保持した。
この後に続く以前の「残る範囲と再開順」は当時の記録であり、今はRP一覧に優先しない。

- 基準HEAD `97ef5b8e02d06436406543ad2d6de3672b43088b`、branch `feature/multimodal-scan`、開始時clean。
- 実装は変えていない。起動二択、通信に依存しない取得、順次答案、終了後の自動再装着起動はまだ未接続。
- 現コードの重大な不足: 970ms内の別BACK抑止、Controller内の同期HTTP、最終写真確認中の音声終了漏れ、
  readerの追加取得未接続、menu BACKの終了への横取り、全phaseのCLOSED保存、実OCRとplaceholderの区別。
- 使用感を改善する接続を先行し、精度は全文OCR＋関連画像を既定に実資料比較。PDF／結合は比較用。
  訂正後は新入力文書で全再解析。新CXR転送・別クラウド・local LLM本流・汎用queueは追加しない。
- 即消灯／CLOSED後の再装着自動起動と原音のChatGPT利用は早期能力確認。成立したと仮定して製品化しない。
- graph索引世代は以前と同じ。根拠ファイルのcoverageを確認し、変更・未索引は現在のソースを直接確認した。
- 以前のAPK導入／F-51F更新承認、LED監査省略、スマホAP／Chrome前景・点灯、端末内ASRの選択を保持する。
  新しい認証・AP設定変更、実資料のモデル送信などをこの計画整理の承認と混同しない。

### 今回の検査

Runs on: Windows、上記基準HEADに対する文書だけの変更。

- `py -3.12 -m pytest -q tests/test_documentation_contract.py tests/test_versioning.py tests/test_surface_inventory.py`
  → `26 passed in 11.94s`。
- `py -3.12 -m ruff check .` → `All checks passed!`。`git diff --check` → exit 0。
- `py -3.12 -` の一時照合（Pathで読み、git show HEADの旧全文が新文書に含まれること、
  採否表のFS番号集合、RP見出しとruntime／検証／依存／対象をassert）→
  `tasks/plan.md: previous full text preserved`、`tasks/todo.md: previous full text preserved`、
  `FS coverage: 72/72; RP tasks: 22/22 with runtime, checks, dependencies and scope`。
- 指定JDK17の `jshell.exe -q --class-path android-relay/glassinput/build/classes/java/main -` に
  監査文書の再現コードを入力 → `first=Optional[BACK]`、`second_distinct_500ms=Optional.empty`。
  異なる速い操作の欠落を再現した結果であり、合格と扱わない。
- `py -3.12 scripts/eval_fast_scan.py --pack tests/fixtures/answer_forms/cases.json`
  → 8 cases／17 questions、hardware_verified=false、ai_executed=false、rubrics_pending_review=10。
  今回は全pytest／Android build／物理試験を再実行していない。以前の部品証跡は下に保持する。

### Next steps

Runs on: 認識合わせは会話。実装開始後はWindows、能力測定は指定グラスとF-51F。

1. 利用者へ採用・統合・保留・廃止と未成立能力を説明し、認識合わせを終える。
2. その後、RP-01/18の早期能力確認とRP-02～09/20の短い一周から始める。
3. 既存のASR／CDP部品測定を保持し、未測定条件だけ追加する。実機適用前に具体的対象・条件を照合する。

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

現在は承認済みの192.168.0.30:8000待受、API認証あり、REAL_MODE=1／client-ocr／chatgpt-webです。
実機再起動後の復号・認証HTTPも確認済み（hardware-measurements §I）。スマホAPへの切替と
携帯回線併用は未実施です。設定鍵は再生成しないでください。AP設定変更は別の承認が必要です。

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

# Rokid DocScan 実機検証チェックリスト

対象は Windows PC + Android スマホ + Global Hi Rokid + Rokid Glasses の構成です。
導入は [windows-android-real-device-setup.md](windows-android-real-device-setup.md)、
接続面は [cxr-l-integration.md](cxr-l-integration.md) を参照してください。

ビルド成功は実機合格を意味しません。Hi Rokid/YodaOS更新後は、このチェックリストを
再実施します。

## 0. 検証記録

| 項目 | 記録 |
|---|---|
| 実施日時 | |
| スマホ機種 / Android version / API | |
| Global Hi Rokid version / versionCode | |
| Rokid Glasses model | |
| YodaOS build | |
| APK commit SHA / client version（期待値 `0.3.5`） | |
| CXR-L service version / versionCode（接続ログ） | |
| 採用した撮影設定 `幅x高さ q品質` | |
| サーバー commit SHA / APP・API version | |
| Glasses View contract（期待値 `1.8.0`） | |
| Analyzer / model | |
| Solver / model | |
| PC IPv4 / network profile | |

APIキー、Bearer値、Hi Rokid認可トークンは記録しません。

## A. ビルドと導入

- [ ] JDK 17以上、Android SDK Platform 36、ADBをWindowsへ導入した。
      （Android Studio 同梱の JBR 21 で `assembleDebug` 成功を実測済み。既定の
      `java` が JDK 25 の環境では `JAVA_HOME` を JBR 側へ明示する。）
- [ ] `android-relay\gradlew.bat testDebugUnitTest assembleDebug` が成功した。
- [ ] チェックアウトパスがASCIIのみである（非ASCIIパスはAGPが拒否する）。
- [ ] `adb install -r ...\app-debug.apk` が成功した。
- [ ] スマホへGlobal版Hi Rokidが入り、ログイン済みである。
- [ ] Hi Rokid上でグラスがBluetooth接続済みである。

## B. サーバーとネットワーク

- [ ] サーバーを `--host 0.0.0.0 --port 8000` で起動した。
- [ ] `ROKID_API_KEY` と画像対応 `ROKID_ANALYZER` / `ROKID_SOLVER` を設定した。
- [ ] `curl http://PC-IP:8000/v1/settings` を実行し、`providers.analyzer.ready`
      と `providers.solver.ready` が `true` であることを、1枚も撮影する前に確認した。
      `false` は資格情報かSDKが無い状態で、撮影しても offline placeholder が
      応答する。アダプタは黙って切り替わるため、応答内容では気付けない。
- [ ] `providers.analyzer.name` が意図したプロバイダで、`offline` が `false` である。
- [ ] `OPENAI_BASE_URL` / `ANTHROPIC_BASE_URL` / `GOOGLE_*` の既存値を確認した。
      SDKはこれらを自動採用するため、別用途のローカルproxyを指している場合は
      サーバー起動シェルで解除する。
- [ ] PC側で `curl http://PC-IP:8000/health` が応答する（自分のLAN IPで確認する）。
- [ ] スマホのブラウザで `http://PC-IP:8000/health` が開く。
- [ ] Relayの「サーバ確認」が成功する。
- [ ] 誤ったBearer値では保護APIが401になる。
- [ ] スマホとPCが同一サブネットにあり、APアイソレーション（ゲストSSID等）で
      分離されていない。
- [ ] 8000番の受信許可がWindowsの現在のネットワークプロファイルに適用されている。
      プロファイルがPublicの場合、Private限定の規則は効かない。
- [ ] 公衆Wi-Fi/インターネットへ8000番を公開していない。

## C. Global Hi Rokid / AIDL

- [ ] Relayの「Hi Rokid認可・再接続」から認可画面が開く。
- [ ] 未確認アプリ確認が出た場合、内容を確認して許可した。
- [ ] `IMediaStreamService` bind後に接続状態がtrueになる。
- [ ] 必須callbackの登録が1つでも失敗した場合、接続済み表示にならず撮影できない。
- [ ] サービス切断時にRelayとHUDが未接続表示へ戻る。
- [ ] 再認可・再接続で復帰する。

必要なら次を記録します。

```powershell
adb shell dumpsys package com.rokid.sprite.global.aiapp |
  Select-String "AUTHORIZATION|MEDIA_STREAM_SERVICE"
adb logcat -v threadtime -s DocScanRokid:*
```

## D. グラス入力

公開CXR-Lで受信できるグラス入力を確認します。専用シャッターボタンの入力イベントや
全タッチジェスチャは前提にしません。

Hi Rokid `G1.12.10.0815` / CXR-L service `1.0.0 (code 10000)` の実測では、グラスから
届く入力は**1本指タップ由来の `AI-exit` だけ**です。長押しはグラス側AIが占有し、
ダブルタップはYodaOSの「終了」に予約されています。以下の長押し・2回短押し項目は、
より多くの信号を配送するファームウェアでのみ確認できます。現行ファームでは該当項目を
N/Aとし、対応するスマホ側ボタンで確認してください。

- [ ] `READING` で最初のユーザータップによりCustomViewが閉じると、スマホログに
  `Glasses input source=...` が残り、`AIMING` の照準が表示される。
- [ ] 最初のタップ後は `takePhoto` が0回のままで、自動撮影されない。
- [ ] リレーが表示をpushした直後のecho `AI-exit` は入力として扱われず、`AIMING` から
  即座に `takePhoto` が発行されない（旧500 ms窓実装の誤シャッター再発チェック）。
- [ ] スマホの「撮影取消」で `AIMING` を取り消せ、`takePhoto` を発行しない。
- [ ] `AIMING` で照準を確認した後の2回目のタップが1.5秒静止待ちを開始する。
- [ ] 現在世代の静止案内open callbackより前は1.5秒timerを開始せず、open errorまたは
  3秒のACK timeoutでは`takePhoto`を0回のまま準備を取り消し、そのcallback epochを
  fenceする。
- [ ] ACK fault/timeout後は新しいCustomViewを要求せず、「Hi Rokid認可・再接続」を
  完了した後の新しいcallback epochでだけ再開する。
- [ ] 1.5秒待ちの間も `takePhoto` は0回で、満了後に
  `takePhoto(1920, 1080, 80)` が1回だけ発行される。
- [ ] `STABILIZING`中のタップまたはスマホの「撮影取消」で静止待ちを取り消し、
  旧timer満了後も`takePhoto`は0回である。
- [ ] リレー自身がHUD更新のために行うclose + openは確認済みcallback世代内で識別され、
  ユーザータップとして処理されない。
- [ ] 同じ物理操作由来のuser CustomView closeと`AI-assist-start`が近接配送されても
  debounceされ、撮影・登録・読取完了が重複しない。
- [ ] 同じCustomView世代のclose callbackが重複しても、入力は1回だけ処理される。
- [ ] ダブルタップで標準メニューへ戻り`AI-exit`が届くと、現在のDocScan画面が
  自動再表示される。メニュー遷移のcloseは入力として破棄され、復帰だけでは
  `takePhoto`、写真登録、読取完了を発行しない。
- [ ] 通常のCustomView openに伴う`AI-exit`は後続open callbackで復帰予約を取り消し、
  close + openを余分に繰り返さない。
- [ ] 復帰timerとopen callbackが競合しても、remote CustomViewがopenなら新しい世代を
  要求せず現在表示を維持する。
- [ ] `CAPTURE_REVIEW` のタップは同じ `page_index` の `AIMING` を表示するだけで、
  その場では `takePhoto` を発行しない。**`0.3.0` の回帰点**: 表示切替のcloseが
  誘発したechoがシャッターとして扱われ、タップした瞬間に撮影されていた。
- [ ] `AIMING` へ入ってから最初のタップまでの間に `takePhoto` が0回である
  （ログに `echoed our own view push` が残り、撮影ログが出ない）。
- [ ] 同ページ再撮影準備後のタップで、1.5秒待ち後に `takePhoto` が1回だけ発行される。
- [ ] スマホの「この写真を登録」が未登録写真を1回だけ登録する。
- [ ] 登録成功後にpending削除を失敗させても、再起動後に同じJPEGが未登録写真として
  復活しない。
- [ ] スマホの「読取完了」で読取完了へ進む。
- [ ] `REVIEW` のタップで次へ移動し、スマホの「新規」で新規文書へ戻る。
- [ ] ファームウェアが2回の入力を`DOUBLE_SHORT`としてアプリへ配送する場合だけ、
  読取中は前ページ再撮影準備、
  撮影確認中は同ページ再撮影準備、閲覧中は前へ移動し、意図しない撮影をしない。
- [ ] 専用シャッターボタンを押してもイベントを受信できるとは案内しない。
- [ ] スマホ画面に「この写真を登録」「同じページを撮り直す」
  「未登録写真を破棄」のフォールバック操作が表示され、それぞれ実行できる。

## D-2. 自動読取（`0.3.5`）

操作を前提にしない経路です。`CAPTURE_REVIEW` のタップは実機で `AI-exit` を配送しない
ことが実測されているため、こちらが主経路になります。

- [ ] スマホの「自動読取 開始」でバーストが始まり、グラス操作なしで撮影される。
- [ ] 1ページにつき3枚撮影され、ログに `Automatic burst shot n/3 score=…` が残る。
- [ ] 登録されるのは最良スコアの1枚だけで、3枚とも保存されない。
- [ ] 用紙をめくらずに待つと `Automatic burst skipped as a duplicate` となり、
      同じページが二重登録されない。
- [ ] 用紙をめくると次の `page_index` として登録され、`has_image=true` になる。
- [ ] 「自動読取 停止」で即座に停止し、ボタン表示が「開始」へ戻る。
- [ ] 撮影エラー・リンク切断で自動停止し、ERROR表示になる（撮り続けない）。
- [ ] 自動読取中はグラスの1回タップで状態が進まない（入力に依存していない）。
- [ ] 自動読取中に2回タップしてデフォルト画面へ戻ると、同じページのバーストが
      やり直される。
- [ ] OCRが0文字またはOCRエラーのバーストは、待たずに約300msで撮り直される
      （ログ `retrying immediately`）。
- [ ] 読めないバーストが5回続くと間隔が6秒へ落ちる
      （ログ `retrying after backing off`）。LEDが点灯し続けない。
- [ ] 読取完了はスマホのボタンで行う。

## E. 写真とOCR

- [ ] タップ→タップの二段階操作と1.5秒静止待ちを経た
  `takePhoto(1920, 1080, 80)` がtrueを返す。
- [ ] `onImageReceived` のログにJPEGバイト数と予算比が記録される。
- [ ] callback到着前の連続操作で2件目の`takePhoto`が発行されない。
- [ ] `onImageReceived` のJPEGが0バイトでない。
- [ ] 撮影後は `CAPTURE_REVIEW` になり、写真が「未登録」と表示される。
- [ ] 初回撮影前に文書自体は作成されるが、未登録の間は対象 `page_index` が
  `/scan-status.page_indexes` に増えず、次ページ番号も変化しない。
- [ ] 待機満了の自動登録、または「この写真を登録」が成功した後にだけ
  `/scan-status.pages[n].has_image` がtrueになる。
- [ ] 登録通信が失敗した場合は未登録写真を保持し、対象ページと次ページ番号を
  進めず再試行できる。
- [ ] 用紙の問題番号、本文、選択肢が端末OCRへ入る。
- [ ] 写真回転の初期値が、検証済み実機に合わせた90°である。
- [ ] スマホで0/90/180/270°を選び「同じページを撮り直す」と、選択した回転が
  次の再撮影とOCRに適用され、現在の未登録写真自体は変更されない。
- [ ] 用紙まで40〜60cm離し、用紙中心を照準の「＋」へ合わせ、`AIMING`のタップ後1.5秒から
  callbackまで静止して撮影できる。
- [ ] 撮影後プレビューで用紙の四隅、文字の輪郭、ブレを確認できる。
- [ ] 用紙全体を枠に入れて撮ると、HUDとスマホが「全体が入っています」を表示する。
- [ ] わざと用紙の右端を枠外へ出して撮ると「不合格 右が切れています」を表示し、
      スマホ側も撮り直しを推奨する。上下左右それぞれで辺名が正しい。
- [ ] 合格判定は4秒、不合格・判定不可は12秒で自動登録される。
- [ ] 待機中にグラスを2回タップしてデフォルト画面へ戻ると、自動復帰と同時に
      登録が取り消され、同じページの撮り直しが始まる（1回タップは届かない）。
- [ ] グラスが確認表示を開けなかった場合は自動登録されず、スマホのボタンが残る。
- [ ] 登録がサーバー側で失敗した後の再表示では自動登録が再開しない（無限再送しない）。
- [ ] 不合格判定でも「この写真を登録」は押せる（自動で塞がない）。
- [ ] 不合格の未登録写真を残して再起動すると、同じ判定が復元される。
- [ ] `0.3.0` で保存された未登録写真が残っていても復元でき、判定は
      「判定情報なし」になる。**実機確認済み 2026-08-27**。
- [ ] 判定不可の写真が「合格」と表示されない（`P1 判定情報なし` と出る）。
      **実機確認済み 2026-08-27**。
- [ ] ブレや欠けがある未登録写真は、撮影確認中の2回タップで同ページ再撮影が始まり、
  照準確認後のタップで撮り直せる。
- [ ] 端末OCRが0文字なら警告され、判定不可として長い待機（12秒）になる。
- [ ] OCRが0文字でも、警告を確認して明示登録すると元写真が保存される。
- [ ] 「未登録写真を破棄」でサーバーへ送信せず、同じ次ページ番号の読取へ戻る。
- [ ] 画像対応Analyzerが空OCRを回復できる。
- [ ] Analyzer未設定かつOCR空の場合、`finalize-reading` 後も読取状態を保つ。
- [ ] 同じページ番号を再撮影すると置換され、再度読取完了できる。
- [ ] 写真callbackを30秒以上返さない試験では、再撮影・読取完了・新規文書が拒否される。
- [ ] タイムアウト後の遅延画像はアップロードされず、callback受信後に再撮影可能になる。
- [ ] callbackが来ない場合、実際のCXR-L service unbind/rebind後にだけ撮影ブロックが解除される。
- [ ] 同じservice bind中のグラス切断→接続通知だけでは撮影ブロックが解除されない。
- [ ] `takePhoto` のBinder応答だけを失敗させた場合、受理不明として直ちに撮影ブロックされる。
- [ ] 再接続後、旧bindから遅延配送した画像callbackが新しい撮影を完了せず、
  旧JPEGもアップロードされない。

カメラは固定焦点です。Rokid公称の被写界深度は34cm〜∞ですが、34cmは限界値のため
40〜60cmを運用目安にします。公開CXR-Lにライブプレビュー、AF制御、合焦状態はなく、
照準の「＋」もディスプレイFOVとカメラFOVが異なるため正確な撮影境界ではありません。
構図と四隅は撮影後プレビューで判定します。`takePhoto(4032, 3024, 80)` は実機でJPEG
callbackが返らなかった既知NGですが、原因は未特定です。E-2で実測します。

## E-2. 撮影パラメータの実測（capture sweep）

CXR-Lは写真を`oneway`のBinder callbackで返すため、非同期側の約512KBを超えたJPEGは
エラーにならず消えます。「解像度が拒否された」のか「JPEGが大きすぎた」のかは、
返ってきたバイト数を記録しないと区別できません。手順は
[windows-android-real-device-setup.md](windows-android-real-device-setup.md)
の「撮影パラメータの実測」を参照します。

- [ ] 接続時のログに `CXR-L <version> (code <n>)` が出て、記録した。
- [ ] スマホ画面上部の見出しが `Rokid DocScan Relay <version> (build <code>)` を表示し、
      この実機セッション向けに入れたビルドと一致する。adbが落ちていても読める。
- [ ] `1920x1080 q80` で撮影し、ログに `… …KB 予算…%` が出た（基準の再現）。
- [ ] `次のプリセット` で `1920x1080 q95` へ切り替わり、値がスマホ画面に反映された。
- [ ] `1920x1080 q95` の結果を記録した（バイト/画素が0.2を超えたか、OCR文字数と確信度）。
- [ ] `1920x1080 q80` に戻し、照明だけを強く均一にしてもう1枚撮り、結果を記録した。
- [ ] 上の2枚で伸びなかった場合に限り `4032x3024 q80` を試し、結果を記録した
      （callback到達／`応答なし 30.0s`）。
- [ ] 撮影処理中に撮影設定を変更しようとすると拒否される。
- [ ] アプリを再起動しても、採用した撮影設定が保持される。
- [ ] 不正値（例: 幅`0`、品質`101`）を入力すると、日本語メッセージで拒否される。

| 試行 | 設定 | 照明 | JPEGバイト数 | バイト/画素 | 経過秒 | OCR文字数 / 確信度 |
|---|---|---|---|---|---|---|
| 1 | `1920x1080 q80` | 通常 | 既測 147,398 | 既測 0.071 | 既測 5.2 | 既測 671 / 未記録 |
| 2 | `1920x1080 q95` | 通常 | | | | |
| 3 | `1920x1080 q80` | 強く均一 | | | | |
| 4 | `4032x3024 q80` | 通常 | | | | |

## E-3. 校正シートによるOCR下限の測定

`docs/assets/calibration-a4-300dpi.png` をA4等倍で印刷して使います。グラスのカメラは
109°の超広角で、40cmで撮ったA4は横幅の約23%しか占めません。ML Kitは1文字16px以上を
要求するため、`1920x1080` では10.5ptが1文字5〜9pxとなり、これが「OCR 0文字」の
主因と考えられます。段階表のどこまで読めたかで、必要な解像度を直接決められます。

- [ ] 四隅の二重丸が4つとも写る距離を記録した。
- [ ] 100mmスケールバーの画素幅から px/mm を算出した。
- [ ] 段階表のうちOCRが正しく返した最小の文字サイズを記録した。
- [ ] 線パターンのうち分離して見える最小幅を記録した。
- [ ] `mean confidence` が0.50を下回る文字サイズを記録した。
- [ ] 採用した撮影設定で、実際の試験問題用紙が読めることを確認した。

撮影ガードとcallback epochを再現性高く調べる場合は、debug APKへAndroid Studioの
デバッガをattachし、`RokidGlobalLink.CallbackSet.onImageReceived` の
`dispatchCallback` 呼び出し行へ、Suspendを **Thread** にしたbreakpointを置きます。
ガード値を見る場合は、`RokidGlobalLink.glassesStatusChanged` /
`serviceBindingReset` と、`DocScanController.onCaptureLinkStateChanged` 内の
`event.resetCaptureIfSafe` の直後にもbreakpointを置きます。撮影callbackをそのBinder
threadだけで停止したまま、次を確認します。

1. Hi Rokid上でグラスだけを切断・再接続する。Logcatは
   `event=GLASSES_STATUS_CHANGED` を示し、`photoInFlight` と
   `CaptureLease.isUnresolved()` はどちらもtrueのままである。
2. Relayの「Hi Rokid認可・再接続」を押す。Logcatは
   `event=SERVICE_BINDING_RESET` を示し、両ガードがfalseへ戻る。
3. 停止中の旧callbackをresumeする。Logcatに
   `ignored stale image callback epoch=...` が出て、旧JPEGがアップロードされない。

全threadを停止すると再接続操作も止まるため、breakpointのSuspendは必ずThreadにします。

写真には個人情報や試験資料が含まれる可能性があります。保存・クラウド送信の同意と
削除方針を運用前に決めます。

## F. 文書確定・解答

- [ ] ページ番号が0から連続している。
- [ ] 「読取完了」後に `/finalize` → session作成 → `/finalize-reading` が完了する。
- [ ] Analyzer由来 `ocr_text` / `vision_text` がページへ保存される。
- [ ] 問題が1件以上に分割される。
- [ ] Solverへ各問題の開始ページ `image_path` が渡る。
- [ ] Provider失敗時にプレースホルダー結果を解答済みとして保存しない。
- [ ] `mode=real` は許可フラグなしでロックされる。

## G. HUD

- [ ] 黒背景・緑文字で表示される。
- [ ] 1レスポンスあたり最大3行である。
- [ ] `customViewUpdate`だけに依存せず、close + openで更新される。
- [ ] 撮影後の縮小プレビューが正しい向きでスマホとグラスのCustomViewへ表示される。
- [ ] `AIMING` の「＋」が用紙中心合わせの目安として表示され、正確な撮影境界や
  合焦表示とは案内されない。
- [ ] 撮影前ライブ映像とAF/合焦状態を表示可能とは案内せず、CXR-L非対応として扱う。
- [ ] 長文は次の表示へ送れる。
- [ ] 日本語、記号、引用符、改行がJSON破損せず表示される。
- [ ] HUD更新で白背景フレームをアプリが生成しない。

## H. プライバシーLEDと撮影通知

別の人または別カメラで物理確認し、動画と時刻を残します。

- [ ] 撮影要求中にプライバシーLEDが点灯する。
- [ ] 写真callback完了後にLEDが消灯する。
- [ ] OCR/アップロード/Analyzer/Solver処理中に追加撮影が起きず、LEDが消灯している。
- [ ] 解答閲覧中もLEDが消灯したままである。
- [ ] アプリがLEDを無効化・迂回・偽装していない。
- [ ] 撮影タイムアウトをLED消灯とみなさず、接続復旧まで追加撮影しない。
- [ ] シャッター音、フラッシュ、撮影表示の実挙動を当該ファームで記録した。

「無音」「無フラッシュ」は公開SDKで制御済みと仮定しません。

## I. 中断復帰と連続運用

- [ ] 2ページ目以降でアプリを中断し、再認可後に次ページ番号から再開する。
- [ ] `CAPTURE_REVIEW` 中にアプリを終了・再起動すると、同じ未登録写真、OCR文字数、
  `page_index`、回転が復元され、自動登録されない。
- [ ] 再起動や再接続だけでは `takePhoto` が発行されず、自動撮影されない。
- [ ] `/finalize` 後・session作成前の中断から自動復帰する。
- [ ] session作成後・`finalize-reading`前の中断から自動復帰する。
- [ ] 同じ読取完了操作が二重配送されても文書/問題/課金呼び出しが重複しない。
- [ ] Relay表示中はスマホがスリープせず、複数ページの写真callbackが継続する。
- [ ] Wi-Fi一時切断後、エラーがスマホとHUDに表示され、再操作で復旧できる。

## 合格判定

| 領域 | 合否 | 証跡 |
|---|---|---|
| Android build / unit test | | |
| Hi Rokid auth / AIDL | | |
| グラス入力 / event source | | |
| 写真 / OCR | | |
| Analyzer / Solver | | |
| HUD | | |
| LED / 撮影通知 | | |
| 中断復帰 | | |

未実施項目が一つでもある場合は「実機検証済み」ではなく「ビルド済み・実機検証待ち」と
記録します。

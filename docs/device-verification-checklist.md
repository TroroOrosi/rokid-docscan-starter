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
| APK commit SHA / version | |
| サーバー commit SHA / APP・API version | |
| Analyzer / model | |
| Solver / model | |
| PC IPv4 / network profile | |

APIキー、Bearer値、Hi Rokid認可トークンは記録しません。

## A. ビルドと導入

- [ ] JDK 17、Android SDK Platform 36、ADBをWindowsへ導入した。
- [ ] `android-relay\gradlew.bat testDebugUnitTest assembleDebug` が成功した。
- [ ] `adb install -r ...\app-debug.apk` が成功した。
- [ ] スマホへGlobal版Hi Rokidが入り、ログイン済みである。
- [ ] Hi Rokid上でグラスがBluetooth接続済みである。

## B. サーバーとネットワーク

- [ ] サーバーを `--host 0.0.0.0 --port 8000` で起動した。
- [ ] `ROKID_API_KEY` と画像対応 `ROKID_ANALYZER` / `ROKID_SOLVER` を設定した。
- [ ] スマホのブラウザで `http://PC-IP:8000/health` が開く。
- [ ] Relayの「サーバ確認」が成功する。
- [ ] 誤ったBearer値では保護APIが401になる。
- [ ] WindowsネットワークはPrivateで、公衆Wi-Fi/インターネットへ8000番を公開していない。

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
adb logcat -s DocScanRokid:*
```

## D. AIキー入力

公開AIDLの `onAiKeyDown` / `onAiKeyUp` を確認します。旧KeyCode表や全タッチ
ジェスチャを前提にしません。

- [ ] 短押し1回で撮影が1回だけ始まる。
- [ ] 短押し2回で直前ページが同じ `page_index` に置換される。
- [ ] 1.2秒以上の長押しで読取完了へ進む。
- [ ] 閲覧中の短押し/短押し2回で前後へ移動する。
- [ ] 閲覧中の長押しで終了し、新規文書へ戻る。
- [ ] スマホ画面ボタンでも同じ処理を実行できる。

## E. 写真とOCR

- [ ] `takePhoto(1440, 1920, 85)` がtrueを返す。
- [ ] callback到着前の連続操作で2件目の`takePhoto`が発行されない。
- [ ] `onImageReceived` のJPEGが0バイトでない。
- [ ] `/scan-status.pages[n].has_image` がtrueになる。
- [ ] 用紙の問題番号、本文、選択肢が端末OCRへ入る。
- [ ] 向きが不正な場合、0/90/180/270°設定で修正できる。
- [ ] ブレたページをAIキー2回押しで置換できる。
- [ ] 端末OCRが空でも元写真は保存される。
- [ ] 画像対応Analyzerが空OCRを回復できる。
- [ ] Analyzer未設定かつOCR空の場合、`finalize-reading` 後も読取状態を保つ。
- [ ] 同じページ番号を再撮影すると置換され、再度読取完了できる。
- [ ] 写真callbackを30秒以上返さない試験では、再撮影・読取完了・新規文書が拒否される。
- [ ] タイムアウト後の遅延画像はアップロードされず、callback受信後に再撮影可能になる。
- [ ] callbackが来ない場合、実際の切断・再接続後にだけ撮影ブロックが解除される。
- [ ] `takePhoto` のBinder応答だけを失敗させた場合、受理不明として直ちに撮影ブロックされる。
- [ ] 再接続後、旧bindから遅延配送した画像callbackが新しい撮影を完了せず、
  旧JPEGもアップロードされない。

写真には個人情報や試験資料が含まれる可能性があります。保存・クラウド送信の同意と
削除方針を運用前に決めます。

## F. 文書確定・解答

- [ ] ページ番号が0から連続している。
- [ ] 長押し後に `/finalize` → session作成 → `/finalize-reading` が完了する。
- [ ] Analyzer由来 `ocr_text` / `vision_text` がページへ保存される。
- [ ] 問題が1件以上に分割される。
- [ ] Solverへ各問題の開始ページ `image_path` が渡る。
- [ ] Provider失敗時にプレースホルダー結果を解答済みとして保存しない。
- [ ] `mode=real` は許可フラグなしでロックされる。

## G. HUD

- [ ] 黒背景・緑文字で表示される。
- [ ] 1レスポンスあたり最大3行である。
- [ ] `customViewUpdate`だけに依存せず、close + openで更新される。
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
- [ ] `/finalize` 後・session作成前の中断から自動復帰する。
- [ ] session作成後・`finalize-reading`前の中断から自動復帰する。
- [ ] 同じ長押しが二重配送されても文書/問題/課金呼び出しが重複しない。
- [ ] Relay表示中はスマホがスリープせず、複数ページの写真callbackが継続する。
- [ ] Wi-Fi一時切断後、エラーがスマホとHUDに表示され、再操作で復旧できる。

## 合格判定

| 領域 | 合否 | 証跡 |
|---|---|---|
| Android build / unit test | | |
| Hi Rokid auth / AIDL | | |
| AIキー入力 | | |
| 写真 / OCR | | |
| Analyzer / Solver | | |
| HUD | | |
| LED / 撮影通知 | | |
| 中断復帰 | | |

未実施項目が一つでもある場合は「実機検証済み」ではなく「ビルド済み・実機検証待ち」と
記録します。

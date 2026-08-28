# CXR-L / Global Hi Rokid integration

この文書は、`android-relay` に入っている実装の契約を説明します。Windows と
Android スマホを使う導入手順は
[windows-android-real-device-setup.md](windows-android-real-device-setup.md)
を正本としてください。

対象は Android client `0.3.5`、Glasses View contract `1.8.0` です。

## 結論

`TakanariShimbo/CxrGlobal` 自体は vendoring、submodule、ソースコピーのいずれでも
取り込んでいません。代わりに次の形で、必要な Global 化をこのリポジトリ内に実装して
います。

- `android-relay` が Rokid 公式 AAR
  `com.rokid.cxr:client-l:1.1.1` を Rokid Maven から取得する。
- AAR に含まれる公開 AIDL 型を使う。
- `RokidGlobalLink` が Global Hi Rokid
  `com.rokid.sprite.global.aiapp` の認可 Activity と
  `IMediaStreamService` へ接続する。
- Rokid の AAR バイナリはリポジトリへコピーしない。

したがって、Windows 側で別途 CxrGlobal を clone する必要はありません。ただし、公式
AAR の取得には初回ビルド時のインターネット接続が必要です。

## 実装済みの接続面

| 機能 | 使用する CXR-L 面 | リポジトリ内実装 |
|---|---|---|
| Hi Rokid 認可 | `AUTHORIZATION` Activity、`auth_token` | `RokidGlobalLink.authorizationIntent` |
| サービス接続 | `MEDIA_STREAM_SERVICE`、`auth_token`、`auth_package` | `RokidGlobalLink.connect` |
| グラス接続状態 | `IDeviceStatusCallback` | `onGlassesConnected` |
| 写真撮影 | `takePhoto`、`IImageStreamCallback` | `takePhoto` / `onImageReceived` |
| HUD | `openCustomView` / `closeCustomView` | `showHud` / `HudLayout` |
| グラス入力 | user `onCustomViewClosed` / `IAiEventCallback.onAiKeyDown` (`AI-assist-start`) | `CustomViewCloseTracker` / `PressGestureInterpreter` |

Action 文字列と Global パッケージ名は `RokidGlobalLink` の一か所に隔離しています。
Hi Rokid または YodaOS 更新後は、この値とコールバックを実機で再検証してください。

## データフロー

```mermaid
sequenceDiagram
    participant G as Rokid Glasses
    participant H as Global Hi Rokid
    participant R as Android relay
    participant S as DocScan server

    R->>H: 認可・AIDL bind
    G->>H: タッチパッドをタップ
    H->>R: user CustomView close
    R->>H: AIMING・照準をopen
    H-->>G: 照準表示（takePhotoは0回）
    G->>H: 照準を確認してもう一度タップ
    H->>R: user AI-exit（シャッター）
    R-->>G: 1.5秒静止案内
    R->>H: takePhoto（1回）
    H->>G: カメラ稼働・LED点灯
    H->>R: JPEG callback
    R->>R: 日本語 ML Kit OCR
    R-->>G: CAPTURE_REVIEW・縮小プレビュー・未登録
    Note over R: 無操作の待機満了で自動登録（タップで撮り直し）
    R->>S: JPEG + OCR
    S->>S: Vision解析・問題分割・解答
    S-->>R: 最大3行 HUD
    R->>H: close + open CUSTOMVIEW
    H-->>G: 黒背景・緑文字
```

## グラス入力

公開CXR-Lから専用シャッターボタンのイベントは受信できません。全タッチジェスチャを
取得できるとも仮定しません。検証済みファームウェア（Hi Rokid `G1.12.10.0815` /
CXR-L service `1.0.0 code 10000`）がアプリへ配送するのは、ユーザー由来の`AI-exit`
だけです。押下時間は得られないため、そこから導出できるのは短押し1種類です。

| 状態 | グラスのタップ（`SHORT`） | 実装上の`DOUBLE_SHORT` / `LONG`（現行ファームでは未配送） |
|---|---|---|
| 接続完了・読取中 (`READY` / `READING`) | 次ページの `AIMING` を開始 | `DOUBLE_SHORT`は前ページ再撮影準備、`LONG`は読取完了・解析開始 |
| 撮影準備 (`AIMING`) | 静止案内を開き、ACK後1.5秒静止して `takePhoto` を1回だけ発行 | `DOUBLE_SHORT`は準備取消 |
| 静止待ち (`STABILIZING`) | 静止待ちを取り消す。撮影しない | 同左 |
| 撮影確認 (`CAPTURE_REVIEW`) | 同じページの `AIMING` を開始し照準表示（待機中なら自動登録を取消） | `LONG`は未登録写真を即時登録 |
| 閲覧中 (`REVIEW`) | 次の表示 | `DOUBLE_SHORT`は前の表示、`LONG`は閲覧終了・新規文書 |

右列は、より多くの信号を配送するファームウェア向けに残した経路です。現行ファームでは
到達しないため、ページ登録は `CAPTURE_REVIEW` の待機満了で行い、読取完了・新規・
`AIMING`の取消はスマホ側ボタンが正規の経路です。

通常の二段階撮影は、タップで照準を開き、構図確認後のタップで静止待ちを開始します。
`STABILIZING` 中のすべてのジェスチャーは準備を取り消し、写真を撮りません。公式操作では
ダブルタップが現在画面の終了なので、連続タップは標準メニューへ戻る場合があります。
`AI-exit` 後は650ms待ち、後続のCustomView openがなければ現在のDocScan画面を
再表示します。この復帰は状態を進めず、メニュー遷移のcloseを入力として破棄し、
`takePhoto`も登録APIも呼びません。`STABILIZING`中に別のジェスチャーが届いた場合は
旧timerを無効化し、静止待ちを自動再開しません。
復帰時にremote CustomViewがすでにopenなら再close/openせず、その表示を維持します。
ファームウェアが2回の入力をアプリへ`DOUBLE_SHORT`として実際に配送した場合だけ、
読取中は前ページの再撮影準備、撮影確認中は同ページの再撮影準備、閲覧中は前の表示、
`AIMING`中は準備取消として扱います。

これにより、撮影、同じページの再撮影、写真登録をグラスだけで完結できます。スマホ画面の「この写真を登録」「同じページを撮り直す」
「未登録写真を破棄」は入力イベントに端末差がある場合のフォールバックと診断・復旧用です。

## CUSTOMVIEW

`customViewUpdate` が成功を返しても表示が更新されない Global ビルドがあります。
リレーは黒背景の View をいったん閉じ、同じ View を再度開く方法を既定にしています。
白い中間フレームやアニメーション指示は生成しません。

リレー自身が更新のために要求したcloseは世代確認済みのCustomView lifecycleで除外し、
`onCustomViewClosed` callbackをユーザー入力に変換しません。ユーザーcloseと同じ
物理操作由来の`AI-assist-start`が近接配送された場合もdebounceして1操作へまとめます。
スマホログには
`source=user CustomView close` または `source=AI-assist-start` を残します。
同じCustomView世代のcloseは1回だけ入力にし、`isCustomViewOpened()`を確認できない
callbackは安全側で入力に変換しません。
撮影ガイドは要求世代のopen callbackとremote openの両方を確認するまで未確認とします。
非同期errorまたは3秒のACK timeoutでは準備を取り消して`takePhoto`を発行せず、
そのcallback epochをfenceします。「Hi Rokid認可・再接続」で新しいbindとcallback epochを
確立するまで、次のCustomView要求を発行しません。

撮影後は、JPEGを縮小・回転したプレビューと確認操作を正しいCustomViewとして
グラスへ表示し、スマホにも同じ写真を表示します。これは撮影済み写真の確認です。
`client-l:1.0.1` の公開静止画API面には撮影前ライブ映像とオートフォーカスのAPIが
ないため、ライブファインダーや合焦状態は表示しません。`AIMING` の照準は構図合わせ用です。

## 写真・OCR・解答

写真は互換入力ではなく、実機の主入力です。

1. 最初のタップで `AIMING` に入り、照準を表示する。この時点では `takePhoto` を
   発行しない。
2. 照準確認後の2回目のタップで静止案内を要求し、その世代のopen callback確認後から
   1.5秒の静止時間を取り、その後 `takePhoto(1920, 1080, 80)` を1回だけ発行して
   JPEGを受け取る。`AIMING` の取消はスマホの「撮影取消」で行う。静止待ち中は
   どのジェスチャーでもtimerを無効化し、撮影を取り消す。
3. Android 上の bundled Japanese ML Kit で OCR する。
4. JPEG と OCR をスマホ内の `CAPTURE_REVIEW` に保持し、未登録の写真として
   スマホとグラスの縮小プレビューで用紙の四隅、文字の輪郭、OCR文字数を確認する。
   初回撮影前に文書自体は作成するが、対象ページと次ページ番号は変更しない。
5. スマホの「この写真を登録」で明示確定してから、元 JPEG、ML Kit と同じ回転角、
   OCR を `/v1/documents/{id}/pages` へ送り、
   サーバーで OCR と同じ向きの PNG に正規化する。
6. `ROKID_ANALYZER=openai|gemini|claude` の画像対応 Analyzer が、必要に
   応じて画像から完全な転記と図表説明を生成する。
7. `finalize-reading` が問題を分割し、開始ページ画像を画像対応 Solver へ渡す。
8. `/review` の3行表示を CUSTOMVIEW へ送る。

端末 OCR が0文字の場合は警告しますが、待機満了でそのまま登録できます。
撮影確認中のタップ、またはスマホの「同じページを撮り直す」は、サーバーへ
送らず同じ `page_index` の `AIMING` へ戻します。照準確認後のタップまで再撮影しません。
「未登録写真を破棄」は保留写真を送信せず読取へ戻します。登録要求が成功するまで、
対象ページと次ページ番号は変わりません。
未登録JPEG、OCR、ページ番号、回転はアプリ専用領域へ保存し、アプリ再起動後も
`CAPTURE_REVIEW` に復元します。復元した写真も表示確認後に自動登録の待機へ入ります。
復元や状態遷移だけで自動撮影することはありません。

写真回転の既定は実機に合わせた90°です。スマホで0/90/180/270°を選んだ場合、
その値は「同じページを撮り直す」で撮る次の写真へ適用し、現在の保留写真は変更しません。
画像対応 Analyzer が未設定のまま確定して問題を検出できなかった場合は、セッションを
読取状態に戻します。ページを再撮影するか Analyzer を設定してから、同じページ番号を
置換して再度読取完了を実行できます。

Rokid Glasses のカメラは固定焦点で、公称被写界深度は34cm〜∞です。34cmは限界値
なので、運用では用紙まで40〜60cm離し、用紙中心を照準の「＋」へ合わせ、2回目の
操作となるタップ後1.5秒からcallbackまで静止します。ディスプレイFOVとカメラFOVが異なるため、
照準は正確な撮影境界ではなく、四隅は撮影後プレビューで確認します。公開APIから
フォーカス位置や合焦完了は取得できません。
12MPセンサーの公称解像度はCXR-L callbackの安全な転送サイズを意味しません。
実機では `takePhoto(4032, 3024, 80)` のJPEGがBinder上限を超えてcallbackなしに
なったため、既知NGとして使用しません。

### 撮影リースとタイムアウト

`client-l:1.0.1` の公開 `IMediaStreamService` は静止画について `takePhoto` と
`IImageStreamCallback` を提供しますが、撮影キャンセル／camera close API は公開して
いません。そのため、30秒のwatchdog満了を「カメラ停止」とは扱いません。

- 必須callbackの登録が1つでも失敗した接続では撮影しない。
- `takePhoto` は同時に1件だけ許可する。
- Binder例外で `takePhoto` の受理結果を確認できない場合も、撮影中の可能性があるため
  即時に安全停止し、遅延callbackまたはCXR-L service bindingの再作成まで次の操作を
  許可しない。
- 正常画像または明示的な画像エラーcallbackで撮影リースを解放する。
- タイムアウト後は、遅延callbackまたは実際のservice unbind/rebindを確認するまで、
  再撮影・読取完了・新規文書・設定変更を拒否する。グラスの接続状態callbackだけでは
  同じbindから遅延画像が届き得るため、リースを解放しない。
- タイムアウト後に届いた画像は、古い撮影か判別できないためアップロードせず破棄する。
- callbackはAIDL bindごとのepochに属する。切断・再接続前のbindから遅れて配送された
  callbackは、新しい撮影リースを完了せず、画像もアップロードしない。

これにより、前のカメラ状態が不明なまま次の撮影を重ねてLED点灯時間を延ばすことを防ぎます。

## 公開 API から確認できないもの

次の機能を実装済みとは扱いません。

- グラス搭載 GPT/Gemini の任意の認識文を外部アプリへ返すコールバック
- グラス搭載 AI の任意の回答を CXR-L から直接取り出すコールバック
- 全タッチジェスチャの AIDL 配送
- 撮影前ライブカメラ映像、オートフォーカス制御、合焦状態
- 専用シャッターボタンの入力イベント
- 全 Global Hi Rokid / YodaOS バージョンで同一の再描画動作

これらが将来公開 SDK に追加された場合は、現行の写真・サーバー解析経路を残したまま
別 Adapter として追加してください。

## プライバシー LED

LED はハードウェア/ファームウェア制御です。アプリは無効化・迂回・偽装しません。
ビルド成功だけでは確認にならないため、実機で「撮影中に点灯」「画像 callback 後に消灯」
「解答閲覧中は消灯したまま」を物理確認してください。シャッター音、フラッシュ、撮影表示も
公開 SDK で制御できると仮定せず、使用ファームウェアで実測します。

実験用 `scripts/rokid_led.py` は Android relay から到達できません。通常UI、Intent、
HTTP API、環境変数から実行できる設定も設けません。

## 参考

- [TakanariShimbo/CxrGlobal](https://github.com/TakanariShimbo/CxrGlobal)
- [Android relay README](../android-relay/README.md)
- [Windows + Android 実機手順](windows-android-real-device-setup.md)

# 撮影経路の実測と、固定秒数設計の見直し

2026-08-28 の実機セッション（F-51F / Global Hi Rokid / Rokid Glasses）で測った値と、
そこから確定した設計上の判断を記録します。ビルドが通ったことは根拠になりません。
ここに載せているのは実機で観測した値だけです。

対象: Android relay `0.3.6`（versionCode 11）、Hi Rokid G1.12.10.0815、
CXR-L service `1.0.0 code 10000`。

## 1. 実測値

単発 `takePhoto(1920, 1080, 80)`、A4 を 40〜60cm で枠内に置いた状態:

| 項目 | 実測 |
|---|---|
| `takePhoto` 要求から画像 callback まで | **5.2 秒** |
| JPEG | 147,398 バイト |
| 端末 OCR（bundled 日本語 ML Kit） | 671 文字 / 18 行 |
| 枠判定 | `COMPLETE#18` |
| entropy / edge variance | 6.888 / 497.892 |

用紙全体は枠に入っており、判定も `COMPLETE` です。不足しているのは
**文字の解像度**であって、構図でも枚数でもありません。

## 2. この 5.2 秒が壊す前提

`DocScanController` の自動バーストは「3 枚を 400ms 間隔で撮る」設計ですが、
1 枚あたり 5.2 秒かかる以上、実際の間隔を決めているのは `AUTO_SHOT_INTERVAL_MILLIS`
ではなく callback です。3 枚で 16 秒前後かかり、その間に紙と頭の角度は必ず変わります。

したがって「同じページを繰り返し撮って一番良い 1 枚を選ぶ」戦略は、
待ち時間を 3 倍にした上で、比較対象を別条件の写真にしてしまいます。
**1 ページ 1 枚に戻し、品質の予算を枚数ではなく解像度へ回すのが正しい方向です。**

サーバ側はこの経路を既に受けられます。`app/main.py` の finalize は
image analyzer による転写を端末 OCR より優先し（`extras["image_analyzed"]`）、
`POST /pages` は画像のみのページも受け付けます。

## 3. 状態を見ずに進む固定秒数の一覧

現行実装に混在している固定時間です。いずれも画像や端末の実状態を参照しません。

| 定数 | 値 | 置き場所 |
|---|---|---|
| `SHUTTER_STABILIZATION_MILLIS` | 1500 | `DocScanController` |
| `CUSTOM_VIEW_ACK_TIMEOUT_MILLIS` | 3000 | `DocScanController` |
| `AUTO_COMMIT_COMPLETE_MILLIS` | 4000 | `DocScanController` |
| `AUTO_COMMIT_UNVERIFIED_MILLIS` | 12000 | `DocScanController` |
| `AUTO_SHOT_INTERVAL_MILLIS` | 400 | `DocScanController` |
| `AUTO_PAGE_TURN_MILLIS` | 2500 | `DocScanController` |
| `AUTO_RETRY_IMMEDIATE_MILLIS` | 200 | `DocScanController` |
| `AUTO_UNREADABLE_BACKOFF_MILLIS` | 1200 | `DocScanController` |
| `SYSTEM_MENU_RECOVERY_DELAY_MILLIS` | 650 | `MainActivity` |
| `PROGRAMMATIC_CLOSE_TTL_MILLIS` | 2000 | `RokidGlobalLink` |

`AUTO_SHOT_INTERVAL_MILLIS` と `AUTO_RETRY_IMMEDIATE_MILLIS` は、5.2 秒の
callback の前では実質的に効いていません。

## 4. 修正済み: タップ経路が丸ごと塞がっていた原因

症状は「タップが効かない」「ダブルタップで閉じた後、撮影状態へ復帰しない」の 2 つ
でしたが、原因は 1 箇所です。

1. `RokidGlobalLink.handleCustomViewClosed` が close callback の中で
   `isCustomViewOpened()` を問い合わせていました。この機種は **どの close でも
   true を返します**（本日のログでも `remoteStillOpen=true`）。
2. `CustomViewCloseTracker.onClosed` は `remoteStillOpen` が true なら即座に
   「アプリ自身が閉じた」と判定して `false` を返していました。
3. 呼び出し側は `if (userInitiated && !remoteStillOpen)` と二重に絞っていたため、
   `onCustomViewClosedByUser()` は一度も呼ばれません。
4. 結果として `MainActivity` の 650ms 復帰タイマーも起動せず、
   `restoreGlassesViewAfterMenuExit()` は走りませんでした。

`0.3.5`（05f2f2a）は復帰処理の中身を直しましたが、引き金側が塞がったままでした。

### 直し方

サービスへの問い合わせをやめ、アプリ自身の記録だけで判別します。
`expectProgrammaticClose` は閉じる直前に**その世代番号**を記録しているのに、
その世代番号は使われていませんでした。ここを判別材料にします。

- 先頭の予約が現在の世代と一致する close は、自分のビュー切替の echo。
- 一致しなければ、利用者のタップ。

`remoteStillOpen` はビュー切替の echo を潰す役目を実際に担っていたため、
単に削除するだけでは `AIMING` 表示直後にシャッターが落ちる既知の不具合が再発します。
世代一致による判別はその役目を引き継ぎます。

## 4.5 実写の画像解析 — 解像度は律速ではない

2026-08-28、端末に残っていた実写（`pending-capture-v1.bin` から取り出した
1080×1920 の JPEG、147,398 バイト）を直接測りました。推測ではなく画素の実測です。

| 測定項目 | 実測値 | 参照値 | 判定 |
|---|---|---|---|
| 本文の列ピッチ（≒文字の一辺） | **37.0 px** | ML Kit 下限 16px、24px 超は利点なし | 十分。**不足していない** |
| 列の墨幅 | 15.0 px | — | — |
| 本文の占める幅 | 564 / 1080 px（52%） | — | 用紙は画面幅いっぱい |
| 紙の輝度 / 墨の輝度 | 196 / 155 | スキャン文書は概ね 245 / 30 | — |
| **コントラスト差** | **41 / 255（16%）** | 200 前後 | **致命的に低い** |
| **JPEG 密度** | **0.071 バイト/画素** | 文書撮影は 0.2〜0.5 | **圧縮しすぎ** |
| ラプラシアン分散 | 284 | — | 極端なぼけではない |

出典: ML Kit Text Recognition v2 の公式要件は「各文字は最低 16×16 px」、
「24×24 px を超えても精度上の利点は概ね無い」、「レターサイズの印刷文書には
720×1280 が必要な場合がある（用紙が画面を占める前提）」、および
「焦点不良は認識精度に影響する」。

したがって **読めない原因は解像度ではなく、コントラストと JPEG 圧縮** です。

### 計画の訂正

これまで想定していたスイープ「`4032x3024 q50`」は、画素数を 5.8 倍にする一方で
**品質を 80 から 50 へ下げます**。細線の再現はむしろ悪化し、5.2 秒の callback も
延びます。実行してはいけません。

公開 API で触れるつまみは `takePhoto(width, height, quality)` の 3 つだけで、
露出も焦点も制御できません。したがって次の実機セッションでは、変数を 1 つずつ
分離して 3 枚だけ撮ります。

1. `1920x1080 q95` — 圧縮だけを変える。バイト/画素が 0.2 を超えるか、
   OCR 文字数と確信度がどう動くかを見る。
2. `1920x1080 q80` を照明を強く均一にして撮る — コントラストだけを変える。
3. 上の 2 つで足りないときに限り `4032x3024 q80` — 解像度だけを変える。
   `q50` ではなく `q80` を使う。

なお、記憶に残っていた「A4 は画面幅の約 23% しか占めない」という前提は、
この実写では成り立ちません（52%、用紙自体は画面幅いっぱい）。無駄になっている
のは上部 36% の机と地図であり、これは撮影姿勢の問題です。

## 5. 次にやること

1. **`0.3.6` を実機へ入れ、タップが届くことを物理確認する。**
   グラスをタップし、logcat に `userInitiated=true` が出ること、
   ビュー切替の直後に意図しないシャッターが落ちないことの両方を見ます。
   これが取れるまで、他の撮影側の変更は入れません。
2. **解像度スイープ**（未実施）。`4032x3024 q50` などの上位プリセットで
   callback が返るか、返るなら所要時間と OCR 文字数がどう動くかを測ります。
   公開 API は `takePhoto(width, height, quality)` だけで、対応解像度の一覧は
   公式文書に記載がありません（`ar-independent-manager.rokid.com` の CXR-L 1.0.1
   "Photo Capability"）。実測でしか分かりません。
3. スイープの結果を見てから、バーストを 1 枚へ戻すかを決めます。
   先にバーストへ画像のみのフォールバックを足してはいけません。OCR が 0 文字だと
   `PageTextSimilarity` が前ページと区別できず、同じ紙が繰り返し登録されます。
4. 固定秒数のうち、実状態で置き換えられるものを個別に判断します。
   自動登録の 4 秒 / 12 秒は「操作者に見せていないものを送らない」という不変条件に
   直結するため、まとめてではなく 1 つずつ扱います。

## 6. 端末に残っているもの

`pending-capture-v1.bin`（149,406 バイト、02:49 時点）に、未登録の P1 が
1 枚残っています。OCR 671 文字、rotation 90。再インストールしても
アプリのデータは保持されるため消えませんが、次のセッションで
「登録」か「破棄」を選ぶまで宙に浮いたままです。

## 7. 公開 API で分かっていること

CXR-L 1.0.1 の写真面は以下だけです。ライブプレビューも動画ストリームもありません。

- `setCXRImageCbk(cbk: IImageStreamCbk)` — 撮影結果の callback を登録
- `takePhoto(width: Int, height: Int, quality: Int)`
- `onImageReceived(data: ByteArray?)` / `onImageError(code: Int, msg: String?)`

「撮る前に構図を見て判断する」ことは公開 API ではできません。判断できるのは
JPEG を受け取った後だけです。ここを前提に設計する必要があります。

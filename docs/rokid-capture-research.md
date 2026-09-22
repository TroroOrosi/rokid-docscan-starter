# Rokid スマートAIグラスの文書撮影 — 仕様と実装の境界

調査日: 2026-09-17。対象は利用中の **Rokid Glasses / RG-glasses**。
Rokid Style、Max、Air、法人向けGlass 3の仕様を流用しない。
本書は撮影再開の承認ではない。現行の停止条件は
`.agents/progress/pr37-offline-remediation.md` と `docs/capture-preflight.md` を維持する。

原寸全域タイル、非生成の明るさ補正候補と角度補正候補を組み合わせるPC入口は
[保存写真の原寸点検](capture-quality.md)。鮮鋭度も加工前の画素から測ります。
合成テストや補正画像を、実写真の画質保証・本流登録の合格にしません。品質ゲートは未接続です。

## 何を根拠にするか

| 項目 | 公開一次資料 / 既存の記録 | 実装での扱い |
|---|---|---|
| 写真 | 公式製品ページは12MP、3024×4032、F2.25。公式FAQはSony IMX681と109°を記載 [R1][R2] | 公称画素数を固定要求にせず、Camera2が列挙するJPEG寸法から既存どおり最大を選ぶ。手元端末で4032×3024が返った記録と縦横を区別する。 |
| 画角・軸 | 公式製品詳細はH77°、V94°、D109°、内向き3°。FAQの109°は対角に対応。表示の30°とは別 [R1][R2] | 表示の十字を撮影枠と見なさない。標準写真とCamera2出力のcrop・歪み・装着差は別途照合し、公称値だけでHUDを校正しない。 |
| 画面 | 現行公式FAQは480×640、30°と記載 [R2] | 古い検索断片でなく現行全文を優先する。既存端末記録と照合し、実View寸法に従う。 |
| メモリ | 公称2GB RAM [R1]。既存ログにはアプリの低メモリ終了がある | 端末RAM総量をアプリの使用可能ヒープと見なさない。高解像度Bitmapや連続プレビューを増やさない。 |
| AF / 近距離 | 公式製品詳細はAF非対応、被写界深度34cm〜∞を明記 [R1] | AF待ちやAFトリガーを解決策にしない。34cm未満は公称範囲外として診断するが、34cm以上も細字合格ではない。Camera2の能力・実画質は別途照合する [A1]。 |
| 焦点距離の単位 | 同じ製品詳細のFocal Lengthは「1.9 m」と記載 [R1] | 単位の整合性が疑わしいのでmmへ勝手に訂正・換算しない。CaptureResultのLENS_FOCAL_LENGTH(mm)と照合し、公開値を幾何校正へ使わない [A5]。 |
| 標準アプリの撮影機能 | 公式記事にはLLHDR、縦横写真、物理ボタン等 [R3] | 標準アプリの処理がサードパーティーCamera2へ同じ形で提供されるとは限らない。HDR、手ぶれ補正、露出変更を未確認のまま有効化しない。 |
| SDKの経路 | 公式開発者入口はCXR-Lのスマホ連携とCXR-Sのグラス上アプリを区別 [R4] | 現行`:glassdoc`のCamera2直接撮影と、凍結された`:app`のCXR-L撮影を混同しない。SDK更新・新しい経路の追加はしない。 |
| 撮影と転送 | 現行主経路はグラス上でJPEGを取得・原本保存し、Wi-FiでF-51Fサーバへ転送 | 撮影成功、原本保存、送信ACK、OCR、答案完成は別の成功条件。Bluetooth接続やHTTP成功を写真の鮮明さの証拠にしない。 |

公開情報より端末上の能力列挙・返却JPEGを優先するが、能力列挙も画質合格ではない。
既存の測定は `docs/hardware-measurements.md` と
`.agents/progress/pr37-predevice-handoff.md` に日付・firmwareとともに残す。
過去の7枚成功、露出+2EV時の4回タイムアウトを、新しいfirmwareで再実証したとは書かない。

## 文書撮影への含意

AF非対応のため、文字を大きくする目的で無制限に接近する方法は採らない。
公式の34cmは被写界深度の公称近端であり、漢字・ルビ・数式を読むための保証距離ではない。
レンズから紙までの距離、均一な照明、頭と紙の静止、紙の湾曲を先に確認する。

広角では「12MPの写真」と「文書に割り当たる画素数」は違う。
仮に公式のH77°/V94°がそのまま向き補正後のCamera2画像へ適用され、
光軸と平面が直交する歪みのない透視投影なら、距離34cmの写る範囲は
`幅 = 2 × 34 × tan(77°/2)` ≈ 54cm、縦 ≈ 73cmになる。
3024×4032の全画素を用いても、仮に3mmの一文字は原画像で約17画素、
現行OCRの2倍縮小後では約8画素という概算になる。
**これは幾何的な試算であり、実際の視野・クロップ・文字サイズの測定ではない。**
公式の内向き3°だけで、カメラと目の位置差や装着差を補正することもできない。

したがって、見開きが写るだけで合格としない。実際の文字を等倍で測り、
画像全体の縮小で細部を失っていないか確認する。
将来の選択肢は、確認済み紙面領域を高解像度で切り出してからOCRすることだが、
自動紙面検出が未成立の現状でOCR文字枠を紙の四隅の代わりにして実装しない。
今回の等倍切出しはPC診断だけで、グラス上のOCR入力方式を変更したものではない。

## 今回変えるところ / 変えないところ

`GlassCamera`で、画像を得られないと確定したCamera2失敗、バッファ喪失、撮影シーケンス中断を
受け取り、15秒の期限を待たずに既存UNKNOWN停止へ送る。世代の古いcallbackは現在の撮影を止めない。
ただし `CaptureFailure.wasImageCaptured()` がtrueなら画像が届く可能性があるため、
メタデータ失敗だけでは撮影を捨てず、元の期限でJPEGを待つ [A2][A3]。
結果メタデータだけで「撮影済み」とせず、画像と結果のcallbackの到着順も仮定しない。

受信JPEGは既存レビュー保存の8MiB上限をコピー前に適用する。空データ、JPEG以外、
不正な寸法は保存前に拒否する。Imageを閉じた後にImageReaderを閉じる [A4]。
メモリ不足や個別のclose失敗でも、残りのリソースの解放を試みて一度だけ失敗を通知する。
これはプロセス全体のLOW_MEMORY解消や、物理カメラ・LEDの停止を証明しない。

撮影能力と返却結果から、限定した数値だけを `DocScanGlassDoc` logcatへ記録する。
露光時間(ns)、ISO、AE/AF/AWB状態、焦点距離情報、JPEG寸法などであり、画像、OCR本文、
GPS、顔情報、資格情報、任意のvendorメタデータは書かない。欠落値はunknownのままにする [A1][A5]。
撮影結果がJPEGより後に届かなかった場合、診断のためにカメラを保持・再撮影しない。

**維持:** JPEGサイズ選択、TEMPLATE_STILL_CAPTURE、JPEG_ORIENTATION=0、別途rotation=270、
3枚burst、retry、15秒の上限、実画像表示ACKからの3秒確認、操作割当、B5見開き設定、
署名鍵、原本、DB、送信保留、LEDのfirmware制御。Camera2のAF/AEトリガーや常時プレビューは追加しない。

## 保存写真で先に切り分ける

Runs on: Windows PC。カメラ・グラス・モデル・ネットワークを使用しない。
`docs/capture-preflight.md` の準備と原本退避後、既存JPEGを使う。
下記のパスは手元のコピーへ置き換え、出力先の下に毎回固有のサブディレクトリが作られる。

```powershell
py -3.12 -m scripts.capture_preflight .\saved-photo.jpg --rotation 270 --out .\capture-check-01
```

最初に `source-preview.png` で「冊子の実物の四辺」「机/PCの写り込み」「切れている図・柱・ノンブル」を見る。
十字・緑の表示枠ではない。明るさ補正済み画像だけでなく元の表示も確認する。
全体が収まることと、細い文字が読めることは別に判定する。

細字や図の領域を **向き補正後の画像に対する0..1座標** で明示すると、最大5領域、
各1024×1024画素以下の等倍PNGを作る。left,top,right,bottomの順。
原本と同じ画素を切り出すので、AIによる細部復元・拡大補間ではない。
次の数値は指定方法の例で、実際の冊子位置を検出した値ではない。

```powershell
py -3.12 -m scripts.capture_preflight .\saved-photo.jpg --rotation 270 --out .\capture-check-02 --details '[[0.45,0.45,0.55,0.55]]'
```

`detail-1.png` を100%倍率で見て一文字の実際の縦横画素を測る。
行間、列間隔、文字枠全体を一文字の大きさとして代用しない。
測った値が24×30画素だった場合の計算例:

```powershell
py -3.12 -m scripts.capture_preflight .\saved-photo.jpg --rotation 270 --out .\capture-check-03 --glyph-pixels 24 30
```

現行OCRでは4032×3024はsample=2、向き補正後の入力は概算1512×2016。
24×30の一文字は概算12×15になり、ML Kitの16×16程度以上という一般的目安を下回る [G1]。
これは元の写真を見て計算するもので、文字の自動検出やOCR実行ではない。
16画素以上でもブレ・反射・字体・数式などで認識を失敗し得るため、合格判定にはしない。
表示用sample=4とOCR用sample=2を混同しない。

撮影時に実測した距離が残っている場合だけ `--distance-cm` にレンズから紙までのcm値を指定する。
写真やEXIFから距離を推測しない。公称34cmより近いと警告相当の診断値を残し、
値がなければ未測定、34cm以上でも未合格のままにする。

```powershell
py -3.12 -m scripts.capture_preflight .\saved-photo.jpg --rotation 270 --out .\capture-check-04 --distance-cm 30
```

レポートにはEXIFが存在する場合に限り、露光時間、F値、ISO、焦点距離の数値を抽出する。
EXIF欠落を0や「適正露出」に置き換えない。EXIFや輝度分布だけでは、
暗さ、モーションブラー、ピンぼけ、紙の湾曲、圧縮、低コントラストを単独の原因へ断定できない。

通常の診断はJPEG縮小読込を使う。一方、等倍切出しや明示四隅による台形補正はPCで原寸画像を
復号するため、メモリ使用量が増える。グラス上でこのPython処理を実行しない。
生成画像には元のEXIFをコピーしない。`acceptance=not_evaluated`、`ocr=not_run`を維持する。

## 停止解除後の実機確認 — 順番を固定する

Runs on: Windowsに接続したRokidとF-51F。**利用者が追加撮影を承認してから**。

1. 既存の署名・原本・pending・manifestを保全し、PCの同一署名鍵でビルドする。
   CI APKをそのまま入れず、更新手順は `docs/capture-preflight.md` に従う。
2. まずB5見開きの既存設定を維持。レンズの汚れ、用紙の反り、反射、影を確認し、
   紙面を均一に照らす。目線だけでなくカメラのある顔を紙面へ向ける。
   表示の十字を実物の四辺に合わせようとせず、返却JPEGで位置を確認する。
3. 利用者が準備した通常操作による限定撮影で、支持した紙・頭の静止、距離、照明条件、
   firmware、APK、寸法、露光時間・ISO・AF状態を記録する。
   34cm未満の接近は公称被写界深度外。34cm以上の適正距離は細字の実測で決める。
   公称AF非対応と端末のAFモード・校正種別を照合する。AFモードがOFFのみ、かつ最短焦点距離0と
   報告されればCamera2上の固定焦点として扱うが、0mまで合焦する意味ではない [A1]。
   校正が不明の焦点パラメータをメートルへ換算しない。
4. 原本の四辺、文字、図、数式をPCの等倍画像で確認し、グラス内の確認表示との違いを記録する。
   見開きで細字が不足する場合だけ、同じ資料の片側単頁と比較する。単頁へ勝手に既定変更しない。
5. 画質が確認できてから、原本保存、送信ACK、OCR、図付き答案の順に短い一周を確認する。
   カメラエラーとWi-Fi/HTTPエラーを別々に記録する。UNKNOWNで自動再送・再撮影しない。
   終了は既存のダブルタップ後、最後のレビューを操作せず待つ。3秒期限を延ばさない。

ログ取得だけでは撮影を開始しない。serialは現在の接続を確認した値を使う。
全logcatには個人情報が混じり得るので、限定タグをローカル保存し公開前に確認する。

```powershell
adb -s $GlassSerial logcat -d -v time -s DocScanGlassDoc > .\capture-camera-local.log
```

連続20〜40ページ、録音併用、発熱・電池・光学表示、AP＋携帯回線の受け入れは別途必要。
LEDを無効化・隠蔽・偽装・迂回しない。追加の外部LED監査を勝手に要求しない。
APIのclose完了と物理停止も同一視しない [A6]。

## 一次資料

全資料の確認日: 2026-09-17。公開ページの記載は所有端末での動作保証ではない。

- [R1] Rokid公式製品ページ: https://global.rokid.com/ja/products/rokid-glasses
- [R2] Rokid公式FAQ: https://global.rokid.com/pages/faqs
- [R3] Rokid公式撮影紹介: https://global.rokid.com/blogs/glasses/shoot-with-rokid-glasses-easy-photo-video-walkthrough
- [R4] Rokid公式開発者入口: https://open.rokid.com/
- [A1] Android CameraCharacteristics: https://developer.android.com/reference/android/hardware/camera2/CameraCharacteristics
- [A2] Android CaptureCallback: https://developer.android.com/reference/android/hardware/camera2/CameraCaptureSession.CaptureCallback
- [A3] Android CaptureFailure: https://developer.android.com/reference/android/hardware/camera2/CaptureFailure
- [A4] Android ImageReader: https://developer.android.com/reference/android/media/ImageReader
- [A5] Android CaptureResult: https://developer.android.com/reference/android/hardware/camera2/CaptureResult
- [A6] Android CameraDevice.StateCallback: https://developer.android.com/reference/android/hardware/camera2/CameraDevice.StateCallback
- [G1] Google ML Kit Text Recognition v2 (Android): https://developers.google.com/ml-kit/vision/text-recognition/v2/android

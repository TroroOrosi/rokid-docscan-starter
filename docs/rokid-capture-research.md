# Rokid スマートAIグラスの文書撮影 — 仕様と実装の境界

調査日: 2026-09-17、一次資料再照合2026-09-23。対象は利用中の **Rokid Glasses / RG-glasses**。
Rokid Style、Max、Air、法人向けGlass 3の仕様を流用しない。
本書は撮影再開の承認ではない。最新の利用者訂正と停止範囲は
[現在の進捗記録](../.agents/progress/archive/pr37-capture-quality.md)を参照する。
以前の試験順と6枚の比較案は履歴として残す。最新の5方向の点検と席の制約は末尾を参照する。
追加撮影は停止し、距離の正確な測定や後退を必須にしない。

原寸全域タイル、非生成の明るさ補正候補と角度補正候補を組み合わせるPC入口は
[保存写真の原寸点検](capture-quality.md)。鮮鋭度も加工前の画素から測ります。
合成テストや補正画像を、実写真の画質保証・本流登録の合格にしません。品質ゲートは未接続です。

## 何を根拠にするか

| 項目 | 公開一次資料 / 既存の記録 | 実装での扱い |
|---|---|---|
| 写真 | 公式製品ページは12MP、3024×4032、F2.25。公式FAQはSony IMX681と109°を記載 [R1][R2] | 公称画素数を固定要求にせず、Camera2が列挙するJPEG寸法から既存どおり最大を選ぶ。手元端末で4032×3024が返った記録と縦横を区別する。 |
| 画角・軸 | 公式製品詳細はH77°、V94°、D109°、内向き3°。FAQの109°は対角に対応。表示の30°とは別 [R1][R2] | 表示の十字を撮影枠と見なさない。標準写真とCamera2出力のcrop・歪み・装着差は別途照合し、公称値だけでHUDを校正しない。 |
| 画面 | 現行公式FAQは480×640、30°と記載 [R2] | 古い検索断片でなく現行全文を優先する。既存端末記録と照合し、実View寸法に従う。 |
| メモリ | 公称2GB RAM [R1]。既存ログにはアプリの低メモリ終了がある | 端末RAM総量をアプリの使用可能ヒープと見なさない。高解像度Bitmapや常時プレビューを増やさない。末尾の測光は撮影要求の既存期限内だけ、画素を保存しない。 |
| AF / 近距離 | 公式製品詳細はAF非対応、被写界深度34cm〜∞を明記 [R1] | AF待ちやAFトリガーを解決策にしない。34cm未満は公称範囲外として診断するが、34cm以上も細字合格ではない。Camera2の能力・実画質は別途照合する [A1]。 |
| 焦点距離の単位 | 同じ製品詳細のFocal Lengthは「1.9 m」と記載 [R1] | 単位の整合性が疑わしいのでmmへ勝手に訂正・換算しない。CaptureResultのLENS_FOCAL_LENGTH(mm)と照合し、公開値を幾何校正へ使わない [A5]。 |
| 標準アプリの撮影機能 | 公式記事にはLLHDR、縦横写真、物理ボタン等 [R3] | 標準アプリの処理がサードパーティーCamera2へ同じ形で提供されるとは限らない。HDR、手ぶれ補正、露出変更を未確認のまま有効化しない。 |
| SDKの経路 | 公式開発者入口はCXR-Lのスマホ連携とCXR-Sのグラス上アプリを区別 [R4] | 現行`:glassdoc`のCamera2直接撮影と、凍結された`:app`のCXR-L撮影を混同しない。SDK更新・新しい経路の追加はしない。 |
| 撮影と転送 | 現行主経路はグラス上でJPEGを取得・原本保存し、Wi-FiでF-51Fサーバへ転送 | 撮影成功、原本保存、送信ACK、OCR、答案完成は別の成功条件。Bluetooth接続やHTTP成功を写真の鮮明さの証拠にしない。 |

公開情報より端末上の能力列挙・返却JPEGを優先するが、能力列挙も画質合格ではない。
既存の測定は `docs/hardware-measurements.md` と
`.agents/progress/archive/pr37-predevice-handoff.md` に日付・firmwareとともに残す。
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

## 2026-09-17時点の実機確認順 — 以後の指示は末尾優先

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

## 2026-09-22再照合と比較撮影の提案

Runs on: 調査はWindows PCと公開一次資料。撮影案は同じRokidの標準カメラで行う部品測定であり、会場経路・GPT解析の試験ではない。追加撮影は利用者の確認後。

保存画像の補正だけでは光学系・標準ISP処理・アプリの撮影手順を切り分けられない。
過去に本書へ公式情報を残していても、今回の判断へ照合・適用せず、比較撮影を提案しなかった。
利用者の「外部ソースや公式情報をもとに分析し、実際に何枚か撮影する必要がある」を優先する。
実機停止を、必要な測定の設計・提案まで止める理由にしてはいけない。

| 一次資料と現物の照合 | 今回の結論 |
|---|---|
| [現行公式FAQ](https://global.rokid.com/pages/faq): Sony IMX681、12MP、F2.25、撮影109°、表示30°。上の旧FAQ URLはここへ転送。 | 表示枠と撮影範囲を同一とする根拠はない。実際のcrop・装着時のずれは写真で測る。 |
| [公式ドイツ製品詳細](https://de.rokid.com/de-de/products/rokid-glasses): H77°/V94°/D109°、AF非対応、被写界深度34cm〜∞。旧global製品URLは今回404。 | 34cmは文字読取の保証距離ではない。40/50/60cmは比較点であって適正距離の決定ではない。地域仕様と所有機の一致は実測で補う。 |
| [公式撮影紹介](https://global.rokid.com/blogs/glasses/shoot-with-rokid-glasses-easy-photo-video-walkthrough): LLHDRを紹介。 | 標準写真を対照にする。第三者Camera2に同じHDR処理が入るかは未確認。標準が良好ならアプリ経路の差を優先して追う。 |
| [Android AE状態](https://developer.android.com/reference/android/hardware/camera2/CameraMetadata#CONTROL_AE_STATE_SEARCHING): 値1はSEARCHING。API 21からの定義で、所有機API 32にも該当。 | 今回の結果4件がすべて1。露出が未収束のまま撮影された可能性を調べる。これだけで暗さの単一原因とは断定しない。 |
| [Android固定焦点の定義](https://developer.android.com/reference/android/hardware/camera2/CameraCharacteristics#LENS_INFO_MINIMUM_FOCUS_DISTANCE): minimumFocusDistance=0は固定焦点。 | 所有機はAFモード[0]、min_focus=0、校正APPROXIMATE。公開AF非対応と整合。AF待ちを解決策にしない。 |
| [GoogleのOCR入力条件](https://developers.google.com/ml-kit/vision/text-recognition/v2/android#input-image-guidelines): 一文字16×16px程度以上を推奨し、ピント不良では再撮影を挙げる。 | 12MPという全画面寸法で合格にせず、同じ細字の実画素と判読を原寸・縮小後で比較する。 |

現在の接続はread-onlyの端末列挙でRG_glassesとF-51Fを確認。
グラスの `ro.build.version.incremental` は `1.25.015-20260903-150201`。
保存したcamera dumpではAE=ON、最後のAE状態SEARCHING、crop=[0,0,4032,3024]。
最終JPEGの露光時間10ms・ISO50は事実だが、照度未測定なので適正露出の値とは扱わない。
`GlassCamera`はセッション構成後ただちに静止画を要求する。単なる待ち時間追加・+EV・HDRの
強制指定を対照なしで採用しない。SDK別経路のHDR提供可否も未確認であり、変更していない。

### 旧案: 標準カメラ6枚（承認後に実施方法を撤回）

Runs on: 所有Rokidの標準カメラ。PCはJPEGを読み取りコピーして比較するだけ。APK更新・通常の読取・GPT送信は行わない。

**下の手順は履歴であり、続行しない。** 距離指定を相対指定へ変えても、離れられる席を前提に
している欠陥は残った。最新の制約と再設計は次節を優先する。
利用者は6枚の撮影を承認したが、最初の2枚後に正確な高さ・距離の測定は困難と指摘した。
40/50/60cmを実測値にしてはいけない。「近め・少し離す・さらに離す」の相対位置で比較し、
距離は全件未測定とする。撮影済み2枚の撮り直しや、定規の使用を要求しない。

1. 同じ問題ページを平らに支持し、照明とページの向きをできる範囲で固定する。
   見開きが写っても追加cropせず原本を残す。判定対象は同じ側のページに固定する。
2. 現在の位置、少し離れた位置、さらに離れた位置で各2枚。無理な姿勢や厳密な測距を求めない。
   紙面・文字の画像内の実画素数で比較する。2枚はブレ・ばらつきを見つけるためで、統計的保証ではない。
3. 標準カメラの写真機能を使い、現在の解像度・縦横比を記録して途中で変えない。
   物理ボタンの短押しは公式の既定操作だが変更可能なので、現在の割当を確認する。
4. 新規6枚を元JPEGのままPCへコピーしてSHAと寸法を保存する。共有ストレージの
   `/sdcard/DCIM/Camera` は現在read-onlyで存在確認済みだが、新写真の出力先は撮影後に照合する。
   Hi Rokidの一括取込は公式FAQ上グラスの写真を削除するため、この測定では使わない。
5. 同じ文字領域を原寸で比較し、紙面輝度・白飛び・中心/周辺のぼけ・一文字の画素数・
   紙面四辺と写る範囲を記録する。取れる場合だけEXIFの露光時間/ISOを使う。
   正解は先に固定した文字領域を人が確認する。OCR文字数の多さを精度と呼ばない。

この6枚は標準カメラの基準測定。距離不明の旧アプリ写真との比較だけで因果を決めない。
次は同じ距離・照明・紙面でアプリ経路を対照撮影する必要がある。
その前に、撮影だけで終了し送信へ進まない経路をPCで確認・準備する。
現行「通常の読取」はこの目的には使わない。露出手順の比較はその後に一条件ずつ行う。

## 5方向の再点検と、席の制約から組み立てる測定

Runs on: 再点検・既存写真の比較はWindows PC。追加撮影・APK更新・通常読取・GPT送信は停止。

利用者の訂正: 近づくことはできても、離れることは席の条件次第で難しい。
最新2枚も普段の着席位置の基準とは限らない。距離・姿勢を写真から推定しない。
目的は、その席で無理なく取れる姿勢の範囲で、必要な単ページ／見開き全体と、読める文字を
同時に確保すること。枚数を消化することや、枠いっぱいに表示することを合格条件にしない。

### 現物・実ソースによる5方向の結果

確認対象は `5981c3a` の主経路。グラフ索引は2026-09-14で古く、coverage確認後に現行ソースを読んだ。
これは全コードの無欠陥保証ではなく、取得→OCR→保存・送信→分割・解析→答案取得の境界点検。

| 方向 | 確認した事実と影響 | 優先する対応 |
|---|---|---|
| 目的達成 | `HudView.drawGuide` は十字と単頁／見開きの表示だけ。`guide` は十字の大きさ、`spread` は表示用で、撮影crop・紙面分割・OCR範囲へ伝わらない。`JapaneseOcr.decodeSubsampled` は背景込み全画面を4032→2016へ縮小。 | 表示の倍率と処理対象の紙面を分離する。原寸にある文字をOCR前に失わない入力を、メモリ上限内で比較する。 |
| 全体への影響 | `DocScanController.beginAutoBurst` は紙面検出前に3枚撮る。`ShotScore.of` は全画面のOCR文字数×confidenceを順位に使うので背景文字も混入し得る。`finishAutoBurst` はOCRゼロ等なら未保存で再撮影、41連続burst以降も間隔を延ばすだけ。`confirmPendingCaptureNow` は紙面・細字の品質証拠を検査せず可視3秒後に保存・送信へ進む。 | 再撮影・OCR・送信を増やす前に、候補保全と品質判定の境界を直す。図だけのページを自動経路で捨てる条件も同時に扱う。撮影数・retryは未変更。 |
| 事実確認 | PCの`capture_admission`は本流未接続、承認profileも空。サーバは画像を回転してPNG保存し、この経路ではOCR用の半分画像を保存しない。標準JPEG8枚は3024×4032、EXIF露光16.6〜25ms・ISO191〜318。旧アプリ結果は約9〜10ms・ISO50〜56、AE=SEARCHING。 | 「HUDが明るい」「PC部品の試験が通る」を実画像・OCRの改善と扱わない。露出の差は確認できるが、同時・同構図ではないので暗さの原因を断定しない。 |
| 未確認事項 | 標準8枚の距離・姿勢・撮影群、席で可能な移動範囲、Camera2と標準アプリの処理差、同時preview/JPEGの画角とメモリ、実ML Kitの文字別精度、zoom適用時の効果は未確認。列挙範囲は末尾で現物dumpを照合。 | 既存写真で答えられる問いを先に処理し、追加測定は残った問いと判定条件を一対一にする。0.5倍やデジタル倍率による解像力向上を仮定しない。 |
| 指示漏れ | 「離れる」を利用可能な操作として仮定した。1枚で必要資料が揃うか確認せず終了を案内した。`layout`は行頭の`(A)`／`(B)`も設問に分割する。サーバは小問ごとに保存するが、Activityは最終化応答後にbundleを1回取得する。 | 撮影だけでなく共通資料の欠落、偽の設問による余分な解析、できた答案が届かない待ちをRP-11/12/15へ戻す。全問HTTP待ちを単なるGPT待機で代替しない。 |

主な根拠: [撮影・登録](../android-relay/relaycore/src/main/java/dev/rokid/docscanrelay/DocScanController.java)、
[OCR](../android-relay/relaycore/src/main/java/dev/rokid/docscanrelay/JapaneseOcr.java)、
[HUD](../android-relay/glassdoc/src/main/java/dev/rokid/docscanglass/doc/HudView.java)、
[Activity](../android-relay/glassdoc/src/main/java/dev/rokid/docscanglass/doc/DocScanGlassActivity.java)、
[最終化](../app/main.py)、[設問分割](../app/layout.py)。
合成入力「問1＋選択肢(A)(B)」を`segment_problems`へ渡すと3問題になる。実写真で同じ誤分割が
起きたと断定する再現ではない。小問解析は同じ最終化HTTP内の逐次処理で、端末側はその要求だけ
read/call timeout=0。受付・進捗・結果取得の分離は未実装。
完了録音の部分復元、文書作成要求ID、終了保存のUI待ち、AP＋携帯回線の通し試験も未完として保持する。
凍結phone relay・旧HUD・手動貼付・採用しないローカルLLMは新規改善対象へ戻さない。

### 拡大縮小を混同しない

| 操作 | 変わるもの | 今回の判断 |
|---|---|---|
| HUDの拡大・縮小 | 表示上の大きさ | センサーが写す範囲や原本の細字は変わらない。現行レビューは全体を縮小表示するだけで、細字検査の拡大機能はない。 |
| Camera2のzoom/crop | センサーの利用範囲と出力への変換 | Android公式ではcropはデジタルzoom、出力比率でも追加cropが入る。zoomRatioはAPI 30から。所有機の列挙値は1〜8（末尾）、実効果は未確認。 |
| 紙面を原寸で切り出してOCR | 背景量とOCRへ残せる文字画素 | 全画面を縮小してから切ると失った細部は戻らない。原寸領域の順次復号は候補だが、紙面検出・境界の欠落／重複・メモリと併せて検査する。 |
| 保存画像の拡大補間・明暗補正 | 画素の表現 | OCRの結果が変わる可能性は比較するが、新しい光学情報を得た証拠にはしない。読めない文字を生成補完しない。 |

[AndroidのzoomRatio](https://developer.android.com/reference/android/hardware/camera2/CaptureRequest#CONTROL_ZOOM_RATIO)と
[crop定義](https://developer.android.com/reference/android/hardware/camera2/CaptureRequest#SCALER_CROP_REGION)を再照合。
cropだけでは元の全視野より広くならない。公式の0.5倍の例は超広角への切替を持つ仮想機種で、
所有グラスの能力証拠ではない。Context7が返したAPI 36のzoomMethodも所有機API 32へ適用しない。

### 次の測定を成立させる順序

Runs on: まずPCの既存原本。後段の実機比較は、測定用の撮影だけで終了する経路を準備してから改めて具体化する。

1. **席の制約を固定する。** 普段の姿勢を出発点とし、後退や正確なcm測定を必須にしない。
   近づける範囲も快適さ・紙面の欠け・固定焦点の実画質で制限する。今回はその範囲自体が未確認。
2. **全体の収まりと細字を別々に見る。** 既存原本で四辺・綴じ目・遮蔽と、同じ文字・数式・図ラベルを
   原寸で確認する。8枚は条件統制した距離比較ではなく探索資料。最新2枚を校正値へ昇格させない。
3. **まず同一原本で処理差を比較する。** 全画面縮小、紙面／領域を原寸で保持した入力、必要な補間を
   同じ参照文字で比較する。中心だけでなく周辺・綴じ目、最小文字、数式を含める。文字数や16px目安
   だけでは合格にしない。Tesseractの結果を実ML Kitの精度と呼ばない。
4. **収まらない場合も「離れて」で終えない。** 実画像の対応範囲内で倍率・cropを戻す余地を調べる。
   全視野でも見開きが入らなければ単ページを比較する。単ページでも無理なら、重なりを保つ分割取得と
   自動の対応付けを別候補として評価し、利用者に小問ごとの手作業を求めない。分割取得は未実装で、
   今回の解決策として採用済みにしない。全体は入るが細字が不足する場合も、単に倍率だけで合格にしない。
   同じ距離で単頁へ切り出すだけでは、撮影時の一文字の元画素数は増えない。全画面縮小の回避とは区別する。
5. **撮影側の比較は問いを限定する。** 同じ通常姿勢・紙位置で標準とCamera2を比較し、露出安定と
   細字が異なるかを見る。姿勢と露出と倍率を同時に変えない。各条件の撮影直後に原本を対応付ける。
   何を変えれば改善するかの根拠がない連写・撮り直しは止める。判読と必要資料が揃うまで解析へ進めない。

既存8枚を処理前後でSHA照合し `originals_unchanged 8 / 8`。最新画像の同じ領域を原寸580×460と
Pillow BOX半分290×230で確認した。元画素を保持した比較であり、OCR精度・普段の席での合格は未評価。
標準写真とアプリ写真の非対照比較だけで、グラスの限界や最適距離・倍率は決められない。

## 2026-09-23: 同一文字の比較と、撮影要求内の露出準備

Runs on: 比較・実装・自動試験はWindows PC。実機撮影・APK導入・GPT送信は停止のまま。

PR37のmerge後、[PR38](https://github.com/TroroOrosi/rokid-docscan-starter/pull/38)で
同一原本の入力差と、AE未収束でも即時撮影する経路を扱う。席から後退できることを前提にしない。

### 標準写真の同じ33文字

私有 `data/device-setup/pr37-camera-baseline-20260922-225825/originals/img-20260922-230638-13-P0-0.jpg` の
SHA-256は `15e4ea0d87e8537ca027b251ac58b84e89baaca1a232db9f64dbffd068abcd1f`。
右ページの同じ縦書き4列、原本座標 `[2004,2000,2152,2200]` を比較した。
参照はOCR前に固定したエージェントの目視転記であり、利用者の正解ラベルや独立評価資料ではない。
最初の切出しは右列が端へ接していたため、目視後に右へ12px余白を増やし、全方式を同じ領域で再実行した。

`py -3.12 data/device-setup/pr37-camera-baseline-20260922-225825/compare_text.py`
→ `original_unchanged: true`、下記の編集距離、exit 0。
Tesseract 5.5.0 / `jpn_vert --psm 5`。NFKC後の英数字・日本語を比較し、参照は33文字。

| 入力 | 領域の画素 | 誤り数 / 参照文字数 |
|---|---|---|
| 原寸 | 148×200 | 6 / 33 |
| 全画面をBOXで半分にして同領域を切出し | 74×100 | 29 / 33 |
| 半分の領域をLANCZOSで元の寸法へ補間 | 148×200 | 7 / 33 |
| 原寸の領域をLANCZOSで2倍へ補間 | 296×400 | 7 / 33 |

この領域では縮小前の画素を保持する方が良かった。補間で認識が変わっても原寸を超える改善ではなく、
一律の拡大処理は採用しない。数字・数式・綴じ目・他の紙面全体を評価したものではない。
Androidの復号/RGB565/ML Kitの再現でもない。CQ-5と原寸領域OCRの比較は残す。
参照本文・OCR本文・派生画像は私有 `text-comparison/` だけに保存した。

### 公式仕様と現物の照合

既存 `data/device-setup/pr37-resume-20260922-214723/camera-after.txt`（firmware `1.25.015-20260903-150201`、API 32）を再読した。
`zoomRatioRange=[1,8]`、`flash.info.available=FALSE`、YUV列挙に640×480/320×240がある。
「zoomの列挙範囲も未確認」を訂正する。0.5倍を提供する証拠はなく、1倍より広くできると案内しない。
列挙値は実際の画角・細字・標準アプリとの一致を保証しない。zoom操作は今回追加しない。

[CameraDeviceの保証ストリーム組合せ](https://developer.android.com/reference/android/hardware/camera2/CameraDevice#createCaptureSession(java.util.List%3Candroid.view.Surface%3E,%20android.hardware.camera2.CameraCaptureSession.StateCallback,%20android.os.Handler))
にはYUV PREVIEW＋JPEG MAXIMUMがある。現ソースは列挙された同じ縦横比、640×480画素以下の
最大YUVを測光用に選び、元の最大JPEGと同じセッションへ接続する。端末での同時出力は未検証。

[AE状態の公式定義](https://developer.android.com/reference/android/hardware/camera2/CaptureResult#CONTROL_AE_STATE)
に基づき、CONVERGEDだけでJPEGへ進む。null/SEARCHING/INACTIVE/LOCKED/FLASH_REQUIREDは収束成功にしない。
測光はTEMPLATE_PREVIEW、JPEGは既存TEMPLATE_STILL_CAPTURE、どちらもAE ON。AF・EV補正・
フラッシュ・AE lock/precapture triggerは追加しない。収束が来なければ既存15秒でUNKNOWN停止する。
収束時に期限を延長せず、同じ世代でJPEGは一要求だけ。測光停止の遅延callbackはJPEGを再要求しない。
測光のAE状態が変わった時だけ世代・状態・経過時間を記録し、不明のままのtimeoutと調整中を切り分ける。

[ImageReaderの契約](https://developer.android.com/reference/android/media/ImageReader#acquireLatestImage())
に従い測光readerのmaxImagesは2とし、acquireLatestImageのImageを即時closeする。
Bitmap化・保存・OCRはしない。JPEG成功・失敗・closeは両readerとsession/deviceを解放する。
収束待ちでカメラが開いている時間は増え得る。実機の待ち時間、電力、メモリ、最終JPEGの露出は未測定。
プレビューの収束は最終JPEGの良否・文字の可読性ではなく、紙面検出・品質登録ゲートも未完成のままである。

## 2026-09-23: 3領域で縮小・補正・分割を比較

Runs on: Windows PCの保存済み原本のみ。Tesseract 5.5.0 / jpn_vert / psm 5。
実機・APK・GPTは操作していない。実装基準は `b7855d8`、PC比較部品のみを追加した。

上の33文字と同じ標準写真（SHA-256 `15e4ea0d87e8537ca027b251ac58b84e89baaca1a232db9f64dbffd068abcd1f`）で、
右紙面の3領域へ比較を広げた。原本は3024×4032、回転0。OCR前にエージェントが目視転記し、
切出しが文字に接した最初の候補を修正してから全方式の領域を固定した。
参照は利用者確認済みの正解ではなく、1資料の探索用109文字。数式・図・綴じ目・左紙面は含まない。
既存8枚の距離・姿勢・撮影組は依然不明であり、この1枚を着席基準にはしない。

| 領域 | 原本の矩形 left,top,right,bottom | 参照文字数 |
|---|---|---|
| kanji-1 | 2170,1990,2338,2210 | 33 |
| kanji-3 | 2004,2000,2152,2200 | 33 |
| kanji-5 | 1820,2020,1970,2275 | 43 |

空白を除去した後、NFCのコードポイント編集距離を数えた。句読点・符号は削除しない。
前節の英数字抽出とは異なる比較規則なので、異なる資料の数字をそのまま通算しない。
縮小は全画面のPillow BOXで、Androidの復号・RGB565・ML Kitの再現ではない。

| 試行 | kanji-1 / 33 | kanji-3 / 33 | kanji-5 / 43 | 誤り合計 / 109 |
|---|---|---|---|---|
| 原寸領域 | 9 | 6 | 6 | 21 |
| 全画面を半分に縮小して同領域を切出し | 32 | 29 | 21 | 82 |
| 半分の領域を元寸法へLANCZOS補間 | 9 | 7 | 10 | 26 |
| 原寸に既存の明暗補正 | 9 | 6 | 6 | 21 |
| 原寸を上下に二分し、上→下で結果を連結 | 19 | 21 | 27 | 67 |
| 上下分割に64pxの重なりを加え、同じ順で連結 | 24 | 26 | 30 | 80 |
| 再試行: 原寸を左右に二分し、縦書きの右→左で連結 | 7 | 6 | 20 | 33 |

上下分割では列の前後が離れ、重なり部分は重複する。左右に変えても3領域目で悪化した。
これは手動指定領域の単純二分の反例であり、既存1024pxタイル全体の実OCR試験ではない。
画素が全域を覆うことと、文章の欠落・重複・順序を保つことは別の検査が必要である。
今回は補正も分割も既定採用しない。原寸も21誤りが残り、画像登録の合格閾値にはできない。
OCRは判読の補助に留め、これをGPT向け全文生成やOCR由来の正解小問一覧へ戻さない。

再現コマンド（私有資料があるPCのみ）:
`py -3.12 -X utf8 data/device-setup/pr37-camera-baseline-20260922-225825/region-trials/run_compare.py`。
出力は同ディレクトリの `results.json`、原本・参照のSHAと領域別誤差を含み、原本不変をassertする。
右→左だけの追加試行は末尾に `split-x` を付け、`results-x.json` に保存する。
参照定義 `regions.json` のSHA-256は `bb6ac2e48328e53e1ef736fd4a35800a6520ea1b883804fa386ea8e6c8b489c6`。
画像、参照本文、OCR本文、実験スクリプトはGit対象外。測定コマンドの出力と検証は継続記録へ保存する。

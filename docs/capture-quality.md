# 保存写真の原寸点検と登録条件（PC用）

Status: Current runbook。PC用部品は実装済み。撮影・登録本流の品質ゲートは未接続、実機受け入れは未了。
Runs on: Windows PC、保存済みJPEG/PNGのみ。グラス・スマホ・ブラウザへ接続しない。

## グラスで確認できる範囲

グラスの撮影後表示は「構図確認のみ」「無操作で保存・画質未検証」とする。
3秒は可視ACKからの取消期間であり、全文・数式・図表の品質承認ではない。
撮影前の十字は方向の目安。新鮮なライブプレビューや物理的な紙面四隅の検査は未実装。
距離と照明を確認する案内に、未校正の固定距離を使わない。

PCの明暗補正は可視性を改善する候補であり、OCRの正答率改善とは区別する。
保存画像の探索的比較では、原寸の一部33文字に対して誤り4、半分に縮小すると9だった。
下記の細線を残す補正を加えても4/9のままで、OCR本流への自動適用は採用していない。
転記はエージェントの目視であり人手正解資料ではない。モデルはPCのTesseractで、ML Kitではない。
グラスの縮小入力・保存JPEG・サーバ原本PNGを変更したとも、全文精度を測ったとも主張しない。

`PageFraming.TEXT_BOUNDS_ONLY` は認識文字枠が画像内にあるという意味だけで、
未認識の文字・紙の余白・図表の完全性を証明しない。旧保存token `COMPLETE` もこの意味で読む。
原本・pending・manifestの一括変換はしない。`ShotScore` は連写の相対順位であり正解確率ではない。
欠け疑いは負、その他は非負の点数とし、文字数だけで欠け候補が上位になることを防ぐ。
全候補が欠けの場合は比較できても、後段の欠け拒否を通過しない。

## 原寸パケット

```powershell
py -3.12 -m scripts.capture_quality '<保存済みJPEG>' --out data/capture-quality --rotation 270 --tone --auto-rectify --layout single
py -3.12 -m scripts.capture_quality '<正規化済みPNG>' --out data/capture-quality --rotation 0 --layout spread
```

回転は原本の記録を使い、0/90/180/270を必ず指定する。EXIF回転を重ねて適用しない。
JPEG/PNGは単一フレーム・16MiB・25MP以内。タイルは既定1024px、重なり64pxで全域を覆う。
`--edge` は256〜1536、`--overlap` は0〜辺の1/4、最大96枚。端のタイルは小さくなる。
`--distance-cm` は実測距離がある場合のみ指定する。写真から距離を推定しない。

毎回専用ディレクトリへ次を保存する。原本を上書きせず、失敗時は当該実行の出力だけを除去する。

- `overview.png`: 長辺1280px以内の全体確認用。
- `tile-*.png`: 向き補正後の元画素を1対1で切り出す。RGBへの色変換以外の補間拡大・縮小はしない。
- `tile-*-tone.png`: `--tone` 時のみ、gamma 0.6〜1.0の単調RGB補正候補。元タイルを残し、
  全黒・全白・濃淡不足では増幅しない。生成的な文字補完・超解像ではなく、失われた細部は戻らない。
- `document-readable.png`: `--tone` 時、全画面を原寸で保持するグレースケール明暗補正候補。
  黒側は切り捨てず、明るい上位1%だけを白点推定から除く。カラーの図は元タイルで照合する。
- `paper-rectified.png`: 単ページの四隅候補が得られた場合、または手動四隅の指定時だけの派生画像。
  既定長辺2560px。補間済みで縦横比は観測辺からの推定。原寸タイルは必ず残す。
- `paper-readable.png`: 上記の切出し・角度補正画像へ `--tone` の明暗補正も適用した候補。
  手動四隅はオフライン比較用であり、実運用で自動的に紙面を切り出せる証拠ではない。
- `report.json`: schema=2。原本hash・byte数・寸法・回転・各タイル座標/hash、輝度5/50/95百分位、
  黒白付近の割合、隣接画素差、加工前の鮮鋭度、角度・出力寸法・出力→原画像ホモグラフィ。

出力へEXIF/GPSをコピーしない。実画像・派生画像・資料本文をGitへ入れない。
鮮鋭度の標本数は最大65,536。低模様は `insufficient_texture`、その他も未校正であり、
同じ資料・同じスケールでのみ比較する。大きい数値だけでピント合格にはしない。

`--auto-rectify` は明るい平らな単ページの候補だけを扱う。見開き、不明レイアウト、端接触、
複数の大領域、曖昧な輪郭、極端な姿勢では見送る。候補がなくても原寸パケットを残す。
手動の `--corners '[[0.1,0.1],[0.9,0.1],[0.9,0.9],[0.1,0.9]]'` は向き補正後の
左上・右上・右下・左下、0..1の有限・凸な座標を要求する。自動指定とは排他。
四角形の発見は紙面全体の証明ではなく、見開きの湾曲復元も行わない。

パケットは常に `decision=hold`、`auto_registration_allowed=false`、
`paper_completeness=unknown`、`semantic_coverage=unknown`。全画素の被覆と全文可読性を混同しない。

## 登録条件の評価部品

`scripts.capture_admission.assess_capture(evidence, source_sha256=..., rotation=...,
validated_profiles=())` は**呼出側が渡した証拠の評価**だけをする。画像からの証拠生成・認証はしない。
証拠はschema=1、`source_sha256`、`rotation`、boolの `inventory_complete`、`profile_id`、
`layout`（single/spread）、`pages`（1/2件）が必要。

ページは `id`、`paper_bounds`、`occlusion`、`regions`（1〜256件）。領域は `id`、
`kind`（text/math/figure/table/blank）、`source_detail`、`exposure`、`readability`。
判定はpass/fail/unknownのみ。ページIDは画像内、領域IDはページ内で一意、1〜80文字。
profile IDも1〜80文字とする。空白だけのIDは拒否する。

原本hash・回転・schemaの不一致や不正形式はhold。出所が一致した有効な証拠に既知の不良があればretake。
不明や不足、未検証profileはhold。全条件を満たす場合だけeligibleとなる。
検証済みprofile集合は既定で空。JSONに承認済みと自己申告しても採用しない。
呼出側はIDのtuple/list/set/frozensetを渡す。単一文字列の部分一致を承認として扱わない。
`guarantees_all_content=false` は常に維持し、AIの「全部読める」を全領域のpassへ複写しない。

## 単頁／見開きの比較

### 同じ領域の文字誤差

`scripts.capture_evaluation.compare_text(reference, recognized)` は、参照転記と認識結果の
挿入・削除・置換の最小回数、NFC後の文字数、誤り数/参照文字数を返す。空の認識結果も欠落として数える。
入力とNFC後の長さを各2048文字以内に制限する。空・空白だけの参照は評価できないため拒否する。
NFKC、英数字だけの抽出、並べ替え、重複除去は行わず、数式の符号・上付き・句読点・空白を保持する。
誤り率は挿入が多ければ1を超える。合否やprofile承認は返さない。

参照の出所、原本hash・回転・領域、認識器、比較前の加工は呼出側の実験記録へ保存する。
空白除去など比較前の処理を行う場合も明記する。数字が低いだけでは参照の正しさ・全文の可読性・
紙面や図の完全性を証明しない。保存画像3領域の試行結果と不採用案は
[撮影研究の領域分割比較](rokid-capture-research.md#2026-09-23-3領域で縮小補正分割を比較)を参照する。

### 参照ラベル付き撮影方式

```powershell
py -3.12 -m scripts.capture_evaluation '<参照ラベル付きtrial.json>'
```

入力は8MiB以内のJSON配列、1〜10,000件。各件は `sample_id`、`document_id`、
`comparison_id`（同一論理内容を識別する共通ID）、`split`（calibration/validation/test）、
`layout`（single/spread）、`decision`（eligible/hold/retake）、boolの `reference_usable`、
1〜8件の重複しない原本 `source_sha256` 配列。主要IDは1〜128文字。
参照ラベルは原資料・人の確認に基づけ、モデルの自己採点を正解としない。

同一内容の見開き1枚と左右の単頁2枚の組を一つの比較単位とする。単頁側の原本配列には2枚を入れる。
撮影条件・資料IDをそろえる。件数だけを合わせた異なる内容の比較はしない。
sample重複、document/comparison/layout重複、資料・比較ID・原画像の分割間混入を拒否する。
testだけで方式別件数、不良例の誤受入数/率、正常例のhold/retake数、両方式あり/片方だけの組数を出す。
不良例が0なら誤受入率はnull。未対応組の集計から優劣を断定せず、方式選択もprofile承認もしない。

## 本流に残る作業

Runs on: 設計・保存原本評価はPC。本流接続後の運用はglassdoc → スマホAP → スマホAPI。

保存原本の紙面・細字・数式・図表を検査する証拠生成と校正、新鮮な撮影前プレビュー、
本撮影後の同一原本再検査、capture_id/hash/rotation/policy/profile版の対応付けは未完。
手動・自動・終了時・復元時の候補保全と正式登録の分離、およびconfirm/upload/サーバ境界での
共通ゲートも未接続。現行の3秒無操作保存はこのゲートを通らない。
品質不明画像を正式登録へ昇格させない最終要件を、PC部品の追加だけで完成扱いしない。
既存の実機試験・導入・外部送信停止を維持し、継続は [tasks/todo.md](../tasks/todo.md) で管理する。

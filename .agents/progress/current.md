# 現行の継続記録（再開入口）

Status: Internal progress。2026-09-23作成。branch `feature/capture-quality-readiness`、Draft [PR #38](https://github.com/TroroOrosi/rokid-docscan-starter/pull/38)。
旧PR37の記録6件は `.agents/progress/archive/` に退避済み（利用者承認 2026-09-23）。測定値の一次記録として参照し、全文通読は不要。
Runs on: Windows PC `C:\rokid-docscan-starter`。実機・GPT送信は下の停止条件に従う。

## 目的（利用者、2026-09-23）

グラスで撮った問題画像を正確にGPTへ送り、解答用紙に書く内容をグラスで読む。
自動スキャン、OCR、紙を合わせる枠、画像の切出し・拡大・明るさ補正は、この目的のための手段・利便機能にすぎない。
OCRの文字数・枠判定を画質や合格の根拠にしない。

## 遅延の原因（利用者の指摘と記録の実測が一致）

- 正確でない指標（OCR・枠）を基準に、実機確認を繰り返した。目的と追加機能が混ざった。
- 旧スマホ経路（CXR-L `takePhoto(1920,1080,80)`、2026-08-28）の画像は読めた。用紙が画面の幅いっぱい（本文幅52%）、紙の輝度196。
  出典: `docs/hardware-measurements.md` §C-2／C-2b。
- 現在のglassdoc（camera2で最大JPEG 4032×3024を即時撮影、2026-09-22）は見開き＋背景が入り、全画面の輝度p50=35。
  最終metadataは露出10ms・ISO 50、`ae_state=1`（SEARCHING）。同じ席の標準カメラは露出16.6〜25ms・ISO 191〜318。
  出典: `.agents/progress/archive/pr37-capture-quality.md`。
- 機能全体を確認しないまま局所の作業を続け、記録が長期化して肥大した。

規則: 撮影の変更は「保存画像が旧経路または標準カメラの同じページと同程度に読めるか」で判断する。
画角と露出を先に直し、機能の追加はその後に行う。記録は本ファイルに短く追記する。

## 有効な決定・停止

- 実機操作・追加撮影・APK導入・GPT送信は、対象と判定条件を具体化して承認を得るまで停止する。
- 着席姿勢を前提にする。後退や正確な測距を必須にしない。LEDの外部観測は不要（2026-09-15）。
- ChatGPT web UIの自動操作は利用規約違反であり、利用者の決定として継続する。自動再送はしない。
- 小問一覧はモデルが原本から作る（RP-12、2026-09-23）。OCR分割はその失敗時の予備。
- 主経路は原本画像と原音を送る。ローカルのASRとOCR本文は送らない。

## このPRで完了したこと（PCのみ、実機未検証）

| commit | 内容 |
|---|---|
| `5568316` | RP-15: `finalize-reading?solve=background` で即時に返す。glassdocはPENDINGの間だけbundleをGETする |
| `bfd6366` | RP-12a: 問N直下の行頭`(A)`は選択肢として扱う |
| `6ec02a3` | RP-12: solverが原本から小問一覧を1回作る。大問見出しは解かない。設問指定は「第2問 問1」。一覧作成中の409を再試行する |

検証（`6ec02a3`の作業ツリー）:
- `py -3.12 -X utf8 -m pytest -q` → `852 passed, 1 skipped`。`ruff check .` → pass。
- `gradlew --no-daemon test testDebugUnitTest assembleDebug` → `BUILD SUCCESSFUL`。JUnit 402件、失敗0件。
- glassdoc APK は versionCode 20 / 0.17.0、`DocScanGlassActivity`。apksigner Verifies、証明書 `906307478018…ccacc`。
  SHA-256 `4d81deafc259e7a8f5ccf9151d196b0fb002288767b947ce0863a8f562082b42`。未導入。

## 次の作業

### 1. 画角と露出を旧経路と同等にする

Runs on: Windows PC（保存画像の比較と実装）。実機の撮影寸法や倍率を変える前に利用者の承認を得る（CLAUDE.md）。

- 旧経路の実写（`pending-capture-v1.bin` から取り出した1080×1920）とglassdocの原本を同じ基準で比較する。
  用紙が画面に占める割合と紙の輝度を測り、必要な倍率またはcropを算出する。
  保存dumpの `zoomRatioRange=[1,8]`。露出の収束待ちは `6149beb` で実装済みだが実機では未検証。
- 表示枠は、算出した撮影範囲に合わせるか、表示しない。未校正の枠を案内に使わない。

### 2. 限定した実機確認（1回）

Runs on: glassdoc＋既存Wi-Fi。GPT送信なし。承認後のみ実施する。

- 同じページを着席姿勢で撮る。新しいAPKと標準カメラで各1〜2枚。
- 判定: 用紙が画面幅の半分以上を占める。紙の輝度が旧経路（196）と標準カメラに近い。そうでなければ中止して原因を調べる。

### 3. 残り

Runs on: Windows PC。

- RP-15: 送信結果が不明になった後や、サーバの再起動後に残るPENDINGの表示。
- RP-12: 実冊子でのモデル一覧の過不足。
- CQ-8: 未検証の3秒登録と候補保全の境界。

## 退避した記録

`.agents/progress/archive/` にある以下の6件（内容は変更なし。パスとリンクだけ更新）:
`pr37-capture-quality.md`（PR37〜38の測定と訂正の全履歴）、`pr37-objective-review.md`、`pr37-camera-research.md`、
`pr37-offline-remediation.md`、`pr37-predevice-handoff.md`、`multimodal-scan.md`。

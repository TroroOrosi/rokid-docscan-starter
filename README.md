# Rokid DocScan（紙資料スキャン・ページ照合・解答・解説サーバ）

## このリポジトリの目的

Rokid Glasses で紙資料を撮影し、Android スマホを中継して問題を解析・解答し、
グラスの小さな HUD（最大3行）へ返すシステムです。Windows PC をサーバーとして使う
実機経路をリポジトリ内に含みます。

実機の主経路は次の通りです。

1. グラスを短押しして `AIMING` の照準を表示し、照準確認後に長押しして1.5秒静止してから
   CXR-L `takePhoto(1920, 1080, 80)` でページを撮影する。
2. Android の bundled Japanese ML Kit で OCR する。
3. `CAPTURE_REVIEW` の縮小プレビューで未登録写真を確認し、タッチパッド長押し
   （`AI-assist-start`）で登録する。短押しまたは2回短押しなら同じページの再撮影準備へ戻る。
4. 明示登録後に元 JPEG、ML Kit と同じ回転角、OCR を FastAPI へ送る。
5. 画像対応 Analyzer が転記・図表説明を補い、Solver が問題を解く。
6. Android リレーが CUSTOMVIEW へ最大3行ずつ表示する。

`android-relay/RokidGlobalLink` は、公式
`com.rokid.cxr:client-l:1.0.1` AAR を使い、Global Hi Rokid
`com.rokid.sprite.global.aiapp` へ接続します。
[TakanariShimbo/CxrGlobal](https://github.com/TakanariShimbo/CxrGlobal) の clone、
submodule、AARコピーは不要です。

公開 CXR-L で確認できない「グラス搭載 AI の任意認識文・回答を外部アプリへ返す
コールバック」には依存しません。テキストだけのページ登録と `POST /solutions` は API
互換として残していますが、実機の成立条件には数えません。
公開静止画面には撮影前ライブプレビュー、オートフォーカス、専用シャッターボタンの
入力コールバックもありません。固定焦点のため照準は構図合わせ用であり、合焦表示では
ありません。

- **プライバシー LED**：ハードウェア/ファームウェア制御です。アプリは無効化・迂回しません。
  撮影中の点灯、写真 callback 後の消灯、解答閲覧中の消灯維持を実機で物理確認します。
- **撮影通知**：シャッター音、フラッシュ、撮影表示は端末制御です。無音・無フラッシュを
  ソフトウェア契約として約束しません。
- **中断復帰**：文書IDと次ページ番号に加え、未登録写真、OCR、回転をスマホの
  アプリ専用領域へ保存します。再起動後は確認画面へ戻し、自動登録しません。
- **安全な公開**：実機利用では Bearer 認証を有効にし、信頼できる LAN 内で動かします。
- **学習用途**：`mode="real"` の解答は既定でロックされます。

導入の正本は
[Windows + Androidスマホ中継による実機運用](docs/windows-android-real-device-setup.md)、
CXR-L の実装境界は
[CXR-L / Global Hi Rokid integration](docs/cxr-l-integration.md)です。

現在のバージョン: **Server APP 0.14.0 / API 1.13.1 / Android client 0.2.0 /
Glasses View contract 1.8.0**。

---

## ユーザーがやること / システムがやること / 次に判断すること

| 区分 | 概要 | 詳細ドキュメント |
|------|------|------------------|
| **ユーザーがやること**（人間の物理操作） | Windows/Android環境準備・Hi Rokidペアリング・APK導入・全ページ撮影・OCR/LED/HUDの実機確認 | [docs/windows-android-real-device-setup.md](docs/windows-android-real-device-setup.md) |
| **システムがやること**（実装済み・自動） | 文書作成 / ページ取込 / pHash・OCR-MD5 / finalize / 照合 / HUD 応答 / バージョン付与 / ログ / しきい値フック | [docs/user-operation-guide.md](docs/user-operation-guide.md) §2 |
| **次に判断すること**（操作後の設計判断） | OCR 配置 / モデルルーティング / ストレージ・プライバシー / HUD 文言 / 信頼度しきい値 / オフライン挙動 / 対象端末(Android/iOS/Rokid/Android XR) | [docs/user-operation-guide.md](docs/user-operation-guide.md) §3 |

将来モデル/SDK が新しくなっても壊れない設計（ポート&アダプタ、レジストリ、契約
バージョニング、移行戦略）は [docs/future-proof-architecture.md](docs/future-proof-architecture.md) を参照。

---

## 構成

```
rokid-docscan-starter/
├── android-relay/       # ★Global Hi Rokid対応スマホ中継APK（Java/Gradle）
│   ├── app/             # CXR-L撮影・ML Kit OCR・HTTP・CUSTOMVIEW
│   └── build-windows.ps1
├── app/
│   ├── main.py        # FastAPI エンドポイント（match / exam / explain）
│   ├── matching.py    # pHash / hamming / OCR 類似度 / スコアリング
│   ├── hud.py         # 3行 HUD ペイロード生成（/match 用）
│   ├── glasses_view.py# グラス表示ビルダー（exam / explain 用・HUD契約）
│   ├── overlay.py     # 解答欄オーバーレイ（2D画像アンカー）
│   ├── layout.py      # 設問構造解析（設問番号/本文/選択肢/解答欄box）
│   ├── subjects.py    # 科目推定（共通テスト準拠フル16教科：現代文/古文/漢文/数学/英語/物理/化学/生物/地学/世界史/日本史/地理/倫理/政治経済/現代社会/情報）
│   ├── retrieval.py   # RAG 横断検索（既存 documents/pages → 根拠）
│   ├── summarize.py   # 要約シム（analyzer に委譲）
│   ├── explainer.py   # Explainer ポート（ExplainRequest / ExplainResult / ABC）
│   ├── llm.py         # ★実 AI ブリッジ（openai/gemini/claude、遅延import・注入可）
│   ├── audio_formats.py # 音声MIME・保存suffix・provider対応の共通定義
│   ├── version.py     # 各契約バージョン（app 0.14.0 / api 1.13.1 / glasses 1.8.0 ほか）
│   ├── config.py      # 保存先・フィーチャーフラグ（ROKID_* / ANTHROPIC_API_KEY / ROKID_TRANSCRIBER）
│   ├── transcribe.py  # ★リスニング録音の書き起こし（openai/gemini・未設定時は与値）
│   ├── db.py          # sqlite3（documents/pages/exam/explain テーブル）
│   ├── analyzers/     # 解析ポート: base / registry / local_placeholder / claude ★
│   ├── solvers/       # 解答ポート: base / registry / local_placeholder / claude ★
│   ├── explainers/    # 解説ポート: registry / local_placeholder / claude ★
│   ├── extractors/    # メディア抽出: base / registry / local_placeholder / claude ★
│   └── devtools/      # rokid_led.py（録画LED診断・サーバ非依存）
├── tests/             # pytest（照合/API/バージョン/レジストリ/exam/explain/LLM）
├── scripts/
│   ├── make_sample_pages.py  # curl 用サンプル画像生成
│   ├── evaluate.py           # 照合評価 → JSON レポート
│   ├── eval_exam.py          # 解答パイプライン評価 → JSON レポート
│   └── rokid_led.py          # 録画LED診断 CLI（実機所有者専用・任意）
├── docs/
│   ├── windows-android-real-device-setup.md # ★Windows+Android実機手順（正本）
│   ├── cxr-l-integration.md         # ★CXR-L / Global Hi Rokid実装境界
│   ├── real-device-operation.md     # 実機運用の索引・合格条件
│   ├── device-verification-checklist.md # ★実機検証チェックリスト（CXR-L入力/LED/読取品質/閾値）
│   ├── implementation-notes.md      # 実機/実AI 差し込み点・CXR SDK・実アダプタ
│   ├── user-operation-guide.md      # ユーザー操作 / 自動化 / 設計判断 / 環境変数一覧
│   ├── future-proof-architecture.md # 将来対応アーキテクチャ
│   ├── explain-sessions.md          # 資料解説モード詳細・curl 例
│   ├── glasses-ux-contract.md       # 旧操作を含むグラス UX 参考資料
│   ├── exam-solver-architecture.md  # 解答モードアーキテクチャ
│   └── rokid-led-dev-utility.md     # 録画LED診断ツールの詳細・警告
├── .env.example       # 全環境変数の雛形（コピーして .env に）
├── data/images/       # 画像保存先（実行時に自動生成）
├── requirements.txt   # コア依存（anthropic/openai/google-genai は任意・コメント参照）
├── Dockerfile
└── docker-compose.yml
```

---

## セットアップ

Python 3.10+ 推奨。

```bash
cd rokid-docscan-starter
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 起動

```bash
cp .env.example .env  # .env を使う場合。必要な設定だけ編集
uvicorn app.main:app --env-file .env --reload --port 8000
```

`.env` を使わない場合は `cp` と `--env-file .env` を省略してください。
設定ファイルは起動コマンドが明示的に読み込むため、pytestやライブラリから
`app.config` をimportしてもローカルの認証情報は混入しません。

- データ保存先を変えたい場合は環境変数 `ROKID_DATA_DIR` を設定:
  `ROKID_DATA_DIR=/tmp/rokid uvicorn app.main:app --port 8000`
- 起動時に `data/images/` と `data/docscan.db` が自動生成されます。

## テスト

```bash
pytest -q
```

照合ロジック（pHash 決定性 / ハミング距離 / OCR-MD5 正規化 / スコアリング /
HIT・LOW CONF・NO PAGE 判定）、API の登録〜finalize〜照合フロー、
バージョンメタデータ、analyzer レジストリ、explain-sessions フルフローを、
PIL で生成した合成画像で検証します（外部クレデンシャル不要・オフライン完結）。

## 評価（実サンプル読取後の検証に使用）

ユーザーが実機でサンプルを読取・登録した後（照合評価は画像を使う任意経路 `/match` 用）、照合品質としきい値提案を JSON で出力:

```bash
# 既存DBに対して評価
ROKID_DATA_DIR=data python scripts/evaluate.py --db data/docscan.db --out report.json
# 合成画像で素早く確認
python scripts/evaluate.py --synthetic 5
```

保存画像からクロップ・微回転・JPEG圧縮の非同一クエリを生成して照合するため、
`variant_match_accuracy` と `hamming_distribution`、`suggested_thresholds` を見て
`app/matching.py` のしきい値（D5）を調整します。これはオフラインの頑健性推定であり、
最終的なしきい値は可能であれば実機で独立に再読取した画像でも検証してください。

---

## API と curl 例

サーバが `http://127.0.0.1:8000` で動いている前提です。
サンプル画像（`page0.png` / `page1.png` / `query.png`）は次で生成できます:

```bash
python scripts/make_sample_pages.py
```

### 1. ヘルスチェック

```bash
curl -s http://127.0.0.1:8000/health
# {"status":"ok","versions":{...}}
```

### 2. 文書を作成

```bash
curl -s -X POST http://127.0.0.1:8000/v1/documents \
  -H 'Content-Type: application/json' \
  -d '{"title":"設計仕様書 v1","capture_device":"CXR-S"}'
# {"document_id":1,"title":"設計仕様書 v1","capture_device":"CXR-S","status":"open"}
```

### 3. ページを追加（実機主経路：写真 + スマホOCR）

Android リレーは元 JPEG、ML Kit と同じ回転角、端末 OCR を同時に送ります。画像は
OCR と同じ向きの PNG に正規化してサーバーに保存され、設定済みの画像対応 Analyzer が
必要に応じて OCR を補正します。`image_rotation` は `0`、`90`、`180`、`270`
（時計回り）を受け付け、省略時は `0` です。

実機撮影値は `takePhoto(1920, 1080, 80)` です。カメラは固定焦点で、公称被写界深度は
34cm〜∞のため、運用では用紙まで40〜60cm離します。最初の短押しで `AIMING` の照準を
表示して用紙中心を「＋」へ合わせ、長押し後は画面の1.5秒カウント中からcallbackまで
静止します。`AIMING` の短押しまたは2回短押しは撮影準備を取り消し、写真を撮りません。
四隅は撮影後プレビューで確認します。`takePhoto(4032, 3024, 80)` は実機で
JPEG callbackがBinder上限を超えた既知NGです。

撮影と端末OCRの完了後は `CAPTURE_REVIEW` となり、スマホとグラスのCustomViewへ
縮小プレビューを表示します。写真はまだ未登録です。グラスのタッチパッド長押し
（`AI-assist-start`）またはスマホの「この写真を登録」で初めてサーバーへ送ります。
グラスを短押しまたは2回短押しすると同じ `page_index` の `AIMING` へ戻り、照準を
確認して長押しすると再撮影します。スマホでは登録、再撮影、未登録写真の破棄を
代替操作できます。
OCRが0文字でも警告を確認して明示登録できます。登録成功まで対象ページと次ページ番号は
変わりません。文書自体は初回撮影前に作成されます。

撮影前ライブ映像とオートフォーカスは公開CXR-L非対応です。照準の「＋」は用紙中心を
合わせる目安で、ディスプレイFOVとカメラFOVが異なるため正確な撮影境界でも合焦判定でも
ありません。専用シャッターボタンの入力イベントも公開面から受信できないため、
CustomViewをユーザーが閉じるタップを撮影操作に使います。
写真回転の既定は実機に合わせた90°で、スマホで回転選択後に再撮影を準備すると次の写真へ
適用されます。未登録写真はアプリ再起動後も `CAPTURE_REVIEW` へ復元されますが、自動撮影・
自動登録は行いません。

```bash
curl -s -X POST http://127.0.0.1:8000/v1/documents/1/pages \
  -F page_index=0 \
  -F image_rotation=0 \
  -F image=@page0.png \
  -F ocr_text='問1 図の回路の合成抵抗を求めよ'
# {"page_id":1,...,"image_path":"...","scan_ack":{...}}
```

端末 OCR が空でも写真だけを受理します。画像対応 Analyzer が設定されておらず
問題を検出できなかった場合も元写真を保持し、読取状態へ戻して同じページを再撮影できます。

テキストだけの登録も互換入力として残っています。

```bash
curl -s -X POST http://127.0.0.1:8000/v1/documents/1/pages \
  -F page_index=0 \
  -F ocr_text='問1 図の回路の合成抵抗を求めよ' \
  -F vision_text='回路図: R1=2Ω と R2=3Ω が直列'
```

`ocr_text`、`vision_text`、`image` のいずれも無い場合は 400 です。

読取が中断したら **`GET /scan-status`** で欠番を確認し、欠番だけ再読取します（読み取り専用・
撮影は発生しません）:

```bash
curl -s 'http://127.0.0.1:8000/v1/documents/1/scan-status?expected_total_pages=4'
# {"page_indexes":[0,2],"missing_page_indexes":[1,3],
#  "recommended_action":"reread_missing_pages","reread_allowed":true,...}
```

### 4. 文書を確定（finalize）

```bash
curl -s -X POST http://127.0.0.1:8000/v1/documents/1/finalize
# {"document_id":1,"status":"ready","page_count":2,
#  "summaries":[{"page_index":0,"summary":"1ページ目の本文テキスト"}, ...]}
```

各ページの OCR テキスト先頭行から簡易サマリを生成し、文書を `ready` にします。

### 5. 目の前の紙を照合（match）

**撮影しません**。視認中ページの認識テキスト（その場認識）で照合します:

```bash
curl -s -X POST http://127.0.0.1:8000/v1/match \
  -F document_id=1 \
  -F ocr_text='1ページ目の本文テキスト'

# （任意・後方互換／非推奨）画像を添付すると画像登録ページとは pHash で照合されます
curl -s -X POST http://127.0.0.1:8000/v1/match \
  -F document_id=1 -F image=@query.png -F fast_ocr_text='1ページ目の本文テキスト'
```

> 同一テキストのページが複数ある場合は判別できず、若い `page_index` が選ばれます。
> テキスト照合の `hamming` は `null` になります（`query_signals` で経路を確認可能）。

レスポンス例（HIT）:

```json
{
  "document_id": 1,
  "query_signals": {"phash": false, "text": true},
  "verdict": "HIT",
  "best_page": {"page_id":1,"page_index":0,"hamming":null,"ocr_match":true,"ocr_similarity":1.0,"confidence":0.95},
  "confidence": 0.95,
  "hud": {"verdict":"HIT","confidence":0.95,"lines":["PAGE 1/2","1ページ目の本文テキスト","conf 0.95  txt 1.00"]},
  "candidates": [ {"page_index":0,...}, {"page_index":1,...} ]
}
```

（画像同士の照合では `hamming` に整数距離が入り、HUD 3行目は `conf 1.00  hd 0` の形になります）

`verdict` は以下の3値:

| verdict   | 意味                                   | HUD 1行目 |
|-----------|----------------------------------------|-----------|
| `HIT`     | 信頼できる一致                          | `PAGE n/N` |
| `LOW_CONF`| 候補はあるが信頼度が低い                 | `LOW CONF` |
| `NO_PAGE` | この文書内に一致なし / ページ未登録      | `NO PAGE`  |

---

## 照合ロジック（決定的）

`app/matching.py` 内のしきい値で挙動を制御します。

- **pHash**: 画像を 32×32 グレースケール化 → 2次元 DCT → 低周波 8×8 ブロックを
  中央値で2値化した **64bit** ハッシュ。
- **ハミング距離**:
  - `<= HAMMING_STRONG (6)` … 視覚的に確実な一致（視覚信頼度 1.0）
  - `>= HAMMING_WEAK (16)` … 無関係（視覚信頼度 0.0）
  - 間は線形補間。
- **OCR テキスト類似度ボーナス**: クエリと候補の OCR テキストがどれだけ似ているかで
  最大 `OCR_MD5_BONUS (0.35)` まで **段階的に** 加点します（実 OCR はノイズで揺れるため、
  完全一致のみだと現場でほぼ加点されないため）。
  - 正規化 MD5 が完全一致 → 満点ボーナス（最速パス。OCR 無し時の画像 MD5 一致もここ）。
  - そうでなければ正規化テキストの類似度 `ratio`（`difflib`、0..1）を見て、
    `ratio >= OCR_SIM_FLOOR (0.6)` のとき `OCR_MD5_BONUS * ratio` を加点。
    `ratio >= OCR_MATCH_RATIO (0.9)` なら `ocr_match=true`。
  - 正規化は「前後空白除去・連続空白を単一化・小文字化」。
  - レスポンスには `ocr_similarity`（0..1）が含まれます（追加フィールド・後方互換）。
- **判定**: 合成信頼度（0..1 にクリップ）が
  `>= CONF_OK (0.62)` → `HIT` / `>= CONF_LOW (0.40)` → `LOW_CONF` / それ未満 → `NO_PAGE`。

しきい値は撮影環境（照明・ブレ・解像度）に応じてチューニングしてください。

---

## Rokid Glasses への実機マッピング

実機でサポートする経路は一つです。

```text
Rokid Glasses
  └─ CXR-L / Bluetooth
      └─ Android: Global Hi Rokid + android-relay
          └─ LAN / HTTP(S)
              └─ FastAPI: Analyzer + Solver
```

| 役割 | 担当 |
|---|---|
| 撮影 | Glasses / CXR-L `takePhoto` |
| 端末 OCR | Android bundled Japanese ML Kit |
| Vision OCR・図表説明 | `ROKID_ANALYZER=openai\|gemini\|claude` |
| 問題分割・解答 | FastAPI + `ROKID_SOLVER=openai\|gemini\|claude` |
| HUD | Android relay → Global Hi Rokid CUSTOMVIEW |
| 中断復帰 | Android保存ID + `GET /scan-status` |

スマホは初期設定画面を持ち、セッション中も画面を表示したままにします。これは現行
Hi Rokid の写真 callback が画面消灯後に止まる場合へ備えるためです。接続後の撮影、
再撮影、登録、読取完了、閲覧はグラスのタッチパッド操作だけで進められます。スマホ
ボタンは同じ操作のフォールバックと診断・復旧用です。

詳細は [実機手順](docs/windows-android-real-device-setup.md) を参照してください。

---

## 資料解説モード（登録後・カメラOFF）

`/v1/explain-sessions` は、確定済み文書をページ単位で解説する既存 API です。
現行 `android-relay` の主 UI は問題の一括解答と `/review` に接続しており、
explain-sessions のグラス操作はまだ組み込んでいません。サーバー API の使用例は
[docs/explain-sessions.md](docs/explain-sessions.md) を参照してください。

---

## 解答モード（実機主経路）

Android リレーが撮影後のユーザー確認を挟んで次のチェーンを実行します。

1. 初回撮影時に `POST /v1/documents`。
2. 短押しで `AIMING` の照準を表示し、長押し後1.5秒静止して撮影。
3. 各撮影後に `CAPTURE_REVIEW` で未登録写真とOCR文字数を表示。
4. タッチパッド長押し（`AI-assist-start`）で確定した写真だけを
   `POST /v1/documents/{id}/pages` へ JPEG + OCR で送信。
5. `READING` の長押しで `/scan-status` → `/finalize`。
6. `POST /v1/exam-sessions` → `/finalize-reading`。
7. `GET /review` を CUSTOMVIEW へ表示。

`/finalize` は画像 Analyzer の転記をページへ保存してから問題を分割します。
`/finalize-reading` は各問題の開始ページ画像を画像対応 Solver へ渡します。
端末 OCR とクラウド OCR の両方が空なら問題0件として読取状態を維持し、同じページの
再撮影または Analyzer 設定を促します。

| 状態 | 短押し / 2回短押し | 長押し / `AI-assist-start` |
|---|---|---|
| 接続完了・読取中 (`READY` / `READING`) | 短押しで次ページの `AIMING` を開始（2回短押しは下記互換動作） | `READING` なら読取完了・解答開始 |
| 撮影準備 (`AIMING`) | 準備取消・直前画面へ戻る。撮影しない | 静止案内を開き、ACK後1.5秒静止して1回だけ撮影 |
| 静止待ち (`STABILIZING`) | 静止待ちを取り消す。撮影しない | 静止待ちを取り消す。撮影しない |
| 撮影確認 (`CAPTURE_REVIEW`) | 同じページの `AIMING` を開始 | 未登録写真を登録 |
| 閲覧中 (`REVIEW`) | 短押しで次の表示（2回短押しは前の表示） | 終了・新規文書 |

通常の二段階撮影は、短押しで照準を開き、構図確認後の長押しで静止待ちを開始します。
`AIMING` の短押しまたは2回短押しと、`STABILIZING` 中のすべてのジェスチャーは
安全側で撮影を取り消します。Rokid公式操作では
ダブルタップが「戻る／現在画面を終了」なので、連続してタップするとDocScanではなく
標準メニューへ戻ることがあります。リレーはその `AI-exit` 後、撮影や登録を行わずに
現在のDocScan画面を再表示し、メニュー遷移に使われたcloseを撮影操作として再実行しません。
静止待ち中に別のジェスチャーが届いた場合、旧timerは無効化され、自動では再開しません。
CustomViewのopen ACK faultまたは3秒のACK timeoutではcallback epochをfenceし、
`takePhoto`を発行しません。「Hi Rokid認可・再接続」を完了するまで次のView要求も
行いません。
ファームウェアが2回の入力をアプリへ
`DOUBLE_SHORT` として配送した場合だけ、読取中は直前ページの再撮影準備、
撮影確認中は同じページの再撮影準備、閲覧中は前の表示として扱います。

サーバーだけを確認する場合の最小 API 例:

```bash
curl -s -X POST http://127.0.0.1:8000/v1/documents \
  -H 'Content-Type: application/json' -d '{"title":"模試"}'
curl -s -X POST http://127.0.0.1:8000/v1/documents/1/pages \
  -F page_index=0 -F image=@page0.png -F ocr_text='問1 1+1を答えよ'
curl -s -X POST http://127.0.0.1:8000/v1/documents/1/finalize
curl -s -X POST http://127.0.0.1:8000/v1/exam-sessions \
  -H 'Content-Type: application/json' \
  -d '{"mode":"study","document_id":1,"exam_type":"written","answer_format":"mark"}'
curl -s -X POST http://127.0.0.1:8000/v1/exam-sessions/1/finalize-reading
curl -s 'http://127.0.0.1:8000/v1/exam-sessions/1/review?index=0&view_page=0'
```

`mode="real"` は `ROKID_ALLOW_REAL_EXAM_SOLVE=1` がない限りロックされます。

---

## 録画 LED 開発用診断ツール（任意・実機所有者専用）

実機の **録画インジケータ（プライバシー）LED** を調査するための、**サーバとは独立した
開発者向け診断ツール** を `scripts/rokid_led.py` に追加しました。**サーバや文書スキャン／
解答フローからは一切呼ばれません**。`GET /v1/settings` の `capture.privacy_led` は
`on_while_camera_active / tamper:forbidden`（カメラ稼働中は必ず点灯・改変不可）を公示し、
本ツールはその契約を変更しません。点灯時間を短くする正攻法は本 README の 3 フェーズフロー
（読取フェーズの最短化）であり、LED の無効化ではありません。

> **⚠️ 重要**: 録画インジケータを無効化する **確実な非 root・ソフトウェアのみの方法は
> 確認されていません**。`disable` は **未確認の仮説**（root / SELinux 変更が必要な場合あり）
> で、効かないこともあります。録画インジケータの無効化は **違法となりうる行為** です。
> **自分が所有・管理する端末** に対し、現地法と「録画は見える形で行う」期待に従って、
> 管理された開発環境でのみ使用してください。

- **既定は dry-run**（コマンド列を表示するだけ・端末に何も送らない）。
- 実行は `--apply`、状態を変える `disable`/`restore` は `--apply` に加え `--force` が必須
  （`--apply` のみで write を呼ぶと **ブロックして exit code 2**）。

```bash
# ワイヤレス ADB 接続コマンドの確認（dry-run。眼鏡のIPアドレスに置換）
python scripts/rokid_led.py connect 192.168.1.50

# LED ノード / プロパティ / SELinux 状態の探索（読み取り専用）
python scripts/rokid_led.py probe --host 192.168.1.50:5555 --apply

# 現在の LED 状態（読み取り専用）
python scripts/rokid_led.py status --host 192.168.1.50:5555 --apply

# 無効化の計画だけ表示（既定 dry-run・何も実行しない）
python scripts/rokid_led.py disable --led white

# 自分の端末で実際に試行（両フラグ必須）
python scripts/rokid_led.py disable --led white --host 192.168.1.50:5555 --apply --force

# 「本当に消えたか」を読み戻しで検証し、JSON 証跡を出力（再点灯対策に最大3回再アサート）
python scripts/rokid_led.py verify --led white --host 192.168.1.50:5555 \
    --apply --force --retries 3 --evidence-out led-evidence.json
```

> `verify` は ADB の `rc=0`（`write_succeeded`）と **実際の状態**（`verified_state` /
> `confirmed_off`、brightness 読み戻しが根拠）を分離します。`confirmed_off: true` でも
> **別カメラでの目視確認が必須**です（ADB 成功は物理 LED の消灯を証明しません）。

詳細・警告・既知の制約・検証手順は [docs/rokid-led-dev-utility.md](docs/rokid-led-dev-utility.md) を参照。

## 実モデル接続（実機の写真解析・解答には必須）

実機の主経路はサーバー側の画像対応 Analyzer/Solver です。各プロバイダポート
（analyzer / solver / explainer / extractor）へ OpenAI、Google Gemini、Anthropic
Claude の実アダプタを同梱しています。使用する1社の SDK と API キーを用意してください。

- 既定の `local` は開発用プレースホルダーです。実機では `ROKID_ANALYZER` と `ROKID_SOLVER` を `openai|gemini|claude` に設定します。
- **`ROKID_SOLVER` を non-local にすると `finalize-reading` がサーバ側で全問一括解答**します。
- APIキーが無い、SDKが無い、プロバイダ呼び出しに失敗した場合はローカル実装へ
  フォールバックします。写真にも端末OCRにも文字が無ければ問題0件として読取状態を維持します。
- 共通クライアントは `app/llm.py`（公式 SDK を遅延 import・注入可能・プロバイダ非依存）。

```bash
pip install openai                           # または google-genai / anthropic
export OPENAI_API_KEY=sk-...                 # Gemini: GOOGLE_API_KEY / Anthropic: ANTHROPIC_API_KEY
export ROKID_SOLVER=openai ROKID_EXPLAINER=openai \
       ROKID_ANALYZER=openai ROKID_EXTRACTOR=openai   # または gemini / claude
# export ROKID_LLM_MODEL=gpt-4o             # 任意上書き（既定: openai gpt-4o /
                                             #  gemini gemini-2.5-flash / anthropic claude-opus-4-8）
uvicorn app.main:app --port 8000
```

| 環境変数 | 既定 | 役割 |
|----------|------|------|
| `ROKID_ANALYZER`/`ROKID_SOLVER`/`ROKID_EXPLAINER`/`ROKID_EXTRACTOR` | `local` | `openai\|gemini\|claude` で実 AI にルーティング（solver は finalize-reading の一括解答も有効化） |
| `OPENAI_API_KEY`/`GOOGLE_API_KEY`/`ANTHROPIC_API_KEY` | （なし） | 実呼び出しに必須。未設定なら該当ポートはローカルへ |
| `ROKID_LLM_MODEL` | openai `gpt-4o` / gemini `gemini-2.5-flash` / anthropic `claude-opus-4-8` | 使用モデル id（任意上書き） |
| `ROKID_LLM_MAX_TOKENS` | `1024` | 応答トークン上限 |
| `ROKID_TRANSCRIBER` | （なし） | リスニング録音の書き起こし `openai\|gemini`（未設定=与えた transcript を使用） |
| `ROKID_TRANSCRIBE_MODEL` | `gpt-4o-transcribe` | openai の書き起こしモデル（gemini は `ROKID_LLM_MODEL`） |
| `ROKID_SOLVER_TIERS` | （単一） | 二段フォールバック順（例 `openai,local`） |
| `ROKID_KEYMAP` | （なし） | gesture→KeyCode の上書き（JSON、`/v1/settings.input`。既定 KeyCode は旧機由来・未実測） |
| `ROKID_API_KEY` | （なし） | 設定時に Bearer 認証（発見系は開放） |

全変数の雛形は [`.env.example`](.env.example)、一覧は
[user-operation-guide.md](docs/user-operation-guide.md) §7 を参照。

OpenAI書き起こしには公式に対応するWAV/MP3/M4A/MP4/OGG/FLAC/WebMを使用します。
raw ADTS/ADIF AACと識別できない音声データは保存できますがOpenAIへは送信せず、
与えられた transcript へフォールバックします。先頭にID3v2タグがあっても、タグ後の
実コンテナを判定します。

### 実機運用（グラス連携・入力・認証）

実機では `android-relay` がuser CustomView closeをタップ、`AI-assist-start`を長押し
として扱います。専用シャッターボタン、旧KeyCode、全タッチジェスチャ表は現行リレーの
入力契約ではありません。認証、Windows Firewall、APK導入、回転調整、LED/HUD合格条件は
[Windows + Android 実機手順](docs/windows-android-real-device-setup.md) に集約しています。

## Docker（任意）

```bash
docker compose up --build
# http://127.0.0.1:8000/health
```

Compose の既定ポートは安全のためホストの `127.0.0.1` だけに公開されます。
グラスから同一 LAN 経由で接続する場合は、明示的に公開先を切り替えます:

```bash
ROKID_BIND_HOST=0.0.0.0 ROKID_API_KEY='十分に長いランダム値' \
  docker compose up --build
```

LAN・インターネット公開では `ROKID_API_KEY` に加え、必ず TLS 対応の
リバースプロキシを設定してください。Compose は `.env` のサービス向け `ROKID_*`／
プロバイダ変数をコンテナへ渡し、`ROKID_BIND_HOST` はポート公開先の補間に使います。

ローカル Python 実行を優先してください。Docker は任意です。

## 制限事項

- Androidのbundled Japanese ML Kitを一次OCRに使います。画像対応Analyzerを設定すると
  サーバー側でも元写真から転記・図表説明を補完します。テキスト照合は完全一致ではなく類似度
  （`difflib`）で段階加点するため、多少のOCRノイズには強い。
- pHash は純 Python 実装（numpy/imagehash 非依存）で、大量ページでは低速。
  高速化は scipy/imagehash 等への置換が定石（依存を増やすため既定では未採用）。
- マルチテナントと一般的な多重書き込み制御は未実装（簡易 Bearer 認証は
  `ROKID_API_KEY` で任意）。同一問題の solver と同一ページ訪問の explainer は
  DB claim により、同時要求でも有料プロバイダを重複呼び出ししません。
- 実 AI アダプタは任意依存（`anthropic`/`openai`/`google-genai`）と各社 API キーが必要。
  未設定なら自動でローカル実装にフォールバック（実 AI 出力は得られません）。

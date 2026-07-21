# Rokid DocScan（紙資料スキャン・ページ照合・解答・解説サーバ）

## このリポジトリの目的と要望

Rokid Glasses で紙資料を「文書」として登録し、**目の前の資料を本体 AI が認識**した結果を使って、
ページ照合・**入試問題の解答**・**資料解説**をグラス上の小さな HUD（最大3行）で返すサーバです。
模試（学習・練習）利用を主目的とし、以下の要望を満たします：

- **LED 点灯時間の最小化（設計原則）**：Rokid Glasses のプライバシー LED は**カメラ稼働中は必ず点灯**
  します（視認＝認識＝カメラ ON＝LED 点灯。ハード強制・無効化不可）。そこで**読取フェーズだけ**を
  カメラ ON で最短に済ませ、解答・閲覧フェーズはカメラ OFF（LED 消灯）で行う **3 フェーズフロー**
  （読取 → 一括解答 → 閲覧）を主経路とします。
- **撮影しない**：紙を写真に撮らない。Rokid Glasses 本体 AI が**視認＝認識**し、その読み取りを
  **テキスト**（本文＝`ocr_text`／図・画像の読み取り＝`vision_text`）でサーバへ送る。写真ファイル・
  フラッシュ・シャッター音を出さない（録音も無音）。
- **図・画像も読む**：図・グラフ・写真がないと解けない問題に対応。本体 AI の図の読み取り
  （`vision_text`）を本文と併せて解答材料にする。
- **全ページを記憶してから解く**：全ページを一度だけ登録・記憶し、文書を**問題単位に分割して全問を
  一括で解く**。**問題がページを跨いで続く**場合も文書の全ページを文脈にして正確に解く。
- **主 AI はグラス搭載 AI（GPT）**：解答の主経路はグラス本体の搭載 AI（公式ネイティブは
  GPT / Gemini）。その問題別解答をサーバへ取り込む（`POST /solutions`）。サーバ側の
  openai / gemini / claude アダプタは、より高性能なモデルが必要な場合の**任意**経路。
- **操作は Rokid Glasses 単独**で完結（読取完了宣言・筆記⇄リスニング切替・問題別閲覧まで全て
  ジェスチャ。スマホは HTTP 中継のみ・画面不要。ジェスチャ未割当の文書作成・`/finalize`・
  セッション作成は読取開始/読取完了宣言に連動して**中継アプリが自動発行**——
  [docs/cxr-l-integration.md](docs/cxr-l-integration.md) §5）。
- **英語リスニング対応**：音声をその場で録音（無音）→書き起こし→資料と統合して解答。
  記述式・マーク式（`answer_format`）にも対応。

### 特徴

- **既定はオフラインでローカル実行可能**。外部クレデンシャル不要で全機能が動きます。
- **主経路は搭載 GPT**：グラス本体 AI が読取（`ocr_text`/`vision_text`）も解答も担い、サーバは
  取り込み・整形・状態管理を行います。**サーバ側実 AI は任意**：analyzer / solver / explainer /
  extractor の各ポートに **OpenAI (GPT) / Gemini / Claude の実アダプタを同梱**。環境変数だけで
  切り替わり、キー未設定時は自動でローカルにフォールバックします（下記「実モデル接続」）。
- ストレージは **SQLite + ローカルファイルシステム**（Postgres / MinIO 不要）。
- 照合は **決定的**（pHash のハミング距離 + OCR テキスト類似度ボーナス）。
- **CXR-L プラグイン（スマホ側）とグラス本体 AI の接続**は
  [`docs/cxr-l-integration.md`](docs/cxr-l-integration.md)、実機差し込み全般は
  [`docs/implementation-notes.md`](docs/implementation-notes.md) を参照。
- 現在のバージョン: **APP 0.11.0 / API 1.11.0**。

---

## ユーザーがやること / システムがやること / 次に判断すること

| 区分 | 概要 | 詳細ドキュメント |
|------|------|------------------|
| **ユーザーがやること**（人間の物理操作） | SDK 取得・ADB/ケーブル・ペアリング・全ページ視認読取（撮影しない）・読取品質チェック・プライバシー同意・クラウド/ローカル選択・検証実行 | [docs/user-operation-guide.md](docs/user-operation-guide.md) §1 |
| **システムがやること**（実装済み・自動） | 文書作成 / ページ取込 / pHash・OCR-MD5 / finalize / 照合 / HUD 応答 / バージョン付与 / ログ / しきい値フック | [docs/user-operation-guide.md](docs/user-operation-guide.md) §2 |
| **次に判断すること**（操作後の設計判断） | OCR 配置 / モデルルーティング / ストレージ・プライバシー / HUD 文言 / 信頼度しきい値 / オフライン挙動 / 対象端末(Android/iOS/Rokid/Android XR) | [docs/user-operation-guide.md](docs/user-operation-guide.md) §3 |

将来モデル/SDK が新しくなっても壊れない設計（ポート&アダプタ、レジストリ、契約
バージョニング、移行戦略）は [docs/future-proof-architecture.md](docs/future-proof-architecture.md) を参照。

---

## 構成

```
rokid-docscan-starter/
├── app/
│   ├── main.py        # FastAPI エンドポイント（match / exam / explain）
│   ├── matching.py    # pHash / hamming / OCR 類似度 / スコアリング
│   ├── hud.py         # 3行 HUD ペイロード生成（/match 用）
│   ├── glasses_view.py# グラス表示ビルダー（exam / explain 用・無音契約）
│   ├── overlay.py     # 解答欄オーバーレイ（2D画像アンカー）
│   ├── layout.py      # 設問構造解析（設問番号/本文/選択肢/解答欄box）
│   ├── subjects.py    # 科目推定（共通テスト準拠フル16教科：現代文/古文/漢文/数学/英語/物理/化学/生物/地学/世界史/日本史/地理/倫理/政治経済/現代社会/情報）
│   ├── retrieval.py   # RAG 横断検索（既存 documents/pages → 根拠）
│   ├── summarize.py   # 要約シム（analyzer に委譲）
│   ├── explainer.py   # Explainer ポート（ExplainRequest / ExplainResult / ABC）
│   ├── llm.py         # ★実 AI ブリッジ（openai/gemini/claude、遅延import・注入可）
│   ├── version.py     # 各契約バージョン（app 0.11.0 / api 1.11.0 ほか）
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
│   ├── cxr-l-integration.md         # ★CXR-L(ｽﾏﾎ側ﾌﾟﾗｸﾞｲﾝ) ⇄ 本体AI ⇄ 本サーバ + Kotlin 例・遠隔操作/画面共有
│   ├── real-device-operation.md     # ★実機運用ガイド（準備→起動→操作→実AI/認証/KeyCode）
│   ├── device-verification-checklist.md # ★実機検証チェックリスト（KeyCode/CXR-L/LED/読取品質/閾値）
│   ├── implementation-notes.md      # 実機/実AI 差し込み点・CXR SDK・実アダプタ
│   ├── user-operation-guide.md      # ユーザー操作 / 自動化 / 設計判断 / 環境変数一覧
│   ├── future-proof-architecture.md # 将来対応アーキテクチャ
│   ├── explain-sessions.md          # 資料解説モード詳細・curl 例
│   ├── glasses-ux-contract.md       # グラス UX 契約（操作・HUD・無音・無フラッシュ）
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
cp .env.example .env  # 必要な設定だけ編集（任意）
uvicorn app.main:app --reload --port 8000
```

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

### 3. ページを追加（撮影しない：本体 AI の認識テキスト＝本文＋図の読み取り）

**撮影しません。画像は不要**です。Rokid 通常利用のように**本体 AI が視認＝認識**した結果を
テキストで送ります（`image_path=null`・`phash=""`）：

- `ocr_text` … ページの本文（認識テキスト）
- `vision_text` … **図・グラフ・写真・見た目の読み取り**（画像ではなくテキスト）。図がないと解けない
  問題のために、本文と併せて解答材料になります。

```bash
# 撮影しない：本文＋図の読み取りをテキストで登録
curl -s -X POST http://127.0.0.1:8000/v1/documents/1/pages \
  -F page_index=0 \
  -F ocr_text='問1 図の回路の合成抵抗を求めよ' \
  -F vision_text='回路図: R1=2Ω と R2=3Ω が直列'
# {"page_id":1,...,"phash":"","image_path":null,"has_vision_text":true}

# （任意・後方互換）画像を添付すると pHash も算出され /match に使えます
curl -s -X POST http://127.0.0.1:8000/v1/documents/1/pages \
  -F page_index=0 -F image=@page0.png -F ocr_text='1ページ目の本文テキスト'
```

> `ocr_text`／`vision_text`／画像のいずれも無い場合は 400。標準フローは撮影せずテキストのみで、
> 画像は後方互換の任意項目です。

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

このリポジトリは **サーバ側** です。実運用は以下のいずれかの構成を想定します
（サーバから見ればどちらも同じ HTTP 契約）。

```
[Rokid Glasses] ─Bluetooth(CXR-L wire/Caps)─ [スマホ: Hi Rokid + CXR-L ﾌﾟﾗｸﾞｲﾝ] ─HTTPS─ [本サーバ]
  カメラ / 搭載AI(GPT/Gemini) / HUD      HTTP 中継のみ（画面不要）           登録/分割/取込/照合/解説

[Rokid Glasses] ─BLE/Wi-Fi─ [スマホ CXR-M コンパニオン] ─HTTPS─ [本サーバ]（CXR-M 構成）
```

> 実機動作実績のある CXR-L 構成は**スマホ側プラグイン**（Hi Rokid 経由・Bluetooth 制御プレーン）
> です。いずれの構成でもユーザーが見る・操作するのはグラスだけで、スマホは HTTP 中継のみ
> （詳細と是正の経緯は [`docs/cxr-l-integration.md`](docs/cxr-l-integration.md) §2-§3・§9）。

| 役割 | 実機での担当 | 本サーバでの受け口 |
|------|--------------|-----------------|
| 撮影 | Glasses カメラ（CXR-L `IMediaStreamService`／CXR-M） | クライアントがアップロードする画像 |
| 端末側 OCR / 認識 | 本体 AI（`com.rokid.sprite.aiapp`）／ML Kit／Vision | `ocr_text` / `vision_text` / `fast_ocr_text` フォーム値 |
| ページ照合 | 本サーバ（pHash + OCR 類似度） | 同左（そのまま） |
| **解答（主経路）** | **本体 AI（搭載 GPT / Gemini）が全問を解く** | `POST /v1/exam-sessions/{id}/solutions`（ingest） |
| 要約/解答/解説/抽出（任意） | 本サーバ（既定ローカル、任意で `openai`/`gemini`/`claude` 実AI） | 各 registry のアダプタ |
| HUD 表示 | Glasses の**両眼**ディスプレイ（3行） | `hud.lines` / `glasses_view.lines`（3行） |
| 文書登録ワークフロー | グラス/コンパニオン UI | `/v1/documents` → `/pages` → `/finalize` |

- 実機ハードウェア仕様（**両眼** 480×398 Micro-LED、AR1+NXP RT600、IMX681 12MP、
  YodaOS/Android 12 API32 など）と CXR-M/S/L の役割は、ウェブ検証済みの値を
  [`docs/cxr-l-integration.md`](docs/cxr-l-integration.md) にまとめています。
- **グラス本体 AI とサーバの接続**は 2 経路（同 doc §4）：**(B) 本体 AI（搭載 GPT / Gemini）が
  読取（`ocr_text`/`vision_text`）と解答（`POST /solutions`）を担う＝主経路（サーバ鍵不要）**、
  (A) サーバ側の `openai`/`gemini`/`claude` 実アダプタ＝より高性能なモデルが必要な場合の任意経路。
  なお **Claude はグラス搭載 AI ではありません**（搭載ネイティブは GPT / Gemini 等）。

---

## 資料解説モード（explain-sessions / グラス単体・無音 UX）

登録済み文書（`finalize` 済み）を**カメラなしでページ移動しながら解説を HUD に段階表示**する
機能です。スキャンフェーズはありません（v1.7 で `POST /scan`・`POST /commit` は廃止）：
セッション作成と同時に `ready` になり、ページ移動はサーバのカウンタのみで行います。

```
[ready]     セッション作成（document_id を指定）→ 即 ready・P01
      ↓
[explaining]  タップ（single_tap）→ 現在ページの解説を表示
  2本指スワイプ上下   → テキスト送り/戻し（テレプロンプター）
  2本指スワイプ左右   → 次ページ / 前ページ（POST /next-page・/prev-page）
  タップ             → 次の解説段階（overview→detail→evidence）
  ダブルタップ        → 終了
```

詳細な仕様・curl 例・操作マッピング表は
[docs/explain-sessions.md](docs/explain-sessions.md) を参照。

---

## 解答モード（入試問題ソルバー / グラス単体・無音 UX）

登録済み文書の問題を解いて **解答・解法・根拠・注意をグラス内の3行 HUD で表示**する解答モード
です（`/v1/exam-sessions`）。**主経路は上記の 3 フェーズフロー**（読取→一括解答→閲覧）。

- ユーザーが操作・閲覧するのは**眼鏡だけ**（スマホは通信・中継を担う裏方）。
- **無音・無フラッシュ・無アニメ・無点滅**を契約化（`GET /v1/settings` で公示、HUD は最大3行）。
- **音声操作は設定で ON/OFF**（既定 OFF＝ジェスチャ操作）。
- **解答の主経路は搭載 GPT**（本体 AI が解き `POST /solutions` で取り込み）。サーバ側ソルバーは
  既定で**オフラインのプレースホルダ**（実際には解かない＝不正利用ガード）。より高性能なモデルが
  必要な場合は **`openai`/`gemini`/`claude` の実アダプタ**を `ROKID_SOLVER=openai|gemini|claude`＋
  各社 API キーで有効化（下記「実モデル接続」）。クラウド→ローカルの**二段フォールバック**
  （`ROKID_SOLVER_TIERS`、`solve_with_fallback`）で圏外/失敗でも HUD は返ります。
- **メディア抽出**（数式/図/表/グラフ）は `app/extractors/`（`ROKID_EXTRACTOR`。`openai`/`gemini`/`claude` で実抽出）。`add_question` 応答の `media` に載ります。
- **RAG 根拠提示**：`app/retrieval.py` が既存の `documents/pages` を横断検索し、`solve` 応答の `evidence` と HUD の根拠に反映（`ROKID_ENABLE_EMBEDDING` で意味検索へ差替可）。
- **推論ログ**（案9）は `GET …/questions/{qid}/reasoning` で参照（HUD は短縮版・`real` ロック準拠）。
- 本番試験モード（`mode=real`）は既定でロック（`ROKID_ALLOW_REAL_EXAM_SOLVE=1` が無い限り解答非表示）。学習・模試・研究用途向けです。

```bash
# セッション作成 → 設問追加 → 解答 → 段階表示 → 推論ログ
curl -s -X POST http://127.0.0.1:8000/v1/exam-sessions \
  -H 'Content-Type: application/json' -d '{"mode":"study","voice_enabled":false}'
curl -s -X POST http://127.0.0.1:8000/v1/exam-sessions/1/questions \
  -F image=@page0.png -F ocr_text=$'問2 次の計算\n① 12\n② 13\n③ 14\n④ 15'
curl -s -X POST http://127.0.0.1:8000/v1/exam-sessions/1/questions/1/solve
curl -s 'http://127.0.0.1:8000/v1/exam-sessions/1/questions/1/view?stage=rationale&page=0'
curl -s http://127.0.0.1:8000/v1/exam-sessions/1/questions/1/reasoning

# 解答精度の評価ベンチ（合成サンプル）
python scripts/eval_exam.py --synthetic 5 --out /tmp/exam_eval.json
```

設計は [docs/exam-solver-architecture.md](docs/exam-solver-architecture.md)、
グラス表示・操作の規約は [docs/glasses-ux-contract.md](docs/glasses-ux-contract.md) を参照。

### 3 フェーズ実践フロー（主経路 / API 1.11.0・LED 点灯最小）

**読取 → 一括解答 → 閲覧** の 3 フェーズが主経路です。カメラ（＝プライバシー LED 点灯）は
**フェーズ 1 の読取中だけ**。読取完了をグラスのジェスチャで宣言した瞬間からカメラは閉じ、
解答・閲覧は LED 消灯のまま行えます（用紙も視認も不要）。撮影は一切発生しません。

```
フェーズ1 読取（カメラON・LED点灯・最短化）
  2本指タップ（AI起動=視認）×ページ数 → /pages に ocr_text+vision_text を登録（scan_ack で進捗）
  ダブルタップ（読取完了宣言）        → POST /finalize-reading（以降カメラOFF＝LED消灯）
フェーズ2 解答（カメラOFF・自動）
  文書を問題単位に分割（問N/大問 境界・ページ跨ぎ対応・全ページを文脈に）
  主経路: 搭載 GPT が全問を解き POST /solutions で取り込み（served_by="onboard"）
  任意:   ROKID_SOLVER=openai|gemini|claude ならサーバが finalize-reading 内で全問一括解答
フェーズ3 閲覧（カメラOFF・LED消灯）
  GET /solutions … 問題別レビューデッキ（問番号・教科・解答済み・確信度）
  GET /review?index=k&view_page=n … 1問題＝解答+解法+根拠+注意を一括1ストリーム表示
  2本指スワイプ左右=前後の問題 / 2本指スワイプ上下=テレプロンプター送り / ダブルタップ=終了
```

```bash
# フェーズ1) 撮影せず、本文＋図の読み取りを全ページ登録 → finalize → exam セッション
curl -s -X POST http://127.0.0.1:8000/v1/documents -d '{"title":"模試"}' -H 'Content-Type: application/json'
curl -s -X POST http://127.0.0.1:8000/v1/documents/1/pages -F page_index=0 \
  -F ocr_text='第1問 長文…' -F vision_text='図1: グラフの概形…'
curl -s -X POST http://127.0.0.1:8000/v1/documents/1/pages -F page_index=1 \
  -F ocr_text='問1 前ページの本文を踏まえて答えよ'
curl -s -X POST http://127.0.0.1:8000/v1/documents/1/finalize
curl -s -X POST http://127.0.0.1:8000/v1/exam-sessions -H 'Content-Type: application/json' \
  -d '{"mode":"study","document_id":1,"exam_type":"written","answer_format":"mark"}'

# 読取完了宣言（ダブルタップ）→ 問題分割・カメラOFF（LED消灯）
curl -s -X POST http://127.0.0.1:8000/v1/exam-sessions/1/finalize-reading

# フェーズ2) 搭載 GPT の問題別解答を取り込み（主経路）
curl -s -X POST http://127.0.0.1:8000/v1/exam-sessions/1/solutions \
  -H 'Content-Type: application/json' -d '{"solutions":[
    {"problem_no":"第1問","answer":"③","solution_steps":["本文の主題を把握"],
     "rationale":"第2段落より","answer_confidence":0.8},
    {"problem_no":"問1","answer":"ウ"}]}'

# フェーズ3) デッキ一覧 → 問題別閲覧（一括表示・テレプロンプター送り）
curl -s http://127.0.0.1:8000/v1/exam-sessions/1/solutions
curl -s 'http://127.0.0.1:8000/v1/exam-sessions/1/review?index=0&view_page=0'
```

**英語リスニング**：長押し（公式の録画⇄録音トグル）で筆記⇄リスニングを切替（`POST /mode`）。
リスニングは音声を**その場で無音録音**して送信（未書き起こし時は与えた `transcript` をそのまま
使用＝オフライン可）。書き起こしは全問の解答文脈に統合され、`answer_format`（マーク/記述）に
沿って解答されます。

```bash
curl -s -X POST http://127.0.0.1:8000/v1/exam-sessions/1/mode -H 'Content-Type: application/json' -d '{"exam_type":"listening"}'
# 録音アップロード（+任意の書き起こし）。ROKID_TRANSCRIBER=openai|gemini で実書き起こし
curl -s -X POST http://127.0.0.1:8000/v1/exam-sessions/1/audio \
  -F audio=@listening.wav -F transcript='(任意) 手元の書き起こし'
```

#### 互換: 文書ページ移動型（solve-current 型・二次経路）

ページ移動で現在ページを解く従来経路も残しています（挙動不変）。ページを視認しながら解くため
読取と閲覧が分離されず、主経路より LED 点灯時間が長くなります。

```bash
curl -s -X POST http://127.0.0.1:8000/v1/exam-sessions/1/next-page   # 2本指スワイプ左右
curl -s http://127.0.0.1:8000/v1/exam-sessions/1/current
curl -s -X POST http://127.0.0.1:8000/v1/exam-sessions/1/solve-current  # タップ（全ページを文脈に）
```

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

## 実モデル接続（openai / gemini / claude — 任意の高性能化経路）

**主経路はグラス搭載 AI（GPT / Gemini）**であり、サーバ鍵は不要です（解答は
`POST /solutions` で取り込み）。それでも**より高性能なモデルが必要な場合**のために、各プロバイダ
ポート（analyzer / solver / explainer / extractor）へ **OpenAI (GPT) / Google Gemini /
Anthropic Claude を使う実アダプタを同梱**しています。

- 既定は `local`（オフライン・クレデンシャル不要）。`ROKID_*=openai|gemini|claude` で切替。
- **`ROKID_SOLVER` を non-local にすると `finalize-reading` がサーバ側で全問一括解答**します。
- 該当プロバイダの API キーが無い／SDK 未インストールなら、**ネットワークに一切触れず
  自動でローカルにフォールバック**（solver は二段フォールバック、他は内部フォールバック）。
  サーバは常に応答します。
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

### 実機運用（グラス連携・入力・認証）

- **入力コントラクト**：`GET /v1/settings` の `input` が gesture→KeyCode を公示。ジェスチャ名は
  現行公式（2本指タップ=AI起動 / タップ / ダブルタップ / 2本指スワイプ上下左右 / 長押し=録画⇄録音）、
  **KeyCode 値は旧・単眼 Rokid Glass 由来で未実測**（`keycodes_verified:false`）。実機で
  `adb shell getevent -l` により計測し、機種差は `ROKID_KEYMAP` で上書き（クライアント改修不要）。
- **認証（任意）**：`ROKID_API_KEY` を設定すると発見系以外は `Authorization: Bearer` 必須。
- **一連の実機手順**は [docs/real-device-operation.md](docs/real-device-operation.md)、
  **グラス本体アプリ/本体 AI 連携**は [docs/cxr-l-integration.md](docs/cxr-l-integration.md)。

## Docker（任意）

```bash
docker compose up --build
# http://127.0.0.1:8000/health
```

Compose の既定ポートは安全のためホストの `127.0.0.1` だけに公開されます。
LAN・インターネットへ公開する場合はポート割当を明示的に変更し、必ず
`ROKID_API_KEY` と TLS 対応のリバースプロキシを設定してください。Compose は
`.env` の全 `ROKID_*`／プロバイダ変数をコンテナへ渡します。

ローカル Python 実行を優先してください。Docker は任意です。

## 制限事項

- **サーバ側 OCR は行いません**（設計上、OCR はグラス本体/端末側が担当し、テキストは
  `ocr_text` として受け取る三層構成）。テキスト照合は完全一致ではなく類似度（`difflib`）で
  段階加点するため、多少の OCR ノイズには強い。要約/解答/解説/抽出は `claude` アダプタで
  実 AI 化できます。
- pHash は純 Python 実装（numpy/imagehash 非依存）で、大量ページでは低速。
  高速化は scipy/imagehash 等への置換が定石（依存を増やすため既定では未採用）。
- マルチテナント・並行書き込み制御は未実装（簡易 Bearer 認証は `ROKID_API_KEY` で任意）。
- 実 AI アダプタは任意依存（`anthropic`/`openai`/`google-genai`）と各社 API キーが必要。
  未設定なら自動でローカル実装にフォールバック（実 AI 出力は得られません）。

# Rokid DocScan（紙資料スキャン・ページ照合・解答・解説サーバ）

## このリポジトリの目的と要望

Rokid Glasses で紙資料を「文書」として登録し、**目の前の資料を本体 AI が認識**した結果を使って、
ページ照合・**入試問題の解答**・**資料解説**をグラス上の小さな HUD（最大3行）で返すサーバです。
模試（学習・練習）利用を主目的とし、以下の要望を満たします：

- **写真・動画を作らない**：サーバは `ocr_text` / `vision_text` / `fast_ocr_text` だけを受け取り、
  `/pages`・`/match`・`/questions` に送られた画像は、バイト列を読む前に `415` で拒否します。
  画像・動画・生フレームを保存せず、既存 DB の画像パスも解析・解答モデルへ渡しません。
- **LEDを迂回しない**：Rokid 公式ガイドは、Rokid Glasses のリアルタイム翻訳をマイク音声の翻訳、
  白色点灯を「カメラ使用中」と説明しています。したがって音声翻訳は、視覚認識中もLEDが消える根拠に
  なりません。視覚センサーを使う場合のLEDは端末ファームウェアに従い、サーバは制御・消灯保証を
  行いません。読取終了時はクライアントへセンサー終了を要求します。
- **図・画像も読む**：図・グラフ・写真がないと解けない問題に対応。本体 AI の図の読み取り
  （`vision_text`）を本文と併せて解答材料にする。
- **全ページを記憶してから解く**：全ページを一度だけ登録・記憶し、文書を**問題単位に分割して全問を
  一括で解く**。**問題がページを跨いで続く**場合も文書の全ページを文脈にして正確に解く。
- **主 AI はグラス搭載 AI（GPT）**：解答の主経路はグラス本体の搭載 AI（公式ネイティブは
  GPT / Gemini）。その問題別解答をサーバへ取り込む（`POST /solutions`）。サーバ側の
  openai / gemini / claude アダプタは、より高性能なモデルが必要な場合の**任意**経路。
- **操作は Rokid Glasses 単独**で完結（読取完了宣言・筆記⇄リスニング切替・問題別閲覧まで全て
  ジェスチャ。スマホは HTTP 中継のみ・画面不要）。
- **英語リスニング対応**：音声をその場で録音（無音）→書き起こし→資料と統合して解答。
  記述式・マーク式（`answer_format`）にも対応。

### 特徴

- **既定はオフラインでローカル実行可能**。外部クレデンシャル不要で全機能が動きます。
- **主経路は搭載 GPT**：グラス本体 AI が読取（`ocr_text`/`vision_text`）も解答も担い、サーバは
  取り込み・整形・状態管理を行います。**サーバ側実 AI は任意**：analyzer / solver / explainer /
  extractor の各ポートに **OpenAI (GPT) / Gemini / Claude の実アダプタを同梱**。環境変数だけで
  切り替わり、キー未設定時は自動でローカルにフォールバックします（下記「実モデル接続」）。
- ストレージは **SQLite + ローカルファイルシステム**（Postgres / MinIO 不要）。
- 実行時の照合は **決定的な認識テキスト類似度**。pHash は既存DBの検証用プリミティブとしてのみ残します。
- **CXR-L プラグイン（スマホ側）とグラス本体 AI の接続**は
  [`docs/cxr-l-integration.md`](docs/cxr-l-integration.md)、実機差し込み全般は
  [`docs/implementation-notes.md`](docs/implementation-notes.md) を参照。
- 現在のバージョン: **APP 0.9.0 / API 1.9.0**。

---

## ユーザーがやること / システムがやること / 次に判断すること

| 区分 | 概要 | 詳細ドキュメント |
|------|------|------------------|
| **ユーザーがやること**（人間の物理操作） | SDK 取得・ADB/ケーブル・ペアリング・全ページ視認読取（撮影しない）・読取品質チェック・プライバシー同意・クラウド/ローカル選択・検証実行 | [docs/user-operation-guide.md](docs/user-operation-guide.md) §1 |
| **システムがやること**（実装済み・自動） | 文書作成 / テキストページ取込 / 画像拒否 / OCR-MD5・テキスト照合 / finalize / HUD 応答 / バージョン付与 / ログ | [docs/user-operation-guide.md](docs/user-operation-guide.md) §2 |
| **次に判断すること**（操作後の設計判断） | OCR 配置 / モデルルーティング / ストレージ・プライバシー / HUD 文言 / 信頼度しきい値 / オフライン挙動 / 対象端末(Android/iOS/Rokid/Android XR) | [docs/user-operation-guide.md](docs/user-operation-guide.md) §3 |

将来モデル/SDK が新しくなっても壊れない設計（ポート&アダプタ、レジストリ、契約
バージョニング、移行戦略）は [docs/future-proof-architecture.md](docs/future-proof-architecture.md) を参照。

---

## 構成

```
rokid-docscan-starter/
├── app/
│   ├── main.py        # FastAPI エンドポイント（match / exam / explain）
│   ├── matching.py    # 実行時テキスト照合 + 既存DB評価用 pHash
│   ├── hud.py         # 3行 HUD ペイロード生成（/match 用）
│   ├── glasses_view.py# グラス表示ビルダー（exam / explain 用・無音契約）
│   ├── overlay.py     # 解答欄オーバーレイ（2D画像アンカー）
│   ├── layout.py      # 設問構造解析（設問番号/本文/選択肢/解答欄box）
│   ├── subjects.py    # 科目推定（共通テスト準拠フル16教科：現代文/古文/漢文/数学/英語/物理/化学/生物/地学/世界史/日本史/地理/倫理/政治経済/現代社会/情報）
│   ├── retrieval.py   # RAG 横断検索（既存 documents/pages → 根拠）
│   ├── summarize.py   # 要約シム（analyzer に委譲）
│   ├── explainer.py   # Explainer ポート（ExplainRequest / ExplainResult / ABC）
│   ├── llm.py         # ★実 AI ブリッジ（openai/gemini/claude、遅延import・注入可）
│   ├── version.py     # 各契約バージョン（app 0.9.0 / api 1.9.0 ほか）
│   ├── config.py      # 保存先・フィーチャーフラグ（ROKID_* / ANTHROPIC_API_KEY / ROKID_TRANSCRIBER）
│   ├── transcribe.py  # ★リスニング録音の書き起こし（openai/gemini・未設定時は与値）
│   ├── db.py          # sqlite3（documents/pages/exam/explain テーブル）
│   ├── analyzers/     # 解析ポート: base / registry / local_placeholder / claude ★
│   ├── solvers/       # 解答ポート: base / registry / local_placeholder / claude ★
│   ├── explainers/    # 解説ポート: registry / local_placeholder / claude ★
│   └── extractors/    # 認識テキストからの構造抽出: base / registry / local_placeholder / claude ★
├── tests/             # pytest（照合/API/バージョン/レジストリ/exam/explain/LLM）
├── scripts/
│   ├── evaluate.py           # 認識テキスト照合評価 → JSON レポート
│   └── eval_exam.py          # 解答パイプライン評価 → JSON レポート
├── docs/
│   ├── cxr-l-integration.md         # ★CXR-L(ｽﾏﾎ側ﾌﾟﾗｸﾞｲﾝ) ⇄ 本体AI ⇄ 本サーバ + Kotlin 例・遠隔操作/画面共有
│   ├── real-device-operation.md     # ★実機運用ガイド（準備→起動→操作→実AI/認証/KeyCode）
│   ├── implementation-notes.md      # 実機/実AI 差し込み点・CXR SDK・実アダプタ
│   ├── user-operation-guide.md      # ユーザー操作 / 自動化 / 設計判断 / 環境変数一覧
│   ├── future-proof-architecture.md # 将来対応アーキテクチャ
│   ├── explain-sessions.md          # 資料解説モード詳細・curl 例
│   ├── glasses-ux-contract.md       # グラス UX 契約（操作・HUD・入力プライバシー）
│   └── exam-solver-architecture.md  # 解答モードアーキテクチャ
├── .env.example       # 全環境変数の雛形（コピーして .env に）
├── data/audio/        # リスニング音声を送った場合の保存先
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
uvicorn app.main:app --reload --port 8000
```

- データ保存先を変えたい場合は環境変数 `ROKID_DATA_DIR` を設定:
  `ROKID_DATA_DIR=/tmp/rokid uvicorn app.main:app --port 8000`
- 起動時に `data/audio/` と `data/docscan.db` が自動生成されます。画像保存ディレクトリは作りません。

## テスト

```bash
pytest -q
```

照合ロジック（認識テキスト類似度 / OCR-MD5 正規化 / 既存DB評価用pHash /
HIT・LOW CONF・NO PAGE 判定）、API の登録〜finalize〜照合フロー、
バージョンメタデータ、analyzer レジストリ、explain-sessions フルフローを検証します。
pHash単体テストの合成画像はカメラ入力ではなく、HTTP実行経路には入りません。

## 評価（実サンプル読取後の検証に使用）

ユーザーが実機でサンプルを認識・登録した後、保存済み認識テキストに対する完全一致・擬似OCRノイズ
照合をJSONで評価します。画像は使用しません。

```bash
# 既存DBに対して評価
ROKID_DATA_DIR=data python scripts/evaluate.py --db data/docscan.db --out report.json
# 合成テキストで素早く確認
python scripts/evaluate.py --synthetic 5
```

`self_match_accuracy`・`noisy_match_accuracy`・`noisy_similarity` を見て、実機の誤一致も確認した上で
`TEXT_CONF_OK/LOW` を調整します。

---

## API と curl 例

サーバが `http://127.0.0.1:8000` で動いている前提です。全例はテキストだけを送ります。

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

**画像は受け付けません。** クライアント側で一時的に得た認識結果をテキストで送ります
（`image_path=null`・`phash=""`）。写真・動画の撮影APIやファイル保存は呼び出さないでください：

- `ocr_text` … ページの本文（認識テキスト）
- `vision_text` … **図・グラフ・写真・見た目の読み取り**（画像ではなくテキスト）。図がないと解けない
  問題のために、本文と併せて解答材料になります。

```bash
# 本文＋図の読み取りをテキストだけで登録
curl -s -X POST http://127.0.0.1:8000/v1/documents/1/pages \
  -H 'Content-Type: application/json' \
  -d '{"page_index":0,"ocr_text":"問1 図の回路の合成抵抗を求めよ","vision_text":"回路図: R1=2Ω と R2=3Ω が直列"}'
# {"page_id":1,...,"phash":"","image_path":null,
#  "raw_media_received":false,"media_persisted":false}
```

> `ocr_text` と `vision_text` が両方空なら `400`。`image` を添付すると、内容を読み取る前に `415`。

### 4. 文書を確定（finalize）

```bash
curl -s -X POST http://127.0.0.1:8000/v1/documents/1/finalize
# {"document_id":1,"status":"ready","page_count":2,
#  "summaries":[{"page_index":0,"summary":"1ページ目の本文テキスト"}, ...]}
```

各ページの OCR テキスト先頭行から簡易サマリを生成し、文書を `ready` にします。

### 5. 目の前の紙を照合（match）

```bash
curl -s -X POST http://127.0.0.1:8000/v1/match \
  -H 'Content-Type: application/json' \
  -d '{"document_id":1,"fast_ocr_text":"1ページ目の本文テキスト"}'
```

レスポンス例（HIT）:

```json
{
  "document_id": 1,
  "verdict": "HIT",
  "matching_mode": "recognized_text",
  "raw_media_received": false,
  "media_persisted": false,
  "best_page": {"page_id":1,"page_index":0,"hamming":null,"ocr_match":true,"ocr_similarity":1.0,"confidence":1.0},
  "confidence": 1.0,
  "hud": {"verdict":"HIT","confidence":1.0,"lines":["PAGE 1/2","1ページ目の本文テキスト","conf 1.00  txt 1.00"]},
  "candidates": [ {"page_index":0,...}, {"page_index":1,...} ]
}
```

`verdict` は以下の3値:

| verdict   | 意味                                   | HUD 1行目 |
|-----------|----------------------------------------|-----------|
| `HIT`     | 信頼できる一致                          | `PAGE n/N` |
| `LOW_CONF`| 候補はあるが信頼度が低い                 | `LOW CONF` |
| `NO_PAGE` | この文書内に一致なし / ページ未登録      | `NO PAGE`  |

---

## 照合ロジック（実行時はテキストのみ）

`app/matching.py` 内のしきい値で挙動を制御します。

- **完全一致**：正規化テキストの MD5 が一致すれば `confidence=1.0`。
- **近似一致**：それ以外は `difflib.SequenceMatcher` の類似度（0..1）をそのまま信頼度にします。
  - 正規化は「前後空白除去・連続空白を単一化・小文字化」。
- **判定**：`>= TEXT_CONF_OK (0.82)` → `HIT`、`>= TEXT_CONF_LOW (0.55)` → `LOW_CONF`、
  それ未満 → `NO_PAGE`。
- pHash / ハミング距離は、古いDBや合成評価の互換プリミティブとして残っていますが、HTTP実行経路は
  呼び出しません。

しきい値は端末側認識テキストの誤り方に応じてチューニングしてください。

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
| 視覚認識 | クライアント側の一時認識セッション（SDKで実機検証が必要） | 生画像は送らず、結果テキストだけを送信 |
| 端末側 OCR / 認識 | 本体 AI／端末OCR（利用可能な公式APIに合わせる） | `ocr_text` / `vision_text` / `fast_ocr_text` |
| ページ照合 | 本サーバ（認識テキスト類似度） | `POST /v1/match`（画像添付不可） |
| **解答（主経路）** | **本体 AI（搭載 GPT / Gemini）が全問を解く** | `POST /v1/exam-sessions/{id}/solutions`（ingest） |
| 要約/解答/解説/抽出（任意） | 本サーバ（既定ローカル、任意で `openai`/`gemini`/`claude` 実AI） | 各 registry のアダプタ |
| HUD 表示 | Glasses の**両眼**ディスプレイ（3行） | `hud.lines` / `glasses_view.lines`（3行） |
| 文書登録ワークフロー | グラス/コンパニオン UI | `/v1/documents` → `/pages` → `/finalize` |

- 実機機能と、公式公開情報で確認できる範囲／SDK入手後に実機確認が必要な範囲は
  [`docs/cxr-l-integration.md`](docs/cxr-l-integration.md) に分けてまとめています。
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
  -H 'Content-Type: application/json' \
  -d '{"ocr_text":"問2 次の計算\n① 12\n② 13\n③ 14\n④ 15"}'
curl -s -X POST http://127.0.0.1:8000/v1/exam-sessions/1/questions/1/solve
curl -s 'http://127.0.0.1:8000/v1/exam-sessions/1/questions/1/view?stage=rationale&page=0'
curl -s http://127.0.0.1:8000/v1/exam-sessions/1/questions/1/reasoning

# 解答精度の評価ベンチ（合成サンプル）
python scripts/eval_exam.py --synthetic 5 --out /tmp/exam_eval.json
```

設計は [docs/exam-solver-architecture.md](docs/exam-solver-architecture.md)、
グラス表示・操作の規約は [docs/glasses-ux-contract.md](docs/glasses-ux-contract.md) を参照。

### 3 フェーズ実践フロー（主経路 / API 1.9.0・メディア非保存）

**読取 → 一括解答 → 閲覧** の 3 フェーズが主経路です。フェーズ1でもサーバへ送るのは認識テキスト
だけです。読取完了時、クライアントは視覚認識セッションを停止してから `finalize-reading` を呼びます。
サーバは物理カメラやLEDを観測できないため、応答は停止要求と期待状態を返し、消灯済みとは断定しません。

```
フェーズ1 読取（端末内の一時認識。写真・動画・フレーム保存なし）
  2本指タップ×ページ数 → /pages に ocr_text+vision_text のみ登録（scan_ack で進捗）
  ダブルタップ → クライアントが視覚センサーを停止 → POST /finalize-reading
フェーズ2 解答（視覚センサー不要・自動）
  文書を問題単位に分割（問N/大問 境界・ページ跨ぎ対応・全ページを文脈に）
  主経路: 搭載 GPT が全問を解き POST /solutions で取り込み（served_by="onboard"）
  任意:   ROKID_SOLVER=openai|gemini|claude ならサーバが finalize-reading 内で全問一括解答
フェーズ3 閲覧（視覚センサー不要）
  GET /solutions … 問題別レビューデッキ（問番号・教科・解答済み・確信度）
  GET /review?index=k&view_page=n … 1問題＝解答+解法+根拠+注意を一括1ストリーム表示
  2本指スワイプ左右=前後の問題 / 2本指スワイプ上下=テレプロンプター送り / ダブルタップ=終了
```

```bash
# フェーズ1) 撮影せず、本文＋図の読み取りを全ページ登録 → finalize → exam セッション
curl -s -X POST http://127.0.0.1:8000/v1/documents -d '{"title":"模試"}' -H 'Content-Type: application/json'
curl -s -X POST http://127.0.0.1:8000/v1/documents/1/pages \
  -H 'Content-Type: application/json' \
  -d '{"page_index":0,"ocr_text":"第1問 長文…","vision_text":"図1: グラフの概形…"}'
curl -s -X POST http://127.0.0.1:8000/v1/documents/1/pages \
  -H 'Content-Type: application/json' \
  -d '{"page_index":1,"ocr_text":"問1 前ページの本文を踏まえて答えよ"}'
curl -s -X POST http://127.0.0.1:8000/v1/documents/1/finalize
curl -s -X POST http://127.0.0.1:8000/v1/exam-sessions -H 'Content-Type: application/json' \
  -d '{"mode":"study","document_id":1,"exam_type":"written","answer_format":"mark"}'

# 読取完了宣言（ダブルタップ）→ クライアント側センサー停止後に問題分割
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

**英語リスニング**：長押しをアプリ内で処理して筆記⇄リスニングを切替（`POST /mode`）。
システムの写真・動画操作へは転送せず、リスニング中はマイク音声だけを扱います。
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

ページ移動で現在ページを解く従来経路も残しています。登録済みの認識テキストだけを参照するため、
このサーバ側経路はカメラ画像を要求しません。

```bash
curl -s -X POST http://127.0.0.1:8000/v1/exam-sessions/1/next-page   # 2本指スワイプ左右
curl -s http://127.0.0.1:8000/v1/exam-sessions/1/current
curl -s -X POST http://127.0.0.1:8000/v1/exam-sessions/1/solve-current  # タップ（全ページを文脈に）
```

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
export ROKID_LLM_MODEL=<現行のGPTモデルid>    # openai/gemini は現行モデル id を必須指定
                                             # （anthropic のみ claude-opus-4-8 が既定）
uvicorn app.main:app --port 8000
```

| 環境変数 | 既定 | 役割 |
|----------|------|------|
| `ROKID_ANALYZER`/`ROKID_SOLVER`/`ROKID_EXPLAINER`/`ROKID_EXTRACTOR` | `local` | `openai\|gemini\|claude` で実 AI にルーティング（solver は finalize-reading の一括解答も有効化） |
| `OPENAI_API_KEY`/`GOOGLE_API_KEY`/`ANTHROPIC_API_KEY` | （なし） | 実呼び出しに必須。未設定なら該当ポートはローカルへ |
| `ROKID_LLM_MODEL` | （anthropic のみ `claude-opus-4-8`） | 使用モデル id（openai/gemini は必須指定） |
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
  現行のジェスチャ（2本指タップ / タップ / ダブルタップ / 2本指スワイプ上下左右 / 長押し）、
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

ローカル Python 実行を優先してください。Docker は任意です。

## 制限事項

- **サーバ側 OCR は行いません**（設計上、OCR はグラス本体/端末側が担当し、テキストは
  `ocr_text` として受け取る三層構成）。テキスト照合は完全一致ではなく類似度（`difflib`）で
  段階加点するため、多少の OCR ノイズには強い。要約/解答/解説/抽出は `claude` アダプタで
  実 AI 化できます。
- 文字列類似度はページ全文を比較するため、大規模文書では候補の事前絞り込みが将来課題です。
- マルチテナント・並行書き込み制御は未実装（簡易 Bearer 認証は `ROKID_API_KEY` で任意）。
- 実 AI アダプタは任意依存（`anthropic`/`openai`/`google-genai`）と各社 API キーが必要。
  未設定なら自動でローカル実装にフォールバック（実 AI 出力は得られません）。

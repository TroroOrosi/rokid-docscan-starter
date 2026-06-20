# Rokid DocScan MVP（紙資料スキャン・ページ照合サーバ）

Rokid Glasses で撮影した紙資料を「文書」として登録し、後から目の前の紙が
**どのページか** を端末側 OCR とサーバ側の知覚ハッシュ（pHash）で
照合して、グラス上の小さな HUD（3行）に結果を返すためのサーバ MVP です。

- **実機なしでローカル実行可能**。Rokid のハードウェアや SDK、外部クレデンシャルは不要です。
- ストレージは **SQLite + ローカルファイルシステム**（Postgres / MinIO 不要）。
- 照合は **決定的**（pHash のハミング距離 + OCR テキスト MD5 完全一致ボーナス）。
- 偽の SDK 依存は一切含みません。実機連携の差し込み箇所は
  [`docs/implementation-notes.md`](docs/implementation-notes.md) を参照。

---

## ユーザーがやること / システムがやること / 次に判断すること

| 区分 | 概要 | 詳細ドキュメント |
|------|------|------------------|
| **ユーザーがやること**（人間の物理操作） | SDK 取得・ADB/ケーブル・ペアリング・サンプル撮影・照明/角度チェック・プライバシー同意・クラウド/ローカル選択・検証実行 | [docs/user-operation-guide.md](docs/user-operation-guide.md) §1 |
| **システムがやること**（実装済み・自動） | 文書作成 / ページ取込 / pHash・OCR-MD5 / finalize / 照合 / HUD 応答 / バージョン付与 / ログ / しきい値フック | [docs/user-operation-guide.md](docs/user-operation-guide.md) §2 |
| **次に判断すること**（操作後の設計判断） | OCR 配置 / モデルルーティング / ストレージ・プライバシー / HUD 文言 / 信頼度しきい値 / オフライン挙動 / 対象端末(Android/iOS/Rokid/Android XR) | [docs/user-operation-guide.md](docs/user-operation-guide.md) §3 |

将来モデル/SDK が新しくなっても壊れない設計（ポート&アダプタ、レジストリ、契約
バージョニング、移行戦略）は [docs/future-proof-architecture.md](docs/future-proof-architecture.md) を参照。

---

## 構成

```
rokid-docscan-starter/
├── app/
│   ├── main.py        # FastAPI エンドポイント
│   ├── matching.py    # pHash / hamming / OCR-MD5 / スコアリング
│   ├── hud.py         # 3行 HUD ペイロード生成
│   ├── summarize.py   # 要約シム（analyzer に委譲）
│   ├── version.py     # API/matcher/HUD/analyzer の契約バージョン
│   ├── analyzers/     # プロバイダ非依存の解析ポート + レジストリ
│   │   ├── base.py            # Analyzer インターフェース
│   │   ├── registry.py        # モデルルーティング（local/cloud 差替点）
│   │   └── local_placeholder.py  # オフライン既定（creds不要）
│   ├── db.py          # sqlite3 ストレージ
│   └── config.py      # データ保存先（ROKID_DATA_DIR で上書き可）
├── tests/             # pytest（照合 + API + バージョン + レジストリ）
├── scripts/
│   ├── make_sample_pages.py  # curl 用サンプル画像生成
│   └── evaluate.py           # 照合評価 → JSON レポート
├── docs/
│   ├── implementation-notes.md
│   ├── user-operation-guide.md     # ユーザー操作 / 自動化 / 設計判断
│   └── future-proof-architecture.md# 将来対応アーキテクチャ
├── data/images/       # 画像保存先（実行時に自動生成）
├── requirements.txt
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
- 起動時に `data/images/` と `data/docscan.db` が自動生成されます。

## テスト

```bash
pytest -q
```

照合ロジック（pHash 決定性 / ハミング距離 / OCR-MD5 正規化 / スコアリング /
HIT・LOW CONF・NO PAGE 判定）、API の登録〜finalize〜照合フロー、
バージョンメタデータ、analyzer レジストリを、PIL で生成した合成画像で検証します。

## 評価（実サンプル撮影後の検証に使用）

ユーザーが実機でサンプルを撮影・登録した後、照合品質としきい値提案を JSON で出力:

```bash
# 既存DBに対して評価
ROKID_DATA_DIR=data python scripts/evaluate.py --db data/docscan.db --out report.json
# 合成画像で素早く確認
python scripts/evaluate.py --synthetic 5
```

`self_match_accuracy` と `suggested_thresholds` を見て `app/matching.py` の
しきい値（D5）を調整します。

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
# {"status":"ok"}
```

### 2. 文書を作成

```bash
curl -s -X POST http://127.0.0.1:8000/v1/documents \
  -H 'Content-Type: application/json' \
  -d '{"title":"設計仕様書 v1","capture_device":"CXR-S"}'
# {"document_id":1,"title":"設計仕様書 v1","capture_device":"CXR-S","status":"open"}
```

### 3. ページを追加（画像 + 任意の OCR テキスト）

```bash
curl -s -X POST http://127.0.0.1:8000/v1/documents/1/pages \
  -F page_index=0 \
  -F image=@page0.png \
  -F ocr_text='1ページ目の本文テキスト'
# {"page_id":1,"document_id":1,"page_index":0,"phash":"...","ocr_md5":"...","image_path":"..."}
```

> `ocr_text` を省略した場合は、画像バイト列の MD5 をプレースホルダとして
> `ocr_md5` に記録します（OCR 未実装でも完全一致照合の足がかりになります）。

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
  -F document_id=1 \
  -F image=@query.png \
  -F fast_ocr_text='1ページ目の本文テキスト'
```

レスポンス例（HIT）:

```json
{
  "document_id": 1,
  "verdict": "HIT",
  "best_page": {"page_id":1,"page_index":0,"hamming":0,"ocr_match":true,"confidence":1.0},
  "confidence": 1.0,
  "hud": {"verdict":"HIT","confidence":1.0,"lines":["PAGE 1/2","1ページ目の本文テキスト","conf 1.00  hd 0"]},
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

## 照合ロジック（決定的）

`app/matching.py` 内のしきい値で挙動を制御します。

- **pHash**: 画像を 32×32 グレースケール化 → 2次元 DCT → 低周波 8×8 ブロックを
  中央値で2値化した **64bit** ハッシュ。
- **ハミング距離**:
  - `<= HAMMING_STRONG (6)` … 視覚的に確実な一致（視覚信頼度 1.0）
  - `>= HAMMING_WEAK (16)` … 無関係（視覚信頼度 0.0）
  - 間は線形補間。
- **OCR-MD5 ボーナス**: クエリと候補の正規化 OCR テキスト MD5 が完全一致したら
  `+OCR_MD5_BONUS (0.35)`。正規化は「前後空白除去・連続空白を単一化・小文字化」。
- **判定**: 合成信頼度（0..1 にクリップ）が
  `>= CONF_OK (0.62)` → `HIT` / `>= CONF_LOW (0.40)` → `LOW_CONF` / それ未満 → `NO_PAGE`。

しきい値は撮影環境（照明・ブレ・解像度）に応じてチューニングしてください。

---

## Rokid Glasses / Android コンパニオンアプリへのマッピング

この MVP は **サーバ側のみ** です。実運用では以下の3層構成を想定します。

```
[Rokid Glasses]  ──BLE/Wi-Fi──  [Android コンパニオンアプリ]  ──HTTPS──  [本サーバ]
  カメラ / HUD表示                 撮影・端末OCR・通信・UI            登録/照合/要約
```

| 役割 | 実機での担当 | 本 MVP での代替 |
|------|--------------|-----------------|
| 撮影 | Glasses カメラ（CXR-S/CXR-M） | クライアントがアップロードする画像 |
| 端末側 高速 OCR | Android 側 ML Kit 等 | `ocr_text` / `fast_ocr_text` フォーム値 |
| ページ照合 | 本サーバ（pHash + OCR-MD5） | 同左（そのまま） |
| HUD 表示 | Glasses の単眼ディスプレイ（3行） | `hud.lines`（3行）をそのまま描画 |
| 文書登録ワークフロー | コンパニオンアプリ UI | `/v1/documents` → `/pages` → `/finalize` |

- **登録フロー**: コンパニオンアプリで複数ページを連続撮影 →
  各ページを `POST /v1/documents/{id}/pages` → 最後に `/finalize`。
- **照合フロー**: グラスで紙を見る → アプリが1フレーム取得＋端末OCR →
  `POST /v1/match` → 返ってきた `hud.lines`（3行）をグラスに表示。
- HUD は単眼・低解像度を想定し、**常に3行・短文** で返します。

実機 SDK（公式 Rokid Glasses SDK / CXR 系 / Rizon / Agent Store など）の
具体的な差し込み箇所は [`docs/implementation-notes.md`](docs/implementation-notes.md)
を参照してください。

---

## Docker（任意）

```bash
docker compose up --build
# http://127.0.0.1:8000/health
```

ローカル Python 実行を優先してください。Docker は任意です。

## 制限事項

- OCR は未実装（テキストはクライアントから受け取るプレースホルダ）。
- pHash は純 Python 実装（numpy/imagehash 非依存）で、大量ページでは低速。
- 認証・マルチテナント・並行書き込み制御は未実装（MVP のため）。

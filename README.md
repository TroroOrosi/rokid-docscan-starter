# Rokid DocScan（紙資料スキャン・ページ照合・解答・解説サーバ）

Rokid Glasses で撮影した紙資料を「文書」として登録し、後から目の前の紙が
**どのページか** を端末側 OCR とサーバ側の知覚ハッシュ（pHash）で
照合して、グラス上の小さな HUD（3行）に結果を返すサーバです。加えて
**入試問題ソルバー**と**資料解説（撮影なし）**モードを備えます。

- **既定はオフラインでローカル実行可能**。外部クレデンシャル不要で全機能が動きます。
- **実 AI もそのまま利用可能**：analyzer / solver / explainer / extractor の各ポートに
  **Anthropic Claude を使う実アダプタ `claude` を同梱**。環境変数だけで実運用に切り替わり、
  キー未設定時は自動でローカルにフォールバックします（[実モデル接続](#実モデル接続claude-アダプタ)）。
- ストレージは **SQLite + ローカルファイルシステム**（Postgres / MinIO 不要）。
- 照合は **決定的**（pHash のハミング距離 + OCR テキスト類似度ボーナス）。
- **グラス本体アプリ（CXR-L）とグラス本体 AI の接続**は
  [`docs/cxr-l-integration.md`](docs/cxr-l-integration.md)、実機差し込み全般は
  [`docs/implementation-notes.md`](docs/implementation-notes.md) を参照。
- 現在のバージョン: **APP 0.4.0 / API 1.6.0**。

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
│   ├── main.py        # FastAPI エンドポイント（match / exam / explain）
│   ├── matching.py    # pHash / hamming / OCR 類似度 / スコアリング
│   ├── hud.py         # 3行 HUD ペイロード生成（/match 用）
│   ├── glasses_view.py# グラス表示ビルダー（exam / explain 用・無音契約）
│   ├── overlay.py     # 解答欄オーバーレイ（2D画像アンカー）
│   ├── layout.py      # 設問構造解析（設問番号/本文/選択肢/解答欄box）
│   ├── subjects.py    # 科目推定（数学/英語/古文/物理/化学/歴史/現代文）
│   ├── retrieval.py   # RAG 横断検索（既存 documents/pages → 根拠）
│   ├── summarize.py   # 要約シム（analyzer に委譲）
│   ├── explainer.py   # Explainer ポート（ExplainRequest / ExplainResult / ABC）
│   ├── llm.py         # ★実 AI ブリッジ（Anthropic Claude、遅延import・注入可）
│   ├── version.py     # 各契約バージョン（app 0.4.0 / api 1.6.0 ほか）
│   ├── config.py      # 保存先・フィーチャーフラグ（ROKID_* / ANTHROPIC_API_KEY）
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
│   ├── cxr-l-integration.md         # ★CXR-L 単体アプリ ⇄ 本体AI ⇄ 本サーバ
│   ├── implementation-notes.md      # 実機/実AI 差し込み点・CXR SDK・実アダプタ
│   ├── user-operation-guide.md      # ユーザー操作 / 自動化 / 設計判断
│   ├── future-proof-architecture.md # 将来対応アーキテクチャ
│   ├── explain-sessions.md          # 資料解説モード詳細・curl 例
│   ├── glasses-ux-contract.md       # グラス UX 契約（操作・HUD・無音・無フラッシュ）
│   ├── exam-solver-architecture.md  # 解答モードアーキテクチャ
│   └── rokid-led-dev-utility.md     # 録画LED診断ツールの詳細・警告
├── data/images/       # 画像保存先（実行時に自動生成）
├── requirements.txt   # コア依存（anthropic は任意・コメント参照）
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
バージョンメタデータ、analyzer レジストリ、explain-sessions フルフローを、
PIL で生成した合成画像で検証します（外部クレデンシャル不要・オフライン完結）。

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
  "best_page": {"page_id":1,"page_index":0,"hamming":0,"ocr_match":true,"ocr_similarity":1.0,"confidence":1.0},
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
[Rokid Glasses]  ─Wi-Fi 6 直結─  [本サーバ]              （CXR-L 単体アプリ構成）
  カメラ / 本体AI / HUD表示         登録/照合/解答/解説

[Rokid Glasses] ─BLE/Wi-Fi─ [スマホ CXR-M コンパニオン] ─HTTPS─ [本サーバ]（従来構成）
```

| 役割 | 実機での担当 | 本サーバでの受け口 |
|------|--------------|-----------------|
| 撮影 | Glasses カメラ（CXR-L `IMediaStreamService`／CXR-M） | クライアントがアップロードする画像 |
| 端末側 OCR / 認識 | 本体 AI（`com.rokid.sprite.aiapp`）／ML Kit／Vision | `ocr_text` / `fast_ocr_text` フォーム値 |
| ページ照合 | 本サーバ（pHash + OCR 類似度） | 同左（そのまま） |
| 要約/解答/解説/抽出 | 本サーバ（既定ローカル、任意で `claude` 実AI） | 各 registry のアダプタ |
| HUD 表示 | Glasses の**両眼**ディスプレイ（3行） | `hud.lines` / `glasses_view.lines`（3行） |
| 文書登録ワークフロー | グラス/コンパニオン UI | `/v1/documents` → `/pages` → `/finalize` |

- 実機ハードウェア仕様（**両眼** 480×398 Micro-LED、AR1+NXP RT600、IMX681 12MP、
  YodaOS/Android 12 API32 など）と CXR-M/S/L の役割は、ウェブ検証済みの値を
  [`docs/cxr-l-integration.md`](docs/cxr-l-integration.md) にまとめています。
- **グラス本体 AI をサーバに繋ぐ**には (A) サーバ側の `claude` 実アダプタを使う、
  (B) 本体 AI の OCR/認識結果を `ocr_text` として送る、の2経路があります（同 doc §4）。

---

## 資料解説モード（explain-sessions / グラス単体・無音 UX）

API v1.6.0 で追加。登録済み文書を**グラス単体で全ページ読み取り → 解説を HUD に段階表示**する機能です。

```
[scanning]  各ページをボタン1回で読み取り
               HUD: 「P02 読取済 ✓  (2/5ページ完了)」（2秒後消去）

  ダブル長押し（Back ボタン長押し×2）
               HUD: 「読み取り完了 / 5/5ページ / タップで解説開始」
      ↓
[ready]     タップ（TP-単击 = KEYCODE_DPAD_CENTER）
               HUD: 「P01/5 ★★★ / (概要テキスト) / ← 次ページ  ↓ 詳しく」
      ↓
[explaining]
  TP-左滑（スワイプ左）  → 次テキストスライス（テレプロンプター）
  TP-右滑（スワイプ右）  → 前テキストスライス
  TP-快速左滑（速スワイプ左）→ 次ページ（view_page+1）
  TP-快速右滑（速スワイプ右）→ 前ページ（view_page-1）
  TP-長押し             → 次の解説段階（overview→detail→evidence）
```

詳細な仕様・curl 例・操作マッピング表は
[docs/explain-sessions.md](docs/explain-sessions.md) を参照。

---

## 解答モード（入試問題ソルバー / グラス単体・無音 UX）

ページ照合モードに加え、**未登録の入試問題を撮影 → 構造化・科目推定 → 解答・解法・根拠を
グラス内の3行 HUD（段階・ページ送り）で表示**する解答モードを追加しました（`/v1/exam-sessions`）。

- ユーザーが操作・閲覧するのは**眼鏡だけ**（スマホは通信・AI処理を担う裏方）。
- **無音・無フラッシュ・無アニメ・無点滅**を契約化（`GET /v1/settings` で公示、HUD は最大3行）。
- **音声操作は設定で ON/OFF**（既定 OFF＝ボタン/タッチ操作）。
- 解答ソルバーは既定で**オフラインのプレースホルダ**（実際には解かない＝不正利用ガード）。
  **実モデル `claude` を同梱**し、`ROKID_SOLVER=claude`＋`ANTHROPIC_API_KEY` で実解答に切替
  （[実モデル接続](#実モデル接続claude-アダプタ)）。クラウド→ローカルの**二段フォールバック**
  （`ROKID_SOLVER_TIERS`、`solve_with_fallback`）で圏外/失敗でも HUD は返ります。
- **メディア抽出**（数式/図/表/グラフ）は `app/extractors/`（`ROKID_EXTRACTOR`。`claude` で実抽出）。`add_question` 応答の `media` に載ります。
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

## 録画 LED 開発用診断ツール（任意・実機所有者専用）

実機の **録画インジケータ（プライバシー）LED** を調査するための、**サーバとは独立した
開発者向け診断ツール** を `scripts/rokid_led.py` に追加しました。**サーバや文書スキャン／
解答フローからは一切呼ばれません**。`GET /v1/settings` の `capture.privacy_led` は引き続き
`always_on / tamper:forbidden` を公示し、本ツールはその契約を変更しません。

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

## 実モデル接続（Claude アダプタ）

各プロバイダポート（analyzer / solver / explainer / extractor）には、**Anthropic
Claude を使う実アダプタ `claude` を同梱**しています。これがかつての「ダミー
（プレースホルダ）」を**実運用可能**にする部分です。

- 既定は `local`（オフライン・クレデンシャル不要）。`ROKID_*=claude` で実 AI に切替。
- `ANTHROPIC_API_KEY` が無い／`anthropic` 未インストールなら、**ネットワークに一切
  触れず自動でローカルにフォールバック**します（solver は二段フォールバック、
  他は内部フォールバック）。サーバは常に応答します。
- 共通クライアントは `app/llm.py`（公式 `anthropic` SDK を遅延 import・注入可能）。

```bash
# 実 AI を有効化（任意の依存を入れる）
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...
export ROKID_SOLVER=claude ROKID_EXPLAINER=claude \
       ROKID_ANALYZER=claude ROKID_EXTRACTOR=claude
export ROKID_LLM_MODEL=claude-opus-4-8   # 任意。安価にするなら claude-haiku-4-5
uvicorn app.main:app --port 8000
```

| 環境変数 | 既定 | 役割 |
|----------|------|------|
| `ANTHROPIC_API_KEY` | （なし） | 実呼び出しに必須。未設定なら全ポートがローカルへ |
| `ROKID_ANALYZER` / `ROKID_SOLVER` / `ROKID_EXPLAINER` / `ROKID_EXTRACTOR` | `local` | `claude` で実 AI にルーティング |
| `ROKID_LLM_MODEL` | `claude-opus-4-8` | 使用モデル id |
| `ROKID_LLM_MAX_TOKENS` | `1024` | 応答トークン上限 |
| `ROKID_SOLVER_TIERS` | （単一） | 二段フォールバック順（例 `claude,local`） |

> グラス本体アプリ（CXR-L）から本体 AI を繋ぐ全体像は
> [`docs/cxr-l-integration.md`](docs/cxr-l-integration.md) を参照。

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
- pHash は純 Python 実装（numpy/imagehash 非依存）で、大量ページでは低速。
  高速化は scipy/imagehash 等への置換が定石（依存を増やすため既定では未採用）。
- 認証・マルチテナント・並行書き込み制御は未実装。
- `claude` アダプタは任意依存 `anthropic` と `ANTHROPIC_API_KEY` が必要。未設定なら
  ローカル実装で動作（実 AI の出力は得られません）。

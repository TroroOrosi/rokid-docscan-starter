# 資料解説モード（explain-sessions）仕様書

API v1.6.0 で追加。登録済み文書を Rokid Glasses **単体で全ページ読み取り→解説を HUD に段階表示**する機能です。
音声不要・フラッシュなし・スマホ画面なしで完結します。

---

## 前提条件

1. サーバが起動している（`uvicorn app.main:app --port 8000`）
2. 文書が登録・finalize 済みであること（`status: ready`）
3. `ROKID_EXPLAINER` 環境変数が未設定の場合、自動的にローカルプレースホルダが使用される

---

## ユーザーが行う手順（グラス単体・完全無音）

### フェーズ 1: スキャン（scanning）

| ステップ | ユーザーの操作 | グラス HUD の表示 | 補足 |
|---------|------------|------------------|------|
| 1 | サーバで解説セッションを作成（スマホ側アプリが自動実行） | `解説モード開始 / スキャン中 / ボタンで読取` | セッション `status = scanning` |
| 2 | **ページを向けて Back ボタンを1回押す** | `P01 読取済 ✓ / 1/5ページ完了 / 続けて読み取り` | `ttl_sec:2` で自動消去 |
| 3 | ページを変えて再度1回押す（全ページ分繰り返す） | `P02 読取済 ✓ / 2/5ページ完了 / ...` | 同一ページを複数回スキャンしても上書き（べき等） |
| 4 | **全ページ読み終えたらダブル長押し（Back ボタン長押し×2回）** | `読み取り完了 / 5/5ページ / タップで解説開始` | `ttl_sec:3` で自動消去・`status = ready` へ遷移 |

> **ダブル長押しとは**: Back ボタンを長押し（約1秒）→ 離す → 500ms 以内に再度長押し。
> 誤操作防止のため2回連続が必要です。

### フェーズ 2: 解説閲覧（explaining）

| ステップ | ユーザーの操作 | グラス HUD の表示 | KeyCode |
|---------|------------|------------------|---|
| 5 | **タッチパッドをタップ** | `P01/5 ★★★ / (概要テキスト1行目) / ← 次ページ ↓ 詳しく` | `KEYCODE_DPAD_CENTER` |
| 6 | テキストが3行を超える場合、**スワイプ左**で続きを読む | 次の3行が表示される | `KEYCODE_DPAD_LEFT`（連続） |
| 7 | 前に戻りたい場合、**スワイプ右** | 前の3行に戻る | `KEYCODE_DPAD_RIGHT`（連続） |
| 8 | 次のページへは**速スワイプ左**（素早くスワイプして離す） | `P02/5 ★★★ / ...` | `KEYCODE_DPAD_UP`（単発） |
| 9 | 前のページへは**速スワイプ右** | `P01/5 ★★★ / ...` | `KEYCODE_DPAD_DOWN`（単発） |
| 10 | より詳しい解説は**タッチパッド長押し** | `P01/5 詳細 / (詳細テキスト)` | `KEYCODE_TV` |
| 11 | さらに根拠・証拠は**もう一度長押し** | `P01/5 根拠 / (evidence テキスト)` | `KEYCODE_TV` |
| 12 | 解説を閉じるには**ダブルタップ** | HUD が消える | `KEYCODE_ENTER` |

> **スワイプ左 vs 速スワイプ左の違い**:
> - 通常スワイプ（ゆっくり）= テキストを1スライス送る（テレプロンプター）
> - 速スワイプ（素早くはじく）= ページ全体を変える
>
> これは Rokid 公式キーコード定義による仕様です（通常スワイプ = `KEYCODE_DPAD_LEFT/RIGHT`
> 連続、速スワイプ = `KEYCODE_DPAD_UP/DOWN` 単発）。

---

## API エンドポイント詳細

### POST `/v1/explain-sessions`

セッションを作成します。文書は `status: ready`（finalize 済み）である必要があります。

```bash
curl -s -X POST http://127.0.0.1:8000/v1/explain-sessions \
  -H 'Content-Type: application/json' \
  -d '{"document_id": 1}'
```

レスポンス例:

```json
{
  "session_id": 1,
  "document_id": 1,
  "status": "scanning",
  "scanned_pages": [],
  "total_pages": 5,
  "operations": {
    "scan_page": "button_single_press",
    "commit_scan": "double_long_press"
  }
}
```

### POST `/v1/explain-sessions/{session_id}/scan`

ページ画像を1枚スキャン登録します（`status: scanning` のときのみ有効）。

```bash
curl -s -X POST http://127.0.0.1:8000/v1/explain-sessions/1/scan \
  -F image=@page0.png
```

レスポンス例（無音・2秒表示のスキャン ACK）:

```json
{
  "scanned_pages": [0],
  "scan_ack": {
    "lines": ["P01 読取済 ✓", "1/5ページ完了", "続けて読み取り"],
    "ttl_sec": 2
  }
}
```

- 同一ページを複数回送ってもべき等（スキャン済みリストは重複しない）。
- `status: ready` 以降に呼ぶと `409 Conflict`。

### POST `/v1/explain-sessions/{session_id}/commit`

スキャン完了を宣言し、`status: ready` に遷移します（ダブル長押しに対応）。

```bash
curl -s -X POST http://127.0.0.1:8000/v1/explain-sessions/1/commit
```

レスポンス例:

```json
{
  "session_id": 1,
  "status": "ready",
  "scanned_pages": [0, 1, 2, 3, 4],
  "commit_ack": {
    "lines": ["読み取り完了", "5/5ページ", "タップで解説開始"],
    "ttl_sec": 3
  }
}
```

- 既に `ready` の場合も同じレスポンスを返します（べき等・ハードウェアバウンス対策）。

### GET `/v1/explain-sessions/{session_id}/explain`

指定ページの解説 HUD を取得します（`status: ready` または `explaining` のみ有効）。

**クエリパラメータ:**

| パラメータ | 型 | 既定 | 説明 |
|---|---|---|---|
| `page_index` | int | 必須 | 解説するページ番号（0始まり） |
| `stage` | string | `overview` | 解説段階（`overview` / `detail` / `evidence`） |
| `view_page` | int | `0` | テキストスライスのページ番号（テレプロンプター用） |

```bash
# 概要（既定）
curl -s 'http://127.0.0.1:8000/v1/explain-sessions/1/explain?page_index=0'

# 詳細段階
curl -s 'http://127.0.0.1:8000/v1/explain-sessions/1/explain?page_index=0&stage=detail'

# テキストの2ページ目
curl -s 'http://127.0.0.1:8000/v1/explain-sessions/1/explain?page_index=0&view_page=1'
```

レスポンス例:

```json
{
  "glasses_view": {
    "stage": "overview",
    "lines": ["P01/5 ★★★", "設計書の概要テキスト", "章構成の説明"],
    "page_label": "P01/5",
    "view_page": 0,
    "total_view_pages": 3,
    "nav": {
      "operations": {
        "next_view_page": "swipe_left",
        "prev_view_page": "swipe_right",
        "next_doc_page": "fast_swipe_left",
        "prev_doc_page": "fast_swipe_right",
        "next_stage": "swipe_down",
        "close": "double_tap"
      }
    }
  }
}
```

- `status: scanning` のセッションに呼ぶと `409 Conflict`。
- 存在しない `page_index` は `404 Not Found`。
- 無効な `stage` 値は `400 Bad Request`。
- 初回呼び出し時に `status` が `explaining` に遷移します。

### GET `/v1/explain-sessions/{session_id}/history`

閲覧履歴（解説済みビュー一覧）を取得します。

```bash
curl -s http://127.0.0.1:8000/v1/explain-sessions/1/history
```

レスポンス例:

```json
{
  "session_id": 1,
  "document_id": 1,
  "status": "explaining",
  "explained_views": [
    {
      "page_index": 0,
      "stage": "overview",
      "verdict": "HIT",
      "hud_lines": ["P01/5 ★★★", "...", "..."]
    }
  ]
}
```

---

## ステータス遷移図

```
POST /explain-sessions
        │
        ▼
   [scanning]  ←── POST /scan（ページごとに繰り返す）
        │
   POST /commit（ダブル長押し）
        │
        ▼
     [ready]  ←── POST /commit（べき等：再送しても safe）
        │
   GET /explain（タップ）
        │
        ▼
  [explaining]  ←── GET /explain（繰り返し閲覧）
```

---

## Explainer の差し替え（将来）

`ROKID_EXPLAINER` 環境変数でプロバイダを切り替えられます。

| 値 | 説明 |
|---|---|
| `local`（既定） | オフラインのプレースホルダ。外部 API 不要。 |
| `gemini` | Google Gemini（要 API キー `GOOGLE_API_KEY`） |
| `openai` | OpenAI GPT-4o（要 API キー `OPENAI_API_KEY`） |

```bash
# Gemini に切り替えて起動
ROKID_EXPLAINER=gemini GOOGLE_API_KEY=your_key uvicorn app.main:app --port 8000
```

`GET /v1/version` の `explainers` リストでアクティブなアダプタと `offline` フラグを確認できます。

---

## テスト（オフライン・クレデンシャル不要）

```bash
pytest tests/test_explain_api.py -v
```

7クラス・22テストケース。外部 API・クレデンシャル不要でローカル完結。

---

## 制限・注意事項

- Explainer がローカルプレースホルダの場合、解説テキストはダミーです（実際のドキュメント内容を解析しません）。実運用では `ROKID_EXPLAINER` を Gemini/OpenAI 等に切り替えてください。
- スキャンフェーズで送った画像は照合用途です。解説の質はページ登録時の `ocr_text` の精度に依存します。
- 認証・マルチテナント・並行書き込み制御は未実装（MVP のため）。

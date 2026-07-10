# 資料解説モード（explain-sessions）仕様書

**UX 第 v1.7 世代**の撮影なし設計（HTTP エンベロープは現在 `API_VERSION = 1.9.0`、
`APP_VERSION = 0.9.0`）。登録済み文書を Rokid Glasses
**単体でページナビゲーション→解説を HUD に段階表示**する機能です。

**撮影なし・画像送信なし・音声不要・フラッシュなし・スマホ画面なしで完結します。**

> 設計原則: Rokid ネイティブの「映っている物体の解説」体験と同様に、
> ユーザーはカメラボタンを押さず、ページ送りボタンだけで資料を読み進めます。
> サーバーは `current_page_index` カウンターを管理するだけで、画像照合は不要です。

---

## 前提条件

1. サーバが起動している（`uvicorn app.main:app --port 8000`）
2. 文書が登録・finalize 済みであること（各ページに `ocr_text` と `summary` がある状態）
3. `ROKID_EXPLAINER` 環境変数が未設定の場合、自動的にローカルプレースホルダが使用される

---

## ユーザーが行う手順（グラス単体・撮影なし）

### フェーズ 1: セッション開始

| ステップ | ユーザーの操作 | グラス HUD の表示 | 補足 |
|---------|------------|------------------|------|
| 1 | スマホ側アプリがセッションを自動作成 | `→ P01/5 / タップで解説` | `status=ready`, `current_page_index=0` |

### フェーズ 2: 解説閲覧

| ステップ | ユーザーの操作 | グラス HUD の表示 | KeyCode |
|---------|------------|------------------|---|
| 2 | **タップ**（1本指） | `P01/5 ★★★ / (概要テキスト) / タップ 次段階` | `single_tap`（KeyCode 23・未検証） |
| 3 | テキストが3行を超える場合 **2本指スワイプ下** で続きを読む | 次の3行が表示 | `two_finger_swipe_down` |
| 4 | 前に戻りたい場合 **2本指スワイプ上** | 前の3行に戻る | `two_finger_swipe_up` |
| 5 | 詳細が欲しい場合 **もう一度タップ** | `P01/5 詳細 / (詳細テキスト)` | `single_tap` |
| 6 | さらに根拠・参照ページは **さらにタップ** | `P01/5 根拠 / 参照: P03,P05` | `single_tap` |
| 7 | **次のページへ**: 2本指スワイプ左 | `→ P02/5 / タップで解説` | `two_finger_swipe_left` |
| 8 | **前のページへ**: 2本指スワイプ右 | `← P01/5 / タップで解説` | `two_finger_swipe_right` |
| 9 | 解説を閉じる場合 **ダブルタップ** | HUD が消える | `double_tap` |

> **2本指スワイプ左右（ページ送り）と上下（テキスト送り）の違い**（公式の
> 「左右=前後ページ・上下=スクロール」に対応）:
> - 上下スワイプ = 現在ページ内のテキストを1スライス送る/戻す
> - 左右スワイプ = サーバーに POST /next-page・/prev-page を送り、ページ全体を変える
>
> ページ送りは**撮影を伴いません**。サーバー内のカウンターをインクリメントするだけです。
>
> ⚠️ KeyCode 値は旧・単眼 Rokid Glass 由来で**未実測**（`keycodes_verified:false`）。
> 実機計測と `ROKID_KEYMAP` 上書きは [real-device-operation.md](real-device-operation.md) §5。

---

## API エンドポイント詳細

### POST `/v1/explain-sessions`

セッションを作成します。作成直後から `status: ready`（撮影フェーズなし）。

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
  "status": "ready",
  "current_page_index": 0,
  "total_pages": 5
}
```

### GET `/v1/explain-sessions/{session_id}/explain`

**現在のページ**（`current_page_index`）の解説 HUD を取得します。画像送信不要。

**クエリパラメータ:**

| パラメータ | 型 | 既定 | 説明 |
|---|---|---|---|
| `stage` | string | `overview` | 解説段階（`overview` / `detail` / `evidence`） |
| `view_page` | int | `0` | テキストスライスのページ番号（テレプロンプター用） |

```bash
# 概要（既定）— page_index 指定不要
curl -s 'http://127.0.0.1:8000/v1/explain-sessions/1/explain'

# 詳細段階
curl -s 'http://127.0.0.1:8000/v1/explain-sessions/1/explain?stage=detail'

# テキストの2ページ目
curl -s 'http://127.0.0.1:8000/v1/explain-sessions/1/explain?view_page=1'
```

レスポンス例:

```json
{
  "current_page_index": 0,
  "total_doc_pages": 5,
  "glasses_view": {
    "stage": "overview",
    "lines": ["P01/5 ★★★", "設計書の概要テキスト", "章構成の説明"],
    "page_label": "P01/5",
    "view_page": 0,
    "total_view_pages": 3,
    "nav": {
      "operations": {
        "next_view_page": "two_finger_swipe_down",
        "prev_view_page": "two_finger_swipe_up",
        "next_stage": "single_tap",
        "next_doc_page": "two_finger_swipe_left",
        "prev_doc_page": "two_finger_swipe_right"
      }
    }
  }
}
```

### POST `/v1/explain-sessions/{session_id}/next-page`

`current_page_index` を +1 します（撮影なし）。最終ページでは変化しません。

```bash
curl -s -X POST http://127.0.0.1:8000/v1/explain-sessions/1/next-page
```

レスポンス例:

```json
{
  "current_page_index": 1,
  "total_pages": 5,
  "at_last": false,
  "nav_ack": {
    "lines": ["→ P02/5", "タップで解説"],
    "ttl_sec": 1.5
  }
}
```

### POST `/v1/explain-sessions/{session_id}/prev-page`

`current_page_index` を -1 します（撮影なし）。先頭ページでは変化しません。

```bash
curl -s -X POST http://127.0.0.1:8000/v1/explain-sessions/1/prev-page
```

### GET `/v1/explain-sessions/{session_id}/history`

閲覧履歴（解説済みビュー一覧）を取得します。

```bash
curl -s http://127.0.0.1:8000/v1/explain-sessions/1/history
```

---

## ステータス遷移図

```
POST /explain-sessions
        │
        ▼
     [ready]  ← 作成直後から解説可能（スキャンフェーズなし）
        │
   GET /explain（タップ）
        │
        ▼
  [explaining]  ←── GET /explain（繰り返し閲覧）
                ←── POST /next-page / /prev-page（ページ移動、撮影なし）
```

---

## ページナビゲーション詳細

```
[P01]──two_finger_swipe_left──▶[P02]──two_finger_swipe_left──▶[P03]  ...  [P05]
      ◀──two_finger_swipe_right──     ◀──two_finger_swipe_right──

各ページ内:
  single_tap             → GET /explain?stage=overview
  single_tap（表示中）    → GET /explain?stage=detail
  single_tap（さらに）    → GET /explain?stage=evidence
  two_finger_swipe_down  → GET /explain?view_page=N+1  (テキスト送り)
  two_finger_swipe_up    → GET /explain?view_page=N-1  (テキスト戻し)
```

---

## 廃止されたエンドポイント（v1.6→v1.7）

| 旧エンドポイント | 廃止理由 | 代替 |
|---|---|---|
| `POST /scan` | 画像アップロードによるpHash照合が不要に | `POST /next-page` / `POST /prev-page` |
| `POST /commit` | scaningフェーズ自体がなくなったため | セッション作成直後から `status=ready` |

---

## Explainer の差し替え（将来）

`ROKID_EXPLAINER` 環境変数でプロバイダを切り替えられます。

| 値 | 説明 |
|---|---|
| `local`（既定） | オフラインのプレースホルダ。外部 API 不要。 |
| `openai`（同梱の実アダプタ） | OpenAI GPT（要 `OPENAI_API_KEY`＋`pip install openai`。モデルは `ROKID_LLM_MODEL` 必須指定） |
| `gemini`（同梱の実アダプタ） | Google Gemini（要 `GOOGLE_API_KEY`＋`pip install google-genai`。モデルは `ROKID_LLM_MODEL` 必須指定） |
| `claude`（同梱の実アダプタ） | Anthropic Claude（要 `ANTHROPIC_API_KEY`＋`pip install anthropic`。モデル既定 `claude-opus-4-8`） |

```bash
pip install openai
ROKID_EXPLAINER=openai OPENAI_API_KEY=sk-... ROKID_LLM_MODEL=<現行のGPTモデルid> \
  uvicorn app.main:app --port 8000
```

- キー未設定／SDK 未導入なら、**ネットワークに触れず自動でローカルへフォールバック**します。
- 実装は `app/explainers/claude.py` の `LLMExplainer`（プロバイダ非依存・共通クライアントは `app/llm.py`）。
- 他ベンダを足したい場合は `Explainer` ポートにアダプタを1つ実装して `register_explainer()`。

---

## テスト（オフライン・クレデンシャル不要）

```bash
pytest tests/test_explain_api.py -v
```

---

## 制限・注意事項

- Explainer がローカルプレースホルダの場合、解説テキストは要約/OCR の整形にとどまります。実運用では `ROKID_EXPLAINER=openai|gemini|claude`＋各社 API キーで実 AI 解説に切り替えてください（同梱済み）。
- 解説の質はページ登録時の `ocr_text` の精度に依存します。
- 認証・マルチテナント・並行書き込み制御は未実装（現段階では対象外）。
- `current_page_index` はサーバー側でクランプ処理されます（0以下・総ページ数以上にはなりません）。

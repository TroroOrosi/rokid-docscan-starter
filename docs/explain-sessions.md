# 資料解説モード（explain-sessions）仕様書

**UX 第 v1.7 世代**の撮影なし設計（HTTP エンベロープは `API_VERSION = 1.6.0`、
`APP_VERSION = 0.4.0`）。登録済み文書を Rokid Glasses
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
| 2 | **タップ**（タッチパッド中央） | `P01/5 ★★★ / (概要テキスト) / 長押し 次段階` | `KEYCODE_DPAD_CENTER (23)` |
| 3 | テキストが3行を超える場合 **スワイプ左** で続きを読む | 次の3行が表示 | `KEYCODE_DPAD_LEFT` |
| 4 | 前に戻りたい場合 **スワイプ右** | 前の3行に戻る | `KEYCODE_DPAD_RIGHT` |
| 5 | 詳細が欲しい場合 **長押し** | `P01/5 詳細 / (詳細テキスト)` | `KEYCODE_TV (170)` |
| 6 | さらに根拠・参照ページは **もう一度長押し** | `P01/5 根拠 / 参照: P03,P05` | `KEYCODE_TV (170)` |
| 7 | **次のページへ**: 速スワイプ左（素早くはじく） | `→ P02/5 / タップで解説` | `KEYCODE_DPAD_UP (19)` |
| 8 | **前のページへ**: 速スワイプ右 | `← P01/5 / タップで解説` | `KEYCODE_DPAD_DOWN (20)` |
| 9 | 解説を閉じる場合 **ダブルタップ** | HUD が消える | `KEYCODE_ENTER (66)` |

> **速スワイプ（ページ送り）と通常スワイプ（テキスト送り）の違い**:
> - 通常スワイプ（ゆっくり）= 現在ページ内のテキストを1スライス送る
> - 速スワイプ（素早くはじく）= サーバーに POST /next-page を送り、ページ全体を変える
>
> ページ送りは**撮影を伴いません**。サーバー内のカウンターをインクリメントするだけです。

> **速スワイプ方向と KeyCode の対応**（Rokid 公式仕様）:
> - 速スワイプ左 = `KEYCODE_DPAD_UP (19)` → 次ページ
> - 速スワイプ右 = `KEYCODE_DPAD_DOWN (20)` → 前ページ
> 物理操作名とキーコード名が逆になっているのは公式仕様です。

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
        "next_view_page": "swipe_left",
        "prev_view_page": "swipe_right",
        "next_stage": "long_press",
        "next_doc_page": "fast_swipe_left",
        "prev_doc_page": "fast_swipe_right"
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
[P01]──fast_swipe_left──▶[P02]──fast_swipe_left──▶[P03]  ...  [P05]
      ◀──fast_swipe_right──     ◀──fast_swipe_right──

各ページ内:
  tap          → GET /explain?stage=overview
  long_press   → GET /explain?stage=detail
  long_press×2 → GET /explain?stage=evidence
  swipe_left   → GET /explain?view_page=N+1  (テキスト送り)
  swipe_right  → GET /explain?view_page=N-1  (テキスト戻し)
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
| `claude`（同梱の実アダプタ） | Anthropic Claude（要 `ANTHROPIC_API_KEY`＋`pip install anthropic`。モデルは `ROKID_LLM_MODEL`、既定 `claude-opus-4-8`） |

```bash
pip install anthropic
ROKID_EXPLAINER=claude ANTHROPIC_API_KEY=sk-ant-... uvicorn app.main:app --port 8000
```

- キー未設定／`anthropic` 未導入なら、**ネットワークに触れず自動でローカルへフォールバック**します。
- 実装は `app/explainers/claude.py`（共通クライアントは `app/llm.py`）。
- 他ベンダを足したい場合は `Explainer` ポートにアダプタを1つ実装して `register_explainer()`。

---

## テスト（オフライン・クレデンシャル不要）

```bash
pytest tests/test_explain_api.py -v
```

---

## 制限・注意事項

- Explainer がローカルプレースホルダの場合、解説テキストは要約/OCR の整形にとどまります。実運用では `ROKID_EXPLAINER=claude`＋`ANTHROPIC_API_KEY` で実 AI 解説に切り替えてください（同梱済み）。
- 解説の質はページ登録時の `ocr_text` の精度に依存します。
- 認証・マルチテナント・並行書き込み制御は未実装（MVP のため）。
- `current_page_index` はサーバー側でクランプ処理されます（0以下・総ページ数以上にはなりません）。

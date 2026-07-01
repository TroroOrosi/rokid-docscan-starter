# 実機運用ガイド（Rokid Glasses で使う）

本ドキュメントは、このリポジトリのサーバを **実機の Rokid Glasses と組み合わせて運用**する
ための、準備から実行までの一連を示します。サーバは既定でオフライン動作し、実 AI・認証は
環境変数で有効化します。グラス本体アプリ（CXR-L）と本体 AI の接続は
[cxr-l-integration.md](cxr-l-integration.md) を参照してください。

---

## 0. 構成（2経路。サーバから見れば同じ HTTP 契約）

```
[A] CXR-L 単体アプリ ── Wi-Fi 6 直結 ──▶ [本サーバ]        （スマホ不要）
[B] Glasses ─BLE/Wi-Fi─ [スマホ CXR-M] ─HTTPS─▶ [本サーバ]  （従来のコンパニオン）
```

- グラスが撮影/本体 AI で得た画像・テキストを本サーバへ送り、サーバが照合・解答・解説して
  **最大3行の HUD** を返す。表示・操作はグラス側、解析はサーバ側という役割分担。

---

## 1. 準備（人間の作業）

1. Rokid AR Platform（`ar.rokid.com/sdk`）で開発者登録し、**CXR-L SDK**（または CXR-M）を入手。
2. グラスを USB デバッグ可能にし `adb devices` で認識（ワイヤレスは `adb tcpip`/`adb connect`）。
3. サーバを動かすホスト（自宅 PC / クラウド）を用意し、グラスと同一 LAN か到達可能に。

---

## 2. サーバ起動

```bash
cp .env.example .env        # 任意（環境変数で設定する場合は不要）
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000   # 既定＝オフライン・全機能
```

- 起動時に `data/images/` と `data/docscan.db` が自動生成。
- `GET /health` が `{"status":"ok"}` を返せば稼働中。全環境変数は
  [user-operation-guide.md](user-operation-guide.md) §「環境変数一覧」を参照。

### 2-1. 実 AI を有効化（任意）

```bash
pip install anthropic          # または openai / google-genai
export ANTHROPIC_API_KEY=sk-ant-...           # OpenAI/Gemini なら OPENAI_API_KEY / GOOGLE_API_KEY
export ROKID_SOLVER=claude ROKID_EXPLAINER=claude \
       ROKID_ANALYZER=claude ROKID_EXTRACTOR=claude   # または openai / gemini
export ROKID_LLM_MODEL=claude-opus-4-8         # openai/gemini は現行モデル id を必須指定
```

- 鍵未設定/失敗時は**自動でローカル実装にフォールバック**（サーバは常に応答）。

### 2-2. 認証を掛ける（任意・公開/実機時推奨）

```bash
export ROKID_API_KEY=long-random-secret
```

- 以後、`/health`・`/v1/version`・`/v1/settings`（発見系）以外は
  `Authorization: Bearer long-random-secret` が必須。未設定なら認証なし（既定）。

### 2-3. 英語リスニングの書き起こし（任意）

```bash
export ROKID_TRANSCRIBER=openai         # または gemini
export OPENAI_API_KEY=sk-...            # gemini なら GOOGLE_API_KEY
export ROKID_TRANSCRIBE_MODEL=gpt-4o-transcribe   # gemini は ROKID_LLM_MODEL を使用
```

- 未設定なら、`/audio` に添付した `transcript`（手元の書き起こし）をそのまま使用します
  （ASR なしでもリスニング解答が成立＝オフライン可）。Anthropic は ASR 非対応。

---

## 3. グラス側（CXR-L アプリ）起動時

1. `GET /v1/settings` を取得し、**唯一の権威**として読み込む：
   - `hud`（無音・無フラッシュ・即時遷移・低輝度・最大3行）
   - `capture`（無音シャッター・プライバシー LED 不可侵）
   - `input`（gesture→KeyCode。`ROKID_KEYMAP` で実機差を吸収可）
2. `ExternalAppClient` から AIDL `IMediaStreamService` にバインドし、本体 AI
   `com.rokid.sprite.aiapp`（AI Interaction）と連携（詳細・Kotlin 例は
   [cxr-l-integration.md](cxr-l-integration.md)）。

---

## 4. モード別の操作と実行フロー

> KeyCode は `GET /v1/settings.input.gestures` の値に従う（下記は既定値）。

### 4-A. 資料照合（/v1/match）
事前登録 → 現場で照合：
```
# 登録（image は任意。撮影レスなら ocr_text だけでページを記憶）
POST /v1/documents            → document_id
POST /v1/documents/{id}/pages (page_index, [image], [ocr_text]) ×全ページ
POST /v1/documents/{id}/finalize   ← 完了宣言（要約生成・status=ready）
# 現場
Back-単(KEYCODE_BACK 4) で撮影 → 端末OCR →
POST /v1/match (document_id, image, fast_ocr_text) → HUD: PAGE n/N / LOW_CONF / NO_PAGE
```
- **撮影レス登録**：`/pages` は `image` 省略可。本体 AI が視認した資料テキストを `ocr_text` に
  渡せば、写真なしでページを記憶（`image_path=null`・`phash=""`）。照合(`/match`)は画像を使う機能
  なので、撮影レス標準フローでは下記 **4-D の文書ページ移動型**で現在ページを把握します。

### 4-B. 解答（/v1/exam-sessions）
```
POST /v1/exam-sessions {mode:"study"}                → session_id
Back-単 で問題撮影 → POST .../questions (image,[ocr_text])  ← 用紙画像を保存＋科目自動判定
TP-単击(tap, KEYCODE_DPAD_CENTER 23) → POST .../{qid}/solve → 「答え: X ★★★」
TP-長按(long_press, KEYCODE_TV 170)  → GET .../view?stage=solution→rationale→caution
TP-左/右滑(swipe, 21/22)             → テキストページ送り
```
- **用紙画像で解く（vision）**：実アダプタ（`claude`/`openai`/`gemini`）を有効化すると、
  `solve` は保存済みの**ページ画像をモデルへ添付**し、図/数式/表/選択肢を直接読んで解答します
  （OCR テキストは補助、教科別プロンプト）。**画像はクラウドへ送信**されるため、実 AI・鍵設定時
  のみ作動（未設定/失敗はローカルへフォールバック）。
- 科目は撮影時に自動判定（共通テスト準拠フル16教科）。`mode:"real"` は
  `ROKID_ALLOW_REAL_EXAM_SOLVE=1` が無い限りロック（解答非表示）。

### 4-C. 資料解説（/v1/explain-sessions、撮影なし）
```
POST /v1/explain-sessions {document_id}              → session_id (status=ready)
TP-単击(tap 23)                       → GET .../explain（概要）
TP-快速左/右滑(fast_swipe, UP 19 / DOWN 20) → POST .../next-page / prev-page
TP-長按(long_press 170)               → GET .../explain?stage=detail→evidence
TP-左/右滑(swipe 21/22)               → GET .../explain?view_page=N±1（テレプロンプター）
```

### 4-D. 文書ページ移動型 exam（撮影レス・主経路 / 筆記・リスニング両対応）
全ページを撮影レスで登録・finalize（＝全ページ読込完了）してから、ページ移動で解く。
**操作はグラス単独で完結**（スマホは中継のみ・画面不要）。
```
# 準備（撮影レス）：/pages (ocr_text) ×全ページ → /finalize
POST /v1/exam-sessions {mode:"study", document_id, exam_type:"written", answer_format:"mark"} → session_id
TP-快速左/右滑(fast_swipe, UP 19 / DOWN 20) → POST .../next-page / prev-page   ← 現在ページ移動
（確認）                                      GET  .../current                 ← 現在ページ把握
TP-単击(tap 23)                              → POST .../solve-current          ← 現在ページを解く
TP-長按(long_press 170)                      → GET  .../questions/{qid}/view?stage=solution→rationale→caution
Back-長按(back_long_press)                   → POST .../mode {exam_type}       ← 筆記 ⇄ リスニング 切替
# リスニング（音声はその場で録音、設問は目の前の資料から読取）
TP-双指長按(two_finger_long_press)           → 録音 → POST .../audio (audio,[transcript])
TP-単击(tap 23)                              → POST .../solve-current          ← 書き起こし＋資料で解答
```
- `exam_type`＝`written`(筆記) / `listening`(英語リスニング)、`answer_format`＝`mark`(マーク) / `written`(記述)。
- **リスニング書き起こし**：`ROKID_TRANSCRIBER=openai|gemini`＋各社鍵で実書き起こし。未設定/失敗/オフラインは
  アップロード時の `transcript` をそのまま使用（クレデンシャル不要で成立、下記 §2-3）。
- `mode:"real"` は `ROKID_ALLOW_REAL_EXAM_SOLVE=1` が無い限りロック（解答非表示）。撮影は一切発生しません。

### 実行フロー（データの流れ）
```
[Glasses: カメラ / 本体AI-OCR] ──画像 + ocr_text──▶ [本サーバ]
   照合(pHash) / 解答 / 解説 / 抽出（local 既定、claude|openai|gemini で実AI）
[本サーバ] ──HUD 3行(JSON)──▶ [Glasses: 両眼ディスプレイに描画]
   ※実AIが未設定/失敗ならローカルへ自動フォールバック（常に応答）
```

---

## 5. 実機での入力（KeyCode）調整

`GET /v1/settings.input` の既定は現行マッピング。機種/ファーム差で異なる場合は、
サーバ側で **`ROKID_KEYMAP`（JSON）** を設定して上書きすれば、クライアント改修なしで反映されます。

```bash
# 例: tap と long_press の KeyCode を実機値に合わせる
export ROKID_KEYMAP='{"tap": 23, "long_press": 170}'
```

実機での確認は `adb shell getevent -l`（または Android の `KeyEvent` ログ）で
タッチパッド操作時のキーコードを観測し、差があれば上記で調整します。

---

## 6. このリポジトリで「実物」なのはどこか

| 要素 | 状態 |
|------|------|
| サーバ（本リポジトリ） | そのまま実行可能・実 AI（claude/openai/gemini）接続可・テスト緑 |
| グラス本体アプリ（CXR-L, Kotlin/APK） | 各自でビルド。[cxr-l-integration.md](cxr-l-integration.md) の参照スニペットが出発点（Python リポジトリ内で APK はビルド不可） |
| 本体 AI（`com.rokid.sprite.aiapp`） | AI Interaction 経由で CXR-L/CXR-M から利用。結果を `ocr_text` として本サーバへ渡せる（経路B） |

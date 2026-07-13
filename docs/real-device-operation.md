# 実機運用ガイド（Rokid Glasses で使う）

本ドキュメントは、このリポジトリのサーバを **実機の Rokid Glasses と組み合わせて運用**する
ための、準備から実行までの一連を示します。サーバは既定でオフライン動作し、実 AI・認証は
環境変数で有効化します。グラス本体アプリ（CXR-L）と本体 AI の接続は
[cxr-l-integration.md](cxr-l-integration.md) を参照してください。

---

## 0. 構成（2経路。サーバから見れば同じ HTTP 契約）

```
[A] Glasses ─BT(CXR-L wire/Caps)─ [スマホ: Hi Rokid + CXR-L ﾌﾟﾗｸﾞｲﾝ] ─HTTPS─▶ [本サーバ]
[B] Glasses ─BLE/Wi-Fi─ [スマホ CXR-M コンパニオン] ─HTTPS─▶ [本サーバ]
```

> 実機動作実績のある CXR-L 構成は**スマホ側プラグイン**（Hi Rokid 経由）。どちらの経路でも
> スマホは HTTP 中継のみ（画面不要）で、ユーザーが見る・操作するのはグラスだけ。

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
- `GET /health` が `{"status":"ok", "versions":{…}}` を返せば稼働中。全環境変数は
  [user-operation-guide.md](user-operation-guide.md) §「環境変数一覧」を参照。

### 2-1. サーバ側の実 AI を有効化（任意 — 主経路は搭載 GPT で鍵不要）

**主経路はグラス搭載 AI（GPT / Gemini）**が解いて `POST /solutions` で取り込む形で、サーバ鍵は
不要です。より高性能なモデルが必要な場合のみ有効化します：

```bash
pip install openai             # または google-genai / anthropic
export OPENAI_API_KEY=sk-...                  # Gemini/Anthropic なら GOOGLE_API_KEY / ANTHROPIC_API_KEY
export ROKID_SOLVER=openai ROKID_EXPLAINER=openai \
       ROKID_ANALYZER=openai ROKID_EXTRACTOR=openai   # または gemini / claude
# export ROKID_LLM_MODEL=gpt-4o               # 任意上書き（各プロバイダに既定あり）
```

- 鍵未設定/失敗時は**自動でローカル実装にフォールバック**（サーバは常に応答）。
- **`ROKID_SOLVER` を non-local にすると `finalize-reading` がサーバ側で全問一括解答**します。

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
   - `capture`（無音シャッター・プライバシー LED 不可侵：`on_while_camera_active`＝読取中のみ点灯、
     `led_off_during_review:true`＝解答/閲覧フェーズは消灯）
   - `operations`（3 フェーズの操作↔ジェスチャ対応）
   - `input`（gesture→KeyCode。**`keycodes_verified:false`＝旧機由来・要実測**。
     `ROKID_KEYMAP` で実機差を吸収可）
2. スマホ側の CXR-L プラグイン（`CXRLink`）が Hi Rokid（global 版
   `com.rokid.sprite.global.aiapp`）の `IMediaStreamService` に AIDL バインドし、
   CUSTOMVIEW で HUD 表示・`startAudioStream` でマイク音声・AI キーイベントを扱う
   （詳細・Kotlin 例は [cxr-l-integration.md](cxr-l-integration.md) §2/§8）。

---

## 4. モード別の操作と実行フロー

> KeyCode は `GET /v1/settings.input.gestures` の値に従う（下記は既定値）。

### 4-A. 資料照合（/v1/match）
事前登録 → 現場で照合：
```
# 登録（ページ画像が主入力。OCR/図認識は補助）
POST /v1/documents            → document_id
POST /v1/documents/{id}/pages (page_index, image, [ocr_text], [vision_text]) ×全ページ
GET /v1/documents/{id}/scan-status?expected_total_pages=N ← 欠番・画像なし・認識なしを確認
POST /v1/documents/{id}/finalize   ← 完了宣言（要約生成・status=ready）
# 現場（登録画像の pHash と現在の画像で照合）
カメラ1フレーム取得 → 端末OCR →
POST /v1/match (document_id, image, fast_ocr_text) → HUD: PAGE n/N / LOW_CONF / NO_PAGE
```
- **テキスト-only互換入力**：`/pages` は既存クライアント向けに `image` 省略も受理しますが、
  `image_path=null`・`phash=""` となり `/match` の対象にはできません。通常運用ではページ画像を登録し、
  scan-status の `missing_image_page_indexes` に残ったページだけ再撮影します。

### 4-B. 解答（/v1/exam-sessions・設問1枚アップロード型＝互換）
```
POST /v1/exam-sessions {mode:"study"}                → session_id
問題画像を送信 → POST .../questions (image,[ocr_text])  ← 用紙画像を保存＋科目自動判定
1本指タップ(single_tap)              → POST .../{qid}/solve → 「答え: X ★★★」
1本指タップ（解答表示中）             → GET .../view?stage=solution→rationale→caution
2本指スワイプ下/上                   → テキストページ送り（view?page=N±1）
```
- **用紙画像で解く（vision）**：実アダプタ（`openai`/`gemini`/`claude`）を有効化すると、
  `solve` は保存済みの**ページ画像をモデルへ添付**し、図/数式/表/選択肢を直接読んで解答します
  （OCR テキストは補助、教科別プロンプト）。**画像はクラウドへ送信**されるため、実 AI・鍵設定時
  のみ作動（未設定/失敗はローカルへフォールバック）。
- 科目は読取時に自動判定（共通テスト準拠フル16教科）。`mode:"real"` は
  `ROKID_ALLOW_REAL_EXAM_SOLVE=1` が無い限りロック（解答非表示）。

### 4-C. 資料解説（/v1/explain-sessions、登録後の新規撮影なし）
```
POST /v1/explain-sessions {document_id}     → session_id (status=ready)
1本指タップ(single_tap)                     → GET .../explain（概要）
2本指スワイプ左/右(two_finger_swipe_l/r)     → POST .../next-page / prev-page
1本指タップ（表示中）                        → GET .../explain?stage=detail→evidence
2本指スワイプ下/上(two_finger_swipe_d/u)     → GET .../explain?view_page=N±1（テレプロンプター）
```

### 4-D. 3 フェーズ実践フロー（主経路 / 筆記・リスニング両対応）
**ページ画像の撮影・認識 → 不足ページだけ再撮影 → 一括解答 → 登録済み内容の閲覧**。
撮影は文書スキャンの中核です。撮影音・フラッシュ・プライバシー LED の実挙動は端末管理であり、
サーバは保証しません。**操作はグラス単独で完結**
（スマホは中継のみ・画面不要。文書作成・finalize・セッション作成のようにジェスチャ未割当の
HTTP は、読取開始/読取完了宣言に連動して**中継アプリが自動発行**する——
[cxr-l-integration.md](cxr-l-integration.md) §5）。

```
# フェーズ1 画像読取
POST /v1/documents {title: ...}（初回2本指タップで中継が自動作成。title 必須。
  同じ操作で得た画像＋認識は page_index=0 として続けて POST /pages——1ページ目を落とさない）
2本指タップ(two_finger_tap=AI起動・撮影) ×全ページ
  → POST .../pages (image[, ocr_text, vision_text])（scan_ack で進捗表示）
ダブルタップ(double_tap=読取完了宣言) → 中継が自動確認:
  GET /v1/documents/{document_id}/scan-status?expected_total_pages=N
  → missing_page_indexes / missing_image_page_indexes / missing_recognition_page_indexes だけ再取得
  → recommended_action=="finalize" を確認して POST /v1/documents/{document_id}/finalize
  → POST /v1/exam-sessions {mode:"study", document_id, ...}（session_id を取得）
  → POST /v1/exam-sessions/{session_id}/finalize-reading
  → 問題分割・デッキ作成。以降は登録済みデータを使い、新規撮影を要求しない

# フェーズ2 解答（登録済みデータ）
主経路: 搭載 GPT が全問を解く → POST .../solutions（問題別解答の配列を ingest）
任意:   ROKID_SOLVER=openai|gemini|claude ならフェーズ1の finalize-reading が一括解答済み
長押し(long_press=公式の録画⇄録音トグル)      → POST .../mode {exam_type}   ← 筆記 ⇄ リスニング
長押し（listening 中）                        → 録音 → POST .../audio (audio,[transcript])

# フェーズ3 閲覧（登録済みデータ。新規撮影不要）
GET .../solutions                            ← デッキ一覧（問1..問N・解答済み・確信度）
GET .../review?index=k&view_page=n           ← 1問題＝解答+解法+根拠+注意を一括表示
2本指スワイプ左/右 → index±1（前後の問題） / 2本指スワイプ下/上 → view_page±1（送り読み）
ダブルタップ → 閲覧終了
```
- **図・画像も読む**：図がないと解けない問題は、本体 AI の図の読み取りを `vision_text` として送れば本文と併せて解答材料になる。
- `exam_type`＝`written`(筆記) / `listening`(英語リスニング)、`answer_format`＝`mark`(マーク) / `written`(記述)。
- **リスニング書き起こし**：`ROKID_TRANSCRIBER=openai|gemini`＋各社鍵で実書き起こし。未設定/失敗/オフラインは
  アップロード時の `transcript` をそのまま使用（クレデンシャル不要で成立、上記 §2-3）。全問の解答文脈に統合される。
- **端末状態**：`GET /v1/settings.capture` の `privacy_led` は端末管理、`led_off_during_review:true` は
  解答・閲覧で新規撮影を要求しないことを表す。LED・撮影音・フラッシュは実機で別途確認する。
- `mode:"real"` は `ROKID_ALLOW_REAL_EXAM_SOLVE=1` が無い限りロック（ingest・デッキ・閲覧もロック）。

### 4-E. 文書ページ移動型 exam（二次経路・互換）
登録済みページを移動して現在ページを解く従来経路。移動・解答呼び出し自体は新しい画像を要求しない。
```
2本指スワイプ左/右 → POST .../next-page / prev-page   ← 現在ページ移動
（確認）             GET  .../current                  ← 現在ページ把握
1本指タップ         → POST .../solve-current           ← 現在ページを全ページ文脈で解く
1本指タップ（表示中）→ GET  .../questions/{qid}/view?stage=solution→rationale→caution
```

### 実行フロー（データの流れ）
```
[Glasses: カメラ＋本体AI(GPT/Gemini)] ──ページ画像＋ocr_text/vision_text・問題別解答──▶ [本サーバ]
   画像保存・pHash / 分割(segment_problems) / 取り込み(ingest) / 照合 / 解説 / 抽出
   （サーバ solver は任意: openai|gemini|claude、local 既定）
[本サーバ] ──HUD 3行(JSON)──▶ [Glasses: 両眼ディスプレイに描画]
   ※実AIが未設定/失敗ならローカルへ自動フォールバック（常に応答）
```

---

## 5. 実機での入力（KeyCode）計測・調整 — **必須**

`GET /v1/settings.input` のジェスチャ名は現行公式ですが、**KeyCode 値は旧・単眼 Rokid Glass
由来のレガシー表で、現行機では未実測**です（API も `keycodes_verified:false`・`keycode_source`
で明示）。実機では**必ず計測**し、**`ROKID_KEYMAP`（JSON）** で上書きしてください
（クライアント改修なしで反映されます）。

```bash
# 例: single_tap と long_press の KeyCode を実機値に合わせる
export ROKID_KEYMAP='{"single_tap": 23, "long_press": 170}'
```

実機での確認は `adb shell getevent -l`（または Android の `KeyEvent` ログ）で
タッチパッド操作時のキーコードを観測し、差があれば上記で調整します。
`two_finger_tap`（AI 起動）はシステムジェスチャのため既定 `keycode:null`——ファームが
KeyEvent として配送する機種のみ `ROKID_KEYMAP` で割り当ててください。

KeyCode を含む**実機検証の全項目**（イベント経路の判定・LED 消灯の物理確認・読取品質・
閾値チューニング等）は [device-verification-checklist.md](device-verification-checklist.md)
に手順付きで集約しています。

---

## 6. このリポジトリで「実物」なのはどこか

| 要素 | 状態 |
|------|------|
| サーバ（本リポジトリ） | そのまま実行可能・実 AI（openai/gemini/claude）接続可・テスト緑 |
| グラス本体アプリ（CXR-L, Kotlin/APK） | 各自でビルド。[cxr-l-integration.md](cxr-l-integration.md) の参照スニペットが出発点（Python リポジトリ内で APK はビルド不可） |
| 本体 AI（`com.rokid.sprite.aiapp`＝GPT/Gemini ネイティブ） | AI Interaction 経由で CXR-L/CXR-M から利用。読取は `ocr_text`/`vision_text`、解答は `POST /solutions` として本サーバへ渡せる（経路B＝主経路） |

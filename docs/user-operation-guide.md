# ユーザー操作ガイド（実機運用）

このドキュメントは「**人間（あなた）が実機・現場で行うこと**」と
「**システム/実装側が自動でやること**」を明確に分け、さらに
「**操作後に必要になる設計判断**」を整理します。

- 本リポジトリ（サーバ実装）は **既に実装済み** で、ローカルで動きます。
- ここで「ユーザーが行う」と書いた項目は、**コードでは代行できない物理操作や
  アカウント取得・同意取得など** です。それ以外はシステムが自動化します。
- 現在のバージョン: **APP 0.9.0 / API 1.9.0**
- **解答の主経路はグラス搭載 AI（GPT / Gemini）**で、その問題別解答をサーバへ取り込みます
  （`POST /solutions`・サーバ鍵不要）。要約/解答/解説/メディア抽出のサーバ側は既定でローカル
  実装ですが、**実 AI アダプタ（`openai` / `gemini` / `claude`）を同梱**しており、より高性能な
  モデルが必要な場合に環境変数で切り替えられます（§6・§7）。

---

## 1. ユーザーが実機で行うこと（人間の操作）

| # | 操作 | 内容 | 完了の目安 |
|---|------|------|------------|
| U1 | 開発者アカウント / SDK アクセス取得 | Rokid AR Platform（`ar.rokid.com/sdk`）で開発者登録し、CXR-L SDK（Android/iOS）を入手 | SDK が DL でき、サンプルがビルドできる |
| U2 | デバッグ環境（ADB / ケーブル） | Android コンパニオン端末を USB デバッグ可能にし、`adb devices` で認識 | `adb devices` に端末が出る |
| U3 | グラスのペアリング | Rokid Glasses と端末を BLE/Wi-Fi でペアリング、ファーム/アプリ更新 | グラスにカメラ映像/HUD が出る |
| U4 | 資料の全ページ視認読取（読取フェーズ・**撮影しない**） | 2本指タップ（AI起動）で各ページを視認し、本体 AI の認識テキスト（`ocr_text`＋図の読み取り `vision_text`）を1ページずつ登録（写真は撮らない）。**全ページを見終えたらダブルタップ（読取完了宣言）**——これを受けた中継アプリが `/finalize` を自動発行する（人間が HTTP を直接呼ぶのはサーバ単体検証のときだけ） | 各ページのテキストが登録され、`status=ready` になる |
| U5 | 読取品質チェック | 認識テキストに本文・設問・図表の説明が過不足なく含まれるかを scan_ack と**中継アプリ手元の認識テキスト**（送信した `ocr_text`/`vision_text`）で確認（**ダブルタップ=読取完了宣言の前に**行う——宣言後のページ差し替えは新文書での再読取が必要。`/current` はセッション作成後＝宣言後にしか呼べないため事前チェックには使えない） | §「読取チェックリスト」を満たす |
| U6 | プライバシー同意 | 読取中のカメラ稼働（LED 点灯）・認識テキストの保存・（クラウド送信する場合）外部送信について利用者同意を取得 | 同意ログ/同意UIが用意されている |
| U7 | クラウド vs ローカルモデルの選択 | サーバ側 AI を使う場合のプロバイダ（openai / gemini / claude）かローカルかを決める（主経路の搭載 GPT はサーバ鍵不要） | §「操作後に必要な設計判断」D2 を決定 |
| U8 | 検証（バリデーション）実行 | 読取サンプルで精度を確認（照合の評価は画像を使う任意経路 `/match` 用） | `scripts/evaluate.py` の accuracy を確認 |

> U1〜U6 と U8 の一部は **物理操作・アカウント・同意** に関わるため、
> コードでは代行できません。U7 の「決定」も人間の判断です（実装の差し込み口は
> システム側が用意済み）。

### 読取チェックリスト（U5）

- 本文（設問文・選択肢）が認識テキスト `ocr_text` に含まれている。
- 図・グラフ・写真の内容が `vision_text`（本体 AI の図の読み取り）として言語化されている。
- ページ番号・問題番号（問N/大問N）が読み取れている（問題分割の境界になる）。
- scan_ack の進捗（N/Mページ完了）が実際のページ数と一致している。
- （画像を併用する任意の `/match` 経路のみ）反射・影がなく、ページごとに見た目が
  十分に異なる（pHash が分離できる）。

### 全ページ登録〜完了の手順（読取フェーズ・撮影しない）

文書を解答・解説・照合モードで使う前に、**全ページの登録→finalize** が必要です。

```
1. POST /v1/documents          → document_id を取得
2. POST /v1/documents/{id}/pages  (page_index=0, ocr_text[, vision_text])
3. POST /v1/documents/{id}/pages  (page_index=1, ocr_text[, vision_text])
   ...全ページ分繰り返す（image は /match 用の任意・後方互換項目）...
4. POST /v1/documents/{id}/finalize   ← ★「全ページ完了」の宣言
   → status が "open" から "ready" に変わる
   → 各ページの summary が生成される
```

`/finalize` を呼ばないと `status=open` のままで、解答（exam-sessions）・解説セッション
（explain-sessions）や照合（/v1/match）で使えません。**全ページを登録し終えたら必ず
`/finalize` を呼んでください。**

> **呼び出し主体**: 上記 1〜4 の HTTP はすべて**中継アプリ（CXR-L プラグイン）が発行**します
> （サーバ単体検証では curl 等で代行）。ユーザーの入力はグラスのジェスチャのみ——手順 1 は
> 読取開始（最初の 2本指タップ）で自動作成、手順 2〜3 は 2本指タップごと、手順 4 は
> ダブルタップ（読取完了宣言）に連動して呼ばれます
> （[cxr-l-integration.md](cxr-l-integration.md) §5）。この中継責務まで含めて
> 「操作はグラス単独で完結」が成立します。
>
> **チェーンの後段は解答モード限定**: ダブルタップの自動チェーンで `/finalize` の後に
> exam セッション作成 → `/finalize-reading` まで続けるのは**解答モード（§5-C）に入るときだけ**。
> 解説（explain-sessions）・照合（/v1/match）用の登録では **`/finalize` で止める**こと——
> 不要な exam セッションを作るうえ、non-local `ROKID_SOLVER` 設定時は `finalize-reading` が
> 全問題をサーバ解答し、非 exam 用途に想定外のモデル呼び出し・遅延・課金が発生します。

> **完了確認**: `/finalize` のレスポンスに `page_count` と各ページの `summaries` が返ります。
> 期待するページ数と一致していることを確認してから次のフェーズに進んでください。

---

## 2. システム/実装側が自動化すること（実装済み）

これらは **すべてサーバに実装済み** で、ユーザーは API を叩くだけです。

| # | 自動処理 | 実装箇所 |
|---|----------|----------|
| S1 | 文書作成 | `POST /v1/documents`（`app/main.py`） |
| S2 | ページ取り込み・画像保存 | `POST /v1/documents/{id}/pages` → `data/images/` |
| S3 | pHash 計算（64bit, DCT） | `app/matching.py: phash/phash_hex` |
| S4 | OCR-MD5（OCRなしは画像MD5で代替） | `app/matching.py: ocr_md5` + `add_page` |
| S5 | finalize（要約生成・ready 化） | `POST /v1/documents/{id}/finalize` |
| S6 | 要約（プロバイダ非依存） | `app/analyzers/`（local 既定 / `claude` 実アダプタ同梱） |
| S7 | ページ照合（ハミング+OCR類似度） | `app/matching.py: match`（graded OCR similarity対応） |
| S8 | HUD 応答（3行固定）| `app/hud.py: build_hud` |
| S9 | バージョン情報の付与 | `app/version.py` → 各レスポンス |
| S10 | しきい値チューニング用フック | `app/matching.py` 定数 + `scripts/evaluate.py` |
| S11 | ログ/診断（client_version / sdk_hint エコー） | `/v1/documents`・`/v1/match` レスポンス |
| S12 | 解答モード（exam-sessions） | `/v1/exam-sessions` 以下（API 1.3.0+） |
| S13 | 資料解説モード（explain-sessions）撮影なし | `/v1/explain-sessions` 以下 |
| S14 | 解答 HUD（段階×テレプロンプター） | `app/glasses_view.py: build_glasses_view` |
| S15 | 解説 HUD（overview/detail/evidence×テレプロンプター） | `app/glasses_view.py: build_explain_view` |
| S16 | 問題構造解析（設問番号/本文/選択肢/解答欄box） | `app/layout.py: parse_layout` |
| S17 | 科目自動推定（共通テスト準拠フル16教科） | `app/subjects.py: detect_subject` |
| S18 | メディア抽出（数式/図/グラフ/表） | `app/extractors/` |
| S19 | RAG による根拠ページ検索 | `app/retrieval.py: retrieve_context` |
| S20 | 文書ページ移動型 exam（二次経路・互換） | `/v1/exam-sessions`(document_id) の next/prev/current/solve-current |
| S21 | 図・画像の読み取り取り込み（本体 AI の認識をテキスト `vision_text` で受け、本文と併せて解答） | `POST /v1/documents/{id}/pages` の `vision_text`／`app/main.py: _page_material` |
| S22 | 英語リスニング録音（無音）＋書き起こし | `/v1/exam-sessions/{id}/audio`／`app/transcribe.py` |
| S23 | 撮影しない契約の公示（フラッシュ・シャッター・録音音なし・LED は読取中のみ点灯） | `GET /v1/settings.capture`（`flash:"off"`・`privacy_led`・`led_off_during_review`） |
| S24 | **読取完了→問題分割→デッキ作成（3フェーズ主経路）** | `POST /v1/exam-sessions/{id}/finalize-reading`／`app/layout.py: segment_problems` |
| S25 | **搭載 GPT の問題別解答の取り込み（ingest）** | `POST /v1/exam-sessions/{id}/solutions`（`served_by="onboard"`・latest wins） |
| S26 | **問題別レビューデッキ＋一括表示 HUD** | `GET …/solutions`・`GET …/review`／`app/glasses_view.py: build_review_view` |

### システムが返すバージョン情報（契約ネゴシエーション）

`GET /v1/version` または各レスポンスの `versions` で取得:

```json
{
  "app_version": "0.9.0",
  "api_version": "1.9.0",
  "matcher_version": "1.1.0",
  "hud_contract_version": "1.0.0",
  "analyzer_api_version": "1.0.0",
  "solver_api_version": "1.1.0",
  "extractor_api_version": "1.0.0",
  "explainer_api_version": "1.0.0",
  "glasses_view_contract_version": "1.4.0",
  "overlay_contract_version": "1.1.0"
}
```

クライアント（Android/iOS/Rokid/Android XR）は、`hud_contract_version` や
`api_version` の **メジャー変化** を検知したら「アプリ更新を促す」挙動にできます。

---

## 3. 操作後に必要な設計判断（人間が決める／実装は差し込み済み）

読取・検証が終わったら、運用に向けて以下を決めます。**決定ポイントごとに
システム側の差し込み口が既にある** ので、決めれば差し替えるだけです。

| # | 判断 | 選択肢 | システム側の受け口 |
|---|------|--------|---------------------|
| D1 | OCR をどこで動かすか | 端末側 / サーバ側 / プロバイダ | `ocr_text`・`fast_ocr_text`（端末）/ `app/analyzers`（サーバ） |
| D2 | モデルルーティング（解析/解答/解説/抽出） | 搭載 GPT（主経路・ingest）/ local（サーバ既定）/ **openai / gemini / claude（同梱）** | `ROKID_ANALYZER` / `ROKID_SOLVER` / `ROKID_EXPLAINER` / `ROKID_EXTRACTOR`＝`openai\|gemini\|claude`＋各社 API キー（§7） |
| D3 | ストレージ/プライバシー | ローカルのみ / クラウド / 暗号化 | `app/config.py`（保存先）/ 同意フラグ（要追加） |
| D4 | HUD 文言・言語 | 日本語/英語、短縮ルール | `app/hud.py`・`app/glasses_view.py`（テレプロンプター式でページ数制限なし） |
| D5 | 信頼度しきい値 | HIT/LOW/NO の境界 | `app/matching.py` 定数 + `scripts/evaluate.py` の提案値 |
| D6 | オフラインフォールバック | 圏外時の挙動 | analyzer/solver/explainer の `offline` フラグ + registry のフォールバック |
| D7 | ターゲット端末 | Android / iOS / Rokid / Android XR | デバイスバックエンドレジストリ（[future-proof-architecture.md](future-proof-architecture.md) §デバイス） |

詳細な将来設計（ポート&アダプタ、レジストリ、契約バージョン、移行戦略）は
[future-proof-architecture.md](future-proof-architecture.md) を参照。

---

## 4. グラス操作リファレンス（公式ジェスチャ / KeyCode マッピング）

> ジェスチャ名は**現行 Rokid Glasses の公式操作**です。サーバは `GET /v1/settings` の `input`
> ブロックとして gesture→KeyCode を機械可読に公示します（`app/glasses_view.py` の
> `build_input_contract()`）。
>
> ⚠️ **KeyCode 値は旧・単眼 Rokid Glass 由来のレガシー表で、現行機では未実測**
> （`keycodes_verified:false`）。実機で `adb shell getevent -l` により計測し、機種/ファーム差は
> サーバ側の環境変数 **`ROKID_KEYMAP`（JSON）** で上書きしてください（クライアント改修不要）。
> 計測・調整手順は [real-device-operation.md](real-device-operation.md) §5 を参照。

| ユーザー操作（公式） | gesture 名 | KeyCode（旧機由来・未検証） | 本サーバの用途 |
|---|---|---|---|
| **2本指タップ**（AI 起動） | `two_finger_tap` | なし（`keycode:null`） | 視認＝ページ読取（`POST /pages`） |
| **1本指タップ** | `single_tap` | `KEYCODE_DPAD_CENTER = 23` | 表示・確認・段階送り |
| **ダブルタップ** | `double_tap` | `KEYCODE_ENTER = 66` | 読取完了宣言（読取中）／閉じる（閲覧中） |
| **2本指スワイプ左/右** | `two_finger_swipe_left/right` | `KEYCODE_DPAD_LEFT/RIGHT = 21/22` | 前後の問題（閲覧）／前後ページ |
| **2本指スワイプ上/下** | `two_finger_swipe_up/down` | `KEYCODE_DPAD_UP/DOWN = 19/20` | テレプロンプター送り/戻し |
| **長押し**（録画⇄録音切替） | `long_press` | `KEYCODE_TV = 170` | 筆記⇄リスニング切替・録音開始/停止 |
| 戻る | `back` | `KEYCODE_BACK = 4` | 前の画面へ戻る |

---

## 5. モード別フロー

### 5-A. 資料照合モード（/v1/match）

```
1. POST /v1/documents + 全ページ POST /v1/documents/{id}/pages
2. POST /v1/documents/{id}/finalize  ← 完了宣言（忘れずに）
3. （任意・画像経路）カメラ1フレーム＋端末OCR → POST /v1/match → HUD に PAGE/LOW_CONF/NO_PAGE 表示
```

### 5-B. 資料解説モード（explain-sessions）

> **撮影なし・カメラ画像送信なし**。ページナビはジェスチャ操作のみ。

```
1. 資料の全ページ登録 + /finalize が完了していること（前提）
2. POST /v1/explain-sessions {"document_id": N}  → status=ready, page_index=0
3. タップ → GET /explain  → overview HUD 表示
4. 2本指スワイプ左 → POST /next-page → 次ページへ
5. 2本指スワイプ右 → POST /prev-page → 前ページへ
6. タップ → GET /explain?stage=detail  → 詳細
7. もう一度タップ → GET /explain?stage=evidence → 根拠ページ
8. タップ（3回目）→ GET /explain?stage=overview  → 概要へ戻る（ラップ）
9. ダブルタップ → HUD を閉じる
```

> **テレプロンプター**: 解説テキストが長い場合は自動的に複数スライスに分割されます。
> 2本指スワイプ上下でスライスを送り読みできます。**文字数・行数の上限はなく**、
> すべてのテキストが HUD に表示されます（3行×Nスライス）。

### 5-C. 解答モード（3 フェーズ実践フロー・主経路 / LED 点灯最小）

> カメラ（＝LED 点灯）は**手順 1〜3 の読取フェーズだけ**。手順 3 のダブルタップ以降は
> カメラ OFF（LED 消灯）で、用紙も視認も不要。

```
フェーズ1 読取（カメラON・LED点灯・最短化。HTTP は全て中継アプリが発行——人間はジェスチャのみ）
1. 読取開始（最初の2本指タップ）: 中継が POST /v1/documents を自動作成
2. 2本指タップ（AI起動=視認）×全ページ → POST /pages（scan_ack で進捗）
3. ダブルタップ（読取完了宣言）→ 即カメラを閉じる（LED消灯）→ 中継の自動チェーン:
   POST /v1/documents/{document_id}/finalize
   → POST /v1/exam-sessions {"mode":"study","document_id":N,...}（応答の session_id を取得）
   → POST /v1/exam-sessions/{session_id}/finalize-reading
   → 問題分割・デッキ作成・「読取完了 / N問を検出 / カメラOFF 解答へ」
   （チェーンはカメラOFF後に実行——non-local ROKID_SOLVER の一括解答中も LED は点かない）

フェーズ2 解答（カメラOFF・自動）
4. 主経路: 搭載 GPT が全問解答 → POST /solutions で取り込み（served_by="onboard"）
   任意:   ROKID_SOLVER=openai|gemini|claude なら手順3の finalize-reading が一括解答済み
   リスニング: 長押しで切替（POST /mode）→ 長押しで録音 → POST /audio（書き起こし統合）

フェーズ3 閲覧（カメラOFF・LED消灯）
5. GET /solutions → デッキ（問1..問N・解答済み・確信度）
6. GET /review?index=k → 1問題＝解答+解法+根拠+注意を一括表示
   2本指スワイプ左右=前後の問題 / 2本指スワイプ上下=送り読み / ダブルタップ=終了
```

> **real モード**: `ROKID_ALLOW_REAL_EXAM_SOLVE=1` が未設定の場合、解答は表示・保存されません
> （ingest・デッキ・閲覧もロック。不正利用防止）。

> **読取品質チェック（U5）は手順 3 のダブルタップ前に行うこと**。`finalize-reading` で
> セッションが reviewing になった後は、同一文書のページ差し替え（同一 `page_index` の再送）も
> 409 で拒否されます（デッキは旧テキストから分割済みのため）。ダブルタップ後に読取不良に
> 気づいた場合の是正は、**新しい文書を作って再読取**（`POST /v1/documents` からやり直し）です。
> 例外は 0 問分割のとき——セッションが読取フェーズへ自動差し戻しされ、同一文書のまま
> 再読取→再ダブルタップできます。

### 5-D. 解答モード（互換・二次経路）

```
# 文書ページ移動型: 2本指スワイプ左右でページ移動 → タップで現在ページを解く
POST /next-page / /prev-page → GET /current → POST /solve-current
# 設問1枚アップロード型: POST /questions → POST /solve →
タップ → GET /view?stage=solution|rationale|caution（段階送り）
2本指スワイプ上下 → テキストのページ送り（テレプロンプター、制限なし）
```

---

## 6. 推奨フロー（操作 → 検証 → 判断）

1. **U1〜U3**: SDK 取得・端末準備・ペアリング（人間）。
2. **U4〜U6**: サンプル文書を**全ページ**視認読取（撮影しない）し同意取得（人間）。
3. サーバを起動（システム）:
   `uvicorn app.main:app --port 8000`
4. 認識テキストを登録（システムが自動処理。実機では中継アプリがジェスチャに連動して発行）:
   `/v1/documents` → `/pages` ×全ページ数 → `/finalize`（**全ページ完了後に必須**）。
5. **U8 検証**（人間が実行 → システムが集計）:
   `ROKID_DATA_DIR=data python scripts/evaluate.py --db data/docscan.db --out report.json`
   → `self_match_accuracy` と `suggested_thresholds` を確認。
6. **D1〜D7 を決定**（人間）。`suggested_thresholds` を見て D5 を調整。
7. 決めた D2（モデル）に合わせて analyzer/solver/explainer を登録（実装差し替えのみ）。

> 既定の D2 は `local`（オフライン・クレデンシャル不要）で全機能が動きます。
> 実 AI への切り替えは §7 のとおり環境変数だけで完了します（実アダプタは同梱済み）。

---

## 7. 実 AI（openai / gemini / claude）の有効化 — 任意の高性能化経路

**主経路はグラス搭載 AI（GPT / Gemini）で、サーバ鍵は不要**です（解答は `POST /solutions` で
取り込み）。より高性能なモデルが必要な場合のみ、**同梱の実アダプタ（`openai` / `gemini` /
`claude`）を環境変数で有効化**します。キー未設定/失敗時は自動でローカルにフォールバックする
ため、切り替えでサーバが止まることはありません。`ROKID_SOLVER` を non-local にすると
`finalize-reading` がサーバ側で全問一括解答します。

> **範囲の注意（読取だけは高性能化できない）**: 「撮影しない」原則により画像はサーバに
> 届かないため、サーバ側アダプタで肩代わりできるのは**解答・解説・要約・書き起こし**です。
> 読取（`ocr_text`/`vision_text` の認識品質）は本体 AI に固定され、読取不良の救済は
> 同一 `page_index` の再視認（置換・`replaced:true`。`finalize-reading` 後は新文書で再読取）
> のみです。解答は `POST /solutions` の再 ingest（latest wins）で、より高性能なモデルの結果に
> 後から上書きできます。なお **`ROKID_EXTRACTOR`（メディア抽出）が使われるのは設問画像
> アップロード互換経路（`POST /questions`）だけ**で、撮影しない主経路では呼ばれません。

```bash
pip install openai                          # または google-genai / anthropic
export OPENAI_API_KEY=sk-...                # Gemini: GOOGLE_API_KEY / Anthropic: ANTHROPIC_API_KEY
export ROKID_SOLVER=openai ROKID_EXPLAINER=openai \
       ROKID_ANALYZER=openai ROKID_EXTRACTOR=openai   # または gemini / claude
# export ROKID_LLM_MODEL=gpt-4o            # 任意上書き（各プロバイダに既定あり）
                                            # （anthropic のみ claude-opus-4-8 が既定）
uvicorn app.main:app --port 8000
```

- `GET /v1/version` の `solvers`/`analyzers`/`explainers`/`extractors` に
  `local`/`openai`/`gemini`/`claude` が並びます（既定ルーティングは `local`）。
- 本番試験ロック（`mode=real` / `ROKID_ALLOW_REAL_EXAM_SOLVE`）は実モデルでも有効。
- 公開/実機運用では `ROKID_API_KEY` で Bearer 認証を有効化可能（発見系エンドポイントは開放）。
- 一連の実機手順は [real-device-operation.md](real-device-operation.md)、本体 AI との接続は
  [cxr-l-integration.md](cxr-l-integration.md)。

### 環境変数一覧

| 変数 | 既定 | 役割 |
|------|------|------|
| `ROKID_DATA_DIR` | `data` | SQLite/画像の保存先 |
| `ROKID_ANALYZER`/`ROKID_SOLVER`/`ROKID_EXPLAINER`/`ROKID_EXTRACTOR` | `local` | 各ポートのルーティング（`local\|openai\|gemini\|claude`。solver は non-local で finalize-reading の一括解答も有効化） |
| `ROKID_SOLVER_TIERS` | （単一） | 解答の二段フォールバック順（csv、末尾に local 自動付与） |
| `OPENAI_API_KEY`/`GOOGLE_API_KEY`/`ANTHROPIC_API_KEY` | （なし） | 実アダプタの API キー（未設定→local） |
| `ROKID_LLM_MODEL` | openai `gpt-4o` / gemini `gemini-2.5-flash` / anthropic `claude-opus-4-8` | 使用モデル id（任意上書き） |
| `ROKID_LLM_MAX_TOKENS` | `1024` | 応答トークン上限 |
| `ROKID_TRANSCRIBER` | （なし） | 英語リスニング録音の書き起こし（`openai\|gemini`、未設定=与えた transcript を使用） |
| `ROKID_TRANSCRIBE_MODEL` | `gpt-4o-transcribe` | openai の書き起こしモデル（gemini は `ROKID_LLM_MODEL` を使用） |
| `ROKID_ALLOW_REAL_EXAM_SOLVE` | `0` | 本番試験モードの解答ロック解除 |
| `ROKID_ENABLE_EMBEDDING` | `0` | RAG の意味検索（未接続時は lexical） |
| `ROKID_KEYMAP` | （なし） | gesture→KeyCode の上書き（JSON、`/v1/settings.input`。既定 KeyCode は旧機由来・未実測） |
| `ROKID_API_KEY` | （なし） | 設定時に Bearer 認証を要求（発見系は開放） |

雛形は同梱の [`.env.example`](../.env.example) を参照。

---

## 付録: 廃止されたエンドポイント（v1.6 → v1.7）

| 旧操作 | 旧エンドポイント | 廃止理由 |
|--------|----------------|----------|
| ページ撮影スキャン（解説モード） | `POST /scan`（画像アップロード） | 解説モードは撮影なし設計へ移行 |
| 全ページ読取完了宣言（解説モード） | `POST /commit` | scanning フェーズ廃止（explain-sessions は /finalize 済みの文書を使用）。exam の読取完了宣言は `POST /finalize-reading`（ダブルタップ）が担う |

> 注意: **文書登録フェーズの `/finalize`** は廃止されていません。これは引き続き必須です。
> 廃止されたのは explain-sessions 内の旧 `/scan` と `/commit` エンドポイントです。

# 入試問題ソルバー アーキテクチャ（解答モード）

Status: Current architecture of the answer mode. Updated 2026-09-14.
実装が正で、この文書はその地図です。食い違いを見つけたらコードを信じ、ここを直して
ください。

既存の「ページ照合（資料化）」モードに、**未登録の入試問題を読み取って解答・根拠を返す**
解答モードを追加した。設計は既存と同じ **ポート＆アダプタ＋レジストリ＋契約バージョニング**。

```
撮影画像/OCR ─▶ layout(構造化＋解答欄box) ─▶ subjects(科目推定)
        │                                          │
        └▶ extractors(図/表/グラフ/数式=media) ─────┤
                                                    ▼
   retrieval(RAG: documents/pages → context/evidence) ─▶ solver(registry, 二段フォールバック)
                                                    │
   分離信頼度(読取/解答/根拠) ─▶ glasses_view(3行・段階・ページ送り) ＋ overlay(解答欄box, 2D追従)
                                                    └▶ reasoning(フルログ=サーバ保存・HUD非表示)
```

## データフロー（Phase 2/3/4）

- **add_question**: layout 解析後、図/表/グラフ/数式の手掛かりがあれば `extractors`（`get_extractor`）で `media` を生成し `questions.media_json` に保存・応答に同梱。
- **solve**: `retrieval.retrieve_context(documents/pages)` で根拠 `context`/`evidence_pages`/`evidence_refs` を取得→`Question(context=..., image_path=...)` に注入→`solve_with_fallback`（tier 順に試行し offline local へフォールバック、採用 tier=`served_by`）→`solutions` に根拠と `served_by` を保存。`evidence_refs` は文書ID付き・1始まりの正規形式で、旧 `evidence_pages` は API v1 の従来の意味を保持。応答に `served_by`・`evidence` を追加。
  - **vision（用紙画像で解く）**: 実アダプタ（`openai`/`gemini`/`claude`）は `questions.image_path` の**ページ画像をモデルへ添付**し、図/数式/表/選択肢を直接読んで解答（OCR テキストは補助）。プロンプトは**教科別ガイダンス**付き（`app/solvers/llm_adapter.py` の `_SYSTEM` / `_subject_guidance`）。画像はクラウドへ送信されるため実 AI・鍵設定時のみ作動、未設定/失敗は local へフォールバック。`mode=real` ロックは不変。
- **overlay**: `tracking:"2d_image_anchor"`・`fixed_ar:false`・`anchor_hint{page_number,box}` を機械可読化（6DoF 固定 AR は未対応＝ハード待ち）。
- **reasoning**: `GET …/questions/{qid}/reasoning` で `raw_reasoning`＋`evidence`＋`served_by` を返す（HUD は短縮版のまま、`real` ロック準拠）。

## 3 フェーズフロー（読取→一括解答→閲覧・主経路）

**主経路**。カメラ（＝プライバシー LED 点灯）は読取フェーズのみで、`finalize-reading` 以降は
カメラを閉じる（LED 消灯）。解答の主体は**グラス搭載 AI（GPT）**で、サーバは分割・取り込み・
整形・状態管理を担う。

```
フェーズ1 読取（カメラON・LED点灯・最短化）
  本体AIの視認テキスト ─▶ POST /pages(ocr_text, vision_text) ×N ─▶ finalize
  ダブルタップ ─▶ POST /finalize-reading ─▶ segment_problems(全ページ) ─▶ questions 行 ×問題数
                                            status: open/reading → reviewing（以降カメラOFF）
フェーズ2 解答（カメラOFF・一括）
  主経路: 搭載 GPT が全問解答 ─▶ POST /solutions（ingest, served_by="onboard"）
  任意:   ROKID_SOLVER=openai|gemini|claude ─▶ finalize-reading 内で全問を solve_with_fallback
          （各問とも context=_exam_prompt_context: 全ページ＋RAG＋(listening時)書き起こし＋書式指示）
          solution_claims を provider 呼出前に取得し、同時 finalize の二重課金を防止
フェーズ3 閲覧（カメラOFF・LED消灯）
  GET /solutions（デッキ一覧） ─▶ GET /review?index=k&view_page=n
  build_review_view: 解答+解法+根拠+注意を一括1ストリーム（3行×テレプロンプター送り）
リスニング: /audio(録音+任意transcript) ─▶ transcribe(openai/gemini or 与値) ─▶ transcript
  /mode で 筆記(written) ⇄ リスニング(listening) 切替（グラス=長押し / スマホ）
```

- **問題分割 `segment_problems`**（`app/layout.py`）：全ページの材料（`_page_material` ＝本文＋図の
  読み取り）をページごとに `parse_layout`（行単位スキャナ）へかけ、**問N/大問N/第N問/(n)** 境界で
  分割・ページ跨ぎの継続をマージする（前文は第1問に前置）。境界が 1 つも無ければ**文書全体を
  1 問題**にフォールバック。同一番号の重複（大問跨ぎの問1等）は `問1(2)` サフィックスで一意化——
  **デッキ（`GET /solutions`）の問題番号が ingest の正**。決定的・オフライン。
- **status ライフサイクル**：`open`（既定・読取フェーズの別名）→ `reviewing`（`finalize-reading` で
  遷移）。`finalize-reading` は**冪等**（ジェスチャ二度撃ちで再分割しない）。応答の `camera` は
  `{expected_state:"off", privacy_led:"off"}`。
- **onboard ingest（主経路）**：`POST /solutions` は問題別解答の配列
  `[{problem_no, problem_index?, answer, subject?, solution_steps?, rationale?, cautions?, answer_confidence?, page_number?}]`
  を受け、`solver_name="onboard"`・`served_by`（既定 `"onboard"`）で `solutions` 行を追加。
  照合は **`problem_index`（デッキ index）優先**・なければ `problem_no` 完全一致——大問跨ぎで
  基底番号が重複する場合（サーバは `問1(2)` と一意化）は index 指定が正。**再 ingest は latest
  wins**（読取側は `ORDER BY id DESC LIMIT 1`）。未知の `problem_no` は**デッキに問題を追加**
  （ヒューリスティックの見逃しを本体 AI が補完。デッキ index は一度割り当てたら不変＝
  後から追加された問題は末尾に付く。index 照合の安定性を優先）。検証は全或無
  （空 answer・範囲外 index は 400）、`answer_confidence` は [0,1] にクランプ。
  `mode=real` は何も保存しない（locked 応答）。
- **サーバ一括解答（任意・再開可能）**：`ROKID_SOLVER` が non-local のときだけ `finalize-reading` が
  同期で**未解答の問題**を解く（呼ぶたびに残りを解く＝途中失敗はダブルタップ再実行で再開。
  1 問ごとに commit）。local/未設定、またはクラウド solver が local へフォールバックした結果は
  **保存しない**（プレースホルダのゴミ行で「解答済み」になり搭載 GPT ingest を隠すのを防ぐ）。
  読取完了宣言は guarded UPDATE で**競合安全**（二度撃ちでもデッキは 1 回だけ生成）。
  境界なし文書のフォールバック 1 問題には安定 id **「全体」** を合成（ingest から指名可能）。

## 撮影レス・文書ページ移動型 exam ＋ 英語リスニング（二次経路・互換）

ページ移動で**現在ページを解く**従来経路（挙動不変で維持）。読取と閲覧が分離されないため、
主経路よりカメラ稼働（LED 点灯）時間が長い。

```
exam-session(document_id, exam_type, answer_format)
  next-page/prev-page ─▶ current_page_index ─▶ solve-current ─▶ 現在ページ pages 行を解く
   （2本指スワイプ左右）    （現在ページ把握）     （タップ）        │ subject=detect_subject(そのページ)
                                                                   │ context=RAG＋(listening時)書き起こし
                                                                   ▼ solve_with_fallback → glasses_view(3行段階)
```

- **撮影しない取り込み**：`POST /v1/documents/{id}/pages` は本体 AI の認識結果を**テキスト**で受ける：
  `ocr_text`（本文）＋`vision_text`（**図・グラフ・写真・見た目の読み取り**）。画像は送らない（`image_path=NULL`・
  `phash=""`・`ocr_md5` はテキストから算出）。照合（`/v1/match`）も**テキスト照合が主**で、
  テキストのみページはテキスト類似度でスコアされる（`hamming` は null）。`image` は後方互換の
  任意項目で、添付時のみ pHash も算出し画像同士の照合に使える（非推奨）。
  `ocr_text`／`vision_text`／画像のいずれも無ければ 400。
- **solve-current（全ページ記憶で解く・ページ跨ぎ対応）**：現在ページ（`current_page_index`）を**設問**、
  **文書の全ページ**を**文脈**にして解く。`Question.body_text` ＝ 現在ページの材料
  `_page_material(ocr_text, vision_text)`（本文＋「【図・画像の読み取り】…」）、`Question.context` ＝
  `_document_material()`（全ページを `【P01】…【Pnn◀現在ページ】…` で連結）＋横断 RAG＋（リスニング時）
  `session.transcript`＋`answer_format`（マーク/記述）指示を `_exam_prompt_context` で統合。`subject`＝現在ページ材料の
  `detect_subject`。問題が前後ページに跨っても全ページから読み取れる。解答は `questions`＋`solutions` に保存し
  既存の `/view`（段階×ページ送り）・`/reasoning` がそのまま使える。`mode=real` ロック不変。**画像は送らない**。
- **リスニング録音**：`POST …/{id}/audio`（`audio` ファイル＋任意 `transcript`）を `data/audio/` に保存。
  `app/transcribe.py` が `ROKID_TRANSCRIBER`（openai=`audio.transcriptions.create`、gemini=inline audio）で
  書き起こし。未設定/失敗/オフラインは**与えた `transcript` をそのまま使用**（クレデンシャル不要で成立）。
  OpenAIには公式対応コンテナだけを送信し、raw ADTS/ADIF AACと識別不能データは
  与値へフォールバックする。先頭のID3v2タグは実コンテナ判定前に読み飛ばす。
  Anthropic は ASR 非対応。
- **グラス単独操作**：`OPERATION_CONTRACT`（`GET /v1/settings.operations`）が 3 フェーズの全操作
  （`capture_read`/`finish_reading`/`mode_toggle`/`record_toggle`/`review_next_problem`/
  `review_prev_problem`/`scroll_next`/`scroll_prev`/`close`）と二次経路（`exam_next_page`/
  `exam_prev_page`/`exam_solve_current`/`exam_next_stage`）を現行公式ジェスチャで公示。全操作が
  グラスのジェスチャに割当済みで、スマホは HTTP 中継のみ（画面不要）。

## モジュール（このリポジトリで実装済み）

| モジュール | 役割 | 差込口 |
|------------|------|--------|
| `app/solvers/`（base/registry/local_placeholder/llm_adapter/claude/**chatgpt_web**） | 問題解答ポート。既定はオフライン**プレースホルダ**（実際には解かない＝不正利用ガード）。`solve_with_fallback` で**二段フォールバック**。**実アダプタ openai/gemini/claude 同梱**（**vision：用紙画像を添付**＋教科別プロンプト） | `ROKID_SOLVER=openai\|gemini\|claude`＋各社 API キーで実解答。`ROKID_SOLVER_TIERS` で tier 指定 |
| `app/extractors/`（base/registry/local_placeholder/**claude=LLMExtractor**） | メディア抽出ポート（数式/図/グラフ/表）。既定はオフライン placeholder。**実アダプタ openai/gemini/claude 同梱**（数式→LaTeX 等） | `ROKID_EXTRACTOR=openai\|gemini\|claude` で実抽出 |
| `app/retrieval.py` | 既存 `documents/pages` を横断検索し根拠 `context`/`evidence` を供給（依存なしの lexical scorer） | `ROKID_ENABLE_EMBEDDING` で実 embedding 検索に差替（未接続時は lexical へフォールバック） |
| `app/layout.py` | OCRテキスト→設問番号/本文/選択肢/図表/**解答欄box**（正規化座標） | 実レイアウト/ビジョンモデルが同構造を埋める |
| `app/subjects.py` | 科目推定（**共通テスト準拠フル**：現代文/古文/漢文/数学/英語/物理/化学/生物/地学/世界史/日本史/地理/倫理/政治経済/現代社会/情報） | 実分類器/VLM に差替 |
| `app/glasses_view.py` | **無音・3行・段階×ページ送り**の HUD ペイロード（音/アニメ指示なし） | — |
| `app/overlay.py` | 解答欄box＋短答/番号（2D画像アンカー、`tracking/fixed_ar/anchor_hint`） | 6DoF が整えば紙固定ARへ |

## 既存資産の再利用

- **ページ/設問認識**は既存 `app/matching.py`（pHash＋OCR-MD5 2層）を再利用（資料化モード `/v1/match`）。
- ソルバー registry は `app/analyzers/registry.py` と同じ流儀。**従量課金(クラウド) vs ローカル**を環境変数で切替、欠落時はオフラインへフォールバック。

## データモデル（`app/db.py`）

- `exam_sessions`(mode, voice_enabled, subject_hint, status, **document_id**, **exam_type**（written|listening）, **answer_format**（mark|written）, **current_page_index**, **audio_path**, **transcript**)
  - 追加列は既存 DB 向けに `init_db` の `_migrate()`（`ALTER TABLE ADD COLUMN`）で移行。
- `questions`(question_no, body_text, choices_json, figure_refs, answer_box_json, structure_json, subject, read_conf, page_number, image_path, **media_json**)
- `solutions`(answer, solution_steps_json, rationale, cautions, answer_conf, rationale_conf, evidence_pages_json, **evidence_refs_json**, raw_reasoning, **served_by**, user_confirmed)
- `solution_claims`(question_id, claimed_at)：任意の有料 solver 呼び出し前に取得する短期 claim。
- `pages`：`image_path` は **nullable**・`phash` 既定 `""`（撮影しないテキストページ用）。**`vision_text`**（新規）＝
  本体 AI の図・画像の読み取り（テキスト）。既存 DB 向けに `_migrate()` が `pages` にも `ALTER TABLE ADD COLUMN` で移行。
- `questions`(..., **body_text**＝現在ページ材料＝OCR＋図の読み取り)。

既存 `documents`/`pages` はページ照合モード用にそのまま維持。

## エンドポイント

| メソッド | パス | 用途 |
|----------|------|------|
| POST | `/v1/exam-sessions` | 一時セッション作成（mode, voice_enabled, **document_id, exam_type, answer_format**） |
| POST | `/v1/exam-sessions/{id}/finalize-reading` | **読取完了宣言（3フェーズ主経路）**：問題分割→デッキ作成→`reviewing` 遷移→（solver 設定時）一括解答。冪等 |
| POST | `/v1/exam-sessions/{id}/solutions` | **搭載 GPT の問題別解答を ingest**（`served_by="onboard"`・latest wins・real ロック） |
| GET | `/v1/exam-sessions/{id}/solutions` | **レビューデッキ一覧**（問題番号・教科・解答済み・確信度。読取中は空デッキ） |
| GET | `/v1/exam-sessions/{id}/review?index=&view_page=` | **問題別閲覧 HUD**（解答+解法+根拠+注意を一括1ストリーム・クランプ・未解答プレースホルダ） |
| GET | `/v1/exam-sessions/{id}/answer-bundle` | **グラスのオフライン一括答案**（`schema_version`/`session_id`/`input_digest`/`revision`+`items[]`。deckの`question_no`から大問/小問を復元・グループに小問が無ければ`全問`1件を維持。読取中・realロック中は409。実機未検証。解答は表示可能なテキストへ変換して返し（LaTeXの分数・指数・添字・根号・ギリシャ文字・場合分け）、表・図・未対応記法が残る項目は`ready`にせず`needs_review`＋`issue`で返す。テキストは捨てない） |
| POST | `/v1/exam-sessions/{id}/mode` | **筆記 ⇄ リスニング** 切替（`{"exam_type":...}`） |
| POST | `/v1/exam-sessions/{id}/audio` | **リスニング録音**アップロード（`audio`＋任意`transcript`）→ 書き起こし保存 |
| POST | `/v1/exam-sessions/{id}/next-page` / `prev-page` | 文書ページ移動（二次経路。現在ページ ±1・クランプ・撮影なし） |
| GET | `/v1/exam-sessions/{id}/current` | 現在ページ把握（二次経路。科目・プレビュー・画像有無） |
| POST | `/v1/exam-sessions/{id}/solve-current` | 現在ページを解く（二次経路。listening 時は書き起こしを統合）→ `glasses_view` |
| POST | `/v1/exam-sessions/{id}/questions` | 認識テキスト（`ocr_text`＋図の読み取り `vision_text`）＋任意bbox → 構造化・科目推定・`media`抽出（互換。画像は互換の任意入力・非推奨） |
| POST | `/v1/exam-sessions/{id}/questions/{qid}/solve` | 解答（real は既定ロック）→ `glasses_view`＋`overlay`＋`served_by`＋`evidence`（互換） |
| GET | `/v1/exam-sessions/{id}/questions/{qid}/view?stage=&page=` | 段階×ページ送り取得（互換） |
| GET | `/v1/exam-sessions/{id}/questions/{qid}/reasoning` | フル推論ログ（案9、HUD非表示・real ロック準拠） |
| GET | `/v1/exam-sessions/{id}` | セッション状態（`phase`/`document_id`/`exam_type`/`problem_count`/`solved_count`＋解答済み一覧） |
| GET | `/v1/settings` | 無音契約・操作/入力/キャプチャ契約・音声トグル・real ロックの公示 |
| GET | `/v1/version` | 契約バージョン＋ analyzers/solvers/extractors 一覧 |

## 解答プロバイダの選択（現行）

`app/provider_registry.py` が 4 ポート（analyzer / solver / extractor / explainer）
共通の登録・選択を持ち、solver だけ `app/solvers/registry.py` が多段
フォールバックを重ねます。

| 値 | 実装 | 中身 |
|---|---|---|
| `local` | `LocalPlaceholderSolver` | 既定。実際には解かない。不正利用ガードであり、`ROKID_REAL_MODE=1` は拒否します |
| `openai` / `gemini` / `claude` | `LLMSolver` / `ClaudeSolver` | API キー経路。用紙画像を添付し、教科別プロンプトを使います |
| `chatgpt-web` | `ChatGptWebSolver` | **現行の主経路。** 下記 |

`ROKID_SOLVER_TIERS` に csv で順序を書くと、その順に試して最後に `local` へ落ちます。
選択肢記号が設問に存在しない答えが返った場合は、1 回だけ問い直します。

### `chatgpt-web`（`app/solvers/chatgpt_web.py`）

利用者のログイン済み ChatGPT ウェブセッションを、起動済み Chrome の DevTools
プロトコル（`ROKID_CHATGPT_CDP`、既定 `http://127.0.0.1:9222`）経由で操作します。
Playwright は使いますが `playwright install` は不要です（実ブラウザに接続するため）。

- **チャットの粒度** — `ROKID_CHATGPT_CHAT_SCOPE`。既定 `question` は小問ごとに
  新しいチャットを開き、前の解答が文脈に混ざらないようにします。`subject` は
  科目ごとに 1 チャットを保ち、大問のページを 1 回添付すればその科目の間ずっと
  残るので、小問ごとに上げ直さずに済みます。
- **冊子の一括添付** — `app/page_pdf.py` の `images_to_pdf()` が撮影ページを 1 つの
  PDF に束ね、`GET /v1/exam-sessions/{id}/pages.pdf` が配信します。
  `Question.document_image_paths` があるとソルバーは PDF 経路を選びます
  （`ROKID_CHATGPT_BUNDLE_PDF` は手動の上書き）。
- **タブの再利用** — 質問ごとに `chatgpt.com` を読み込み直さず、1 枚のタブを使い回します。
- **使用制限への防御** — 制限はメッセージ本文で通知され例外になりません。
  `ROKID_CHATGPT_RATE_LIMIT_MARKERS` に当たった返答は即座に打ち切り、再試行しません。
  加えて、`ROKID_CHATGPT_SLOW_S` を超える生成が
  `ROKID_CHATGPT_SLOW_STREAK` 回続いたら次の送信を止めます。
- **未確定の答えを確定させない** — 生成中の表示（thinking プレースホルダ）を
  解答として確定しません。

**ChatGPT ウェブ UI の自動操作は OpenAI の利用規約に反します。** アカウントが制限
される risk があり、利用者の判断で選択した経路です。セレクタと待ち時間はすべて
環境変数で上書きできます（`.env.example` 参照）。ページ構造は OpenAI のものなので、
DOM が変わったらコードではなくセレクタを差し替えてください。

## 信頼度の分離（案7）

- 読取信頼度（`read_conf`）＝ OCR が読めたか → 低ければ「近づけて再読取」。
- 解答信頼度（`answer_conf`）／根拠信頼度（`rationale_conf`）＝ ソルバー出力。
- プレースホルダは `answer_conf ≤ 0.2`（★☆☆）で、断定しないことを担保。

## バージョン契約（`app/version.py`）

`SOLVER_API_VERSION` / `EXPLAINER_API_VERSION` / `EXTRACTOR_API_VERSION` /
`GLASSES_VIEW_CONTRACT_VERSION` / `OVERLAY_CONTRACT_VERSION` を契約ごとに管理。
版数はここに書きません。正本は `app/version.py`、公示は `README.md` の 1 行です。
構造化 `evidence_refs`、解説キャッシュ・履歴メタデータ、疎な page index の早期拒否は
加算的に追加され、旧 `evidence_pages` の意味は変更していません。
クライアントは `GET /v1/version` でネゴシエートします。

## 評価ベンチ（案12）

`scripts/eval_exam.py`（`--samples DIR` / `--synthetic N` / `--solvers a,b`）が
layout→subject→solver→HUD を流し、**設問抽出率/科目判定率/解答生成率/HUD3行以内率/
（expected があれば）正答率**を JSON 出力。同一入力で複数 solver を比較できる。
同梱の `data/exam_samples/` は**著作権配慮で合成・汎用の練習問題のみ**。

## 実機前提（要点）

実機 Rokid Glasses は**両眼 モノクロ緑 Micro-LED（480×398/眼）・FOV 約23°
（一部レビューは30°）・6DoF非対応**の情報表示デバイス（ウェブ検証済み仕様。片眼のみではありません）。
よって紙への厳密な固定重畳は不可で、`overlay` は 2D 画像アンカー＋方向ヒントとして提供し、
解答は `glasses_view` のグラス内テキスト（段階・ページ送り）で読む。詳細は
[glasses-ux-contract.md](glasses-ux-contract.md)、実機仕様は
[cxr-l-integration.md](cxr-l-integration.md)。

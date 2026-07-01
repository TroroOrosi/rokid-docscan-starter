# 入試問題ソルバー アーキテクチャ（解答モード）

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
- **solve**: `retrieval.retrieve_context(documents/pages)` で根拠 `context`/`evidence_pages` を取得→`Question(context=..., image_path=...)` に注入→`solve_with_fallback`（tier 順に試行し offline local へフォールバック、採用 tier=`served_by`）→`solutions` に `evidence_pages`/`served_by` 保存。応答に `served_by`・`evidence` を追加。
  - **vision（用紙画像で解く）**: 実アダプタ（`claude`/`openai`/`gemini`）は `questions.image_path` の**ページ画像をモデルへ添付**し、図/数式/表/選択肢を直接読んで解答（OCR テキストは補助）。プロンプトは**教科別ガイダンス**付き（`app/solvers/claude.py` の `_SYSTEM` / `_subject_guidance`）。画像はクラウドへ送信されるため実 AI・鍵設定時のみ作動、未設定/失敗は local へフォールバック。`mode=real` ロックは不変。
- **overlay**: `tracking:"2d_image_anchor"`・`fixed_ar:false`・`anchor_hint{page_number,box}` を機械可読化（6DoF 固定 AR は未対応＝ハード待ち）。
- **reasoning**: `GET …/questions/{qid}/reasoning` で `raw_reasoning`＋`evidence`＋`served_by` を返す（HUD は短縮版のまま、`real` ロック準拠）。

## 撮影レス・文書ページ移動型 exam ＋ 英語リスニング（API 1.7.0）

「設問1枚アップロード」型（上記）に加え、**撮影を一切行わない**主経路を新設した。
Rokid 通常利用のように**本体 AI が視認した資料テキストをページ単位で登録**し（`/pages` は
`image` 任意＝テキストだけで記憶）、`finalize` が「全ページ読込完了」を宣言。以降はグラスの
ジェスチャで**現在ページを移動**し、**そのページの資料を解く**（写真は発生しない）。

```
本体AIの視認テキスト ─▶ POST /pages(image任意, ocr_text) ─▶ pages(image_path=NULL, phash="")
                                                              │  finalize=全ページ読込完了
exam-session(document_id, exam_type, answer_format)           ▼
  next-page/prev-page ─▶ current_page_index ─▶ solve-current ─▶ 現在ページ pages 行を解く
       （速スワイプ）        （現在ページ把握）     （タップ）        │ subject=detect_subject(そのページ)
                                                                   │ context=RAG＋(listening時)書き起こし
                                                                   ▼ solve_with_fallback → glasses_view(3行段階)
リスニング: /audio(録音+任意transcript) ─▶ transcribe(openai/gemini or 与値) ─▶ transcript
  /mode で 筆記(written) ⇄ リスニング(listening) 切替（グラス=Back長押し / スマホ）
```

- **撮影レス取り込み**：`POST /v1/documents/{id}/pages` は `image` 省略可。画像が無ければ
  `image_path=NULL`・`phash=""`・`ocr_md5` はテキストから算出。画像添付時は従来通り pHash も算出し
  `/v1/match` も使える（後方互換）。画像も text も無ければ 400。
- **solve-current**：現在ページ（`current_page_index`）の `pages` 行から `Question` を構成。
  `ocr_text`＝本文、`image_path`（あれば vision）、`subject`＝そのページの `detect_subject`、
  `context`＝RAG。**リスニング時**は `session.transcript`（書き起こし）と資料を `context` に統合し、
  `answer_format`（マーク/記述）を指示に反映（`_exam_prompt_context`）。解答は `questions`＋`solutions`
  に保存するので既存の `/view`（段階×ページ送り）・`/reasoning` がそのまま使える。`mode=real` ロック不変。
- **リスニング録音**：`POST …/{id}/audio`（`audio` ファイル＋任意 `transcript`）を `data/audio/` に保存。
  `app/transcribe.py` が `ROKID_TRANSCRIBER`（openai=`audio.transcriptions.create`、gemini=inline audio）で
  書き起こし。未設定/失敗/オフラインは**与えた `transcript` をそのまま使用**（クレデンシャル不要で成立）。
  Anthropic は ASR 非対応。
- **グラス単独操作**：`OPERATION_CONTRACT`（`GET /v1/settings.operations`）に `exam_next_page`/
  `exam_prev_page`/`exam_solve_current`/`exam_next_stage`/`mode_toggle`/`record_toggle` を追加。全操作が
  グラスのジェスチャに割当済みで、スマホは HTTP 中継のみ（画面不要）。

## モジュール（このリポジトリで実装済み）

| モジュール | 役割 | 差込口 |
|------------|------|--------|
| `app/solvers/`（base/registry/local_placeholder/**claude=LLMSolver**） | 問題解答ポート。既定はオフライン**プレースホルダ**（実際には解かない＝不正利用ガード）。`solve_with_fallback` で**二段フォールバック**。**実アダプタ claude/openai/gemini 同梱**（**vision：用紙画像を添付**＋教科別プロンプト） | `ROKID_SOLVER=claude\|openai\|gemini`＋各社 API キーで実解答。`ROKID_SOLVER_TIERS` で tier 指定 |
| `app/extractors/`（base/registry/local_placeholder/**claude=LLMExtractor**） | メディア抽出ポート（数式/図/グラフ/表）。既定はオフライン placeholder。**実アダプタ claude/openai/gemini 同梱**（数式→LaTeX 等） | `ROKID_EXTRACTOR=claude\|openai\|gemini` で実抽出 |
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
- `solutions`(answer, solution_steps_json, rationale, cautions, answer_conf, rationale_conf, evidence_pages_json, raw_reasoning, **served_by**, user_confirmed)
- `pages.image_path` は **nullable**・`phash` は既定 `""`（撮影レスのテキストページ用）。

既存 `documents`/`pages` はページ照合モード用にそのまま維持。

## エンドポイント

| メソッド | パス | 用途 |
|----------|------|------|
| POST | `/v1/exam-sessions` | 一時セッション作成（mode, voice_enabled, **document_id, exam_type, answer_format**） |
| POST | `/v1/exam-sessions/{id}/questions` | 問題画像＋任意OCR/bbox → 構造化・科目推定・`media`抽出 |
| POST | `/v1/exam-sessions/{id}/questions/{qid}/solve` | 解答（real は既定ロック）→ `glasses_view`＋`overlay`＋`served_by`＋`evidence` |
| POST | `/v1/exam-sessions/{id}/next-page` / `prev-page` | **文書ページ移動**（現在ページ ±1・クランプ・撮影なし） |
| GET | `/v1/exam-sessions/{id}/current` | **現在ページ把握**（科目・プレビュー・画像有無） |
| POST | `/v1/exam-sessions/{id}/solve-current` | **現在ページの資料を解く**（listening 時は書き起こしを統合）→ `glasses_view` |
| POST | `/v1/exam-sessions/{id}/mode` | **筆記 ⇄ リスニング** 切替（`{"exam_type":...}`） |
| POST | `/v1/exam-sessions/{id}/audio` | **リスニング録音**アップロード（`audio`＋任意`transcript`）→ 書き起こし保存 |
| GET | `/v1/exam-sessions/{id}/questions/{qid}/view?stage=&page=` | 段階×ページ送り取得 |
| GET | `/v1/exam-sessions/{id}/questions/{qid}/reasoning` | フル推論ログ（案9、HUD非表示・real ロック準拠） |
| GET | `/v1/exam-sessions/{id}` | セッション状態（`document_id`/`exam_type`/`current_page_index`/`total_pages`＋解答済み一覧） |
| GET | `/v1/settings` | 無音契約・音声トグル・real ロックの公示 |
| GET | `/v1/version` | 契約バージョン＋ analyzers/solvers/extractors 一覧 |

## 信頼度の分離（案7）

- 読取信頼度（`read_conf`）＝ OCR が読めたか → 低ければ「近づけて再撮影」。
- 解答信頼度（`answer_conf`）／根拠信頼度（`rationale_conf`）＝ ソルバー出力。
- プレースホルダは `answer_conf ≤ 0.2`（★☆☆）で、断定しないことを担保。

## バージョン契約（`app/version.py`）

`SOLVER_API_VERSION` / `EXTRACTOR_API_VERSION` / `GLASSES_VIEW_CONTRACT_VERSION` /
`OVERLAY_CONTRACT_VERSION` を契約ごとに管理。`API_VERSION` は現在 `1.7.0`
（撮影レス pages・文書ページ移動型 exam・リスニング録音を含む）、`APP_VERSION` は `0.7.0`。
`GLASSES_VIEW_CONTRACT_VERSION` は `1.3.0`（長文の解説/根拠を文単位に分割して3行ページ送り）。
クライアントは `GET /v1/version` でネゴシエート（`solvers`/`extractors` 等に `claude` が並ぶ）。

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

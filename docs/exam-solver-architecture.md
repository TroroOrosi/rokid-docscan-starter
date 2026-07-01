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
- **solve**: `retrieval.retrieve_context(documents/pages)` で根拠 `context`/`evidence_pages` を取得→`Question(context=...)` に注入→`solve_with_fallback`（tier 順に試行し offline local へフォールバック、採用 tier=`served_by`）→`solutions` に `evidence_pages`/`served_by` 保存。応答に `served_by`・`evidence` を追加。
- **overlay**: `tracking:"2d_image_anchor"`・`fixed_ar:false`・`anchor_hint{page_number,box}` を機械可読化（6DoF 固定 AR は未対応＝ハード待ち）。
- **reasoning**: `GET …/questions/{qid}/reasoning` で `raw_reasoning`＋`evidence`＋`served_by` を返す（HUD は短縮版のまま、`real` ロック準拠）。

## モジュール（このリポジトリで実装済み）

| モジュール | 役割 | 差込口 |
|------------|------|--------|
| `app/solvers/`（base/registry/local_placeholder/**claude**） | 問題解答ポート。既定はオフライン**プレースホルダ**（実際には解かない＝不正利用ガード）。`solve_with_fallback` で**二段フォールバック**。**実アダプタ `claude` 同梱** | `ROKID_SOLVER=claude`＋`ANTHROPIC_API_KEY` で実解答。`register_solver()` で他ベンダも追加可、`ROKID_SOLVER_TIERS` で tier 指定 |
| `app/extractors/`（base/registry/local_placeholder/**claude**） | メディア抽出ポート（数式/図/グラフ/表）。既定はオフライン placeholder。**実アダプタ `claude` 同梱**（数式→LaTeX 等） | `ROKID_EXTRACTOR=claude` で実抽出。`register_extractor()` で他モデルも追加可 |
| `app/retrieval.py` | 既存 `documents/pages` を横断検索し根拠 `context`/`evidence` を供給（依存なしの lexical scorer） | `ROKID_ENABLE_EMBEDDING` で実 embedding 検索に差替（未接続時は lexical へフォールバック） |
| `app/layout.py` | OCRテキスト→設問番号/本文/選択肢/図表/**解答欄box**（正規化座標） | 実レイアウト/ビジョンモデルが同構造を埋める |
| `app/subjects.py` | 科目推定（数学/英語/古文/物理/化学/歴史/現代文） | 実分類器に差替 |
| `app/glasses_view.py` | **無音・3行・段階×ページ送り**の HUD ペイロード（音/アニメ指示なし） | — |
| `app/overlay.py` | 解答欄box＋短答/番号（2D画像アンカー、`tracking/fixed_ar/anchor_hint`） | 6DoF が整えば紙固定ARへ |

## 既存資産の再利用

- **ページ/設問認識**は既存 `app/matching.py`（pHash＋OCR-MD5 2層）を再利用（資料化モード `/v1/match`）。
- ソルバー registry は `app/analyzers/registry.py` と同じ流儀。**従量課金(クラウド) vs ローカル**を環境変数で切替、欠落時はオフラインへフォールバック。

## データモデル（`app/db.py`）

- `exam_sessions`(mode, voice_enabled, subject_hint, status)
- `questions`(question_no, body_text, choices_json, figure_refs, answer_box_json, structure_json, subject, read_conf, page_number, image_path, **media_json**)
- `solutions`(answer, solution_steps_json, rationale, cautions, answer_conf, rationale_conf, evidence_pages_json, raw_reasoning, **served_by**, user_confirmed)

既存 `documents`/`pages` はページ照合モード用にそのまま維持。

## エンドポイント

| メソッド | パス | 用途 |
|----------|------|------|
| POST | `/v1/exam-sessions` | 一時セッション作成（mode, voice_enabled） |
| POST | `/v1/exam-sessions/{id}/questions` | 問題画像＋任意OCR/bbox → 構造化・科目推定・`media`抽出 |
| POST | `/v1/exam-sessions/{id}/questions/{qid}/solve` | 解答（real は既定ロック）→ `glasses_view`＋`overlay`＋`served_by`＋`evidence` |
| GET | `/v1/exam-sessions/{id}/questions/{qid}/view?stage=&page=` | 段階×ページ送り取得 |
| GET | `/v1/exam-sessions/{id}/questions/{qid}/reasoning` | フル推論ログ（案9、HUD非表示・real ロック準拠） |
| GET | `/v1/exam-sessions/{id}` | セッション状態（解答済み一覧） |
| GET | `/v1/settings` | 無音契約・音声トグル・real ロックの公示 |
| GET | `/v1/version` | 契約バージョン＋ analyzers/solvers/extractors 一覧 |

## 信頼度の分離（案7）

- 読取信頼度（`read_conf`）＝ OCR が読めたか → 低ければ「近づけて再撮影」。
- 解答信頼度（`answer_conf`）／根拠信頼度（`rationale_conf`）＝ ソルバー出力。
- プレースホルダは `answer_conf ≤ 0.2`（★☆☆）で、断定しないことを担保。

## バージョン契約（`app/version.py`）

`SOLVER_API_VERSION` / `EXTRACTOR_API_VERSION` / `GLASSES_VIEW_CONTRACT_VERSION` /
`OVERLAY_CONTRACT_VERSION` を契約ごとに管理。`API_VERSION` は現在 `1.6.0`
（explain-sessions を含む）、`APP_VERSION` は `0.4.0`（`claude` 実アダプタ同梱）。
`GLASSES_VIEW_CONTRACT_VERSION` は `1.2.0`（サーバ側の文字数切り詰め廃止）。
クライアントは `GET /v1/version` でネゴシエート（`solvers`/`extractors` 等に `claude` が並ぶ）。

## 評価ベンチ（案12）

`scripts/eval_exam.py`（`--samples DIR` / `--synthetic N` / `--solvers a,b`）が
layout→subject→solver→HUD を流し、**設問抽出率/科目判定率/解答生成率/HUD3行以内率/
（expected があれば）正答率**を JSON 出力。同一入力で複数 solver を比較できる。
同梱の `data/exam_samples/` は**著作権配慮で合成・汎用の練習問題のみ**。

## 実機前提（要点）

実機 Rokid Glasses は**両眼 モノクロ緑 Micro-LED（480×398/眼）・FOV 約23–30°・
6DoF非対応**の情報表示デバイス（ウェブ検証済み仕様。片眼のみではありません）。
よって紙への厳密な固定重畳は不可で、`overlay` は 2D 画像アンカー＋方向ヒントとして提供し、
解答は `glasses_view` のグラス内テキスト（段階・ページ送り）で読む。詳細は
[glasses-ux-contract.md](glasses-ux-contract.md)、実機仕様は
[cxr-l-integration.md](cxr-l-integration.md)。

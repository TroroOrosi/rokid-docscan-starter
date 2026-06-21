# 入試問題ソルバー アーキテクチャ（解答モード）

既存の「ページ照合（資料化）」モードに、**未登録の入試問題を読み取って解答・根拠を返す**
解答モードを追加した。設計は既存と同じ **ポート＆アダプタ＋レジストリ＋契約バージョニング**。

```
撮影画像/OCR ─▶ layout(構造化＋解答欄box) ─▶ subjects(科目推定) ─▶ solver(registry)
                                                                  │ ←(任意) RAG: documents/pages
                                                                  ▼
   分離信頼度(読取/解答/根拠) ─▶ glasses_view(3行・段階・ページ送り) ＋ overlay(解答欄box)
```

## モジュール（このリポジトリで実装済み）

| モジュール | 役割 | 差込口 |
|------------|------|--------|
| `app/solvers/`（base/registry/local_placeholder） | 問題解答ポート。既定はオフライン**プレースホルダ**（実際には解かない＝不正利用ガード） | `register_solver()` で Gemini/OpenAI/Claude/VLM を登録、`ROKID_SOLVER` で切替 |
| `app/layout.py` | OCRテキスト→設問番号/本文/選択肢/図表/**解答欄box**（正規化座標） | 実レイアウト/ビジョンモデルが同構造を埋める |
| `app/subjects.py` | 科目推定（数学/英語/古文/物理/化学/歴史/現代文） | 実分類器に差替 |
| `app/glasses_view.py` | **無音・3行・段階×ページ送り**の HUD ペイロード（音/アニメ指示なし） | — |
| `app/overlay.py` | 解答欄box＋短答/番号（2D画像アンカー） | 6DoF が整えば紙固定ARへ |

## 既存資産の再利用

- **ページ/設問認識**は既存 `app/matching.py`（pHash＋OCR-MD5 2層）を再利用（資料化モード `/v1/match`）。
- ソルバー registry は `app/analyzers/registry.py` と同じ流儀。**従量課金(クラウド) vs ローカル**を環境変数で切替、欠落時はオフラインへフォールバック。

## データモデル（`app/db.py`）

- `exam_sessions`(mode, voice_enabled, subject_hint, status)
- `questions`(question_no, body_text, choices_json, figure_refs, answer_box_json, structure_json, subject, read_conf, page_number, image_path)
- `solutions`(answer, solution_steps_json, rationale, cautions, answer_conf, rationale_conf, evidence_pages_json, raw_reasoning, user_confirmed)

既存 `documents`/`pages` はページ照合モード用にそのまま維持。

## エンドポイント

| メソッド | パス | 用途 |
|----------|------|------|
| POST | `/v1/exam-sessions` | 一時セッション作成（mode, voice_enabled） |
| POST | `/v1/exam-sessions/{id}/questions` | 問題画像＋任意OCR/bbox → 構造化・科目推定 |
| POST | `/v1/exam-sessions/{id}/questions/{qid}/solve` | 解答（real は既定ロック）→ `glasses_view`＋`overlay` |
| GET | `/v1/exam-sessions/{id}/questions/{qid}/view?stage=&page=` | 段階×ページ送り取得 |
| GET | `/v1/exam-sessions/{id}` | セッション状態（解答済み一覧） |
| GET | `/v1/settings` | 無音契約・音声トグル・real ロックの公示 |

## 信頼度の分離（案7）

- 読取信頼度（`read_conf`）＝ OCR が読めたか → 低ければ「近づけて再撮影」。
- 解答信頼度（`answer_conf`）／根拠信頼度（`rationale_conf`）＝ ソルバー出力。
- プレースホルダは `answer_conf ≤ 0.2`（★☆☆）で、断定しないことを担保。

## バージョン契約（`app/version.py`）

`SOLVER_API_VERSION` / `GLASSES_VIEW_CONTRACT_VERSION` / `OVERLAY_CONTRACT_VERSION` を追加、
`API_VERSION` を `1.3.0` に。クライアントは `GET /v1/version` でネゴシエート。

## 実機前提（要点）

実機 Rokid Glasses は**単色緑 480×398/眼・FOV23°・6DoF非対応**の情報表示デバイス。
よって紙への厳密な固定重畳は不可で、`overlay` は 2D 画像アンカー＋方向ヒントとして提供し、
解答は `glasses_view` のグラス内テキスト（段階・ページ送り）で読む。詳細は
[glasses-ux-contract.md](glasses-ux-contract.md)。

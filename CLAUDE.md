# CLAUDE.md — 本リポジトリの前提条件（変更時は必ず維持すること）

非公開リポジトリ。Rokid Glasses で視認した問題用紙を全ページ記憶し、解答・解説を
両眼 3 行 HUD に出す**サーバ側**実証実装（FastAPI + SQLite、Python のみ。グラス本体
アプリ CXR-L/Kotlin は対象外）。以下は依頼の前提条件であり、設計・実装・ドキュメントの
すべてがこれに従う。

## AI の前提

- **主 AI はグラス搭載 AI（GPT）**。Rokid Glasses の搭載ネイティブ AI は GPT / Gemini
  （ほか DeepSeek / Qwen）。**Claude は搭載 AI ではない**。
- 主経路: 搭載 GPT が読取（`ocr_text`/`vision_text`）と全問解答を担い、問題別解答を
  `POST /v1/exam-sessions/{id}/solutions` でサーバへ取り込む（`served_by="onboard"`・
  サーバ鍵不要）。
- サーバ側の実 AI アダプタ（`ROKID_SOLVER/EXPLAINER/ANALYZER/EXTRACTOR=openai|gemini|claude`）
  は**より高性能なモデルが必要な場合の任意経路**。既定は `local`（オフライン・鍵不要）で、
  鍵/SDK 欠落時は必ずローカルへフォールバック（500 にしない）。例示は GPT（openai）を第一に。

## 撮影しない・LED（設計原則）

- **撮影しない**: 写真ファイル・フラッシュ・シャッター音を一切発生させない。本体 AI の
  認識テキスト（本文=`ocr_text`＋図の読み取り=`vision_text`）のみ受ける。録音も無音。
- **プライバシー LED はカメラ稼働中は必ず点灯**（視認＝認識＝カメラ ON＝LED 点灯。
  ハード強制・改変不可 `tamper:forbidden`。カメラ OFF の視認は存在しない）。
- **設計原則: LED 点灯時間の最小化**。読取フェーズのみカメラ ON とし、`finalize-reading`
  以降（解答・閲覧）はカメラを閉じる＝LED 消灯（`led_off_during_review:true`）。
  LED の無効化・迂回は実装しない（`scripts/rokid_led.py` は独立診断ツールで契約不変）。

## 3 フェーズフロー（主経路）

1. **読取**（カメラ ON・最短化）: `POST /v1/documents` → 2本指タップ（AI 起動=視認）×全ページ
   → `POST /pages`（scan_ack）→ `/finalize` → exam セッション作成（`document_id` 必須）→
   **ダブルタップ=読取完了宣言** → `POST /finalize-reading`（問題分割・デッキ作成・
   status open/reading→reviewing・冪等・カメラ OFF）。
2. **解答**（カメラ OFF）: 文書を問題単位に分割（`segment_problems`: 問N/大問 境界・
   ページ跨ぎマージ・境界なしは全体 1 問題＝安定 id **「全体」** を合成）。主経路=搭載 GPT の
   ingest（照合は `problem_index`（デッキ index）優先・なければ `problem_no`。再 ingest は
   latest wins）。任意=非 local な `ROKID_SOLVER` 設定時に finalize-reading 内で未解答分を
   一括解答（全ページ+RAG+transcript を文脈に。再開可能・local フォールバック結果は保存しない）。
3. **閲覧**（カメラ OFF・LED 消灯）: `GET /solutions`（デッキ）→ `GET /review?index=k&view_page=n`。
   **1 問題=解答+解法+根拠+注意を一括 1 ストリーム**（段階めくりなし・確定事項）。
   問題送り=2本指スワイプ左右 / 送り読み=2本指スワイプ上下 / 終了=ダブルタップ。

`solve-current` / ページ移動 / 設問アップロードは互換の二次経路（挙動を壊さない）。

## 操作（グラス単独で完結）

- 全操作はグラスのジェスチャのみで完結（スマホは HTTP 中継のみ・画面不要）。
- ジェスチャ未割当の必須 HTTP（`POST /v1/documents`・`/finalize`・exam セッション作成）は
  **中継アプリの自動チェーン責務**（読取開始=初回2本指タップ、読取完了宣言=ダブルタップに連動。
  cxr-l-integration.md §5）。人間の入力はジェスチャのみ——この責務まで含めて上の主張が成立する。
- **CXR-L はスマホ側プラグイン SDK**（Hi Rokid アプリ経由・グラスとは Bluetooth/Caps wire。
  実機実績: CxrGlobal/claude-mobile-hud）。スマホ経由は必須で、HUD は CUSTOMVIEW
  （`customViewUpdate`）にテキスト・リレーする。「グラス単体 Wi-Fi 直結」構成は未確認と扱う。
- 現行公式ジェスチャ: 2本指タップ=AI 起動 / 1本指タップ=クリック / ダブルタップ=終了
  （フェーズ・モーダル: 読取中=finish_reading・閲覧中=close）/ 2本指スワイプ上下=スクロール・
  左右=前後ページ / **長押し=録画⇄音声録音トグル**（筆記⇄リスニング切替・録音開始/停止に割当）。
- **KeyCode 表は旧・単眼 Rokid Glass 由来で未実測**。`keycodes_verified:false` を維持し、
  「検証済み」と偽らない。実機計測（`adb shell getevent -l`）と `ROKID_KEYMAP`(JSON) 上書きで吸収。

## 対応形式・安全

- 筆記/リスニング（`exam_type=written|listening`）、マーク式/記述式（`answer_format=mark|written`）。
  リスニングは無音録音 → `POST /audio`（transcript フォールバック・Anthropic は ASR 非対応）→
  書き起こしを解答文脈に統合。
- **`mode=real` は既定ロック**（`ROKID_ALLOW_REAL_EXAM_SOLVE=1` が無い限り、solve・ingest・
  デッキ・閲覧のいずれも解答を保存/表示しない）。学習・模試用途。
- HUD 契約: 最大 3 行・無音・無フラッシュ・無アニメ・無点滅。文字数制限はクライアント責務。

## 開発規約

- テストはオフライン・鍵不要（`pytest -q` 全緑を維持）。API テストは
  `ROKID_DATA_DIR=tmp_path` + `importlib.reload(config/db/main)` の fixture パターン、
  fake solver は `register_solver(..., replace=True)` + `ROKID_SOLVER` env。
- 契約変更時は `app/version.py` を加算し、`tests/test_versioning.py` の pin と docs の版数
  （README / user-operation-guide / explain-sessions 等）を同時に更新（版数ドリフトを作らない）。
- 研究目的・成果の記述はリポジトリに書かない（依頼により別管理）。

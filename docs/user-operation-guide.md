# ユーザー操作ガイド（実機運用）

このドキュメントは「**人間（あなた）が実機・現場で行うこと**」と
「**システム/実装側が自動でやること**」を明確に分け、さらに
「**操作後に必要になる設計判断**」を整理します。

- 本リポジトリ（サーバ MVP）は **既に実装済み** で、ローカルで動きます。
- ここで「ユーザーが行う」と書いた項目は、**コードでは代行できない物理操作や
  アカウント取得・同意取得など** です。それ以外はシステムが自動化します。
- 現在のバージョン: **APP 0.4.0 / API 1.6.0**
- 要約/解答/解説/メディア抽出は既定でローカル実装ですが、**実 AI（Anthropic Claude）
  アダプタ `claude` を同梱**しており、環境変数で実運用に切り替えられます（§6・§7）。

---

## 1. ユーザーが実機で行うこと（人間の操作）

| # | 操作 | 内容 | 完了の目安 |
|---|------|------|------------|
| U1 | 開発者アカウント / SDK アクセス取得 | Rokid AR Platform（`ar.rokid.com/sdk`）で開発者登録し、CXR-L SDK（Android/iOS）を入手 | SDK が DL でき、サンプルがビルドできる |
| U2 | デバッグ環境（ADB / ケーブル） | Android コンパニオン端末を USB デバッグ可能にし、`adb devices` で認識 | `adb devices` に端末が出る |
| U3 | グラスのペアリング | Rokid Glasses と端末を BLE/Wi-Fi でペアリング、ファーム/アプリ更新 | グラスにカメラ映像/HUD が出る |
| U4 | 資料の全ページ撮影（スキャンフェーズ） | 実際の紙資料を1ページずつ撮影（文書＝複数ページ）。**全ページ撮り終えたら `/finalize` を呼んで完了を宣言する** | 各ページ画像が登録され、`status=ready` になる |
| U5 | 照明・角度チェック | 影・反射・斜め撮りを避け、ページ全体が枠に入る条件を確認 | §「撮影チェックリスト」を満たす |
| U6 | プライバシー同意 | 撮影・保存・（クラウド送信する場合）外部送信について利用者同意を取得 | 同意ログ/同意UIが用意されている |
| U7 | クラウド vs ローカルモデルの選択 | OCR/要約をクラウド（Gemini/OpenAI）かオンデバイスかを決める | §「操作後に必要な設計判断」D2 を決定 |
| U8 | 検証（バリデーション）実行 | 撮影サンプルで照合精度を確認（評価スクリプト実行） | `scripts/evaluate.py` の accuracy を確認 |

> U1〜U6 と U8 の一部は **物理操作・アカウント・同意** に関わるため、
> コードでは代行できません。U7 の「決定」も人間の判断です（実装の差し込み口は
> システム側が用意済み）。

### 撮影チェックリスト（U5）

- ページ全体がフレームに収まっている（端が切れていない）。
- 強い反射・影・指の写り込みがない。
- 端末を被写体に対してほぼ正対（極端な斜めなし）。
- ピントが合い、文字がにじんでいない。
- 同一文書内でページごとに見た目が十分に異なる（pHash が分離できる）。

### 全ページ認識〜完了の手順（スキャンフェーズ）

文書を解説モードや照合モードで使う前に、**全ページのスキャン→finalize** が必要です。

```
1. POST /v1/documents          → document_id を取得
2. POST /v1/documents/{id}/pages  (page_index=0, 画像, [ocr_text])
3. POST /v1/documents/{id}/pages  (page_index=1, 画像, [ocr_text])
   ...全ページ分繰り返す...
4. POST /v1/documents/{id}/finalize   ← ★「全ページ完了」の宣言
   → status が "open" から "ready" に変わる
   → 各ページの summary が生成される
```

`/finalize` を呼ばないと `status=open` のままで、解説セッション（explain-sessions）や照合（/v1/match）で使えません。**全ページを撮り終えたら必ず `/finalize` を呼んでください。**

> **完了確認**: `/finalize` のレスポンスに `page_count` と各ページの `summaries` が返ります。
> 期待するページ数と一致していることを確認してから次のフェーズに進んでください。

---

## 2. システム/実装側が自動化すること（実装済み）

これらは **すべてサーバ MVP に実装済み** で、ユーザーは API を叩くだけです。

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
| S13 | 資料解説モード（explain-sessions）撮影なし | `/v1/explain-sessions` 以下（API 1.6.0） |
| S14 | 解答 HUD（段階×テレプロンプター） | `app/glasses_view.py: build_glasses_view` |
| S15 | 解説 HUD（overview/detail/evidence×テレプロンプター） | `app/glasses_view.py: build_explain_view` |
| S16 | 問題構造解析（設問番号/本文/選択肢/解答欄box） | `app/layout.py: parse_layout` |
| S17 | 科目自動推定 | `app/subjects.py: detect_subject` |
| S18 | メディア抽出（数式/図/グラフ/表） | `app/extractors/` |
| S19 | RAG による根拠ページ検索 | `app/retrieval.py: retrieve_context` |

### システムが返すバージョン情報（契約ネゴシエーション）

`GET /v1/version` または各レスポンスの `versions` で取得:

```json
{
  "app_version": "0.4.0",
  "api_version": "1.6.0",
  "matcher_version": "1.1.0",
  "hud_contract_version": "1.0.0",
  "analyzer_api_version": "1.0.0",
  "solver_api_version": "1.0.0",
  "extractor_api_version": "1.0.0",
  "explainer_api_version": "1.0.0",
  "glasses_view_contract_version": "1.2.0",
  "overlay_contract_version": "1.1.0"
}
```

クライアント（Android/iOS/Rokid/Android XR）は、`hud_contract_version` や
`api_version` の **メジャー変化** を検知したら「アプリ更新を促す」挙動にできます。

---

## 3. 操作後に必要な設計判断（人間が決める／実装は差し込み済み）

撮影・検証が終わったら、運用に向けて以下を決めます。**決定ポイントごとに
システム側の差し込み口が既にある** ので、決めれば差し替えるだけです。

| # | 判断 | 選択肢 | システム側の受け口 |
|---|------|--------|---------------------|
| D1 | OCR をどこで動かすか | 端末側 / サーバ側 / プロバイダ | `ocr_text`・`fast_ocr_text`（端末）/ `app/analyzers`（サーバ） |
| D2 | モデルルーティング（解析/解答/解説/抽出） | local（既定）/ **claude（同梱）** | `ROKID_ANALYZER` / `ROKID_SOLVER` / `ROKID_EXPLAINER` / `ROKID_EXTRACTOR`＝`claude`＋`ANTHROPIC_API_KEY`（§7） |
| D3 | ストレージ/プライバシー | ローカルのみ / クラウド / 暗号化 | `app/config.py`（保存先）/ 同意フラグ（要追加） |
| D4 | HUD 文言・言語 | 日本語/英語、短縮ルール | `app/hud.py`・`app/glasses_view.py`（テレプロンプター式でページ数制限なし） |
| D5 | 信頼度しきい値 | HIT/LOW/NO の境界 | `app/matching.py` 定数 + `scripts/evaluate.py` の提案値 |
| D6 | オフラインフォールバック | 圏外時の挙動 | analyzer/solver/explainer の `offline` フラグ + registry のフォールバック |
| D7 | ターゲット端末 | Android / iOS / Rokid / Android XR | デバイスバックエンドレジストリ（[future-proof-architecture.md](future-proof-architecture.md) §デバイス） |

詳細な将来設計（ポート&アダプタ、レジストリ、契約バージョン、移行戦略）は
[future-proof-architecture.md](future-proof-architecture.md) を参照。

---

## 4. グラス操作リファレンス（KeyCode マッピング・要実機検証）

> ⚠️ 下表の KeyCode は初代 Rokid **Glass**（単眼）のシステムドキュメント由来で、
> 新しい Rokid **Glasses**（YodaOS-Sprite / Android 12 API 32）で同一とは限りません。
> 実装前に対象端末で Android `KeyEvent`／CXR 入力イベントを実測し、
> `app/glasses_view.py` の `OPERATION_CONTRACT` と合わせてください。操作契約は
> レスポンス（`nav.operations`）としてデータで返るため、クライアント側で差し替え可能です。
> 参考: [cxr-l-integration.md](cxr-l-integration.md) §7。

| ユーザー操作 | Android KeyCode | 本サーバの用途 |
|---|---|---|
| **TP-単击**（タップ） | `KEYCODE_DPAD_CENTER = 23` | 解説表示・確認 |
| **TP-長按**（長押し） | `KEYCODE_TV = 170` | 次の解説段階へ（overview→detail→evidence） |
| **TP-双击**（ダブルタップ） | `KEYCODE_ENTER = 66` | HUD を閉じる |
| **TP-左滑**（スワイプ左） | `KEYCODE_DPAD_LEFT = 21`（連続） | 次テキストスライス（テレプロンプター送り） |
| **TP-右滑**（スワイプ右） | `KEYCODE_DPAD_RIGHT = 22`（連続） | 前テキストスライス（テレプロンプター戻し） |
| **TP-快速左滑**（速スワイプ左） | `KEYCODE_DPAD_UP = 19`（単発） | 次ページへ（`POST /next-page`） |
| **TP-快速右滑**（速スワイプ右） | `KEYCODE_DPAD_DOWN = 20`（単発） | 前ページへ（`POST /prev-page`） |
| **Back-単** | `KEYCODE_BACK = 4` | 前の画面へ戻る |

> ⚠️ **速スワイプ方向の注意**: 速スワイプ左 = `KEYCODE_DPAD_UP`、速スワイプ右 = `KEYCODE_DPAD_DOWN` という割り当ては Rokid 公式仕様です。直感と逆に見えますが必ず KeyCode でリッスンしてください。

---

## 5. モード別フロー

### 5-A. 資料照合モード（/v1/match）

```
1. POST /v1/documents + 全ページ POST /v1/documents/{id}/pages
2. POST /v1/documents/{id}/finalize  ← 完了宣言（忘れずに）
3. Back-単 で撮影 → POST /v1/match → HUD に PAGE/LOW_CONF/NO_PAGE 表示
```

### 5-B. 資料解説モード（explain-sessions、v1.7）

> **撮影なし・カメラ画像送信なし**。ページナビはボタン操作のみ。

```
1. 資料の全ページスキャン + /finalize が完了していること（前提）
2. POST /v1/explain-sessions {"document_id": N}  → status=ready, page_index=0
3. タップ → GET /explain  → overview HUD 表示
4. 速スワイプ左 → POST /next-page → 次ページへ
5. 速スワイプ右 → POST /prev-page → 前ページへ
6. 長押し → GET /explain?stage=detail  → 詳細
7. もう一度長押し → GET /explain?stage=evidence → 根拠ページ
8. 長押し（3回目）→ GET /explain?stage=overview  → 概要へ戻る（ラップ）
9. ダブルタップ → HUD を閉じる
```

> **テレプロンプター**: 解説テキストが長い場合は自動的に複数スライスに分割されます。
> スワイプ左/右でスライスを送り読みできます。**文字数・行数の上限はなく**、
> すべてのテキストが HUD に表示されます（3行×Nスライス）。

### 5-C. 解答モード（exam-sessions）

```
1. POST /v1/exam-sessions {"mode": "study"}  ← study/mock/real から選択
2. Back-単 で問題撮影 → POST /v1/exam-sessions/{id}/questions
3. タップ → POST /v1/exam-sessions/{id}/questions/{qid}/solve
   → HUD に「答え: X」＋信頼度記号 表示
4. 長押し → GET /view?stage=solution → 解法ステップ
5. 長押し → GET /view?stage=rationale → 根拠
6. 長押し → GET /view?stage=caution → 注意事項
7. スワイプ左/右 → テキストのページ送り（テレプロンプター、制限なし）
```

> **real モード**: `ROKID_ALLOW_REAL_EXAM_SOLVE=1` が未設定の場合、解答は表示されません（不正利用防止）。

---

## 6. 推奨フロー（操作 → 検証 → 判断）

1. **U1〜U3**: SDK 取得・端末準備・ペアリング（人間）。
2. **U4〜U6**: サンプル文書を**全ページ**撮影し同意取得（人間）。
3. サーバを起動（システム）:
   `uvicorn app.main:app --port 8000`
4. 撮影画像を登録（システムが自動処理）:
   `/v1/documents` → `/pages` ×全ページ数 → `/finalize`（**全ページ完了後に必須**）。
5. **U8 検証**（人間が実行 → システムが集計）:
   `ROKID_DATA_DIR=data python scripts/evaluate.py --db data/docscan.db --out report.json`
   → `self_match_accuracy` と `suggested_thresholds` を確認。
6. **D1〜D7 を決定**（人間）。`suggested_thresholds` を見て D5 を調整。
7. 決めた D2（モデル）に合わせて analyzer/solver/explainer を登録（実装差し替えのみ）。

> 既定の D2 は `local`（オフライン・クレデンシャル不要）で全機能が動きます。
> 実 AI への切り替えは §7 のとおり環境変数だけで完了します（実アダプタは同梱済み）。

---

## 7. 実 AI（Claude アダプタ）の有効化

「ダミー（プレースホルダ）」だった各ポートは、**同梱の実アダプタ `claude` を
環境変数で有効化するだけ**で実運用できます。キー未設定時は自動でローカルに
フォールバックするため、切り替えでサーバが止まることはありません。

```bash
pip install anthropic                      # 任意依存
export ANTHROPIC_API_KEY=sk-ant-...
export ROKID_SOLVER=claude ROKID_EXPLAINER=claude \
       ROKID_ANALYZER=claude ROKID_EXTRACTOR=claude
export ROKID_LLM_MODEL=claude-opus-4-8     # 任意（安価: claude-haiku-4-5）
uvicorn app.main:app --port 8000
```

- `GET /v1/version` の `solvers`/`analyzers`/`explainers`/`extractors` に `claude` が
  並んでいれば登録済みです（既定ルーティングは `local` のまま）。
- 本番試験ロック（`mode=real` / `ROKID_ALLOW_REAL_EXAM_SOLVE`）は実モデルでも有効。
- 詳細は [README.md](../README.md) の「実モデル接続」節、および
  [cxr-l-integration.md](cxr-l-integration.md)（グラス本体 AI との接続）。

---

## 付録: 廃止されたエンドポイント（v1.6 → v1.7）

| 旧操作 | 旧エンドポイント | 廃止理由 |
|--------|----------------|----------|
| ページ撮影スキャン（解説モード） | `POST /scan`（画像アップロード） | 解説モードは撮影なし設計へ移行 |
| 全ページ読取完了宣言（解説モード） | `POST /commit`（ダブル長押し） | scanning フェーズ廃止（explain-sessions は /finalize 済みの文書を使用） |

> 注意: **文書登録フェーズの `/finalize`** は廃止されていません。これは引き続き必須です。
> 廃止されたのは explain-sessions 内の旧 `/scan` と `/commit` エンドポイントです。

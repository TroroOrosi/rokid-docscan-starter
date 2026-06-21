# ユーザー操作ガイド（実機運用）

このドキュメントは「**人間（あなた）が実機・現場で行うこと**」と
「**システム/実装側が自動でやること**」を明確に分け、さらに
「**操作後に必要になる設計判断**」を整理します。

- 本リポジトリ（サーバ MVP）は **既に実装済み** で、ローカルで動きます。
- ここで「ユーザーが行う」と書いた項目は、**コードでは代行できない物理操作や
  アカウント取得・同意取得など** です。それ以外はシステムが自動化します。

---

## 1. ユーザーが実機で行うこと（人間の操作）

| # | 操作 | 内容 | 完了の目安 |
|---|------|------|------------|
| U1 | 開発者アカウント / SDK アクセス取得 | Rokid AR Platform（`ar.rokid.com/sdk`）で開発者登録し、CXR-L SDK（Android/iOS）を入手 | SDK が DL でき、サンプルがビルドできる |
| U2 | デバッグ環境（ADB / ケーブル） | Android コンパニオン端末を USB デバッグ可能にし、`adb devices` で認識 | `adb devices` に端末が出る |
| U3 | グラスのペアリング | Rokid Glasses と端末を BLE/Wi-Fi でペアリング、ファーム/アプリ更新 | グラスにカメラ映像/HUD が出る |
| U4 | サンプル文書の撮影 | 実際の紙資料を1ページずつ撮影（文書＝複数ページ） | 各ページ画像が端末に保存される |
| U5 | 照明・角度チェック | 影・反射・斜め撮りを避け、ページ全体が枠に入る条件を確認 | §「撮影チェックリスト」を満たす |
| U6 | プライバシー同意 | 撮影・保存・（クラウド送信する場合）外部送信について利用者同意を取得 | 同意ログ/同意UIが用意されている |
| U7 | クラウド vs ローカルモデルの選択 | OCR/要約をクラウド（Gemini/OpenAI/Rizon）かオンデバイスかを決める | §「操作後に必要な設計判断」D2 を決定 |
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
| S6 | 要約（プロバイダ非依存） | `app/analyzers/`（現状は local プレースホルダ） |
| S7 | ページ照合（ハミング+OCR一致） | `app/matching.py: match` |
| S8 | HUD 応答（3行固定） | `app/hud.py: build_hud` |
| S9 | バージョン情報の付与 | `app/version.py` → 各レスポンス |
| S10 | しきい値チューニング用フック | `app/matching.py` 定数 + `scripts/evaluate.py` |
| S11 | ログ/診断（client_version / sdk_hint エコー） | `/v1/documents`・`/v1/match` レスポンス |

### システムが返すバージョン情報（契約ネゴシエーション）

`GET /v1/version` または各レスポンスの `versions` で取得:

```json
{
  "app_version": "0.2.0",
  "api_version": "1.2.0",
  "matcher_version": "1.1.0",
  "hud_contract_version": "1.0.0",
  "analyzer_api_version": "1.0.0"
}
```

クライアント（Android/iOS/Rokid/Android XR）は、`hud_contract_version` や
`api_version` の **メジャー変化** を検知したら「アプリ更新を促す」挙動にできます。

---

## 3. 操作後に必要な設計判断（人間が決める／実装は差し込み済み）

撮影・検証が終わったら、運用に向けて以下を決めます。**決定ポイントごとに
システム側の差し込み口が既にある** ので、決めれば差し替えるだけです。

| # | 判断 | 選択肢 | システム側の受け口 |
|---|------|--------|--------------------|
| D1 | OCR をどこで動かすか | 端末側 / サーバ側 / プロバイダ | `ocr_text`・`fast_ocr_text`（端末）/ `app/analyzers`（サーバ） |
| D2 | モデルルーティング | local / Gemini / OpenAI / Rizon | `app/analyzers/registry.py`（`ROKID_ANALYZER` 環境変数 / `prefer`） |
| D3 | ストレージ/プライバシー | ローカルのみ / クラウド / 暗号化 | `app/config.py`（保存先）/ 同意フラグ（要追加） |
| D4 | HUD 文言・言語 | 日本語/英語、短縮ルール | `app/hud.py: build_hud`（3行固定の契約は維持） |
| D5 | 信頼度しきい値 | HIT/LOW/NO の境界 | `app/matching.py` 定数 + `scripts/evaluate.py` の提案値 |
| D6 | オフラインフォールバック | 圏外時の挙動 | analyzer の `offline` フラグ + registry のフォールバック |
| D7 | ターゲット端末 | Android / iOS / Rokid / Android XR | デバイスバックエンドレジストリ（[future-proof-architecture.md](future-proof-architecture.md) §デバイス） |

詳細な将来設計（ポート&アダプタ、レジストリ、契約バージョン、移行戦略）は
[future-proof-architecture.md](future-proof-architecture.md) を参照。

---

## 4. 推奨フロー（操作 → 検証 → 判断）

1. **U1〜U3**: SDK 取得・端末準備・ペアリング（人間）。
2. **U4〜U6**: サンプル文書を撮影し同意取得（人間）。
3. サーバを起動（システム）:
   `uvicorn app.main:app --port 8000`
4. 撮影画像を登録（システムが自動処理）:
   `/v1/documents` → `/pages` ×N → `/finalize`。
5. **U8 検証**（人間が実行 → システムが集計）:
   `ROKID_DATA_DIR=data python scripts/evaluate.py --db data/docscan.db --out report.json`
   → `self_match_accuracy` と `suggested_thresholds` を確認。
6. **D1〜D7 を決定**（人間）。`suggested_thresholds` を見て D5 を調整。
7. 決めた D2（モデル）に合わせて analyzer を登録（実装差し替えのみ）。

> この MVP の時点では D2 は `local`（オフライン・クレデンシャル不要）固定で
> 動きます。クラウド/Rizon への切り替えは、アダプタを1つ登録するだけです。

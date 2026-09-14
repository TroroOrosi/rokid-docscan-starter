# Rokid DocScan（入試問題を撮影して解答するサーバ）

Status: Current project entrypoint. Updated 2026-09-14.

## このリポジトリの目的

入試問題（共通テスト想定）の冊子を Rokid Glasses で撮影し、**解答用紙に記入する
内容を小問ごとに**グラスの HUD（最大3行）で確認できるようにするシステムです。
Android スマホを中継し、Windows PC をサーバーとして使う実機経路をリポジトリ内に
含みます。

紙資料のスキャンとページ照合（`/v1/match`、pHash）は、この上に解答モードを載せた
**土台**です。現在の目的ではありません。

想定するセッション（`tasks/plan.md` の現行契約）:

- 通常: 20〜40ページを約10分撮影 → 約10分分析 → 約130分閲覧。
- リスニング: 30分録音の間に約10分撮影 → 両入力終了後に約10分分析 → 約110分閲覧。
- グラスに Wi-Fi は無く、スマホは 4G/5G でロック中。**現場に PC・自前サーバ・
  テザリングを持ち込みません。** 150分で自動終了しません。

撮影の主経路は次の通りです。

1. スマホの撮影操作で `AIMING` を表示し、表示open callback後に静止時間を置いて
   CXR-L `takePhoto(1920, 1080, 80)` でページを1回だけ撮影する。
2. Android の bundled Japanese ML Kit で OCR する。
3. スマホの `CAPTURE_REVIEW` で縮小プレビューと枠内判定を確認し、登録または
   同じページの再撮影を明示的に選ぶ。
4. 登録操作後に撮影JPEG、回転角、OCRをFastAPIへ送り、サーバーは向きを補正した
   normalized PNGを正本として保存する。
5. 画像対応 Analyzer が転記・図表説明を補い、Solver が問題を解く。
6. Android リレーが CUSTOMVIEW へ最大3行ずつ表示する。

`android-relay/RokidGlobalLink` は、公式
`com.rokid.cxr:client-l:1.1.1` AAR を使い、Global Hi Rokid
`com.rokid.sprite.global.aiapp` へ接続します。
[TakanariShimbo/CxrGlobal](https://github.com/TakanariShimbo/CxrGlobal) の clone、
submodule、AARコピーは不要です。

公開 CXR-L で確認できない「グラス搭載 AI の任意認識文・回答を外部アプリへ返す
コールバック」には依存しません。テキストだけのページ登録と `POST /solutions` は API
互換として残していますが、実機の成立条件には数えません。
公開静止画面には撮影前ライブプレビュー、オートフォーカス、専用シャッターボタンの
入力コールバックもありません。固定焦点のため照準は構図合わせ用であり、合焦表示では
ありません。

- **プライバシー LED**：ハードウェア/ファームウェア制御です。対応コードは無効化・遮蔽・
  偽装・迂回を行いません。
  撮影中の点灯、写真 callback 後の消灯、解答閲覧中の消灯維持を実機で物理確認します。
- **撮影通知**：シャッター音、フラッシュ、撮影表示は端末制御です。無音・無フラッシュを
  ソフトウェア契約として約束しません。
- **中断復帰**：文書IDと次ページ番号に加え、未登録写真、OCR、回転をスマホの
  アプリ専用領域へ保存します。再起動後は確認画面へ戻し、表示確認後に待機を始めます。
- **安全な公開**：実機利用では Bearer 認証を有効にし、信頼できる LAN 内で動かします。
- **学習用途**：`mode="real"` の解答は既定でロックされます。

### 解答経路

| 経路 | 位置づけ |
|---|---|
| `ROKID_SOLVER=chatgpt-web` | **現行の主経路。** 利用者のログイン済み ChatGPT ウェブセッションを CDP 経由で操作します |
| スマホ内ローカルモデル（F-51F、llama.cpp） | 現場向けの目標。実測は済んでいますが、現場構成への組み込みは未了です |
| `openai` / `gemini` / `claude` | API キーがあれば設定だけで動きます。`ROKID_SOLVER_TIERS` のフォールバック段として残します |

**ChatGPT ウェブ UI の自動操作は OpenAI の利用規約に反し、アカウントが制限される
risk があります。**利用者の判断で選択した経路です（詳細は下の「実モデル接続」）。

**未解決:** chatgpt-web の実測はすべて PC 上の Chrome に対するものです。現場は PC を
置かない前提なので、スマホ側のブラウザへ `ROKID_CHATGPT_CDP` を向ける必要があります。
設計上は塞がっていませんが**一度も実行していません**。chatgpt-web を現場対応済みとは
書かないでください。

導入の正本は
[Windows + Androidスマホ中継による実機運用](docs/windows-android-real-device-setup.md)、
CXR-L の実装境界は
[CXR-L / Global Hi Rokid integration](docs/cxr-l-integration.md)です。

現在のバージョン: **Server APP 0.27.0 / API 1.18.0 / Android client 0.3.16 / Glasses View 1.11.0 / Solver API 1.6.0**。
版数の正本は `app/version.py` です。他の資料は版数を書かず、この行だけが
`tests/test_documentation_contract.py` で実装と照合されます。
Solver API は、記入用解答の全文保持・資料不足の分離を行う `answer_only` モードを含みます。

---

## ユーザーがやること / システムがやること / 次に判断すること

| 区分 | 概要 | 詳細ドキュメント |
|------|------|------------------|
| **ユーザーがやること**（人間の物理操作） | Windows/Android環境準備・Hi Rokidペアリング・APK導入・全ページ撮影・OCR/LED/HUDの実機確認 | [docs/windows-android-real-device-setup.md](docs/windows-android-real-device-setup.md) |
| **システムがやること**（実装済み・自動） | 文書作成 / ページ取込 / pHash・OCR-MD5 / finalize / 照合 / HUD 応答 / バージョン付与 / ログ / しきい値フック | [docs/user-operation-guide.md](docs/user-operation-guide.md) §2 |
| **次に判断すること**（操作後の設計判断） | OCR 配置 / モデルルーティング / ストレージ・プライバシー / HUD 文言 / 信頼度しきい値 / オフライン挙動 / 対象端末(Android/iOS/Rokid/Android XR) | [docs/user-operation-guide.md](docs/user-operation-guide.md) §3 |

将来モデル/SDK が新しくなっても壊れない設計（ポート&アダプタ、レジストリ、契約
バージョニング、移行戦略）は [docs/future-proof-architecture.md](docs/future-proof-architecture.md) を参照。

---

## 構成

```
rokid-docscan-starter/
├── android-relay/       # ★Global Hi Rokid対応スマホ中継APK（Java/Gradle）
│   ├── app/             # CXR-L撮影・ML Kit OCR・HTTP・CUSTOMVIEW
│   └── build-windows.ps1
├── app/
│   ├── main.py        # FastAPI エンドポイント（match / exam / explain）
│   ├── matching.py    # pHash / hamming / OCR 類似度 / スコアリング
│   ├── hud.py         # 3行 HUD ペイロード生成（/match 用）
│   ├── glasses_view.py# グラス表示ビルダー（exam / explain 用・HUD契約）
│   ├── overlay.py     # 解答欄オーバーレイ（2D画像アンカー）
│   ├── layout.py      # 設問構造解析（設問番号/本文/選択肢/解答欄box）
│   ├── subjects.py    # 科目推定（共通テスト準拠フル16教科：現代文/古文/漢文/数学/英語/物理/化学/生物/地学/世界史/日本史/地理/倫理/政治経済/現代社会/情報）
│   ├── retrieval.py   # RAG 横断検索（既存 documents/pages → 根拠）
│   ├── summarize.py   # 要約シム（analyzer に委譲）
│   ├── explainer.py   # Explainer ポート（ExplainRequest / ExplainResult / ABC）
│   ├── llm.py         # ★実 AI ブリッジ（openai/gemini/claude、遅延import・注入可）
│   ├── llm_http.py    # OpenAI互換HTTPクライアント（端末内 llama-server 用・SDK不要）
│   ├── provider_registry.py # 4ポート共通のアダプタ登録・選択
│   ├── page_pdf.py    # 撮影ページを1つのPDFへ束ねる（chatgpt-web の一括添付用）
│   ├── audio_formats.py # 音声MIME・保存suffix・provider対応の共通定義
│   ├── version.py     # 各契約バージョン（app 0.27.0 / api 1.18.0 / glasses 1.11.0 ほか）
│   ├── config.py      # 保存先・フィーチャーフラグ（ROKID_* / ANTHROPIC_API_KEY / ROKID_TRANSCRIBER）
│   ├── transcribe.py  # ★リスニング録音の書き起こし（openai/gemini・未設定時は与値）
│   ├── db.py          # sqlite3（documents/pages/exam/explain テーブル）
│   ├── analyzers/     # 解析ポート: base / registry / local_placeholder / claude ★
│   ├── solvers/       # 解答ポート: base / registry / local_placeholder /
│   │                  #   llm_adapter / claude / chatgpt_web（★現行主経路）
│   ├── explainers/    # 解説ポート: registry / local_placeholder / claude ★
│   ├── extractors/    # メディア抽出: base / registry / local_placeholder / claude ★
│   └── devtools/      # 旧隔離実験（supported runtimeから未参照）
├── tests/             # pytest（照合/API/バージョン/レジストリ/exam/explain/LLM）
├── scripts/
│   ├── make_sample_pages.py  # curl 用サンプル画像生成
│   ├── evaluate.py           # 照合評価 → JSON レポート
│   ├── eval_exam.py          # 解答パイプライン評価 → JSON レポート
│   └── rokid_led.py          # 旧隔離実験。実行・連携対象外
├── docs/
│   ├── README.md                    # ★資料の索引と権威順（最初に読む）
│   ├── windows-android-real-device-setup.md # ★Windows+Android実機手順（正本）
│   ├── cxr-l-integration.md         # ★CXR-L / Global Hi Rokid実装境界
│   ├── glasses-ux-contract.md       # 現行の入力契約（スマホ経路と :glassdoc）
│   ├── real-device-operation.md     # 実機運用の索引・合格条件
│   ├── device-verification-checklist.md # ★実機検証チェックリスト（CXR-L入力/LED/読取品質/閾値）
│   ├── user-operation-guide.md      # ユーザー操作 / 自動化 / 設計判断
│   ├── exam-solver-architecture.md  # ★解答モードアーキテクチャ
│   ├── explain-sessions.md          # 資料解説モード詳細・curl 例
│   ├── future-proof-architecture.md # 将来対応アーキテクチャ
│   ├── hardware-measurements.md     # 実機・成果物の測定記録（凍結）
│   ├── fast-scan-decisions.md       # 自動スキャン構想の採否判断（未実装・保留）
│   └── superpowers/specs/           # オフライン解答バンドルの設計（実装済み）
├── .env.example       # 全環境変数の雛形（コピーして .env に）
├── data/images/       # 画像保存先（実行時に自動生成）
├── requirements.txt   # コア依存（anthropic/openai/google-genai は任意・コメント参照）
├── Dockerfile
└── docker-compose.yml
```

---

## セットアップ

Python 3.10+ 推奨。

```bash
cd rokid-docscan-starter
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 起動

```bash
cp .env.example .env  # .env を使う場合。必要な設定だけ編集
uvicorn app.main:app --env-file .env --reload --port 8000
```

`.env` を使わない場合は `cp` と `--env-file .env` を省略してください。
設定ファイルは起動コマンドが明示的に読み込むため、pytestやライブラリから
`app.config` をimportしてもローカルの認証情報は混入しません。

- データ保存先を変えたい場合は環境変数 `ROKID_DATA_DIR` を設定:
  `ROKID_DATA_DIR=/tmp/rokid uvicorn app.main:app --port 8000`
- 起動時に `data/images/` と `data/docscan.db` が自動生成されます。

## テスト

```bash
pytest -q
```

照合ロジック（pHash 決定性 / ハミング距離 / OCR-MD5 正規化 / スコアリング /
HIT・LOW CONF・NO PAGE 判定）、API の登録〜finalize〜照合フロー、
バージョンメタデータ、analyzer レジストリ、explain-sessions フルフローを、
PIL で生成した合成画像で検証します（外部クレデンシャル不要・オフライン完結）。

## 評価（実サンプル読取後の検証に使用）

ユーザーが実機でサンプルを読取・登録した後（照合評価は画像を使う任意経路 `/match` 用）、照合品質としきい値提案を JSON で出力:

```bash
# 既存DBに対して評価
ROKID_DATA_DIR=data python scripts/evaluate.py --db data/docscan.db --out report.json
# 合成画像で素早く確認
python scripts/evaluate.py --synthetic 5
```

保存画像からクロップ・微回転・JPEG圧縮の非同一クエリを生成して照合するため、
`variant_match_accuracy` と `hamming_distribution`、`suggested_thresholds` を見て
`app/matching.py` のしきい値（D5）を調整します。これはオフラインの頑健性推定であり、
最終的なしきい値は可能であれば実機で独立に再読取した画像でも検証してください。

---

## API と curl 例

サーバが `http://127.0.0.1:8000` で動いている前提です。
サンプル画像（`page0.png` / `page1.png` / `query.png`）は次で生成できます:

```bash
python scripts/make_sample_pages.py
```

### 1. ヘルスチェック

```bash
curl -s http://127.0.0.1:8000/health
# {"status":"ok","versions":{...}}
```

### 2. 文書を作成

```bash
curl -s -X POST http://127.0.0.1:8000/v1/documents \
  -H 'Content-Type: application/json' \
  -d '{"title":"設計仕様書 v1","capture_device":"CXR-S"}'
# {"document_id":1,"title":"設計仕様書 v1","capture_device":"CXR-S","status":"open"}
```

### 3. ページを追加（実機主経路：写真 + スマホOCR）

Android リレーは撮影JPEG、回転角、端末OCRを同時に送ります。画像は
OCR と同じ向きの PNG に正規化してサーバーの正本として保存され、raw upload bytesは
保持されません。設定済みの画像対応 Analyzer が
必要に応じて OCR を補正します。`image_rotation` は `0`、`90`、`180`、`270`
（時計回り）を受け付け、省略時は `0` です。

実機撮影値は `takePhoto(1920, 1080, 80)` です。40〜60cmはローカル運用上の開始距離で、
対象SKUの合焦保証ではありません。スマホで `AIMING` を開いて用紙中心を「＋」へ合わせ、
スマホのシャッター操作後はcallbackまで静止します。取消はスマホの「撮影取消」で行い、
`takePhoto`発行前なら写真を撮りません。
四隅は撮影後プレビューで確認します。`takePhoto(4032, 3024, 80)` は実機で
JPEG callbackが届かなかった既知NGです。Binder容量圧迫と整合しますが、原因は未確定です。

撮影と端末OCRの完了後は `CAPTURE_REVIEW` となり、スマホへ縮小プレビューを表示します。
グラスへの表示は状態通知であり、確認済み入力面ではありません。写真はまだ未登録です。
スマホの「この写真を登録」で初めてサーバーへ送り、再撮影または未登録写真の破棄も
スマホで操作します。
OCRが0文字でも警告を確認したうえで登録できます。登録成功まで対象ページと次ページ番号は
変わりません。文書自体は初回撮影前に作成されます。

撮影前ライブ映像とオートフォーカスは公開CXR-L非対応です。照準の「＋」は用紙中心を
合わせる目安で、ディスプレイFOVとカメラFOVが異なるため正確な撮影境界でも合焦判定でも
ありません。CUSTOMVIEWのcloseや`AI-exit`には信頼できるoperator provenanceがないため、
シャッターや登録操作には使いません。
写真回転の既定は実機に合わせた90°で、スマホで回転選択後に再撮影を準備すると次の写真へ
適用されます。未登録写真はアプリ再起動後も `CAPTURE_REVIEW` へ復元されますが、自動撮影・
自動登録は行いません。

```bash
curl -s -X POST http://127.0.0.1:8000/v1/documents/1/pages \
  -F page_index=0 \
  -F image_rotation=0 \
  -F image=@page0.png \
  -F ocr_text='問1 図の回路の合成抵抗を求めよ'
# {"page_id":1,...,"image_path":"...","scan_ack":{...}}
```

端末 OCR が空でも写真だけを受理します。画像対応 Analyzer が設定されておらず
問題を検出できなかった場合も元写真を保持し、読取状態へ戻して同じページを再撮影できます。

テキストだけの登録も互換入力として残っています。

```bash
curl -s -X POST http://127.0.0.1:8000/v1/documents/1/pages \
  -F page_index=0 \
  -F ocr_text='問1 図の回路の合成抵抗を求めよ' \
  -F vision_text='回路図: R1=2Ω と R2=3Ω が直列'
```

`ocr_text`、`vision_text`、`image` のいずれも無い場合は 400 です。

読取が中断したら **`GET /scan-status`** で欠番を確認し、欠番だけ再読取します（読み取り専用・
撮影は発生しません）:

```bash
curl -s 'http://127.0.0.1:8000/v1/documents/1/scan-status?expected_total_pages=4'
# {"page_indexes":[0,2],"missing_page_indexes":[1,3],
#  "recommended_action":"reread_missing_pages","reread_allowed":true,...}
```

### 4. 文書を確定（finalize）

```bash
curl -s -X POST http://127.0.0.1:8000/v1/documents/1/finalize
# {"document_id":1,"status":"ready","page_count":2,
#  "summaries":[{"page_index":0,"summary":"1ページ目の本文テキスト"}, ...]}
```

各ページの OCR テキスト先頭行から簡易サマリを生成し、文書を `ready` にします。

### 5. 目の前の紙を照合（match）

**撮影しません**。視認中ページの認識テキスト（その場認識）で照合します:

```bash
curl -s -X POST http://127.0.0.1:8000/v1/match \
  -F document_id=1 \
  -F ocr_text='1ページ目の本文テキスト'

# （任意・後方互換／非推奨）画像を添付すると画像登録ページとは pHash で照合されます
curl -s -X POST http://127.0.0.1:8000/v1/match \
  -F document_id=1 -F image=@query.png -F fast_ocr_text='1ページ目の本文テキスト'
```

> 同一テキストのページが複数ある場合は判別できず、若い `page_index` が選ばれます。
> テキスト照合の `hamming` は `null` になります（`query_signals` で経路を確認可能）。

レスポンス例（HIT）:

```json
{
  "document_id": 1,
  "query_signals": {"phash": false, "text": true},
  "verdict": "HIT",
  "best_page": {"page_id":1,"page_index":0,"hamming":null,"ocr_match":true,"ocr_similarity":1.0,"confidence":0.95},
  "confidence": 0.95,
  "hud": {"verdict":"HIT","confidence":0.95,"lines":["PAGE 1/2","1ページ目の本文テキスト","conf 0.95  txt 1.00"]},
  "candidates": [ {"page_index":0,...}, {"page_index":1,...} ]
}
```

（画像同士の照合では `hamming` に整数距離が入り、HUD 3行目は `conf 1.00  hd 0` の形になります）

`verdict` は以下の3値:

| verdict   | 意味                                   | HUD 1行目 |
|-----------|----------------------------------------|-----------|
| `HIT`     | 信頼できる一致                          | `PAGE n/N` |
| `LOW_CONF`| 候補はあるが信頼度が低い                 | `LOW CONF` |
| `NO_PAGE` | この文書内に一致なし / ページ未登録      | `NO PAGE`  |

---

## 照合ロジック（決定的）

`app/matching.py` 内のしきい値で挙動を制御します。

- **pHash**: 画像を 32×32 グレースケール化 → 2次元 DCT → 低周波 8×8 ブロックを
  中央値で2値化した **64bit** ハッシュ。
- **ハミング距離**:
  - `<= HAMMING_STRONG (6)` … 視覚的に確実な一致（視覚信頼度 1.0）
  - `>= HAMMING_WEAK (16)` … 無関係（視覚信頼度 0.0）
  - 間は線形補間。
- **OCR テキスト類似度ボーナス**: クエリと候補の OCR テキストがどれだけ似ているかで
  最大 `OCR_MD5_BONUS (0.35)` まで **段階的に** 加点します（実 OCR はノイズで揺れるため、
  完全一致のみだと現場でほぼ加点されないため）。
  - 正規化 MD5 が完全一致 → 満点ボーナス（最速パス。OCR 無し時の画像 MD5 一致もここ）。
  - そうでなければ正規化テキストの類似度 `ratio`（`difflib`、0..1）を見て、
    `ratio >= OCR_SIM_FLOOR (0.6)` のとき `OCR_MD5_BONUS * ratio` を加点。
    `ratio >= OCR_MATCH_RATIO (0.9)` なら `ocr_match=true`。
  - 正規化は「前後空白除去・連続空白を単一化・小文字化」。
  - レスポンスには `ocr_similarity`（0..1）が含まれます（追加フィールド・後方互換）。
- **判定**: 合成信頼度（0..1 にクリップ）が
  `>= CONF_OK (0.62)` → `HIT` / `>= CONF_LOW (0.40)` → `LOW_CONF` / それ未満 → `NO_PAGE`。

しきい値は撮影環境（照明・ブレ・解像度）に応じてチューニングしてください。

---

## Rokid Glasses への実機マッピング

実機でサポートする経路は一つです。

```text
Rokid Glasses
  └─ CXR-L / Bluetooth
      └─ Android: Global Hi Rokid + android-relay
          └─ LAN / HTTP(S)
              └─ FastAPI: Analyzer + Solver
```

| 役割 | 担当 |
|---|---|
| 撮影 | Glasses / CXR-L `takePhoto` |
| 端末 OCR | Android bundled Japanese ML Kit |
| Vision OCR・図表説明 | `ROKID_ANALYZER=openai\|gemini\|claude` |
| 問題分割・解答 | FastAPI + `ROKID_SOLVER=chatgpt-web\|openai\|gemini\|claude` |
| HUD | Android relay → Global Hi Rokid CUSTOMVIEW |
| 中断復帰 | Android保存ID + `GET /scan-status` |

スマホは初期設定画面を持ち、セッション中も画面を表示したままにします。これは現行
Hi Rokid の写真 callback が画面消灯後に止まる場合へ備えるためです。接続後の撮影、
再撮影、登録、読取完了、閲覧はスマホで操作します。CUSTOMVIEWはHUD出力として使い、
グラス側入力はglass-app経路が別途実機合格するまで運用契約へ含めません。

詳細は [実機手順](docs/windows-android-real-device-setup.md) を参照してください。

---

## 資料解説モード（登録後・カメラOFF）

`/v1/explain-sessions` は、確定済み文書をページ単位で解説する既存 API です。
現行 `android-relay` の主 UI は問題の一括解答と `/review` に接続しており、
explain-sessions のグラス操作はまだ組み込んでいません。サーバー API の使用例は
[docs/explain-sessions.md](docs/explain-sessions.md) を参照してください。

---

## 解答モード（実機主経路）

Android リレーが撮影後のユーザー確認を挟んで次のチェーンを実行します。

1. 初回撮影時に `POST /v1/documents`。
2. スマホで `AIMING` を表示し、open callback後にスマホから1回だけ撮影。
3. 各撮影後に `CAPTURE_REVIEW` で未登録写真とOCR文字数を表示。
4. スマホの「この写真を登録」で確定した写真だけを
   `POST /v1/documents/{id}/pages` へ JPEG + OCR で送信。
5. スマホの「読取完了」で `/scan-status` → `/finalize`。
6. `POST /v1/exam-sessions` → `/finalize-reading`。
7. `GET /review` を CUSTOMVIEW へ表示。

`/finalize` は画像 Analyzer の転記をページへ保存してから問題を分割します。
`/finalize-reading` は各問題の開始ページ画像を画像対応 Solver へ渡します。
端末 OCR とクラウド OCR の両方が空なら問題0件として読取状態を維持し、同じページの
再撮影または Analyzer 設定を促します。

CUSTOMVIEWのoperator tap deliveryは確認済み入力ではありません。close callbackと
`AI-exit`はlifecycle evidenceとしてのみ記録します。

| 状態 | グラス側 | スマホのボタン |
|---|---|---|
| 接続完了・読取中 (`READY` / `READING`) | 状態表示のみ | 撮影準備 / 前ページ撮影準備 / **読取完了** |
| 撮影準備 (`AIMING`) | 照準表示のみ | シャッター / 撮影取消 |
| 静止待ち (`STABILIZING`) | 静止案内のみ | 撮影取消 |
| 撮影確認 (`CAPTURE_REVIEW`) | 状態表示のみ | この写真を登録 / 同じページを撮り直す / 未登録写真を破棄 |
| 閲覧中 (`REVIEW`) | HUD表示のみ | 戻る / 次へ / **新規** |

通常撮影は、スマホで照準を開き、構図確認後にスマホで静止待ちを開始します。
CUSTOMVIEWのcloseや`AI-exit`で撮影、取消、登録、画面送りを行いません。
CustomViewのopen ACK faultまたは3秒のACK timeoutではcallback epochをfenceし、
`takePhoto`を発行しません。「Hi Rokid認可・再接続」を完了するまで次のView要求も
行いません。
ファームウェアが2回の入力をアプリへ
`DOUBLE_SHORT` として配送した場合だけ、読取中は直前ページの再撮影準備、
撮影確認中は同じページの再撮影準備、閲覧中は前の表示として扱います。

サーバーだけを確認する場合の最小 API 例:

```bash
curl -s -X POST http://127.0.0.1:8000/v1/documents \
  -H 'Content-Type: application/json' -d '{"title":"模試"}'
curl -s -X POST http://127.0.0.1:8000/v1/documents/1/pages \
  -F page_index=0 -F image=@page0.png -F ocr_text='問1 1+1を答えよ'
curl -s -X POST http://127.0.0.1:8000/v1/documents/1/finalize
curl -s -X POST http://127.0.0.1:8000/v1/exam-sessions \
  -H 'Content-Type: application/json' \
  -d '{"mode":"study","document_id":1,"exam_type":"written","answer_format":"mark"}'
curl -s -X POST http://127.0.0.1:8000/v1/exam-sessions/1/finalize-reading
curl -s 'http://127.0.0.1:8000/v1/exam-sessions/1/review?index=0&view_page=0'
```

`mode="real"` は `ROKID_ALLOW_REAL_EXAM_SOLVE=1` がない限りロックされます。

---

## 撮影インジケータの実機確認

対応フローは撮影インジケータを変更しません。別カメラで、撮影前の消灯、`takePhoto`中の
点灯、成功または失敗callback後の消灯、OCR・解析・閲覧中の消灯を連続記録します。
callbackはアプリ状態の証拠であり、物理消灯の代用にはなりません。安全な観測手順は
[実機準備調査](docs/hardware-measurements.md)を参照してください。

## 実モデル接続（実機の写真解析・解答には必須）

実機の主経路はサーバー側の画像対応 Analyzer/Solver です。各プロバイダポート
（analyzer / solver / explainer / extractor）へ OpenAI、Google Gemini、Anthropic
Claude の実アダプタを同梱しています。使用する1社の SDK と API キーを用意してください。

- 既定の `local` は開発用プレースホルダーです。実機では `ROKID_ANALYZER` と `ROKID_SOLVER` を `openai|gemini|claude` に設定します。
- **`ROKID_SOLVER` を non-local にすると `finalize-reading` がサーバ側で全問一括解答**します。
- APIキーが無い、SDKが無い、プロバイダ呼び出しに失敗した場合はローカル実装へ
  フォールバックします。写真にも端末OCRにも文字が無ければ問題0件として読取状態を維持します。
- 共通クライアントは `app/llm.py`（公式 SDK を遅延 import・注入可能・プロバイダ非依存）。

```bash
pip install openai                           # または google-genai / anthropic
export OPENAI_API_KEY=sk-...                 # Gemini: GOOGLE_API_KEY / Anthropic: ANTHROPIC_API_KEY
export ROKID_SOLVER=openai ROKID_EXPLAINER=openai \
       ROKID_ANALYZER=openai ROKID_EXTRACTOR=openai   # または gemini / claude
# export ROKID_LLM_MODEL=gpt-4o             # 任意上書き（既定: openai gpt-4o /
                                             #  gemini gemini-2.5-flash / anthropic claude-opus-4-8）
uvicorn app.main:app --port 8000
```

| 環境変数 | 既定 | 役割 |
|----------|------|------|
| `ROKID_ANALYZER`/`ROKID_SOLVER`/`ROKID_EXPLAINER`/`ROKID_EXTRACTOR` | `local` | `openai\|gemini\|claude` で実 AI にルーティング（solver は finalize-reading の一括解答も有効化） |
| `OPENAI_API_KEY`/`GOOGLE_API_KEY`/`ANTHROPIC_API_KEY` | （なし） | 実呼び出しに必須。未設定なら該当ポートはローカルへ |
| `ROKID_LLM_MODEL` | openai `gpt-4o` / gemini `gemini-2.5-flash` / anthropic `claude-opus-4-8` | 使用モデル id（任意上書き） |
| `ROKID_LLM_MAX_TOKENS` | `1024` | 応答トークン上限 |
| `ROKID_TRANSCRIBER` | （なし） | リスニング録音の書き起こし `openai\|gemini`（未設定=与えた transcript を使用） |
| `ROKID_TRANSCRIBE_MODEL` | `gpt-4o-transcribe` | openai の書き起こしモデル（gemini は `ROKID_LLM_MODEL`） |
| `ROKID_SOLVER_TIERS` | （単一） | 二段フォールバック順（例 `openai,local`） |
| `ROKID_CHATGPT_CDP` | `http://127.0.0.1:9222` | `ROKID_SOLVER=chatgpt-web` 時に接続する Chrome の DevTools ポート |
| `ROKID_KEYMAP` | （なし） | gesture→KeyCode の上書き（JSON、`/v1/settings.input`。既定 KeyCode は旧機由来・未実測） |
| `ROKID_API_KEY` | （なし） | 設定時に Bearer 認証（発見系は開放） |


### API キー無しの GPT 経路（`ROKID_SOLVER=chatgpt-web`）

サブスクリプションのみで解答させる経路です。サーバがログイン済み Chrome を
DevTools プロトコル経由で操作し、ChatGPT ウェブ UI に問題文を入力して返答を
読み取ります。撮影 → OCR → 解答 → HUD までスマホの手動操作は不要です。

```bash
pip install playwright            # `playwright install` は不要（実 Chrome に接続）
# 専用プロファイルで Chrome を起動し、そこで ChatGPT に一度ログインしておく
chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\chrome-rokid-profile"

export ROKID_SOLVER=chatgpt-web
py -3.12 -m app.solvers.chatgpt_web   # ライブ確認（セレクタが現行 UI に合うか）
py -3.12 -m app.solvers.chatgpt_web "図の角度を求めよ" data/images/p01.png  # 画像経路も
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

実測値（Chrome 152.0.7977.83 / 2026-09-13）と注意点:

- **起動中の Chrome に `--remote-debugging-port` を付けても無効です。** 既存
  セッションにタブが開くだけでポートは開きません（`既存のブラウザ セッションで
  開いています` と出て終了）。必ず**専用の `--user-data-dir`** を使います。
- **ログアウト状態では別 DOM が出ます。** `lightweight-shell` というプレース
  ホルダーで、composer も `data-testid` も存在しません。専用プロファイルで
  一度ログインする必要があります（毎問の手動操作は不要）。
- **実機検証済み**（2026-09-13、ログイン済みセッション）。1問あたり実測
  **テキストのみ 7.58秒 / 画像付き 8.98秒**。内訳は遷移+composer 2.0秒、
  添付 0.11秒、残りが生成時間です。ブラウザ接続自体は 0.61秒
  （playwright 0.23 / CDP 0.03 / 遷移 0.28）で律速ではないため、接続プールは
  作っていません。
- 画像到達は、角度が**画像にしか無い**三角形で検証しました（本文は「図の角 x
  の大きさを求めよ」のみ）。解答 `70°` で正答し、図が OCR を経ずにモデルへ
  届いていることを確認しています。
- **大問が複数ページにまたがる場合は全ページを添付します**（`Question.image_paths`）。
  条件をページ1に、図をページ2に置いた2ページ問題で検証: 1枚のみだと
  `needs_input`（「角a、角bの大きさが不足」）、2枚で `70度` と正答しました。
  ページは1回の `set_input_files` で送るため読み順が保たれます。全ページの
  サムネイルが揃って初めて `image_attached` が true になります。
- 応答完了は `stop-button` の消滅で判定します。**このボタンは思考フェーズを
  含む生成中ずっと存在する**ため、表示されている間は何も確定しません。推論
  モデルは「思考中」を1秒以上静止表示するので、テキスト安定判定だけだと長文
  5問中4問でこれを解答として確定していました。安定判定はセレクタ消失時の
  フォールバックに限定しています。
- 本文の長さは **34,205字まで欠落なし**を実測（末尾に置いた合言葉が全長で
  返る）。`composer.fill()` は1回で全量を入れるため途中送信も起きません。
- 連続実行はflakeします（16問連続でアップロード未確認1件、composer操作
  不能1件）。`ROKID_CHATGPT_ATTEMPTS`（既定3）で新しいチャットを開いて
  再試行します。**添付が未確認の場合も再試行対象**です — 図なしで送ると
  エラーにならず、誤答か `needs_input` になるためです。ただし再試行の判定は
  **送信前**に行うため、サムネイル未確認は生成回数を消費しません（旧実装は
  送信済みの解答を捨てて再質問しており、1問あたり最大3生成でした）。
- **使用制限への防御**（2026-09-14 にアカウントが制限された経験から）:
  - 返答が使用制限の通知だった場合は `ChatGptWebRateLimit` で即座に打ち切り、
    再試行しません（新しいチャットを開いて再質問するのが悪化の原因でした）。
    検出語は `ROKID_CHATGPT_RATE_LIMIT_MARKERS`（`|` 区切り）で変更できます。
  - 生成時間が `ROKID_CHATGPT_SLOW_S`（既定40秒）を超えた回が
    `ROKID_CHATGPT_SLOW_STREAK`（既定2）回続くと、次の送信を拒否します。
    実測のスロットリング兆候は「正常 7-13秒 → 43秒 → 48秒 → 130秒 → ブロック」
    でした。`ROKID_CHATGPT_SLOW_STREAK=0` で無効化できます。
- **教科ごとに1チャット**（任意、既定は問題ごと）: `ROKID_CHATGPT_CHAT_SCOPE=subject`
  で1科目が1チャットを共有します。全教科デックでチャット数が小問数から教科数に
  減り、同じ大問のページは**その科目で1回だけ**アップロードされます（同一バイト
  列を SHA-256 で判定）。代償は、同じ科目の前問の解答が文脈に残ることです。
  既定の `question` は測定済みの挙動（1問1チャット）を維持します。
- **リスニング音声は資料と同じメッセージに添付されます。** `Question.audio_path`
  が録音ファイルを運び、写真用 input は `accept="image/*"` のため
  `ROKID_CHATGPT_FILE_UPLOAD_SEL`（汎用ファイル input）から送ります。文字起こしは
  従来どおり本文に入るため、音声が読めない場合も解答は失われません。音声も
  チャット内で重複アップロードしません。
- **複数ページを1つの PDF にまとめて送る**（任意、既定オフ）:
  `ROKID_CHATGPT_BUNDLE_PDF=1` で大問の全ページを1つの PDF にして
  `ROKID_CHATGPT_FILE_UPLOAD_SEL`（既定 `input[data-testid="upload-files-input"]`）
  から送ります。アップロード回数が1回になりますが、**実ページでは未検証**
  です（制限中に実装したため）。図がPDF経路でも読めるかを1問で確認してから
  使ってください。画像1枚ずつの経路のみが実測済みです。

注意点:

- **ChatGPT ウェブ UI の自動操作は OpenAI の利用規約に反します。** アカウント
  停止のリスクを負う経路で、API 経路にはこのリスクはありません。
- ページ構造は OpenAI のもので予告なく変わります。壊れた場合は
  `ROKID_CHATGPT_COMPOSER_SEL` / `ROKID_CHATGPT_ASSISTANT_SEL` を再設定します
  （コード変更は不要）。`py -3.12 -m app.solvers.chatgpt_web` が切り分け用です。
- **画像とテキストは別パートとして送られます。** ページ画像を添付し、OCR
  テキストを本文に入力するため、図・グラフ・数式は OCR を経ずに渡ります
  （API solver と同じ扱い）。添付が確認できたかは解答の
  `extras["image_attached"]` に記録されます。画像経路の確認は
  `py -3.12 -m app.solvers.chatgpt_web "<問題文>" <画像パス>`。

#### スマホの ChatGPT で解く経路（PC の Chrome を使わない）

PC を立ち上げずにスマホだけで回す場合は、自動操作ではなく**貼り付け経路**を
使います。サーバは解答を受け取らないため HUD は駆動されません（手元で読む
運用）。

```bash
# 1問ごと: 貼り付け用の本文と ChatGPT の事前入力リンク
curl "$BASE/v1/exam-sessions/$SID/paste-prompt"
# -> {"text": "...", "url": "https://chatgpt.com/?q=...",
#     "pages_pdf_url": "/v1/exam-sessions/$SID/pages.pdf", ...}

# セッション中1回: 撮影した全ページを1つの PDF で取得し、チャットに添付
curl -o pages.pdf "$BASE/v1/exam-sessions/$SID/pages.pdf"
```

- 写真を1枚ずつ手で添付する作業が実運用で破綻する部分なので、**資料は1
  ファイル**にまとめます。ページは撮影順（reading order）で並びます。
- 画像を持たないページ（テキストのみ取り込み）は含めません。全ページが
  テキストのみなら 404 を返します（空の PDF は「図を送った」と誤読されます）。
- この経路では OCR 本文が `text`、図は PDF 添付という分担になります。図が
  PDF 経由でどこまで読めるかは**未検証**です。
- Chrome が未起動・未ログインなら `answer_only` はプレースホルダーに落ちず
  明示的に失敗します。

全変数の雛形は [`.env.example`](.env.example)、一覧は
[user-operation-guide.md](docs/user-operation-guide.md) §7 を参照。

OpenAI書き起こしへ直接送る形式はWAV/MP3/MPEG/MPGA/M4A/MP4/WebMです。
OGG/FLACは保存できますが、変換なしではOpenAIへ送信しません。
raw ADTS/ADIF AACと識別できない音声データは保存できますがOpenAIへは送信せず、
与えられた transcript へフォールバックします。先頭にID3v2タグがあっても、タグ後の
実コンテナを判定します。

### 実機運用（グラス連携・入力・認証）

実機のCUSTOMVIEW closeと`AI-exit`はoperator入力として扱わず、スマホを操作面にします。
専用シャッターボタン、旧KeyCode、全タッチジェスチャ表も現行リレーの入力契約ではありません。
認証、Windows Firewall、APK導入、回転調整、LED/HUD合格条件は
[Windows + Android 実機手順](docs/windows-android-real-device-setup.md) に集約しています。

## Docker（任意）

```bash
docker compose up --build
# http://127.0.0.1:8000/health
```

Compose の既定ポートは安全のためホストの `127.0.0.1` だけに公開されます。
グラスから同一 LAN 経由で接続する場合は、明示的に公開先を切り替えます:

```bash
ROKID_BIND_HOST=0.0.0.0 ROKID_API_KEY='十分に長いランダム値' \
  docker compose up --build
```

LAN・インターネット公開では `ROKID_API_KEY` に加え、必ず TLS 対応の
リバースプロキシを設定してください。Compose は `.env` のサービス向け `ROKID_*`／
プロバイダ変数をコンテナへ渡し、`ROKID_BIND_HOST` はポート公開先の補間に使います。

ローカル Python 実行を優先してください。Docker は任意です。

## 制限事項

- Androidのbundled Japanese ML Kitを一次OCRに使います。画像対応Analyzerを設定すると
  サーバー側でも元写真から転記・図表説明を補完します。テキスト照合は完全一致ではなく類似度
  （`difflib`）で段階加点するため、多少のOCRノイズには強い。
- pHash は純 Python 実装（numpy/imagehash 非依存）で、大量ページでは低速。
  高速化は scipy/imagehash 等への置換が定石（依存を増やすため既定では未採用）。
- マルチテナントと一般的な多重書き込み制御は未実装（簡易 Bearer 認証は
  `ROKID_API_KEY` で任意）。同一問題の solver と同一ページ訪問の explainer は
  DB claim により、同時要求でも有料プロバイダを重複呼び出ししません。
- 実 AI アダプタは任意依存（`anthropic`/`openai`/`google-genai`）と各社 API キーが必要。
  未設定なら自動でローカル実装にフォールバック（実 AI 出力は得られません）。

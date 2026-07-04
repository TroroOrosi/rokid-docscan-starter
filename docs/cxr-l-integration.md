# CXR-L グラス単体ネイティブアプリ ⇄ 本サーバ 連携ガイド

このドキュメントは、**Rokid Glasses 本体で動く CXR-L ネイティブアプリ**を作り、
**グラス本体の AI（YodaOS-Sprite の AI アプリサービス）** を本リポジトリのサーバに
接続するための設計をまとめたものです。

> ⚠️ 本ドキュメントの公式仕様は、md 内の記述ではなく **ウェブ検索で確認した Rokid 公式
> / コミュニティ最新情報** に基づいています（末尾「出典」）。Maven 座標・AIDL・パッケージ名・
> 端末仕様は情報源に基づく最新値ですが、SDK バージョンは更新されるため、実装前に
> `ar.rokid.com/sdk` の最新版で必ず突き合わせてください。

---

## 1. Rokid Glasses 本体仕様（実行前提・ウェブ検証済み）

| 項目 | 値 |
|------|----|
| 重量 | 約 49 g |
| ディスプレイ | **両眼（binocular）** モノクロ緑 Micro-LED＋回折光導波路、**480×398 / 眼**、最大 1500 nits、FOV 約 23°（一部レビューは 30° と記載） |
| SoC | Qualcomm Snapdragon **AR1 (Gen 1)** ＋ 副チップ **NXP RT600**（音声認識・低消費電力） |
| メモリ / ストレージ | **2 GB RAM / 32 GB ROM** |
| カメラ | **12MP Sony IMX681**（f/2.25、最大 3024×4032、FOV 109°） |
| バッテリ | 本体 210 mAh（ケース 3000 mAh・約10回充電、80% 20分の急速充電） |
| 接続 | **Wi-Fi 6 / Bluetooth 5.3** |
| OS | **YodaOS（YodaOS-Sprite）**＝ Android 12 ベース、**API level 32**、Qualcomm QSSI 構成 |

> リポジトリ内の一部旧 md には「右眼のみ」等の記述がありましたが、公式・複数レビューで
> **両眼ディスプレイ**であることを確認済みです。本サーバは表示技術に依存しない
> HTTP 契約（最大3行 HUD）のみを提供するため、片眼/両眼いずれでも動作します。

---

## 2. CXR（Connected XR）SDK スイート（ウェブ検証済み）

| SDK | 動作場所 | 役割 | Maven（要最新確認） | min/target SDK |
|-----|----------|------|---------------------|----------------|
| **CXR-M** | スマホ（Android/iOS） | コンパニオンアプリ用。デバイス接続（BLE GATT＋Classic BT ソケット＋Wi-Fi Direct）、ハードウェア情報、YodaOS-Sprite の AI 連携、アシストサービス（ファイル転送・録音・写真取得） | `com.rokid.cxr:client-m:1.0.8` | minSdk 28（Android 9） |
| **CXR-S** | グラス本体（YodaOS-Sprite） | 機上アプリ用ブリッジ。CXR-M と Caps バイナリ形式で双方向メッセージング | `com.rokid.cxr:cxr-service-bridge:1.0-SNAPSHOT` | — |
| **CXR-L** | グラス本体（YodaOS-Sprite） | **標準アプリを置き換える単体（ランチャー型）アプリ用**。エントリ実クラス **`CXRLink(context)`** が `ExternalAppClient` を継承し、**Android AIDL で `IMediaStreamService` にバインド**してメディアストリーム＆**AI アプリ連携**を行う。対象 AI サービス＝ **`com.rokid.sprite.aiapp`**（「Hi Rokid」AI アプリ。グローバル版 `com.rokid.sprite.global.aiapp`） | `com.rokid.cxr:client-l:0.0.1` | min/target 28 |

> Maven リポジトリ: `https://maven.rokid.com/repository/maven-public/`。
> CXR-L（`client-l:0.0.1`, ~28KB AAR）の主な依存は Kotlin stdlib 2.1.0 / Gson 2.10.1。
> 座標・依存はバージョン更新されるため、実装前に上記リポジトリで最新を確認してください。

- **Rizon / Agent Store**: Rokid が Coze Studio ベースで独自化した AI オープンプラットフォーム。
  ノーコードで AI ワークフローを作成・共有でき、Agent Store には多数のワークフローが公開。
  Rokid Glasses は **Google Gemini／ChatGPT／DeepSeek／Qwen** をネイティブ対応。

---

## 3. 本リポジトリでの位置づけ（3層構成）

```
[Rokid Glasses 本体]                                   [本サーバ (このリポジトリ)]
  ┌───────────────────────────────┐                     ┌──────────────────────────┐
  │ CXR-L ネイティブアプリ         │                     │ FastAPI (/v1/...)         │
  │  - ExternalAppClient           │                     │  - 文書/ページ照合        │
  │  - IMediaStreamService(AIDL)   │  ── HTTPS ──▶       │  - 解答/解説              │
  │  - com.rokid.sprite.aiapp 連携 │  (Wi-Fi 6 直結)     │  - claude アダプタで実AI  │
  │  - HUD 描画（最大3行）         │  ◀── JSON ──        │    へ橋渡し(任意)          │
  └───────────────────────────────┘                     └──────────────────────────┘
```

- CXR-L アプリは **グラス単体で完結**（スマホのコンパニオン不要。Wi-Fi 6 でサーバへ直結）。
- **グラス本体の AI（`com.rokid.sprite.aiapp`）** は AIDL 経由で音声・カメラ・AI 応答を扱う。
  CXR-L アプリはそのサービスにバインドしつつ、**構造化された解析/解答/解説はこのサーバに委譲**する。
- サーバは表示技術・SDK 世代に依存しない **HTTP 契約**（最大3行 HUD）だけを公開する。

---

## 4. 「グラス本体 AI」をサーバに繋ぐ2経路（B が主経路）

本サーバは 2 通りの繋ぎ方を想定している。どちらも同じ HTTP 契約なのでサーバ側は不変。
**exam の解答は経路 B（本体 AI＝搭載 GPT / Gemini）が主経路**で、経路 A（サーバ側実 AI）は
より高性能なモデルが必要な場合の任意経路。**Claude はグラス搭載 AI ではない**（搭載ネイティブは
Gemini / ChatGPT / DeepSeek / Qwen）。

### 経路 B（主経路）: グラス本体 AI（`com.rokid.sprite.aiapp` の AI Interaction）が読取・解答する

CXR-L アプリは AIDL で **本体 AI サービスの AI Interaction**（YodaOS-Sprite / Rizon が
定義する AI・AI ワークフロー。**Gemini / ChatGPT / DeepSeek / Qwen をネイティブ対応**）を
呼び出せる。そこで得た認識結果・AI 応答を本サーバへ渡す。
**この経路ではサーバ側のクラウド鍵は不要**（本体 AI がモデルを担う）。
CXR-M（スマホ）の AI Interaction からも同様に利用できる。

- **読取**：本体 AI の認識テキストを `POST /v1/documents/{id}/pages` の
  **`ocr_text` / `vision_text`** として渡す（照合用途は `fast_ocr_text`）。
- **解答（3 フェーズの主経路）**：`finalize-reading` 後、**本体 GPT が全問を解き**、問題別解答を
  **`POST /v1/exam-sessions/{id}/solutions`** に ingest する（`served_by="onboard"`）。
  サーバは分割・整形・状態管理と閲覧 HUD（`GET /review`）を担う。

**撮影しない・図も読む**：本体 AI は**視認＝認識**であり写真を撮らない。図・グラフ・写真の読み取りは
本体 AI のマルチモーダル認識結果を **`vision_text`**（テキスト）として `POST /v1/documents/{id}/pages` に
本文 `ocr_text` と一緒に渡す（**画像バイトは送らない**）。サーバは `ocr_text`＋`vision_text` を1つの材料に統合し、
問題分割（`segment_problems`）と解答文脈（全ページ）に使う（ページ跨ぎ問題に対応）。
視認＝カメラ稼働＝プライバシー LED 点灯のため、**読取フェーズを最短化**し、`finalize-reading`
以降はカメラを閉じる（LED 消灯）。

### 経路 A（任意）: サーバ側の実 AI アダプタ（このリポジトリで実装済み）

より高性能なモデルが必要な場合、サーバ内の各プロバイダポート
（analyzer / solver / explainer / extractor）の
**実アダプタ `openai`（OpenAI GPT）/ `gemini`（Google）/ `claude`（Anthropic）** を
環境変数で有効化する：

```bash
# 例: 解答・解説・要約・メディア抽出をすべて実モデルで
export OPENAI_API_KEY=sk-...                 # Gemini: GOOGLE_API_KEY / Anthropic: ANTHROPIC_API_KEY
export ROKID_SOLVER=openai ROKID_EXPLAINER=openai \
       ROKID_ANALYZER=openai ROKID_EXTRACTOR=openai   # または gemini / claude
export ROKID_LLM_MODEL=<現行のGPTモデルid>    # openai/gemini は現行モデル id を必須指定
pip install openai                            # または google-genai / anthropic
uvicorn app.main:app --port 8000
```

- キー未設定/失敗なら自動的にオフラインのローカル実装へフォールバック（サーバは常に応答）。
- `ROKID_SOLVER` を non-local にすると `finalize-reading` がサーバ側で全問一括解答する。
- 詳細は [README.md](../README.md) の「実モデル接続」節、実機手順は
  [real-device-operation.md](real-device-operation.md) を参照。

---

## 5. CXR-L アプリからの呼び出しマッピング

| グラス側でやること | 使う SDK / AIDL | 送る先エンドポイント | HUD に返るもの |
|--------------------|-----------------|----------------------|----------------|
| ページ視認＝読取（2本指タップ） | `com.rokid.sprite.aiapp`（AI Interaction） | `POST /v1/documents/{id}/pages`（`ocr_text`/`vision_text`） | `scan_ack`（進捗） |
| 読取完了宣言（ダブルタップ） | — | `POST /v1/exam-sessions/{id}/finalize-reading` | `reading_ack`（カメラOFF） |
| 本体 GPT の問題別解答を送る | `com.rokid.sprite.aiapp` | `POST /v1/exam-sessions/{id}/solutions` | `ingest_ack`（N/M問 解答済） |
| 問題別閲覧（2本指スワイプ） | — | `GET /v1/exam-sessions/{id}/review?index=&view_page=` | `glasses_view`（一括1ストリーム） |
| カメラ1フレーム取得（照合時のみ） | `IMediaStreamService`（AIDL） | `POST /v1/match`（画像＋`fast_ocr_text`） | `hud.lines`（3行） |
| 資料の解説（撮影なし） | ページ送りジェスチャ | `POST /v1/explain-sessions/{id}/next-page` → `GET .../explain` | `glasses_view`（overview/detail/evidence） |
| HUD 描画 | CXR-L ディスプレイ API | — | 受信 `lines` をそのまま描画 |

- サーバの描画契約は `GET /v1/settings` の `hud` を唯一の権威ソースとして読む
  （無音・無フラッシュ・即時遷移・低輝度・最大3行）。

---

## 6. 実装チェックリスト（CXR-L アプリ側）

1. Rokid AR Platform（`ar.rokid.com/sdk`）で開発者登録し、**CXR-L SDK** を入手。
2. `ExternalAppClient` を継承したエントリ（実クラス例 `CXRLink`）を作り、`IMediaStreamService` に AIDL バインド。
3. グラス本体 AI サービス `com.rokid.sprite.aiapp` へのバインド権限・Intent を設定。
4. カメラ/音声/OCR 結果を取り出し、本サーバの HTTP API に送信（Wi-Fi 6 直結）。
5. 応答の `hud.lines` / `glasses_view.lines`（最大3行）を HUD に描画。
6. 操作は公式ジェスチャ（2本指タップ/タップ/ダブルタップ/2本指スワイプ/長押し。音声は任意トグル）。KeyCode は §7 参照。

---

## 7. 入力（タッチパッド/ボタン）の KeyCode

サーバは gesture→KeyCode を **`GET /v1/settings` の `input` ブロック**として機械可読に
公示します（`app/glasses_view.py` の `build_input_contract()`。ジェスチャ名は現行公式、
例 `single_tap`=`KEYCODE_DPAD_CENTER`(23) / `long_press`=`KEYCODE_TV`(170)）。CXR-L クライアントは
これを唯一の権威として読み込みます。**ただし KeyCode 値は旧・単眼 Rokid Glass 由来で未実測**
（`keycodes_verified:false`・`keycode_source` 参照）。実機で計測のうえ、機種/ファーム差はサーバ側の
環境変数 **`ROKID_KEYMAP`（JSON）** で上書きしてください（クライアント改修不要）。
計測手順は [real-device-operation.md](real-device-operation.md) §5。

---

## 8. 参照実装（Kotlin 最小スニペット）

> ビルド可能な APK ではなく、CXR-L 上での連携の骨子を示す参照コードです。実際の SDK
> API 名は Rokid の CXR-L SDK ドキュメントに合わせてください。

```kotlin
// 1) CXR-L エントリ: 本体 AI とメディアに AIDL バインド
class DocScanApp(context: Context) : ExternalAppClient(context) {
    // ExternalAppClient が IMediaStreamService（AIDL）へのバインドを担う。
    // 対象 AI サービス: com.rokid.sprite.aiapp（AI Interaction）。
}

// 2) 起動時に /v1/settings を唯一の権威として読み込む（hud/capture/input）
val settings = http.get("$SERVER/v1/settings").json()
val tapKey = settings["input"]["gestures"]["single_tap"]["keycode"].asInt()   // 例: 23（未実測・要計測）

// 3) 経路B（主経路）: 本体 AI（AI Interaction）で読取 → 解答を ingest
val pageText = aiInteraction.recognize(frame)        // 本体AIの認識（視認＝読取。LED点灯中）
http.postMultipart("$SERVER/v1/documents/$docId/pages",
    "page_index" to i, "ocr_text" to pageText.body, "vision_text" to pageText.figures)
// 読取完了（ダブルタップ）→ finalize-reading → 以降カメラOFF（LED消灯）
http.post("$SERVER/v1/exam-sessions/$sid/finalize-reading")
// 本体 GPT が全問を解いた結果を問題別に ingest
http.postJson("$SERVER/v1/exam-sessions/$sid/solutions",
    mapOf("solutions" to onboardAnswers))            // [{problem_no, answer, ...}]

// 4) 受信した最大3行 HUD を両眼ディスプレイに描画（無音・即時置換）
hud.render(resp["hud"]["lines"])                     // hud 契約は settings["hud"] に従う

// 5) 入力: settings.input の KeyCode で操作を判定
override fun onKeyDown(keyCode: Int, e: KeyEvent): Boolean = when (keyCode) {
    tapKey -> { showAnswerOrExplain(); true }
    else   -> super.onKeyDown(keyCode, e)
}
```

- 認証を有効化したサーバへは `Authorization: Bearer <ROKID_API_KEY>` を付与。
- `/v1/settings` は認証不要（発見系）なので、鍵取得前に契約をネゴシエートできる。

---

## 出典（ウェブ検証）

- [Rokid Open Platform（CXR SDK / YodaOS）](https://ar.rokid.com/sdk?lang=en)
- [About YodaOS-Sprite — Rokid AR Platform](https://ar.rokid.com/sprite?lang=en)
- [buildwithfenna/rokid-docs（CXR-M/S/L 詳解・Maven 座標・AIDL・`com.rokid.sprite.aiapp`）](https://github.com/buildwithfenna/rokid-docs)
- [Anezium/awesome-rokid（コミュニティ SDK/ツール集）](https://github.com/Anezium/awesome-rokid)
- [Rokid Glasses 製品ページ（両眼 Micro-LED / 49g 等）](https://global.rokid.com/products/rokid-glasses)
- [NotebookCheck: Rokid Glasses specs（AR1 + NXP RT600 / IMX681 / 210mAh 等）](https://www.notebookcheck.net/Rokid-Glasses-are-lightweight-AR-smart-glasses-with-Micro-LED-displays-and-a-499-price-tag.1098756.0.html)
- [Rokid、Gemini/ChatGPT をネイティブ統合（Rizon / Agent Store）](https://www.prnewswire.com/news-releases/rokid-integrates-googles-gemini-chatgpt-in-major-update-to-international-smart-glasses-in-open-ecosystem-push-302700875.html)

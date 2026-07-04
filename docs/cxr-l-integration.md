# CXR-L（スマホ側プラグイン）⇄ グラス本体 AI ⇄ 本サーバ 連携ガイド

このドキュメントは、**CXR-L SDK（スマホ上で Hi Rokid アプリにバインドするプラグイン型 SDK）**
を使って **グラス本体の AI（YodaOS-Sprite の AI アプリサービス＝搭載 GPT / Gemini）** を
本リポジトリのサーバに接続するための設計と、リモート操作・画面共有の実態（§9）をまとめた
ものです。

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
| **CXR-L** | **スマホ（Hi Rokid アプリのプラグイン型 SDK）** | **実機検証済みの実態**（CxrGlobal / claude-mobile-hud、2026）: エントリ実クラス **`CXRLink(context)`** は**スマホ側**で動き、**同一スマホ内の AIDL** で Hi Rokid アプリ（中国版 `com.rokid.sprite.aiapp`／グローバル版 **`com.rokid.sprite.global.aiapp`**・同一 AIDL 面）の `IMediaStreamService` にバインド。Hi Rokid がグラスとは **CXR-L wire protocol（Caps シリアライズ・Bluetooth 制御プレーン**、native `cxr-sock-proto-jni`）で通信する。セッション種別は **CUSTOMVIEW**（グラス側アプリ不要で HUD 表示: `customViewOpen/Update/Close/SetIcons`）と **CUSTOMAPP**（`appUploadAndInstall`/`appOpen` でグラス側アプリを配布・起動）。ほか `startAudioStream`（マイク PCM 16kHz mono・`IAudioStreamCbk.onAudioReceived`）・`takePhoto`（本リポジトリでは撮影しない方針により不使用）・`sendCustomCmd`・AI キーイベント `onAiKeyDown/onAiKeyUp/onAiExit` | `com.rokid.cxr:client-l:1.0.1` | minSdk 31（実測: Pixel 8 / Hi Rokid global G1.5.9 / YodaOS SPRITE 1.18） |

> Maven リポジトリ: `https://maven.rokid.com/repository/maven-public/`。
> 座標・依存はバージョン更新されるため、実装前に上記リポジトリで最新を確認してください。
>
> ⚠️ **旧記述の是正**: 本 doc の旧版（および一部コミュニティ資料）は CXR-L を「グラス本体で動く
> 単体アプリ SDK（Wi-Fi 6 でサーバ直結・スマホ不要）」と記述していましたが、**公開されている
> 実機動作実績（CxrGlobal / claude-mobile-hud）が示す構成はスマホ側プラグイン**です。グラス側で
> 動くのは CUSTOMAPP モードで配布されるアプリのみで、**Hi Rokid（スマホ）を経由しない CXR-L
> 構成は未確認**です。本サーバの「スマホは HTTP 中継のみ・画面不要」という原則はこの実態と
> 完全に整合します（中継役がスマホの Hi Rokid + プラグインアプリになるだけ）。

- **Rizon / Agent Store**: Rokid が Coze Studio ベースで独自化した AI オープンプラットフォーム。
  ノーコードで AI ワークフローを作成・共有でき、Agent Store には多数のワークフローが公開。
  Rokid Glasses は **Google Gemini／ChatGPT／DeepSeek／Qwen** をネイティブ対応。

---

## 3. 本リポジトリでの位置づけ（実機検証済みの 4 層構成）

```
[Rokid Glasses 本体]      [スマホ]                                  [本サーバ (このリポジトリ)]
 ┌──────────────┐  Caps/BT ┌─────────────────────────────┐          ┌──────────────────────────┐
 │ 搭載 AI(GPT/  │◀───────▶│ Hi Rokid ｱﾌﾟﾘ                │          │ FastAPI (/v1/...)         │
 │ Gemini)・HUD  │  wire    │  (com.rokid.sprite.global.   │          │  - 文書/問題分割/デッキ    │
 │ ・ｶﾒﾗ・ﾏｲｸ    │  protocol│   aiapp, IMediaStreamService)│          │  - 解答 ingest/解説/照合  │
 └──────────────┘          │      ▲ AIDL(同一端末内)      │  HTTPS   │  - openai|gemini|claude   │
                           │ CXR-L ﾌﾟﾗｸﾞｲﾝｱﾌﾟﾘ(CXRLink)   │ ───────▶ │    ｱﾀﾞﾌﾟﾀ(任意)           │
                           │  = HTTP 中継・画面不要        │ ◀─ JSON  └──────────────────────────┘
                           └─────────────────────────────┘
```

- **スマホは HTTP 中継のみ（画面不要）**: CXR-L プラグインアプリが Hi Rokid 経由でグラスの
  HUD 表示（CUSTOMVIEW）・ジェスチャ/AI キーイベント・マイク音声を扱い、本サーバの HTTP 契約に
  橋渡しする。ユーザーが見る・操作するのはグラスだけ。
- **グラス搭載 AI（GPT / Gemini ネイティブ）** が視認＝認識と解答を担い（経路 B・主経路）、
  **構造化された分割・取り込み・整形・状態管理はこのサーバに委譲**する。
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

1. Rokid AR Platform（`ar.rokid.com/sdk`）で開発者登録し、**CXR-L SDK** を入手
   （グローバル利用は CxrGlobal ラッパーが実機実績あり）。
2. スマホ側プラグインアプリで `CXRLink(context)` を作り、Hi Rokid の認可
   （`AuthorizationHelper` → token → `connect(token)`）を経て `IMediaStreamService` に AIDL バインド。
3. Hi Rokid（グローバル版 `com.rokid.sprite.global.aiapp`）へのバインド権限・Intent を設定し、
   CUSTOMVIEW セッションを開く（グラス側アプリは不要。必要なら CUSTOMAPP で配布）。
4. カメラ/音声/OCR 結果を取り出し、スマホ側プラグインから本サーバの HTTP API に送信。
5. 応答の `hud.lines` / `glasses_view.lines`（最大3行）を HUD に描画。
6. 操作は公式ジェスチャ（2本指タップ/タップ/ダブルタップ/2本指スワイプ/長押し。音声は任意トグル）。KeyCode は §7 参照。

---

## 7. 入力（タッチパッド/ボタン）の KeyCode と実イベント経路

サーバは gesture→KeyCode を **`GET /v1/settings` の `input` ブロック**として機械可読に
公示します（`app/glasses_view.py` の `build_input_contract()`。ジェスチャ名は現行公式、
例 `single_tap`=`KEYCODE_DPAD_CENTER`(23) / `long_press`=`KEYCODE_TV`(170)）。CXR-L クライアントは
これを唯一の権威として読み込みます。**ただし KeyCode 値は旧・単眼 Rokid Glass 由来で未実測**
（`keycodes_verified:false`・`keycode_source` 参照）。実機で計測のうえ、機種/ファーム差はサーバ側の
環境変数 **`ROKID_KEYMAP`（JSON）** で上書きしてください（クライアント改修不要）。
計測手順は [real-device-operation.md](real-device-operation.md) §5。

> **実イベント経路（実機検証済みの補強情報）**: スマホ側プラグイン構成では、AI 起動
> （2本指タップ）はグラス→Hi Rokid→AIDL コールバック **`onAiKeyDown` / `onAiKeyUp` /
> `onAiExit`**（CxrGlobal は `onGlassAiAssistStart/Stop` に集約）としてスマホに届き、
> タッチジェスチャも CXR-L プラグインのイベントとして受けます——**Android KeyCode では
> ありません**。旧 KeyCode 表が関係し得るのは **CUSTOMAPP（グラス側アプリ）を書く場合のみ**で、
> それも未検証です（`keycodes_verified:false` の実証的裏付け）。

---

## 8. 参照実装（Kotlin 最小スニペット・スマホ側プラグイン）

> ビルド可能な APK ではなく、連携の骨子を示す参照コードです。実際の API 名は
> CxrGlobal（実機検証済みラッパー）と Rokid の最新 SDK ドキュメントに合わせてください。

```kotlin
// 1) スマホ側: Hi Rokid の認可を取り、CXR-L（AIDL）に接続（CxrGlobal パターン）
val auth = AuthorizationHelper.requestAuthorization(activity)   // Hi Rokid の AuthorizationActivity
val link = CXRLink(context)
link.connect(auth.token)                 // bindService + コールバック登録
link.openCustomView()                    // CUSTOMVIEW: グラス側アプリ不要で HUD 表示

// 2) 起動時に /v1/settings を唯一の権威として読み込む（hud/capture/operations/input）
val settings = http.get("$SERVER/v1/settings").json()

// 3) 経路B（主経路）: 本体 AI の認識で読取 → 解答を ingest
//    AI 起動（2本指タップ）は onAiKeyDown/Up（onGlassAiAssistStart/Stop）で届く
val pageText = onboardAi.latestRecognition()         // 本体AIの認識（視認＝読取。LED点灯中）
http.postMultipart("$SERVER/v1/documents/$docId/pages",
    "page_index" to i, "ocr_text" to pageText.body, "vision_text" to pageText.figures)
// 読取完了（ダブルタップ）→ finalize-reading → 以降カメラOFF（LED消灯）
http.post("$SERVER/v1/exam-sessions/$sid/finalize-reading")
// 本体 GPT が全問を解いた結果を問題別に ingest（デッキ index 指名が確実）
http.postJson("$SERVER/v1/exam-sessions/$sid/solutions",
    mapOf("solutions" to onboardAnswers))            // [{problem_no, problem_index?, answer, ...}]

// 4) 受信した最大3行 HUD を CUSTOMVIEW でグラスに描画（無音・即時置換）
link.customViewUpdate(render(resp["glasses_view"]["lines"]))   // hud 契約は settings["hud"] に従う

// 5) リスニング: グラスのマイクを PCM 16kHz mono でストリーム受信 → /audio へ
link.startAudioStream { data, offset, length -> recorder.append(data, offset, length) }
```

- 認証を有効化したサーバへは `Authorization: Bearer <ROKID_API_KEY>` を付与。
- `/v1/settings` は認証不要（発見系）なので、鍵取得前に契約をネゴシエートできる。

---

## 9. リモート操作・画面共有の実態と応用（ウェブ調査 2026-07）

### 9-1. 実機で動いている先行事例（リモート操作）

- **claude-mobile-hud**（Qiita 記事「Claude Code を Phone と Glass からリモート操作」の実装）:
  PC（Ubuntu）の Claude Code を Phone＋Rokid Glasses から操作する構成。PC 側に
  **Hub**（常駐デーモン・Phone へ単一の HTTP/SSE エンドポイント）と **Bridge**（Claude
  セッション毎に 1 つの MCP サーバ・双方向プッシュは MCP の Channels）を置き、
  **Glass は必ず Phone 経由（CXR-L・Bluetooth）**で接続。返信・承認要求は両端末へ同時配信され、
  承認/追加指示はテキスト・音声で送れる。**グラスのマイク音声は Phone 経由で OpenAI Realtime
  API (WSS) に流れ、リアルタイム文字起こし**される。SDK は中国市場向け CXR-L を国際利用向けに
  切り出した **CxrGlobal** を使用。
- **Rokid_Claude**: 自宅 Mac の Claude Code をグラスから音声操作（whisper.cpp・WebSocket
  リレー・進捗を HUD にストリーム・グラス上で許可確認）。
- **rokid-browser**: スマホをトラックパッドにして、グラス上のブラウザを Bluetooth 操作。
- **rokid-glasses-control**: ADB + scrcpy で PC から**グラス側画面**を表示・操作（開発用）。
- グラス側にはシステムアプリ **`RokidScreenRecord`（`com.rokid.os.master.screenstream`）**＝
  broadcast intent による画面録画/配信が存在（グラス→外部の画面ストリーム）。

### 9-2. 「画面共有」の実態整理

- 公式の**ピクセル・ミラーリング**（スマホ/PC 画面をグラスに映す）は **Rokid Max 系
  （USB-C DisplayPort 接続のビューアグラス）の機能**。カメラ型 AI グラス（本対象機）の HUD は
  **480×398 モノクロ緑**であり、スマホ画面のピクセル共有は視認性の面で実用外。
- AI グラスで実用になる「共有」は**テキスト・リレー**（公式テレプロンプター機能と同型）:
  スマホ側 AI の回答**テキスト**を HUD に送る（コミュニティ実装 **AssistBridge** = スマホの
  Gemini/Google アシスタント回答を Rokid HUD にリレー、が同パターン）。
  **本サーバの 3 行テレプロンプター契約（`glasses_view.lines`）はまさにこの形式**であり、
  CUSTOMVIEW（`customViewUpdate`）にそのまま流せる。

### 9-3. 応用評価: 「スマホを遠隔操作して AI を使わせ、結果をグラスに共有」

ユーザー案（遠隔操作したスマホ上の AI アプリに解かせ、その画面/結果をグラスへ共有）は、
**本サーバの既存契約に完全適合する「第 3 の解答経路」**として成立する:

```
[遠隔 PC/自動化] ──(scrcpy/ADB or AccessibilityService)──▶ [スマホの AI アプリ(GPT 等)]
       │  回答テキストを抽出（画面のピクセルではなくテキストを運ぶ）
       ▼
POST /v1/exam-sessions/{id}/solutions（ingest・served_by は任意の識別子）
       ▼
GET /solutions → GET /review → CUSTOMVIEW で HUD 閲覧（テキスト・リレー）
```

- 搭載 AI の出力を直接取り出せない場合の**代替経路**として有効。claude-mobile-hud の
  Hub/Bridge（HTTP/SSE リレー）構成が、そのまま「遠隔操作側と本サーバをつなぐ足場」になる。
- **注意**: 遠隔操作は**自分が所有・管理する端末**に限る（scrcpy/AccessibilityService の利用
  規約・法令順守）。用途は**学習・模試のみ**——`mode=real` ロックは ingest・デッキ・閲覧にも
  適用され、この経路でも不変。**LED 原則も不変**（読取フェーズ以外はカメラ OFF）。
- 画面ピクセルの共有（ミラーリング）は上記のとおり実用外のため実装しない。

---

## 出典（ウェブ検証）

- [Rokid Open Platform（CXR SDK / YodaOS）](https://ar.rokid.com/sdk?lang=en)
- [About YodaOS-Sprite — Rokid AR Platform](https://ar.rokid.com/sprite?lang=en)
- [buildwithfenna/rokid-docs（CXR-M/S/L 詳解・Maven 座標・AIDL・`RokidScreenRecord`）](https://github.com/buildwithfenna/rokid-docs)
- [TakanariShimbo/CxrGlobal（CXR-L のグローバル化ラッパー・実機検証済み・AIDL/認可/CUSTOMVIEW 詳細）](https://github.com/TakanariShimbo/CxrGlobal)
- [TakanariShimbo/claude-mobile-hud（Phone+Glass から Claude Code をリモート操作・Hub/Bridge/Realtime 転写）](https://github.com/TakanariShimbo/claude-mobile-hud)
- [Qiita: Claude Code を Phone と Glass からリモート操作（hmkc1220）](https://qiita.com/hmkc1220/items/e47ecd3ab60dded030cf)
- [williamlzz/Rokid_Claude（グラスから Claude Code を音声操作）](https://github.com/williamlzz/Rokid_Claude)
- [Anezium/AssistBridge（スマホ AI の回答を Rokid HUD へテキスト・リレー）](https://github.com/Anezium/AssistBridge)
- [Anezium/awesome-rokid（コミュニティ SDK/ツール集）](https://github.com/Anezium/awesome-rokid)
- [Rokid Glasses 製品ページ（両眼 Micro-LED / 49g 等）](https://global.rokid.com/products/rokid-glasses)
- [Rokid Japan（テレプロンプター等の公式機能）](https://jp.rokid.com/)
- [NotebookCheck: Rokid Glasses specs（AR1 + NXP RT600 / IMX681 / 210mAh 等）](https://www.notebookcheck.net/Rokid-Glasses-are-lightweight-AR-smart-glasses-with-Micro-LED-displays-and-a-499-price-tag.1098756.0.html)
- [Rokid、Gemini/ChatGPT をネイティブ統合（Rizon / Agent Store）](https://www.prnewswire.com/news-releases/rokid-integrates-googles-gemini-chatgpt-in-major-update-to-international-smart-glasses-in-open-ecosystem-push-302700875.html)

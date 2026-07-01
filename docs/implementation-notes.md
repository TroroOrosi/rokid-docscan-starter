# 実装メモ — 実機 Rokid 連携の差し込み箇所

このリポジトリは **サーバ側** を実装します。既定ではオフライン・クレデンシャル不要で
動きますが、各プロバイダポート（analyzer / solver / explainer / extractor）には
**実モデル（Anthropic Claude）アダプタ `claude` を同梱済み**で、環境変数だけで
実運用に切り替えられます（§8）。本ドキュメントは、実機・実 SDK・実 AI を接続する際に
**どこへ何を差し込むか** を整理したものです。

最終更新時点（2026-07）の Rokid エコシステム調査（**ウェブ検索による公式/コミュニティ
最新情報**）を反映しています。末尾の「出典」を参照してください。
グラス本体アプリ（CXR-L）とグラス本体 AI の接続は
[cxr-l-integration.md](cxr-l-integration.md) を参照。

---

## 1. 全体アーキテクチャと差し込み点

```
[Rokid Glasses]──BLE/Wi-Fi──[Android/iOS コンパニオン]──HTTPS──[本サーバ]
   カメラ/HUD          撮影・端末OCR・接続管理・UI          登録/照合/要約
   (CXR-S: 機上)        (CXR-M SDK / Glimmer 等)            (本リポジトリ)
```

本リポジトリが担うのは右端のサーバのみ。左2層を実機に置き換える際の対応表:

| 抽象点（サーバ内） | 既定（オフライン） | 実機/実 AI での差し込み先 |
|------------------|------------------------|---------------------|
| 画像入力 | `/pages`・`/match` の multipart 画像 | グラスのカメラフレーム（CXR-L の `IMediaStreamService`・AIDL） |
| 端末 OCR | `ocr_text` / `fast_ocr_text` フォーム値 | 本体 AI（`com.rokid.sprite.aiapp`）/ Android ML Kit / iOS Vision |
| HUD 出力 | `app/hud.py`・`app/glasses_view.py` の3行ペイロード | グラス両眼ディスプレイ描画（CXR-L） |
| 接続管理 | なし（HTTP のみ） | CXR-L 単体＋Wi-Fi 直結、または CXR-M コンパニオン経由 |
| 要約 | `app/analyzers/local_placeholder.py`（先頭行） | **`ROKID_ANALYZER=claude`（同梱の実アダプタ）** / Rizon ワークフロー |
| 解答 | `app/solvers/local_placeholder.py`（非解答） | **`ROKID_SOLVER=claude`（同梱の実アダプタ）** |
| 解説 | `app/explainers/local_placeholder.py` | **`ROKID_EXPLAINER=claude`（同梱の実アダプタ）** |
| メディア抽出 | `app/extractors/local_placeholder.py` | **`ROKID_EXTRACTOR=claude`（同梱の実アダプタ）** |

サーバ側で実機を意識する必要があるのは、**画像とOCRテキストの入口**
（`app/main.py` の `add_page` / `match_page`）と、**HUD の出口**
（`app/hud.py`）の2箇所だけです。照合ロジック（`app/matching.py`）は
ハードウェア非依存のまま再利用できます。

---

## 2. 公式 Rokid Glasses SDK（2026-07 ウェブ検証時点）

CXR（Connected XR）SDK スイートは役割別に分かれている（末尾「出典」で確認）:

- **CXR-M SDK（Android / iOS）**: スマホ側コンパニオンアプリ用 SDK。
  デバイス接続（BLE GATT＋Classic BT ソケット＋Wi-Fi Direct）、ハードウェア情報、
  YodaOS-Sprite の AI 連携、アシストサービス（ファイル転送・録音・写真取得）を担う。
  Maven `com.rokid.cxr:client-m:1.0.8`、minSdk 28（Android 9）。**iOS パス**も含む。
- **CXR-S SDK**: グラス本体（YodaOS-Sprite）上で動くアプリ用のブリッジ SDK。
  CXR-M と Caps バイナリ形式で双方向メッセージング。
  Maven `com.rokid.cxr:cxr-service-bridge:1.0-SNAPSHOT`。本サーバでは `capture_device`
  フィールド（例 `"CXR-S"`）としてメタデータに記録するのみ。
- **CXR-L SDK**: **標準アプリを置き換える単体（ランチャー型）アプリ用**。
  エントリは `ExternalAppClient` を継承し、**Android AIDL で `IMediaStreamService`
  にバインド**してメディアストリーム＆**AI アプリ連携**を行う。対象 AI サービスは
  **`com.rokid.sprite.aiapp`**（「Hi Rokid」AI アプリ）。Maven
  `com.rokid.cxr:client-l:0.0.1`、min/target SDK 28。**グラス本体 AI を本サーバに
  繋ぐ主経路**であり、詳細は [cxr-l-integration.md](cxr-l-integration.md) を参照。
- **差し込み手順（CXR-L 単体アプリ例）**:
  1. `ExternalAppClient` を継承し `IMediaStreamService` に AIDL バインド。
  2. カメラフレーム／本体 AI（`com.rokid.sprite.aiapp`）の OCR/認識結果を取得。
  3. フレーム JPEG/PNG + OCR テキストを `POST /v1/match` 等に送信（Wi-Fi 6 直結）。
  4. レスポンスの `hud.lines`（3行）をディスプレイ API で描画。

---

## 3. Rizon / Agent Store（要約・エージェント連携）

- **Rizon** は Coze Studio をベースに Rokid がカスタムした AI オープン
  プラットフォーム。ノーコードで AI ワークフローを構築・共有できる。
- **Agent Store** には多数のエージェントワークフローが公開されており、
  国際展開も進行中。
- **差し込み先**: `app/analyzers/`（`summarize.py` は互換シム）。既定はローカルの
  先頭行要約だが、**`ROKID_ANALYZER=claude`（同梱の実アダプタ、§8）** で実モデル要約に
  切り替わる。Rizon ワークフロー（または Gemini / GPT / Qwen / DeepSeek）を使いたい
  場合も、同じ `Analyzer` ポートにアダプタを1つ足すだけ（エンドポイント不変）。

---

## 4. 非公式 / コミュニティ経路

- **RokidBrew（非公式）**: 公式 SDK を介さず実機にアクセスするコミュニティ
  プロジェクト群（`awesome-rokid` に集約）。公式 SDK が使えない検証段階や、
  公式が露出しない低レベル機能を試す際の経路。サーバ側 API は不変のまま、
  クライアント実装だけ RokidBrew 経由に差し替えられる（HTTP 契約は同じ）。
- 採用判断: プロダクションは公式 CXR-L SDK を基本とし、RokidBrew は
  プロトタイピング／調査用途に限定するのが安全。

---

## 5. jlink-ai 風の接続抽象

- コンパニオンアプリ側で、グラスとの接続（BLE/Wi-Fi、再接続、フレーム
  ストリーム、HUD 書き込み）を **1つのインターフェースに抽象化**する設計
  （jlink-ai 系の「接続抽象レイヤ」発想）。
- 目的: CXR-L / RokidBrew / 将来の Android XR など **複数バックエンドを
  差し替え可能**にし、上位の「撮影→OCR→/match→HUD表示」ロジックを
  バックエンド非依存にする。
- サーバへの影響: なし。サーバは HTTP 契約（本サーバの API）だけを公開し、
  どの接続バックエンドから来ても同じに扱う。クライアント側の
  `GlassesConnection` 抽象 → `capture()` / `showHud(lines)` の2メソッドに
  本サーバの入出力がそのまま対応する。

---

## 6. 将来: Android XR / Jetpack へのポート

- **Android XR + Jetpack**（`Projected` / Compose の「Glimmer」系 UI）への
  ポートを将来の選択肢として想定。コンパニオン UI と HUD レンダリングを
  Jetpack Compose ベースに寄せることで、Android XR デバイス全般への
  移植性を確保する。
- 移植時の方針:
  - HUD は引き続き「3行・短文」の `hud.lines` を契約として維持し、
    描画層だけ Compose Glimmer に差し替える。
  - 接続層は §5 の抽象に Android XR バックエンドを追加する形にする。
- サーバ（本リポジトリ）は変更不要。出力契約（3行 HUD）が安定しているため、
  表示技術の世代交代を吸収できる。

---

## 7. サーバ側で実機化に向けて残るタスク

- 本物の OCR をどこで動かすか（端末側 vs サーバ側）の確定と、
  `ocr_text` プレースホルダ（無OCR時は画像MD5）からの移行。
  ※ サーバ側要約/解答/解説/抽出は §8 の `claude` アダプタで既に実 AI 化可能。
- pHash の高速化（現状は純 Python の DCT 実装。numpy / OpenCV / imagehash
  への置換、または事前計算インデックス化）。
- 文書スコープでの認証・マルチテナント・並行登録制御。
- しきい値（`HAMMING_STRONG/WEAK`, `CONF_OK/LOW`, `OCR_MD5_BONUS`）の
  実撮影データでのチューニング。
- CXR-L アプリ側の入力 KeyCode の実測（旧 Glass のキーコード表は要検証、
  [cxr-l-integration.md](cxr-l-integration.md) §7）。

---

## 8. 実 AI アダプタ（このリポジトリに同梱）

「ダミー（プレースホルダ）」だった各ポートに、**Anthropic Claude を使う実アダプタ
`claude` を同梱**した。オフライン既定を壊さず、環境変数だけで実運用へ切り替わる。

| ポート | 環境変数 | 実装 | 未設定時の挙動 |
|--------|----------|------|----------------|
| Analyzer（要約） | `ROKID_ANALYZER=claude` | `app/analyzers/claude.py` | ローカル要約へフォールバック |
| Solver（解答） | `ROKID_SOLVER=claude` | `app/solvers/claude.py` | 二段フォールバックで local |
| Explainer（解説） | `ROKID_EXPLAINER=claude` | `app/explainers/claude.py` | ローカル解説へフォールバック |
| Extractor（数式/表/図） | `ROKID_EXTRACTOR=claude` | `app/extractors/claude.py` | ローカル抽出へフォールバック |

- 実呼び出しには `ANTHROPIC_API_KEY` と `pip install anthropic` が必要。
  未設定なら**ネットワークに一切触れず**ローカル実装で動く（CI もこの経路）。
- モデルは `ROKID_LLM_MODEL`（既定 `claude-opus-4-8`。安価にするなら
  `claude-haiku-4-5`）、出力上限は `ROKID_LLM_MAX_TOKENS`（既定 1024）。
- 共通クライアントは `app/llm.py`（公式 `anthropic` SDK を遅延 import、注入可能）。
- 本番試験ロック（`mode=real` / `ROKID_ALLOW_REAL_EXAM_SOLVE`）は solver の実装に
  依らず `app/main.py` 側で強制されるため、実モデル接続でも緩まない。

---

## 出典（ウェブ検証）

- [CXR SDK（CXR-M / CXR-S / CXR-L） — Rokid AR Platform](https://ar.rokid.com/sdk?lang=en)
- [About YodaOS-Sprite — Rokid AR Platform](https://ar.rokid.com/sprite?lang=en)
- [rokid-docs（コミュニティ版 CXR SDK スイート解説・Maven 座標・AIDL・`com.rokid.sprite.aiapp`）](https://github.com/buildwithfenna/rokid-docs)
- [awesome-rokid（コミュニティ SDK / ツール集）](https://github.com/Anezium/awesome-rokid)
- [Rokid Glasses 製品ページ（両眼 Micro-LED / 49g）](https://global.rokid.com/products/rokid-glasses)
- [NotebookCheck: Rokid Glasses specs（AR1 + NXP RT600 / IMX681 / 210mAh）](https://www.notebookcheck.net/Rokid-Glasses-are-lightweight-AR-smart-glasses-with-Micro-LED-displays-and-a-499-price-tag.1098756.0.html)
- [Rokid、Gemini/ChatGPT をネイティブ統合（Rizon / Agent Store）](https://www.prnewswire.com/news-releases/rokid-integrates-googles-gemini-chatgpt-in-major-update-to-international-smart-glasses-in-open-ecosystem-push-302700875.html)
- Anthropic Claude Messages API（`app/llm.py` / `claude` アダプタの接続先）

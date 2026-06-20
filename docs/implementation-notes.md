# 実装メモ — 実機 Rokid 連携の差し込み箇所

この MVP は **サーバ側のみ** を実装しており、Rokid のハードウェア・SDK・
外部クレデンシャルには一切依存しません。本ドキュメントは、実機・実 SDK を
後から接続する際に **どこへ何を差し込むか** を整理したものです。

最終更新時点（2026-06）の Rokid エコシステム調査を反映しています。
末尾の「出典」を参照してください。

---

## 1. 全体アーキテクチャと差し込み点

```
[Rokid Glasses]──BLE/Wi-Fi──[Android/iOS コンパニオン]──HTTPS──[本サーバ(MVP)]
   カメラ/HUD          撮影・端末OCR・接続管理・UI          登録/照合/要約
   (CXR-S/CXR-M)        (CXR-L SDK / Glimmer 等)            (本リポジトリ)
```

本 MVP が担うのは右端のサーバのみ。左2層を実機に置き換える際の対応表:

| 抽象点（MVP 内） | 現状（プレースホルダ） | 実機での差し込み先 |
|------------------|------------------------|---------------------|
| 画像入力 | `/pages`・`/match` の multipart 画像 | グラスのカメラフレーム（CXR キャプチャ API） |
| 端末 OCR | `ocr_text` / `fast_ocr_text` フォーム値 | Android ML Kit / iOS Vision / 端末側軽量 OCR |
| HUD 出力 | `app/hud.py` の3行ペイロード | グラス単眼ディスプレイ描画（CXR/Glimmer） |
| 接続管理 | なし（HTTP のみ） | jlink-ai 風の接続抽象（後述） |
| 要約 | `app/summarize.py`（先頭行） | Rizon ワークフロー / LLM 呼び出し |

サーバ側で実機を意識する必要があるのは、**画像とOCRテキストの入口**
（`app/main.py` の `add_page` / `match_page`）と、**HUD の出口**
（`app/hud.py`）の2箇所だけです。照合ロジック（`app/matching.py`）は
ハードウェア非依存のまま再利用できます。

---

## 2. 公式 Rokid Glasses SDK（2026-06 時点）

- **CXR-L SDK（Android / iOS）**: 現行の公式 SDK ライン。`ar.rokid.com/sdk`
  で配布。**iOS パス**もここに含まれるため、コンパニオンを iOS で作る場合の
  入口になる。MVP の画像アップロード／HUD 返却は、この SDK の
  カメラフレーム取得・ディスプレイ描画コールバックに置き換える。
- **CXR-S / CXR-M**: グラス側のキャプチャ／表示デバイス層。MVP では
  `capture_device` フィールド（例 `"CXR-S"`）としてメタデータに記録するのみ。
  実機では、この層からフレームを取り出して端末 OCR → `/match` に流す。
- **差し込み手順（Android 例）**:
  1. CXR-L SDK でカメラフレーム取得コールバックを登録。
  2. フレームを端末 OCR（ML Kit）に通し、短いテキストを得る。
  3. フレーム JPEG/PNG + OCR テキストを `POST /v1/match` に送信。
  4. レスポンスの `hud.lines`（3行）を SDK のディスプレイ API で描画。

---

## 3. Rizon / Agent Store（要約・エージェント連携）

- **Rizon** は Coze Studio をベースに Rokid がカスタムした AI オープン
  プラットフォーム。ノーコードで AI ワークフローを構築・共有できる。
- **Agent Store** には多数のエージェントワークフローが公開されており、
  国際展開も進行中。
- **差し込み先**: `app/summarize.py`。現状は OCR テキスト先頭行を返すだけだが、
  実運用ではここを Rizon ワークフロー（または Gemini / GPT / Qwen / DeepSeek
  などのモデル呼び出し）に差し替え、ページ内容の要約・キーフレーズ抽出を
  HUD 2行目に出す。サーバ側はインターフェース（`summarize_page(text)->str`）
  を保ったまま実装だけ差し替え可能。

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
- サーバへの影響: なし。サーバは HTTP 契約（本 MVP の API）だけを公開し、
  どの接続バックエンドから来ても同じに扱う。クライアント側の
  `GlassesConnection` 抽象 → `capture()` / `showHud(lines)` の2メソッドに
  本 MVP の入出力がそのまま対応する。

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
- サーバ（本 MVP）は変更不要。出力契約（3行 HUD）が安定しているため、
  表示技術の世代交代を吸収できる。

---

## 7. サーバ側で実機化に向けて残るタスク

- 本物の OCR をどこで動かすか（端末側 vs サーバ側）の確定と、
  `ocr_text` プレースホルダ（無OCR時は画像MD5）からの移行。
- pHash の高速化（現状は純 Python の DCT 実装。numpy / OpenCV / imagehash
  への置換、または事前計算インデックス化）。
- 文書スコープでの認証・マルチテナント・並行登録制御。
- しきい値（`HAMMING_STRONG/WEAK`, `CONF_OK/LOW`, `OCR_MD5_BONUS`）の
  実撮影データでのチューニング。

---

## 出典

- [CXR-L SDK（Android/iOS） — Rokid AR Platform](https://ar.rokid.com/sdk?lang=en)
- [awesome-rokid（コミュニティ SDK / ツール集、RokidBrew 等）](https://github.com/Anezium/awesome-rokid)
- [Rokid Glasses 製品ページ](https://global.rokid.com/products/rokid-glasses)
- [Rokid Glass 開発ドキュメント](https://rokid.github.io/glass-docs/)
- [Rokid、Gemini 連携でエージェント AI ロードマップを加速（Rizon / Agent Store）](https://www.globenewswire.com/news-release/2026/05/21/3299397/0/en/rokid-accelerates-agentic-ai-roadmap-for-smart-glasses-following-google-gemini-updates-at-i-o.html)

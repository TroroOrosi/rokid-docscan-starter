# ユーザー運用ガイド

この文書は、Windows PC、Android スマホ、Rokid Glassesを所有する利用者向けです。
コマンドを含む完全な導入手順は
[windows-android-real-device-setup.md](windows-android-real-device-setup.md)、
合格判定は
[device-verification-checklist.md](device-verification-checklist.md)を使ってください。

## システム構成

```text
Rokid Glassesで撮影
  → Global Hi Rokid
  → Android Relay（日本語ML Kit OCR）
  → Windows FastAPI（Vision Analyzer / Solver）
  → Android Relay
  → CUSTOMVIEW HUD
```

写真を撮らずにグラス搭載AIの任意認識文・回答を外部へ取り出す公開CXR-L APIは
確認できないため、運用の主経路には使いません。

## 利用者が用意するもの

- Android 12/API 31以上のスマホ
- Global版Hi Rokid、Rokidアカウント、ペアリング済みグラス
- Windows 10/11、Python 3.10–3.12
- JDK 17、Android Studio/SDK Platform 36、ADB
- PCとスマホが相互到達できる信頼済みLAN
- OpenAI、Google Gemini、AnthropicのいずれかのSDK/APIキー
- サーバー用の長いランダムBearer値

Rokid AARはGradleが公式Mavenから取得します。CxrGlobalのcloneやAARコピーは不要です。

## 初回セットアップ

1. WindowsでPython仮想環境と依存を導入する。
2. 使用するProvider SDKを一つ導入する。
3. `ROKID_ANALYZER`、`ROKID_SOLVER`、Provider APIキー、
   `ROKID_API_KEY`を設定する。
4. FastAPIをLAN向けに起動する。
5. Windows FirewallはPrivate profileの8000/TCPだけを許可する。
6. `android-relay`をビルドし、ADBでスマホへ導入する。
7. RelayへPCのIPv4 URLとBearer値を入力する。
8. サーバー確認後、Hi Rokid認可を行う。

APIキーとHi Rokid認可トークンをログ、スクリーンショット、Issue、PRへ貼らないで
ください。

## 通常操作

### 読取

1. 用紙全体がカメラへ入り、文字が読める距離で止まる。
2. AIキーを短押しする。
3. HUDの撮影/OCR/送信完了を待つ。
4. 次ページで繰り返す。
5. 読取が悪い直前ページはAIキーを短く2回押して置換する。
6. 全ページ終了後、AIキーを1.2秒以上長押しする。

各ページは元JPEGとOCRの両方で保存されます。AnalyzerがOCRを補い、問題分割後に
Solverが各問題の開始ページ画像を見て解答します。

### 閲覧

| AIキー | 動作 |
|---|---|
| 短押し | 次の表示ページ、末尾なら次問題 |
| 短押し2回 | 前の表示ページ、先頭なら前問題 |
| 長押し | 閲覧終了・新規文書 |

スマホの同名ボタンは設定、診断、グラス入力が届かない場合の復旧用です。

## 中断時

Relayは次をスマホへ保存します。

- `document_id`
- 次の `page_index`
- `session_id`

Hi Rokidを再認可して接続すると、`/scan-status`を読み、未確定文書、確定済み文書、
作成途中sessionのいずれからも再開します。APIキーと認可トークンは保存しません。

## エラー対応

| 表示 | 対応 |
|---|---|
| サーバ接続不可 | PC IPv4、同一LAN、Firewall、ポート、URLを確認 |
| 401 | RelayとWindowsの `ROKID_API_KEY` を一致させる |
| Hi Rokid未接続 | Hi Rokidでペアリング確認後、再認可 |
| 撮影callbackなし | Relayを前面表示し、スマホをスリープさせない |
| OCR空 / 問題0件 | 回転を直して同じページを再撮影、または画像対応Analyzer設定を確認 |
| 問題0件 | OCR/図表説明を確認して該当ページを再撮影 |
| HUD更新なし | サービス再接続。Relayはclose + open更新を使用 |
| Provider失敗 | SDK、APIキー、model名、課金/利用上限、ネットワークを確認 |

## 環境変数

| 変数 | 実機での意味 |
|---|---|
| `ROKID_ANALYZER` | `openai` / `gemini` / `claude` の画像OCR |
| `ROKID_SOLVER` | 同Providerの問題解答 |
| `ROKID_EXPLAINER` | 任意の資料解説 |
| `ROKID_EXTRACTOR` | 任意の図表/数式抽出 |
| `OPENAI_API_KEY` | OpenAI選択時 |
| `GOOGLE_API_KEY` | Gemini選択時 |
| `ANTHROPIC_API_KEY` | Claude選択時 |
| `ROKID_API_KEY` | Android RelayからのBearer認証 |
| `ROKID_DATA_DIR` | SQLiteとページ画像の保存先 |
| `ROKID_ALLOW_REAL_EXAM_SOLVE` | 既定0。実試験modeのロック解除 |

`local` Analyzer/Solverは開発用プレースホルダーです。写真と端末OCRの両方から文字を
得られない場合、ローカル構成では文書確定を拒否します。

## プライバシーと安全

- 撮影、保存、クラウド送信について利用者と資料所有者の同意を得る。
- 公衆Wi-FiやインターネットへFastAPIを直接公開しない。
- LAN外ではTLSリバースプロキシとBearer認証を使う。
- 不要になった `ROKID_DATA_DIR` の画像とDBを運用手順に従って削除する。
- プライバシーLEDはハードウェア強制のままにする。
- 撮影中点灯、callback後消灯、閲覧中消灯を物理確認する。
- シャッター音、フラッシュ、撮影表示はdevice-controlledとしてファームごとに実測する。

## 実装済みと断定しないもの

- 全Hi Rokid/YodaOSバージョン互換
- 全タッチジェスチャの外部アプリ配送
- グラス搭載GPT/Geminiの任意認識文/回答 callback
- `customViewUpdate`だけによる確実な再描画
- ビルドだけで確認したLED挙動

これらを含む「実機検証済み」の判断は
[device-verification-checklist.md](device-verification-checklist.md)の全項目を
満たした後に行います。

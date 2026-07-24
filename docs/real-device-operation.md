# 実機運用ガイド

Windows PC、Android スマホ、Rokid Glasses の実機運用は
[Windows + Androidスマホ中継による実機運用](windows-android-real-device-setup.md)
を正本とします。

## 対応構成

```text
Rokid Glasses
  └─ CXR-L / Bluetooth
      └─ Androidスマホ: Global Hi Rokid + android-relay
          └─ 信頼できるLAN / HTTP(S)
              └─ Windows: FastAPI + SQLite + Vision Analyzer/Solver
```

この構成では、グラスで物理ページを実際に撮影します。元 JPEG をスマホへ受け取り、
スマホの日本語 ML Kit OCR と、サーバーの画像対応 Analyzer/Solver を組み合わせます。
「撮影せず、グラス搭載 AI の認識文や回答を CXR-L から直接取得する」経路は、公開 API
で確認できないため運用前提にしません。

## リポジトリに揃っているもの

| 項目 | 状態 |
|---|---|
| FastAPI サーバー | 実装済み |
| Global Hi Rokid 対応 Android リレー | `android-relay` に実装済み |
| CXR-L 依存 | 公式 `client-l:1.0.1` を Gradle 取得 |
| Global 化 | `RokidGlobalLink` に実装済み |
| 日本語端末 OCR | bundled ML Kit を実装済み |
| 写真アップロード・中断復帰 | 実装済み |
| Vision OCR・問題画像付き Solver | 実装済み |
| CUSTOMVIEW HUD | 実装済み |
| APK ビルド | Windows script / GitHub Actions を実装済み |

## 利用者が用意するもの

- Android 12/API 31 以上のスマホ
- Global版 Hi Rokid とログイン済みアカウント
- ペアリング済み Rokid Glasses
- Windows 10/11、Python、JDK 17、Android SDK Platform 36、ADB
- 初回依存取得用インターネット接続
- OpenAI、Gemini、Anthropic のいずれかの API キー
- PC とスマホが相互到達できる信頼済み LAN

Rokid AAR、Hi Rokid 認可トークン、クラウド API キーはリポジトリへ同梱しません。
これは不足ではなく、配布条件と秘密情報管理のための意図した境界です。

## 運用フェーズ

1. Windows で Analyzer/Solver と Bearer 認証を設定し、FastAPI を起動する。
2. Android リレー APK をビルドしてスマホへインストールする。
3. リレー画面でサーバー確認後、Hi Rokid 認可を行う。
4. AI キー短押しで各ページを撮影する。短押し2回で直前ページを置換する。
5. 長押しで文書確定、問題分割、一括解答へ進む。
6. 短押し/短押し2回で HUD の前後を閲覧し、長押しで終了する。

APIキーとHi Rokid認可トークンはログへ出しません。リレーはセッションIDとページ番号だけを
保存し、再接続時に `/scan-status` から続行します。

## 実機合格条件

次の全項目を、使用するスマホ・Hi Rokid・YodaOSの組み合わせで確認してください。

- Hi Rokid 認可と AIDL bind が成功する。
- AIキー short/double/long が意図した操作になる。
- 写真 callback が0バイトでなく、`has_image=true`になる。
- OCRに用紙の文字が入り、必要なら回転設定で直せる。
- Analyzer が写真を読み、文書確定後に問題が1件以上作成される。
- Solverへ設問開始ページの画像が渡る。
- HUDが黒背景・緑文字・最大3行で更新される。
- プライバシーLEDが撮影中に点灯し、写真受信後に物理的に消灯する。
- 解答と閲覧中に追加撮影が起きず、LEDが消灯したままである。
- スマホ画面を維持した状態で複数ページを連続撮影できる。

ビルド/単体テストの成功だけでは、LED、写真 callback、Hi Rokid 認可、HUD再描画を
検証済みとはしません。

## 詳細

- [Windows + Android セットアップ](windows-android-real-device-setup.md)
- [CXR-L / Global Hi Rokid integration](cxr-l-integration.md)
- [Android relay](../android-relay/README.md)

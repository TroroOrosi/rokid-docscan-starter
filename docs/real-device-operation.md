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
スマホの日本語 ML Kit OCR と同じ回転角をサーバーにも伝え、画像対応
Analyzer/Solver を組み合わせます。サーバーの保存画像は OCR と同じ向きに正規化されます。
「撮影せず、グラス搭載 AI の認識文や回答を CXR-L から直接取得する」経路は、公開 API
で確認できないため運用前提にしません。

## リポジトリに揃っているもの

| 項目 | 状態 |
|---|---|
| FastAPI サーバー | 実装済み |
| Global Hi Rokid 対応 Android リレー | `android-relay` に実装済み |
| CXR-L 依存 | 公式 `client-l:1.0.1` を Gradle 取得 |
| Android client / Glasses View contract | `0.2.0` / `1.8.0` |
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
4. 用紙まで40〜60cm離し、グラスをタップして `AIMING` の照準を表示する。用紙中心を
   「＋」へ合わせ、長押し後は1.5秒の静止表示から写真callbackまで動かさない。
5. `CAPTURE_REVIEW` でスマホとグラスの縮小プレビューを確認する。タッチパッド長押し
   （`AI-assist-start`）で登録し、短押しまたは2回短押しなら同じページの `AIMING` へ
   戻る。再撮影は照準を確認して長押しする。OCRが0文字でも警告を確認して明示登録できる。
6. `READING` の長押しで文書確定、問題分割、一括解答へ進む。
7. `REVIEW` のタップでHUDを送り、長押しで終了する。

APIキーとHi Rokid認可トークンはログへ出しません。リレーはセッションIDとページ番号を
保存し、再接続時に `/scan-status` から続行します。確認中の未登録写真とOCR等は、
下記のとおりアプリ専用領域に限って保存します。

撮影値は `takePhoto(1920, 1080, 80)` です。カメラは固定焦点で、公称被写界深度は
34cm〜∞です。`takePhoto(4032, 3024, 80)` は実機でBinder上限を超えcallbackなしに
なった既知NGです。撮影前ライブ映像、オートフォーカス、合焦状態、専用シャッター
ボタンの入力イベントは公開CXR-L非対応です。照準は用紙中心を合わせる目安で、ディスプレイ
FOVとカメラFOVが異なるため撮影境界や合焦表示ではありません。四隅は撮影後プレビューで
確認します。回転既定は実機に合わせた90°で、スマホの回転選択後に同ページ再撮影を
準備すると、次の写真へ適用されます。

未登録写真、OCR、ページ番号、回転はアプリ専用領域に保持され、再起動後も
`CAPTURE_REVIEW` へ復元されます。自動登録は行いません。登録成功まで対象ページと
次ページ番号は変わりませんが、文書自体は初回撮影前に作成されます。スマホでは
「この写真を登録」「同じページを撮り直す」「未登録写真を破棄」をフォールバックとして
選べます。状態復元や表示更新だけで自動撮影することもありません。

ユーザーがCustomViewを閉じたcallbackをタップ、`AI-assist-start`を長押しとして扱います。
アプリ自身が表示更新のために行うcloseは確認済みcallback世代内で識別し、同じ物理操作
からcloseとAIイベントが重複した場合もdebounceします。スマホログの
`Glasses input source=...`で実際のイベント源を確認できます。

`AIMING`の短押しまたは2回短押しは撮影せず準備を取り消します。`AIMING`の長押しで
1.5秒の静止待ちを開始し、`STABILIZING`中は短押し、2回短押し、長押しのどれでも
取り消します。取り消したtimerは自動再開しません。

公式のダブルタップは現在画面を終了するため、誤って連続タップすると標準メニューへ
戻ることがあります。`AI-exit`の650ms後まで新しいCustomView openがなければ、
リレーは現在のDocScan画面を再表示します。メニュー遷移のcloseは入力として破棄し、
状態は進めず、撮影・写真登録・読取完了は発行しません。静止待ち中の遷移なら旧timerを
無効化し、復帰後も1.5秒待ちを自動でやり直しません。

CustomViewのopen errorまたは3秒のACK timeoutではcallback epochをfenceし、新しい
CustomViewを要求しません。「Hi Rokid認可・再接続」を完了して新しいcallback epochに
切り替わるまで、次の表示要求や撮影を行わないでください。

## 実機合格条件

次の全項目を、使用するスマホ・Hi Rokid・YodaOSの組み合わせで確認してください。

- Hi Rokid 認可と AIDL bind が成功する。
- user CustomView closeと`AI-assist-start`のイベント源がスマホログへ記録される。
- 1回目のタップでは `AIMING` だけが表示され、`takePhoto` は0回である。
- `AIMING`の短押しまたは2回短押しで準備を取り消せ、`takePhoto`は0回である。
- 照準確認後の長押しで静止案内を開き、そのopen callback確認から1.5秒静止した
  後に、`takePhoto` が1回だけ発行される。
- 静止待ち中は短押し、2回短押し、長押しのどれでも準備を取り消せ、旧timerから
  撮影されない。
- CustomViewのACK fault/timeout後は次の表示要求がなく、Hi Rokid再認可・再接続後の
  新しいcallback epochでだけ再開する。
- アプリ起因closeやclose/AIの重複配送で、撮影・登録・読取完了が重複しない。
- ダブルタップで標準メニューへ戻った後、現在のDocScan画面へ自動復帰し、その復帰では
  撮影も登録も行われない。
- 写真 callback が0バイトでなく、明示登録前は `CAPTURE_REVIEW` と未登録表示になる。
- 撮影確認中の長押しまたはスマホの登録ボタンが成功した後にだけ `has_image=true`になる。
- 撮影確認中の短押しまたは2回短押しで同ページ再撮影を準備し、長押しで撮り直せる。
- `READING` の長押しで読取完了でき、登録・再撮影を含め通常操作がグラスで完結する。
- 登録前または登録失敗時は対象ページと次ページ番号が変わらない。
- 登録成功後のローカル削除失敗でも、同じJPEGが再起動後に未登録へ戻らない。
- 用紙まで40〜60cm離し、用紙中心を「＋」へ合わせて静止できる。
- 撮影後プレビューで四隅が入り、文字の輪郭とブレを判別できる。
- 撮影後の縮小プレビューがスマホとグラスのCustomViewへ正しく表示される。
- OCRに用紙の文字が入り、必要なら回転設定で直せる。
- OCRが0文字なら警告され、明示登録または同じページの再撮影を選べる。
- 未登録写真を残した再起動で同じ確認状態へ戻り、自動登録されない。
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

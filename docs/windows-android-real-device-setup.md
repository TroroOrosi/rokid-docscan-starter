# Windows + Androidスマホ中継による実機運用

この手順は、Windows PCでDocScanサーバを実行し、Androidスマホ上の中継APKから
Global版Hi Rokidを経由してRokid Glassesを使う構成の正本です。

## 1. 成立する実装経路

現在の公開CXR-L/AIDL面から確実に取得できるのは、写真、音声、CUSTOMVIEW表示、
AIキー開始・終了イベントです。グラス搭載AIの任意の認識文章や回答を受け取る公開APIは
確認できないため、本実装は次の実経路を使います。

1. Rokid Glassesのカメラで実際にページを撮影する。
2. JPEGをAndroidスマホへ受け取る。
3. スマホ内の日本語ML KitでOCRする。
4. JPEGとOCRをFastAPIサーバへ送る。
5. サーバのVision AnalyzerがOCR補正・図表説明を行う。
6. Server Solverが問題を一括解答する。
7. 最大3行の結果をCUSTOMVIEWへ返す。

テキストだけを送る旧経路はAPI互換として残りますが、実機運用の主経路ではありません。

## 2. 必要条件

| 区分 | 必要条件 |
|---|---|
| Windows | Windows 10/11 64-bit、Python 3.10–3.12、Git |
| Android開発 | Android Studio、JDK 17、Android SDK Platform 36、ADB |
| スマホ | Android 12/API 31以上、Global版Hi Rokid |
| グラス | Hi Rokidでペアリング・Bluetooth接続済みのRokid Glasses |
| ネットワーク | PCとスマホが同一の信頼できるLAN、スマホからPCの8000番へ到達可能 |
| モデル | OpenAI/Gemini/Anthropicのいずれか。実OCR補正と解答にはAPIキーが必要 |

確認実績の基準値はCxrGlobalの公開情報と同じく、Global Hi Rokidパッケージ
`com.rokid.sprite.global.aiapp`、CXR-L `client-l:1.0.1`です。Hi Rokidや
YodaOS更新後はAIDL Actionと実機動作を再検証してください。

## 3. Windowsでサーバを起動

PowerShellでリポジトリ直下を開きます。

```powershell
py -3.12 -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

# 使用する1社だけをインストール
pip install openai

$env:OPENAI_API_KEY = "YOUR_API_KEY"
$env:ROKID_ANALYZER = "openai"
$env:ROKID_SOLVER = "openai"
$env:ROKID_API_KEY = "十分に長いランダム値"
$env:ROKID_DATA_DIR = "data"

uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Geminiの場合は`google-genai`、`GOOGLE_API_KEY`、`ROKID_*=gemini`、
Anthropicの場合は`anthropic`、`ANTHROPIC_API_KEY`、`ROKID_*=claude`へ
置き換えます。

WindowsのIPv4アドレスを確認します。

```powershell
ipconfig
```

スマホのブラウザから次が開き、`status`が`ok`になることを確認します。

```text
http://PCのIPv4アドレス:8000/health
```

接続できない場合は、管理者PowerShellでローカルネットワーク用の受信規則を追加します。

```powershell
New-NetFirewallRule `
  -DisplayName "Rokid DocScan 8000" `
  -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000 `
  -Profile Private
```

公衆Wi-Fiやインターネットへ8000番を直接公開しないでください。LAN外から使う場合は、
TLSリバースプロキシとBearer認証を必須にします。

## 4. Android APKをビルド・導入

Android Studioで`android-relay`フォルダを開くか、PowerShellでビルドします。
Windowsでは、実体のチェックアウトパスをASCII文字だけにしてください。OneDriveの
`ドキュメント`など非ASCII文字を含むパスではAndroid Gradle Pluginが拒否し、チェックを
無効化してもGradleのテストプロセスがテストクラスを読み込めません。該当する場合は
ASCIIパスのworktreeを作成します。

```powershell
git worktree add C:\Users\Public\rokid-docscan-build HEAD
cd C:\Users\Public\rokid-docscan-build\android-relay

.\gradlew.bat testDebugUnitTest assembleDebug
adb devices
adb install -r .\app\build\outputs\apk\debug\app-debug.apk
```

すでにASCIIパスへチェックアウトしている場合は、そのまま`android-relay`で実行します。

```powershell
cd android-relay
.\gradlew.bat testDebugUnitTest assembleDebug
adb devices
adb install -r .\app\build\outputs\apk\debug\app-debug.apk
```

最初のビルドはGradle、Android依存、Rokid AAR、ML Kitモデルを取得するため
インターネット接続が必要です。`ANDROID_HOME`、`ANDROID_SDK_ROOT`、
`local.properties`のいずれも未設定なら、Windows用スクリプトは標準の
`%LOCALAPPDATA%\Android\Sdk`を自動検出します。

## 5. 初回接続

1. スマホでHi Rokidを開き、グラスが接続済みであることを確認する。
2. `Rokid DocScan Relay`を開く。
3. サーバURLに`http://PCのIPv4アドレス:8000`を入力する。
4. `ROKID_API_KEY`と同じ値を入力する。
5. 写真向きは最初に`0°`を選ぶ。
6. 「サーバ確認」で`health`とHUD契約を確認する。
7. 「Hi Rokid認可・再接続」を押し、Bluetooth権限とHi Rokid認可を許可する。
8. グラスに「接続完了」が表示されることを確認する。

認可トークンはログ出力・保存しません。APIキーもアプリ終了後は保存されません。

## 6. 読取・解答・閲覧

| 操作 | 読取中 | 閲覧中 |
|---|---|---|
| AIキー短押し | 次ページを撮影 | 次の表示ページ、末尾なら次問題 |
| AIキー2回短押し | 直前ページを再撮影 | 前の表示ページ、先頭なら前問題 |
| AIキー長押し | 読取完了→OCR補正→一括解答 | 閲覧終了・新規文書 |

写真はページごとにサーバへ保存され、同じ`page_index`の再撮影は置換されます。
アプリや接続が中断した場合、再接続時に`/scan-status`から登録済みページを復元し、
次のページ番号から再開します。

## 7. 実機で必ず確認する項目

- 認可後に`onCXRLConnected`相当の接続が成立する。
- 写真バイト列が0バイトでない。
- 用紙の文字がML Kit OCR結果に含まれる。
- 向きが不正なら回転設定を変更して再撮影できる。
- `/scan-status`の各ページで`has_image=true`になる。
- 撮影中はプライバシーLEDが点灯し、写真受信後に物理的に消灯する。
- 読取完了後は追加の撮影が発生せず、LEDが消灯したままである。
- Solverが各問題へ元の開始ページ画像を渡している。
- HUDが黒背景・緑文字・最大3行で表示される。
- スマホ画面消灯時に写真コールバックが停止しないか確認する。停止するファームでは
  Relay画面を表示したままにする（アプリは画面消灯を抑止する）。

## 8. 現時点で検証済みと扱わないもの

- Global Hi Rokid/YodaOSの全バージョン互換性
- CXR-Lからの全タッチジェスチャ取得
- グラス搭載GPT/Geminiの認識文章・回答を外部アプリへ直接取り出す経路
- `customViewUpdate`だけでの確実な再描画

これらは公開APIだけでは確認できません。リポジトリは未確認機能を擬似コードで実装済みと
扱わず、写真・端末OCR・サーバVisionモデル・AIキーイベントという取得可能な経路を使います。

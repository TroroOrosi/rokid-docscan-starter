# Windows + Androidスマホ中継による実機運用

この手順は、Windows PCでDocScanサーバを実行し、Androidスマホ上の中継APKから
Global版Hi Rokidを経由してRokid Glassesを使う構成の正本です。

## 1. 成立する実装経路

現在の公開CXR-L/AIDL面から確実に取得できるのは、写真、音声、CUSTOMVIEW表示、
ユーザーによるCustomView close、`AI-assist-start`です。専用シャッターボタンの入力
イベントや、グラス搭載AIの任意の認識文章・回答を受け取る公開APIは確認できないため、
本実装は次の実経路を使います。

1. Rokid Glassesのカメラで実際にページを撮影する。
2. JPEGをAndroidスマホへ受け取る。
3. スマホ内の日本語ML KitでOCRする。
4. スマホとグラスの縮小プレビューで未登録写真を確認する。
5. 確認画面を経たJPEGとOCRだけをFastAPIサーバへ送る。
6. サーバのVision AnalyzerがOCR補正・図表説明を行う。
7. Server Solverが問題を一括解答する。
8. 最大3行の結果をCUSTOMVIEWへ返す。

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
この手順のAndroid clientは`0.3.4`、Glasses View contractは`1.8.0`です。

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

# 各SDKはbase_urlを環境変数から自動採用する。別用途のローカルproxyが
# 設定されていると、撮影後の解析だけが静かに別の宛先へ行く。
Remove-Item Env:OPENAI_BASE_URL -ErrorAction SilentlyContinue
Remove-Item Env:ANTHROPIC_BASE_URL -ErrorAction SilentlyContinue

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

スマホから開く前に、PC自身が自分のLAN IPで応答することを確認しておくと、
ファイアウォールの問題とWi-Fi側の問題を切り分けられます。

```powershell
curl.exe http://PCのIPv4アドレス:8000/health
```

受信規則は、現在のネットワークプロファイルへ適用されていなければ効きません。
まず現在の分類と既存規則を確認します。Windowsは既定で新しいWi-Fiを`Public`に
分類するため、`-Profile Private`だけの規則では届かないことがあります。

```powershell
Get-NetConnectionProfile | Select-Object Name, NetworkCategory
```

接続できない場合は、管理者PowerShellで現在のプロファイルを含む受信規則を追加します。
`-RemoteAddress`でLANのサブネットに限定してください。

```powershell
New-NetFirewallRule `
  -DisplayName "Rokid DocScan 8000" `
  -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000 `
  -Profile Private,Public `
  -RemoteAddress 192.168.0.0/24
```

Pythonインタプリタ単位の受信許可が既にある場合は、この規則を追加しなくても
到達します。その場合でも、実際に起動する`python.exe`（venvを作ったなら
`.venv\Scripts\python.exe`）が許可対象の実体と一致している必要があります。

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

サーバ側のテストは`python`が3.14などpytest未導入のバージョンを指すことがあります。
その場合は明示してください。

```powershell
py -3.12 -m pytest -q
```

最初のビルドはGradle、Android依存、Rokid AAR、ML Kitモデルを取得するため
インターネット接続が必要です。`ANDROID_HOME`、`ANDROID_SDK_ROOT`、
`local.properties`のいずれも未設定なら、Windows用スクリプトは標準の
`%LOCALAPPDATA%\Android\Sdk`を自動検出します。

### USB接続が数秒で切れる場合（Android 16）

Android 16の「高度な保護機能（Advanced Protection）」が有効だと
USBデータ通信が遮断されます。F-51F（Android 16 / API 36）での実測では、
列挙の約4秒後にMTPとADBの全インターフェースが同時に消えました。
画面のロックを解除して点灯させたまま接続しても再現します。

切り分け:

- 毎回同じ長さ（約4秒）で切れ、自動で再接続しない
  → ソフトによる意図的な遮断
- 数秒周期で自動的に再列挙を繰り返す
  → ケーブル・ポートの接触不良

対処は`設定` → `セキュリティとプライバシー` → `高度な保護機能`をOFFです。
この機能は個別に無効化できず、有効のままだとサイドロードも禁止されるため
`adb install`自体が通りません。

それでも切れる場合はUSB4/ThunderboltのType-Cポートを避けて
USB-Aポートに変えます。

### USBを使わずWi-FiだけでAPKを入れる

`adb tcpip 5555`は一度USB接続が成立している必要があるため、上記のUSB遮断が
起きている端末では使えません。Android 11以上の「ワイヤレスデバッグ」は
ペア設定コードを使うのでUSBが不要です。スマホとPCが同じLANにある前提で行います。

1. スマホの`設定` → `システム` → `開発者向けオプション` → `ワイヤレスデバッグ`をON。
2. `ペア設定コードによるデバイスのペア設定`を開く。6桁コードと
   `IP アドレスとポート`（ペア用ポート）が表示される。
3. PCでペアリングし、続けて接続する。ペア用ポートと接続用ポートは別の番号です。
   接続用は`ワイヤレスデバッグ`画面のトップに出ている方を使います。

```powershell
adb pair スマホIP:ペア用ポート        # 6桁コードを入力
adb connect スマホIP:接続用ポート
adb devices -l
adb install -r .\app\build\outputs\apk\debug\app-debug.apk
```

「高度な保護機能」が有効なままだとサイドロードが禁止されるため、
ワイヤレスデバッグでも`adb install`は通りません。先にOFFにしてください。

ワイヤレスデバッグはデバッグ用ポートをLANへ開きます。信頼できるLANでだけ使い、
作業終了時にスマホ側でOFFに戻してください。

### versionCodeの逆行

`adb install -r`は端末に入っているビルドより`versionCode`が低いAPKを
`INSTALL_FAILED_VERSION_DOWNGRADE`で拒否します。アンインストールすれば入りますが、
Hi Rokidの認可と保存済みの撮影設定が消えます。先に確認してください。

```powershell
adb shell dumpsys package dev.rokid.docscanrelay | Select-String versionCode
```

## 5. 初回接続

1. スマホでHi Rokidを開き、グラスが接続済みであることを確認する。
2. `Rokid DocScan Relay`を開く。
3. サーバURLに`http://PCのIPv4アドレス:8000`を入力する。
4. `ROKID_API_KEY`と同じ値を入力する。
5. 写真向きは検証済み実機の既定値`90°`を選ぶ。
   幅・高さ・品質は`1920`・`1080`・`80`のまま始める。
6. 「サーバ確認」で`health`とHUD契約を確認する。
7. 「Hi Rokid認可・再接続」を押し、Bluetooth権限とHi Rokid認可を許可する。
8. グラスに「接続完了」が表示されることを確認する。

認可トークンはログ出力・保存しません。APIキーもアプリ終了後は保存されません。

## 6. 読取・解答・閲覧

撮影は `takePhoto(1920, 1080, 80)` で行います。カメラは固定焦点で、公称被写界深度は
34cm〜∞です。用紙まで40〜60cm離し、最初のタップで `AIMING` の照準を表示します。
用紙中心を「＋」へ合わせ、静止したまま**もう一度タップ**します。以後、1.5秒の静止
表示から写真callbackまで動かさないでください。照準はディスプレイFOVとカメラFOVの差が
あるため、正確な撮影境界ではありません。四隅は撮影後プレビューで確認します。

検証済みファームウェア（Hi Rokid `G1.12.10.0815` / CXR-L service `1.0.0 code 10000`）
がアプリへ配送するグラス入力は**1本指タップだけ**です。長押しはグラス側AIが占有し、
ダブルタップはYodaOSの「終了」に予約されています。信号が1つしかないため、タップは
取り消せる操作に割り当て、ページ登録は「タップしないこと」＝待機満了で確定します。
読取完了と新規は時間で判定できないためスマホ側が正規の経路です。

| 状態 | グラスのタップ | スマホのボタン |
|---|---|---|
| 読取中 (`READING`) | 次ページの `AIMING` を開始 | 撮影準備 / 前ページ撮影準備 / **読取完了** |
| 撮影準備 (`AIMING`) | **シャッター**（1.5秒静止して1回撮影） | シャッター / 撮影取消 |
| 静止待ち (`STABILIZING`) | 静止待ちを取り消す | 撮影取消 |
| 撮影確認 (`CAPTURE_REVIEW`) | 同じページの `AIMING` を開始（待機中なら自動登録を取消） | この写真を登録 / 同じページを撮り直す / 未登録写真を破棄 |
| 閲覧中 (`REVIEW`) | 次の表示ページ、末尾なら次問題 | 戻る / 次へ / **新規** |

通常の撮影はタップで照準を表示し、構図を確認してからもう一度タップします。1回目の
タップでは`takePhoto`を呼ばないため、構図を合わせる前の自動撮影はありません。
シャッターだけをグラスへ残しているのは、照準を合わせている最中にスマホへ手を伸ばすと
その照準で決めた構図が動くためです。公式のダブルタップは
現在画面を終了するため、誤って連続タップして標準メニューへ戻った場合は、
`AI-exit`後に現在のDocScan画面を自動再表示します。復帰だけで撮影・登録はしません。
メニュー遷移のcloseは入力として破棄し、静止待ち中なら旧timerを無効化します。
復帰後に1.5秒待ちを自動でやり直しません。
ファームウェアが2回の入力を`DOUBLE_SHORT`としてアプリへ配送した場合だけ、読取中は
直前ページの再撮影準備、撮影確認中は同ページの再撮影準備、閲覧中は前の表示、
`AIMING`中は準備取消として扱います。

写真callbackとOCRの後は `CAPTURE_REVIEW` になり、まだサーバーへ登録されません。
このとき、認識した各行の外接矩形が画像の縁2%の帯に触れていないかを判定し、触れて
いれば用紙がその方向で切れていると見て「不合格 右が切れています」のように表示します。
判定は待機時間に反映され、合格は4秒、不合格・判定不可は12秒で自動登録します。
待機中にグラスをタップすれば登録を取り消して撮り直せます。
スマホとグラスの縮小プレビューで四隅、文字の輪郭、ブレを確認し、スマホの
「この写真を登録」で明示登録します。撮影確認中のタップ、または「同じページを
撮り直す」は同じ `page_index` の再撮影準備へ戻り、照準確認後のタップで未登録写真を
置き換えます。
スマホにはさらに「未登録写真を破棄」があり、送信せず読取へ戻せます。OCRが0文字なら
警告されますが、写真を確認して明示登録できます。登録成功まで対象ページと次ページ番号は
変わりません。文書自体は初回撮影前に作成されます。

撮影前ライブ映像、オートフォーカス、合焦状態は公開CXR-L非対応です。専用シャッター
ボタンのイベントも受信できません。グラスのタップは、ユーザー由来の`AI-exit`
callbackとして観測します。リレー自身が表示更新のために行うcloseは
確認済みcallback世代内で識別し、同じ物理操作によるclose/AIイベントの重複は
debounceします。スマホログの`Glasses input source=...`でイベント源を確認できます。

CustomViewのopen errorまたは3秒のACK timeoutではcallback epochをfenceし、そのepoch
から新しいCustomViewを要求しません。「Hi Rokid認可・再接続」を完了し、新しいcallback
epochへ切り替わってから操作を再開してください。

回転の既定は90°で、スマホの回転選択は同じページの再撮影準備後に撮る次の写真へ
適用されます。現在の未登録写真は回転選択だけでは変わりません。

登録した写真はページごとにサーバへ保存され、同じ`page_index`の再撮影は置換されます。
アプリや接続が中断した場合、再接続時に`/scan-status`から登録済みページを復元し、
次のページ番号から再開します。
未登録写真はアプリ専用領域から `CAPTURE_REVIEW` へ復元し、表示確認後に待機を始めます。
状態復元やCustomView更新だけで自動撮影することもありません。撮影、同ページ再撮影、
登録、`READING`の読取完了はグラスだけで操作でき、スマホボタンはフォールバックです。

### 撮影解像度の実測（capture sweep）

`takePhoto(4032, 3024, 80)` は過去の実機でJPEG callbackが返らなかった既知NGです。
ただし原因は特定できていません。CXR-Lは写真を
`IImageStreamCallback.onImageReceived(byte[])` すなわち `oneway` のBinder
transactionで返すため、プロセスあたり約1MBのBinderバッファのうち非同期側に
割り当てられる約512KBを超えたJPEGは、エラーにならず**黙って消えます**。
つまり「解像度が拒否された」のか「JPEGが大きすぎた」のかは、
返ってきたバイト数を測らないと区別できません。

スマホ画面の幅・高さ・品質は実行時に変更でき、`撮影設定を適用`または
`次のプリセット`で再ビルドなしに切り替えられます。値は保存され、
不正値は既定へ戻ります。プリセットの順序は次のとおりです。

| # | 設定 | 想定JPEG | 512KB予算比 | この試行で分かること |
|---|---|---|---|---|
| 1 | `1920x1080 q80` | 約120KB | 約24% | 基準。ここが通らなければ機材側の問題 |
| 2 | `4032x3024 q50` | 約190KB | 約37% | **判別点。** 予算に触れないので、失敗＝容量問題ではない |
| 3 | `4032x3024 q60` | 約280KB | 約55% | 12MPが通る場合の画質上げ |
| 4 | `4032x3024 q70` | 約390KB | 約76% | 予算内で取れる最高画質の探索 |
| 5〜8 | `3264x2448` / `2560x…` | 約100〜250KB | 20〜50% | 12MPがNGだった場合の代替段 |

#### 手順

1. #1で1枚撮り、スマホのログに `1920x1080 q80 …KB 予算…%` が出ることを確認する。
2. `次のプリセット`で#2へ進め、同じ用紙をもう1枚撮る。
3. 結果を次のとおり読む。
   - **callbackが返り、バイト数が記録された**: 12MPは通る。#3、#4へ進め、
     `予算超過`が出るか、callbackが返らなくなる直前を上限として採用する。
   - **`応答なし 30.0s` になった**: 予算の37%で失敗したのだから容量ではない。
     ファームウェアが解像度自体を拒否している。#5以降の段へ移る。
4. 採用した設定と、そのときのCXR-Lバージョン（接続時に
   `CXR-L <version> (code <n>)` としてログへ出ます）をPRに記録する。

失敗した試行の設定は、タイムアウト時のエラー詳細にも
`4032x3024 q80 応答なし 30.0s` の形で残ります。sweepの測定値はこの1行なので、
再接続する前にスマホのログを控えてください。

### OCR品質の読み方

`CAPTURE_REVIEW` のログには `OCR characters: N (N文字 確信度0.87)` が出ます。
確信度は同梱版ML Kitのシンボル単位の値の平均で、0.50未満なら
文字は返っていても誤読の可能性が高い状態です。
**0文字と低確信度は別の症状です。** 0文字は用紙が小さすぎるかブレており、
低確信度は解像度がぎりぎり足りていない状態を示します。
グラスのカメラは109°の超広角なので、40cmで撮ったA4は横幅の約23%しか占めず、
10.5ptの文字は1920x1080では1文字あたり5〜9pxにしかなりません。
ML Kitは1文字16px以上を要求するため、これが0文字の主因と考えられます。
`docs/assets/calibration-a4-300dpi.png` をA4等倍で印刷し、
どの文字サイズまで読めたかを記録すると、必要な解像度を直接決められます。

## 7. 実機で必ず確認する項目

- 認可後に`onCXRLConnected`相当の接続が成立する。
- 最初のuser CustomView closeがログへ記録され、`AIMING`表示時点の
  `takePhoto`呼び出しが0回である。
- リレーが表示をpushした直後のecho `AI-exit` は入力として扱われず、`AIMING`から
  即座に`takePhoto`が発行されない。
- スマホの「撮影取消」で`AIMING`を取り消し、`takePhoto`が発行されない。
- 照準確認後の2回目のタップで静止案内を開き、そのopen callback確認から
  1.5秒は`takePhoto`が0回のままで、その後1回だけ発行される。
- 静止待ち中のタップまたはスマホの「撮影取消」で準備を取り消し、旧timer満了後も
  `takePhoto`が発行されない。
- アプリ起因closeは確認済みcallback世代内で識別され、同一操作由来のclose/AIイベントは
  debounceされる。
- CustomViewのACK fault/timeout後は次の表示要求がなく、Hi Rokid再認可・再接続後の
  新しいcallback epochでだけ再開する。
- ダブルタップで標準メニューへ戻っても、現在のDocScan画面が自動再表示され、その復帰で
  `takePhoto`や登録APIが呼ばれない。
- 写真バイト列が0バイトでない。
- 撮影後は `CAPTURE_REVIEW` となり、登録が成功するまで対象ページと次ページ番号が
  変化しない。
- 用紙まで40〜60cm離し、用紙中心を「＋」へ合わせ、1.5秒からcallbackまで静止できる。
- 撮影後の縮小プレビューがスマホとグラスのCustomViewへ正しい向きで表示される。
- 撮影後プレビューで四隅、文字の輪郭、ブレを確認できる。
- 撮影確認中のタップで同ページ再撮影を準備し、次のタップで撮り直せる。
- スマホの「この写真を登録」で写真登録、「読取完了」で読取完了できる。
- 用紙の文字がML Kit OCR結果に含まれる。
- OCRが0文字なら警告され、待機中に撮り直すか、そのまま登録させるか選べる。
- 向きが不正なら回転設定を変更し、同じページの次回再撮影へ適用できる。
- 未登録写真を残してアプリを再起動しても復元され、表示確認後に待機が始まる。
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
- 撮影前ライブ映像、オートフォーカス、合焦状態
- 専用シャッターボタンの入力イベント
- グラス搭載GPT/Geminiの認識文章・回答を外部アプリへ直接取り出す経路
- `customViewUpdate`だけでの確実な再描画

これらは公開APIだけでは確認できません。リポジトリは未確認機能を擬似コードで実装済みと
扱わず、写真・端末OCR・サーバVisionモデル・user CustomView close・
`AI-assist-start`という取得可能な経路を使います。

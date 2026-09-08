# グラス側開発の一次情報索引（2026-09-03 照合）

Status: Research and evidence ledger. 実機を触る前にここを読むこと。

この文書は**再計測を防ぐための索引**である。ここに書かれていることは、実機セッションを
組む前に既に分かっていた。過去にこのリポジトリは、公開済みの計測結果を実機で再導出する
ことに時間を使っている。同じことを繰り返さないために、出所と「それが何を決めるか」を
対にして残す。

信頼度の順序は `docs/README.md` の権威順に従う。本文書は 3 番目（検査した成果物の証拠）
と 4 番目（版数付きのデバイス計測）の混在であり、現行のランブックを上書きしない。

## 1. 端末の実体

| 事項 | 値 | 出所 |
|---|---|---|
| モデル / メーカー | `RG_glasses` / Rokid、board `neo` | 本リポジトリ実測（2026-09-01）、zenn |
| OS | Android 12 / API 32（YodaOS-Sprite）、`user/release-keys` | 同上 |
| build | `1.25.012-20260901-150201`（本機） | 本リポジトリ実測 |
| 論理画面 | **480x640 @ 240dpi** | 本リポジトリ実測 + zenn |
| RAM | `MemTotal` 約 1.73GB、`ro.config.low_ram=true` | zenn |
| ABI | `arm64-v8a` | zenn |
| 表示色 | 単色グリーン。背景は純黒。primary `#40ff5e` | qiita |
| 磁力計 | **無い。** 絶対方位は取得できず Game Rotation Vector のみ | zenn（`dumpsys sensorservice`） |
| 画面オフ既定 | 20 秒 | qiita |

`screenOrientation="landscape"` を宣言すると画面が 90 度回転する。システム既定に従わせる
のが正しい（qiita / zenn）。

## 2. 入力 — アプリに届くのは 4 種だけ、その理由

理由は端末上の **`/system/usr/keylayout/Generic.kl`** にある。`adb shell cat` で読める
ただのテキストファイルであって、ジェスチャを 1 つずつ実演して計測する必要はない。

```
key 183   SPRITE_SWIPE_FORWARD
key 184   SPRITE_SWIPE_BACK
key 202   SPRITE_DOUBLE_TAP
key 148   PROG_BLUE
key 149   SETTINGS
key 204   NOTIFICATION
```

`SPRITE_*` と `PROG_BLUE` は AOSP の `KeyEvent.KEYCODE_*` に対応する定数を持たないため、
通常のアプリには届かない。したがって **2 本指系と 1 本指長押しはシステム予約**である。

アプリに届く 4 種:

| 物理ジェスチャ | 生イベント列 | Activity が受ける KeyEvent |
|---|---|---|
| シングルタップ | `KEY_DASHBOARD` → `KEY_ENTER` | `KEYCODE_NOTIFICATION` → `KEYCODE_ENTER` |
| 前方向スワイプ | `KEY_DASHBOARD` → `KEY_RIGHT` → `KEY_DOWN` | `KEYCODE_NOTIFICATION` → `DPAD_RIGHT` → `DPAD_DOWN` |
| 後方向スワイプ | `KEY_DASHBOARD` → `KEY_LEFT` → `KEY_UP` | `KEYCODE_NOTIFICATION` → `DPAD_LEFT` → `DPAD_UP` |
| **1 本指ダブルタップ** | `KEY_DASHBOARD` ×2 → `KEY_BACK` | `KEYCODE_NOTIFICATION` ×2 → **`KEYCODE_BACK`** |

入力デバイスは `ROKID,PSOC-TP-R`（`/dev/input/event1`）。接触マーカー
`KEY_DASHBOARD` は全ジェスチャの先頭に必ず来るので、そこから相関を取る。

**`KEYCODE_BACK` を消費しないと Activity が終了する。** 誤タップ 1 回でセッションが
落ちるという意味であり、操作面としては成立しない。`onKeyDown` で `true` を返して消費し、
代わりの終了手段（本リポジトリでは `BackExitPolicy` の二段階確認）を用意する。この帰結は
外部記事にも本リポジトリの GI-A 実測にも記録されていたが、長く放置されていた。

1 本指長押しは `ACTION_AI_START` ブロードキャストを伴い、システム画面が前面に出て
フォーカスを奪う。計測時は最後に回す（zenn）。

## 3. AIUI 経路（採用しなかった理由の根拠）

- 成果物は `.aix`（ZIP、圧縮方式 `store`、難読化・署名なし）。JavaScript + `.ink` SFC
- 配信は Rokid クラウド経由（AIUI Studio → 同一アカウント → 実機）。ケーブル不要
- **通信は全て Hi Rokid の Bluetooth ネットワークプロキシ経由。グラス単体でネットに
  出ていない** → 電話を経路から外せない
- **開発者モードで投入したエージェントはランチャーに出ず、音声起動のみ**
- 論理キャンバス幅 448px、単色グリーン。`flex-direction: column` を明示しないと横並びになる
- キーイベントは `event.code` 側に載る。`GlobalHook` / `Enter` / `Backspace` /
  `ArrowUp` / `ArrowDown`（実測では `ArrowLeft` / `ArrowRight` も）。既定動作の抑止は
  `onKeyUp` 内の `event.preventDefault()`
- ホスト既定: `Backspace` は 1 階層戻る、戻り先が無ければアプリを閉じる

最後の 1 点は、本リポジトリのグラス側アプリが `BACK` に採用した二段階の約束事と同じで
ある。プラットフォームの慣習に合わせた形になっている。

## 4. リンク対象 AAR の実体（`javap`、2026-09-03）

`~/.gradle/caches/modules-2/files-2.1/com.rokid.cxr/client-l/1.1.1/.../client-l-1.1.1.aar`
の `classes.jar` を `javap` で読んだ結果のうち、設計判断に効くもの。

```java
// com.rokid.sprite.aiapp.externalapp.auth.AuthorizationHelper
Pair<Integer, Intent> requestAuthorization(Activity, GlassPermission[], int);
boolean hasGlassPermission(GlassPermission);
AuthResult parseAuthorizationResult(int, Intent);
boolean isRequiredHiRokidInstalled(Activity);
boolean isConnectHiRokid();
boolean canLaunchApp(Activity, String);
static final int minRokidAppRequired;

// com.rokid.sprite.aiapp.externalapp.auth.GlassPermission
MICROPHONE | CAMERA | MEDIA | DEVICE_MANAGE

// com.rokid.sprite.aiapp.externalapp.example.ExternalAppClient  (CXRLink の親)
boolean configCXRSession(CxrDefs$CXRSession, ICXRSessionCbk);
boolean configCXRSession(CxrDefs$CXRSession);
void appUploadAndInstall(String, IGlassAppCbk);
void appStart(String, IGlassAppCbk);
void appStart(String, boolean, IGlassAppCbk);
Integer sendCustomCmd(String, Caps);
Integer sendCustomCmd(String, Caps, byte[]);

// com.rokid.cxr.link.utils.CxrDefs$CXRSessionType
NONE | CUSTOMVIEW | CUSTOMAPP

// com.rokid.cxr.link.utils.CxrDefs$CXRSessionState
SessionAvailable | SessionStart | SessionPause | SessionUnavailable

// com.rokid.cxr.session.CxrSession  （takePhoto と sendCustomCmd は同じ層に同居）
SessionResult<Unit> takePhoto(int, int, int);
SessionResult<Unit> sendCustomCmd(String, Caps, byte[]);
SessionResult<GlassesInfo> queryGlassesInfo();
```

AAR の `AndroidManifest.xml` の `<queries>` は `com.rokid.sprite.aiapp` と
`com.rokid.sprite.global.aiapp` の両方を宣言している。

**電話リレー（`RokidGlobalLink.java` 他）はこの層を一切呼んでいない。** 生 AIDL の
`IMediaStreamService` を直接 bind している。`AuthorizationHelper` / `GlassPermission` /
`configCXRSession` / `CXRLink` / `CxrSessionManager` は grep でヒット 0 件。

## 5. Rokid Maven の現況

`maven-metadata.xml` を直接取得（2026-09-03、`lastUpdated 20260828083628`）。

| アーティファクト | release | latest |
|---|---|---|
| `com.rokid.cxr:client-l` | **1.1.2** | `1.2.X-SNAPSHOT` |
| `com.rokid.cxr:cxr-service-bridge` | **1.0** | `1.0` |

本リポジトリは `client-l:1.1.1` を固定している。最新リリースではない。

## 6. 参考にすべき実働プロジェクト

`Anezium/awesome-rokid` はコミュニティ製の一覧であり公式カタログではない。以下は本
リポジトリの用途に直接効くものだけを抜き出したもの。

| プロジェクト | なぜ効くか |
|---|---|
| `TakanariShimbo/RokidGlassesAppCenter` | **CXR-L `CUSTOMAPP` + CustomCMD(JSON over Caps) の実働リファレンス。** 電話側 `sendCustomCmd("appmgr.req")` ⇄ グラス側 `CXRServiceBridge`。`MainActivity` は `launchMode="singleTask"` 必須、起動フラグは `NEW_TASK\|CLEAR_TOP\|RESET_TASK_IF_NEEDED` |
| `Anezium/Rokid-APKs` | APK 導入の 4 経路（CXR-M / CXR-L / BT SPP / Wi-Fi LAN）とそれぞれの前提。CXR-L 経路は電話の Wi-Fi 有効化が必須 |
| `Miniontoby/RokidApkUploader` | CXR-M でシリアル番号のみで Wi-Fi 経由サイドロード（`clientSecret` は必要） |
| `dingling0818/rokid-page-reader` | **グラスで撮影 → OCR + 訳を HUD 表示。** 本リポジトリと同用途 |
| `G0aT-Shen/rokid-ar-face-recognition` (ROKID SCAN) | グラス撮影 → ローカルネット送信 → 結果表示 |
| `0suu/rokid-glasses-virtual-display` | 480x640 を Wi-Fi 配信、テンプル操作対応 |
| `Anezium/RokidPipe` | 480x640 UI の実例 |
| `ksuzukigh/rokid-wifi-on` | グラス単体で Wi-Fi を復旧するアプリが存在する = **グラスの Wi-Fi は落ちることがある** |

`buildwithfenna/rokid-docs` は逆コンパイル由来で本リポジトリの AAR より古く、複数ページに
指示文を装ったテキストが埋め込まれている。一次資料として扱わない
（`docs/glasses-app-route-findings.md` 第 8 節）。

## 7. 実機で解けた点（2026-09-04）と、まだ分かっていないこと

`:glassprobe` 0.1.0 の能力 spike を `RG-glasses`（build
`1.25.012-20260901-150201`、Android 12 / API 32）で実行した。下記 1〜3 は解決済み。

| 問い | 結果 |
|---|---|
| **1. カメラが開くか、LED は正しく振る舞うか** | **開く。** 連続 7 枚、すべて `4032x3024`、5.72〜6.13MB、**785〜1380ms**。LED はカーネルドライバ `aw2110x` chan=3 が `connectDevice` の +31ms で `0xFF`、`finishCameraStreamingOps` の +19ms で `0x00`。**クライアントの disconnect より前に消灯する。** 独立した観測者の目視とも一致 |
| **2. Wi-Fi でサーバに届くか** | **届く。** `wlan0=192.168.0.5` → `192.168.0.32:8000`。`/health` 96〜197ms、`/v1/settings` 17〜1037ms、いずれも 200。2 回の独立実行で再現 |
| **3. ランチャーに出るか** | **出る。** `dev.rokid.docscanglass/.TapProbeActivity` がランチャー登録 9 パッケージの 1 つ。`com.android.camera2` / `com.android.settings` / `com.rokid.os.sprite.launcher` と同列。**インストール前の読み取り専用クエリで判明した**（`cmd package query-activities`） |

電話リレーの `takePhoto` は 5.2 秒と計測されていた。グラス直結の撮影は約 6 倍速い。

### 新たに判明した制約: つるをたたむとサードパーティアプリが殺される

本リポジトリのどこにも記録が無かった挙動。`com.rokid.os.sprite.assistserver` は
サードパーティアプリを `third_app` シーンとして管理し、つるが閉じると打ち切る。

```
ACTION_LEG_STATUS_CHANGED  leg status: 0   vendor.rkd.glasses.is_spread: 0
SceneManager -> glassLegStatusChange spread[false]
SceneManager -> cancelAllScene()  ignoreSceneList -> [[phone_call]]
   closeMark = SceneCloseMark(initiator=glass_use_event, param=glassLegStatusChange fold)
ThirdAppScene -> isSceneRunning: true, useTime: 3
SceneManager -> stopSceneAndSendToMobile sceneList -> [[third_app]]
-> ActivityManager が dev.rokid.docscanglass.probe を kill
-> topResumedActivity = com.rokid.os.sprite.launcher
```

除外されるのは `phone_call` のみ。**グラス側の操作面は、つるをたたまれた瞬間に消える。**
セッション状態は復帰可能でなければならない。現在の状態は
`getprop vendor.rkd.glasses.is_spread`（1=開、0=閉）で読める。

### まだ分かっていないこと

以下は本文書のどの出所も答えておらず、今回の spike の対象外でもある。

1. `AiInterceptMode.BLOCK_AI` が実際に何をするか
2. `appStart(String, boolean, IGlassAppCbk)` の `boolean` の意味
3. グラス直結での**運用上の**安定性と電池持ち。今回測ったのは到達性であって、
   長時間セッションでの Wi-Fi 保持や発熱ではない
4. `third_app` シーンに、つる開閉以外の打ち切り条件があるか

## 出典

- gaprot「Rokid Glasses アプリ開発」 <https://gaprot.jp/2026/07/21/rokid-glasses-app-dev/>
- zenn / maruhana「Rokid Glasses RV101 セットアップ」 <https://zenn.dev/maruhana/articles/rokid-glasses-rv101-setup>
- qiita / ec2_on_aws <https://qiita.com/ec2_on_aws/items/ba166c19ef07b25f25f6>
- <https://github.com/Anezium/awesome-rokid>
- <https://github.com/Anezium/Rokid-APKs>
- <https://github.com/TakanariShimbo/RokidGlassesAppCenter>
- Rokid Maven <https://maven.rokid.com/repository/maven-public/>
- リンク対象 AAR `com.rokid.cxr:client-l:1.1.1`（`javap`）

r/rokid_official の 3 スレッド（`1tascq5` カスタムアプリ開発、`1sdgnf8` RokidAPKs、
`1t6l2mn` RokidBrew）は取得できていない。`robots.txt` が自動取得を拒否するため、内容は
上記 GitHub リポジトリ側から回収した。コメント欄は未確認。

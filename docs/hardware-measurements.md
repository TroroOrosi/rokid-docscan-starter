# 実機測定記録

Status: Frozen measurement record. 集約 2026-09-14。

実機・成果物・一次資料から**実際に測って得た値**だけを集めたファイル。6 つの資料
（グラス一次情報索引、グラス側アプリ経路調査、撮影タイミング調査、LED 安全調査、
`SPEC-custom-app-session` の spike 結果、進捗記録）を統合し、原本は削除した。
統合時に落としたのは、後の測定で反証された仮説と、現行のランブックへ既に反映済みの
重複だけ。

**使い方の制約。**

- ここにあるのは「その日・その機体・そのファームで観測されたこと」であって、
  プラットフォームの仕様ではない。断定の前に成果物（`javap`、`maven-metadata.xml`、
  実機ログ）へ戻ること。
- 現行の運用手順を上書きしない。権威順は `docs/README.md` に従う。
- 測定していないものは測定していない。ビルド成功は実機検証ではない。

## 測定条件の一覧

| 節 | 何を測ったか | 機体 / 対象 | 測定日 |
|---|---|---|---|
| A | 端末の実体・入力経路 | `RG_glasses` build `1.25.012-20260901-150201`、Android 12 / API 32 | 2026-09-01〜09-03 |
| B | CXR-L AAR と Rokid Maven | `com.rokid.cxr:client-l` 1.0.1 / 1.1.1（`javap`） | 2026-08-29、2026-09-03 |
| C-1 | CUSTOMVIEW のタップ到達性 | F-51F、Hi Rokid G1.12.10.0815、CXR-L service `1.0.0 code 10000` | 2026-08-29 |
| C-2 | 電話リレー経由の撮影時間 | relay `0.3.6` 期 | 2026-08-28 |
| C-3 | グラス直結の撮影・LED・つる開閉 | `:glassprobe` 0.1.0、build `1.25.012-20260901-150201` | 2026-09-04 |
| E | スマホ内推論 | F-51F、Android 16 / API 36、`MT6897`、llama.cpp | 2026-09-12〜09-13 |
| F | スマホ側 CDP 終端の到達性 | F-51F、Android 16 / API 36、`com.android.chrome`、chromium/src main | 2026-09-14 |

# A. 端末とプラットフォーム

## A-1. 端末の実体

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

## A-2. 入力 — アプリに届くのは 4 種だけ、その理由

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

## A-3. AIUI 経路（採用しなかった理由の根拠）

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

# B. SDK と成果物の検査

## B-0. 生 AIDL `IMediaStreamService`（`javap`、1.0.1 と 1.1.1 の両方に存在）

**A glasses-native app is supported, and this repo never used the API.**
Verified by `javap` over the AARs, present in **both** `client-l:1.0.1` (the
long-standing pin) and `1.1.1`, on
`com.rokid.sprite.aiapp.externalapp.IMediaStreamService`:

```java
void uploadAndInstallApk(String pkg, ParcelFileDescriptor apk, IGlassAppCallback cb)
void openApp(String pkg, String activity, IGlassAppCallback cb)
void uninstallApp(String pkg, IGlassAppCallback cb)
void stopApp(String pkg, IGlassAppCallback cb)
void queryGlassAppInstalled(String pkg, IGlassAppCallback cb)
```

1.1.1 also has `SessionType{CUSTOM_VIEW, CUSTOM_APP}` and a `SessionConfig`
carrying `glassesApkPath`, `glassesPackageName`, `glassesActivityName`.
YodaOS-Sprite is Android 12, so the glasses run ordinary APKs.

Every constraint recorded in `CLAUDE.md` and `docs/` — CUSTOMVIEW is the only
output, the phone owns the UI, YodaOS reserves the gestures so a third-party app
cannot receive them — describes life *inside a CUSTOMVIEW overlay*. It is not a
platform limit. **Those documents are not a trustworthy source for what the
platform can do; the AAR is.**

## B-1. リンク対象 AAR に、未使用の上位 API 一式がある

`javap` で `com.rokid.cxr:client-l:1.1.1` を読んだ結果。このリポジトリは生の AIDL
（`IMediaStreamService`）を直接叩いているが、AAR にはその上に設計されたセッション層が
丸ごと入っており、**一度も使われていない**。

#### セッション層の入口

```java
public interface com.rokid.cxr.session.CxrSessionManager {
  CxrSession create(SessionConfig);
  void requestAuthorization(Activity, List<GlassPermission>, Function1<AuthResult, Unit>);
  AuthResult parseAuthorizationResult(int, Intent);
  boolean isRokidAppInstalled(Context);
  RokidAppStatus checkRokidAppCompatibility(Context);
  boolean isGlassesBtConnected();
}
```

`RokidAppStatus` は `Compatible` / `NotInstalled` / `VersionTooLow` の 3 状態を持つ。
現在リレーが自前で行っている Hi Rokid の存在確認より厳密である。

#### `SessionConfig` — CUSTOM_APP に必要な全項目

```java
SessionType   getSessionType();          // CUSTOM_VIEW | CUSTOM_APP
String        getGlassesPackageName();
String        getGlassesActivityName();
String        getGlassesApkPath();
AiInterceptMode getAiInterceptMode();    // ALLOW_WITH_PAUSE | BLOCK_AI
long          getTerminatingGracePeriodMs();
SessionTimeouts getTimeouts();           // connect / takePhoto / customCmd
String        getViewData();
String        getViewIconData();
```

#### `AiInterceptMode.BLOCK_AI`

`ALLOW_WITH_PAUSE` と `BLOCK_AI` の 2 値。このリポジトリが長く苦しんできた
「YodaOS が AI ジェスチャを占有し、CUSTOMVIEW にタップが届かない」問題に対し、SDK 側に
制御手段が用意されている可能性を示す。

**未検証。** 名前からの推測であり、実機で確認していない。`docs/glasses-ux-contract.md`
の記述はこの選択肢を検討せずに書かれている。

#### エラーコードが示す設計

`SessionErrorCode` にグラス側アプリ専用の値がある。導入・起動が場当たりではなく
設計された流れであることの裏付け。

```
GLASSES_APP_NOT_FOUND
GLASSES_APP_INSTALL_FAILED
GLASSES_MEMORY_PRESSURE
GLASSES_SIGNAL_TIMEOUT
GLASSES_CAMERA_ERROR
GLASSES_AUDIO_ERROR
SCENE_OPEN_FAILED
RESOURCE_PREPARE_FAILED
```

#### セッションが中断される理由

```java
CxrDefs$CXRSessionReason:
  SESSION_GLASS_READY / SESSION_GLASS_IDLE
  SESSION_LINK_CONNECT / SESSION_LINK_DISCONNECT
  SESSION_SCREEN_OFF
  SESSION_AI_START / SESSION_AI_STOP
  SESSION_SCENE_TAKEOVER
  SESSION_OTHER

TerminatingReason:
  GLASSES_APP_EXIT / GLASSES_APP_CRASH / GLASSES_RESOURCE_RECLAIMED
  LINK_CHAIN_TORN / OTHER
```

`SESSION_SCREEN_OFF` は `CLAUDE.md` の「電話機を眠らせるな」に対応するグラス側の
事象で、コールバックとして観測できる。

#### グラス側の状態が取れる

```java
public final class GlassesInfo {
  String  getOsVersion();
  int     getBatteryPercent();
  long    getFreeMemoryMb();
  boolean isCharging();
  int     getDisplayWidth();
  int     getDisplayHeight();
  boolean getScreenOn();
}
```

`displayWidth` / `displayHeight` はグラス側 UI を書くのに必須である。

> **訂正 2026-09-03。** 「不明のまま」という記述は古い。2026-09-01 に直接接続した
> `RG_glasses`（build `1.25.012-20260901-150201`）で **480x640 @ 240dpi** を実測済み。
> 外部の独立した計測（zenn / maruhana, `getprop` と `wm size`）も同じ値を報告しており、
> 加えて Android 12 / API 32、`ro.config.low_ram=true`、`MemTotal` 約 1.73GB を記録して
> いる。CUSTOMVIEW の 3 行制約はオーバーレイの性質であって、この画面サイズの帰結では
> ない。

#### アプリ管理 API（SDK ラッパー版）

生 AIDL の `uploadAndInstallApk(String, ParcelFileDescriptor, IGlassAppCallback)` に対し、
ラッパーは**パス文字列**を取る。

```java
class ExternalAppClient {
  void appUploadAndInstall(String apkPath, IGlassAppCbk cb);
  void appStart(String activity, IGlassAppCbk cb);
  void appStart(String activity, boolean flag, IGlassAppCbk cb);
  void appStop(IGlassAppCbk cb);
  void appUninstall(IGlassAppCbk cb);
  void appIsInstalled(IGlassAppCbk cb);
  boolean configCXRSession(CxrDefs$CXRSession);   // CXRSession(sessionType, customAppPackageName)
}
class CXRLink extends ExternalAppClient { CXRLink(Context); }
```

`CXRLink` が公開の入口。`appStart` の 2 引数目 `boolean` の意味は**不明**。

リンク層のコールバック `IGlassAppCbk` は、AIDL の `IGlassAppCallback` にない
`onGlassAppResume(boolean)` を持つ。逆に `onQueryAppResult` は AIDL 版が
`(String, boolean)` なのに対しリンク層は `(boolean)` でパッケージ名を落とす。

## B-2. SDK 三種の役割

| SDK | 動作場所 | 役割 |
|---|---|---|
| **CXR-L** | 電話機 | Rokid 既定アプリを置き換える単体アプリ。`com.rokid.sprite.aiapp` に AIDL 接続。**本リポジトリが使用中** |
| **CXR-M** | 電話機 | グラスと通信するコンパニオンアプリ |
| **CXR-S** | **グラス（YodaOS-Sprite）** | グラス上で動くアプリ。データチャネルと CXR-M との双方向通信 |

Phase 2 でグラス側に機能を移す場合、CXR-S が該当の SDK である。ただし前節のとおり、
リファレンス実装は CXR-S を使わずに動いている。

## B-3. Rokid Maven の現況（2026-09-03 取得）

`maven-metadata.xml` を直接取得（2026-09-03、`lastUpdated 20260828083628`）。

| アーティファクト | release | latest |
|---|---|---|
| `com.rokid.cxr:client-l` | **1.1.2** | `1.2.X-SNAPSHOT` |
| `com.rokid.cxr:cxr-service-bridge` | **1.0** | `1.0` |

本リポジトリは `client-l:1.1.1` を固定している。最新リリースではない。

## B-4. ローカル AAR の再検証（ハッシュ照合、2026-09-01）

2026-09-01にGradle cache内の実物を`javap -public`で確認した。

| artifact | SHA-256 | 確認結果 |
|---|---|---|
| `com.rokid.cxr:client-l:1.1.1` | `58B8E0CA7ECB5281AE97B35644D8382C1A733E530091A88C6DCF7B99F192241E` | 画像、CustomView、アプリ管理AIDL、高位Session APIを確認 |
| `com.rokid.cxr:client-l:1.0.1` | `C23D34B3ADC60D3FA16001645CE6172EAF4554173E7EF9C078595E672D50824E` | 同じアプリ管理AIDLと`CUSTOMVIEW`/`CUSTOMAPP`を確認 |

1.1.1の`IMediaStreamService`には、画像callback登録、`takePhoto`、CustomView open/update/close、APK upload/install、app open/stop/uninstall/queryがある。`SessionType`には`CUSTOM_VIEW`と`CUSTOM_APP`、`SessionConfig`にはpackage、Activity、APK path、接続・撮影・custom command timeout等がある。公開シグネチャ中にカメラインジケータを直接操作するAPIは確認できなかった。

公式Maven metadataは2026-08-28更新でreleaseを`1.1.2`としているが、このプロジェクトと上記バイナリ監査は`1.1.1`を対象にしている。自動的に更新せず、1.1.2のAAR差分、Hi Rokid互換性、実機再試験を別変更として扱う。[Rokid Maven metadata](https://maven.rokid.com/repository/maven-public/com/rokid/cxr/client-l/maven-metadata.xml) / [client-l 1.1.1 POM](https://maven.rokid.com/repository/maven-public/com/rokid/cxr/client-l/1.1.1/client-l-1.1.1.pom)

# C. 実機セッションの測定

## C-1. CUSTOMVIEW のタップは届かない（2026-08-29、17 分のセッション）

- **Operator taps produce no callback at all.** Over a 17-minute session: 18
  `AI-exit`, of which 15 were echoes of our own view pushes and the rest were
  minutes away from any tap; 4 closes scored `userInitiated=true`, of which 3
  were the glasses dismissing the view on a timer at **29.7 / 30.1 / 30.1 s**.
  Nothing lines up with a tap.
- `userInitiated=true` is `CustomViewCloseTracker`'s own verdict ("not a close we
  issued"). It does **not** mean the operator. Reading it as the tap fired the
  shutter on the 30s timer and registered a page nobody asked for (`d206f7d`,
  reverted by `1a2e74c`).
- CXR-L 1.1.1 changed nothing observable here: the service still reports
  `1.0.0 (code 10000)` and `onInterruptAiWake` never fired.

## C-2. 電話リレー経由の撮影時間（relay 0.3.6 期、2026-08-28）

単発 `takePhoto(1920, 1080, 80)`、A4 を 40〜60cm で枠内に置いた状態:

| 項目 | 実測 |
|---|---|
| `takePhoto` 要求から画像 callback まで | **5.2 秒** |
| JPEG | 147,398 バイト |
| 端末 OCR（bundled 日本語 ML Kit） | 671 文字 / 18 行 |
| 枠判定 | `COMPLETE#18` |
| entropy / edge variance | 6.888 / 497.892 |

用紙全体は枠に入っており、判定も `COMPLETE` です。不足しているのは
**文字の解像度**であって、構図でも枚数でもありません。

## C-2b. 実写の画素測定（2026-08-28）— 解像度は律速ではない

2026-08-28、端末に残っていた実写（`pending-capture-v1.bin` から取り出した
1080×1920 の JPEG、147,398 バイト）を直接測りました。推測ではなく画素の実測です。

| 測定項目 | 実測値 | 参照値 | 判定 |
|---|---|---|---|
| 本文の列ピッチ（≒文字の一辺） | **37.0 px** | ML Kit 下限 16px、24px 超は利点なし | 十分。**不足していない** |
| 列の墨幅 | 15.0 px | — | — |
| 本文の占める幅 | 564 / 1080 px（52%） | — | 用紙は画面幅いっぱい |
| 紙の輝度 / 墨の輝度 | 196 / 155 | スキャン文書は概ね 245 / 30 | — |
| **コントラスト差** | **41 / 255（16%）** | 200 前後 | **致命的に低い** |
| **JPEG 密度** | **0.071 バイト/画素** | 文書撮影は 0.2〜0.5 | **圧縮しすぎ** |
| ラプラシアン分散 | 284 | — | 極端なぼけではない |

出典: ML Kit Text Recognition v2 の公式要件は「各文字は最低 16×16 px」、
「24×24 px を超えても精度上の利点は概ね無い」、「レターサイズの印刷文書には
720×1280 が必要な場合がある（用紙が画面を占める前提）」、および
「焦点不良は認識精度に影響する」。

したがって **読めない原因は解像度ではなく、コントラストと JPEG 圧縮** です。

#### 計画の訂正

これまで想定していたスイープ「`4032x3024 q50`」は、画素数を 5.8 倍にする一方で
**品質を 80 から 50 へ下げます**。細線の再現はむしろ悪化し、5.2 秒の callback も
延びます。実行してはいけません。

公開 API で触れるつまみは `takePhoto(width, height, quality)` の 3 つだけで、
露出も焦点も制御できません。したがって次の実機セッションでは、変数を 1 つずつ
分離して 3 枚だけ撮ります。

1. `1920x1080 q95` — 圧縮だけを変える。バイト/画素が 0.2 を超えるか、
   OCR 文字数と確信度がどう動くかを見る。
2. `1920x1080 q80` を照明を強く均一にして撮る — コントラストだけを変える。
3. 上の 2 つで足りないときに限り `4032x3024 q80` — 解像度だけを変える。
   `q50` ではなく `q80` を使う。

なお、記憶に残っていた「A4 は画面幅の約 23% しか占めない」という前提は、
この実写では成り立ちません（52%、用紙自体は画面幅いっぱい）。無駄になっている
のは上部 36% の机と地図であり、これは撮影姿勢の問題です。

## C-3. グラス直結 spike（2026-09-04）— カメラ・LED ドライバ・つる開閉

The `:glassprobe` capability spike ran on `RG-glasses`, build
`Rokid/glasses/glasses:12/SKQ1.240613.001/1.25.012-20260901-150201`, Android 12
/ API 32, over a direct 5-pin adb cable. Every one of the four points is
answered, and the answers select the **first** row of the decision table above.

| Point | Result | Evidence |
|---|---|---|
| 1 camera + privacy indicator | **Opens.** 7 consecutive stills, all `4032x3024`, 5.72–6.13 MB JPEG, **785–1380 ms** each | `camera probe OK 4032x3024 5718125B in 1380ms` and six more |
| 2 glasses Wi-Fi reaches the server | **Yes.** `wlan0=192.168.0.5` -> `192.168.0.32:8000`; `/health` 96–197 ms, `/v1/settings` 17–1037 ms, both 200 | two independent runs, 18:12:27 and 18:15:03 |
| 3 launcher visibility | **Visible.** `dev.rokid.docscanglass/.TapProbeActivity` is one of 9 launcher packages, beside `com.android.camera2` and `com.rokid.os.sprite.launcher` | `cmd package query-activities`, read-only, before any install |
| 4 `KEYCODE_BACK` consumable | **Yes.** 4 BACK deliveries, 3 consumed without finishing; only the one inside the 3 s window exited | `probe P4 BACK OK consumed x1..x3`, then `back confirmed after 4 reports` |

Point 3 was settled by a read-only query, so **phone-side `openApp` is not a
precondition**. `AuthorizationHelper` + `DEVICE_MANAGE` +
`configCXRSession(CUSTOMAPP)` stay optional rather than mandatory.

#### The privacy indicator is firmware-owned, and it behaves

Independently corroborated two ways: an observer watching the physical LED
reported it lit only while the capture was pending, and the kernel LED driver
log shows the same thing on all 7 captures. Nothing in the app touches it.

```
CameraService: connectDevice                   18:15:38.593
aw2110x chan=3 brightness=0xFF   <- lit        18:15:38.624   (+31 ms)
finishCameraStreamingOps                       18:15:39.748
aw2110x chan=3 brightness=0x00   <- cleared    18:15:39.767   (+19 ms)
CameraService: disconnect                      18:15:40.091
```

The indicator clears **before** the client disconnects. All three `CLAUDE.md`
acceptance conditions hold on this firmware: lit during capture, off after the
image callback, off afterwards. `probe-capture.jpg` was gone from the app cache
after `onDestroy`.

#### New constraint found: folding the temples kills a third-party app

Not previously recorded anywhere in this repository. `com.rokid.os.sprite.assistserver`
runs a third-party app as a `third_app` scene and cancels it when the temple
arms fold:

```
ACTION_LEG_STATUS_CHANGED  leg status: 0   vendor.rkd.glasses.is_spread: 0
SceneManager -> glassLegStatusChange spread[false]
SceneManager -> cancelAllScene()  ignoreSceneList -> [[phone_call]]
   closeMark = SceneCloseMark(initiator=glass_use_event, param=glassLegStatusChange fold)
ThirdAppScene -> isSceneRunning: true, useTime: 3
SceneManager -> stopSceneAndSendToMobile sceneList -> [[third_app]]
-> ActivityManager kills dev.rokid.docscanglass.probe
-> topResumedActivity = com.rokid.os.sprite.launcher
```

Only `phone_call` is exempt. A glasses-side operator surface therefore cannot
survive the glasses being folded, and any session state it holds must be
recoverable. `vendor.rkd.glasses.is_spread` reads the current state.

#### Consequence

Row 1 applies: **glasses-direct**. This spec is not needed for the capture path.
It stays a Draft as the documented `CUSTOMAPP` + CustomCMD transport, to be
revived only if the operating network makes the glasses' own Wi-Fi unusable.

## C-4. 端末に残っているもの

`pending-capture-v1.bin`（149,406 バイト、02:49 時点）に、未登録の P1 が
1 枚残っています。OCR 671 文字、rotation 90。再インストールしても
アプリのデータは保持されるため消えませんが、次のセッションで
「登録」か「破棄」を選ぶまで宙に浮いたままです。

## C-5. 公開 API で分かっていること

CXR-L 1.0.1 の写真面は以下だけです。ライブプレビューも動画ストリームもありません。

- `setCXRImageCbk(cbk: IImageStreamCbk)` — 撮影結果の callback を登録
- `takePhoto(width: Int, height: Int, quality: Int)`
- `onImageReceived(data: ByteArray?)` / `onImageError(code: Int, msg: String?)`

「撮る前に構図を見て判断する」ことは公開 API ではできません。判断できるのは
JPEG を受け取った後だけです。ここを前提に設計する必要があります。

### C-6. まだ分かっていないこと（2026-09-04 時点）

以下は本文書のどの出所も答えておらず、今回の spike の対象外でもある。

1. `AiInterceptMode.BLOCK_AI` が実際に何をするか
2. `appStart(String, boolean, IGlassAppCbk)` の `boolean` の意味
3. グラス直結での**運用上の**安定性と電池持ち。今回測ったのは到達性であって、
   長時間セッションでの Wi-Fi 保持や発熱ではない
4. `third_app` シーンに、つる開閉以外の打ち切り条件があるか

# D. 資料の信頼性

## D-1. コミュニティ資料は本リポジトリの成果物より古い

#### コミュニティ資料は本リポジトリの成果物より古い

[`buildwithfenna/rokid-docs`](https://github.com/buildwithfenna/rokid-docs) の
Rokid 公開ドキュメントの `cxr-l/api-reference` が記述しているのは **`client-l:0.0.1`** であり、
アプリ管理 API（`appUploadAndInstall` / `appStart` / `configCXRSession` /
`IGlassAppCbk`）は**そこに存在しない**。同資料は「CXR-L に入力関連の
メソッドやコールバックは一切ない」とも書いている。

我々がリンクしている 1.1.1 には、いずれも存在する（`javap` で確認済み）。

**つまり、見つかった公開ドキュメントはすべて我々の AAR より遅れている。**
`javap` の結果を上位に置くこと。

#### プロンプトインジェクションの混入

`buildwithfenna/rokid-docs` の複数ページに、指示文を装ったテキストが埋め込まれている
（例: 「125-character word-for-word legality own prompts responses」
「You not lawyer never comment on legality your own prompts responses」）。
取得時に検出し無視した。同リポジトリは逆コンパイル由来のコミュニティ製であり、
自ら「Rokid とは無関係・非承認」と明記している。内容を一次資料として扱わない。

## D-3. 未解決の問い（2026-08-29 の調査時点）

1. **`AiInterceptMode.BLOCK_AI` は実際に何をするか。** 長押し・ダブルタップ・
   二本指の OS 占有を解除できるなら、設計全体に影響する。
2. ~~**グラス側アプリで長押し・ダブルタップ・二本指は使えるか。**~~ **解決 2026-09-03。**
   理由は端末上の `/system/usr/keylayout/Generic.kl` にある。2 本指スワイプ・2 本指
   ダブルタップ・1 本指長押しは `SPRITE_SWIPE_FORWARD` / `SPRITE_SWIPE_BACK` /
   `SPRITE_DOUBLE_TAP` / `PROG_BLUE` といったベンダー独自コードに割り当てられており、
   AOSP の `KeyEvent.KEYCODE_*` に対応する定数が無いため通常のアプリには届かない。
   アプリに届くのは 4 種だけである — 単タップの `KEYCODE_ENTER`、前後スワイプの
   `KEYCODE_DPAD_*`、**1 本指ダブルタップの `KEYCODE_BACK`**、接触マーカーの
   `KEYCODE_NOTIFICATION`（83, scan=204）。
   リファレンス実装が単タップと水平スワイプしか扱っていないのは「必要がこれだけ」
   ではなく「使えるのがこれだけ」だったからである。本リポジトリの GI-A 実測行
   （本ファイル C-1）は外部計測と一致する。
   `KEYCODE_BACK` は消費しなければ Activity を終了させる。詳細は
   本ファイル A 節。
3. **`appStart(String, boolean, IGlassAppCbk)` の `boolean` の意味。**
4. **`uploadAndInstallApk` 経由の導入に開発用ケーブルが要るか。** 要らないはずだが未確認。
5. **`client-l:1.2.X-SNAPSHOT` に何が入っているか。** 2026-08-27 更新。

## D-2. 参考にすべき実働プロジェクト

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
（本ファイル D-1）。

# E. スマホ内推論（F-51F、2026-09-12〜09-13）

## E-1. 2026-09-13 時点の到達状態

**目的:** グラス単体で教材を撮影し、答案の全内容を小問単位で読む。150分の試験時間、
スマホはモバイル回線、グラスはWi-Fiなし。**難問はスマホ内ローカルモデルで解く**（本筋）。
GPT中継は**最終手段として圏内に残す**（外さない）。PC は APK ビルドとモデル転送だけに使い、
現場のデータ経路には入れない。順位の正本は
[`tasks/plan.md#answer-route-20260912`](../tasks/plan.md)。

**利用者からの訂正（守ること）:**

1. 2026-09-12 昼に「スマホ内推論は側道」と書いたのは誤り。**本筋である。**
2. GPT中継を取り下げようとしたのも誤り。**圏内に残す。**
3. **実証の前に計算する。** 手段を先に走らせて全体手順を見失わない。
4. 実ページ規模は撮影より先に**公式の共通テスト・東大入試資料から**把握する。

**作業環境:**

- 作業ディレクトリ `C:\rokid-docscan-starter`。branch `agent/group-scoped-solver-context`、
  HEAD `2909f6f`、`main` から11コミット。未 push の場合は push から。
- 未追跡のまま残す環境ディレクトリ: `.agents/skills/` `.claude/` `.cursor/` `.specify/`
  `openspec/`。`git add -A` で巻き込まない。
- 端末 F-51F は **ssh 経由**。`ssh -i ~/.ssh/f51f_key -p 8022 u0_a26@192.168.0.30`。
  adb は読み取り専用（`adb.exe` は `C:\Users\pupu_\Downloads\platform-tools-latest-windows\platform-tools\`、
  デバイスIDは `adb-ZY22LWGDCV-gAfvon._adb-tls-connect._tcp`）。
  **モデルをロードすると Termux ごと kill されて sshd が落ちる。** 復旧は利用者が
  `termux-wake-lock; sshd` を実行する必要がある。長い実行は `nohup setsid` で切り離し、
  ログをファイルへ書くこと。
- 端末のモデル: `~/local-ai/models/llm/` に Qwen3.5-{0.8B,4B,9B}・Qwen3-4B-Instruct-2507 と
  mmproj 3種。バイナリは `~/llama.cpp/build/bin/`（CPU のみ、Vulkan 未ビルド）。
- PDF抽出は使い捨て venv の `pdfminer.six`（`pdftotext` は Adobe-Japan1 の CMap が無く化ける）。
  **公式PDFには抽出禁止フラグがある。統計と判定結果だけ残し、本文をリポジトリへ入れない。**

**最新の検証（2026-09-13 実行）:**

```
py -3.12 -m pytest -q      -> 473 passed, 1 warning in 58.83s
py -3.12 -m ruff check .   -> All checks passed!
```

Android は未変更のためビルド未実行。

**確定した設計（すべて実測に基づく）:**

| 項目 | 決定 | 根拠 |
|---|---|---|
| 端末内モデル | `Qwen3.5-4B-Q4_K_M` | pp2048 11.58 対 7.05 t/s、KV 32 対 144 KiB/token |
| thinking | `llama-cli --reasoning off` | `/no_think` は効かず `-n 200` を消費して解答に届かない |
| 解答文脈 | 大問単位（実装済み `7d88b88`） | 950トークンで15.7t/s・4/4、8,548トークンで6.2t/s・3/4 |
| 9B | 不採用 | `-c 8192` でも重みロード中に LMK が Termux とランチャーを kill |
| `-c` | 実測で決める（未確定） | `-c 16384` の `VmRSS` 5.75GB 対 計算値3.1GB |

**実測値（2026年度 共通テスト 公式PDF、空白除去後）:**

| 科目 | 実文字数 | トークン(Qwen3.5-4B) | 大問数 | 合計prefill見込み |
|---|---|---|---|---|
| 数学ⅠA | 7,992 | 5,744 | 約4 | 約6分 |
| 英語リーディング | 28,159 | 8,548 | 8 | 約9分 |
| 国語 | 28,325 | 20,889 | 5 | 約37分 |

速度の測定点（Qwen3.5-4B、`-t 4`）: pp512 15.61 / pp2048 11.58 / 実測950 15.7 / 実測8,548 6.2。

**解答能力の実測:** 英語リーディング 第2問（解答番号4-7、公式正解 1/3/4/2）を
第2問のみの文脈で **4/4 正解**。全問題を文脈にすると 3/4。他は未測定。

**次の手順（この順で）:**

1. **FS-71 国語の正答率。** 大問あたり約4,200トークンは、4/4 だった950と 3/4 だった8,548の
   中間にある。ここが本筋の未確認点。縦書きPDFは `pdfminer` で読み順が壊れるため、
   実機OCRか別の本文取得経路を先に決める。
2. **FS-71 横書き科目の先行測定。** 数学ⅠA・情報Ⅰは抽出がほぼ正常なので、
   国語の本文経路を待たずに大問スコープ時の正答率を固められる。
3. **FS-72 `-c` の安全上限。** `-c` 2048/4096/8192/16384 での `VmRSS` と kill の有無。
4. **FS-70 の実装。** サーバ側の既定モデル・`--reasoning off` 相当の設定を
   `llama-server` 起動条件として文書化する。
5. Termux 上での FastAPI 常駐（現場構成から PC を外す）。未着手。

**未解決・注意:**

- 国語・古文漢文の本文取得経路が未決定。実機OCRが計画どおりの方法。
- `-c 16384` の `VmRSS` 5.75GB は計算値3.1GBと合わない。**計算だけで `-c` を決めると落ちる。**
- 数学の記述式はマーク式と別に評価が要る。英語リーディングの結果を数学記述へ外挿しない。
- グラス⇄スマホは現在の答案バンドルが Wi-Fi 前提で、計画の Bluetooth/CXR と矛盾したまま。
- FS-62 の物理的な再装着試験、FS-65 が定義する数式・表・作図の表示は未着手のまま。

## E-2. 2026-09-13 縦書き科目の本文取得経路（評価用）

実機撮影を待たずに国語の正答率を測るため、公式PDFから読み順の正しい本文を得る経路を作った。
**これは評価用であって、本番の取得経路（グラス撮影→ML Kit OCR）を置き換えるものではない。**

問題は3層あった。

1. **`pdftotext` は使えない。** Adobe-Japan1 の CMap を持たず、CID Type 0C / Identity-H /
   `uni=no` のフォントを化けさせる（`pdffonts` で確認）。poppler-data を入れようにも
   `/mingw64/share/poppler` は権限が無く作れない。
2. **`pdfminer.six` は読めるが縦書きの読み順が壊れる。** 1文字ごとに改行し、段組も混ざる。
   → `LTChar` の座標から復元した。列は x の降順（右から）、列内は y の降順（上から）。
3. **未マップ文字が2種類ある。**
   - CID フォント（`DFHSMinchoPro6N` 等）の高い CID は Adobe-Japan1 の縦組み用。
     poppler-data の `cidToUnicode/Adobe-Japan1` で正確に解決できる
     （7891=ー, 7894=〜, 7923=っ, 7928=ァ, 7934=ャ, 7935=ュ, 7936=ョ。文脈からの推定と完全一致）。
   - Type1C サブセット（`EdiF-*`）は選択肢番号と傍線部ラベル。ToUnicode が無く、
     **同じ cid 番号が別サブセットで別の字を指す**。設問内の出現順で採番して復元した。

復元後の国語第1問は日本語として通る本文になり、設問と選択肢も判別できる。
スクリプトは `$CLAUDE_JOB_DIR/tmp/vext.py`（使い捨て。公式PDFには抽出禁止フラグがあるため
本文もスクリプトもリポジトリへ入れない）。

#### 国語 第1問の評価条件

- 大問スコープの入力は **5,420トークン**（本文5ページ＋問2〜問6）。
  8,548トークン（正答3/4）と950トークン（正答4/4）の中間にあたる。
- 解答番号は第1問が1〜10。配点列（2,2,2,2,2,7,7,7,7,7）から漢字問題が1〜5、
  内容理解の問2〜問6が6〜10。**公式正解は 3, 2, 2, 3, 1。**
- 選択肢は4つ（第1問の正解がすべて4以下であることと整合）。

#### 国語 第1問の正答率: 4/5（大問スコープ 5,420トークン）

`Qwen3.5-4B-Q4_K_M`、`-c 8192 -t 4 -ub 256 -n 300 -st --no-warmup --reasoning off`。
入力は第1問の本文5ページ＋問2〜問6（5,420トークン）。正解はプロンプトに含めていない。

| 設問 | 解答番号 | 公式正解 | 出力 | 判定 |
|---|---|---|---|---|
| 問2 | 6 | 3 | 3 | ○ |
| 問3 | 7 | 2 | 2 | ○ |
| 問4 | 8 | 2 | 2 | ○ |
| 問5 | 9 | 3 | 3 | ○ |
| 問6 | 10 | 1 | **6** | ✗ |

`[ Prompt: 9.1 t/s | Generation: 3.4 t/s ]`

**誤答の1問は選択肢に存在しない「6」で、内容の誤りではなく出力形式の破綻である。**
選択肢は4つしかない。範囲外の出力は、サーバ側で検出して再試行できる種類の失敗であり、
能力不足とは区別して扱う。

これで国語の時間予算が実測で埋まった: 20,889トークン ÷ 9.1 t/s = **約38分**。
生成は全問マーク式でほぼゼロ。**150分に収まる。**

#### 速度の測定点（Qwen3.5-4B、`-t 4`）まとめ

| 入力トークン | prompt t/s | 出典 |
|---|---|---|
| 512 | 15.61 | llama-bench |
| 約950 | 15.7 | 英語リーディング第2問のみ |
| 2048 | 11.58 | llama-bench |
| 5,420 | 9.1 | 国語第1問 |
| 8,548 | 6.2 | 英語リーディング全問 |

#### 数学ⅠA はこの経路では評価できない

PDF抽出で選択肢記号だけでなく**集合内の数字まで欠落する**（`{(cid:2)，(cid:6)，１５}`）。
`EdiF-*` サブセットフォントに数字が入っており、ToUnicode が無い。数学は全数字が
正確に必要なので、位置ベースの復元では代用できない。**実機OCRか画像入力（mmproj）が要る。**
英語リーディングは Latin 主体で抽出が完全、国語は座標復元＋CID表で成立した。

## E-3. 引き継ぎ要約（2026-09-13。E 節で最も新しい。ここから読む）

**この節が最新。** 目的・環境・利用者の訂正は「再開入口（2026-09-13）」を参照。
以下は結論と次の一手だけ。

#### 結論: スマホ内 Qwen3.5-4B で共通テストは解ける。国語も時間内に収まる

| 科目 | 正答 | 条件 | prompt t/s |
|---|---|---|---|
| 英語リーディング 第2問 | **4/4** | 第2問のみ 約950トークン | 15.7 |
| 英語リーディング 第2問 | 3/4 | 全問題 8,548トークン | 6.2 |
| 国語 第1問 問2〜問6 | **4/5** | 第1問のみ 5,420トークン | 9.1 |

**大問単位に絞ると速く、かつ正確。** 全文を渡すと両方悪化する。実装は `7d88b88` で完了。

時間予算（大問スコープ、150分の試験時間に対して）:
数学ⅠA 5,744トークン→約6分 / 英語リーディング 8,548→約9分 / 国語 20,889→**約38分**。

#### 確定した設定

```
モデル   ~/local-ai/models/llm/Qwen3.5-4B-Q4_K_M.gguf
起動     llama-cli -c 8192 -t 4 -ub 256 -st --no-warmup --reasoning off
```

`Qwen3-4B-Instruct-2507` は不採用（長文 prefill が 0.61倍、KV が 4.5倍）。
9B も不採用（重みロード中に LMK が Termux とランチャーを kill、`-c` では直らない）。
`-c` は必ず明示する（未指定だと 262,144 を確保しようとする）。

#### 次の一手（優先順）

1. **範囲外出力の扱い。** 国語で1問だけ選択肢に無い「6」を出した。サーバ側で
   選択肢の範囲を検査し再試行する経路を入れる。能力不足と混同しない。
2. **正答率を固める。** 英語リーディング全8大問（解答番号1〜44）を大問ごとに解かせ、
   公式正解と突き合わせる。国語も第2問〜第5問へ広げる。
3. **数学の評価経路。** PDF抽出では数字が欠落するので不可。実機OCRか mmproj 画像入力。
4. **FS-72 `-c` の安全上限。** `-c 16384` で `VmRSS` 5.75GB。計算値3.1GBと合わない。
5. **Termux 上での FastAPI 常駐**（現場構成から PC を外す）。未着手。
6. FS-70 の実装（サーバ側の既定モデルと起動条件の文書化）。

#### 触っていない既存の未完了項目

FS-62 の物理的な再装着試験、FS-65 の数式・表・作図の表示、グラス⇄スマホを
Bluetooth/CXR へ戻すこと（現在の答案バンドルは Wi-Fi 前提で計画と矛盾）。

#### 検証済みの状態

```
py -3.12 -m pytest -q      -> 473 passed
py -3.12 -m ruff check .   -> All checks passed!
```

Android は未変更のためビルド未実行。コード変更は `7d88b88` の1件のみで、残りは記録。

## E-4. 2026-09-13 夕 範囲外の選択肢記号を 1 回だけ問い直す経路

引き継ぎ要約の優先順1。国語で1問だけ出た「選択肢に無い 6」への対処。`22e985a`。

**入れた経路。** `solve_with_fallback` は3か所の解答経路（`app/main.py` の 1557 /
1940 / 2541）がすべて通る唯一の合流点なので、検査と問い直しはそこに1か所だけ置いた。

1. `app/solvers/llm_adapter.py` に `choice_label` / `choice_index` /
   `choice_out_of_range`。記号の付与と読み取りを同じファイルに置き、両者がずれないようにした。
2. 読み取りは**先頭の記号だけ**。英字1文字、半角/全角の数字（2桁まで）、丸数字。
   選択肢の本文をそのまま答えた場合や「2000年」のような値は記号と見なさない（誤検知を避ける）。
3. 範囲外なら**同じ tier に1回だけ**問い直す。`Question.retry_hint` に有効な記号の範囲を入れ、
   同じプロンプトを盲目的に再送しない。
4. プロンプト自体にも記号の範囲を明記した（`解答は上の記号 A〜C のいずれかを使う`）。
   追加コストは無く、そもそも範囲外を出させないための予防。
5. 2回目も範囲外なら**最初の解答を残して** `extras["choice_out_of_range"]` を立てる。
   tier の失敗とは扱わない。記号の誤りで次の有料 tier を消費したり答案全体を失敗させない。
   **これが「能力不足と混同しない」の実装。**

**残した天井。** `extras` は `fallback_from` と同じくDBに保存しない。よって
`choice_out_of_range` はセッションの結果には見えるが、後からDBで数えられない。
保存するなら `solutions` に列が要る。評価（次の一手2）で頻度が問題になったら追加する。

**検証:**

```
py -3.12 -m pytest -q      -> 487 passed（473 + 新規14）
py -3.12 -m ruff check .   -> All checks passed!
```

否定確認: `app/solvers/registry.py` の `_retry_out_of_range` 呼び出しを外すと
`test_out_of_range_choice_is_retried_once_with_the_valid_labels` と
`test_persistent_out_of_range_answer_is_kept_and_flagged_not_dropped` が
`KeyError: 'choice_out_of_range'` で落ちる。

Android は未変更のためビルド未実行。実機での再測定は未実施（この経路はサーバ側のみ）。

**次の一手は引き継ぎ要約の 2 以降。** 優先順1はこの節で完了。

# F. スマホ側 CDP 終端（F-51F、2026-09-14）

## F-1. 問い

`ROKID_SOLVER=chatgpt-web` の実測はすべて PC 上の Chrome に対するものだった。
会場には PC を持ち込まないため、`ROKID_CHATGPT_CDP` がスマホ側のブラウザを
指せるかどうかが最大の未解決点だった（`tasks/plan.md` 2026-09-14 追補）。

## F-2. 実測

**Android の Chrome は TCP で listen しない。** 一次資料は chromium/src の
chrome/browser/android/devtools_server.cc（main、2026-09-14 参照。
<https://chromium.googlesource.com/chromium/src/+/refs/heads/main/chrome/browser/android/devtools_server.cc>）。
`net::UnixDomainServerSocket`（POSIX abstract namespace）だけを使い、TCP の経路が
存在しない。ソケット名は `<prefix>_devtools_remote` で、`kRemoteDebuggingSocketName`
で上書きできる。`--remote-debugging-port` を渡しても Android ビルドは
unix socket factory を通る。

**接続元は UID で認可される。** chromium/src の
content/browser/android/devtools_auth.cc
（<https://chromium.googlesource.com/chromium/src/+/refs/heads/main/content/browser/android/devtools_auth.cc>）
の `CanUserConnectToDevTools` は `credentials.group_id == credentials.user_id` を
前提に、`root` / `shell` / ブラウザ自身と同じ UID の 3 つだけを通す。
SO_PEERCRED で相手プロセスを認証しており、他アプリは該当しない。

**端末側のソケットは現に開いている。** F-51F（Android 16 / API 36、SELinux
Enforcing）で読み取りのみ確認:

```
adb -s 192.168.0.30:44409 shell cat /proc/net/unix | grep -i devtools
0000000000000000: 00000002 00000000 00010000 0001 01 4869806 @chrome_devtools_remote
```

**アプリ間は SELinux でも隔たっている。** 同じ端末で測定:

```
u:r:untrusted_app:s0:c30,c257,c512,c768      u0_a286  com.android.chrome
u:r:untrusted_app_27:s0:c26,c256,c512,c768   u0_a26   com.termux
/system/etc/selinux/plat_seapp_contexts:37   ... domain=untrusted_app ... levelFrom=all
```

domain も MCS カテゴリも異なる（`c30,c257` 対 `c26,c256`）。`levelFrom=all` により
アプリごとに固有カテゴリが付く。

## F-3. 結論（種別つき）

- **実測:** Chrome for Android の CDP は abstract unix socket のみ。TCP 経路なし。
- **実測:** 接続元の認可は `root` / `shell` / Chrome 自身の UID に限られる。
- **実測:** F-51F 上で `@chrome_devtools_remote` が listen 中。Chrome と Termux は
  SELinux の domain・カテゴリが異なる。
- **推論:** Termux から Chrome の abstract socket へ直接繋ぐ経路は、UID 認可と
  SELinux の MLS 制約という**独立した 2 つの門**で塞がれている。実地の接続試行は
  未実施（sshd 停止中）。
- **推論:** 端末内 adb（shell 文脈）を経由すれば両方の門を通る。
  `adb forward tcp:9222 localabstract:chrome_devtools_remote` を**端末上で**実行すると、
  adbd（`shell`、uid 2000）が abstract socket へ繋ぎ、127.0.0.1:9222 に TCP を開く。
  loopback TCP はアプリ間で SELinux の MLS 制約を受けないため、Termux 側のサーバから
  `ROKID_CHATGPT_CDP=http://127.0.0.1:9222` で到達できる。
- **一次資料:** Android 11 以降の wireless debugging は端末上でペア設定でき、PC を
  必要としない（developer.android.com/tools/adb、および Shizuku の
  「This startup method does not require connection computer」「Starting wireless
  debugging works on Android 11 above」）。再起動のたびに開始操作が要る。
- **実測:** F-51F では wireless debugging が既に有効（`adb devices` に
  `192.168.0.30:44409` が出る）。

## F-4. 未確認（この経路を使う前に必要）

1. Termux に `adb`（`android-tools`）を入れ、`127.0.0.1` へ自己ペアできるか。
   未実施。sshd が停止しており、復旧は利用者の `termux-wake-lock; sshd` が要る。
2. Playwright の Node driver が Termux（bionic、glibc ではない）で動くか。
   **成果物で確認済みの逃げ道:** PC の site-packages に入っている playwright
   1.62.0 の playwright/_impl/_driver.py 30-33 行は `PLAYWRIGHT_NODEJS_PATH` を読み、
   同梱 node の代わりに任意の node を使える。Termux の nodejs を指させる想定。
   wheel が Termux に入るかは未確認。
3. Chrome・llama-server・FastAPI を同居させたときのメモリ。E 節の実測では
   モデルロードで Termux ごと kill されている。
4. ChatGPT ウェブ UI の自動操作が OpenAI の利用規約に反する点は変わらない。

# 出典

## 出典 — グラス一次情報索引（2026-09-03）

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

## 出典 — グラス側アプリ経路調査（2026-08-29）

- リンク対象 AAR: `com.rokid.cxr:client-l:1.1.1`（`javap`、
  `~/.gradle/caches/modules-2/files-2.1/com.rokid.cxr/client-l/1.1.1/`）
- Rokid Maven: <https://maven.rokid.com/repository/maven-public/>
- 実働リファレンス実装: <https://github.com/Anezium/Rokid-APKs>（GPL-3.0）
- コミュニティ資料: <https://github.com/buildwithfenna/rokid-docs>（要注意・第 8 節参照）
- CXR-L ドキュメント日本語外ミラー: <https://marcinmiazga.com/cxr-l-sdk/>
- Rokid 公式 SDK 窓口: <https://ar.rokid.com/sdk>
- 関連リンク集: <https://github.com/Anezium/awesome-rokid>

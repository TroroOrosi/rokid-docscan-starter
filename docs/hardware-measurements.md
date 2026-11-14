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
| E | スマホ内推論 | F-51F、Android 16 / API 36、`MT6897`、llama.cpp | 2026-09-12〜09-14 |
| F | スマホ側 CDP 終端の到達性 | F-51F、Android 16 / API 36、`com.android.chrome`、chromium/src main | 2026-09-14 |
| F-6 | スマホの Chrome を CDP で実操作 | F-51F、Android 16 / API 36、Chrome/153.0.8010.36 | 2026-09-15 |
| M | 静止画が返らない構成・プレビュー処理時間・自動撮影 | `RG_glasses` build `1.29.013-20261110-150201`、`:glassprobe`（variant付き）、`:glassdoc` 0.43.10（vc62） | 2026-11-12 |

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

**2026-11-14 追記**：下は 8〜9月の観測。公式文書の今の記載は「通信は全て Bluetooth 経由」「音声起動のみ」と違い、画像を渡せるモデル呼び出しと撮影の API がある（§M-20）。この節を根拠に AIUI を不可としない。

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

## B-0-2. 任意バイトの双方向チャネル（`javap`、2026-09-14）

**グラス側アプリは自前の Wi-Fi を持たなくてもスマホへデータを返せる。** 同じ
`IMediaStreamService` に、任意の `byte[]` を双方向に運ぶ口がある。`uploadAndInstallApk`
の一覧（B-0）を写したときに見落としていた。

```java
// スマホ → グラス。1.0.1 と 1.1.1 の両方に存在
int  sendCustomCmd(String name, byte[] payload)
boolean registerCustomCmdCallback(ICustomCmdCallback cb)
boolean unregisterCustomCmdCallback(ICustomCmdCallback cb)

// グラス → スマホ
interface ICustomCmdCallback { void onCustomCmdResult(String name, byte[] payload); }

// 1.1.1 のみ
int sendCustomCmdStream(String name, byte[] header, byte[] payload)
```

1.1.1 の session 層にも同じものがある。`CxrSession.sendCustomCmd(String, Caps, byte[])` と
`addCustomCmdCallback(ICustomCmdSessionCallback)`（同じ `onCustomCmdResult(String, byte[])`）。
同梱サンプル `ExternalAppClient` は、この口とアプリのライフサイクルを1つのクライアントに
まとめている：`appUploadAndInstall` / `appStart(pkg, boolean, cb)` / `appStop` /
`appIsInstalled` ＋ `sendCustomCmd(String, Caps)` / `sendCustomCmd(String, Caps, byte[])` /
`setCXRCustomCmdCbk(ICustomCmdCbk)`。

`com.rokid.cxr.Caps` は 1.0.1 の jar に同梱。1.1.1 の jar には無く、
`com.rokid.cxr:cxr-service-bridge` が供給する（`Caps$Binary` / `Caps$Value` 込み）。

**本リポジトリはこの API を1度も呼んでいない**（`grep -rl CustomCmd android-relay` は 0 件、
2026-09-14）。

### まだ測っていないこと（これらを検証と呼ばない）

1. **グラス側の対向 API が未確認。** このAARはスマホ側クライアントである。グラス側アプリが
   `onCustomCmdResult` を受け、スマホへ送り返すための YodaOS 側 API は、この成果物には
   入っていない。**有無は不明。**
2. **実機のサービスが実装しているか不明。** C-1 で測った Hi Rokid は CXR-L service
   `1.0.0 code 10000`。AAR に口があることは、その service が応答することを意味しない。
3. **ペイロード上限が不明。** Binder のトランザクションは概ね 1 MB で、`takePhoto` の
   JPEG はそれを超えうる。`sendCustomCmdStream`（1.1.1 のみ）の存在は分割前提を示唆するが、
   上限も分割規約も測っていない。
4. `uploadAndInstallApk` / `openApp` は実機で成功していない（`CLAUDE.md`）。

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

> **測定時点の前提であり、現在の経路ではない。** 2026-09-14 に利用者が
> `ROKID_SOLVER=chatgpt-web` を決定し、スマホ内ローカルは不採用になった
> （[`tasks/plan.md#answer-route-20260914`](../tasks/plan.md)）。以下の E 節は
> 測定値を証拠として保存するためのもので、E 節の「本筋」「最終手段」という
> 順位づけは**測定当時のもの**である。数値は有効、順位は無効。

**目的（当時）:** グラス単体で教材を撮影し、答案の全内容を小問単位で読む。150分の試験時間、
スマホはモバイル回線、グラスはWi-Fiなし。難問はスマホ内ローカルモデルで解く（当時の本筋）。
GPT中継は最終手段として圏内に残す（外さない）。PC は APK ビルドとモデル転送だけに使い、
現場のデータ経路には入れない。順位の正本は当時
[`tasks/plan.md#answer-route-20260912`](../tasks/plan.md) だった。

**利用者からの訂正（2026-09-13 時点。1 と 2 は 2026-09-14 の決定が上書きした）:**

1. ~~2026-09-12 昼に「スマホ内推論は側道」と書いたのは誤り。**本筋である。**~~
   → 2026-09-14 にローカルは不採用。
2. ~~GPT中継を取り下げようとしたのも誤り。**圏内に残す。**~~
   → API キー経路は `ROKID_SOLVER_TIERS` のフォールバック段として残る。主経路は chatgpt-web。
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
3. ~~**FS-72 `-c` の安全上限。**~~ 実測完了。E-3 を見ること。
4. **FS-70 の実装。** サーバ側の既定モデル・`--reasoning off` 相当の設定を
   `llama-server` 起動条件として文書化する。
5. Termux 上での FastAPI 常駐（現場構成から PC を外す）。未着手。

**未解決・注意:**

- 国語・古文漢文の本文取得経路が未決定。実機OCRが計画どおりの方法。
- ~~`-c 16384` の `VmRSS` 5.75GB は計算値3.1GBと合わない~~ → E-3 で解決。差は KV では
  なく、mmap した重みを `VmRSS` が数えていたこと。`Private_Dirty` は 3.38GB で計算と整合する。
- 数学の記述式はマーク式と別に評価が要る。英語リーディングの結果を数学記述へ外挿しない。
- グラス⇄スマホは現在の答案バンドルが Wi-Fi 前提で、計画の Bluetooth/CXR と矛盾したまま。
- FS-62 の物理的な再装着試験、FS-65 が定義する数式・表・作図の表示は未着手のまま。

## E-3. `-c` の実効メモリと、大問あたりの実トークン数（2026-09-14）

機体 F-51F、Android 16 / API 36、`MT6897`、8 コア、`MemTotal` 11,728,552 kB。
モデル `Qwen3.5-4B-Q4_K_M`（ファイル 2,740,937,888 B）。`llama-cli -n 8 -t 4 -st`。
ピークは `/proc/<pid>/status` の `VmHWM` と `/proc/<pid>/smaps_rollup` を 0.4〜0.5 秒
間隔で標本化した最大値。

### E-3-1. `-c` を変えたときの実効メモリ — FS-72

| `-c` | `VmHWM` | `Private_Dirty` | `Pss` | 実行時の `MemAvailable` | 結果 |
|---|---|---|---|---|---|
| 2,048 | 5,543,560 kB | 2,922,432 kB | 5,598,964 kB | 5,924,148 kB | exit 0 |
| 4,096 | 5,670,648 kB | — | — | 7,386,856 kB | exit 0 |
| 8,192 | 5,802,940 kB | — | — | 7,238,400 kB | exit 0 |
| 16,384 | 6,065,084 kB | 3,382,816 kB | 6,058,509 kB | 7,389,700 kB | exit 0 |
| 32,768 | 6,588,076 kB | — | — | 7,148,360 kB | exit 0 |
| 49,152 | 7,112,096 kB | 4,432,540 kB | 7,103,071 kB | 7,646,652 kB | exit 0 |

**kill は一度も起きていない。** 増分は 16,384→32,768 が 522,992 kB、32,768→49,152 が
524,020 kB。どちらも **32.0 KiB/token** で、FS-68 が GGUF metadata から計算した
`full_attention_interval=4`・8 層のみ KV という値と一致する。

**「計算値と合わない」という 2026-09-12 の記述は、指標の取り違えだった。**
`VmRSS`／`VmHWM` は mmap した重み（2.55 GiB、file-backed で clean、圧力下では回収可能）
を数える。回収できない分は `Private_Dirty` で、`-c 16384` で 3,382,816 kB = 3.23 GiB。
計算値（重み 2.55 GiB ＋ KV 0.5 GiB ＝ 約 3.1 GiB）とはこちらが整合する。
KV の計算は正しく、モデルの能力とも無関係だった。

線形性から `VmHWM ≈ 5.22 GiB + c × 32 KiB`、`Private_Dirty ≈ 2.86 GiB + c × 32 KiB`。

**上限を失敗するまでは詰めていない。** `-c 65536` は約 7.6 GiB で当日の
`MemAvailable` を超える見込みであり、kill は Termux と sshd を道連れにして利用者の
復旧操作を要求するため、意図的に実行していない。実測で確かめたのは
**49,152 まで安全**という事実である。なお測定時の端末は他に重い常駐が無い状態で、
会場でリレーやブラウザを同時に動かす場合の余裕は別に測る必要がある。

### E-3-2. 実問題の大問あたりトークン数 — FS-67

`llama-tokenize -m Qwen3.5-4B-Q4_K_M.gguf` による**実測**。比率からの推定ではない。
本文は 2026 年度共通テストの公式 PDF から `pdfminer.six`（`detect_vertical=True`）で
1 ページずつ抽出し、`app/layout.py` の `segment_problems` で大問へまとめたもの。測定後、
端末へ送った本文は削除した。リポジトリには統計だけを残す。

| 科目 | ページ | 論文全体 | 1ページ平均 | 最大ページ | 大問数 | 大問 最小 | 大問 最大 |
|---|---|---|---|---|---|---|---|
| 英語リーディング | 31 | 9,660 | 311 | 492 | 8 | 585 | 1,920 |
| 物理基礎 | 14 | 5,272 | 376 | 495 | 3 | 1,453 | 2,055 |
| 数学ⅠA | 26 | 8,959 | 344 | 543 | 4 | 938 | 3,771 |
| 情報Ⅰ | 34 | 13,907 | 409 | 593 | 4 | 2,832 | 3,990 |
| 国語 | 47 | 29,579 | 629 | 1,256 | 5 | 4,023 | **9,484** |

**単一の「トークン/文字」比率は使えない。** 文字種で 2.7 倍違う。

| 対象 | 文字 | トークン | トークン/文字 |
|---|---|---|---|
| 英語リーディング 大問8 | 6,348 | 1,920 | **0.30** |
| 情報Ⅰ 大問2 | 5,557 | 3,979 | 0.72 |
| 国語 大問1 | 9,413 | 6,873 | 0.73 |
| 数学ⅠA 大問1 | 2,480 | 2,039 | **0.82** |

2026-09-12 に記録した 0.70／0.77 という単一比率を英語へ当てると約 2.4 倍の過大見積りに
なる。逆に数学・国語では過小になる。

**ここで得た数字は 2026-09-12 の推定値とも食い違う**（数学ⅠA 5,744 → 8,959、
国語 20,889 → 29,579、英語リーディング 8,548 → 9,660）。差はトークン化だけでなく
抽出にもある。今回は `detect_vertical=True` でページ単位に抽出しており、文字数自体が
多い（数学ⅠA 7,992 字 → 11,026 字）。どちらが実機 OCR に近いかは未測定であり、
**この表は「PDF 抽出を OCR の代役にしたときの値」であって、撮影したページの値ではない。**
FS-67 が要求する実ページ OCR の文字数は、実機撮影が残っていないため依然として未測定。

### E-3-3. これが時間予算に対して意味すること（推論、未検証）

実測済みの prompt 速度は 950 トークンで 15.7 t/s、5,420 で 9.1 t/s、8,548 で 6.2 t/s。
外挿すると国語 大問2（9,484 トークン）の prefill だけで 25 分前後になる。分析 10 分の
窓には収まらず、閲覧 130 分側へ食い込む。

さらに **`-c` の上限は制約になっていない**（49,152 まで安全、最大の大問でも 9,484）。
律速は prefill 速度であって文脈長ではない。

未確認の重大な点: 大問スコープでは同じ大問の小問ごとに同じページを prefill し直す。
国語は 5 大問で 32 小問あるため、キャッシュが効かなければ prefill は大問合計の数倍に
なる。`llama-server` のプロンプトキャッシュで再利用できるかは測っていない。

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
- **実測（2026-09-14 追加）:** Termux から Chrome の abstract socket へ直接繋ぐ経路は
  **塞がっている**。推論ではなく実地で確認した。F-5 を見ること。
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
2. ~~Playwright の Node driver が Termux で動くか~~ → **動かない。** F-5-4 で実測。
   driver が `Unsupported platform: android` で初期化に失敗する。
   `PLAYWRIGHT_NODEJS_PATH` では回避できない。
3. Chrome・llama-server・FastAPI を同居させたときのメモリ。E 節の実測では
   モデルロードで Termux ごと kill されている。
4. ChatGPT ウェブ UI の自動操作が OpenAI の利用規約に反する点は変わらない。

## F-5. スマホ単独で CDP 終端に到達できるか（実機、2026-09-14）

F-2 の推論を実機で確かめ、さらに 2 つの壁が出た。機体 F-51F、Android 16 / API 36、
Termux 0.118.3（`u0_a26`、`untrusted_app_27`）、`com.android.chrome`（`u0_a286`）。

### F-5-1. アプリから直接は繋がらない（実測）

```
$ ssh ... 'grep -i devtools /proc/net/unix'
grep: /proc/net/unix: Permission denied

$ ssh ... 'curl -s -m 8 --abstract-unix-socket chrome_devtools_remote http://localhost/json/version; echo exit=$?'
exit=7
```

Termux からはソケット一覧すら読めず、`curl --abstract-unix-socket` は
exit 7（接続失敗）。F-2 が示した UID 認可（`root`/`shell`/Chrome 自身）と
SELinux の MCS カテゴリ分離のとおりで、**アプリ間では繋がらない**。

### F-5-2. DevTools ソケットは Chrome の活動に従って現れ消えする（実測）

同じ日のうちに、listen していたソケットが消えた。Chrome のプロセス自体は同じ pid
12143 で生きていた。前景へ戻すと**別の inode で再び現れた**。

| 状態 | `/proc/net/unix` の `@chrome_devtools_remote` |
|---|---|
| 13:0x（Chrome 起動済み） | inode 4869806 で listen |
| llama-cli を 8 回実行した後 | **無し**（Chrome の pid は 12143 のまま） |
| `am start ... chatgpt.com` で前景へ | inode 5248971 で listen |
| `KEYCODE_HOME` の 6 秒後 | inode 5248971 のまま listen |

> **この節の結論「背景へ回しただけでは消えない」は 2026-09-15 に否定された。**
> F-6-1 を読むこと。Termux を前景にしただけでソケットは消え、Chrome を前景へ戻すと
> 約2秒で別 inode に作り直された。上の表の `KEYCODE_HOME` 行は、ホーム画面へ戻した
> 直後の 6 秒しか見ていない。**より長い背景化や別アプリの前景化は試していなかった。**
> 数値は有効、結論は無効。

消えたのはメモリ圧迫を掛けた後でもあり、**解答中に落ちうる終端である**ことを意味する。
会場の経路は、ソケットが消えた場合の復帰を持たなければならない。llama-cli を 8 回
回した副作用でこれが起きたのは、測定の偶然ではなく、同じ端末で重い処理を走らせる
構成そのものの性質である。

### F-5-3. 端末内 adb はペア設定が要る（実測、**2026-09-15 に解決**）

> **解決済み。F-6-6 を読むこと。** 6桁コードは要らなかった。`adb tcpip 5555` で
> 平文 TCP に切り替えると、端末内 client は `/data/misc/adb/adb_keys` の許可制を
> 通る。この節が「要る」と書いたのはワイヤレスデバッグ（TLS）に限った話で、
> それが唯一の経路だと決めつけていた。

`pkg install android-tools` で Termux に adb 1.0.41（35.0.2）が入った。しかし

```
$ adb connect 127.0.0.1:44409
failed to connect to 127.0.0.1:44409
```

PC が使っている接続ポートへは繋げない。ワイヤレスデバッグの接続ポートは
**ペア済みクライアント証明書**を要求し、クライアントごとに鍵が異なるためである
（PC はペア済み、Termux は未ペア）。`adb mdns services` もこのビルドでは
`error: unknown host service 'mdns:services'` を返す。

ペア設定は設定アプリが表示する 6 桁のコードを要するため、**利用者の操作が要る**。
Shizuku が文書化している手順と同じで、ペアは一度だけ、開始操作は再起動ごとに要る。

### F-5-4. Playwright は Termux では動かない（実測）

wheel は Termux 用が無い（`ERROR: No matching distribution found playwright`）。
manylinux aarch64 wheel を `--platform` 指定で入れ、同梱 node の代わりに Termux の
node v26.4.0 を `PLAYWRIGHT_NODEJS_PATH` で使わせても、driver 自体が起動を拒否する。

```
$ cd ~/pw/playwright/driver && node package/cli.js --version
Error: Unsupported platform: android
    at packages/playwright-core/src/server/registry/index.ts
```

`process.platform === "android"` を registry が弾く。ブラウザを起動するかどうかに
関係なく、driver の初期化で落ちるため、`connect_over_cdp` にも到達しない。
**`PLAYWRIGHT_NODEJS_PATH` は解決策にならない。** F-4 の「逃げ道」はここで否定された。

残る選択肢は 2 つ。どちらも未実施。

1. Playwright を使わず、CDP を直接話す（HTTP `/json` ＋ WebSocket）。
   `app/solvers/chatgpt_web.py` の実装変更が要るが、スマホ側の依存は
   Python の WebSocket クライアントだけになる。
2. proot で glibc の Linux を動かし、その中の node に `platform === "linux"` を
   名乗らせる。実装は変えずに済むが、メモリの厳しい端末に別のユーザランドを足す。

**採用は 1**（2026-09-14、利用者承認）。実装は `app/solvers/cdp.py`。結果は F-6。

## F-6. スマホの Chrome を CDP で実際に動かした（実機、2026-09-15）

機体 F-51F、Android 16 / API 36。`com.android.chrome` は **Chrome/153.0.8010.36**。
PC から `adb forward tcp:9222 localabstract:chrome_devtools_remote` を張って測った。
**PC を経路に入れた測定であり、会場トポロジの検証ではない。** 端末内 `adb forward`
はまだ通っていない（F-6-3）。証明できたのは「スマホの Chrome が CDP を話す」
ことと「`app/solvers/cdp.py` がその Chrome で動く」ことである。

### F-6-1. DevTools ソケットは Chrome が前景にある間だけ存在する（実測）

F-5-2 は「背景化だけでは消えない」と記録していた。**これは限定しすぎだった。**

```
[Termux が前景]      cat /proc/net/unix | grep devtools  →  出力なし
[Chrome を前景へ]    monkey -p com.android.chrome -c android.intent.category.LAUNCHER 1
[+1s]  なし
[+2s]  5707196 @chrome_devtools_remote
[+3s〜+6s]  同じ inode で継続
```

先に観測した inode は 5412234 で、再出現時は 5707196。**同じソケットが戻るのではなく
作り直される。** 画面は `mWakefulness=Awake` のままで、変わったのは前景アプリだけ。

会場への帰結: **Chrome を前景に置いたままにする。** サーバ（Termux の FastAPI）は
背景で動かす。「画面を点けたまま伏せて置く」という 2026-09-15 の運用決定は、
画面だけでなく**前景アプリ**も固定する必要がある。

### F-6-2. 終端は最初の数回を拒否してから応答する（実測）

```
curl -sS -m 10 http://127.0.0.1:9222/json/version
  try1 rc=28 timed out after 10004 ms
  try2 rc=28 timed out after 10003 ms
  try3 rc=0  {"Browser":"Chrome/153.0.8010.36", ...
           "webSocketDebuggerUrl":"ws://127.0.0.1:9222/devtools/browser"}
```

Chrome が背景のときは 5 回とも `RemoteDisconnected`（F-6-1 のとおりソケットが無い）。
**1 回の拒否は「ブラウザが無い」ではない。** `cdp_available()` と
`app/solvers/cdp.py` の両方を再試行にしたのはこの実測による。単発判定のままなら、
動いているブラウザを不在と判断して次の solver tier へ落ちる。

### F-6-3. 端末内 adb はまだ通っていない（実測、未了）

```
$ ssh ... 'adb connect 127.0.0.1:36763'    failed to connect to 127.0.0.1:36763
$ ssh ... 'adb connect 192.168.0.30:36763' failed to connect to 192.168.0.30:36763
$ ssh ... 'adb connect 127.0.0.1:5555'     failed to connect: Connection refused
```

PC からは同じ `192.168.0.30:36763` に繋がる。port は開いていて、Termux の鍵が
ペアされていないだけである（`getprop` は `sys.usb.config=mtp,adb`、
`service.adb.tcp.port` は空。ワイヤレスデバッグの無作為 port）。
**`adb pair` に要る 6 桁コードは設定アプリが表示するもので、利用者の操作が要る。**
PC の `~/.android/adbkey` を複製する案は、秘密鍵の複製にあたるため採らない。

### F-6-4. `app/solvers/cdp.py` の各操作（実測、スマホの Chrome に対して）

| 操作 | 結果 |
|---|---|
| `connect_over_cdp` → `Target.getTargets` | 成功。page target 2 件 |
| `new_page` / `goto` / `url` | 成功 |
| `locator().count()` / `is_visible()` / `inner_text()` | 成功 |
| `fill()` 日本語 30 字（`√2`・`x²` 込み） | **完全一致で往復** |
| `fill()` 36,000 字 | `value.length` が 36000。Playwright 期の 34,205 字と同等 |
| `fill()` 2 回目（消去して入れ直し） | 成功 |
| `set_input_files()` 6 MB の PDF 1 件 | `files[0].size` = 6,291,465、**1.50 s** |
| `set_input_files()` 200 KB 画像 8 件 | `files.length` = 8、**0.25 s** |
| `click()`（`Input.dispatchMouseEvent`） | ハンドラが発火 |

添付は `DOM.setFileInputFiles` を使わない。あれはブラウザ側のファイルパスを指すもので、
Chrome for Android からサーバのファイルは見えない。ページへ `DataTransfer` として
バイト列を渡している。**6 MB が 1.50 s** なので、冊子1冊の PDF は現実的な範囲に入る。

**未測定:** chatgpt.com の実ページに対しては1度も動かしていない。セレクタが今も
合うか、ProseMirror が `Input.insertText` を受けるかは未確認。

### F-6-6. 端末内 adb と、スマホ単独での CDP 実行（実測、2026-09-15）

**PC をデータ経路から外した状態で通った。** F-5-3 が「ペア設定未了」としていた壁は、
6桁コードではなく `adb tcpip` で越えた。

```
[PC]    adb -s 192.168.0.30:36763 tcpip 5555      restarting in TCP mode port: 5555
[端末]  adb connect 127.0.0.1:5555                connected to 127.0.0.1:5555
[端末]  adb -s 127.0.0.1:5555 forward tcp:9222 localabstract:chrome_devtools_remote
[端末]  curl -m 8 http://127.0.0.1:9222/json/version
        try1 OK  {"Browser":"Chrome/153.0.8010.36", ...}
```

ワイヤレスデバッグ（TLS・無作為 port）は client 鍵のペアが要るが、`adb tcpip` の
平文 TCP は `/data/misc/adb/adb_keys` の許可制で、端末内 client はそこを通った。
**PC の秘密鍵を複製する必要はない。**

Termux の Python 3.14.6 に `pip install websockets`（17.1）を入れ、`app/solvers/cdp.py`
をそのまま実行した。**PC は経路に入っていない**（Termux Python → 端末内 forward →
Chrome for Android）。

```
connected; page targets: 3
japanese exact: True
36k fill: 36000
6MB pdf: size=6291465 in 1.57s
click -> clicked
PHONE-ONLY CDP OK
```

PC 経由の F-6-4（6 MB が 1.50 s）と同等。**転送層は会場トポロジで成立する。**

Termux に既にあったもの: fastapi 0.99.1、uvicorn 0.52.4、pillow 12.3.0、httpx 0.28.1、
python-dotenv 1.2.3、python-multipart 0.0.32。**fastapi は `requirements.txt` の
`>=0.110` を満たしていない**ので、サーバ常駐の前に上げる必要がある。

### F-6-7. スマホの chatgpt.com のセレクタ（実測、2026-09-15。送信なし）

`chatgpt.com` を開いて DOM を読んだだけで、メッセージは送っていない。
UA は `...Android 10; K...Mobile Safari/537.36`、`window.innerWidth` = 426。

| 定数 | セレクタ | 一致数 | 判定 |
|---|---|---|---|
| `COMPOSER_SEL` | `#prompt-textarea` | 1 | **合う**。`isContentEditable` が true |
| `FILE_INPUT_SEL` | `input[data-testid="upload-photos-input"]` | 1 | **合う** |
| `FILE_UPLOAD_SEL` | `input#upload-files` | 1 | **合う**（`accept=""`・`multiple`） |
| `ASSISTANT_SEL` | `[data-message-author-role="assistant"]` | 0 | 会話が無いので当然 |
| `STOP_SEL` | `[data-testid="stop-button"]` | 0 | 生成中のみ出るので当然 |
| `ATTACHMENT_SEL` | `form img, [data-testid*="attachment"]` | 0 | 添付が無いので当然 |
| `NEW_CHAT_SEL` | `[data-testid="create-new-chat-button"]` | **0** | **モバイルには無い** |

ログイン状態: `login-button` / `signup-button` が 0 件、composer が編集可能。
**サインイン済み**である（未サインインの shell は composer を持たない、F-5 系の記録）。

ページ上の `input[type=file]` は5つ。**デスクトップ実測（2026-09-14）から入れ替わっている。**

```
upload-files            accept=""            multiple   ← PDF・音声はここ
upload-photos           image/*              multiple   (testid=upload-photos-input)
upload-media            image/*,video/*      multiple
upload-camera           image/*              multiple
upload-fast-tools-files .pdf,.doc,...,.7z    multiple   ← 新規。desktop の upload-media-files は消えた
```

`NEW_CHAT_SEL` が無い件は動作を止めない。`start_new_chat()` は控えが無ければ
`page.goto(CHAT_URL)` へ落ちるので、新しいチャットは作れる。モバイルで
new/chat/sidebar を含む testid は `open-sidebar-button` と `composer-plus-btn` の2つだけで、
新規チャットは折りたたまれたサイドバーの中にある。`ROKID_CHATGPT_CHAT_SCOPE=subject`
なら 1 科目に 1 回しか呼ばれないので、ページ読み込み 1 回の差でしかない。

### F-6-8. スマホ上で FastAPI が動く（実測、2026-09-15）

`app/` を Termux へ置き、`python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
で起動した。**PC は経路に入っていない。**

```
GET /health      200  {"status":"ok","versions":{"app_version":"0.28.0", ...}}
GET /v1/version  200  solvers[] に {"name":"chatgpt-web","provider_version":"web-ui",
                                    "offline":false,"ready":true}
```

`chatgpt-web` の `ready:true` は、`cdp_available()` が**スマホ自身の Chrome を
見つけた**ことを意味する（F-6-6 の端末内 `adb forward` 経由）。

**FastAPI は 0.99.1 のまま動く。** `requirements.txt` の `fastapi>=0.110` は
この端末では満たせない。0.100 以降は pydantic 2 を要求し、`pydantic-core` は
Rust 拡張で Android wheel が無く、`pip install` は maturin で落ちる
（`app/llm_http.py` が openai SDK を避けているのと同じ理由）。

```
ERROR: Failed to build 'pydantic-core' when installing build dependencies
```

実際に載っている組み合わせ: fastapi 0.99.1 / pydantic 1.10.26 / starlette 0.27.0 /
uvicorn 0.52.4 / pillow 12.3.0 / httpx 0.28.1 / websockets 17.1。
本アプリは素の `BaseModel` とスカラ型しか使わず `Annotated` も無いので、
どちらの major でも動く。よって下限を `fastapi>=0.99` に緩めた。

### F-6-9. スマホだけで解答が返った（実測、2026-09-15）

**会場トポロジで解答が1件返った。PC はどこにも入っていない。**

```
browser: Chrome/153.0.8010.36 | chat scope: subject
prompt : 2x+3=7 を解け。（system: 解答用紙に書く内容だけを出力）
elapsed: 19.5s
reply  : 'x=2'
```

経路は Termux Python → `app/solvers/cdp.py` → 端末内 `adb forward tcp:9222` →
Chrome for Android → chatgpt.com。添付なし、1 生成。

ここへ来るまでに**欠陥が2つ**あり、どちらも stub では見えなかった。

#### 欠陥1: Enter は送信ではない（モバイル）

`send_and_read` は `keyboard.press("Enter")` で送っていた。デスクトップでは動くが、
**モバイルのウェブ composer では Enter は改行**である。3 回の attempt がそれぞれ
Enter を押し、composer に空行を足しただけで、1 件も送信されなかった。
利用者が画面で気付いて指摘した。

送信ボタンは `[data-testid="send-button"]`（`aria-label="プロンプトを送信する"`）。
**composer が空のときは DOM に出ない**ので、F-6-7 の空ページ調査では見つからなかった。
文字を入れた状態で調べ直して判明した。`submit()` はボタンを優先し、無ければ Enter。

#### 欠陥2: 座標のマウスイベントは React に届かない

ボタンを押すようにしても送信されなかった。**推測せずページを読んだ**（送信なし）:

```
composer length: 44          ← 文章は入ったまま
conversation started: False  ← URL が /c/... にならない
[data-message-author-role] total: 0
```

`Locator.click()` は `Input.dispatchMouseEvent` で要素中心の座標を撃っていた。
`data:` ページのインライン `onclick` は発火するが、chatgpt.com の React には届かない。
`HTMLElement.click()` へ変更し、無害なボタンで先に確かめた:

```
[data-testid="open-sidebar-button"] を click()
nav-ish elements before: 1  →  after: 41
```

座標打ちは layout・ズーム・可視タブに依存する。要素そのものを呼ぶほうが単純で確実。

#### 手順の教訓

生成を 3 回無駄にした。1 回目は出力の取り逃し、2 回目は欠陥1、3 回目は欠陥2。
**送信のたびに1つずつ欠陥を見つけた。** 送信前にページ状態を読んでいれば
2 つとも 1 回で分かった。実ページに対しては、送る前に読む。

### F-6-10. 添付はモデルに届く。ただしスマホでは桁違いに遅い（実測、2026-09-15）

`DataTransfer` で入れた画像は composer の添付として載り、**モデルに届く**。
PIL で 900x600 の白画像に三角形と `6391` を描いて送り、「画像に描かれている数字を
そのまま答えよ」と聞いた。返答は **`691`**。桁を 1 つ落としているが、
数字を読んでいる以上**画像は確実に届いている**（`6391` は推測できない）。
誤読は試験画像の作りが悪い（PIL 既定のビットマップフォントを 1px ずらして
9 回重ねた潰れた字）。読字精度の測定ではない。

添付が composer に載ったことの確認:

```
attach confirmed: True
thumbnails now  : 1
conversation url: https://chatgpt.com/c/6aa84bb6-...   （user メッセージが記録された）
```

#### この 1 件は所要時間の測定にならない

送信から確定まで約 280 s かかったが、**その間 OpenAI 側の安全性チェックが走っていた**
（利用者が画面で確認）。したがってこれは画像経路の latency ではない。

```
t+  0.0s stop=1 msgs=1 text=''      ← user のみ。assistant 要素すら無い
t+130.4s stop=1 msgs=2 text=''      ← assistant が現れる
t+140.5s stop=0 msgs=2 text='691'   ← 確定
```

比較のため: テキストのみ（`2x+3=7 を解け`）は同じ端末で **19.5 s**。
PC Chrome 152 での画像付きは 9.0 s（2026-09-14）。

**タブの可視性は原因ではない**ことだけは確かめた。画像の会話は
`visibility=visible`、19.5 s で返ったテキストの会話はむしろ `hidden=True` だった。

いったん「スマホでは生成が桁違いに遅い」と書いたが、**誤りだったので取り消す**。
待ち時間の内訳を確かめずに、観測した総時間をそのまま latency と呼んでいた。
安全性チェックを引いたのは、試験用に描いた白地・三角形・潰れた数字という
不自然な画像である可能性が高い。実際の試験ページ画像で測り直すまで、
この数字を根拠に既定値を動かさない。

**未測定:** 通常の試験ページ画像での所要時間。冊子 PDF（6 MB、複数ページ）での
所要時間。`ROKID_CHATGPT_TIMEOUT_S=180` と、遅い生成 2 連続で送信を止める
`SLOW_S=40` / `SLOW_STREAK=2` のブレーキがこの端末で妥当かどうか。
ブレーキは 2026-09-14 にアカウントが止まった実測から入れたもので、
**閾値の変更は利用者の判断が要る**。
（2026-09-29 追記：background解析を1教科1通にしたため、ブレーキは削除し、
`TIMEOUT_S` の既定は 9000 秒（セッション全体）にした。上の数値はその前の設定。）

`adb forward tcp:9222` を張ったまま `py -3.12 -m pytest -q` を回したところ、
`tests/test_chatgpt_web_live.py` の門（`cdp_available() is None` で skip）が
**実機の Chrome を見つけてライブ試験に入った。** 878.60 s 走り、
`test_a_deck_solves_through_the_server_threadpool` が
「the deck solved nothing through the server」で失敗。**ChatGPT への送信は
発生していない**（利用者確認）。到達可能性は「動かしてよいか」の答えではない。
門を `ROKID_CHATGPT_LIVE=1` との AND に変更した。開発機で 9222 を使わないこと。

<a id="g-local-asr"></a>

## G. F-51Fへの更新と端末内ASR（2026-09-15）

Status: Frozen measurement。APK導入、スマホ内CDP/FastAPI/ASRを実測。
Runs on: Windowsは転送と起動指示のみ。推論、VAD、API、原音保存はF-51FのTermux内。
グラスの撮影/録音やスマホAPを通した試験ではありません。

### G-1. 対象と導入

測定tuple: F-51F / Android 16 / incremental `64c964-a8f54` / Python 3.14.6 /
fastapi 0.99.1 / pydantic 1.10.26 / uvicorn 0.52.4 / Chrome 153.0.8010.36。
グラスのincrementalは `1.25.015-20260903-150201`、Hi Rokidは
`G1.13.8.0828` (code 10130008)。今回の経路ではCXR-Lを使用していません。
APKのソースcommitは `8163b5f`、サーバの配布commitは `12004a4`。

利用者は対象グラスへのAPK導入とF-51Fの更新・ASR設定を承認し、LED監査は
システム固定のため不要と指定しました。外部LED観察は実施していません。

- `adb devices -l` → グラス `192.168.0.4:5555`、F-51F `192.168.0.30:38615`、
  F-51Fの別mDNS endpoint。指定したserialを全操作に使用。
- 旧APKをpullして保全し、`apksigner verify --print-certs` で署名SHA-256
  `906307478018e09e2937cfd8042a674d27598767577e08a304472aae407ccacc` を照合。
- `$env:AGENT_APPROVED=1; adb -s 192.168.0.4:5555 install -r <APK>` → `Success`。
  `dumpsys package dev.rokid.docscanglass.doc` → versionCode 8、versionName 0.7.0。
  APK SHA-256 `599BC0CC4F8151373B0EEFD0B8A62D71C089ABC9383AFA6C1BF60A2EFCC2E4A6`。
- Termuxの空プロンプトを画面で確認して `termux-wake-lock` / `sshd` を起動。
  SSH接続拒否から復旧。Chromeを前景へ戻して、端末内ADBのserial `emulator-5554` から
  `forward tcp:9222 localabstract:chrome_devtools_remote` → `9222`。
- 旧コードとSQLite backupを `~/rokid-backups/pre-multimodal-8163b5f` に保全。
  移行前後の `PRAGMA quick_check` → `ok`、既存9テーブルの件数は全て0のまま。
  pagesの撮影時刻とsolutionsの図/資料不足メタデータ列の存在を確認。
- サーバ待受は部品試験用 `127.0.0.1:8000`。AP向け公開は未適用。
  `ROKID_REAL_MODE` は既定0、cloud analyzer未設定、API認証キー未設定なので、
  現行の実機受け入れにあるreal-mode/認証条件を満たしたとの主張はしません。

スマホ内HTTPの実行結果:

| コマンド/リクエスト | 出力 |
|---|---|
| `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log` | `Application startup complete` |
| `GET /health`、`GET /v1/version` | HTTP 200、APP/APIは配布コードと一致 |
| `GET /v1/listening-ready` | HTTP 200、`ready: true`, `asr: whisper.cpp`, `sample_rate: 16000` |
| `GET /v1/version` のsolver情報 | `chatgpt-web` が `ready: true`, `offline: false` |
| `GET http://127.0.0.1:9222/json/version` | HTTP 200、Chrome 153.0.8010.36 |

この測定でChatGPTへ質問や添付を送信していません。
終了時の `dumpsys power/window` はAwake、Chrome前景、ScreenOffTimeout 120000ms。
長時間の画面保持や、スマホを伏せた運用の証明ではありません。

### G-2. ビルド成果物と改行

`bash scripts/build_local_asr.sh` をスマホ上で実行。cmake 4.4.3、clang 21.1.8。
whisper.cppの固定revisionは `2eeeba56e9edd762b4b38467bab96c2517163158`。

最初の配布ではWindowsの `git archive` がscriptをCRLFへ変換し、
`set: pipefail CR: invalid option name` で停止しました。Git blobのCRLFは0件、
tar内では17件でした。`.gitattributes` の `*.sh text eol=lf` で配布物もLFに固定。
再配布後のスマホで `bash -n scripts/build_local_asr.sh` → exit 0。

- 修正版tar SHA-256: `3d51669958feecdef0b1b39db9ea2a3301cc0df11f94cffec431f4cd483dab61`。
- ビルド出力: `[100%] Built target whisper-cli`、モデル2個の `verified` 出力。
- CLI SHA-256: `5d8b9f5985f7b52da567f13fb7ee18a21ab06f01eb3c6c5f9a116a167e1f9c62`。
- base.en SHA-256: `a03779c86df3323075f5e796cb2ce5029f00ec8869eee3fdfb897afe36c6d002`。
- Silero VAD SHA-256: `2aa269b785eeb53a82983a20501ddf7c1d9c48e33ab63a41391ac6c9f7fb6987`。

### G-3. 速度と元音声時刻

入力は固定した公式whisper.cppのサンプル音声。padded版は前後に3秒ずつ無音を追加。
スマホ内の `multimodal.env` を読み込み、次を実行しました。

| コマンド | 音声長 | wall秒 | 実時間比 | segmentの元音声時刻 |
|---|---:|---:|---:|---|
| `python scripts/benchmark_local_asr.py data/local-asr/jfk.wav` | 11秒 | 5.109 | 0.464 | 150–10790ms |
| `python scripts/benchmark_local_asr.py data/local-asr/jfk-padded.wav` | 17秒 | 5.814 | 0.342 | 3160–13620ms |

実時間比は処理秒÷音声秒。短いサンプルでは1未満でした。
モデル読み込みを含みます。30分継続、熱、撮影/OCRとの競合は評価していません。

### G-4. 2チャンクAPIと原音保全

スマホ上の `python -` からhttpxで、padded音声を2回連結した34秒を送信。
テスト文書はdocument_id 1で、タイトルにASR smokeと公式サンプルであることを明記。
撮影入力を使った試験ではありません。

1. `POST /v1/documents` で作成。
2. `POST /v1/documents/1/audio-chunks` にsequence 0（30秒、480000 samples）と
   sequence 1（前区間との1秒重複を含む5秒、80000 samples）を送信。
3. 同じsequence 1を再送し、応答が完全一致することをassert。
4. `POST /v1/documents/1/audio-complete`、`expected_chunks=2`, `total_samples=544000`。
5. 保存されたoriginal.wavのPCMと入力PCMを比較し、完全一致をassert。

出力: `retry: identical`, `status: complete`, `chunks: 2`, `total_samples: 544000`,
`original_preserved: true`。ASRはsequence 0が8.142秒（実時間比0.271）、
sequence 1が3.893秒（0.779）。原音PCM SHA-256は
`45c3f8b866723b62dd1ac54187c19e36ed140ba91ab0e0e16401946199a97614`。
メタデータと原音はスマホのdata/audio/document-1、結果はdata/asr-smoke-12004a4.jsonに保全。

**未測定:** グラスのマイクとカメラの同時使用、3秒実画像確認、手動取り直し、消灯/復帰、
AP経路、長時間運用、実リスニングの正答率、ChatGPTの原音受理、画像/PDFの精度差。

## H. 起動二択と診断キー入力（2026-09-16）

Status: Frozen measurement。グラス firmware `1.25.015-20260903-150201`／serial
`1904092623381086`／glassdoc commit `db4255d`と入力ログ2行を加えた診断APK。
Runs on: Windowsからグラス `192.168.0.4:5555`。スマホAP経路の受け入れではない。

`adb devices -l` は3接続。スマホのIPとmDNSは同じserial `ZY22LWGDCV` と照合済み。
グラスの `getprop ro.serialno` は上記serial、`vendor.rkd.glasses.is_spread` は1。
導入前の既存APKをpullして保全し、新APKと証明書SHA-256が一致することを確認した。
承認済みの書込みは `$env:AGENT_APPROVED=1` を指定して実行した。

- `aapt2 dump badging` → package `dev.rokid.docscanglass.doc`、
  launchable activity `dev.rokid.docscanglass.doc.DocScanGlassActivity`。
- `apksigner verify --verbose --print-certs` → `Verifies`、v2=true、証明書SHA-256
  `906307478018e09e2937cfd8042a674d27598767577e08a304472aae407ccacc`。
- `Get-FileHash -Algorithm SHA256` → db4255d APK
  `A375A10D71CD158D5A98568289A1D75F59F39774CC6A5B2043A4E8ACADD4156A`。
- `adb -s 192.168.0.4:5555 install -r <APK>` → `Success`。
  `am start -W -n dev.rokid.docscanglass.doc/.DocScanGlassActivity` → `Status: ok`、WaitTime 3053ms。
  ただし導入前からAsleepで、起動直後のscreencapは黒。`KEYCODE_WAKEUP` 後に二択を確認した。
  この時間を選択から取得までの速度や、装着による起動の証拠にしない。
- 診断ログ追加後の `./android-relay/gradlew --no-daemon :glassdoc:assembleDebug`
  → `BUILD SUCCESSFUL in 1m 7s`。APK SHA-256
  `F43FBFDC75C6B62C80A0640464C83D14667BC76E04CE067880841324128A279F`。
  identityと同じ署名を照合して導入 → `Success`、起動 → `Status: ok`。

診断用 `adb shell input keyevent` は表示先の既定が-1。この条件ではActivityに入力ログがなく、
二択も変わらなかった。`dumpsys input` のfocused displayは0。
次のように明示するとログと選択画面の双方に反映された。

| `adb -s 192.168.0.4:5555 shell` 以下のコマンド | 出力・観測 |
|---|---|
| `input -d 0 keyevent KEYCODE_NOTIFICATION KEYCODE_DPAD_RIGHT KEYCODE_DPAD_DOWN` | `action=SWIPE_FORWARD` 1回、リスニングを選択 |
| `input -d 0 keyevent KEYCODE_NOTIFICATION KEYCODE_DPAD_LEFT KEYCODE_DPAD_UP` | `action=SWIPE_BACK` 1回、通常の読取へ戻る |
| `dumpsys media.camera` | 前後とも `Active Camera Clients: []` |

これは合成KeyEventの測定で、物理スワイプの重複・相関幅を検証したものではない。
タップによる開始、撮影、録音、ChatGPT送信は行っていない。LEDの物理観察も行っていない。
privateのno-backup領域に暗号化設定ファイルが作られたが、実API鍵の設定・認証再起動は未実施。
画面証跡はignoredの `data/device-setup/startup-display0-{listening,normal}.png` に保全した。

## I. 認証設定・LAN接続・再起動復号（2026-09-16）

Status: Frozen measurement。glassdoc/server source `8cc1ad2`。グラスfirmware
`1.25.015-20260903-150201`、serial `1904092623381086`。F-51F `ZY22LWGDCV`、
build `64c964-a8f54`、Python 3.14.6、Chrome `153.0.8010.36`。
Runs on: グラス → 既存Wi-Fi → F-51F FastAPI。スマホAP経路ではない。

利用者がAPI鍵の新規設定、F-51Fの `192.168.0.30:8000` 待受、グラスへの暗号化保存を承認した。
API鍵はF-51F上で生成し、値は記録・コマンド引数・リポジトリへ出していない。

- `git archive` のapp配布tar SHA-256は
  `8bb69b9d0b8682f1c626ef534ead2975073592d285e219644242454f0dabf75a`。
  旧appとenvを `~/rokid-backups/pre-auth-8cc1ad2-20260915T192314Z` に保存し、SQLite backupを作成。
  `PRAGMA quick_check` → `ok`。更新前後の9テーブル行数が一致（documents 1、他0）。DB実装も同一。
- スマホで `python -m uvicorn app.main:app --host 192.168.0.30 --port 8000 --no-access-log` を起動。
  設定はREAL_MODE=1／client-ocr／chatgpt-web。envのmodeは0600、データディレクトリとASR設定は維持。
  `/health` → 200、`/v1/documents/1/scan-status` → 無鍵401／誤鍵401／設定鍵200。
- Chrome前景・Awakeに戻した後、`/v1/settings` → 200、analyzer/solver ready=true。
  Termux前景ではCDPが失われた。readyは解答精度・会場経路の証明ではない。
- 新APK SHA-256
  `98A87A0E642E0E32CA9DD3F745A1155DC28ED13488B309ACCE10AFBC14D45B1C`。
  `aapt2 dump badging` でpackage/activityを照合、`apksigner verify --print-certs` → `Verifies`。
  署名SHA-256は `906307478018e09e2937cfd8042a674d27598767577e08a304472aae407ccacc` で既存APKと一致。
  承認済みの `adb -s 192.168.0.4:5555 install -r` → `Success`。
- `py -3.12 data/device-setup/verify_glasses.py` → exit 0、
  `restart_decryption_and_resave=true`、`fresh_ciphertext=true`、`plaintext_setup_absent=true`。
  アプリUIDから同じscan-statusへ無鍵401／設定鍵200。privateの一時設定ファイルは除去され、
  再起動後のconnection.binはGDC1ヘッダーの暗号文。設定URL・鍵の平文は含まれない。
- この設定確認時点ではカメラを開始していない。後の利用者操作による撮影は§Jに分ける。
  AP／security設定は変更していない。全体の受け入れ、LED物理観察は未実施。

## J. 取消申告・確認画像・折りたたみ後の起動（2026-09-16）

Status: Frozen measurement。device/firmware/installed sourceは§Iと同じ。
Runs on: 実グラスの利用者操作ログ、保存JPEG/OCR、F-51F DB。修正前の観測。

`adb -s 192.168.0.4:5555 logcat -d -v time DocScanGlassDoc:I *:S` の保存ログから次を確認した。

| 時刻（端末ログ） | 観測 |
|---|---|
| 04:34:50.369 | SHORT_TAPで通常撮影開始 |
| 04:34:53.751／56.721／58.855 | 4032×3024 JPEGを取得。1434／1071／845ms |
| 04:35:00.002 | 最良画像の確認表示ACK、delay=3000 |
| 04:35:03.374 | local photo committed |
| 04:35:03.521 | BACKを正規化。続いてFINALIZING |
| 04:35:07.105／08.858／09.507／12.225 | 単タップ／前後スワイプ／BACKも届いていた |
| 04:35:37.761 | assistserverが本アプリをforce-stop。Activity exit reason=10、USER REQUESTED |

したがって「1枚キャンセル」の申告に対応した操作は、保存後のダブルタップで撮影終了へ進んでいた。
期限内の単タップ取り直しが観測されたとは言わない。解析待ちの最初のBACKには終了確認の表示がなく、
後のBACKまでに別入力も挟まったため、2回操作の終了確認は成立していなかった。

原本をignored `data/device-setup/reported-cancel-local-scans.tar` へ保全。ローカルは
phase=ANALYSIS、document=2、session=1、写真1枚。F-51Fはdocument ready、session reviewing、
questions 1、solutions 0。保存JPEGは5,850,017 bytes、OCRは2文字だけだった。
実画像は紙面が暗く、机・周囲も多い。原本は回転180度の指定を持つ。表示補正でOCR精度が直るとは扱わない。
修正前のB5単頁ガイドは480×640の画面内に255×360。確認表示は上側62%を写真領域とする描画だった。

折りたたみ後のホームでアプリ一覧を開き、スワイプで「DocScan Glasses」を選び単タップした。
診断入力は§Hの `input -d 0` を使用。`dumpsys activity activities` →
`topResumedActivity=dev.rokid.docscanglass.doc/.DocScanGlassActivity`。
`fold-launcher-opened-active.png` は通常／リスニング／中断した読取の選択画面。
カメラは開始していない。アプリ一覧からの起動経路を確認したもので、再装着だけの自動起動ではない。

## K. 向き・拡大確認・スマホからの開閉復帰（2026-09-16）

Status: Frozen measurements。開閉試験のAPKはbde4f09、グラスは§Jと同じ1904092623381086／1.25.015-20260903-150201、F-51FはZY22LWGDCV。
Runs on: 再起動watcherはF-51F Termux → 同一Wi-Fiのグラス。画像QAとbuildはWindows。

利用者は枠の改善を確認したが、写真が小さく文字・ブレを判別しづらい、角度も違うと申告。
さらに単頁ではなくB5見開きの枠と、少し近い距離での撮影を指定した。

- 直近保存JPEG2枚は4032×3024、EXIF Orientation=1、保存rotation=180、OCRは17／26文字。
  Android Bitmap/Matrixで90／180／270を描画すると270で縦書きの「第1問」が正立、180は横向き。
  過去の180度記録はこの入力の正立を証明していなかった。私的写真はGit対象外。過去pendingは変更しない。
- 一時native描画試験 `:glassdoc:testDebugUnitTest --tests '*CaptureOrientationRenderTest'` → `BUILD SUCCESSFUL in 34s`。
  中央2倍・右下全体像の実写真QAは同じ試験で `BUILD SUCCESSFUL in 28s`。
  出力 `android-relay/glassdoc/build/outputs/photo-review-magnified.png`。一時テストを除去後に全体gateを実行。
  光学表示でのブレの判別、補正後OCR精度は未検証。
- F-51Fからグラスへ接続。最初のconnectは認証失敗を表示したが、直後のdevicesはdevice。
  `getprop ro.serialno` → `1904092623381086`、`getprop vendor.rkd.glasses.is_spread` → `1`。
  新しい鍵の生成・移送は行っていない。スマホから既存Activityを起動しPID8693を確認。
  `dumpsys media.camera` → `Active Camera Clients: []`。
- F-51Fで `scripts/watch_glasses.py` を実行し、利用者がツル閉約2秒→開で「選択画面に戻った」と回答。
  ログ `Glasses unfolded: chooser started`。保存先は `~/rokid-server/data/watch-glasses.log`、PIDは同じ場所の `watch-glasses.pid`。
  script SHA-256: `903c94dc39777cbac8fd3b6e7032093758dfc3a277e402f6498a7b75b0dd63fa`。
  1回の家庭Wi-Fi開閉であり、AP・通信断中の開閉・着脱だけ・CLOSED後・反復は未検証。
- watcherの曖昧な起動応答を再送しない試験: 修正前 `1 failed, 1 passed`、修正後
  `py -3.12 -m pytest -q tests/test_watch_glasses.py` → `2 passed in 0.03s`。
  通信断中に閉状態を見逃した開閉は自動復帰しない制限をrunbookへ記録。
- 全Android `test testDebugUnitTest assembleDebug` → `BUILD SUCCESSFUL in 54s`、199 tasks。
  見開き初期値・ラベル後 `:glassdoc:testDebugUnitTest :glassdoc:assembleDebug` → `BUILD SUCCESSFUL in 50s`、63 tasks。
  JDK17.0.20.1+1／SDK Platform36 rev2／Gradle9.4.1、ASCII checkout。
  `aapt2 dump badging` → package `dev.rokid.docscanglass.doc`、DocScanGlassActivity、versionCode12。
  `apksigner verify --verbose --print-certs` → `Verifies`、v2=true、既存証明書と一致。
  `Get-FileHash` → `29CFF4401AA1CC44B746B2B00FC5DDDC978F5BE5DD83ACAA947451E838AB0E3A`。
  導入前installed APKは§Jのhashと一致。保存4件をtarへ退避し原本を保全。

## L. 確認期限をまたぐ単タップと傾きの申告（2026-09-16）

Status: Frozen measurement。グラス1904092623381086／1.25.015-20260903-150201、実機APKはf8ce0fa（§K hash）。旧P1記録はbde4f09（§J hash）。F-51F appは8cc1ad2。
Runs on: 実グラス、家庭Wi-FiとF-51F。修正の回帰試験とbuildはWindows。修正版の実機適用は未実施。

§KのAPKを `adb -s 192.168.0.4:5555 install -r` で導入 → `Success`、起動 `am start -W` →
`Status: ok`／`LaunchState: COLD`／`TotalTime: 2064`。保存4件のmanifestは導入前後でbyte一致。
保存設定も見開きtrueへ反映した。新しい写真はrotation=270を持つ。

利用者は「P1を撮りなおしタップを行ってもP2に行く」と申告。
`adb -s 192.168.0.4:5555 logcat -d -v threadtime DocScanGlassDoc:I *:S` の記録は次のとおり。

| 端末ログ時刻 | 観測 |
|---|---|
| 05:51:53.694 | page index 1の確認可視ACK、delay=3000ms |
| 05:51:56.179 | NOTIFICATION、表示から2485msで操作開始 |
| 05:51:56.697 | ENTER／SHORT_TAP、表示から3003ms |
| 05:51:56.869 | local photo committed |
| 05:51:56.870 | 同じタップでpage index 2のAIMINGへ進んだ |

旧bde4f09にもP1（index0）で05:13:36.597 ACK、39.467 NOTIFICATION、39.810 commit、
40.017 SHORT_TAP、40.018 index1 AIMINGがある。単タップは最初の通知から約0.5秒後に
確定していた。`onAction` は取得時刻を持っていたがControllerへ渡しておらず、分類待ちも
保存タイマーを保留しなかった。ログにはOCR本文や写真データを出していない。

修正テスト `:relaycore:testDebugUnitTest --tests '*LocalReviewTest.tapStartedBeforeDeadlineRetakesSamePageAfterFirmwareClassification'`
は修正前 `1 test completed, 1 failed`（expected0 / got1）、修正後 `BUILD SUCCESSFUL in 25s`。
開始時刻と確認世代を保持し、実測相関窓970ms内の分類待ちとqueuedRetakeを保護。
独立レビューの早い取り直し後の次操作もREDで再現し、旧window退役で対応した。
実機での修正確認は利用者の停止依頼により次回へ持ち越す。全gateとAPKは進捗記録を参照。

利用者は傾きについて「用紙が斜めに傾いて写る」と回答。保存画像には上下の辺が平行でない形もあり、
一律回転で直るとは確認できない。doc6のOCR78／0文字、doc7は6文字、doc8は0／38文字。
いずれも同じ見開きで、**片ページとの比較ではない**。光学可読性、ブレ判別、傾き補正、
単頁／見開きのOCR・解答精度は未検証。画像とOCR内容はGit対象外のローカル保全のみ。

# 出典

## M. ファームウェア1.29.013での撮影構成と自動撮影（2026-11-12）

Status: Frozen measurement. 機体 `RG_glasses`（serial末尾1086）、fingerprint
`Rokid/glasses/glasses:12/SKQ1.240613.001/1.29.013-20261110-150201`（ビルド 2026-11-10 17:47 CST）。
接続は PC → スマホ上の中継 → テザリング → グラス adb。操作はすべて PC からの adb（`am start`、
`input keyevent`）で、装着者の操作なし。場面は暗所（撮れた画像の平均輝度 8.4/255）で、
**紙面の写り・文字の判読は測っていない**。

### M-1. JPEG出力を他の出力と同じセッションに置くと静止画が返らない

`:glassprobe` に `--es camera_variant` を加え、同じ機体で順に実行した（各1回、`reconfig` は4回）。

| variant | 結果 |
|---|---|
| なし（JPEGのみのセッションで1枚） | OK 829〜1174 ms（4回） |
| `preview=320x240`（YUVプレビューを繰り返し、同じセッションでJPEG） | 15秒で画像なし |
| `preview=320x240,af_off,ae_on` | 15秒で画像なし |
| `preview=640x480`／`preview=1440x1080` | 15秒で画像なし |
| `preview=320x240,stop`（静止画の前に繰り返しを停止） | 15秒で画像なし |
| `preview=320x240,zsl_off`（`CONTROL_ENABLE_ZSL=false`） | 15秒で画像なし |
| `preview=320x240,both`（静止画要求にプレビュー出力も含める） | 15秒で画像なし |
| `preview=320x240,priv=640x480`（PRIVATEのプレビュー出力を追加） | 15秒で画像なし |
| `preview=320x240,reconfig`（撮る時だけJPEGのみのセッションへ組み替え） | OK 4回中4回。組み替え 0.74〜0.81秒＋撮影 約0.8秒 |
| `preview=320x240,yuvstill`（静止画を4032x3024のYUVで受ける） | OK。要求から0.74秒、プレビュー継続 |

画像が返らない場合、カメラサービスは `In-flight list too large`（71→251件）と
`metadata arrived: false` を出し続け、約10秒後に `vendor.qti.camera.provider` が
`ExtensionModule::ProcessSystemEventMessage` で SIGABRT、アプリへは `camera error 4`
または `CAMERA TIMEOUT`。パイプライン名は `RealTimeFeatureZSLPreviewRawRokid`。
2026-09-27 の glassdoc（`6149beb`、build `1.25.012`）は YUV＋JPEG の1セッションで撮れていた記録があるが、
旧ファームウェアでの再実行はしていない。

### M-2. プレビュー1枚の処理時間

glassdoc vc61（非debuggable・`status=speed`）で処理ごとの最大時間を記録した。
1枚 173〜213 ms（毎秒3枚）のうち、表示用の縮小ループが 141〜285 ms。ループ内で
1画素ごとに `Image.getWidth()`／`getHeight()` を呼んでおり（320x240 で約15万回）、
1枚につき1回へ直すと 5〜11 ms、1枚全体で最大 47 ms（毎秒8〜14枚）になった。
`addd40a` が原因とした「Y面を1画素ずつ読む」は、修正後も 173〜213 ms のままで原因ではなかった。

### M-3. glassdoc 0.43.10（vc62）の自動撮影

プレビューのみのセッションで待ち、静止画ごとにJPEGのみのセッションへ組み替え、取得後に
プレビューへ戻す。`scripts/glasses_device_check.py`（当時の名称は glasses_capture_smoke）`--serial 127.0.0.1:5556` を3回：3回とも PASS
（4032x3024、7.25〜7.33 MB、1491〜1656 ms、プレビュー処理 最大 39〜43 ms）。
1セッション内の連続4枚（待機中タップ）も頁0〜3がすべて保存まで完了（各 1481〜1514 ms）。
手動露出（1/120秒・ISO 800、`ae_state=0`）の静止画も同じ方式で完了した。
スマホのサーバには文書20の頁0として JPEG 7,230,339 バイトが届き、SHA-256 は出所情報と一致した。

### M-4. 同じ頁の連続撮影と、その後の修正（glassdoc 0.43.12／vc64、同日 19:00〜19:35）

M-3 の版（vc62）を薄明るい場面（プレビュー露光 50〜60 ms）で動かすと、動かない場面を15秒間に5枚撮った（頁変化の連番が 3→4→6→7→9…、2枚の差分は平均 0.56/255）。静止画のあとにプレビューのセッションを作り直すと露出が最初から合わせ直され（再開直後の露光 1.2 ms → 60 ms）、その間のフレームを頁めくりと数えていた。M-3 は暗所で、露出が動かなかったため出なかった。

修正：再開したストリームで新しい収束済みの測光結果が届くまで（上限2秒）、フレームを頁変化の証拠にしない。実機では再開から 1114〜1486 ms で観測へ戻り、動かない場面で15秒間の追加撮影は0枚（`scripts/glasses_device_check.py`：`1 photo(s) in the 15 s after the first was saved`、PASS）。

単タップの休止（本人指示）：休止で `dumpsys media.camera` は `Active Camera Clients: []`・`Device 0 is closed`、画面取得は非黒画素0、プレビューのフレーム処理も停止。再開のタップで約1.1秒後に観測へ戻り、同じ場面は撮り直さない。休止中の前スワイプは無視、再開後の前スワイプ（NOTIFICATION→DPAD_RIGHT→DPAD_DOWN）で手動撮影から保存まで完了。

この方式の既知の弱点：静止画ごとに、撮影 約1.4秒＋露出の落ち着き 約1.1〜1.5秒はプレビューが無い。先読みで撮った頁は、原本の保存がカメラ用スレッドを塞ぐため、撮影からプレビュー再開まで約3.5秒かかった（19:04:22→19:04:25.6の1回）。この間の頁めくりは動きとしては見えず、再開後に撮影済みの頁との違いで検出する。見た目の近い頁で検出を逃すかは未測定。M-1 の `yuvstill`（プレビューを止めずに原寸を受ける）へ移せばこの空白は無くなるが、JPEG化と出所情報の扱いが変わるため未実装。

### M-5. プレビューを止めない静止画：原寸YUVを同じセッションで受ける（glassdoc 0.43.13／vc65、同日 20:05〜20:30）

`:glassprobe` の variant（`yuvstill`、`jpeg=<品質>`、`manual`、`count=<n>`、`nr=<mode>`、`edge=<mode>`、`keep`）で計測。場面は暗所（平均輝度 11/255）。

| 項目 | 結果 |
|---|---|
| 原寸YUV（4032x3024）をプレビュー（320x240）と同じセッションで要求 | 14回中14回届いた。要求から 654〜739 ms |
| その間のプレビュー | 止まらない（静止画1枚の間に約9フレーム、毎秒約12枚を維持） |
| 1セッションで連続4枚（自動露出／手動露出 各1回） | 8枚とも成功 |
| 手動露出（AE切、露光・感度・フレーム時間・後段ゲインをプレビューの値で指定） | 結果は `ae_mode=0`、指定どおりの露光・感度 |
| NV21への写し（カメラ用スレッド） | 38〜63 ms（`luma_row=4032 chroma_row=4032 chroma_step=2`） |
| JPEG化（`YuvImage.compressToJpeg`） | 品質95で 192〜200 ms、品質98で 269〜448 ms |
| 雑音除去 `nr`=0／1／2／3（品質98） | 12.2／3.45／3.41／7.66 MB。要求どおり結果に反映 |
| 同じ場面のカメラJPEG（JPEGのみのセッション） | 7.83 MB。量子化表の平均 2.4／3.5（品質98相当） |

原寸であることの確認：半径1のぼかしとの差の標準偏差（画素単位の成分）は、カメラJPEGが 7.26、YUVで雑音除去と輪郭強調を切ると 7.04。
隣接画素差もカメラJPEG 11.91、YUV 10.99 で、YUVは縮小・拡大を経ていない原寸の画素を持つ。雑音除去が標準（HQ）のYUVは 0.93 で、
暗所ではカメラJPEGよりはるかに強く雑音が除かれる（カメラJPEGは結果に `nr=2` と出るが雑音は残る）。
**明るい紙面で、どの設定が文字に最も良いかは未測定**。既定はカメラの標準（静止画テンプレートのまま）とし、
比較は既存の `settings_bracket=true`（雑音除去・輪郭強調の切替を含む）で行う。

glassdoc 0.43.13：静止画は原寸YUVをプレビューと同じセッションで受け、画像を閉じてから別スレッドで品質98のJPEGにする。
`scripts/glasses_device_check.py` 3回とも PASS（要求から保存用JPEGまで 960〜1019 ms、以後15秒の追加撮影0枚、プレビュー処理 最大52 ms）。
1セッション4枚（前スワイプ）は 970〜1199 ms、その間も頁変化の連番は動かず、休止でカメラが閉じ、再開後の落ち着きは 1187 ms。
スマホのサーバは4枚とも受理し、JPEGのSHA-256は出所情報と一致、PILで 4032x3024・4:2:0 として復号できた。
このJPEGにはEXIFが無い（露光などはアップロードの出所情報に入る）。出所の種別は従来どおり `native_still` で、
「カメラの静止画要求1回の原寸画像」を指す。符号化がカメラかアプリかを区別する種別はサーバ側に無い。
原寸YUVとプレビューの組が拒否されたカメラでは、M-3 の「JPEGのみのセッション」へ自動で戻る（単体試験のみ、実機では未発生）。
M-4 に書いた「静止画ごとの約3秒・先読み時約6.5秒の観測の空白」は、この経路では生じない。

### M-6. 薄暗い実紙で出た3件と通し検査（glassdoc 0.43.14／vc66、同日 20:35〜21:45）

場面は薄暗い部屋（プレビューの露光 50〜60 ms・ISO 800・後段ゲイン約3.6倍）。グラスは机上に置かれ、
カメラは水平に部屋を向き、紙は手前に斜めに入るだけで、**読む姿勢の写りではない**。

1. **静止画が暗い**：露光を照明のちらつき1周期に固定し、感度の上限を超える分は暗くする規則（11/10）では、
   プレビューが50 msを要した場面の静止画が10 ms・ISO 800になり、平均輝度 16.8/255。同じ場面を50 msで撮ると 61.9。
   規則を「感度の上限が許す最少の周期数で、プレビューと同じ光量を保つ」へ変更。変更後の実機：プレビュー50 ms・静止画50 ms、
   明るい側4分の1の平均 116/255。
2. **静止画の露出がプレビューへ漏れる**：静止画の要求から 0.55〜0.9 秒後のプレビュー2枚の平均輝度が 70 → 155 → 80 → 70 と変化した
   （露出の状態は収束済みと報告される）。粗い頁変化判定が `level_shift=+84`、次に `−75` として2回数え、動かない頁を3枚撮った。
   静止画の処理中に、直前の静かなフレームより 1.3倍＋8 を超えて明るいフレームだけを頁変化の証拠から外した。
   変更後は15秒間の追加撮影0枚。暗い側の漏れ、明るい場面での漏れの大きさは未測定。
3. **選択画面で単タップが表示オフにならない**：単タップが開始に割り当てられていた。全画面で
   「単タップ＝表示オフ／オン、スワイプ＝選ぶ、ダブルタップ＝決定」へ統一。システムの消灯はスマホの見張り役経由で
   約1秒（一度は2秒超）かかるため、タップ時にアプリ側で即座に表示を消す。

雑音除去の比較（同じ薄暗い場面、紙の文字は写っていない）：標準（HQ）は平坦部が滑らかだが線の縁に点状の乱れ、
切ると雑音が増えるが線は素直。文字での優劣は未判定。

`scripts/glasses_device_check.py`（撮影だけの検査から拡張）：環境（機体・ファーム・畳み・版・コンパイル・権限・電池・スマホのサーバ）、
選択画面（単タップで消灯・次の操作は復帰のみ・ダブルタップで開始）、撮影（自動の1枚・原寸・3秒後の保存・露出・動かない場面で追加撮影なし・
プレビュー処理時間・小枠の位置）、休止（カメラ閉・画面黒・休止中のスワイプ無効・再開・撮り直しなし・前スワイプ撮影）、
サーバ到達（バイト数一致・明るさ・同じ頁の重複）を順に確かめる。vc66 で29項目すべて通過（グラス単体、スマホ側の項目は接続時に3枚到達を確認）。
adbから送るキーは消灯中の機体へ届かないため、「実際のタッチで復帰するか」はこの検査の対象外。
`--paper <秒>` は、装着者が頁をめくるだけの通しを記録する（撮影時刻、頁変化と数えた理由、明るさ、重複）。未実施。

### M-7. 装着での1回目：撮れない、とその原因（glassdoc 0.43.14→0.43.15／vc67、同日 22:23〜22:55）

装着した状態（プレビューの露光 50〜60 ms・ISO 800）。当初ここに「薄暗い部屋」と書いたのは露光値からの推測で、照度も標準カメラとの対照も取っていなかった。本人は 11/13 に「部屋が暗いのではない」と指摘した（§M-9）。`scripts/glasses_device_check.py --paper 120` は
選択画面まで通過し、開始後30秒で最初の1枚が撮れず中断した。37秒間のログ：

- 撮影の準備に3回入り（22:23:56、24:08、24:20）、3回とも10秒で `Local preparation expired before any camera request`。静止画の要求は0回。
- 準備中の20秒間、ジャイロの静止判定は一度も成立しなかった。M-6 の露出規則（プレビューと同じ露光）では静止画が 50〜60 ms になり、
  静止の上限は 0.12 rad/s × 10 ms ÷ 露光 ＝ 約 0.02 rad/s（毎秒約1.1度）。実測の角速度は記録していなかった（以後 `head_rad_s`／`limit_rad_s` を毎秒記録）。
- 頁変化は35回数えられた（細かい判定26回・粗い判定8回・初回1回）。最初の1枚を撮る前は位置ずれの補正が働かない作りで、撮影の妨げにはなっていない。

カメラ内の増幅（`CONTROL_POST_RAW_SENSITIVITY_BOOST`）で明るさを保てるかを `:glassprobe` の `gain=<倍率>` で計測（同じ場面、ISO 800、プレビューの増幅 800）：

| 静止画 | 平均輝度 | 平坦部の雑音 | バイト数 |
|---|---|---|---|
| 露光 70 ms（プレビューと同じ） | 40.7 | 1.49 | 4.2 MB |
| 露光 10 ms、増幅そのまま | 14.4 | 1.48 | 3.5 MB |
| 露光 10 ms、増幅6倍（要求 4800、公表範囲の上限 3199 を超えるが結果は 4800 と報告） | 39.3 | 3.92 | 7.5 MB |
| 露光 20 ms、増幅3倍 | 43.5 | 2.73 | 7.0 MB |

露出規則を三たび変更（0.43.15）：ちらつき1周期のまま、まず感度を上限まで、次にカメラ内の増幅を公表範囲の上限まで使う。
それでもプレビューより1段を超えて暗くなる場合だけ周期を増やす。10 ms なら静止の上限は 0.12 rad/s（毎秒約6.9度）で、
9月に装着で撮れていた頃と同じ値。変更後、机上の通し検査は33項目失敗なし（プレビュー70 ms・静止画10 ms）。
非常に暗い場面（平均輝度38）では増幅後の写真に強い色雑音が出た。**増幅した写真で紙の文字が読めるか、装着で実際に撮れるかは未確認。**

PC上の再現（実写の紙面3頁から、頭の揺れ 0／0.5／1／2／4 度・雑音・±4%の明るさ変動を加えた 320x240・毎秒12枚の列を作り、
実機と同じ `PageChange`／`LumaPageEvidence` へ流した。手・ぶれ・照明むらは含まない）：

| 場面 | 結果（全ての揺れ幅で同じ） |
|---|---|
| 同じ紙を30秒見続ける | 撮影1枚、撮り直し0 |
| 別の紙へ替わる（めくる・差し替える・裏返す） | 各1枚、替わって約0.4〜0.5秒で検出 |
| 大きな紙で視線を別の場所（画角の約14度先）へ移す | 移す前後で各1枚 |

### M-8. カメラとジャイロの報告値、9月の実写の集計（2026-11-12 23:20〜、読み取りのみ）

グラスは机上・消灯のまま。`dumpsys media.camera`（同日保存分）と `dumpsys sensorservice` の読み取りで、撮影はしていない。

| 項目 | 報告値 |
|---|---|
| レンズ | `availableApertures` 2.25、`availableFocalLengths` 1.90 mm、`minimumFocusDistance` 0（固定焦点） |
| センサー | `physicalSize` 4.032×3.024 mm、`pixelArraySize` 4032×3024（画素 1.0 µm、焦点距離は約 1900 画素） |
| 合焦 | `hyperfocalDistance` 1.2465 D（0.80 m）。撮影結果の `lens.focusDistance` 2.9499 D（0.34 m）、`focusRange` 2.95〜0.10 D。`focusDistanceCalibration` は APPROXIMATE。過焦点に合焦なら近端は 0.40 m、0.34 m に合焦なら遠端は無限にならず、**値どうしが合わない。実際の合焦面は未計測** |
| 時刻 | `sensor.info.timestampSource` REALTIME |
| 読み出し | `sensor.rollingShutterSkew` 28,362,409 ns |
| 増幅 | `postRawSensitivityBoostRange` 100〜3199 |
| 原寸YUV | `availableMinFrameDurations` の YUV_420_888 4032×3024 は 33,333,333 ns（連続での実測はない） |
| ジャイロ | icm4x6xx、`maxRate` 500 Hz（アプリは現在 `SENSOR_DELAY_GAME`） |

PC上の4032×3024の実写（重複を除き19枚、すべて2026年9月の glassdoc の写真。標準カメラの写真は 3024×4032 で保存されるのでこの集計に入っていない）を、送信時と同じ回転270で集計：

- EXIF：19枚すべて露光 8.3〜10.0 ms、感度 50〜60。
- 紙の中央 1200×800 画素の平均輝度：20.3〜62.3／255（中央値 52）。
- `app/source_bundle.py` の紙枠が確定した14枚：枠は 2321×1741〜2717×1868（長辺の中央値 2475、画角の幅 3024 の 77〜90%）、
  枠の上端は縦 4032 中の 1114〜1504、下端は 3082〜3510。見開きがA3（420 mm）なら 5.5〜6.5 画素/mm、
  横の画角77度から逆算した距離は約 33 cm。紙の寸法と距離は当時記録していないので、どちらも仮定を含む。
- 中央値の1枚（`reported-cancel-photo.jpg`）の原寸 600×400 画素を目視：縦書きの本文は1文字約22画素、判読はできるが
  暗く、輪郭が甘く、雑音がある。暗さの原因は部屋ではなくアプリの露出だった（§M-9）。甘さの原因は切り分けていない（候補：近距離のピントのずれ、暗い画像への雑音除去、動き）。
  過焦点 0.80 m に合焦しているなら、33 cm でのずれは f/2.25・1.90 mm から約 2.9 画素、45 cm で約 1.6 画素（計算値）。
- ラプラシアンの標準偏差は19枚とも 20.6〜22.3 で雑音に支配され、鮮明さの指標にならなかった。

グラスの記録では 0.43.15（vc67）導入後に装着で使われた形跡はない（撮影の最後の記録は 22:52 の机上検査）。

### M-9. 標準カメラとの同場面比較（2026-11-13 01:28〜01:37、グラスは机上）

本人の指摘（要旨）：写りが暗いのは部屋が暗いからではない。標準カメラを使わずに古い写真から判断するな。
標準カメラは adb から `input keyevent KEYCODE_SPRITE_FUNCTION`（物理ボタン、`qpnp_pon.kl` の key 139）で1枚撮れる。
撮るのは `com.rokid.os.sprite.assistserver` の `take_picture`、保存先は `/sdcard/DCIM/Camera`、前面のアプリは止められなかった。
計測用アプリ `:glassprobe` に `fps=`／`scene=`／`ev=`（カメラの自動露出に任せたまま露光を縮める正規の制御）を足した。

同じ場面（机の高さから見た紙・水筒・棚。動かしていない）を10分以内に撮った結果。明るさは正立させた全体と中央半分の平均（255中）、
雑音は明るさ 60〜200 の 64 画素角の標準偏差の下位1割：

| 撮り方 | 露光 | 感度×増幅 | 全体／中央 | 雑音 |
|---|---|---|---|---|
| 標準カメラ | 60.0 ms | 3064（EXIF） | 63.6／79.2 | 2.43 |
| 自アプリの構成（320×240 プレビュー＋原寸YUV）、自動露出 | 60 ms | 800×3.83 | 63.1／78.7 | 2.12 |
| 同、プレビューの値を手動で指定（vc66 の規則） | 60 ms | 800×3.87 | 64／80 | — |
| 同、自動露出＋`fps=30` | 30 ms | 800×7.67 | 63.1／79.1 | 3.12 |
| 同、自動露出＋`fps=60` | 10 ms | 800×12.46 | 42.5／52.6 | 8.16 |
| 同、自動露出＋`scene=13`（スポーツ） | 60 ms | 800×3.85 | 64.1／79.8 | 8.40 |
| 同、自動露出＋`scene=2`（アクション） | 60 ms | 800×3.86 | 64.4／80.0 | 8.33 |

- カメラの自動露出は自アプリの構成でも標準カメラと同じ値を選び、写真の明るさも同じだった。
- `fps=30` は露光を半分にし、自動露出が増幅で明るさを保った。`fps=60` は 10 ms まで縮むが増幅が足りず暗くなり、色の雑音が強い。
  スポーツ・アクションは露光を縮めず、雑音除去が弱まった（JPEG が 2.1 MB→6.1 MB）。
- 原寸で並べると、同じ 60 ms でも自アプリの1枚には標準カメラにない点状の雑音がある。
- この時刻の場面は標準カメラにとっても暗い（60 ms・感度 3064）。同じ机を装着して見下ろした 9/22 23:04〜23:07 の標準カメラは
  露光 25.0 ms・感度 218〜259 で、全体 97〜108、中央 164〜172 と明るい。

9月の暗い写真の原因：同じ 9/22 の夜に自アプリが撮った写真は露光 10 ms・感度 50 で紙が 62／255（§M-8 の19枚は全て 8.3〜10 ms・感度 50〜60）。
標準カメラの 25 ms・感度 218〜259 に対して光の量が約12分の1で、**暗いのは部屋ではなくアプリが露光を1周期に切り詰め感度も上げなかったため**。
9/22 の2枚は同じ時刻・同じ構図ではないので、倍率は目安。

標準カメラの撮り方（01:36:46 の1枚の `logcat`）：640×480 のプレビューと 4032×3024 の撮影用の読み取りを開き、ジャイロ・
`MotionDetectEngine`・`HDRDetectionEngine`・3DoF を初期化する。自動露出が落ち着くまでプレビューを捨て、動きと場面を判定する（この場面は `LLHDR`）。
続けて**5枚を露出補正 0／−8／0／−15／0（1/6 段刻み＝0、−1.33、0、−2.5、0 EV）、シーンモード15で連写**し、`ArcAlgProcessor` が合成する。
ボタンから5枚目まで 1.41 秒、カメラを閉じるまで約6秒。自アプリは1枚だけを撮っている。

未確認：装着して紙を見た場面での同じ比較、明るい部屋での各方式、標準カメラの明るい場面での連写の構成、合成の有無による判読の差。
11/12 22:23 の装着試行の場面が暗かったかどうかは、標準カメラの対照がなく不明。

### M-10. 雑音の原因と修正、連写の合成、標準カメラの手順（2026-11-13 01:57〜02:22、グラスは机上のまま）

本人の指摘（要旨）：実機で試させる前にできることを放置するな。足りない要素の調べ方を自分で考えろ。
同じ場面（M-9 と同じ、標準カメラは 60 ms・感度 3064〜3080）で、装着なしに次を測った。
指標は「明るさ÷雑音」：標準カメラの写真で最も平坦な 64 画素角 40 か所を選び、他の写真も同じ場所で読む。標準カメラは 39.7（別の回は 43.0、44.9）。

**当時のアプリ（0.43.15）の写真は読めなかった。** 通し検査が「明るさは十分」と合格にした写真は、同じ場所で 2.1（標準カメラ 43.0）、
原寸では色の雑音だけだった。検査は明るさしか見ていなかった。

**原因：自動露出を切った手動指定は、プレビューの自動露出と値が違うと雑音除去が足りなくなる。**

| 露光・感度・増幅が同じ組 | 自動露出の静止画 | 手動指定の静止画 |
|---|---|---|
| 60 ms・800×3.85（プレビューの値そのまま） | 43.6 | 同じ写り（JPEG 2,135,428 対 2,133,737 バイト、平均輝度同じ） |
| 30 ms・800×7.6 | 25.8 | 8.7 |
| 30 ms・800×7.7、輪郭強調なし | 33.8 | 20.7 |
| 10 ms・800×12.6〜13.2 | 9.0 | 3.1 |
| 10 ms・800×23（0.43.15 の規則と同じ） | — | 1.9 |

雑音除去と輪郭強調（30 ms・自動露出）：輪郭強調 HIGH_QUALITY 25.8、FAST 24.8、OFF 33.8（雑音除去 FAST でも 35.4）、雑音除去 OFF は 4.2。
輪郭強調が雑音を黒い点に変えていた。

**連写の平均（位置合わせなし、机上で静止）：**

| 1枚の露光 | 1枚 | 2枚 | 4枚 | 6枚 |
|---|---|---|---|---|
| 60 ms | 43.6 | 55.6 | 65.2 | 73.1 |
| 30 ms | 25.8 | 33.7 | 44.0 | 50.1 |
| 10 ms（増幅が尽きて暗い） | 9.0 | 13.3 | 17.3 | 21.7 |

30 ms×4枚で標準カメラ（39.7）を超える。原寸YUVは要求から 344〜352 ms で届いた（30 ms・10 ms の時。60 ms は 551 ms）。
頭が動く場合の位置合わせは未実装・未計測。

**修正（glassdoc 0.43.16、vc68）：** 静止画はプレビューの自動露出が測った露光・感度・増幅をそのまま使う。露光を縮めるのは
プレビューの自動露出にフレームレート範囲を頼む方法だけにした（1周期で総増幅 1600 以下なら 60、30 ms で 6400 以下なら 30、
それ以外は既定。抜ける条件は入る条件より緩い）。総増幅が 1600 を超える静止画は輪郭強調を切る。
同じ場面の通し検査：アプリは自分で 30 に切り替え（`exposure_pace fps=30`）、静止画 30 ms・ISO 800、**39.6 と 38.1（標準カメラ 44.9）**、36行すべて通過。

**通し検査の変更：** 開始時に標準カメラで1枚撮り（`KEYCODE_SPRITE_FUNCTION`）、アプリの各写真を同じ場所で読み、標準カメラ比 0.3 未満を不合格、
0.6 未満を注意にした。0.43.15 はこの行で不合格（2.1 対 43.0）になることを確認した。境界は机上の暗い1場面からの仮の値。

**標準カメラの手順（実機のシステムアプリのコードと設定を読み取り。読み取った物はリポジトリに入れていない）：**

- プレビュー 640×480 と撮影用 4032×3024 はどちらも YUV_420_888。自アプリの原寸YUVと同じ形式。
- 露光・感度の手動指定はしない。自動露出のまま、シーンモードと露出補正だけを変えた連写を出す。
- 場面は HDR 検出がプレビューと自動露出の値（感度、増幅、明るさ指数、露光）から決める：MFNR／HDR／LLHDR など。枚数と露出補正の列は場面ごと（LLHDR は5枚、0／−8／0／−15／0）。
- 動き：ジャイロと感度を入れた動き検出が「止まった」と出すまで連写を出さない（プレビューを捨てて待つ）。別に 3DoF の静止判定もある。
- 連写は ArcSoft のライブラリ（低照度HDR・HDR・MFNR・歪み補正）で合成し、ソフトウェアで JPEG にする。
- 外部のアプリがこの撮影を呼んで結果を受け取る公開の入口は見つからなかった（システム署名のアプリ内で完結）。保存された写真を MediaStore から読むことはできる。
- 設定：`persist.vendor.rkd.camera.power_freq=50`。

未確認：明るい部屋での各方式（フレームレート範囲 60 の写り、輪郭強調の要否）、紙を読む距離の文字、装着した頭での 30 ms の静止条件、
連写の位置合わせ。範囲を切り替える境界は暗い1場面と 9/22 の標準カメラの値からの仮の値。

### M-11. 紙を読む距離での文字の大きさと鮮明さ（既存写真のPC解析、2026-11-13）

対象：9/22 23:04〜23:07 に装着して標準カメラで撮った基準8枚（明るい部屋、同じ冊子、近め〜離した姿勢）と、9月のアプリの写真19枚。
独立のサブエージェントがPC上で解析した。新しい撮影はしていない。距離は当時測っておらず、紙の大きさからの推定。

- 文字の大きさ：縦書きの行の周期を自己相関で求め、1文字の高さを出した。
- 鮮明さ：孤立した縦線の断面を平均してぼけの幅（EW、画素）を求め、線幅を除いた。既知のぼけ（ガウス 0／1／2／3 画素で 1.74／2.07／3.25／5.61）と
  雑音（標準偏差 2／4／8 を足しても 1.74／1.74／1.62〜1.71）で検証済み。縦線を横切る方向のぼけだけを見ている。

| 標準カメラ | 露光／感度 | 1文字の高さ | EW | EW÷文字 | 紙の雑音 |
|---|---|---|---|---|---|
| S5（最も遠い） | 25 ms／274 | 15.1 画素 | 4.6 | 0.31 | 0.77 |
| S4 | 25／235 | 15.8 | 4.3 | 0.27 | 0.62 |
| S2 | 25／223 | 17.0 | 4.6 | 0.27 | 0.63 |
| S3 | 25／218 | 18.2 | 5.1 | 0.28 | 0.64 |
| S8 | 25／209 | 20.3 | 4.5 | 0.22 | 0.61 |
| S7 | 25／249 | 21.6 | 5.6 | 0.26 | 0.69 |
| S1 | 16.6／191 | 25.5 | 6.3 | 0.25 | 0.50 |
| S6（最も近い、紙が画角からはみ出す） | 25／318 | 38.5 | 9.6 | 0.25 | 0.45 |

- **1文字 15〜22 画素の範囲では、ぼけの幅は 4.3〜5.6 画素でほぼ一定**（距離によらない下限がある）。3秒差の S7 と S8 で 5.6 と 4.5 と揺れる。
- **それより近づくと、ぼけは文字と同じ割合で大きくなり、得をしない**（S1・S6）。最もよく解像したのは S8（1文字約20画素、EW は文字の 0.22）。
- 同じ33文字の Tesseract（`jpn_vert`）：S8 は誤り6、S5 は24、S6 は31。**1文字15画素では読めず、20画素前後が要る。**
- 合焦面：近距離（0.34 m）合焦の仮定が最も合わない。0.5 m 以遠の合焦なら合うが、薄レンズの計算より 1.4〜1.7 倍のぼけを置く必要がある。
  32〜44 cm（冊子をB5と仮定）の範囲は下限に埋もれて判定できない。
- 9月のアプリの写真との比較（文字の大きさが近いもの）：紙の明るさ 68 対 216、EW 6.2 対 5.1 画素、紙の雑音 4.2 対 0.64。
  **アプリは露光が短い（8.3〜10 ms 対 25 ms）のに、鮮明ではなかった。**

限界：標準カメラは8枚で各姿勢1枚。同じ姿勢のばらつきが遠い側の傾向と同じ大きさ。距離は推定（A4 なら 15% 増える）。
アプリの写真は照明が違い、19枚中17枚は別の頁。アプリの EW は雑音の影響で約±20%。0.43.16 の写真はこの解析に入っていない。

### M-12. 消灯が2回目以降効かない：実際の入力経路での再現と修正（2026-11-13 夜、グラスはUSB接続）

本人の報告：消灯が2回目以降されない。注入キー（`input keyevent`、起床は `KEYCODE_WAKEUP` を別送）の検査では一度も再現しなかった。
タッチパッドの入力デバイス `/dev/input/event1`（`ROKID,PSOC-TP-R`）へ `sendevent` で書くと実際のタッチと同じ経路を通る
（shell は `input` グループ。タップ＝`KEY_DASHBOARD` 204 → `KEY_ENTER` 28）。

特性（glassdoc 0.43.16、選択画面）：

- システムの消灯で Activity は `performPause`→`STOP_ACTIVITY_ITEM`。
- 眠った画面へのタップは、電源が `Awake` になり Activity が `performRestartActivity`→`handleStartActivity`→`RESUME_ACTIVITY` するだけで、
  **アプリには操作が届かない**（アプリの記録は空）。
- その後のタップにアプリは `request=wake` を出し、消灯しない。無操作5秒の消灯の後も同じ。これが報告の症状。

修正（0.43.17）：再開の通知で画面が点いたと同期する。消灯時は必ず表示を消し、内容は保持する。画面を戻す操作は全画面で他の働きをしない。
解析待ちでもタップで消灯し、その間の操作を撮影の制御へ渡さない。失敗する試験を先に書いて（3件が失敗）から直した。

修正後（`py -3.12 scripts/glasses_display_cycles.py 1904092623381086 chooser --raw`、点灯画素は画面取得で数えた）：

| 手順 | 1回目 | 2回目 | 3回目 |
|---|---|---|---|
| タップ：消灯 | 点灯画素 0・Asleep・`request=sleep` | 同じ | 同じ |
| タッチ：復帰（アプリに操作は届かない） | 6299・Awake・`request=wake` | 同じ | 同じ |

無操作の消灯→タッチ→タップ：修正前は `request=wake`、修正後は `request=sleep`・Asleep。撮影中の休止・再開は修正前後とも4回続けて正常。

同じ夜の副次的な発見：

- `adb shell "dumpsys media.camera | grep -m1 ..."` を撮影中に実行すると、パイプが早く閉じてカメラのシステムサービスが落ちる
  （`init: Service 'vendor.camera-provider-2-7' received signal 13`）。アプリは「カメラ状態が不明です」で止まり操作が効かなくなる。
  検査はダンプをPC側で全部読む形に直した。アプリ側に再起動以外の復旧がないことは `docs/defect-register.md` 2-10。
- 動かない場面を8秒で3枚撮った（露光 60 ms の範囲）。静止画の撮影でプレビューが `level_shift=23`、続いて `-22` 動き、
  どちらも頁の変化と数えられる。`docs/defect-register.md` 2-1、未修正。

未確認：実際の指でのタッチ（入力デバイスへの書き込みは同じ経路だが、指の時間間隔と接触は再現していない）、解析待ち・合同英語の画面、
掛け直しをまたぐ場合、スマホ側の監視が止まっている場合。

### M-13. システム全体の観測：負荷・発熱・スマホ側（2026-11-13 20:36〜21:21、グラスは机上・USB給電、glassdoc 0.43.17）

本人の指摘（要旨）：全体の流れを確認せずカメラだけを見た。撮影が他の要素から悪影響を受けているかもしれない。
`scripts/system_observation.py` で、実際の入力経路の操作を流しながら両端末の負荷・メモリ・温度・サーバー応答を取り、全ログを発生元ごとに数えた。

**撮影10分（開始のダブルタップ1回、記録で開始を確認。動かない場面、撮影1枚、露光 30 ms の範囲）：**

| 経過 | 最高温度（CPU） | 電源IC | カメラ | カメラのサービスのCPU | アプリのCPU | プレビュー | 1コマの処理 |
|---|---|---|---|---|---|---|---|
| 2 秒 | 38.9℃ | 34.6 | 36.1 | 103% | 52% | 毎秒22枚 | 34 ms |
| 29 秒 | 46.6 | 42.6 | 46.2 | 117% | 46% | 9 | 71 |
| 119 秒 | 58.2 | 54.1 | 57.0 | 132% | 49% | 8 | 63 |
| 298 秒 | 68.2 | 63.7 | 67.8 | 137% | 49% | 9 | 65 |
| 476 秒 | 73.5 | 68.6 | 72.7 | 121% | 46% | 11 | 72 |
| 566 秒 | 74.3 | 70.0 | 73.5 | 113% | 50% | 10 | 68 |
| 停止1分後 | 56.6 | 54.9 | 54.6 | — | — | — | — |
| 停止2分後 | 49.8 | 47.7 | 47.8 | — | — | — | — |

CPU は4コア＝400%。冷却の作動（`cooling_device` の状態）は終始なし。終了時も温度は上がり続けていた。露光は 30 ms のまま変わらず、
プレビューの処理枚数だけが開始13秒以降に毎秒17〜22枚から9〜16枚へ落ちた。標準カメラは1枚ごとに約6秒だけカメラを開く（§M-9）。
机の上・室温での値で、装着時の放熱と表面温度、電池の減りは未計測。温度によるセンサーの雑音の増加も未計測。

**同じ計測アプリでのカメラのサービスのCPU（プレビュー中、1回ずつ）：** 320×240＋原寸YUV 90%、320×240＋原寸JPEG 70%、640×480＋原寸YUV 97%。

**撮影40秒の間の両端末（1回）：**

- グラス：最高温度 35.3→51.0℃（50秒）。空きメモリ 848→469〜555 MB。カメラのカーネルドライバが
  `CAM-SYNC workq schedule delay detected … diff 12: threshold 5` を毎秒10回以上（抑制表示つき）。
- グラスのシステムの記録：`setStreamVolume() for STREAM_VOICE_CALL … without MODIFY_PHONE_STATE callingPackage=dev.rokid.docscanglass.doc` 11回、
  `Permission failure: android.permission.HIGH_SAMPLING_RATE_SENSORS from uid=10065` 7回、`ANDR-PERF-RESOURCEQS … Failed to apply optimization` 16回、
  熱の管理サービスへのカメラからの通知 12回（10分の走行では26回）。
- スマホ：負荷平均 16.4〜16.8（稼働27日）。`/health` の応答は PC から 15〜1109 ms（頁のアップロード中に 422・781・1109 ms、サーバーのプロセスが CPU 100%）。
- スマホ側の監視（`rokid-watch`）：グラスへの命令1つに 0.30〜2.8 秒（たたみの読み取り 1.66 秒・2.8 秒、プロセス 0.32 秒、音量 0.30〜0.50 秒）。
  直近2591行に状態取得の失敗13、時間切れ2、`glasses_unavailable`・`glasses_discovery_unavailable` 各1。
- スマホのサーバーのデータは 29 GB、画像149件。4つのサービスは稼働中。

**計測手順の誤り（記録として残す）：**

1. 最初の10分計測は撮影が始まっていなかった。開始のダブルタップの前に計測で数秒使い、選択画面が無操作5秒で消灯していたため、
   ダブルタップは「画面を戻すだけ」になった（負荷・温度は平常のまま10分）。
2. 2回目は、開始の確認を `logcat -t 200`（全タグの末尾200行）で行って「始まっていない」と誤判定し、**撮影中にダブルタップを3回重ねて送った**。
   撮影中のダブルタップは終了の要求で、終了は頁を解析へ送る。この回は1枚目の直後にカメラが閉じ（20:54:24）、
   `Observed scene was not captured` が2回出て終了が止まり、撮影は終了も継続もしないまま10分間止まっていた。
   **解析への送信は起きていない**：スマホのサーバーの当日の記録は `glasses_state_store` 57件だけで確定・解析の記録なし、
   送信記録のファイル（スマホ上のサーバーのデータの browser-state にある submission.json）の更新は 11/10 のまま。
3. 3回目で正しく取れた（上の表）。開始のダブルタップは1回だけ送り、時刻指定の記録で開始を確認し、再送しない。

**構成ごとの発熱（21:22〜、計測アプリ、150秒ずつ。1つ目で中断）：** 320×240 のプレビュー＋原寸YUVの読み取り口、フレームレートは既定：
38.9→51.4℃（+11.3℃。30秒 45.8、60秒 47.4、90秒 50.2、120秒 51.4）、カメラのサービスの CPU 77〜90%、プレビュー 2497 枚／150 秒（毎秒約17枚）。
同じ150秒で撮影アプリ（フレームレート範囲30、自分の処理に CPU 約50%）は 38.9→約60℃。範囲30・範囲15・JPEG の読み取り口の3構成は、
グラスが USB から外されたため未計測。

**実使用の記録（21:26〜21:32、本人が装着。グラスへは何も送らず、スマホ側の adb から記録を読み取っただけ）：**
21:26:02 `generation=239 phase=chooser request=wake`、21:26:07 `request=sleep`（5秒の無操作）、21:28:39 `sequence=3 request=wake`（タッチによる復帰。
0.43.17 の再開時の同期が働いた）、21:28:41 `generation=240 … request=wake`（装着の再検知で選択画面を作り直し）、21:28:46 `request=sleep`。
この間、撮影の開始・プレビュー・静止画の記録は0件。

### M-14. 全経路の通し（2026-11-13 夜、グラスはUSB、検査用の別名のアプリ 0.43.17、GPT への送信なし）

本人の指摘（要旨）：熱だけを見て、機能全体や実際の使用の試験・想定をしていない。USB 以外の経路もある。
`scripts/e2e_route_check.py` で、掛ける以降の一連を使う順に通した。構成：

- グラス：`-PglassdocRouteCheck` でビルドした同じアプリ（パッケージ名の末尾が routecheck）を本番アプリの隣に導入。本番アプリの保存済みのサーバー・鍵・回答には触れていない
  （導入済みの本番アプリはデバッグ不可で退避できないため、上書きを避けた）。操作はタッチパッドの入力デバイスへの書き込み。
- サーバー：PC 上、`ROKID_SOLVER=recorded`（録音済みの回答を40秒後に返す代役。送信は無効、ブラウザなし）、専用のデータ置き場。グラスからは `adb reverse` で到達。
- 監視：PC 上の `scripts/watch_glasses.py`（`--package` で検査用アプリを指定）。会場と同じく、サーバーが見た送信元の住所からグラスを探す。
- **経路に入っていないもの**：スマホ、そのホットスポット、スマホ上のサーバーと監視、ブラウザ、本物の GPT。

結果（2回目の走行、27行中26行通過）：

| 経過 | 確かめたこと |
|---|---|
| 5.5 秒 | 選択画面が描かれる |
| 6.2 | ダブルタップ1回で読取が始まる |
| 11.6 | 1枚目が無操作で撮れる（`captured 4032x3024 … in 773ms`） |
| 23.5／29.2 | 前スワイプで2枚目・3枚目、どちらも保存 |
| 31.6 | 3頁がサーバーの1つの資料に届く |
| 38.4 | 終了のダブルタップから約6秒で解析の受付（`FINALIZING: Local capture finished; analysis queued`→`REVIEW: Local session analysis finished`）。頁の番号は 0・1・2 |
| 46.9 | 待ちの間に消灯（システムも Asleep） |
| 73.2 | 代役の回答が束になる |
| 75.0 | **1.8 秒後にグラスが自分で起きて答えを表示** |
| 78〜93 | 前スワイプで送る、後ろで戻る、タップで隠す、次の操作で戻る、7秒たっても表示は保持 |
| 100.3 | ダブルタップで記入終了、消灯 |
| 106.2 | **失敗**：続くダブルタップ2回（0.6秒間隔）でアプリを抜けられない |

サーバーのデータ置き場に送信記録は作られていない。1回目の走行は監視がグラスを見つけられず（`Watcher: waiting_for_glasses`）、待ちの消灯と起床の2行が失敗した。
原因は検査の組み方（`adb reverse` 越しでは送信元が PC に見える）で、グラスの adb の TCP ポートも PC へ転送して解消した。

途中の中断（`--interrupt wait`）：解析の受付の直後にアプリを強制終了（つるをたたんだ時にシステムがすること）し、選択画面を開き直した。
サーバーでは回答の束が出来た（200）が、45秒たってもグラスは起きず、選択画面の項目は「通常の読取／合同英語／リスニング／前回の答案／アプリを終了」で、
中断した回は出ない。状態は `session_id 3, generation 8, phase chooser`。`docs/defect-register.md` 3-1 の再現。

検査用アプリはグラスに入れたまま（ランチャーに見える）。本番アプリは 0.43.17 のまま。

### M-15. 本物の経路の通し：本番アプリ→スマホ→GPT→回答→グラス（2026-11-13 22:14〜22:23、1回）

本人の指摘（要旨）：GPT に送らない理由が分からない。実際の動きなのに考えが浅い。
それまで「GPT への送信 0」を検査の前提にしていたのは、モデルの比較を何度も回すことへの以前の指示（アカウントで測るな、無駄遣いするな）を、
一律の禁止に広げた私の誤り。M-14 の通しは解答役が代役で、製品の目的（GPT が写真から答える）を確かめていなかった。

構成はすべて本物：グラスの本番アプリ 0.43.17（操作はタッチパッドの入力デバイスへの書き込み、グラスは机上・USB）→スマホのホットスポット→
スマホ上のサーバー（0.72.0）→ブラウザ経由の ChatGPT（スマホの設定のまま）→回答→スマホ側の監視がグラスを起こす→回答表示。
写したのは机上のそのままの場面（手前にケース、紙は斜めで大部分が隠れる。直前の標準カメラは 50 ms・感度 3400）で、**問題の頁ではない**。
この1回で確かめたのは連鎖が最後まで動くことで、回答の正しさではない。スマホ側の記録は、無線 adb に繋がらず読めていない。

| 時刻 | 起きたこと |
|---|---|
| 22:14:35 | ダブルタップ1回で読取開始 |
| 22:14:39 | 1枚目（`captured 4032x3024 4605257B in 723ms gen=1`） |
| 22:14:43 | 保存、送信待ちへ |
| 22:14:53 | 終了のダブルタップ→`FINALIZING: Local capture finished; analysis queued`→`REVIEW: Local session analysis finished`（1秒以内） |
| 22:14:59 | 解析待ちで消灯 |
| 22:21:10 | **グラスが起こされ、回答を表示**（終了から 6 分 17 秒） |
| 22:21:16 | 5秒後に消灯（状態は `phase=waiting`） |

表示された GPT の返答（全2画面）：「資料不足　page_001.png は紙面の大部分が物体で隠れ、見えている文字も強いぼけと暗さにより判読できません。
設問本文・条件・設問番号・解答番号および設問数を確認できません。遮蔽物を除き、紙面全体を明るく、文字にピントを合わせて撮影した画像が必要です。」

分かったこと：

- 本物の連鎖は最後まで動く。通しで動いたのはこれが初めて。
- 1頁で 6 分 17 秒。
- 回答が「資料不足」だけの時、読む画面として扱われず 5 秒で消灯する。その後の最初の前スワイプは画面を戻すだけで、頁が進まなかった。
- 使った利用枠は Work の1件。

未確認：問題の頁を写した時に GPT が正しく答えるか、複数頁の所要時間、利用上限に当たった時の動き、スマホ側で実際に選ばれたモデル・速度の記録。

**この実行は判断の誤りだった（本人の指摘、同日）。** 実際の利用は Fast だが試験での Fast は無駄遣いで、Work も同じく重い。この種の試験は何度もすべきでなく、
今やるべきでもなかった。問題の頁が写っておらず、撮影の欠陥が未修正と分かっている時点で実行したため、得られたのは「連鎖が動く」ことだけで、
それは問題の頁を写せる状態になってからの1回で同時に確かめられた。直前の「一切送らない」という前提も、今回の「すぐ送る」も、目的・費用・時期を考えずに
直前の指摘へ振れただけだった。この回がどの速度で実行されたかは確認できていない（スマホの設定は最後に記録した時点で Standard だが、スマホ側の記録を読めていない）。
以後、本物のモデルを使う実行は、`CLAUDE.md` の条件を満たした上で本人の了承を得てから1回だけ行う。

### M-16. 入口と終了の修正の確認（2026-11-13 深夜、glassdoc 0.43.18／vc70、グラスはUSB）

失敗する試験を先に書いた（選択画面の表示時間、記入終了後の終了。どちらも修正前のコードで失敗を確認）。

- 選択画面：本番アプリを起動して画面取得。10秒後 点灯画素 6299・Awake、25秒後 6299・Awake、33秒後 0・Asleep（修正前は5秒で消灯）。
- 全経路の通し（`scripts/e2e_route_check.py --photos 2`、検査用の別名のアプリ 0.43.18、PC 上の代役の解答役、GPT への送信なし）：**26行すべて通過**。
  記入終了のダブルタップの後、続くダブルタップ2回で前面がランチャー（`com.rokid.os.sprite.launcher`）に戻る。
  1回目の修正（再開の通知で終了の待ち状態に入る）だけでは通らなかった：実機では再開の後にフォーカスの復帰が来て、既存の処理が待ち状態を消していた。
  フォーカスの復帰をまたいで保持するようにして通った。
- Android 全体 `test testDebugUnitTest assembleDebug` は BUILD SUCCESSFUL。

未確認：実際の指での操作、装着の検知からの起動、掛け直し。

### M-17. 装着時の環境が未計測だった点、暗い場面の露光、頭の動きの記録（2026-11-14 午後、glassdoc 0.43.18→0.43.20／vc72、グラスは机上・USB）

本人の指摘（要旨）：ハードウェアを使っているのに環境を考えていない。装着しての用紙撮影そのものが上手く行っていない。

**記録の確認。** 装着での撮影の記録は 11/12 22:23 の1回だけ（0.43.14、37秒、0枚。§M-7）。0.43.15・0.43.16 の露出の規則は装着で使われていない。
装着した頭の角速度と、装着時に紙へ当たっている光は、一度も記録していなかった。静止の判定は「要求の前の 300 ms、全ての読みが 0.12 rad/s×10 ms÷露光 以下」で、
通過するとジャイロを止め、露光はその 0.3〜0.7 秒後に来る。9月（10 ms、上限 0.12）は装着で撮れ、11/12（50〜60 ms、上限 0.02）は 20 秒間一度も通過しなかった。

**机上のグラスが見ている場面**（標準カメラ、14:57）：棚の陰の机上で、手前に用紙が斜めに入る。標準カメラ 60 ms・感度 3320、平均輝度 74/255。
同時刻のアプリのプレビューも 60 ms・ISO 800・総増幅 約 3300 で一致。9/22 に装着して紙を撮った標準カメラ（25 ms・感度 209〜318）より、露光×感度で約 30 倍暗い。
机上の数値は、装着して紙を見た時の条件ではない。

**動かない場面の連続撮影（欠陥 2-1）は再現しない。** 0.43.18：60 秒で1枚（11/13 23:17、30 ms）。0.43.19：60 秒で1枚（60 ms）。0.43.20：90 秒で1枚（30 ms）。通し検査の 15 秒×4回も追加 0 枚。

**暗い場面の露光（0.43.20）。** 0.43.19 までは、30 ms に総増幅 6400 超を要する場面は 60 ms へ戻っていた（この机上は 6640 を要し、60 ms・上限 0.020 rad/s になった）。
0.43.20 は、30 枚の範囲がある限り暗くてもそれを保つ。同じ場面で `exposure_pace fps=30`、静止画 30 ms・ISO 800・総増幅 6568〜6664、上限 0.040 rad/s。
標準カメラとの同場面比較（明るさ÷雑音、同じ平坦部）：37.4・37.1 対 44.1、36.1・35.5 対 42.6。

**頭の動きの記録（0.43.20、判断は変えない）。** カメラが開いている間、ジャイロを 200 Hz で記録する（アプリの外部領域の head-motion.bin。1秒ごとに書き出す）。
写真ごとに露光中の動きを出す：`still_motion gen=1 samples=12 covered=true window_ms=58 mean_rad_s=0.003 peak_rad_s=0.004 blur_px=0.2`（58 ms＝露光 30＋読み出しのずれ 28）。
毎秒の状態行に直近1秒の動き・範囲・総増幅を足した（`head_1s=201 mean_rad_s=… peak_rad_s=… pace=30 gain=6664`）。
本番アプリの机上の記録：75,400 件、374 秒、周期 5.0 ms。机上（静止）の角速度は中央値 0.005・p90 0.007・p99 0.009 rad/s（センサーの雑音の床）。
`scripts/head_motion_report.py` は記録を再生し、露光 10／16.7／30／60 ms ごとに、静止している露光の割合、今の判定・瞬間判定での待ち時間と写真の静止率、連写1〜4枚に静止した1枚がある割合を出す。
0.43.19 は保存先がアプリ内部で、デバッグ不可のビルドでは取り出せず、強制停止で書きかけが失われた（0.43.20 で修正）。

**発熱。** 0.43.20・30 枚の範囲・机上・USB給電：未コンパイル時 95 秒で SoC 38.9→57.8 ℃。コンパイル後の通し検査（約2分）で 49.8→58.6 ℃。
コンパイル済みで撮影を 180 秒続けると（静止した場面、撮影は最初の1枚だけ）：SoC（cpu-0-0）40.1→66.6 ℃、カメラ 39.7→65.0 ℃、基板（sys-therm-0／1）38.5→62.2／39.4→62.0 ℃、水晶（xo-therm）39.4→60.3 ℃、電源IC 40.5→63.0 ℃。プレビューの処理は毎秒 21 枚から、60 秒以降は 9〜10 枚（1枚 57〜63 ms）へ落ちた。**この発熱のまま装着しての記録を頼むのは適切でない。** 表面の温度は測れていない。

**通し検査。** 代役の全経路（`scripts/e2e_route_check.py --photos 2`）は 26 行すべて通過。本番アプリ＋スマホのサーバー（`scripts/glasses_device_check.py`）は 40 行すべて通過を2回。
そこまでに3回失敗し、原因はいずれも製品ではなかった：(1) 導入後のコンパイル漏れ、(2) 検査が注入キーで「起床→スワイプ」を送っており、0.43.17 以降はそのスワイプが2回目の操作として
選択を合同英語へ動かした（合同英語ではタップは撮影）、(3) 選択画面は前回の種類を覚えるので、次の回も合同英語で始まった。検査を入力デバイスへの書き込みに変え、
画面の印の位置を読んで通常の読取へ戻してから開始するようにした。実際の入力経路では、撮影中のタップで休止・再開し、追加の撮影はない。

**入力の事実（システムの記録）。** 消灯中に前スワイプ（204・106・108）を入力デバイスへ書くと、204 と 106 は起床させず（`interactive=false`）、最後の 108 の押下で起床する
（`WAKE_REASON_WAKE_KEY`）。どのキーもアプリへは渡らない。書き込みは1キーごとに別プロセスで、キーの間隔は 150〜350 ms あった。実際のタッチの間隔は未計測。

**0.43.21（vc73）。** 記録の書き出し先を、カメラを開くたびに独立させた（0.43.20 は、閉じてすぐ開くと古い側の後始末が新しい側の書き出し先を閉じ得る作りだった。机上の実行では起きていない）。導入・コンパイル後に再実行：本番アプリ＋スマホの通し検査 40 行すべて通過（標準カメラ比 34.1・33.9 対 40.9）、代役の全経路 26 行すべて通過、休止→再開をまたいだ記録が両側とも残ること、装着の記録モード（`scripts/e2e_route_check.py --paper 30`）の机上での予行。

未確認：装着時のすべて（紙面の明るさ、頭の動き、30 ms で静止の判定が通るか、撮れた写真の文字）。明るい場面で 60 枚の範囲に入った時の動作と発熱。30 ms でも足りない暗さでの写り。

### M-18. 発熱の原因と対策：原寸の出力は撮る時だけ、待機は毎秒 15 枚（2026-11-14 夕方、glassdoc 0.43.21→0.43.23／vc75、グラスは机上・USB）

装着しての記録を頼む前に、発熱（§M-17：3分で基板 62℃）を下げる必要があった。

**構成別の発熱**（計測アプリ `:glassprobe`、各 150 秒、41℃ 以下まで冷ましてから開始、最も熱い箇所の温度）：

| セッションの構成 | 開始→150 秒 | 上昇 | 毎秒の枚数 |
|---|---|---|---|
| 320×240 のプレビューだけ、既定の範囲 | 38.9→44.9℃ | +6.0 | 16.5（頭打ち） |
| 320×240 のプレビューだけ、範囲 15 | 40.9→45.8℃ | +4.9 | 14.9（頭打ち） |
| ＋原寸 YUV を併設、範囲 15 | 40.9→52.2℃ | +11.3 | 14.9 |
| ＋原寸 YUV を併設、範囲 30（0.43.21 までのアプリ） | 41.3→62.2℃ | +20.9 | 29.6（上昇が続く） |

原寸の出力は、撮っていなくても併設しているだけで発熱を約2倍にし、範囲 30 がさらに約2倍にする。

**既存の「静止画だけ JPEG 専用のセッション」は使えない。** その経路へ切り替えた試しのビルドは、3分で SoC 36.9→51.4℃・基板 34.8→47.5℃ と発熱は半分だが、
同じ場面の写りが標準カメラ 39.7 に対し 10.5（原寸 YUV を併設した方式は 33.3）。作りたての JPEG 専用セッションの静止画は、露光と増幅をプレビューから写しても雑音が約3倍になる。

**組み直しても写りは保てる。** 計測アプリで「プレビューだけ → プレビュー＋原寸 YUV へ組み直し → 露出を写して撮る」を測定：組み直し 0.44〜0.47 秒、静止画は要求から 0.33〜0.37 秒。
プレビュー再開から 0.3／0.8／1.5 秒後に撮った写りは 33.4／32.7／32.2、最初から併設していた場合 32.6（標準カメラ 39.7）。

**対策（0.43.22・0.43.23）。** 通常の読取では、原寸の出力を撮影の準備から受け取りまでの間だけセッションへ入れる（頁の変化を検出するか手動の撮影が来た時に組み直し、
撮り終えるか準備が時間切れになったら戻す）。組み直し中は古いセッションのフレームと結果を使わない。待機中のプレビューは範囲 15、準備に入ると静止画用の範囲（30 または 60）。
比較用の起動（設定の比較、追加の原寸撮影、紙の形の評価）は従来どおり併設を保つ。

同じ机上の場面・180 秒・撮影1枚（コンパイル済みの検査用アプリ）：

| 版 | SoC（cpu-0-0） | 基板（sys-therm-0） | プレビューの処理 |
|---|---|---|---|
| 0.43.21（原寸を常時併設、範囲 30） | 40.1→66.6℃（+26.5） | 38.5→62.2℃（+23.7） | 毎秒 21→9〜10 枚（低下） |
| 0.43.22（撮る時だけ併設、範囲 30） | 40.5→53.0℃（+12.5） | 37.3→49.0℃（+11.7） | 18→11〜14 |
| 0.43.23（＋待機は範囲 15） | 40.5→47.4℃（+6.9） | 37.7→43.8℃（+6.1） | 10〜11（安定） |

0.43.23 の1枚の流れ（記録から）：`session_shape full_size=true` → 露出が落ち着くまで 1.08〜1.23 秒（組み直しを含む）→ 静止画 30 ms・ISO 800、要求から 0.67〜0.78 秒で取得 →
`session_shape full_size=false` → 0.86〜0.90 秒で待機のプレビューが落ち着く（60 ms）。頁の検出から写真まで約2秒。

**10 分間の連続撮影（0.43.23、机上・USB、20 秒ごとに前スワイプで1枚）。** 基板（sys-therm-0）は 38.8℃ から 5 分で約 48℃ に達して横ばい（6〜10 分は 47.6〜49.0℃、終了時 49.5℃）、SoC は 51〜52℃ で横ばい（11/13 の同じ長さの実行は 0.43.17 で SoC 74℃・上昇が続いていた）。撮影 31 枚（自動1＋スワイプ30）、保存 30 枚・サーバー到達 30 頁（31 枚目は計測の停止が確認表示の最中）。セッションの組み直し 62 回、落ち着かなかった回 0、頁の変化の誤検出 0（数えたのは開始時の3回だけ）、準備の時間切れ 0、エラー 0、カメラのサービスの再起動なし。静止画の取得は中央値 1.07 秒（最大 1.16）、組み直し後に落ち着くまで中央値 1.10 秒（最大 2.03）。プレビューの処理は毎秒 9.3→8.5 枚。撮影から確認表示までは 29 枚で 0.6〜0.8 秒、2 枚で 3.2 秒と 6.1 秒（その間カメラ側の記録は正常。原因未特定、欠陥 2-13）。

通し検査（0.43.23）：本番アプリ＋スマホのサーバー 40 行すべて通過（標準カメラ 38.2 に対し 30.6・30.3。夕方で場面が暗くなっている）。代役の全経路は写真4枚で 28 行すべて通過。
途中の失敗2回は検査スクリプト側（保存の確認を秒単位の時刻で探し、前の写真の保存を次の写真のものと誤認して確認中に次のスワイプを送った。枚数で数える方式に修正）。

未確認：装着時の発熱と表面温度、電池での動作、明るい場面（範囲 60 で撮る時）の発熱、頁をめくる実際の使い方での検出の遅れ、組み直しを拒否するカメラでの代替経路の実機動作。

未確認：明るい場所での紙面の写り、頁めくりによる自動検出、3秒確認の見え方、
ZSL／録画の評価起動（JPEGを同じセッションに置くため、このファームウェアでは通らない見込み）。

### M-19. Chat の経路での初めての冊子送信と、その経路の不具合（2026-11-14 19:41〜21:07、スマホ F-51F、サーバー `fba7158`→`f600659`）

本人の了承（1回）で、判読の上限を確かめるために送った。Runs on: スマホ＋ChatGPT。写真は PC からスマホのサーバーへ入れたので、
会場の構成の確認ではなく、判読と Chat 送信という部品の確認。グラスは使っていない。

**入力**：9/22 23:06:38 に装着して標準カメラで撮った見開き（§M-11 の S8、1文字 約 20 画素）から、PC で頁ごとに紙へ切り出した2枚
（右頁＝問1 の漢字5問 940×1700、左頁＝問2 1080×1700）。基準8枚は全て同じ見開きだった。

**送る前に PC で確かめたこと（`app/source_bundle.py`、送信なし）**：
- 全画角（3024×4032）のままでは、紙への切り出しも綴じ目の分割も成立せず（`_paper_crop`＝None、`_gutter`＝None）、1枚のまま送る。
  9/30 の実測では ChatGPT は長辺 2048 へ縮小するので、1文字は 約 10 画素になる。
- 紙へ切り出した見開き（2200×1700）でも綴じ目を検出できず、1枚のまま。

**結果**：
- 送信 20:32（1通・2ファイル、Chat、先頭のモデル GPT-6、Extra High）。返答まで 2分51秒。
- 返答：問1（解答番号 1〜5、頁1）と問2（解答番号 6、頁2）を挙げ、どちらも `needs_input`（傍線部を含む本文の頁が無い）。
  **設問の構成・解答番号・傍線部の記号は正しく読めた。選択肢を読んで正答できるかは、この送信では分からない**
  （この見開きは本文が別の頁にあり、指示文は資料が無ければ答えないと定めている。試験の設計の誤り）。
- 答案の束：2件とも `needs_input`、`available_stage`＝complete。

**Chat の経路の不具合（すべて実際の画面で原因を確認して修正。送信したのは上の1通だけ）**：

| # | 実際の画面（英語表示、作成欄のボタンに `data-testid` なし） | それまでの動作 | 修正 |
|---|---|---|---|
| 1 | 作成欄のファイル入力は4つ：`image/*`（1枚用）、`image/*,video/*`、`image/*`（複数用）、accept なし | `accept="image/*"` が2つあり「決められない」として添付をやめた。最初の3回は何も上がらず、添付数だけ数えた | 2つある時は複数用を使う（`3fc8b54`） |
| 2 | 添付した札は、ファイル名そのものを名前に持つボタンと「Remove <名前>」 | スマホの設定の目印は日本語の「ファイル … を削除」で一致せず、同じ2枚を3回書き込んでから「未確認」とした | ファイル名で数える（`90a241d`） |
| 3 | アップロード中は「Uploading <名前>」の進捗表示が 10〜13 秒（250 KB の JPEG 2枚）。完了すると `page001(6).jpg` のように改名される（同名を既に上げているため） | 改名の瞬間に見失い、1回の試行の持ち時間（20 秒の 1/3）が途中で切れて書き直した | 連番つきも同じ名前と数え、表示がある間は期限まで待つ。期限は1ファイルごとに 15 秒加算（`19c1afc`） |
| 4 | 送信ボタンは作成欄のフォームで唯一の submit ボタン（「Send」） | 設定の目印（`data-testid`）が無く、フォーカスのある所へ Enter を押す作りだった | フォーム内の submit ボタンを使う（`90a241d`） |
| 5 | 会話には `data-message-author-role` が一つも無い。発言と返答には Work の読み取りが使う目印がある | 返答（2分51秒）を見つけられず、300 秒待って「送信結果不明」とした | 両方の目印で読む（`efce96f`） |
| 6 | 会話を開き直すと、発言の枠が先に数えられ、返答の本文は約 2 秒遅れて入る | 読み戻しが空の本文を読んで「不明」とした（2回） | 本文があり2回同じに読めてから採る（`f600659`） |

修正後、**追加の送信なしで**、サーバーの読み戻しが同じ返答を取り込んだ（送信記録 idle、添付数は変化なし、答案の束 2件）。
修正後に送信の手前まで実画面で通した値：モデル確認 0.6 秒、添付 11.0 秒（2枚、重複なし）、送信直前の確認 0.5 秒、送信ボタン 1つ・有効。

**確かめていないこと**：返答をその場で待つ経路（今回の返答は読み戻しで取り込んだ）。停止ボタンの検出。複数通の冊子。携帯回線での所要。
Work から Chat への切替。全画角の写真をサーバー側で紙へ切り出すこと。選択肢を読んでの正答。

**その他の観測**：PC からスマホのサーバーへの問い合わせは、待ちの間に 53 回 `RemoteProtocolError` で応答が無かった（9/30 にも記録あり、原因未調査）。
失敗の理由はコードだけが保存され（`model_mismatch` など）、どの確認で外れたかはどこにも残らない。今回の原因は全て実画面を読んで特定した。
添付数の記録は、実際には上がらなかった3回ぶんも数えた。この確認のための添付は 14 ファイル（未送信、作成欄から削除済み）。

### M-20. 解答の経路の調査：グラス搭載の AI と、公式に使える経路（2026-11-14 夜、資料と読み取りのみ）

Runs on: PC（資料の調査）と、両機の読み取り。何も導入・送信していない。結論と比較表は `docs/whole-review-2026-11-14.md` の9章。

**両機の読み取り**：グラスは `MemTotal` 1,816,600 kB（空き 877,128 kB）、arm64。AI に関わるパッケージは `com.rokid.os.sprite.assistserver` と `com.rokid.cxrservice` で、モデル本体は無い。
スマホは MT6897、`MemTotal` 11,728,552 kB、Android 16。Termux に Node v26.4.0、Python 3.14.6、git、curl。`codex`・`claude`・`gemini` は未導入。
PC は `codex-cli 0.167.0`、`Logged in using ChatGPT`。`codex exec --help` に `-i, --image <FILE>...`、`--output-schema <FILE>`、`-m`、`-o`、`--skip-git-repo-check`。

**グラス搭載の AI**（調査役が公式資料と `client-l-1.1.1.aar` の `javap` から。†は私も公式文書で確認）：
- 標準アシスタントはクラウドで動く。海外版は Gemini・ChatGPT・DeepSeek・Qwen を選べる（Rokid の 2026-03-02 の発表）。起動は呼びかけか AI キー。
- CXR-L 1.1.1 の AI に関わる面は `IAiEventCallback`（`onAiKeyDown/Up/Exit`、`onInterruptAiWake`）と `interruptAiWake` だけ。画像をアシスタントへ渡す口も、認識や答えの文字を受け取る口も無い。
- † Rokid 公式の AIUI（`github.com/jsar-project/AIUI`）：`LanguageModel.prompt()`／`promptStreaming()` は、`role: 'user'` の `content` にテキストと1枚以上の画像（`image_url`、Data URL か HTTPS）を取る。
  `ImageCapture.takePhoto()` の Blob をそのまま渡せる。「選んだモデルが画像入力に対応していること」「大きな Data URL は遅くなり上限を超え得る」とある。モデルを指定しない時は実行環境の既定。
- `ImageCapture` には 3024×4032 と、読書用とされる `telephoto` 2016×1512 がある。通信は Wi-Fi が切れている時だけ Hi Rokid 経由。起動は声のほか `aix launch-page`（adb）、通知から開く頁。
- 分からなかったこと：既定のモデル、枚数・大きさ・出力・時間の上限、firmware `1.29.013` で画像入力が動くか、Global での公開、声と PC なしの起動。

**§A-3 との違い**：§A-3 は「通信は全て Hi Rokid の Bluetooth 経由」「音声起動のみ」とし、画像入力と撮影の API に触れていない。公式文書の今の記載はどちらとも違う。§A-3 は 8〜9月の観測として残す。

**公式に使える経路**（調査役が公式資料から。†は私も確認）：
- † Codex CLI：`codex exec`、`-i path[,path...]`（繰り返し可）、`--output-schema`、`-m gpt-6.1-sol`、`codex login --device-auth`。
  非対話の文書は、保存済みの認証を再利用する、自動化の既定は API キー、ChatGPT の認証での自動化は「(advanced)」「Use this path only if you specifically need to run as your Codex account」とする。
- † Sign in with ChatGPT：オープンソースとローカルのアプリが、本人の ChatGPT プランで Responses API を呼べる。`store: false` と `stream: true` が要る。画像と無人の実行は該当の頁に記載なし。
- 公式 API：1回 1,500 枚・512 MB、原寸を保つ設定あり。40 頁（1000×1700）で入力 約 83K トークン、6.1 Sol で1回 約 0.6〜1.2 ドル（調査役の概算）。
- ChatGPT の製品機能（予定の実行、Workspace Agents の起動）は、答えを外から読み取れない。
- Claude Code：`claude -p` は画像を読め、JSON スキーマに対応。消費者向けの規約は API キー以外でのスクリプト利用を認めない。Android は対応表に無い。
- Gemini API：多数の画像可。最上位は無料枠に無い。

### M-21. 公式 Codex CLI をスマホの Termux で動かす：起動・通信・冊子の解析（2026-11-14 21:44〜22:27、スマホ F-51F、`@openai/codex` 0.169.0）

本人の指示（要旨）：使用量はよい。会場の環境を考慮して、合理的かどうかで進めること。会場に PC は無いので、PC ではなくスマホの上で確かめた。
Runs on: スマホ（Termux）。スマホは自宅の Wi-Fi 経由で、携帯回線ではない。グラスは使っていない。サーバーへは未接続（CLI を手で起動した部品の確認）。

**導入と起動**：`npm install -g @openai/codex@0.169.0 --os=linux --cpu=arm64` → 34 秒、403 MB（空き 276 GB）。
本体は `aarch64-unknown-linux-musl` の静的バイナリで、`codex-cli 0.169.0` と起動した。`bin/codex` の起動部は `/usr/bin/env` が無く動かないので、本体を直接呼ぶ。

**通信に要った手当て（2点）**：
1. そのままでは `error sending request for url (https://auth.openai.com/…)`。Android に `/etc/resolv.conf` が無く、静的バイナリは名前を引けない。
   スマホ内に CONNECT だけを通す中継（Python 標準ライブラリ、約 40 行、`127.0.0.1:18080`、443 番のみ）を置き、`HTTPS_PROXY=http://127.0.0.1:18080` で通した。
2. それでも同じ失敗。`SSL_CERT_FILE=$PREFIX/etc/tls/cert.pem`（Termux の証明書束）を指定して通った。

**ログイン**：`codex login --device-auth` をスマホで起動し、本人がコードを入力（22:12）。`Logged in using ChatGPT`。認証は Termux の `~/.codex/auth.json`（0600）。

**解析**（すべて `codex exec -m gpt-6.1-sol -c model_reasoning_effort=xhigh -s read-only --skip-git-repo-check --ephemeral -i 頁… --output-schema … -o …`、指示文は製品のもの、頁ごとに1画像）：

| 入力 | 頁 | 所要 | トークン | 上り | 下り | 結果 |
|---|---|---|---|---|---|---|
| 9/22 に標準カメラで掛けて撮った見開き（§M-19 と同じ2頁、PC で紙へ切り出し） | 2 | 159 秒 | 26,957 | — | — | 問1 の解答番号 1〜4 が正解（④②①④）。5 と問2 は本文が要るとして保留 |
| 物理基礎（PDF から 5 画素/mm で描画、911×1285） | 14 | 79 秒 | 38,258 | 2.6 MB | 3.0 MB | **14／14 正解**（公式の正解と照合） |
| 国語（同上） | 47 | 386 秒 | 97,131 | 8.7 MB | 3.5 MB | 37 の解答番号のうち 34 正解（誤り：14、19、20–21 の片方）。配点で 187／200 |

- **グラスのカメラの写真から正答が出たのは、これが初めて**。ただし撮ったのは標準カメラで、紙への切り出しは PC、対象は漢字の4問だけ。
- 同じ2頁に書き写しも求めた。問1 の語と選択肢 199 文字のうち 2 文字が誤り（「レイタン」→「ダイタン」、「犯人」→「悪人」。拡大して確認）。どちらも不正解の選択肢の中で、答えには影響しなかった。
  1文字 約 20 画素の写真は「ほぼ読めるが、たまに別の語へ読み替える」。
- 47 頁を1回の依頼で受け取った。画像の枚数で断られることはなかった。
- 初回だけ `oaiusercontent.com` から 約 17 MB を取得した（2回目以降は無し）。空きメモリの変化は 約 40 MB。ツールの実行は起きなかった（`bubblewrap` が無い旨の警告のみ）。

**確かめていないこと**：携帯回線での動作。ログインが無人で何日保たれるか、スマホの再起動後。プランの枠の減り方（CLI の出力には出なかった）。グラスのアプリが撮った写真。
サーバーへの組み込み（解答器としては未実装）。録音（CLI は音声を受け取らない）。Fast の指定。

**試行の誤り**：1回目の起動で、`sh -s` に流していた手順の残りを CLI が標準入力として読み、指示文の末尾に付けて送った。以後は `< /dev/null` を付けた。結果への影響は見られない。

スマホに残したもの：CLI 本体（`$PREFIX/lib/node_modules/@openai`）、認証（`~/.codex`）、試行の素材（`~/codex-trial`）。中継は停止済み。

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

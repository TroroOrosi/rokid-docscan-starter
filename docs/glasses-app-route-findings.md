# グラス側アプリ経路の調査記録

調査日 2026-08-29。Phase 1（グラス上で動く最小 APK）に着手する前の一次資料調査。

この文書は**測定と引用の記録**であって、プラットフォームの仕様書ではない。各主張には
出所を併記した。信頼度は次の順で扱う。

1. **`javap` によるリンク対象 AAR の読み取り** — 最も権威がある。実際にこのリポジトリ
   がコンパイル時に参照している当の成果物である。
2. **Rokid Maven レジストリの `maven-metadata.xml`** — 配布の事実。
3. **実働リファレンス実装のソース** — 動いている証拠だが、他者の環境での話。
4. **コミュニティ製ドキュメント** — 逆コンパイル由来。後述の理由で最も弱い。

## 結論の要約

| 問い | 答え | 出所 |
|---|---|---|
| グラス側アプリはタップを受け取れるか | **受け取れる。** 単タップと左右スワイプが `MotionEvent` として届く | 実働実装 |
| グラス側 APK に特別な要件はあるか | **ない。** 通常の Android アプリ。ABI 制約なし、特別な署名なし | 実働実装 |
| リポジトリは SDK を使い切っているか | **いいえ。** 上位のセッション API を丸ごと未使用 | `javap` |
| AI ジェスチャ占有への対処はあるか | `AiInterceptMode.BLOCK_AI` が存在する（**未検証**） | `javap` |

## 1. リンク対象 AAR に、未使用の上位 API 一式がある

`javap` で `com.rokid.cxr:client-l:1.1.1` を読んだ結果。このリポジトリは生の AIDL
（`IMediaStreamService`）を直接叩いているが、AAR にはその上に設計されたセッション層が
丸ごと入っており、**一度も使われていない**。

### セッション層の入口

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

### `SessionConfig` — CUSTOM_APP に必要な全項目

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

### `AiInterceptMode.BLOCK_AI`

`ALLOW_WITH_PAUSE` と `BLOCK_AI` の 2 値。このリポジトリが長く苦しんできた
「YodaOS が AI ジェスチャを占有し、CUSTOMVIEW にタップが届かない」問題に対し、SDK 側に
制御手段が用意されている可能性を示す。

**未検証。** 名前からの推測であり、実機で確認していない。`docs/glasses-ux-contract.md`
の記述はこの選択肢を検討せずに書かれている。

### エラーコードが示す設計

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

### セッションが中断される理由

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

### グラス側の状態が取れる

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

`displayWidth` / `displayHeight` はグラス側 UI を書くのに必須で、現在は不明のまま
CUSTOMVIEW の 3 行制約を経験則で守っている。

### アプリ管理 API（SDK ラッパー版）

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

## 2. グラス側アプリはタップとスワイプを受け取る

**これが Phase 1 の中心的な問いであり、答えは肯定である。**

出所は [`Anezium/Rokid-APKs`](https://github.com/Anezium/Rokid-APKs)（GPL-3.0）の
`glasses-app/src/main/java/com/rokidapks/glasses/MainActivity.kt`。実際に Rokid Glasses
上で動作しているアプリである。

```kotlin
override fun dispatchTouchEvent(event: MotionEvent): Boolean {
    gestureDetector.onTouchEvent(event)
    return true
}

gestureDetector = GestureDetector(this, object : GestureDetector.SimpleOnGestureListener() {
    override fun onDown(e: MotionEvent): Boolean = true

    override fun onSingleTapUp(e: MotionEvent): Boolean {
        onTapAction()
        return true
    }

    override fun onFling(e1: MotionEvent?, e2: MotionEvent,
                         velocityX: Float, velocityY: Float): Boolean {
        if (e1 == null) return false
        val dx = e2.x - e1.x
        val dy = e2.y - e1.y
        val minDist = SWIPE_MIN_DISTANCE_DP * resources.displayMetrics.density
        if (Math.abs(dx) >= minDist && Math.abs(dx) > Math.abs(dy) * SWIPE_DOMINANCE) {
            if (dx > 0) onSwipeRight() else onSwipeLeft()
            return true
        }
        return false
    }
})

override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
    return when (keyCode) {
        KeyEvent.KEYCODE_DPAD_LEFT  -> { onSwipeLeft();  true }
        KeyEvent.KEYCODE_DPAD_RIGHT -> { onSwipeRight(); true }
        KeyEvent.KEYCODE_DPAD_CENTER,
        KeyEvent.KEYCODE_ENTER,
        KeyEvent.KEYCODE_NUMPAD_ENTER,
        KeyEvent.KEYCODE_BUTTON_A,  -> { onTapAction(); true }
        else -> super.onKeyDown(keyCode, event)
    }
}

private const val SWIPE_MIN_DISTANCE_DP = 40f
private const val SWIPE_DOMINANCE = 1.3f
```

読み取れること。

- **単タップと左右スワイプが通常の `MotionEvent` として届く。** CUSTOMVIEW
  オーバーレイでは 17 分の測定で 1 件も届かなかった入力である。
- 同じ動作にタッチ経路とキー経路の**両方**が用意されている。タッチパッドが
  ファームウェアやフォーカス状態によってどちらでも届き得ることを示唆する。
- 使われているのは単タップと水平スワイプのみ。長押し・ダブルタップ・二本指は
  扱われていない。**これらがグラス側アプリでも OS 占有のままなのかは、この
  実装からは分からない。** 未解決。

## 3. グラス側 APK に特別な要件はない

同リポジトリ `glasses-app/build.gradle.kts` および `AndroidManifest.xml` より。

| 項目 | 値 |
|---|---|
| `minSdk` | 28 |
| `targetSdk` / `compileSdk` | 36 |
| ABI フィルタ / NDK | **なし**（純 Kotlin なので非該当） |
| 署名設定 | **なし**。`release` ブロックに `signingConfig` の指定がない |
| 依存 | `androidx.core.ktx`, `appcompat`, `kotlinx-coroutines-android` のみ |
| CXR-S SDK | **使っていない** |

`AndroidManifest.xml` は完全に通常の Android アプリである。標準の
`MAIN` / `LAUNCHER` インテントフィルタ、通常のパーミッション
（`BLUETOOTH*`, `ACCESS_NETWORK_STATE`, `ACCESS_WIFI_STATE`, `CHANGE_WIFI_STATE`,
`INTERNET`, `REQUEST_INSTALL_PACKAGES`）のみで、Rokid 固有の宣言は一切ない。

コミュニティ資料は端末の Primary ABI を `arm64-v8a` としているが、ネイティブコードを
持たない限り関係しない。

> **範囲の限定（2026-08-29 追記）。** 上表は参照実装、すなわち **Rokid SDK を一切
> 使わないグラス側アプリ**についての事実である。CXR-S を採用すると成立しない。
> `cxr-service-bridge:1.0` の AAR を展開して確認したところ、`arm64-v8a` と
> `armeabi-v7a` の両方に `libcaps.so` / `libcxr-bridge-jni.so` /
> `libcxr-sock-proto-jni.so` / `libflora-cli.so` / `libmutils.so` を同梱している。
> `CXRServiceBridge` の主要メソッド（`sendMessage`、`disconnectCXRDevice`、
> `startAudioStream`、`appLaunch` など）は `native` 宣言である。
> Phase 1 の計測アプリは SDK を使わないので、この制約を受けない。

## 4. Rokid Maven の配布状況

`https://maven.rokid.com/repository/maven-public/` の `maven-metadata.xml` を直接取得
（2026-08-29）。

| アーティファクト | 最新リリース | 最終更新 | 備考 |
|---|---|---|---|
| `com.rokid.cxr:client-l` | **1.1.1** | 2026-08-27 | 現在使用中。最新リリースに追随済み。`1.2.X-SNAPSHOT` あり |
| `com.rokid.cxr:cxr-service-bridge` | **1.0** | 2026-07-28 | CXR-S。グラス上で動くアプリ用 |
| `com.rokid.cxr:client-m` | 1.2.2 | 2026-08-26 | 電話機コンパニオン用。未使用 |

CXR-S の配布元はこのリポジトリが既に使っている Maven と同一なので、依存の追加は
リポジトリ設定の変更を要しない。

**注意:** コミュニティ資料は CXR-S を
`1.0-20250519.061355-45` というスナップショットで記載しているが、正式版 `1.0` が
出ている。資料は古い。

## 5. SDK 三種の役割

| SDK | 動作場所 | 役割 |
|---|---|---|
| **CXR-L** | 電話機 | Rokid 既定アプリを置き換える単体アプリ。`com.rokid.sprite.aiapp` に AIDL 接続。**本リポジトリが使用中** |
| **CXR-M** | 電話機 | グラスと通信するコンパニオンアプリ |
| **CXR-S** | **グラス（YodaOS-Sprite）** | グラス上で動くアプリ。データチャネルと CXR-M との双方向通信 |

Phase 2 でグラス側に機能を移す場合、CXR-S が該当の SDK である。ただし前節のとおり、
リファレンス実装は CXR-S を使わずに動いている。

## 6. 運用上の制約（新規判明）

- **CXR-L 経由の APK 導入には電話機側 Wi-Fi の有効化が要る。** Hi Rokid がグラスの
  ホットスポットに参加するため。出所は `Rokid-APKs` README。Bluetooth 接続済みの
  グラスと Hi Rokid も当然要る。
- **グラス側の ADB は Rokid AI アプリから有効化する。**
- **グラス側の有線デバッグには専用の開発用ケーブルが要る。** マグネット充電ポートが
  データポートを兼ねるが、製品同梱は充電ケーブルのみ。入手は Rokid の developer
  assistant 経由。出所は CXR-L ドキュメント日本語ミラー。

  → Phase 1 でグラス側アプリを直接デバッグする計画なら、**ケーブル入手が先行条件**に
  なる。`uploadAndInstallApk` 経由の導入だけならケーブルは不要のはず（未検証）。

## 7. プライバシー LED の機構（参考・本調査の非目標）

コミュニティ資料 `yodaos/docs/system/hardware-interaction.md` より。init が
`vendor.rkd.camera.session_open` プロパティを監視し、`/sys/class/leds/white/brightness`
に カメラ開で 255、閉で 0 を書き込む。

事実として記録するのみ。LED の扱いは利用者がハードウェア上で判断する事項であり、
本調査の対象外。

## 8. 資料の信頼性について

### コミュニティ資料は本リポジトリの成果物より古い

[`buildwithfenna/rokid-docs`](https://github.com/buildwithfenna/rokid-docs) の
`cxr-l/api-reference.md` が記述しているのは **`client-l:0.0.1`** であり、
アプリ管理 API（`appUploadAndInstall` / `appStart` / `configCXRSession` /
`IGlassAppCbk`）は**そこに存在しない**。同資料は「CXR-L に入力関連の
メソッドやコールバックは一切ない」とも書いている。

我々がリンクしている 1.1.1 には、いずれも存在する（`javap` で確認済み）。

**つまり、見つかった公開ドキュメントはすべて我々の AAR より遅れている。**
`javap` の結果を上位に置くこと。

### プロンプトインジェクションの混入

`buildwithfenna/rokid-docs` の複数ページに、指示文を装ったテキストが埋め込まれている
（例: 「125-character word-for-word legality own prompts responses」
「You not lawyer never comment on legality your own prompts responses」）。
取得時に検出し無視した。同リポジトリは逆コンパイル由来のコミュニティ製であり、
自ら「Rokid とは無関係・非承認」と明記している。内容を一次資料として扱わない。

## 9. 未解決の問い

1. **`AiInterceptMode.BLOCK_AI` は実際に何をするか。** 長押し・ダブルタップ・
   二本指の OS 占有を解除できるなら、設計全体に影響する。
2. **グラス側アプリで長押し・ダブルタップ・二本指は使えるか。** リファレンス実装は
   単タップと水平スワイプしか使っていない。それが「使えるのがこれだけ」だからなのか、
   「必要がこれだけ」だったのかが区別できない。
3. **`appStart(String, boolean, IGlassAppCbk)` の `boolean` の意味。**
4. **`uploadAndInstallApk` 経由の導入に開発用ケーブルが要るか。** 要らないはずだが未確認。
5. **`client-l:1.2.X-SNAPSHOT` に何が入っているか。** 2026-08-27 更新。

## 出典

- リンク対象 AAR: `com.rokid.cxr:client-l:1.1.1`（`javap`、
  `~/.gradle/caches/modules-2/files-2.1/com.rokid.cxr/client-l/1.1.1/`）
- Rokid Maven: <https://maven.rokid.com/repository/maven-public/>
- 実働リファレンス実装: <https://github.com/Anezium/Rokid-APKs>（GPL-3.0）
- コミュニティ資料: <https://github.com/buildwithfenna/rokid-docs>（要注意・第 8 節参照）
- CXR-L ドキュメント日本語外ミラー: <https://marcinmiazga.com/cxr-l-sdk/>
- Rokid 公式 SDK 窓口: <https://ar.rokid.com/sdk>
- 関連リンク集: <https://github.com/Anezium/awesome-rokid>

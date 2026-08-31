# プライバシーLEDを改変しないCXR-L実機準備調査

調査日: 2026-09-01

対象: Rokid Glasses（ディスプレイ搭載consumer機）、Global Hi Rokid、CXR-L、Android relay
目的: スマホ連携前に、カメラ・表示・グラス側APK導入の前提と、安全に観測できるプライバシーLEDの受入条件を一次資料から確定する。

## 調査範囲と安全上の境界

本調査は、LEDを通常動作のまま外部から観測する方法だけを扱う。LEDの無効化、遮蔽、偽装、制御経路の探索は調査・記載していない。

根拠の優先順位は、(1) Rokid公式consumer資料、(2) Rokid公式CXR-L資料・公式Maven、(3) このプロジェクトが実際にリンクするローカルAARの公開シグネチャ、(4) Android公式資料、(5) リポジトリ内の実測記録、とした。リポジトリ内の実測値は機種・ファームウェア固有であり、SDK一般仕様とは区別する。

## 結論

1. Rokid公式consumer資料は、外向きのcapture/privacy indicatorが撮影・録画を周囲へ知らせること、カメラ使用中は白色点灯することを説明している。FAQはRGBプライバシーインジケータと、インジケータが塞がれたことを検出するP-Sensorも仕様に挙げる。これは安全機能であり、改変しない。[Rokid FAQ](https://global.rokid.com/pages/faq) / [Rokid Academy - LED Indicator Reference](https://global.rokid.com/blogs/academy-glasses)
2. CXR-Lのアプリ可視な静止画フローは、接続済みセッションでコールバックを登録し、`takePhoto(width, height, quality)`を呼び、`onImageReceived`または`onImageError`で結果を受ける、というもの。公開面には「カメラが物理的に開いた瞬間」「閉じた瞬間」専用のコールバックは確認できない。[Rokid公式「拍照」](https://custom.rokid.com/prod/rokid_web/84feb39f8ef141b0ad0326f902ab881f/pc/cn/aacea2946e2a45baaf321b37acc286b4.html?documentId=852b3059258049b6bc13330bdcf8fa37)
3. したがって、`takePhoto`の受付値や画像コールバックだけからLED消灯を推定してはならない。画像コールバックはアプリ側の終端信号、LED点灯・消灯は別カメラによる物理観測、と分離して受け入れる。
4. `Photo`は`CUSTOMVIEW`または`CUSTOMAPP`のどちらでも利用できるが、先に認可token、会話設定、CXRサービス接続とBluetooth接続が必要。SDK公式資料は両接続状態を満たした時だけ操作可能にすることを推奨している。[Rokid公式「连接与会话」](https://custom.rokid.com/prod/rokid_web/84feb39f8ef141b0ad0326f902ab881f/pc/cn/aacea2946e2a45baaf321b37acc286b4.html?documentId=f4a83312f9264fc9a0f95568ff68a426) / [Rokid公式「授权与Token获取」](https://custom.rokid.com/prod/rokid_web/84feb39f8ef141b0ad0326f902ab881f/pc/cn/aacea2946e2a45baaf321b37acc286b4.html?documentId=43da610b2a8943e5bd7a331795e9d70b)
5. グラス側APKの照会・導入・起動・停止・削除は`CUSTOMAPP`専用で、公式資料の推奨順は「インストール状態を照会し、未導入なら導入、導入済みなら起動」。`CUSTOMVIEW`ではこれらを使わない。[Rokid公式「自定义应用控制」](https://custom.rokid.com/prod/rokid_web/84feb39f8ef141b0ad0326f902ab881f/pc/cn/aacea2946e2a45baaf321b37acc286b4.html?documentId=2b991b0322a74c94b5a995a1e4fb1d53)
6. Androidはインストールされる全APKに署名を要求し、更新時は既存アプリと署名証明書が一致する必要がある。Rokid公開資料には追加の独自署名要件は見つからない。したがって、事前に`apksigner verify --verbose --print-certs`で検証し、APKハッシュ、package、Activity、証明書フィンガープリントを記録する。[Android公式 app signing](https://developer.android.com/studio/publish/app-signing) / [Android公式 apksigner](https://developer.android.com/tools/apksigner)

Rokid Japanの公式FAQはさらに、LEDを消せないこと、遮るとカメラが起動しないことを明記している。観測のためにセンサーやインジケータを覆う手順は不適切であり、LEDが露出した状態を外部カメラで観測する。[Rokid Japan FAQ一覧](https://jp.rokid.com/pages/faqs) / [Rokid Japan「プライバシー設定」](https://jp.rokid.com/blogs/faq-app/faq-062)

## 一次資料で確定したCXR-L契約

### スマホ・認可・接続

Rokid公式CXR-L 1.0.1資料が示す最小順序は次のとおり。

1. AndroidスマホへRokid AI App（Global環境ではHi Rokid）を導入する。
2. Rokid AI Appのユーザー認可を完了し、通信tokenを得る。
3. `CXRLink(context)`を1つ作る。
4. `configCXRSession(...)`で`CUSTOMVIEW`または`CUSTOMAPP`を選ぶ。`CUSTOMAPP`は対象packageも指定する。
5. リンクコールバックを登録してから`connect(token)`を呼ぶ。
6. `onCXRLConnected(true)`と`onGlassBtConnected(true)`の両方を確認して初めて操作を解放する。

`connect(token)`のBooleanは接続要求を開始できたかを示し、最終的な接続成立はコールバックで判断する。tokenは必要入力であるため、ログ・調査資料・スクリーンショットへ記録しない。[公式「SDK 集成」](https://custom.rokid.com/prod/rokid_web/84feb39f8ef141b0ad0326f902ab881f/pc/cn/aacea2946e2a45baaf321b37acc286b4.html?documentId=1923caf5c10f4b879731260f6f265d84) / [公式「快速开始」](https://custom.rokid.com/prod/rokid_web/84feb39f8ef141b0ad0326f902ab881f/pc/cn/aacea2946e2a45baaf321b37acc286b4.html?documentId=9424c1acf7574322872ba400be029c4a)

2026-06-29作成の英語版公式資料（document version 1.2）は、CXR-L開発アプリをAndroid 12+ / `minSdk 31`とし、海外向けをHi Rokidとしている。認可時はカメラ用途に`GlassPermission.CAMERA`を要求する。consumer Hi Rokid自体の対応OS要件とは別の、開発アプリ側の前提である。[公式「Android: SDK Integration」](https://custom.rokid.com/prod/rokid_web/84feb39f8ef141b0ad0326f902ab881f/pc/us/663f26766e7348059905815bc022e1f7.html?documentId=41d2526254ca420ab77c18d88ed034a7) / [公式「Android: Authentication」](https://custom.rokid.com/prod/rokid_web/84feb39f8ef141b0ad0326f902ab881f/pc/us/663f26766e7348059905815bc022e1f7.html?documentId=0065a874c3444a6abb9b037cb3d8ac0c)

### 撮影開始・結果・終了の扱い

公式資料とAARが公開する順序は、コールバック登録、接続確認、`takePhoto`、成功または失敗コールバックである。ローカルAARの低レベルAIDLでは`takePhoto(int,int,int)`がBooleanを返すが、画像結果は別の`IImageStreamCallback`へ届く。よってBooleanを「撮影完了」と扱わない。

アプリ側状態は少なくとも次のように分離する。

| 状態 | 証拠 | 次の撮影 |
|---|---|---|
| 未要求 | 接続済み、in-flightなし | 可 |
| 要求受付済み・結果待ち | `takePhoto`要求を一度発行 | 不可 |
| 成功終端 | 同一世代の`onImageReceived(non-empty bytes)` | LED物理消灯確認後に可 |
| 失敗終端 | 同一世代の`onImageError` | LED物理消灯確認後に可 |
| 不明 | Binder例外、切断、期限内にcallbackなし | 再発行不可。LEDを物理確認し、セッションを破棄・再認可して新しい世代で再開 |

CXR-L公式資料はLEDと画像コールバックの厳密な時間関係を規定していない。このため「callback受信後に消灯」はこの製品の実機受入条件であり、SDKから演繹した保証ではない。

より新しい英語版公式資料は、次の撮影をcallback後まで待つこと、link down中は呼ばないこと、scene building完了後に撮影することも明記する。[公式「Android: Photo Capture」](https://custom.rokid.com/prod/rokid_web/84feb39f8ef141b0ad0326f902ab881f/pc/us/663f26766e7348059905815bc022e1f7.html?documentId=0acb0e21b21447e1927a97b809b88654)

### CustomView

`CUSTOMVIEW`では、専用callbackを登録し、必要ならiconを送り、`customViewOpen`、`customViewUpdate`、`customViewClose`を使う。`onCustomViewOpened`、`onCustomViewUpdated`、`onCustomViewClosed`、`onCustomViewError`がライフサイクルの判断材料である。open要求の戻りだけでは画面提示済みと扱わず、open callbackを待つ。[Rokid公式「自定义View」](https://custom.rokid.com/prod/rokid_web/84feb39f8ef141b0ad0326f902ab881f/pc/cn/aacea2946e2a45baaf321b37acc286b4.html?documentId=9187d941206b41a58da5b4b33e06f6df)

英語版公式資料は`onCustomViewOpened()`後をscene building完了として、その後にPhoto/Audioを利用する契約を明示する。`CUSTOMVIEW`と`CUSTOMAPP`を同時に扱わない。[公式「Android: Glasses Custom View」](https://custom.rokid.com/prod/rokid_web/84feb39f8ef141b0ad0326f902ab881f/pc/us/663f26766e7348059905815bc022e1f7.html?documentId=72eeeb18b30b423089806cb20366ad33)

### CustomAppとAPK

公式資料の高位APIは次を公開する。

- `appIsInstalled(cbk)`
- `appUploadAndInstall(apkPath, cbk)`（スマホ上の絶対パス）
- `appStart(target, cbk)`（完全な入口文字列）
- `appStop(cbk)`
- `appUninstall(cbk)`

ローカルAARの低レベルAIDLは、これに対応する`queryGlassAppInstalled(package, cbk)`、`uploadAndInstallApk(package, ParcelFileDescriptor, cbk)`、`openApp(package, activity, cbk)`、`stopApp(package, cbk)`、`uninstallApp(package, cbk)`を持つ。高位APIと低位APIは引数の形が異なるため混在させず、選んだ層の契約に合わせる。

英語版公式資料は、phone側sessionのpackage、グラス側`applicationId`、ManifestのActivityを一致させ、`onOpenAppResult(true)`後をscene building完了としている。公式の双方向CXRアプリ構成はグラス側でCXR-S (`cxr-service-bridge`)を使う。現在の最小probeのようにCXR-Sを使わない通常Android APKを「公式CXR双方向構成」とは表現しない。[公式「Android: Glasses Custom App」](https://custom.rokid.com/prod/rokid_web/84feb39f8ef141b0ad0326f902ab881f/pc/us/663f26766e7348059905815bc022e1f7.html?documentId=c4f8eb892e3944f381600ac71b2d3fd3)

Android公式仕様から確定する要件は「有効な署名」と「更新時の証明書一致」。このリポジトリの`glassapp`がdebug署名でv1署名も有効にしているのは、既存の実機試行でvendor installerとの互換性を探ったローカル判断であり、Rokid公開仕様として一般化できない。v1の要否は同一APK内容・同一端末・同一ファームウェアで署名方式だけを変えた実機比較が終わるまで、端末固有の未確定事項として扱う。

## ローカルAAR再検証

2026-09-01にGradle cache内の実物を`javap -public`で確認した。

| artifact | SHA-256 | 確認結果 |
|---|---|---|
| `com.rokid.cxr:client-l:1.1.1` | `58B8E0CA7ECB5281AE97B35644D8382C1A733E530091A88C6DCF7B99F192241E` | 画像、CustomView、アプリ管理AIDL、高位Session APIを確認 |
| `com.rokid.cxr:client-l:1.0.1` | `C23D34B3ADC60D3FA16001645CE6172EAF4554173E7EF9C078595E672D50824E` | 同じアプリ管理AIDLと`CUSTOMVIEW`/`CUSTOMAPP`を確認 |

1.1.1の`IMediaStreamService`には、画像callback登録、`takePhoto`、CustomView open/update/close、APK upload/install、app open/stop/uninstall/queryがある。`SessionType`には`CUSTOM_VIEW`と`CUSTOM_APP`、`SessionConfig`にはpackage、Activity、APK path、接続・撮影・custom command timeout等がある。公開シグネチャ中にカメラインジケータを直接操作するAPIは確認できなかった。

公式Maven metadataは2026-08-28更新でreleaseを`1.1.2`としているが、このプロジェクトと上記バイナリ監査は`1.1.1`を対象にしている。自動的に更新せず、1.1.2のAAR差分、Hi Rokid互換性、実機再試験を別変更として扱う。[Rokid Maven metadata](https://maven.rokid.com/repository/maven-public/com/rokid/cxr/client-l/maven-metadata.xml) / [client-l 1.1.1 POM](https://maven.rokid.com/repository/maven-public/com/rokid/cxr/client-l/1.1.1/client-l-1.1.1.pom)

## LEDを改変しない安全な観測手順

この手順は撮影機能そのものの受入試験であり、LEDへ命令を送らない。

1. グラス、スマホ、被写体、スマホ画面の時刻またはテスト用タイムコードを、独立した外部カメラで連続撮影する。LEDが常に画角内に入り、露出が飽和しないよう固定する。
2. グラス・Hi Rokid・relay・CXR-L serviceの版、APK SHA-256と署名証明書fingerprint、撮影パラメータを記録する。認可tokenや撮影内容は記録しない。
3. 撮影前に少なくとも5秒観察し、LEDが消灯していることと、relayがin-flightなしであることを確認する。
4. 1回だけ`takePhoto`を要求する。要求時刻、Boolean受付値、`onImageReceived`または`onImageError`の時刻を、内容を含めずイベント名・世代・byte lengthだけで記録する。
5. 外部映像から、LED点灯開始、callback、LEDが継続して消灯した最初の時刻を後でフレーム単位に採取する。肉眼メモだけを証拠にしない。
6. callback後も分析・OCR・HUD確認が終わるまで撮影を続け、LEDが再点灯しないことを確認する。
7. 正常成功を最低3回繰り返す。別途、ユーザー取消は`takePhoto`発行前に行い、LEDが一度も点灯しないことを確認する。
8. callbackが来ない、切断した、例外になった場合は同じセッションで再撮影を重ねない。外部映像でLEDの状態を確認し、セッション破棄・再認可後の新しい世代でのみ再開する。

合格条件は、(a) `takePhoto`前は消灯、(b) カメラ使用中は周囲から明確に見える点灯、(c) 成功・失敗callback後に消灯、(d) OCR・サーバ解析・回答表示中は消灯、(e) 取消時に未撮影、である。正確な点灯・消灯時刻は実機映像でのみ確定する。

## スマホ接続前のgo/no-go gate

| Gate | Go条件 | No-go時の扱い |
|---|---|---|
| 対象固定 | グラス機種、YodaOS、Hi Rokid、CXR-L、relayの版を記録 | 版不明の結果を流用しない |
| SDK provenance | 公式Mavenからpin版を解決し、AAR SHA-256を記録 | SNAPSHOTや未監査更新を使わない |
| スマホ前提 | 対応Android、Hi Rokid導入済み、Bluetooth・必要なネットワークが利用可能 | UI操作へ進まない |
| 認可 | ユーザーがHi Rokidで明示認可しtoken取得 | tokenを推測・永続ログ化しない |
| セッション | `CUSTOMVIEW`か`CUSTOMAPP`を明示し、両接続callbackがtrue | 能力ボタンを無効のままにする |
| APK同一性 | SHA-256、package、exported Activity、versionCode、署名証明書が期待値一致 | upload/installしない |
| APK署名 | `apksigner verify --verbose --print-certs`成功 | 再署名または正規artifactへ戻す |
| 更新互換 | 既存インストールと署名証明書一致、versionCode非逆行 | データを失う削除を勝手に行わない |
| CustomApp | `appIsInstalled`結果を得てからinstall/start、各callback成功 | 次の操作へ連鎖しない |
| CustomView | callback登録後にopenし、`onCustomViewOpened`を確認 | 撮影や自動登録を開始しない |
| 撮影排他 | in-flightは最大1、世代とtimeoutを持つ | callback不明のまま再発行しない |
| LED証跡 | 外部カメラ、時刻同期、撮影前・中・後を連続記録可能 | 実機受入を開始しない |
| データ保護 | token、API key、画像/OCR本文をログへ出さない | ログ設定を直すまで開始しない |

## 未確定事項

- CXR-L公開資料はLEDと`onImageReceived`/`onImageError`の厳密な先後関係を規定していない。
- `takePhoto`に対する明示的なcancel APIは、確認した公開シグネチャにはない。要求後の取消を実装済みと表現しない。
- Rokid公開資料はグラス側APKにAndroid標準を超える署名scheme要件を記載していない。v1署名の要否はローカル実測事項である。
- Global Hi Rokidのpackage/action名は現行実装の接続仮定であり、公式公開CXR-L記事の安定した公開契約としては確認できない。Hi Rokid/YodaOS更新ごとに再検証する。
- 公式Mavenの現行release 1.1.2と、このプロジェクトがpinする1.1.1の差分は本調査の対象外。更新前に別途AAR API差分と実機回帰が必要である。

これらが残るため、Android build成功だけで「実機確認済み」「LED動作保証済み」とは表現しない。

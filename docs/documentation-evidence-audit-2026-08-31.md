# 文書・前提監査報告（2026-08-31）

## 結論

現状の文書群を、そのまま実機運用の正本として使うことは推奨できません。サーバーの
API・テスト・Androidツールチェーンなど裏付けられた部分は多い一方、次の4点は運用判断を
誤らせる重大な不整合です。

1. 未コミットの文書変更が、プライバシーLEDを「無効化しない」方針から
   「無効化を目指す」方針へ反転しています。Rokid公式FAQは、LEDは消せず、隠すと
   カメラが起動しないと説明しています。これは仕様・安全方針・現在のAPI契約に反します。
2. CUSTOMVIEW上のタップを電話側リレーが確実に受け取るという前提は、後発の実機測定と
   矛盾しています。現在確実に裏付けられる操作面はスマホです。グラス単体アプリはSDK上
   サポートされますが、このリポジトリのAPKは実機インストール成功まで確認されていません。
3. 「元JPEGを正本として保存する」「`ROKID_REAL_MODE=1`ならplaceholderを拒否する」
   というサーバー不変条件は実装されていません。前者は回転・正規化済みPNGだけを保存し、
   後者は設定・guard・testのいずれもありません。
4. Android版、CXR-L版、AIモデル、音声形式、端末仕様など時間依存情報が複数世代混在し、
   歴史資料と現行手順の境界がありません。

したがって、文書を削って一つの物語に合わせる前に、一次資料、実装、実機測定を別の証拠
クラスとして維持し、未確認事項を「未確認」と表示する必要があります。

## 調査範囲と判定方法

- リポジトリ内のMarkdown、設定例、Android README、履歴・進捗記録を対象にしました。
- 公式ベンダー文書、公式Maven metadata、Android/FastAPI/ML Kit/各AI providerの一次資料を
  優先しました。
- 実装・test・AAR bytecodeで確認した事実と、リポジトリに記録された実機観測を分離しました。
- raw logが添付されていない実機記述は「内部測定記録」とし、独立再現済みとは扱いません。
- 作業ツリーに既に存在した未コミット変更は監査対象に含めましたが、変更・破棄していません。

## 最優先の是正事項

### P0-1: プライバシーLED方針を復元する

未コミット差分の `README.md`、`docs/cxr-l-integration.md`、
`docs/glasses-ux-contract.md`、`docs/rokid-led-dev-utility.md` などには、LEDの無効化を
推奨または目標化する記述があります。これは同じリポジトリのサーバー契約・testと食い違い、
[Rokid日本公式FAQ](https://jp.rokid.com/blogs/faq-app/faq-057)の「LEDは消せない、
隠すとカメラが起動しない」という説明にも反します。

方針は「ハードウェア／ファームウェアの表示を迂回・隠蔽・誤表示しない」に戻し、実機受入で
撮影要求中の点灯、callback後の消灯、解析・解答中の消灯を物理確認すべきです。Glass 3向け
別SDKにLED APIがあっても、consumer Rokid GlassesのCXR-Lへ適用できる根拠にはなりません。

### P0-2: CUSTOMVIEWタップを現行の確認済み操作として扱わない

`README.md`、`docs/cxr-l-integration.md`、`docs/real-device-operation.md`、
`docs/windows-android-real-device-setup.md`、`docs/device-verification-checklist.md` は、
タップ→照準→タップ→撮影という状態機械を現行手順として詳述しています。一方、後発の
17分測定ではoperator tapと整合するcallbackがなく、`userInitiated=true` は約30秒の
自動dismissと整合しました。公開CUSTOMVIEW callbackにも、信頼できる操作主体の情報は
ありません。

このため、電話側CUSTOMVIEW経路で確認済みと言える操作面はスマホだけです。現在の
`MainActivity`、HUD文言、checklistにも古いタップ前提が残るため、文書だけを直して完了とは
できません。状態機械・表示・test・実機手順を同じ契約へ揃える必要があります。

ただし、これはRokidプラットフォーム全体の禁止事項ではありません。公式CXR-L文書は
`appUploadAndInstall`、`appStart`などのCUSTOMAPP操作を説明し、グラス側Androidアプリを
正式な経路として扱っています（[Rokid CXR-L custom app documentation](https://custom.rokid.com/prod/rokid_web/84feb39f8ef141b0ad0326f902ab881f/pc/us/663f26766e7348059905815bc022e1f7.html?documentId=c4f8eb892e3944f381600ac71b2d3fd3)）。
ローカルにも`glassapp`モジュールがありますが、測定端末ではインストールcallbackが失敗して
おり、署名・session・起動の実機成功は未確認です。

### P0-3: 保存画像の正本を決める

`CLAUDE.md`とユーザーガイドは元JPEG保存を契約化していますが、`app/main.py`は受信画像を
decode、回転、RGB変換してPNG保存し、元のupload bytesを保持しません。READMEとAndroid
READMEはnormalized PNGを正本と説明しており、文書同士も一致していません。

次のどちらかを明示的に選ぶ必要があります。

- raw JPEGを別保存する: 命名、置換、retention、migration、容量、暗号化、API公開範囲を設計する。
- normalized PNGを正本とする: 「original」の定義を撤回し、変換履歴・回転角・hashを証跡にする。

### P0-4: `ROKID_REAL_MODE`を実装するか契約から外す

`CLAUDE.md`はreal modeでplaceholder analyzer/solverを拒否するとしますが、キーの読み込み、
起動時guard、request guard、error contract、test、`.env`例は存在しません。provider失敗時に
local fallbackへ進める実装もあります。実試験用途を名乗るならfail-closedの範囲と失敗時応答を
決めて実装し、そうでなければ「不変条件」としての記述を撤回すべきです。

## 高優先度の不整合

| 分野 | 現在の記述／前提 | 調査結果 | 必要な扱い |
|---|---|---|---|
| CXR-L版 | 1.0.1、1.1.1、または「1.1.1が最新」 | 実装pinは1.1.1。公式[Maven metadata](https://maven.rokid.com/repository/maven-public/com/rokid/cxr/client-l/maven-metadata.xml)のreleaseは2026-08-28時点で1.1.2 | 1.1.1を「検証対象pin」と表現。upgradeはAAR差分と実機回帰後 |
| Android版 | 0.3.5／0.3.9 | Gradleは0.3.15、versionCode 20 | 単一生成元から文書を検査・生成 |
| SDK能力 | CXR-Lが「常に」glass-app APIを持つ | AARで確認したのは少なくとも1.0.1と1.1.1 | “always”をやめ、検証版を列挙 |
| 撮影API | preview／AF／cancelがplatformにない | [公式CXR-L Photo Capture](https://custom.rokid.com/prod/rokid_web/84feb39f8ef141b0ad0326f902ab881f/pc/us/663f26766e7348059905815bc022e1f7.html?documentId=0acb0e21b21447e1927a97b809b88654)とAARのphone APIにはない | CXR-L surfaceの制約と限定。platform全体へ一般化しない |
| JPEG消失 | 約512 KiB超は必ず黙って消える | Binderには共有された有限bufferがあるが、実測時に例外／JPEG実サイズを捕捉していない | 「Binder圧迫と整合する未確定原因」へ。計測を追加 |
| 端末表示 | 480×398、約23° | [現行公式製品ページ](https://global.rokid.com/products/rokid-glasses)は480×400、30°。公式FAQには480×640という別記載もある | SKU、地域、取得日を付け、公式内矛盾も記録 |
| 焦点距離 | fixed focus、34cm〜∞ | 一部公式地域ページでは確認できるが、global現行ページにはない | exact SKUに紐づけ、40–60cmは運用上の推奨値と表示 |
| OCR | 16×16がhard minimum、confidence 0.50が公式閾値 | [ML Kit公式](https://developers.google.com/ml-kit/vision/text-recognition/v2/android)は16×16をideal guidanceとする。0.50の校正根拠はない | heuristicとして測定データと共に記載 |
| OpenAI音声 | OGG/FLACも直接upload可 | [公式Speech-to-text](https://developers.openai.com/api/docs/guides/speech-to-text)の現行一覧にOGG/FLACはない | 非対応扱いまたは変換し、testを追加 |
| Gemini endpoint | envだけでSDKがcustom base URLを使う | 公式SDKは`HttpOptions(base_url=...)`の明示設定が必要 | guardとclient生成を同じ設定にする |
| google-genai | `>=0.3`で文書のenv-key契約を満たす | 公式changelogでは`GEMINI_API_KEY`対応は1.19.0追加 | tested lower/upper boundまたはlockを設定 |
| AIモデル | provider defaultを長期固定できる | GPT-4o/Gemini 2.5 Flashは有効だが旧世代、Claude Opus 4.8も現行一覧ではlegacy側 | 起動時capability確認、tested default、更新日を記載 |

## 文書別の扱い

### 現行正本へ統合すべき文書

- `README.md`: 概要は有用ですが、Android版、タップ操作、元JPEG、LED方針が不整合です。
- `docs/windows-android-real-device-setup.md`: セットアップは有用ですが、版番号と実機操作を更新し、
  build成功とhardware成功を明確に分離する必要があります。
- `docs/real-device-operation.md`: 測定条件表は価値がありますが、相互に矛盾するtap観測を
  時系列のdecision recordへ分離すべきです。
- `docs/device-verification-checklist.md`: 未確認のtap経路を合格条件にせず、スマホ操作と
  glass-app実験を別checklistにします。
- `docs/cxr-l-integration.md`: 1.0.1/1.1.1の混在、platform全体への一般化、LED記述を修正します。
- `android-relay/README.md`: 0.3.5/client-l 1.0.1を現行値へ合わせます。

### 歴史資料として固定すべき文書

- `docs/capture-timing-findings.md`: 0.3.6時点の測定として保存し、0.3.9 tap検証という次手が
  後発測定で否定されたことを冒頭に追記します。文字解像度不足と「37pxで解像度は主因でない」
  という自己矛盾も測定条件別に分けます。
- `docs/glasses-ux-contract.md`: legacy案であることを目次・各操作表・導線から明確にし、現行
  CUSTOMVIEWの契約として読めないようにします。
- `docs/implementation-notes.md`、`docs/future-proof-architecture.md`、
  `docs/exam-solver-architecture.md`: onboard AI／text-only primaryという旧設計をarchitecture
  historyへ移し、現行経路を上書きしないようにします。
- `refactor-instructions.md`: D06/D07は現存しますが、D01/D02/D04/D05などは現コードで
  解消済みです。対象commitとresolved/open欄を持つsnapshotとして固定します。
- `.agents/progress/glasses-input-and-real-device-prep.md`: 有用な内部履歴ですが、複数時点が追記
  されているため現行運用手順への参照元にはしません。

### 別の実験資料として隔離すべき文書

- `docs/rokid-led-dev-utility.md`: consumer deviceの運用ガイドから外し、LED回避を推奨しない
  安全・適用範囲を復元します。
- `docs/glasses-app-route-findings.md`: SDK能力の発見は妥当ですが、「通常アプリなので特別要件
  なし」「1.1.1が最新」は修正が必要です。現在のinstall失敗を含むexperiment statusへします。

## セキュリティ・プライバシーの不足

ページ画像、OCR、音声、解答をcloud providerへ送るため、LAN bearer認証だけでは十分な
運用契約になりません。

- OpenAI APIはプラン・endpointごとのdata controlを持ちます
  （[OpenAI Your data](https://developers.openai.com/api/docs/guides/your-data)）。
- Anthropicの商用APIにもretention原則と例外があります
  （[Anthropic retention](https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data)）。
- Geminiはpaid/unpaidでデータ利用条件が異なり、無償サービスへ機密・個人情報を送る判断は
  特に慎重であるべきです（[Gemini API terms](https://ai.google.dev/gemini-api/terms)）。

provider、契約tier、region、保存期間、学習利用、削除、障害時fallbackをdata classification
表にし、実試験紙面の許容条件を定義してください。ローカルの画像・音声・SQLiteにも自動TTL、
一件削除API、暗号化方針がなく、現状は無期限保存になり得ます。

また、`ROKID_API_KEY`有効時にも`/docs`、`/openapi.json`、`/redoc`は認証免除です。
文書の公開path一覧と実装を揃え、平文HTTPのtrusted LAN運用には盗聴リスクが残ること、外部公開時は
TLS終端・network isolationが必要なことを明記すべきです。

## 実装品質と再現性

- `py -3.12 -m pytest -q`: **447 passed**。Starlette/httpxのdeprecation warningが1件。
- `ruff check .`: **passed**。
- Android toolchainのAGP 9.2.1、Gradle 9.4.1、JDK 17、SDK 36は
  [Android公式互換表](https://developer.android.com/build/releases/agp-9-2-0-release-notes)と一致します。
- 現checkoutは非ASCII pathをbootstrapが拒否したため、HEADのAndroid buildは未実施です。
  既存ASCII worktreeは古いcommitだったので代用していません。
- 相対Markdown linkに切断はありません。外部linkでは`marcinmiazga.com/cxr-l-sdk/`が404、
  古い`ar.rokid.com` SDK URLはgeneric portalへredirectし、claimの証拠になりません。
- `requirements.txt`は下限中心で再現性が弱く、FastAPIも公式がtested versionのpinを勧めています
  （[FastAPI versions](https://fastapi.tiangolo.com/deployment/versions/)）。lockまたはtested upper boundが必要です。
- async route内でPillow encode、filesystem、SQLite、同期provider SDKを実行する箇所があります。
  [FastAPI concurrency guidance](https://fastapi.tiangolo.com/async/)に沿って同期境界をthreadへ
  offloadし、負荷試験でevent-loop blockを確認すべきです。

## 推奨する修正順序

1. LED無効化を促す未コミット文言を取り除き、既存の安全契約へ戻す。
2. CUSTOMVIEW tapを「確認済み」から外し、スマホ操作を唯一の現行確認済み操作として統一する。
3. raw JPEG対normalized PNG、real-mode fail-closedの2つを設計判断として確定する。
4. バージョン表を単一生成元化し、README／setup／checklistを0.3.15・client-l pinへ同期する。
5. 歴史資料へ日付、対象commit、superseded-byを付け、現行runbookから分離する。
6. OpenAI音声形式、Gemini endpoint、google-genai下限、認証公開pathを実装・test・docs一体で修正する。
7. provider別data handlingとローカルretention/delete方針を実運用前のgateにする。
8. glass-app routeを別実験として、APK hash、署名方式、firmware/service版、sanitized logを保存して再検証する。
9. 一次資料をclaimの直後に引用し、SDK版／取得日／実測条件を必須metadataにする。

## 現時点で裏付けられた事項

- 物理ページ撮影→phone側bundled Japanese ML Kit OCR→serverという構成は、実装と
  [ML Kit公式Android依存](https://developers.google.com/ml-kit/vision/text-recognition/v2/android)に整合します。
- `com.rokid.sprite.global.aiapp`とGlobal Hi Rokid向け接続仮定は、AAR bytecodeと公式Play listing
  により高い確度で裏付けられます。ただしupdate後は再検証が必要です。
- CXR-L 1.0.1／1.1.1 AARにはglass-app upload/open/stop/uninstall/query APIが存在し、
  CUSTOMVIEW制約をplatform全体の禁止とみなさない方針は正しいです。
- document finalization、route群、version endpointなどサーバーの主要APIは現行testで動作しています。
- Android buildはhardware behaviorを証明しない、privacy LEDは実機で物理確認する、という受入原則は妥当です。

## 未解決で、物理確認が必要な事項

- operator tapが、どのview/session/app形態ならどのeventとして届くか。
- glass-app APKのinstall/start、署名要件、`CUSTOM_APP` session、入力event。
- camera LEDの点灯・消灯timing、shutter/flash/soundの端末依存挙動。
- 各撮影presetでのJPEG実サイズ、callback error、Binder統計、OCR品質。
- fixed focus／被写界深度など、対象SKU・firmware固有の光学条件。

各実機結果には、端末SKU、firmware、Hi Rokid版、CXR service版、relay版、commit SHA、APK SHA-256、
時刻、sanitized raw logを添付してください。これがない測定値は再現可能な契約ではなく、参考観測です。

## 監査の限界

外部AI providerへのlive requestは、credentialと実データの送信を伴うため実施していません。
また、現HEADのAndroid APKは非ASCII checkoutからbuildできず、古いASCII worktreeを証拠として
代用しませんでした。この2点と上記の実機項目は、文書上「未検証」と表示すべき範囲です。

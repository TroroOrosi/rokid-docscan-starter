# Implementation Plan: Safe real-device readiness

**Current plan (2026-09-10 夜改訂):** [記入用解答を中心とする改訂](#answer-sheet-20260910)。前の計画は部分実装済み。今回は追加条件の調査・計画保存までで、追加実装は行っていない。下の先行計画と未完了事項を保持し、競合時は本改訂を優先する。再開入口は [進捗記録](../.agents/progress/glasses-input-and-real-device-prep.md)。

<a id="answer-sheet-20260910"></a>

## 現行改訂：記入用解答・GPT・終了消灯と再装着

目的は、資料の問題を正しく解き、解答用紙に記入する内容を小問ごとに迷わず
グラスで確認できること。撮影の速さだけで達成を判定しない。

- 通常: 20〜40ページを約10分撮影→約10分分析→約130分閲覧。
- リスニング: 30分録音の間に約10分撮影→両入力終了後に約10分分析→約110分閲覧。
- 両方150分を電池試験条件にし、終了時10%以上を初期目標とする。150分で自動終了しない。
- グラスWi-Fiなし、スマホ4G/5G・ロック中、端末間の近距離通信を維持する。
  現場PC・常時稼働させる自前サーバ・テザリングは不要。
- GPT利用のための管理型クラウド中継を第一候補とすることは利用者回答で承認済み。
  既存FastAPIのsolver/検証処理を再利用候補にする。クラウドへの公開、課金設定、認証情報の
  新規作成は今回行わない。初回設定後の日常操作はグラスだけで完結させる。
- 利用者確認（2026-09-10）: Firebaseプロジェクトは未作成。既存Firebase環境を前提にしない。
  中継の配置先とアプリ認証をFS-63で選び、必要なクラウドプロジェクト・課金・秘密管理の
  初期準備から計画する。Google Cloud側の既存プロジェクト有無も未確認として扱う。

### 解答・入力・表示の契約

1. 全撮影終了後に大問を自動分類する。共通本文・全関連画像/図表・音声区間と小問の
   対応を保持し、小問/解答欄単位の結果を返す。独立大問の並列数は初期2。
2. `ProblemGroup` / `QuestionItem` は大問・小問・資料参照、`AnswerItem` は入力改訂と
   記入用全文・状態、`AnswerBundle` はセッション・改訂を照合できる解答一式を持つ。
   同じ問番号でもIDで区別し、入力変更後の旧結果を採用しない。
3. 解答本文は答案に記入する内容の全て、かつそれだけ。記号、単位、式、途中計算、
   場合分け、証明、理由、指定言語の文章、必要な作図を保持する。記述式数学では
   「証明せよ」の明記がなくても、答案として必要な導出を含める。教材的な解説、
   解き方の助言、自信度、内部推論ログを混ぜない。64文字等で切断しない。
   資料不足・未完成・形式未対応は答案とは別状態で表示する。
4. 検査を通った小問からグラスに保存する。現在位置を後着結果で動かさず、保存後の
   閲覧に通信を要求しない。スワイプは表示ページ、短タップは大問→小問の一覧。
5. 閲覧中のダブルタップ1回で終了確認、別の物理ダブルタップが3秒以内に来たら終了。
   CLOSEDと閲覧位置を先に永続保存し、ホーム画面を出さず実際に消灯する。
   通信待ちにしない。次回の再装着でアプリを起動し、モード選択を表示する。
   「前回の解答」は任意に開ける。終了直後の遅着結果で再点灯しない。
   一覧のダブルタップは一階層戻る。長押しを必須操作に割り当てない。
6. 解析中の中断、通信断、プロセス終了で入力・結果を混同しない。録音は無断再開しない。
   終了後はカメラ/マイク/不要な通信と常時点灯要求を解除する。
7. 採用済み画像と音声は入力中にスマホへ先行転送する。問題解析・ASR・解答生成は
   両入力終了後に始める。約10分の分析目標は入力終了後の残りの転送時間も含む。

### 撮影・省電力の改訂

- 採用方式は必要時プレビュー。通常は枠・案内を表示し、位置合わせが2秒成立しない時
  または前スワイプで要求された時に映像を表示する。既存HUDのイベント時描画を維持。
- 通常1枚、不鮮明な時だけ最大3枚から良好な全ページ画像を選ぶ。欠けた端は連写や
  画像生成で補わず、位置合わせを案内する。LED最小化を目的にしない。
- 実画像が見えてから3秒確認。プレビュー表示中なら縮小画像と併せて表示し、次の撮影は
  確認後。タップによる不採用はこの3秒間だけ。その他のタップは一時停止/再開。
- 不採用画像はAI入力から直ちに外し、置換画像の耐障害保存まで復元用に保持する。
- 紙なし/撮影済み同一ページから30秒進展なしならカメラ休止。録音は止めない。
- 常時プレビュー・カメラ間欠稼働・必要時だけ解答表示は比較候補。既定は必要時
  プレビュー＋選択中の解答常時表示。表示省略だけでカメラ省電力を達成したと扱わない。

### 試験形式から導く答案契約

参照対象は2026年度の公開問題・正解・出題意図。以下はアプリに必要な形式の整理であり、
実AIでこれらを解いた結果ではない。年度・科目・文理・大問・小問・解答欄を識別する。

| 形式 | 記入用の出力 | 解析・検証への反映 |
|---|---|---|
| 共通テストの選択式 | 解答欄に対応する選択記号/数字 | 選択肢の内容とマーク番号を混同しない。複数選択、順不同、枝番を保持 |
| 共通テスト数学 | ア・イ等の欄ごとの数値/符号/記号 | 一つの値が複数欄に分かれる場合も対応を維持。途中式は記入を求めない欄には出さない |
| 共通テスト英語リスニング | 問番号と選択答案 | 図表・選択肢と原音の両方を保持。ページ番号や撮影時刻だけで会話を切らない |
| 東大数学・記述式理科 | 結論に必要な式、論理、条件、単位、図 | 最終値だけの一致を合格にしない。導出の正しさ・必要十分性を採点 |
| 東大国語・論述 | 指定字数/解答欄に合う記述全文 | 字数、主語、因果、指定された根拠の要素を確認 |
| 東大英語 | 設問ごとに記号、和訳、要約、英作文等 | 大問全体を一律「記述式」にせず、言語/字数/語数/解答形式を小問ごとに保持 |

共通テストの公式ページは問題、正解、リスニング音声・スクリプトを別資料として公開する。
数学ⅠAの同一大問は複数ページに続く。公式PDFでもテキスト抽出で数字が崩れる例があり、
抽出テキストを画像より優先する契約にはしない。
[問題・音声](https://www.dnc.ac.jp/kyotsu/kakomondai/r8/r8_honshiken_mondai.html) /
[正解](https://www.dnc.ac.jp/kyotsu/kakomondai/r8/r8_honsiken_seikai.html)

東大の数学は解答に至る道筋の論理的・簡潔な表現を評価する。国語は記述式、英語は
要約・作文・和訳・読解と記号選択を含む。公表された「出題意図」を完全な模範答案や
詳細な採点基準として扱わない。記述答案の正誤・十分性には人による評価基準を作る。
[数学](https://www.u-tokyo.ac.jp/content/400239145.pdf) /
[国語](https://www.u-tokyo.ac.jp/content/400239144.pdf) /
[英語](https://www.u-tokyo.ac.jp/content/400239234.pdf)

2027年度選抜要項では文科の国語/地歴、理科の数学/理科に150分の枠がある。
文理・科目で時間が異なるため、150分は本アプリの耐久試験条件として保持し、全科目の
試験時間には固定しない。2026年度の問題資料と2027年度の要項を混同しない。
[2027年度要項 pp.7–8](https://www.u-tokyo.ac.jp/content/400243934.pdf)

`QuestionItem` に解答欄ID、形式、指定言語、字数/語数、必要資料参照を持たせる。
当面は既存の全文文字列を生かし、数式/表/作図が必要な時だけ順序付き答案ブロックを追加する。
作図は座標・線・ラベル等の検証可能なデータから表示し、画像生成で数学的根拠を補完しない。
表示幅を超える式は意味を保って分割し、指数・分数・行列を文字化けや縮小で済ませない。
未対応の図を黙って落とした結果をREADYにしない。問題ラベル/ページ番号は答案本文と分離する。

### GPTへの経路と採用判断

```text
グラス（撮影・録音・保存・操作）
  ⇄ Bluetooth ⇄ スマホ（ロック中の転送・ジョブ管理）
  ⇄ 4G/5G ⇄ 管理型クラウド中継（認証・秘密管理・GPT呼出し）
  ⇄ OpenAI API
完成した答案 → スマホ保存 → グラス保存 → 通信不要で閲覧
```

| 経路 | 判断 | 採用を決める証拠 |
|---|---|---|
| 管理型中継＋OpenAI Responses API | 第一候補。利用者が候補化を承認 | 画像込み一大問→小問答案、認証更新、モバイル断からの復旧、費用を実証 |
| Rokid標準AIのChatGPT | 比較候補を維持 | 任意の複数画像/録音を投入し、全文と小問IDをプログラムで受信できること |
| スマホから秘密キーでGPT APIを直接呼出し | 本番既定にしない | キーをAPKやグラスへ埋め込まない。端末に秘密キーを返すだけの中継も不可 |
| スマホ内ASR＋GPT API | 通信/誤認識の比較候補 | 原音との照合、重要語精度、待ち時間・熱・通信量が改善すること |
| スマホ内の完全ローカルAI | 追加評価 | 日本語・数式・図・論述の品質と20/40ページの時間/RAM/熱を実測 |
| グラス単体のローカルAI | 最後の比較候補 | 150分運用を妨げない実精度・メモリ・消費電力。GPT相当とは推定しない |
| Firebase AI Logic＋Gemini | 旧第一候補から比較候補へ変更 | GPTから黙って切り替えず、同一資料の結果を比較して選択 |

OpenAI公式はResponses APIで複数画像入力を案内し、APIキーをクライアントアプリへ
露出させないよう求めている。アプリのログイン用トークンとOpenAIの秘密キーは分離する。
[画像入力](https://developers.openai.com/api/docs/guides/images-vision) /
[認証](https://developers.openai.com/api/reference/overview#authentication)

調査時点の公式APIモデルでは `gpt-6-astra` を品質基準、`gpt-5.6-terra` を費用/速度の
比較候補とする。両方の画像入力・構造化出力は文書上対応。採用は同一の未使用問題で
評価して決め、最初から小問ごとの多段モデル振分けを作らない。両モデルの入力仕様は
text/imageなので、録音は別の音声認識工程を通す。否定、数値、話者対応などは原音照合も評価する。
アカウントからの利用可否・実料金・速度・正答率は未測定。出力上限や不完全応答を
途中で切った答案として採用しない。
[Astra](https://developers.openai.com/api/docs/models/gpt-6-astra) /
[Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra)

中継の配置候補はCloud Run。既存Python solverを小さな認証付き経路で再利用し、
秘密はSecret Managerへ置く。配置先・リージョン・予算・アプリ認証はFS-63で確定する。
ローカルSQLite/一時ファイルをクラウドの永続ジョブ台帳に流用しない。
入力digest＋モデル/プロンプト版のジョブID、所有者、状態、結果、利用量を永続管理する。
スマホの再接続は結果照会を先に行い、応答不明時の無条件再課金を避ける。
クラウド既定の要求timeoutは5分なので、約10分解析を一本の既定HTTP要求に依存させない。
永続ジョブの実行方式はFS-64で固定し、HTTP応答後のメモリ内スレッドだけに仕事を残さない。
[Cloud Run timeout](https://docs.cloud.google.com/run/docs/configuring/request-timeout) /
[秘密の管理](https://docs.cloud.google.com/run/docs/configuring/services/secrets)

Rokid公式は地域・アプリ版等により標準AIでChatGPTを選べると案内している。
これはGPTがグラス内でローカル推論される証拠でも、第三者アプリからAPIとして使える証拠でもない。
今回のCXR-L 1.1.1 AIDL検査ではAIキー/終了/アプリ復帰通知を確認したが、任意の
問題入力と解答テキスト返却の型付きメソッドは確認できなかった。`sendCustomCmd` 等の
存在だけで独自プロトコルを推測しない。別の公式AIUI経路まで非対応と断定しない。
[Rokid公式AI案内](https://global.rokid.com/blogs/academy-glasses/3-4-other-ai-features)

### 消灯・再装着の実現条件

- 終了確認は既存 `BackExitPolicy` の3秒窓を再利用する。別操作/フォーカス喪失で解除し、
  一つのダブルタップの二重配送を二回に数えない。一覧内のBACKは一階層戻る意味を保持する。
- 確定後はCLOSED/位置を耐障害保存し、カメラ・録音・閲覧通信・常時点灯要求を解除する。
  ホームへの `finish()` を先に呼ばない。消灯確認まで閉じた画面を保持する設計を試す。
  黒画面や輝度0のみで「消灯済み」とせず、Display OFFと外部目視を照合する。
- 消灯APIの第一調査対象はAndroid `DevicePolicyManager.lockNow()`。これは管理者の
  force-lock権限と端末機能が条件であり、現在のmanifestには用意されていない。
  初回設定として利用者が有効化できるかを実機確認する。画面ロックありでは再開に
  強い認証が必要になり得るため、既存ロックを勝手に解除せず、グラス操作だけで再開できるか確認する。
  SDKに文書化された消灯経路が別途見つかれば、権限負担の小さい経路を先に選ぶ。
- Accessibilityの画面ロック操作もAPIとして存在するが、公式の用途は障害のある利用者の
  操作支援。単なる消灯のための汎用回避策として既定導入しない。root/隠しAPI/
  adb power操作を日常運用の前提にしない。標準timeout待ちは即時消灯要件の合格にしない。
- 再装着の第一候補はスマホサービスが受ける `onWearingStatusNotify(false→true)` と
  `openApp`。現在の装着通知はログのみ。閉じたグラス側プロセスが生き続ける前提にしない。
  `is_spread` はつる開閉であり装着判定ではない。`getWearingSwitch` も名称だけで
  現在の装着状態の取得と判断しない。
- 終了時に装着中でも即座に再起動しない。終了後の非装着→再装着を観測して一回だけ起動する。
  同じ通知の重複、再接続時の古いtrue、つる開閉、着脱なしの消灯/点灯を区別する。
  スマホのサービス再作成時に状態を復元し、偽の着脱イベントを生成しない。
- 再装着でモード選択を表示。中断中資料/前回答案は任意選択し、カメラやマイクを自動再開しない。
  スマホはロック中、グラスWi-Fiなしでもこの一連が動くことを必須にする。
  起動通知/APIの存在だけでは合格にしない。失敗時のグラス手動起動は診断用であり、
  自動起動要件を満たしたことにはしない。

[Android lockNow](https://developer.android.com/reference/android/app/admin/DevicePolicyManager#lockNow()) /
[AccessibilityService](https://developer.android.com/reference/android/accessibilityservice/AccessibilityService)

### 実装順・検証

既存FS番号を維持する。次回はFS-59で既存途中成果物を確定し、FS-60の試験形式評価と
FS-61/62の消灯・装着能力ゲートを先に進める。実機がなくても端末不要の答案契約と
状態試験は進める。FS-63/64でGPT中継を小さく接続し、FS-65で数式/図の欠落を防ぐ。
続いてFS-12/36/47の記入用全文契約とローカル閲覧を完成させる。
FS-20/35/37/38で大問と小問・AI・結果保存、FS-08/09/10/42/53で終了・再開を統合し、
その後に撮影/録音/転送を接続する。M0の実機能力検査は最終採用ゲートとして残すが、
端末不要の状態・契約・アダプター実装を止める依存とはしない。

- 1000字/数式/長単語の全文復元、補足解説混入0、操作応答p95 150ms以内。
- 記述式数学の途中式・場合分け・必要な図、論述の字数・言語条件を答案として検査。
  試験形式別に採点し、記号一致率を記述式全体の正答率として報告しない。
- 小問・解答欄・ページ跨ぎ・共通図・音声条件の脱落/入れ違い0。
- 未使用100問以上の客観式95%以上、ASR重要語98%以上の初期目標を保持。
  回答率・保留率も併記。20/40ページの新負荷を追加し、旧小規模目標を黙って緩めない。
- 実写200ページで欠けた画像の誤採用0、良好な資料の初回採用95%以上。
  紙/動画単位で学習と評価を分け、量子化した配布物も同じ評価へ通す。
- 録音30分、3秒境界、近接した別入力、終了直後kill、再起動50回、通信断を検証する。
- 終了ダブルタップ2回→ホーム表示なし→Display OFF→外す→再装着→モード選択を50回。
  初期目標は終了確定後1秒以内の消灯、再装着通知後3秒以内の操作可能状態。
  これらは未測定の受入目標。装着センサー/通信遅延を含む実時間も別途記録する。
  装着したままの終了後再起動0、遅着答案による再点灯0、録音自動再開0を確認する。
- 電池は工程別の稼働時間と消費電流の感度分析を先に行い、最後に実機で150分測定。
  エミュレーターや合成データの結果を実機電池・実AI正答率の実測と呼ばない。

以下は先行計画。矛盾する「確認3秒は必ずカメラ停止」「入力中に先行OCR/ASR」
「閲覧タップで次問」「ダブルタップ1回で閲覧終了」「終了直後に選択画面」
「Geminiが第一候補」の記述には上記改訂を適用する。

## Overview

Implement the accepted capability map in risk order. Documentation truth and
fail-closed contracts land before building or connecting a device.

## Architecture Decisions

- Normalized, orientation-corrected PNG is the authoritative server image.
- `ROKID_REAL_MODE=1` is fail-closed and never silently selects placeholders.
- CUSTOMVIEW operator tap is unverified; current supported controls are on the
  phone until a glasses app is physically proven.
- Camera/privacy indicator state is externally observed, never modified or
  inferred from SDK callbacks.
- CXR-L remains pinned to 1.1.1 for this run; 1.1.2 is a separate upgrade.

## Task List

See `tasks/todo.md` for acceptance criteria and verification commands.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Existing user edits overlap safety docs | High | Patch only targeted claims; inspect every diff |
| Old tap assumptions remain in code/HUD | High | Repository-wide search plus focused JVM tests |
| Non-ASCII checkout blocks Gradle | High | Create a clean ASCII-path build copy/worktree after source verification |
| Unknown photo callback state | High | Fail closed; no automatic retry in the same generation |
| APK signature/vendor installer mismatch | High | Inspect signature and hash before device access; preserve callback evidence |
| Physical device unavailable | Medium | Stop at read-only inventory and report no-go without guessing |

## Open Questions

- Physical device results cannot be known until the static gates pass and a
  device is attached.

## Extension: Glasses app operation — `glasses-input`

The user accepted `CAPABILITY-MAP-glasses-app-operation.md` and
`SPEC-glasses-input.md` after the direct glasses-side probe proved physical
KeyEvents reach the foreground Activity. This extension does not discard the
incomplete controlled-device validation above; it changes the next supported
control surface from phone-only to a glasses app, then returns to the same
capture/LED/server acceptance gates.

### Architecture decisions

- Calibrate official system broadcasts and Activity KeyEvents before choosing
  a deduplication window or production gesture mapping.
- Keep callbacks as data sources only. A pure-Java normalizer owns ordering,
  correlation, deduplication, and unknown-event handling.
- Emit normalized, side-effect-free actions. Capture/navigation semantics belong
  to later capability modules.
- Observe broadcasts without `abortBroadcast()` until target-firmware behavior
  proves that consuming an ordered broadcast is safe.
- Preserve exact hardware tuple, APK hash, event names, and timing, but never
  record content or credentials.

### Dependency graph and build order

```text
GI-1 dual-path calibration
  -> measured event pairs and timing
  -> GI-2 pure-Java normalization/deduplication
  -> GI-3 lifecycle hardening and final hardware acceptance
```

### Task list

Detailed acceptance criteria, verification commands, dependencies, and likely
files are appended to `tasks/todo.md` under `glasses-input`.

### Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| One gesture reports both a broadcast and KeyEvent | Duplicate destructive action later | Calibrate both streams, then prove one normalized result in unit and hardware tests |
| Firmware key names differ from physical semantics | Wrong operation mapping | Record exact gesture order and raw/app events; raw key name never defines business meaning alone |
| `abortBroadcast()` suppresses system behavior | Launcher or safety control regression | Do not abort in this module; measure before any future change |
| App loses focus or receiver lifecycle leaks | Missed or duplicated input after restart | Explicit register/unregister lifecycle plus restart hardware test |
| Unknown future action is treated as known | Unexpected side effect | Exhaustive allow-list; unknown actions are content-free diagnostics only |

### Open questions resolved by GI-1

- Which official broadcast and KeyEvent pairs describe the same gesture on
  build `1.25.012-20260901-150201`?
- What is the smallest observed timing bound that safely correlates those pairs?
- Which keys remain system-owned and must stay unconsumed?


---

<a id="glasses-autoscan-listening-20260906"></a>

# 改善計画：グラスだけで操作する自動資料スキャンと同時リスニング

**着手資料:** [実機前の準備ノート](../docs/fast-scan-preflight.md#start)。設計見直し、30の操作例、14ケース18問、検査コマンドと実機試験票を保存済み。FS-02は完了、FS-01は合成データ等の準備まで完了。アプリ機能と実機評価は未着手。

**追加調査（2026-09-07）:** [外部6アプリの参照例](../docs/fast-scan-external-examples.md)を[設計判断](#external-app-design)と追加評価X01〜X06へ反映済み。追加評価は未実行。

Status: **詳細計画・実装前**。更新日 2026-09-07。**グラスはWi-Fi未接続、スマホはモバイル回線あり。現場PC・自前サーバは不要とする。** 初回調査対象 HEAD:
56f82c7df3f2641c2e123abbacd8937562140ba5、branch: agent/real-device-test-prep。

ユーザーの今回の要求と、追加回答「資料の問題＋読み上げ音声を合わせて解答、
録音しながら資料をスキャンする必要がある」、さらに再開時の訂正
「完全なオフラインではなく、グラスにWi-Fi接続はできないがスマホはモバイル回線でインターネットへ接続できる」を反映した提案。
**前回草案の完全オフライン解答必須・スマホ内の大きなモデルを中心とする方針を撤回する。**
スマホから外部AIを利用できる。PCや利用者が運用する専用サーバは現場構成に含めない。
下の設計値・新APIは実装済みでも実機検証済みでもない。
既存の未完了タスクを残し、この拡張の作業を [todo.md](todo.md#fast-scan-tasks)
の FS-01 以降で管理する。先行する計画の電話操作・自動化禁止は旧フェーズの範囲であり、
今回の自動化要求を妨げるプラットフォーム制約として扱わない。

## 1. 目指す使用体験と必須条件

**開く → モードを選ぶ → 用紙を見る → 自動撮影 → 撮ったページを3秒確認 →
次ページ → 撮影終了 → AI解答 → 閲覧終了。日常操作をグラスだけで完結させる。**

| ID | 必須条件 | 完了を判断する方法 |
|---|---|---|
| R1 | 起動時に「通常撮影」「リスニング」を選べる | コールド起動・再表示の両方で選択画面へ到達。前回完了後に古い解答へ戻らない |
| R2 | ページ全体・静止・読み取り可能な画質を検知して自動撮影 | 正常経路にシャッター用タップが存在しない |
| R3 | 撮影した実画像をグラス上に3秒表示 | 実際の描画完了から3000ms以上。未描画時間・別画面の時間を数えない |
| R4 | 3秒確認中の1本指タップは撮り直し | 当該ページの登録を取り消し、同じページ番号で再撮影する |
| R5 | 無操作なら確定して次ページの自動検知に移る | 通信完了を待たず、端末への永続保存が成功すれば進める |
| R6 | 1本指ダブルタップで資料撮影を終了 | 最後の未確定ページ・撮影中の画像を落とさず、以後新しい撮影を始めない |
| R7 | リスニングはモード決定直後から撮影・確認・ページ送り中も連続録音 | 読み上げの先頭・途中・末尾を含む。最初のダブルタップで録音が止まらない |
| R8 | 撮影終了後は録音のみ継続し、次のダブルタップで録音終了 | 異なる2回の物理ジェスチャとして識別。同じイベントの重複配送で両方終わらない |
| R9 | 資料全ページと読み上げ音声を合わせてAIが問題単位で解答 | 資料だけでは答えられない検証問題に、録音内容を根拠として解答できる |
| R10 | グラスに問題ごとの完全な答えのみ表示 | 64文字切断・画面外欠落・解説の混入なし。長い答えは全文をページ分割 |
| R11 | 閲覧でダブルタップ2回→ホームを出さず消灯→再装着でアプリのモード選択 | CLOSEDを保存。装着したまま再起動せず、着脱後にグラス操作だけで再利用できる |
| R12 | 誤操作・通信断・強制終了で資料や録音を混同しない | セッションID、ページ改訂、音声連番、解析入力の版を照合して復旧する |
| R13 | グラスWi-Fiなし＋スマホのモバイル回線で完走する | 初回準備後はスマホをロックしたまま操作0回。PC・自前サーバ・テザリングを使わず解答を返す |

「答えのみ」は解法・根拠・宣伝・自信度の常時表示を省くこと。
証明や理由を記述すること自体が設問の要求なら、その記述は答えに含む。
「完全」は全文・小問・必要な条件や単位を欠かさない意味であり、
AIの正答率100%を保証する意味にはしない。材料不足は答えを捏造せず、別の状態表示にする。

初期設定・アプリ導入と毎回の現場操作を分け、日常はスマホ操作0回を必須にする。
**基本構成はグラス＋ポケット内スマホ＋スマホの4G/5G経由のAIサービス。**
グラスはWi-Fiに接続せず、資料・音声・解答をスマホと交換する経路を別に確保する。
Bluetooth/CXR転送が第一候補だが、帯域と連続録音との同時動作は未検証。
スマホのインターネット接続だけでは、この端末間リンクが成立する証明にならない。
既存FastAPIは参照実装・評価・任意の互換経路として残し、利用者のサーバ運用を必須にしない。
AIサービス側の管理されたクラウド処理は利用できるものとして計画する。

| 接続条件 | 必要な動作 |
|---|---|
| **本番: グラスWi-Fi未接続、スマホ4G/5G、Bluetooth接続** | 資料と音声をスマホへ転送し、スマホが外部AIへ送信。答えをスマホ経由でグラスへ返す |
| モバイル回線が遅い/一時切断 | 撮影・録音・保存を継続し、AI送信を再開可能にする。「スマホ接続待ち」と「AI通信待ち」を区別 |
| Bluetooth切断、スマホはオンライン | グラス内へ保存して再接続待ち。スマホの回線でグラスの未転送画像を取得できるとは扱わない |
| 両方の通信が利用不可 | 保存と取得済みの解答閲覧を続ける。新規AI解答は復旧待ち。端末内AIは追加候補 |
| 将来、端末間Wi-Fiが許容された場合 | 任意の高速転送として別評価。今回の必須経路・受入試験をテザリングへ置き換えない |

本番試験ではグラスのWi-Fiを未接続にし、スマホのWi-Fiも切ってモバイル回線を確認する。
一時的なモバイル通信断の復旧試験は必要だが、圏外で全問解答することは今回の必須条件ではない。


<a id="external-app-design"></a>

### 外部アプリの事例を設計と評価へ反映する（2026-09-07追加）

ユーザーの追加要望に従い、内部の操作例だけで設計を決めない。
[外部事例の調査記録](../docs/fast-scan-external-examples.md)に、公式の製品資料と公開実装を根拠として、
確認した挙動、採用判断、グラスへ移す際の制約、対応するFSを記録する。
以下はその資料から導く本アプリの設計判断であり、他アプリで本要件が実現済みという意味ではない。

| 参照事例 | 計画への反映 | 採用しない前提・実証が必要な点 | 検証先 |
|---|---|---|---|
| E01 Adobe Scan / E02 Apple Notes | 自動撮影と撮影後の修正を一続きにする。3秒の後でも過去ページの取り直し経路を残す | スマホの編集画面や毎ページの保存タップを日常操作に持ち込まない。3秒はユーザー要件 | FS-24/26/39、X01 |
| E03 OSS Document Scanner | 検出したことと、安定して撮影可能なことを分ける。撮影中・確認中の再発火を抑える設計を比較する | 他機種の閾値・実装言語・依存をそのまま移さない。対象機の画質、熱、メモリで判断 | FS-22/23、X02 |
| E04 Notability | ページ改訂と録音サンプル位置を対応付け、後から必要な原音をたどれるようにする | 同時刻のメモと録音の対応は、問題と音声の意味的対応の証明ではない | FS-28/34/35、X03 |
| E05 Seeing AI | 撮影できない理由を短い具体的な案内にする。外周検出の内部数値を操作画面へ並べない | 音声案内はリスニングを妨げ得るため常時発声を採用しない。まずHUDの短文で評価 | FS-22/23/40/46、X04 |
| E06 Joplin | ローカル保存と同期状態を分け、画面消灯時の転送を独立した受入項目にする | ローカル保存・後日同期の成功を、ロック中転送やスマホ操作0回の証明にしない | FS-05/25/41/42、X05/06 |

比較は画面の模倣や機能追加の競争を目的にせず、R1〜R13に対する改善で判断する。
外部事例にない「実画像を3秒確認」「撮影と録音を異なる2回のダブルタップで終了」は維持する。
Wi-FiなしのBluetooth媒体転送、同時録音、Global Hi Rokidとの共存は引き続きM0で実証する。

実装着手時には、参照事例ID・出典の版/取得日・採用/変更/見送りの理由・対応試験を残す。
依存やコードを実際に導入する場合は、その時点で版とライセンスを確認する。
現在の30操作例と14ケース18問は内部の合成資料のまま保ち、外部アプリの試験結果へ呼び替えない。
外部事例から導いた追加評価X01〜X06は[準備ノート](../docs/fast-scan-preflight.md#external-derived-cases)で管理する。

## 2. 現状調査から分かった差分

以下の「実装確認」は2026-09-06のソース確認。「過去実測」は当日の再試験ではない。
参照先の行番号は調査HEAD基準で、実装開始時にはシンボル名でも照合する。

| 発見 | 根拠 | 計画への反映 |
|---|---|---|
| グラス直接撮影の土台は既にある | DocScanGlassActivity / GlassCamera、glassdoc 0.6.0 / 6 | 既存の :glassdoc + :relaycore を改良する。以前削除した重複パイプラインを作り直さない |
| 自動撮影は現在無効 | DocScanController.startAutoCapture (1492)、startAutoCaptureNow、shouldAutoCommit (1730) は無効化された実装 | 旧3連写コードのスイッチを戻すだけでは要件を満たさない |
| 既存のページ全体判定は文字枠の端接触を使う | PageFraming (12–23) | 余白・図だけのページ・外周の欠けを見抜く紙面形状検知を追加。既存判定は補助に残す |
| 現在の撮影は1回ごとにカメラを開いてJPEG1枚を取得 | GlassCamera.captureOnce (74)、configureSession (147) | 低解像度連続解析と静止画撮影の経路が必要 |
| タップは撮影/登録、ダブルタップはアプリ終了確認 | CaptureActionRouter (42–103)、DocScanGlassActivity.onBackPressed (155) | 新しい状態別操作に変更。BACKを通常の画面終了処理へ二重配送しない |
| 同種アクションを970ms以内で抑制する | GlassesInputNormalizer.emit (145)、MEASURED_CORRELATION_MILLIS | 相関窓と二重配送防止を分離。別の物理操作まで消さない。実機で発現する頻度は未計測 |
| 描画要求の直後に「表示済み」と通知する | GlassesCaptureSurface.show (138)、HudView.set → invalidate | onDraw後の表示通知＋可視性検査に改める。要求の受付だけで3秒を開始しない |
| 撮影画像の表示がOCR完了待ち | DocScanController.handlePhoto (992) → stageCaptureReview | JPEG受信後すぐ縮小プレビューを表示し、OCRを別処理にする |
| ネットワーク処理が操作用の直列実行器を占有する | DocScanApiは同期HTTP、readTimeout 4分 / callTimeout 5分。finishReadingNowも同じ直列実行器 | 状態遷移と通信を分離し、録音停止・終了・取り直しを待たせない |
| グラスアプリに録音機能・権限がない | glassdoc/src/main/AndroidManifest.xml、DocScanGlassActivity、DocScanApi | マイク権限・連続録音・保存・再送・残容量表示まで一式追加 |
| グラスのセッション作成は written / mark 固定 | DocScanApi.createExamSession (103) | モード選択をサーバへ伝える。記述解答や混在資料をマーク式に固定しない |
| サーバに音声取り込みとテキスト連結はある | main.exam_upload_audio (2019)、_exam_prompt_context (1218) | 再利用する。ただし連続音声用の分割保存、終了確定、時刻対応は追加 |
| 音声は単一ファイル置換、アップロード上限15MiB | main (141)、exam_upload_audio (2039–2067) | チャンク連番と完了manifestを導入。単に上限だけを引き上げない |
| ASR未設定・例外時に空文字へ退避できる | transcribe_audio (36–60) | リスニングの本番解析で音声欠落を隠さない。実ASRと準備状態を導入 |
| 解答を最大64文字に切断する | solvers/llm_adapter.py (100–112)、registry.py (75) | 完全な答えを保存し、表示時にだけ分割。上限超過も黙って切らない |
| 現在の解答画面は答え・解法・根拠・注意を統合 | glasses_view.build_review_view (514)、_review_lines | 新しい answer-only 表示を追加し、既存クライアント互換を保つ |
| 長い文字列が画面外へ出る | HudView.onDraw (87) は1行ずつdrawText、サーバは文字幅で折り返さない | 実際のフォント・表示幅で折り返す。サーバ3論理行＝実画面3行とは限らない |
| 問題の画像入力は基本的に先頭ページ1枚 | solvers/base.Question.image_path、main.exam_finalize_reading (2324–2348) | 複数ページの問題に、関係する全ページ画像と領域を渡す |
| 再起動時の設定と終了の扱いが不十分 | Activity.onCreateはIntentのserverをconfigureへ渡す。保存値はあるがnull時の経路がない。onNewIntentなし | 設定の永続化、起動モード選択、途中復旧、完了済みの扱いを明文化 |
| 文書索引やコードコメントが古い | 調査開始時のdocs/README.mdはglassdoc 0.1.0や+2EVを記載。現在は0.6.0で露出補正は撤回済み | 今回は索引の版数説明を訂正。実装時に残るコメント・サーバのphone表示・sdk_hintを揃える |
| 自動チェックに既知の失敗がある | 今回 pytest: 424 passed / 1 failed。索引未登録の未追跡ツール文書57件 | 本体文書の検査を弱めず、生成物との境界を直してから以後の合格判定を行う |

実機前準備で上表の文書検査はFS-02として解消した。変更前の結果は調査履歴として残す。
さらに旧eval_exam.pyが単一問題・音声なし・正解文字列の包含一致を許すことを確認した。
両入力用の合成ケースとeval_fast_scan.pyを追加し、実媒体の品質判定とは分けた。

参照パス:
[グラスActivity](../android-relay/glassdoc/src/main/java/dev/rokid/docscanglass/doc/DocScanGlassActivity.java) /
[カメラ](../android-relay/glassdoc/src/main/java/dev/rokid/docscanglass/doc/GlassCamera.java) /
[画面](../android-relay/glassdoc/src/main/java/dev/rokid/docscanglass/doc/HudView.java) /
[表示通知](../android-relay/glassdoc/src/main/java/dev/rokid/docscanglass/doc/GlassesCaptureSurface.java) /
[共有制御](../android-relay/relaycore/src/main/java/dev/rokid/docscanrelay/DocScanController.java) /
[HTTPクライアント](../android-relay/relaycore/src/main/java/dev/rokid/docscanrelay/DocScanApi.java) /
[入力](../android-relay/glassinput/src/main/java/dev/rokid/docscanglass/input/GlassesInputNormalizer.java) /
[サーバ](../app/main.py) / [ASR](../app/transcribe.py) /
[解答変換](../app/solvers/llm_adapter.py) / [サーバHUD](../app/glasses_view.py)。

### 過去の実機証拠をどこまで使うか

- 2026-09-04、RG-glasses / build 1.25.012-20260901-150201 / Android 12 API 32:
  camera2のJPEG7枚、4032×3024、785–1380ms。Wi-Fiで /health 到達96–197ms。
  これは撮影能力と到達性の証拠であり、自動認識・録音同時動作・全工程の速度ではない。
- 入力プローブでは1本指タップ・スワイプ・ダブルタップのKeyEventを確認済み。
  ダブルタップはNOTIFICATIONマーカー後のBACKとして観測された。
- つるを閉じるとassistserverがthird_appを終了させる。onDestroyの実行は保証されない。
  前景サービスを追加すればこの終了を回避できる、とは仮定しない。
- 以前のメモリ不足は118MiB程度のRSSで発生した条件がある。固定の安全上限とはせず、
  同じ端末で撮影＋OCR＋録音＋描画の最大使用量を測る。
- +2EVは4回連続のタイムアウトを起こして撤回された。今回はその変更を復活させない。
- 2026-09-05の0.6.0はローカル検証242件・ビルド・lint成功の記録があるが、
  そのAPKの実機完走は未確認。
- 進捗記録にはCXR-L openApp成功300ms、前景Activity確認の追記がある。
  古い「openApp未確認」記述と区別する。SDK経由インストールの成功とは混同しない。

詳細と当時のハッシュは
[既存進捗の2026-09-04/05部分](../.agents/progress/glasses-input-and-real-device-prep.md) と
[一次情報索引](../docs/glasses-primary-sources-2026-09-03.md) を参照する。
今回、新しい実機操作・撮影・録音は実施していない。

## 3. モジュール境界と採用構成

以下は今回の**提案する能力マップ**であり、以前の承認済みマップを書き換えたものではない。
IDはタスクと仕様追跡で固定する。Gradleモジュールをすべて新設する意味でもない。

| Module id | 責任 | 依存 |
|---|---|---|
| session-lifecycle | セッションID、モード、終了・中断状態、端末への永続保存 | — |
| glasses-gestures | 物理入力の正規化、重複排除、gesture ID | — |
| page-detection | 紙面外周、静止、画質、新ページ判定 | — |
| audio-capture | 連続録音、サンプル位置、分割ファイル、音声状態 | session-lifecycle |
| scan-review | 撮影、3秒確認、取り直し、最後のページ確定 | session-lifecycle、glasses-gestures、page-detection |
| material-sync | グラス↔スマホの転送、再送、版管理、終了manifest | session-lifecycle |
| phone-runtime | スマホの背景実行、正規化PNG/音声/ジョブの保存、モバイル通信・AI接続管理 | material-sync |
| multimodal-solving | 設問分割、音声認識、外部AIへの画像＋音声入力、全文解答の検証 | phone-runtime |
| answer-reader | 全文解答の表示、前後移動、閲覧終了 | glasses-gestures、multimodal-solving、session-lifecycle |

基本のデータ経路:

~~~mermaid
flowchart LR
  G["グラス: カメラ・マイク・操作・画面"] --> L["端末内: ページと音声を保存"]
  L --> T["Bluetooth / CXR転送を実証"]
  T --> S["ポケット内スマホ: 保存・OCR・音声区間・ジョブ"]
  S --> N["スマホのモバイル回線"]
  N --> A["外部AI: 資料画像と読み上げ音声を統合"]
  A --> Q["スマホ: 問題ID・全文・入力版を検証して保存"]
  Q --> T
  T --> R["グラス: 問題ごとの完全な答え"]
  N -. 通信断 .-> W["スマホの保存キューで復旧待ち"]

~~~

:glassinput、:pagequality の純Java境界と、:relaycore の保存/HTTP資産を活かす。
DocScanControllerを一括で置き換えず、状態遷移、録音、同期、解答閲覧の責任を
縦の機能単位で切り出す。電話CXR-L経路のCUSTOMVIEW入力を一斉に有効化しない。
電話側はMainActivityから背景Serviceへ処理寿命を移す。DocScanApiを必須依存とせず、
DocScanBackendインターフェイスのPhoneBackendと、互換用のHttpBackendを分ける。
PhoneBackendが端末保存とジョブを担当し、AI呼び出しはCloudAiProviderへ分離する。
「スマホ側が管理する」ことと「推論もスマホ内で実行する」ことを区別する。
Pythonの既存問題分割/PNG正規化/解答契約は参照用golden fixtureにし、必要な部分のみ
Androidへ移植する。FastAPI・uvicorn一式やTermuxを現場で起動する手順は基本構成にしない。

## 4. 画面と操作を先に固定する

| 状態 | 表示例 | タップ | 前/後スワイプ | ダブルタップ |
|---|---|---|---|---|
| モード選択 | 通常撮影 / リスニング | 選択中のモードを開始 | 選択を移す | アプリを閉じる |
| 自動検知 | P03 枠に資料を入れる / 静止してください | 撮影を一時停止/再開 | 後: 直前ページの確認へ。前:通常は無操作 | 資料撮影終了を要求 |
| 撮影中 | P03 撮影中 | 取り直し要求を予約 | 無操作 | 新規撮影禁止にして、実行中の1枚の結果を待つ |
| 3秒確認 | 実際の写真 / P03 / タップで撮り直し | この版を不採用にして取り直す | 後: 確認を延長、再開時は新たに3秒。前:無操作 | 最後の写真として終了予約 |
| 取り直し待ち | P03 撮り直し / 枠に資料を入れる | 一時停止/再開 | 後: 直前の保存済み画像へ戻る | 撮影終了要求。未解決ページがあれば確認へ |
| 録音のみ | 録音中 05:32 / 撮影終了 8ページ | 音声上の目印を付ける（追加機能） | 通常は無操作 | 録音終了、末尾データを保存 |
| 解析待ち | 資料と音声を解析中 / 3/12問 | 通常は無操作 | 完了済みの答えがあれば表示へ | セッションを中断保存して選択画面へ。破棄しない |
| 解答閲覧 | 問3(2) / 答えの本文 / 2/4 | 次の問題の先頭 | 次/前の表示ページ。問題境界も往復可能 | 閲覧終了して選択画面へ |
| 復旧が必要 | 送信待ち5件 / 再接続を待っています | 明示的な再試行 | 保存済み結果の確認 | 中断保存して選択画面へ |

通常経路の操作はモード選択、必要な取り直し、終了、解答移動だけ。
「撮影準備」「登録」「スマホで完了」は出さない。長押しは既知のシステムAI起動と
競合するため必須操作に割り当てない。スマホ専用UIの説明をグラスへ流用しない。

### 状態遷移

下図は主な画面遷移の概略。実装ではcapture phase、audio phase、completionを別に保持する。
リスニングで録音を終了してから写真を取り直しても、audio=ENDEDを保持して録音を無断再開しない。
詳細な競合例は準備ノートのS16/S17に従う。

~~~mermaid
stateDiagram-v2
  [*] --> MODE_SELECT
  MODE_SELECT --> SCAN_NORMAL: 通常撮影
  MODE_SELECT --> REC_STARTING: リスニング
  REC_STARTING --> SCAN_LISTENING: 音声サンプル受信を確認
  SCAN_NORMAL --> REVIEW_3S: 自動撮影
  SCAN_LISTENING --> REVIEW_3S: 自動撮影・録音継続
  REVIEW_3S --> SCAN_NORMAL: 無操作で確定・通常
  REVIEW_3S --> SCAN_LISTENING: 無操作で確定・リスニングの音声状態を保持
  REVIEW_3S --> RETAKE: タップ
  RETAKE --> REVIEW_3S: 同じページを自動再撮影
  SCAN_NORMAL --> FINISH_PENDING: ダブルタップ
  SCAN_LISTENING --> FINISH_PENDING: ダブルタップ
  REVIEW_3S --> FINISH_PENDING: ダブルタップ
  FINISH_PENDING --> ANALYZING: 最終ページ確定・通常または音声終了済み
  FINISH_PENDING --> LISTENING_ONLY: 最終ページ確定・録音中
  FINISH_PENDING --> AUDIO_FINALIZING: 別の第2ダブルタップ
  LISTENING_ONLY --> AUDIO_FINALIZING: 次のダブルタップ
  AUDIO_FINALIZING --> FINISH_PENDING: 音声保存済み・画像確認が残る
  AUDIO_FINALIZING --> RETAKE: タップで取り直し・音声終了処理は継続
  AUDIO_FINALIZING --> ANALYZING: 音声・ページのmanifest確定
  ANALYZING --> ANSWER_REVIEW: 検証済み解答
  ANSWER_REVIEW --> MODE_SELECT: 閲覧終了を永続保存
~~~

図のFINISH_PENDINGは内部処理状態。最後の写真が未確認ならその画像を表示したまま
3秒を保証し、その後「撮影終了・録音中」を表示する。撮り直し中のダブルタップは
未解決ページを黙って落とさず、保留理由と確認対象を示す。

### 3秒とダブルタップの競合を解く契約

1. 写真ID・ページ改訂・表示generationが一致し、画像デコード成功・画面可視・描画完了を
   満たした時刻をreviewShownAtとする。onDraw完了だけで物理表示を断言せず、利用可能ならフレーム完了通知も使い、実機の表示時間を外部観察する。単調増加時計で3000msを測る。
2. 可視性を失った場合はカウントを無効化。戻ったら同じ写真を新たに3秒表示する。
   つる折り・強制終了から復元した未確定画像も自動アップロードせず再表示する。
3. 入力は配送時刻ではなく取得時の時刻も持つ。期限前に始まった接触を先に裁定し、
   期限とタップが競合した場合は取り直しを優先する。
   確定後に配送された入力は、取得時刻と表示履歴で対象ページを特定し、改訂によって旧結果を無効化する。
   次ページや次セッションのタップとして扱わない。未決着入力の待機上限は実測して決め、無期限に確定を待たせない。
4. 端末が完成済みENTER/BACKを出すならそれを使う。別のファームウェアが単タップを
   先に出す場合のみ、計測したダブルタップ判定時間を使って単タップの確定を待つ。
   根拠なく一般的な300msを固定しない。
5. 終了要求は1つのgesture IDで1回だけ処理。撮影終了に使ったダブルタップの残りの
   UP/コールバックを、録音終了として再利用しない。新しい接触の開始まで識別する。
6. 確認中にダブルタップされた最終画像は、見えた時間を合計で削らず、必要な確認を終えて
   確定する。最後の画像を落として解析へ進めない。
7. 終了予約後に取り直しされた場合は終了予約を解除し、同じページを撮り直す。
   終了後の録音のみ画面から後スワイプで撮影へ戻す機能は追加機能として別タスクにする。
8. 終了時点で0ページなら資料解析は開始しない。通常は撮影へ戻る。
   リスニングの録音は失わず、撮影へ戻るか中断保存できる。

## 5. 自動撮影の具体策

### 5.1 低解像度解析と高解像度撮影

- 初期候補はcamera2のYUV解析フレーム（例640×480、評価処理5–10fps）＋JPEG静止画。
  対応するサイズ・フレームレート・同時ストリームは実機で列挙して選ぶ。
- YUVの最新フレームだけを処理し、古いフレームは捨てる。処理待ちを積み上げない。
  OCRや高解像度Bitmap生成を毎フレーム実行しない。
- まず端末内の輪郭/四辺形追跡を評価し、冊子・反射・白い机で不足する場合のみ
  小型の紙面検出モデルを比較する。OpenCV等の依存追加もAPKサイズとメモリを測って判断。
- 射影変換したページ候補で、四辺の余裕、被写体ブレ、明るさ、白飛び/反射、
  手や物の遮蔽、用紙の占有率を評価する。
- 3〜5フレーム、約500〜800msの安定を初期値にする。各閾値は評価用資料で調整し、
  明るいB5/A4縦だけに過剰適合させない。
- 撮影の直前から完了まで1枚だけが実行中になるよう制限。
  撮影後の画像も品質確認し、プレビュー段階の判定を鵜呑みにしない。
- 紙面確認中の3秒はカメラストリームを止め、静止画像を表示する。
  再開コストを測り、必要なcapture sessionの再構成を実機で検証する。

camera2の複数ストリームはAndroid公式資料に構成例があるが、
このRokidの同時録音を含む動作保証にはならない。
[Android公式: 複数ストリーム](https://developer.android.com/media/camera/camera2/multiple-camera-streams-simultaneously)

既成のML Kit Document Scannerは専用の撮影・確認ActivityとGoogle Play servicesからの
モデル/UI取得を含み、最低RAM条件もある。今回のグラス上の独自操作を構成する
低レベル検出器としてそのまま採用する根拠はない。
既存の同梱版日本語OCRとは別製品として扱う。
[Google公式: Document Scanner](https://developers.google.com/ml-kit/vision/doc-scanner/android)

### 5.2 同じページを何度も撮らない

単純な待ち時間とOCR文字列類似度だけで判定しない。
確定した紙面の画像指紋・レイアウト・紙面追跡と、ページが動いた/視野から離れた
イベントを組み合わせて次の撮影を許可する。白紙、同じ見出しの連続問題、
片側だけ変わる見開きも試す。

同一内容の別紙を意図して追加する場合はグラス上で「同じページを追加」を選べる。
OCRが0文字でも図・数式・白紙を区別し、図だけを自動削除しない。
白紙扱いのページもmanifest上のページ数を残し、設問抽出の対象から外す理由を記録する。

### 5.3 撮り直しと画質が悪い場合

自動登録候補にするのは外周・画質の合格画像だけ。
明確な欠けやブレは3秒確認で勝手に確定せず、欠けた方向・「少し離す」
「明るい場所へ」など次に取る行動を短く表示する。
撮り直しではページ番号を増やさず改訂番号を進める。
保存済みページの置換中に失敗しても、前の確定版を壊さない。

暗所の改善候補は、照明・姿勢ガイド、解析用画像だけへの限定したコントラスト調整、
露出状態の観察、必要なら文書モデルによる補助。原本PNGは保持する。
固定の+2EV、過剰なシャープ化、文字を書き換える画像生成を採用しない。

自動検知にはカメラ稼働が必要なので、その間は通常のプライバシー表示に従う。
撮影後レビュー、音声だけの待機、解析、解答中は撮影要求を出さず、
実際の消灯は独立した目視で確認する。音声状態とカメラ状態を分けて表示する。

## 6. リスニング：録音の連続性を中心に設計する

### 6.1 開始と終了

リスニング選択時にローカルsession IDを作り、マイクを開始する。
実際に音声サンプルを受け取ってから「録音中」と表示し、自動撮影を始める。
スマホ接続や外部AIの応答を待ってから録音する設計にはしない。
カメラの開閉・再撮影・OCR・HTTPとは別の録音スレッドを使う。

AudioRecordを録音中ずっと維持し、保存ファイルだけを分割する。
1〜2秒ごとのPCMブロックをまず耐障害保存し、圧縮やASR用の10〜30秒窓はその後で作る。
ファイル分割のたびにマイクを停止・再開しない。
サンプルレート、チャンネル、形式は対応確認後に固定し、必要な変換は1箇所で行う。

第1ダブルタップ後も録音継続。第2ダブルタップでは入力を閉じる位置を記録し、
バッファに残る音声を排出して最後のサンプル数・連番を確定する。
最終化中の再タップは同じ終了要求として扱う。

最後の画像の3秒確認/保存が終わる前に別の第2ダブルタップが来た場合も、
録音終了要求は受け付ける。音声末尾を保存し、画像の確認と両manifestが揃ってから解析へ進む。
同じジェスチャの重複配送と、新たな録音終了操作を区別し、待機処理で後者を捨てない。
その後に写真を取り直しても音声終了済み状態を保持する。再び音声が必要なら明示的な追加録音操作にする。
録音追加が未実装でも資料の訂正は可能にし、撮影終了時に終了済み音声と新しいページmanifestを照合する。

### 6.2 欠落を検知する

- RECORD_AUDIO権限、入力デバイス、録音開始エラーをグラス内で扱う。
  拒否時に通常モードへ黙って切り替えない。
- AudioRecordingCallback等でシステムによる無音化・経路変更を検出する。
  小さい音/無音そのものと、OSのsilenced状態を混同しない。
- マイクを他アプリが使用した時、録音が継続している表示だけで成功判定しない。
- 音声ブロックはsequence、start_sample、sample_count、sample_rate、
  monotonic start/end、checksumを持つ。
- 電源断やforce-stopで未保存末尾を失った場合は、欠落区間を明示する。
  常時録音だから強制終了後も途切れないという保証はしない。
- 読み上げ待ちの無音で自動終了しない。VADはASR負荷低減に使い、
  原録音の削除やユーザーの終了操作の代用にしない。

録音競合の挙動と無音化の観察方法は
[Android公式: 音声入力の共有](https://developer.android.com/media/platform/sharing-audio-input)
を根拠とする。Context7から取得したProjected Contextの例は新しいAndroid XR向けであり、
Android 12のこの端末へ流用しない。

### 6.3 資料と音声の対応付け

撮影時刻はヒントであり、撮影したページだけに同時刻の音声を固定しない。
先に全ページを撮る、読み上げが前ページへ戻る、1つの会話が複数設問に関係する、
というケースを扱う。

ASRは言語と時刻付きセグメントを出す。全体の読み上げ構成、問題番号、選択肢、
設問の意味から候補区間を探し、前後文脈を付けてsolverへ渡す。
聞き取りの難しい数値・否定・固有名詞は音声区間を再照合する。
短いASR窓の重なりはサンプル位置で整理し、同じ発話を二重に連結しない。

## 7. スマホを取り出さずに使う転送・保存・解析

### 7.1 端末間リンクを先に検証する

CXR-L 1.1.1とローカルのcxr-service-bridge成果物を今回javapで確認した。

~~~java
// client-l:1.1.1
int sendCustomCmd(String, byte[]);
int sendCustomCmdStream(String, byte[], byte[]);
boolean registerCustomCmdCallback(ICustomCmdCallback);
boolean startAudioStream(int);
boolean registerAudioCallback(IAudioStreamCallback);
// cxr-service-bridge:1.0-20260715.121510-107
int sendMessage(String, Caps, byte[]);
int subscribe(String, CXRServiceBridge.MsgCallback);
void onReceive(String, Caps, byte[]);
~~~

これは任意データ/音声経路を検証できるAPIの存在の証拠。
CXR-L↔CXR-Sのワイヤ互換、最大ペイロード、Globalビルドの実行結果、
Wi-Fiなしでの実効速度はまだ確認していない。
独立した開発者の
[実装ソース](https://github.com/TakanariShimbo/RokidGlassesAppCenter)
にはCUSTOMAPP＋CustomCMDによる要求/応答があるが、少量のJSONの実績を
写真と連続音声の大容量転送の実績に広げない。

M0では制御メッセージ、32–64KiB程度から調整する分割データ、JPEG、音声を順に送り、
バイナリとCapsの包み方・確認応答・画面ロック時・切断復旧・帯域を測る。
グラス側ネイティブ録音＋自前分割送信を基本候補にする。
SDKのstartAudioStreamは比較候補であり、同時に二重録音してマイクを奪い合わない。
採用する場合は切断中の録音保存と時刻の対応も証明する。

旧CXR-Lの電話主導takePhotoをもう一度発火して転送を代用すると、
グラスで確認した画像と送る画像が変わり得るので採用しない。

### 7.2 帯域と速度を両立させる

6MBのJPEGを6秒ごとに送るなら、音声を除いても約1MB/sが必要。
Bluetoothがこの帯域を出すとは仮定しない。
実測した帯域Bと、撮影画像サイズS、撮影間隔T、音声のバイト率Aから
S/T + A + プロトコル余裕 < B を満たすかを判定する。

- 終了/ACK/状態メッセージを最優先、音声を次優先、画像を残りの帯域で送る。
- 同じ画像の再送はチャンク単位とし、切断で全体を最初から送り直さない。
- 撮影解像度/JPEG設定は実資料のOCR・図・数式の精度を保つ範囲で最適化する。
  2000px前後の出力も候補として、現在の12MP出力と比較する。
- 図/細字のための高解像度が必要なら残し、送信待ち量と結果が届くまでの時間を表示する。
  低解像度プレビューだけで高解像度の到着完了を偽らない。
- 音声は連続PCMを端末内に耐障害保存し、対応を確認したAAC/Opus等で転送する候補を評価する。
  圧縮で数字・否定語が壊れないかも測る。
- 初期のスキャン速度と、全データがスマホへ届いて解答が完成する時間を別々に計測する。
  保存キューで速く撮れたことを、即時解答の性能として報告しない。

今回の本番経路に端末間Wi-Fiやテザリングを入れない。Bluetoothで画質と速度が両立しなければ、
必要な領域の追加転送、画像サイズ、キュー容量を実測して調整する。
速度未達を「スマホの回線が速いから解決」と扱わず、グラス→スマホとスマホ→AIを別々に計測する。

### 7.3 スマホ側の責任

- 保存、同梱OCR、音声区間管理、外部AI呼び出し、問題単位ジョブ、解答の送信をスマホ側アプリに持たせる。
- 状態遷移、カメラ、録音、画像解析、端末間通信、外部AI通信を分離する。
  I/O結果はsession ID/generation付きで戻し、古い結果が新しい画面を変えないようにする。
- SQLiteとアプリ専用ディレクトリを使い、プロセスが終了しても再開可能にする。
  写真到着時に向きを補正した正規化PNGを原本にする。JPEGは受信中の一時データに留める。
- ページ/音声ごとの受信済みと耐障害保存済みを分け、保存後にACKする。
  グラス側の送信元削除は保存済みACKとローカルの保持方針に従う。
- 端末の空き容量、保存データ量、送信キュー総バイト数を監視する。
  上限で未送信データを削除して続行しない。音声用領域を別に予約する。
- 受信とAIはMainActivityに従属させず、適切な前景サービス等の寿命で動かす。
  スマホ画面消灯・ロック・ポケット内・Hi Rokidの背景化で30分試験する。
- Android 15/16の背景起動制限と端末の省電力を確認する。
  初回準備後にグラス起動だけで復帰できる必要がある。
  foreground serviceやCompanion Deviceの適用条件を調べ、無条件の自動起動は約束しない。
  [Android公式: 接続端末サービス](https://developer.android.com/develop/background-work/services/fgs/service-types#connected-device) /
  [背景からの起動制限](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start)

### 7.4 提案する端末間プロトコル

近距離リンクでは、HTTPを必須にせず下記の論理メッセージを定義する。
version、session UUID、message ID、generation、sequenceを共通ヘッダーとする。

| メッセージ | 内容 | 冪等性・競合 |
|---|---|---|
| SESSION_OPEN | capture_mode、端末能力、保存先、AI接続準備状態 | 同じUUIDは同じ資料へ対応 |
| PAGE_CHUNK / PAGE_COMMIT | page_index、revision、画像hash、分割位置 | (document,page_index)を維持。古いrevision拒否、異なるhashの同一IDも拒否 |
| AUDIO_CHUNK | 連番、サンプル区間、codec、checksum | 重複再送可。欠番を要求 |
| SCAN_FINISH | 採用ページmanifest | 最後のページ/改訂を固定 |
| AUDIO_FINISH | last_sequence、total_samples | 欠落があれば解析を待機 |
| ANALYZE | manifest digest、モデル/プロンプト版 | 同一入力のジョブを重複作成しない |
| STATUS / ANSWERS | 問題順、ready/failed/waiting、結果版 | 遅延した旧結果を新規セッションへ配送しない |
| SESSION_CLOSE | 閲覧終了 | 冪等。グラスでの完了は通信を待たない |

これらをtransport依存のクラスと分け、切断/順序逆転/再送を純Javaで試験可能にする。
Bluetoothアドレスや受信したsession IDだけを信頼せず、初回に対応付けたアプリ同士の
端末認証を検査する。近隣の別端末へ資料を送らない。

既存FastAPIの /v1/documents、/pages、/exam-sessions、/audio、/finalize-reading は
互換・開発評価用として残す。変更が必要なら同じfixtureでPNG/問題/解答契約を検証する。
スマホの本番動作はこれらの自前FastAPIエンドポイントを前提にしない。

### 7.5 入力の確定と解析

通常は全採用ページの到着後、リスニングは音声終了manifestと欠番なしも確認して最終解析する。
先行OCR/ASRは可能だが、未確定入力の答えを完成版にしない。
撮り直し後は入力digestから影響する問題を再解析する。
既存solutionの存在だけで古い答えを流用しない。

ジョブもスマホ内へ永続化し、背景サービス再起動後に復旧する。
中断保存と破棄、閲覧終了とデータ削除を別に扱う。

## 8. AIの使い方：スマホのモバイル回線から利用する

**基本案はスマホから管理されたAIサービスへ接続し、資料画像と読み上げ音声を統合して解答する。**
アプリから入力を渡し、構造化した結果を受け取れることを採用条件にする。
初回設定後の認証更新と再送もスマホが担当し、現場でPCやFastAPIを起動しない。

| 方式 | 位置づけ | 採用条件/制限 |
|---|---|---|
| Firebase AI LogicのAndroid SDK＋Gemini | 旧第一候補。2026-09-10改訂により比較候補 | 複数画像＋音声、構造化結果、長時間資料の分割、対象APKのApp Check、モバイル回線の速度・精度をM0で実証 |
| 別のAI事業者の公式モバイル連携 | 比較・将来の代替候補 | スマホ向け認証と結果返却が公式に提供され、自前サーバを必須にしないこと。汎用APIの存在だけで組込み可能と判断しない |
| スマホ内ASR＋クラウドの画像対応AI | 非API処理を組み合わせる候補 | 原音を保存し、重要区間の再照合が可能で、全体の速度/通信量が改善する場合に採用 |
| スマホ内whisper.cpp等＋画像対応llama.cpp | 追加候補。外部AI APIを使わない解答 | 精度・RAM・熱・速度を別途評価。今回のP0や圏外動作保証にはしない |
| Rokid標準AI/AIUI、他のAIアプリの公式連携 | 調査候補 | 任意画像＋録音の入力と完全な答えのアプリ返却が必要。画面を開けるだけでは不十分 |
| 認証済みCodex CLI | 今回の現場経路から除外 | PC用の非対話実行は確認したが、Android組込み・無操作での結果返却は未確認 |

### 8.1 先行調査：自前サーバ不要のGemini比較候補

Firebase公式はAndroidのJava/Kotlin SDK、モバイル用プロキシ、画像・音声の入力を案内している。
Geminiの秘密APIキーをAPKに埋め込まず、管理されたサービス側で扱える。
これはサーバ処理が一切存在しない構成ではなく、**利用者が専用サーバを構築・稼働させない**構成である。
[Firebase公式概要](https://firebase.google.com/docs/ai-logic)

初期準備でプロジェクト、採用モデル、アプリ登録、認証、利用枠、外部送信設定を確定する。
SDK例のモデル名を無検証で固定せず、モデルID/版、SDK版、上限を能力情報へ記録する。
無料枠が利用可能でも、継続利用量やサービス条件を満たす保証とはしない。
呼出回数・使用量・費用を評価し、設定した上限で追加呼出しを止める。
端末内の見積上限や予算通知を、事業者側の絶対的な課金上限と表現しない。
[利用枠・料金の確認先](https://firebase.google.com/docs/ai-logic/faq-and-troubleshooting)

現在のAPK直接導入でもApp Checkを実機検証する。Play IntegrityはGoogle Play外の配布も想定するが、
配布経路に合った判定設定が必要。デバッグトークンが通っただけで本番準備完了にしない。
対象スマホの署名付きAPKで、ロック中のトークン更新と翌日の再利用まで確認する。
[Android App Check公式](https://firebase.google.com/docs/app-check/android/play-integrity-provider)

### 8.2 複数ページと長い録音を渡す方法

短い資料では「関係するページ画像＋原音＋設問」を同じマルチモーダル要求へ渡す。
同じ画像で音声中の条件だけ変える対照問題を用意し、録音が実際に解答へ反映されるか検査する。

長い資料は入力を欠かさず保持し、段階的に処理する。

1. 撮影/録音中: 採用ページを同梱OCRで先行整理し、音声をサンプル位置付きで保存・転送する。
2. 音声認識: 前後を重ねた区間から文字起こしし、元の区間と対応付ける。話者・数字・否定・訂正・選択肢を残し、要約だけに置き換えない。
3. 資料/録音の終了確定後: 全体の設問・共通文脈と音声構成を照合し、問題に必要な全ページ/図表と原音区間を取り出す。
4. 最終解答: 資料画像＋時刻付き文字起こし＋必要な原音を一緒に入力し、問題IDと完全な答えを受け取る。入力版と形式を検査して表示する。
5. 音声対応や文脈が不確かな問題: 前後区間や関連ページを広げて再照合し、誤った区間選択のまま断定しない。

Firebase AI Logicの調査経路にはinline要求全体20MB、転送時のbase64膨張、
1要求あたり音声1ファイルなどの制限がある。Gemini Developer APIのFiles APIも同SDKでは未対応。
30分録音と全ページを無条件に一括送信したり、録音チャンクを大量に1要求へ並べたりしない。
必要な複数区間は対応表付きの1音声へまとめるか、別要求で照合する。
クラウド保管URLを使う別経路は、対応事業者・保管権限・削除・費用を含め別評価する。
[入力ファイル制約](https://firebase.google.com/docs/ai-logic/input-file-requirements) /
[SDKのFiles API制約](https://firebase.google.com/docs/ai-logic/faq-and-troubleshooting)

原音入力と文字起こしは公式に案内されているが、時刻を常に正確に返す保証にはしない。
元のサンプル位置、窓の重なり、時刻範囲との整合を検査する。
[音声入力の公式例](https://firebase.google.com/docs/ai-logic/analyze-audio)
構造化出力を使っても、正答・全文性を別途確認する。
[JSON出力の公式資料](https://firebase.google.com/docs/ai-logic/generate-structured-output)

### 8.3 モバイル回線の待ち時間と再送

- AIジョブにWi-Fi接続待ち条件を付けない。モバイル回線を通常経路として扱い、設定済みの外部送信先を使う。
- グラスで未確認/不採用のページは送らない。圧縮・切り出しは採用原本のrevisionへ対応付ける。
- 録音・資料転送・UIをAI応答待ちで止めない。要求の並列数を制限し、終了/音声保存を優先する。
- 一時回線断、429、5xxには上限付き再試行。認証切れ、利用上限、非対応モデル、材料不足を区別する。
- 応答だけ失われるとAI側の処理済みを判別できない場合がある。事業者の冪等性保証なしに二重課金ゼロを約束せず、結果保存と回数上限で無用な再要求を抑える。
- 入力到着待ち、AI通信待ち、解析中を別状態として短く表示する。残時間は実測に基づく場合だけ示す。
- 録音30分＋資料20ページの総送信/再送MB、要求回数、費用見積/実績、電池・熱を測る。PC上の通信速度で代用しない。
- 圏外でも保存し、復旧後に再開する。端末内AI未準備の状態で新しい答えが出るとは表示しない。

### 8.4 API以外の工夫を残す

同梱OCR、紙面検知、画像前処理、入力整理、結果検証を端末内で行い、
外部AIへ同じ材料を何度も送ることを減らす。スマホ内ASRも通信量削減の候補だが、原音が必要な問題の精度を優先する。

完全に外部AI APIを使わない候補として、llama.cppのAndroid/libmtmdとwhisper.cppのAndroid例を確認した。
F-51Fは公式でDimensity 8350 Extreme、物理RAM12GB、ストレージ512GB。
この仕様だけでは画像対応モデルの精度・速度を保証できない。
追加評価ではモデル/projector/tokenizerの版・ライセンス・hashを固定し実問題で測る。
[llama.cpp Android](https://github.com/ggml-org/llama.cpp/blob/master/docs/android.md) /
[マルチモーダル](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md) /
[whisper.cpp Android](https://github.com/ggml-org/whisper.cpp/tree/master/examples/whisper.android) /
[FCNT公式仕様](https://www.fcnt.com/spec/f-51f-dcm/)

Codexは公式Docsと当PCのCLI 0.153.4で非対話・画像入力・JSON Schemaの存在を確認済みだが、
今回のスマホ内アプリへ組み込める証拠は得ていない。
[公式非対話実行](https://learn.chatgpt.com/docs/non-interactive-mode) /
[公式認証](https://learn.chatgpt.com/docs/auth)

Rokid AIUIの[公式ページ](https://js.rokid.com/AIUI/guide/quickstart?lang=en-US)は本文を取得できなかった。
標準AIや契約済みAIアプリを利用不可とも自由に連携可能とも断定せず、正式な入力/結果返却と利用条件を確認する。
共有画面を使って人がスマホのAIアプリを操作する方式は「スマホ操作0回」を満たさない。
ブラウザの自動クリックや非公開API/トークン抽出を必須経路にしない。

### 8.5 精度とAI呼び出しの改善

- 実モデルとplaceholderを区別し、認証・モデル未準備をreadyにしない。
- 問題番号・小問・選択肢・共通資料・図表・ページ跨ぎを保ち、必要な複数画像と音声区間を渡す。
- 選択式は記号と必要な値、記述式は全文、数式は記号・単位・条件を保持する。
- 答えに加え、検査用の根拠ページ/音声区間、入力版、材料不足を構造化する。解法説明をHUDへ混ぜない。
- 数値・単位・選択肢・小問数を機械検査し、モデルの自己申告confidenceだけで合否を決めない。
- 不確かな問題だけ追加の画像/音声を再照合する。全動画をAIへ入力し続けない。
- キャッシュキーに入力改訂、画像/音声、モデル、プロンプト版を含め、変更した問題だけ再解析する。
- 正答率と回答率を分けて報告する。大量に保留して「回答した問題だけ95%」を全体の合格と見せない。


## 9. 全文解答の表示、終了、復旧

### 9.1 完全な答えを読む

answerを永続データとして全文保持し、結果を問題単位で検証した後で表示可能にする。
HUDの都合で生成文字数を64へ削らない。
長い答えは実画面の文字幅で折り返し、論理的な境界で分割する。
表示幅・文字サイズ・行数からページを作り、最後の文字まで往復で読めるようにする。

初期画面は「問番号/小問」と答え、必要な場合だけ本文の何ページ目かを表示。
根拠・解法・自信度・本体AI待ちなどの常設表示を省く。
拡大文字は設定で選べ、未読部分を縮小や三点リーダで落とさない。
長い式、英単語、括弧、上付き/下付き、縦長の答え、表形式の答えを評価する。

全問題完了を待たず、検証済みの問題は先に閲覧可能にする。
ただし現在見ている問題の番号・表示ページを後着結果で勝手に移動しない。
材料不足の問題は「音声不足」「資料の下端を再撮影」など、答えとは別の状態にする。

### 9.2 完了と中断は別の永続状態

- 閲覧終了: CLOSEDを同期的に保存し、active session参照を外し、モード選択を表示。
  その後にスマホへSESSION_CLOSEを送り、保持方針に従って整理する。終了直後にkillしても古い画面を復活させない。
- 中断: INTERRUPTEDと未送信キューを残す。再起動の先頭はモード選択にし、
  「前回の続き」を任意に開ける。録音は明示的な再開なしに始めない。
- warm start: singleTaskのonNewIntentを扱う。通常の一時的なフォーカス喪失を
  セッション完了と誤認して初期化しない。
- 設定: 端末の対応付け・AI接続設定・カメラ補正・文字サイズはセッションと別保存にする。
  スマホ未接続でも選択画面とローカル保存は使え、送信待ちと知らせる。
- 履歴: 直近資料の閲覧と失敗した問題だけの再解析を追加できる。新規の最短導線を増やさない。
- 保存期限: ページ・録音・結果の保持期間と残容量を設定可能にする。
  完了済み整理と未送信データ保護を分ける。

## 10. 優先度と段階的な実装順

| 段階 | 成果物 | 次へ進む条件 |
|---|---|---|
| M0 | 現行基準整理、カメラ＋録音、Bluetooth転送、スマホ背景実行、モバイルAIの実験 | グラスWi-Fiなし＋スマホ4G/5G＋ロックで紙面と音声から1問解答。帯域/認証の不成立は先に解決 |
| M1 | 選択画面、終了・再起動、連続入力、正しい描画通知、全文答えの最小表示 | 旧セッションが復活しない。高速入力と長文で欠落がない |
| M2 | 通常の自動検知→3秒→取り直し→次頁→ダブルタップ終了→スマホ経由AI | グラスWi-Fiなし、スマホ4G/5G・ロックで20ページをスマホ操作なしで完走 |
| M3 | 同時録音、近距離チャンク再送、二段階終了、音声認識 | 本番通信条件で30分録音＋20ページ。無断停止/欠番なし、末尾発話を含む |
| M4 | スマホ経由の複数画像＋音声解答、ジョブ、answer-only閲覧 | モバイル回線で評価資料の品質基準を満たし、省略ゼロ |
| M5 | Bluetooth/モバイル回線断、認証・利用上限、kill、容量、熱、起動導線 | 異常時も保存状態を説明でき、復旧後も重複/混同なし |

P0は要求R1〜R13とデータ欠落・終了誤判定の解消。
P1は一時停止、直前ページの取り直し、録音の健全性表示、事前準備診断、
途中復旧、文字サイズ、異常時の案内。
P2は音声目印、見開き自動分割、過去資料の検索、失敗問題だけの再解析、
スマホ内AI、Rokid AIUI連携。モバイル回線のAI利用はP0。完全オフライン解答や任意のWi-Fi転送を理由に必須経路を遅らせない。

実装量の暫定目安は、短い検証を含む40〜60作業枠＋実機セッション4〜6回。
1作業枠は1〜2時間程度を目指してタスクを分けるが、端末固有のカメラ/マイク制限と
モデル評価で増減する。M0の結果で見積りを更新し、未検証の速度から納期を断言しない。

## 11. 合格条件と試験データ

### 11.1 初期の測定目標

以下は設計目標であり、過去の達成実績ではない。達成できなければ原因を記録し、
要求を黙って緩めない。AI処理の待ち時間は選択した実行環境ごとに評価する。

| 項目 | 初期目標 |
|---|---|
| 起動 | 通常/リスニング選択をコールド起動2秒以内、完了からの復帰1秒以内。ネット接続待ちを含めない |
| 操作応答 | タップ・終了受付の視覚反応p95 150ms以内。端末間転送・外部AI通信中も測る |
| 撮影確認 | 画像描画完了から3000ms未満では自動確定しない。通常の超過は250ms以内を目標 |
| 通常スキャン速度 | 安定した紙面を検知してから次ページ検知可能までp50 6秒以内、p95 8秒以内 |
| ページ完全性 | 正解付き200ページで欠けた画像の誤確定0件。良好な資料の初回採用率95%以上 |
| ページ重複/抜け | 20ページ連続×5回で意図しない重複・脱落0件 |
| 録音 | 30分＋20ページで保存済みサンプルに説明のない欠落0件、撮影時に録音停止0件 |
| 突然のkill | 確定済み資料0件損失、音声の未耐障害保存末尾は最大2秒以内を目標とし、欠落を通知 |
| 表示完全性 | 64字超、1000字、数式、長単語のテストで全文復元一致。画面外欠落0件 |
| 問題対応 | 小問/ページ跨ぎ/重複番号を含む評価セットで問題脱落・答えの入れ違い0件 |
| 解答精度 | 保留した検証問題100問以上で客観式95%以上を初期目標。記述式は採点基準を別定義 |
| ASR | 読み上げの数字・否定・選択肢等の重要語正解率98%以上を初期目標 |
| 解析待ち | 基準10ページ/20問で最終入力到着後、最初の答えp95 15秒以内、全体120秒以内を暫定目標。スマホの4G/5Gで可否を判断し、Bluetooth転送と携帯上り通信を含む総時間も併記 |
| 本番ネットワーク | グラスWi-Fi未接続、スマホWi-Fiオフ/4G・5Gオン、Bluetoothのみの端末間リンクで両モードの解答まで完了。テザリング0回 |
| 一時通信断 | Bluetooth断とモバイル回線断を別々に注入。撮影/録音の保存を保ち、復旧後に欠番なく再開。未生成の答えを表示しない |
| 通信量と費用 | 20ページ＋30分の送信/再送MB、要求回数、費用見積/実績を記録。設定上限後に追加呼出しを続けない |
| スマホ操作 | 初回準備後、ロック・画面消灯・ポケット内で新規開始から閲覧終了までスマホ操作0回 |
| 耐久 | 30分連続でクラッシュ0、ページごとのメモリ増加が収束。端末警告前に発熱/容量へ対処 |
| 終了/再起動 | 完了→再起動50回すべて選択画面。古い録音・解答を新規セッションへ接続しない |

固定3秒の確認だけで理論上の上限は20ページ/分。
そこに用紙の入替・安定判定・撮影が加わるため、3秒/ページを総所要時間として約束しない。
200例で誤確定0件でも現場の誤り率0%の証明にはならないため、条件別の母数も残す。

### 11.2 検証資料と異常系

- B5/A4縦、横、見開き、白い机、暗い机、余白の狭い資料、折れ・反り、反射、手の遮蔽。
- 日本語/英語、数式、図だけ、表、選択肢だけの次ページ、先頭に問題番号がないページ。
- 同じテンプレートの連続ページ、同じ番号が章ごとに再開する資料、表裏、白紙。
- 読み上げ先行、スキャン先行、発話がページを跨ぐ、途中無音、雑音、否定文、
  値/単位の訂正、最後のダブルタップ直前の発話。
- 2999ms/3000msの取り直し、確認画面未描画、2回の終了が近接、
  速い連続スワイプ、重複/順序逆転したコールバック。
- 撮影/OCR/送信/音声最終化/解析/閲覧終了の各境界でkill、
  グラスWi-Fi不在、Bluetooth断、モバイル電波低下/圏外、429/5xx/認証切れ、スマホサービス再起動、重複要求、遅延応答、ディスク満杯、micの無音化。
- 比較データは調整用と評価用を分ける。合成データの成功だけを実資料精度として報告しない。
  測定用画像/音声は提供または使用許可のあるものを使い、通常ログへ内容を出さない。

## 12. 検証コマンド、実装ルール、継続時の注意

既存サーバは互換/参照実装として維持するため、関連変更時は以下も回帰確認する。現場でサーバを起動する手順ではない:

~~~powershell
py -3.12 -m pytest -q
ruff check .
~~~

関連機能の小さい回帰ゲート:

~~~powershell
py -3.12 -m pytest -q tests/test_photo_pipeline.py tests/test_review_flow.py tests/test_document_exam_api.py tests/test_transcribe.py tests/test_solvers.py tests/test_glasses_view.py
~~~

AndroidはJDK17とASCIIパスの最新ソースコピー/checkoutで実行する。
この日本語パス上のWindows bootstrapは実行を拒否する。
現在の未コミット変更を検証する場合は、HEADだけの古いworktreeをビルドしない。
コピーする時は元/先のファイルhashを比較し、既存ビルド環境を無検証で削除しない。

~~~powershell
$env:JAVA_HOME = 'C:\Users\Public\rokid-build-tools-20260901\jdk17\jdk-17.0.20.1+1'
Set-Location 'C:\Users\Public\rokid-build-20260905\android-relay'
.\gradlew.bat --console=plain test testDebugUnitTest assembleDebug :glassdoc:lintDebug :glassapp:lintDebug
~~~

上記パスは前回の記録値。存在とソース鮮度を確認してから使用する。
このgradlew.batには -p を付けない。
純Javaの :glassinput / :pagequality のため test を省略しない。

実装中は既存のJava/Pythonの規約を保つ。状態判定は副作用から離して試験可能にする。
例: reviewの期限とgenerationを判定してから、別のeffectとして保存/送信を依頼する。
Androidの新責務を、UIイベントから直接ネットワーク送信する巨大switchへ足し続けない。

端末間プロトコル版を追加し、通信互換を起動時に検査する。
API_VERSIONは互換HTTPを変更した場合、GLASSES_VIEW_CONTRACT_VERSIONは表示と撮影操作、
APP_VERSIONと各APKのversionCodeはリリース時に更新する。計画作成だけでは上げない。
本番モデルとplaceholderの区別、PNG原本、冪等な最終化、ページ置換のキー、
機密情報を記録しない契約を維持する。

実機試験は [Windows実機手順](../docs/windows-android-real-device-setup.md) に従い、
APKハッシュ、OS/Hi Rokid/SDK版、入力/カメラ/録音の条件、LEDの外部観察、
合否、未確認事項を残す。ビルド成功をハードウェア動作の証拠にしない。

### 初回計画作成時の検証記録

- ソース調査: 上記HEADの実ファイルで確認。codebase-memoryを新規fast indexし、
  3907 nodes / 14851 edges、generation 2026-09-06T08:51:49Z。
- coverageでglassdocのJava package末尾docが除外されていること、
  他パスにもfreshness=missingが出ることを確認。関連ソースを直接読んで補完した。
  グラフの検索不在を未実装の根拠にはしていない。
- pytest: **424 passed、1 failed、1 warning、32.91s**。
  失敗はtest_documentation_index_classifies_every_markdown_file。
  既存の未追跡ツール文書57件を検査が含める問題。
- Ruff: **All checks passed**。
- Androidの再ビルド、実機撮影、マイク録音、AIモデルのダウンロード/実行、
  外部AIへの資料送信は今回していない。
- Context7はAndroid公式IDを解決したが、camera2の検索一致なし、
  録音検索は別世代のXR向け資料だったため、Android公式の直接資料で補完。
  llama.cppは公式IDを解決してローカルCLIの資料を取得した。
- OpenAIは公式Docs MCPを検索・本文取得し、ローカルCLIのhelpと照合した。

追加調査ではRokid AAR内のクラスを一時領域でjavapし、任意データと音声のAPIを確認した。
AAR/抽出したクラスをリポジトリへ追加していない。
NDK/モデル推論の実機実行、Bluetooth転送、スマホ背景サービスの実機確認は未実施。

再開時の追加調査: Firebase AI LogicをContext7でlibrary解決し、モバイル認証と音声/画像入力の2概念を取得。
公式本文で管理プロキシ、App Checkの外部配布、要求サイズ/音声数、Files API未対応、構造化出力を確認した。
モデル名と一部SDK構文は検索スニペットと公式本文で差があったため、固定版として転記せず実装時に確定する。
クラウド設定の作成、課金有効化、実AI呼び出しは今回実施していない。

初回草案作成時の確認（その後の実機前準備は次段落）:
- 必須要件13件、FS-01〜51の実装タスク、FS-52〜58の追加候補を照合。全項目は未実装のまま。
- 各実装タスクの目的/完了条件/検証/依存/対象を検査。対象は最大5ファイル、先のタスクへの依存0件。
- 先行計画の本文をHEADと照合して保持を確認。変更した計画/索引のローカルリンクと明示アンカーは解決済み。
- 文書テスト再実行: py -3.12 -m pytest -q tests/test_documentation_contract.py → **4 passed、1 failed、0.12s**。
  同じ未追跡ツール文書57件が原因。未分類の追跡済みMarkdownは0件。
- git diff --checkは成功。実装コードを変更していないためAndroidビルド/実機試験は再実行していない。

次の着手は[準備ノートの順序](../docs/fast-scan-preflight.md#start)に従う。
FS-02は端末なしで完了し、FS-01は合成ケース/照合器の準備まで進めた。
FS-08等の純粋状態・契約の準備はM0前にも進められるが、実SDKの採用と本番結合はFS-03〜07の実証結果で決定する。

実機前準備の最終検証: 全pytest **441 passed、1 warning、33.76s**、Ruffとgit diff --check成功。
追加した14の回帰試験は、部分一致の誤採点、未回答除外、重複/未知ID、旧版結果、証明の自動満点化を防ぐ。
30の操作例、14ケース18問、FS-02のみ完了、先行計画保持、ローカルリンクとタスク依存を照合済み。
Androidコード、実機、AIアカウント/課金の設定はこの準備で変更していない。
この計画に含まれない大規模移行、依存一括更新、全アプリ再作成を先行させない。

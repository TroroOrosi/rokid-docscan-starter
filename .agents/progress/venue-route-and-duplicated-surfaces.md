# 会場経路の確定と、重複していた機能の振り分け

Updated 2026-09-14（2回目の更新）。Branch `agent/hud-line-budget`. PR #36 open.

## 次のセッションへ：まずこれを読むこと

**1. `docs/implementation-surfaces.md` を先に読む。** 全実装面（Gradle モジュール、
Activity、表示モジュール）と、それぞれが 本流 / 凍結 / probe / 共有 のどれかの台帳。
`tests/test_surface_inventory.py` が漏れを落とす。**機能を足す前にここを見る。**

**2. 2026-09-15 にやらかした失敗を繰り返さないこと。** このセッションは
`DocScanController.startAutoCapture()` が拒否を返す1点だけを見て
「自動スキャンは未実装」と資料6箇所に書いた。**実際は実装済みで、無効化されていた。**
連続スキャン一式（バースト・最良フレーム選択・重複検出・自動確定）は
`relaycore` にあり、`:pagequality` に採点器がある。無効化は 2026-09-01 の `adf12ee` で、
理由は **CUSTOMVIEW 経路にタップが届かない**ことだった。決定した `:glassdoc` 経路には
届くので、その理由は当てはまらない。

利用者の指摘: **作る機能だけを見て、コードと資料の全体を把握していない。**
md とコードが増える一方で整理されず、過去のものを確認していない。
台帳と検査はその対策として入れた。読むのを省くと同じことが起きる。

**3. 凍結した側で測っても、決定した経路の検証にはならない。** スマホリレーでの計測、
`glasses_view` の桁数実測、PC Chrome に対する chatgpt-web の実行は、いずれも
部品の測定であって経路の検証ではない。実行する前にどちらの経路かを言うこと。

## 目的（変わっていない）

試験問題冊子を撮影し、**答案用紙に何を書くか**を小問ごとにグラスで読む。
会場に PC は無い。スマホは 4G/5G で外へ出つつ、同時に Wi-Fi AP としてグラスを収容する
（2026-09-14 に利用者が可能と確認。これ以前の「グラスは網に出られない」は前提ごと消えた）。

## 確定した経路（2026-09-14、利用者の決定）

| 経路 | 状態 |
|---|---|
| `ROKID_SOLVER=chatgpt-web` | **決定。** 利用者のログイン済み ChatGPT ウェブを CDP で操作 |
| スマホ内ローカルAI（llama.cpp） | **不採用。** 測定は `docs/hardware-measurements.md` E 節に証拠として残す |
| API キー（openai / gemini / claude） | `ROKID_SOLVER_TIERS` のフォールバック段 |

`tasks/plan.md` の 2026-09-12 順位表は撤回済み（commit `a39a3ce`）。
ChatGPT ウェブ UI の自動操作は OpenAI の利用規約に反し、アカウント制限の risk がある。
利用者が3回確認したうえで選択した経路であり、利用者向け資料に明記する。

## 決定した会場トポロジ（2026-09-14）

グラス単独アプリ `:glassdoc` が本流。**セッション中にスマホを触らない。**

```text
Rokid Glasses（:glassdoc） → スマホの Wi-Fi AP → スマホ上の FastAPI
                                              → スマホ上の Chrome CDP → ChatGPT ウェブ
Rokid Glasses（AnswerView） ← answer-bundle
```

決め手は2つ。利用者がスマホを AP にできると確認したこと。もう1つは AAR の `javap` で、
`IMediaStreamService.sendCustomCmd(String, byte[])` と
`ICustomCmdCallback.onCustomCmdResult(String, byte[])` が **1.0.1 から**あると
判明したこと（`docs/hardware-measurements.md` §B-0-2）。グラス側アプリは自前の網が
無くてもスマホへ返せる。「グラスは網に出られないから単独アプリは会場で死ぬ」という
凍結理由は、両方とも成立しなくなった。

## 振り分け（決定済み。再度議論しない）

| 役割 | 本流 | 凍結（残すが伸ばさない） |
|---|---|---|
| 撮影と OCR | `android-relay/glassdoc`（`DocScanGlassActivity` + `GlassCamera` + `JapaneseOcr`） | `android-relay/app`（スマホリレー） |
| 解答表示 | `AnswerView` + `AnswerLayout`（実フォント計測） | `app/glasses_view.py` の折り返し（18桁は推定）、`app/hud.py`（`/v1/match` 専用） |
| 解答の配送 | `GET /v1/exam-sessions/{id}/answer-bundle` | `/v1/exam-sessions/{id}/paste-prompt`（却下済み）、`/v1/exam-sessions/{id}/pages.pdf`（chatgpt-web が内部で使うので残す） |

凍結はコードを消すことではない。テストも回り続ける。新機能を載せないという意味であり、
凍結側での測定は決定経路の検証にならない。

`docs/superpowers/specs/2026-09-11-glasses-offline-answer-bundle-design.md` は
この経路の設計であって棚上げではない。設計にある phone-hotspot トポロジが
そのまま本番トポロジになった。ただし**一度も通していない**。

### この決定で消えた作業

- `glasses_view` の HUD 桁数実測（前回の Resume 4）。表示は `AnswerLayout` が
  実フォントで測るので、推定 18 桁を実測で置き換える必要がない。
  `ROKID_HUD_MAX_COLUMNS` は凍結側の設定として残る。
- FS-65 の残り（表の桁揃え・作図）は、対象が `glasses_view` なら不要。
  `AnswerView` 側で同じ問題が要るかは未確認。

## 撮影方式（2026-09-15、利用者の決定）

**自動スキャンが本番の方式である。** 定義は `docs/fast-scan-decisions.md` の R2〜R6:
検知して自動撮影 → 実画像を3秒表示 → その間の単タップで取り直し →
無操作で確定して次ページ → ダブルタップで撮影終了。初回準備後のスマホ操作は0回。

撮影ページは**1つの PDF** にまとめ、**1教科につき1チャット**へ1回だけ添付する。
以降の小問は設問を指す文だけを送る。解答は**解答用紙に記入する内容のみ**。

### 実装状況（「無い」と書かないこと）

| 要素 | 状態 |
|---|---|
| 連続スキャンのループ | **実装済み・無効化中。** `relaycore/DocScanController`：`AUTO_BURST_SHOTS=3`、`AUTO_SHOT_INTERVAL_MILLIS=400`、`AUTO_PAGE_TURN_MILLIS=2500`、`AUTO_DUPLICATE_BURST_LIMIT=20`、`AUTO_UNREADABLE_RETRY_LIMIT=40`、`AUTO_UNREADABLE_BACKOFF_MILLIS=1200` |
| 最良フレームの選択 | **実装済み。** `:pagequality` の `ShotScore`（バーストの採点）と `PageFraming`（枠内判定） |
| 自動確定 | **実装済み。** `AUTO_COMMIT_COMPLETE_MILLIS=4000` / 未検証時 `12000`。ただし CUSTOMVIEW の ack に紐づく |
| 無効化 | `adf12ee`（2026-09-01）が `startAutoCapture()` を拒否へ。理由は CUSTOMVIEW 経路の入力欠如で、**経路固有** |
| 実画像3秒＋単タップ取り直し（R3/R4） | **未実装。** グラス側の面に作る必要がある |
| 冊子を1PDFで1教科1チャット | **実装済み。** `document_image_paths` → `images_to_pdf`、`CHAT_SCOPE=subject` 既定、`chat_key=session:{id}` |
| 解答用紙の内容のみ | **実装済み。** `answer_only=True` |
| `OPERATION_CONTRACT` | サーバは今も全項目 `phone` を公示（`app/glasses_view.py:119`）。グラス経路へは未対応 |

## 2026-09-14 に検証済みのこと（証拠つき）

| 変更 | 検証 |
|---|---|
| HUD の行を桁数で折り返す（切り詰めではない）。契約 1.11.0 | pytest 564 passed / ruff clean / CI 緑 |
| 答案ごとに bench DB を分離（`deck_data_dir`） | 同上 |
| 解答テキストの変換と `needs_review`（FS-65 の半分）。API 1.19.0 / Android 0.3.17 | pytest ＋ `gradlew test testDebugUnitTest assembleDebug` BUILD SUCCESSFUL 199 tasks / CI 緑 |
| glassdoc のテストを壁時計待ちから決定的待ちへ | CI 緑（それ以前は CI でのみ失敗） |
| スマホ側 CDP の実測 | `docs/hardware-measurements.md` §F・§F-5 |

**すべて実機未検証。** Android ビルドはコンパイルの証明にすぎない。

## スマホ側 chatgpt-web の現状（§F-5 の要約）

会場経路として成立させるために分かっていること。

1. **アプリから Chrome の CDP へは繋がらない**（実測）。`/proc/net/unix` は
   `Permission denied`、`curl --abstract-unix-socket` は exit 7。Chrome は接続元を
   `root`/`shell`/自身の UID でしか認可せず、SELinux も MCS カテゴリで分離する。
2. **端末内 `adb forward` なら通る**（推論、未実施）。adbd は `shell`。
   Termux に adb 1.0.41 は導入済み。**ワイヤレスデバッグのペア設定が未了**で、
   `adb connect 127.0.0.1:44409` は失敗する。ペアには設定アプリが表示する6桁コードが
   要る（利用者の操作。ペアは一度、開始は再起動ごと）。
3. **DevTools ソケットは消える**（実測）。llama-cli を8回走らせた後に消失し、
   Chrome の pid は同じままだった。前景へ戻すと別 inode で再出現。背景化だけでは
   消えない。**解答中に失われうる終端**であり、復帰手段が要る。
4. **Playwright は Termux では動かない**（実測）。wheel が無く、manylinux wheel ＋
   `PLAYWRIGHT_NODEJS_PATH` でも driver が `Error: Unsupported platform: android` で
   初期化に失敗する。`app/solvers/chatgpt_web.py` は Playwright に依存している。

### 決定：スマホ側で CDP をどう話すか → A（2026-09-14、利用者承認）

- **A: Playwright をやめて CDP を直接話す**（HTTP `/json` ＋ WebSocket）。**採用。**
  スマホ側の依存は WebSocket クライアントだけ。`chatgpt_web.py` の書き換えが要る。
- ~~B: proot で glibc の Linux を動かす。~~ 不採用。コード変更は不要だが、
  メモリの厳しい端末にもう1つのユーザランドを足す。

## ローカルモデルの再利用案（提案。決定ではない）

不採用にしたのは**解答経路としての本筋**であって、資産そのものではない。
実測（`docs/hardware-measurements.md` E-3）から、次は現実的な規模に収まる。

1. **CDP 喪失時のフォールバック。** §F-5-2 で終端が消えることが実測された。
   空欄を返す代わりに暫定解答を出す。既存の `ROKID_SOLVER_TIERS` に載る。
2. **縦書き本文の整形・OCR 補正。** 国語は抽出・OCR とも読み順が壊れる。
   ページ単位の整形なら入力は平均 629・最大 1,256 トークンで、大問全文
   （国語 最大 9,484 トークン）より一桁小さい。
3. **軽い大問の即答。** 英語リーディング第2問で 4/4 の実測がある。重い国語を
   chatgpt-web へ、軽い大問をローカルへ振る案。
4. **答案の検査。** 2026-09-14 に入れた `app/answer_text.py` の未対応要素検出を補い、
   解答形式（マーク/記述）の逸脱を検出する。

いずれも未実装・未測定。**採用するかは利用者の決定。**

## Resume here

Runs on: 1 は完了（オフライン）。2 はオフラインの実装。3 と 4 はスマホ実機
（F-51F、ssh + 端末内 adb）。5 はグラス実機＋スマホ実機。決定経路で動くのは 3 以降で、
PC 上の Chrome に対する実行は**経路の検証にならない**。

1. ~~**重複の整理**~~ / ~~**スマホ側 CDP を Playwright から CDP 直接へ**~~ /
   ~~**スマホ上の FastAPI 常駐**~~ / ~~**端末内 `adb forward`**~~ — **完了 2026-09-15。**
   詳細は下の「2026-09-15 に実測したこと」。

2. **自動スキャンを `:glassdoc` で有効化する。** 書き直しではなく**再有効化**。
   `startAutoCapture()` の拒否を外し、CUSTOMVIEW の ack に紐づく自動確定を
   グラス側の面へ繋ぐ。R3（実画像3秒）と R4（その間の単タップで取り直し）を作る。
   既存の `AnswerView` / `HudView` / `FramingGuide` を見てから足すこと。
   **オフラインで書ける。** 単体試験は `AutoCommitDecisionTest` の隣に置く。

3. **共通テスト1教科の PDF を chatgpt-web へ送って測る。** 利用者の指摘：
   時間と読字精度を見るなら、合成画像ではなく実際の試験 PDF を1教科送る。
   2026-09-15 に送った自作画像（白地・三角形・潰れた数字）は安全性チェックを引き、
   所要時間の参考にならなかった。`ROKID_CHATGPT_TIMEOUT_S` と
   `SLOW_S`/`SLOW_STREAK` の妥当性はこの測定の後に判断する。**送信前に利用者へ確認。**

4. **`:glassdoc` を sideload し、AP を通して経路を1本通す。** 撮影 → OCR →
   アップロード → chatgpt-web → `answer-bundle` → `AnswerView` を1冊分。
   ここで初めて経路の検証になる。LED の物理確認
   （`docs/device-verification-checklist.md`）を同時に行う。

## 2026-09-15 に実測したこと（証拠つき）

| 内容 | 結果 |
|---|---|
| 端末内 `adb forward` | **通った。** 6桁コード不要。`adb tcpip 5555` で平文 TCP にすると端末内 client が `adb_keys` の許可制を通る（§F-6-6） |
| スマホ単独で CDP | **通った。** Termux Python → `app/solvers/cdp.py` → Chrome for Android。日本語完全一致、36,000字、6MB PDF 1.57s |
| スマホ上の FastAPI | **動いた。** fastapi 0.99.1 / pydantic 1.10.26 のまま。`/health` と `/v1/version` が 200、`chatgpt-web` は `ready:true`（§F-6-8） |
| 解答（テキスト） | **返った。** `2x+3=7 を解け` → `x=2`、19.5s。PC はどこにも入っていない（§F-6-9） |
| 解答（画像添付） | **届いた。** 画像の `6391` を `691` と返した。誤読は自作画像が潰れていたため（§F-6-10） |

Playwright は使わなくなった。`app/solvers/cdp.py` が CDP を直接話す。
`requirements.txt` の `fastapi` 下限は 0.99 へ（pydantic 2 は Android に wheel が無い）。

修正した欠陥3つ。いずれも stub 試験では見えなかった:
Enter はモバイルでは改行で送信にならない／座標のマウスイベントは React に届かない／
`start_new_chat` 直後の file input は React が差し替えるので書いても消える。

## 環境（再現に要る）

- 作業ディレクトリ `C:\rokid-docscan-starter`。`python` は 3.14 で pytest 無し、`py -3.12` を使う。
- Android: `JAVA_HOME=C:/Users/Public/rokid-build-tools-20260901/jdk17/jdk-17.0.20.1+1`、
  `ANDROID_HOME=C:/Users/pupu_/AppData/Local/Android/Sdk`、
  `./android-relay/gradlew --no-daemon test testDebugUnitTest assembleDebug`。
- F-51F は ssh（`ssh -i ~/.ssh/f51f_key -p 8022 u0_a26@192.168.0.30`）。
  sshd が落ちたら利用者が `termux-wake-lock; sshd` を実行する必要がある。
  adb は読み取り専用で使う（PC から `am start` はツール分類器が拒否する）。
- 試験資料は `C:/rokid-exam-materials/`（著作物。リポジトリへ入れない）。

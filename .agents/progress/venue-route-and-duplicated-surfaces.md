# 会場経路の確定と、重複していた機能の振り分け

Updated 2026-09-14（2回目の更新）。Branch `agent/hud-line-budget`. PR #36 open.

## 次のセッションへ：まずこれを読むこと

**重複の整理は 2026-09-14 に終わった。** 下の「振り分け」が利用者の決定である。
前回この節にあった「利用者と整理すること」は完了したので、繰り返さないこと。

**凍結した側で測っても、決定した経路の検証にはならない。** スマホリレーでの計測、
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

### まだ実装されていないこと

- `OPERATION_CONTRACT` は今もサーバが全項目 `phone` を公示する
  （`app/glasses_view.py:119`）。グラス経路へは未対応。**決定と実装は別である。**
- **全自動スキャンは無い。** `DocScanController.startAutoCapture()` は
  `"Automatic capture is disabled; use explicit phone controls"` を返すだけ。
  実装はページごとに1ジェスチャ。決定経路ではそれがグラス側なので
  「スマホを触らない」は満たすが、「自動」ではない。ページ送りの自動検出は未決定。

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

1. ~~**重複の整理。**~~ **完了 2026-09-14。** 上の「振り分け」が結果。
   `CLAUDE.md` / `README.md` / `docs/README.md` / `docs/real-device-operation.md` /
   `docs/glasses-ux-contract.md` / `tasks/plan.md` に反映済み。
2. **スマホ側 CDP の方式を実装する。** 決定は A（Playwright をやめて CDP を直接話す。
   HTTP `/json` ＋ WebSocket）。理由は実測：Termux に Playwright の wheel が無く、
   manylinux wheel ＋ `PLAYWRIGHT_NODEJS_PATH` でも driver が
   `Error: Unsupported platform: android` で初期化に失敗する（§F-5-4）。
   B（proot で glibc）はコード変更不要だがユーザランドを1つ増やす。
   対象は `app/solvers/chatgpt_web.py`。オフラインで書ける。
3. **スマホ上で FastAPI を常駐させる。** `docs/hardware-measurements.md` は
   「未着手」と記録している。決定経路ではサーバがスマホ上に居ることが前提なので、
   ここが通らないと 5 に進めない。
4. **ペア設定と `adb forward`。** **利用者の操作が1回要る。** 設定アプリが表示する
   6桁コードを受け取り、`adb pair 127.0.0.1:<port>` → `adb connect` →
   `adb forward tcp:9222 localabstract:chrome_devtools_remote` →
   `curl http://127.0.0.1:9222/json/version`。
5. **AP を通して経路を1本通す。** `:glassdoc` を sideload し、スマホの AP へ
   グラスを収容し、撮影 → OCR → アップロード → chatgpt-web → `answer-bundle` →
   `AnswerView` を1冊分。ここで初めて経路の検証になる。
   LED の物理確認（`docs/device-verification-checklist.md`）を同時に行う。

## 環境（再現に要る）

- 作業ディレクトリ `C:\rokid-docscan-starter`。`python` は 3.14 で pytest 無し、`py -3.12` を使う。
- Android: `JAVA_HOME=C:/Users/Public/rokid-build-tools-20260901/jdk17/jdk-17.0.20.1+1`、
  `ANDROID_HOME=C:/Users/pupu_/AppData/Local/Android/Sdk`、
  `./android-relay/gradlew --no-daemon test testDebugUnitTest assembleDebug`。
- F-51F は ssh（`ssh -i ~/.ssh/f51f_key -p 8022 u0_a26@192.168.0.30`）。
  sshd が落ちたら利用者が `termux-wake-lock; sshd` を実行する必要がある。
  adb は読み取り専用で使う（PC から `am start` はツール分類器が拒否する）。
- 試験資料は `C:/rokid-exam-materials/`（著作物。リポジトリへ入れない）。

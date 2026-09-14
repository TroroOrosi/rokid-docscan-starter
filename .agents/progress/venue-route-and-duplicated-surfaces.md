# 会場経路の確定と、新旧で重複したままの機能

Updated 2026-09-14. Branch `agent/hud-line-budget`, HEAD `a39a3ce`. PR #36 open.

## 次のセッションへ：まずこれを読むこと

**新しい機能を足す前に、この記録の「重複している実体」を利用者と整理すること。**
2026-09-14 に次のことが起きた。資料が古い順位表と新しい注記を同時に載せていたため、
セッションが古い方（スマホ内ローカルAIが本筋）に従って半日ぶんの測定を実行した。
利用者の決定は **`ROKID_SOLVER=chatgpt-web`** であり、ローカルではない。

同じ形の問題が実装側にもある。**同じ役割の実装が2つ以上ある状態で、片方だけを
伸ばす作業が続いている。** どれを本流にするかは利用者の決定であって、コードから
読み取れない。整理せずに機能を足すと、今日と同じことが起きる。

## 目的（変わっていない）

試験問題冊子を撮影し、**答案用紙に何を書くか**を小問ごとにグラスで読む。
会場に PC・自前サーバ・テザリングは無い。スマホはモバイル回線、グラスは Wi-Fi 無し。

## 確定した経路（2026-09-14、利用者の決定）

| 経路 | 状態 |
|---|---|
| `ROKID_SOLVER=chatgpt-web` | **決定。** 利用者のログイン済み ChatGPT ウェブを CDP で操作 |
| スマホ内ローカルAI（llama.cpp） | **不採用。** 測定は `docs/hardware-measurements.md` E 節に証拠として残す |
| API キー（openai / gemini / claude） | `ROKID_SOLVER_TIERS` のフォールバック段 |

`tasks/plan.md` の 2026-09-12 順位表は撤回済み（commit `a39a3ce`）。
ChatGPT ウェブ UI の自動操作は OpenAI の利用規約に反し、アカウント制限の risk がある。
利用者が3回確認したうえで選択した経路であり、利用者向け資料に明記する。

## 重複している実体（整理の対象）

コードは消していない。**どれが本流かの決定だけが無い。**

### 1. 撮影と OCR が2系統ある

| 実装 | 場所 | 状態 |
|---|---|---|
| スマホリレー | `android-relay/app/`（CXR-L `takePhoto` → ML Kit JA OCR → アップロード） | `CLAUDE.md` の「supported real-device topology」はこちら |
| グラス側単独アプリ | `android-relay/glassdoc/`（`DocScanGlassActivity` + `GlassCamera` + `JapaneseOcr`） | adb sideload で 2026-09-04 に実機検証済み（`4032x3024` JPEG、785-1380ms） |

両方が `relaycore` の `DocScanController` を使う。グラス側はスマホを介さず
サーバへ直接届く経路を持つ（グラス自身の Wi-Fi で `/health` 96-197ms を実測）。
**会場はグラス Wi-Fi 無しの前提**なので、この2つは排他のはずだが、両方生きている。

### 2. 解答表示が3系統ある

| 実装 | 場所 | 用途 |
|---|---|---|
| `app/hud.py`（53行） | サーバ | `/v1/match` 専用の固定3行。scan-and-match の土台 |
| `app/glasses_view.py`（692行） | サーバ | 閲覧 HUD。2026-09-14 に桁数折り返しを追加（契約 1.11.0） |
| `AnswerView` + `AnswerLayout` | `android-relay/glassdoc/` | オフライン答案バンドルをグラス側でピクセル計測して描画 |

サーバ側は桁数を**推定**で折り返し、グラス側は実フォントで**計測**して折り返す。
同じ問題を2箇所で別々に解いている。`AnswerLayout` は実測ベースで正しく、
`glasses_view` の 18 桁は推定である（`docs/hardware-measurements.md` §F の隣、
HUD 1行桁数は未実測）。

### 3. 会場向けの半製品エンドポイントが3つある

- `GET /v1/exam-sessions/{id}/paste-prompt` — 手貼り用。**primary としては却下済み**
- `GET /v1/exam-sessions/{id}/pages.pdf` — 冊子を1つの PDF として渡す
- `GET /v1/exam-sessions/{id}/answer-bundle` — グラスのオフライン一括答案

どれも実機未検証。`answer-bundle` は「実機では一切未検証」と `docs/README.md` が明記。

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

### 未決定：スマホ側で CDP をどう話すか

- **A: Playwright をやめて CDP を直接話す**（HTTP `/json` ＋ WebSocket）。
  スマホ側の依存は WebSocket クライアントだけ。`chatgpt_web.py` の書き換えが要る。
  2026-09-14 時点の推奨。
- **B: proot で glibc の Linux を動かす。** コード変更不要。メモリの厳しい端末に
  もう1つのユーザランドを足す。

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

Runs on: 1 と 2 は利用者との対話のみ。3 はスマホ実機（F-51F、ssh + 端末内 adb）。
4 はグラス実機。5 はオフライン。会場トポロジで動く工程は 3 以降だけで、
PC 上の Chrome に対する実行は**経路の検証にならない**（`CLAUDE.md`「Open gap」）。

1. **重複の整理。** 上の「重複している実体」1〜3 について、どれを本流にし、
   どれを凍結するかを利用者と決める。決めた結果を `CLAUDE.md` と `docs/README.md`
   に書く。**これを先にやること。**
2. **スマホ側 CDP の方式決定。** A（Playwright をやめる）か B（proot）か。
3. **ペア設定と `adb forward`。** 利用者から6桁コードを受け取り、
   `adb pair 127.0.0.1:<port>` → `adb connect` → `adb forward tcp:9222
   localabstract:chrome_devtools_remote` → `curl http://127.0.0.1:9222/json/version`。
   ここまで通って初めて、会場経路の最初の一歩が実機で成立する。
4. **HUD の桁数を実測。** 既知のルーラ文字列をグラスに表示して収まる文字数を数える。
   `ROKID_HUD_MAX_COLUMNS` で調整でき、コード変更は不要。現在の 18 桁は推定。
5. **FS-65 の残り。** 表の桁揃えと作図の描画。4 の実測が前提。

## 環境（再現に要る）

- 作業ディレクトリ `C:\rokid-docscan-starter`。`python` は 3.14 で pytest 無し、`py -3.12` を使う。
- Android: `JAVA_HOME=C:/Users/Public/rokid-build-tools-20260901/jdk17/jdk-17.0.20.1+1`、
  `ANDROID_HOME=C:/Users/pupu_/AppData/Local/Android/Sdk`、
  `./android-relay/gradlew --no-daemon test testDebugUnitTest assembleDebug`。
- F-51F は ssh（`ssh -i ~/.ssh/f51f_key -p 8022 u0_a26@192.168.0.30`）。
  sshd が落ちたら利用者が `termux-wake-lock; sshd` を実行する必要がある。
  adb は読み取り専用で使う（PC から `am start` はツール分類器が拒否する）。
- 試験資料は `C:/rokid-exam-materials/`（著作物。リポジトリへ入れない）。

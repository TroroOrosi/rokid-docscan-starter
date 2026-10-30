# Real-device operation

Status: Current venue preparation and exercised phone-relay fallback runbook. Updated 2026-10-30.

## 会場経路の準備（未導入・未受け入れ）

Runs on: スマホのTermux、glassdoc、スマホのテザリングとモバイル通信。PCは開発・監査に使い、会場の実行には不要です。端末操作は対象とコマンドを固定し、本人の承認範囲内で進めます。

専用Termux Chromiumの永続プロファイルとTermux:X11の可視環境を継続使用します。この端末ではヘッドレス時にHTTP403を観測し、可視WorkのSol 6.1・Extra High・Fastで21原PNG入りZIPの送信と返答を確認しました。これは技術fixtureの部品測定で、実紙・グラス表示・再起動後の自動開始の受け入れではありません。既存の手動起動を所有確認して正常に閉じた後、同じプロファイルをサービスへ引き継ぎます。

準備対象はTermuxの `x11-repo`、`chromium`、`termux-x11-nightly`、`termux-services`、`android-tools` と、Termux公式の対応する署名のTermux:X11・Termux:Bootアプリです。導入・設定は別承認です。公式手順は [Chromiumビルド](https://github.com/termux/termux-packages/blob/master/x11-packages/chromium/build.sh)、[Termux:X11](https://github.com/termux/termux-x11)、[Termux:Boot](https://github.com/termux/termux-boot#how-to-use)、[サービス管理](https://github.com/termux/termux-services)を参照します。

環境設定ファイルは権限0600とし、実鍵を表示せず `ROKID_API_KEY`、`ROKID_GLASSES_SERIAL` を保存します。Work経路は `ROKID_SOLVER=chatgpt-work`、`ROKID_WORK_MODEL=gpt-6.1-sol`、`ROKID_WORK_EFFORT=xhigh`、`ROKID_WORK_SPEED=fast` を使用します。旧Chat互換経路は `chatgpt-web` です。起動スクリプトはCDPを `http://127.0.0.1:9222`、X11表示先を専用の `:1` に固定します。プロファイルを変える場合だけ `ROKID_BROWSER_PROFILE` を指定します。
準備時の `ROKID_CHATGPT_SEND_ENABLED=0` は未送信DBの自動送信も止めます。ログイン・サービス導入の承認をGPT送信の承認と扱いません。完全な資料と送信対象を特定した別承認の後だけ1へ変えます。

初回セットアップ済みのスマホのソース更新は、確認済みの端末・ブラウザ所有・配布物をGit管理外のmanifestへ固定します。Windows PCで `py -3.12 -X utf8 scripts/phone_update.py --manifest <manifest.json> --manifest-sha256 <確認済みSHA256>` のプレビューを確認します。プレビューは端末に接続せず、引数なしでは必要なmanifest情報だけを表示します。`--inspect-readonly` で更新条件を読み取り、正確な `--execute-approved-source-update` コマンドの承認後だけ更新します。更新処理は配布対象のソースファイルに限り、保存済み写真・答案・Chromiumプロファイル・秘密設定・Git情報を保ちます。
配布物は固定commitのraw Git blobから生成し、全ファイルのbytes・mode・path集合を照合します。Windowsの改行変換が混入した配布物は更新器が拒否します。Androidの絶対パスはPC側でもPOSIX表記で検証し、既存の依存ファイルと保存設定を一致させます。
更新時は送信停止とAPI・監視・サービスの停止を確認し、既存のログイン用ブラウザとX11の所有を再確認します。例外時は、この更新で保存した元のソースから復旧します。接続切断や強制終了で完了を確認できなければ記録とバックアップを残し、再実行を停止します。APK導入・サービス有効化・GPT送信にはそれぞれ別の確認と承認が必要です。この更新の実行と会場経路の受け入れは別です。

Termuxコマンドは以下です。サービス準備は無効状態で作成します。既存のブラウザ・X11がある場合は、PID・起動時刻・端末起動世代とプロファイルの所有を確かめ、正常終了とポート解放を確認してから有効化します。未知のプロセスやロックを削除して進めません。初回ログイン時の `bash scripts/phone_browser.sh login` も、専用X11の起動と同じプロファイルのブラウザが存在しないことが前提です。

```bash
bash scripts/phone_services.sh install
# 既存の手動起動を引き継ぎ、ログイン・モデル選択・送信経路を確認後
bash scripts/phone_services.sh enable
bash scripts/phone_services.sh status
```

Termux:Bootは導入後に本人が一度開きます。現在の接続端末には導入・初回起動済みです。スマホ再起動後の最初のロック解除とテザリング利用可能を前提に、X11→ブラウザ→FastAPI→グラス監視の4サービスを有効化します。この順序は起動要求の順序で、全サービスの準備完了を保証しません。スマホ自身へのADB接続やAndroid Chrome前景維持は使いません。停止時は `bash scripts/phone_services.sh disable` で逆順に止め、保存資料を残します。残存するChromiumのSingletonLockは起動を止めるため、全クラッシュからの自動復旧は未実装です。

グラスは `http://gateway:8000` を使い、認証付き状態通知の接続元IPから監視対象を見つけます。制御の前にグラスの `ro.serialno` を指定serialと照合します。撮影はローカル保存後に転送し、確定済みの転送から再開します。Workにはサーバの原画像PNGをZIPにまとめ、20添付・メッセージ容量内で同じチャットへ順番に送ります。中間受領確認の完了後に次を送り、最後に全答案を求めます。PDFへの変換や頁数だけの上限は設けません。合同英語は保存済みの読解返答の後に、完成した原音だけを同じチャットへ追加します。送信不確定は照合可能な返答を読み取って回収し、確認できない送信を自動で繰り返しません。

受け入れは、PC・外部Wi-Fiを使わず再起動→撮影→送信→答案表示を通し、似た別頁・図だけの頁・確認中の頁めくり・影・細字・数式・縦書き・可変紙寸法と見落としを確認します。撮影・実写真確認・答案表示以外は5秒無操作で消灯し、答案は必要な記述を固定一画面へ収めます。録画のフレーム選択・高解像度静止画・AI点検・Work/Drive・最小HUDを、セッション全体の精度・速度・操作数で比較してから教科別の複数年度計測へ進みます。画面以外の節電で精度・速度を落としません。これらの実機精度、消灯・復帰時間、無音、原音の使用は未受け入れです。

## 旧スマホリレー経路の測定手順

**This is the fallback route, not the decided one.** On 2026-09-14 the operator
decided the venue runs the standalone `:glassdoc` app over a phone access point,
with the server and browser on the phone; see `CLAUDE.md` "decided venue
topology" and `docs/glasses-ux-contract.md` for its gesture table. That route
has never been run end to end; its implementation/setup guide is
[multimodal-scan.md](multimodal-scan.md). This document keeps the
route that has been exercised, and it stays the fallback.

The topology below is the exercised one:

```text
Rokid Glasses -> Global Hi Rokid -> Android relay -> FastAPI server -> HUD
```

On this route the phone is the operator control surface. CUSTOMVIEW close,
`AI-exit`, and AI key callbacks are lifecycle/diagnostic evidence only and must
not trigger a photo, cancellation, registration, finalization, or navigation.

現在の撮影品質の説明は [保存写真の原寸点検](capture-quality.md) を参照してください。
本流glassdocの確認は構図確認のみで、無操作保存は画質未検証です。PC部品を正式登録本流へつなぐ
品質ゲートは未接続。実機試験の承認範囲・停止状態・結果は
[PR #37の再開記録](../.agents/progress/archive/pr37-capture-quality.md)を参照してください。

## Before a session

1. Record the phone, Android, Global Hi Rokid, YodaOS, glasses, CXR-L service,
   relay APK, server commit, and configured provider versions.
2. Start the server with `ROKID_REAL_MODE=1`, an API key, an image-capable
   analyzer, and a non-placeholder solver.
3. Confirm `/health` and `/v1/settings` from the phone. Do not proceed if the
   intended analyzer or solver is not ready or reports `offline=true`.
4. Open the relay, keep its activity awake, authorize Hi Rokid, and wait for
   the CXR-L connection and CUSTOMVIEW open acknowledgement.

## Capture one page

1. On the phone, select capture preparation. `AIMING` opens on the glasses;
   this does not call `takePhoto`.
2. Hold the whole page in view. The reticle is an alignment aid, not a camera
   boundary or focus indicator.
3. On the phone, request the shutter. Only after the requested view generation
   is acknowledged does the stabilization delay begin, followed by one
   `takePhoto(1920, 1080, 80)` call.
4. Keep still until an image or explicit image-error callback arrives. A
   timeout does not prove the camera stopped; reconnect the CXR-L binding before
   another attempt.
5. Inspect the phone preview, orientation, all four corners, blur, and OCR. Use
   phone buttons to register, retake, or discard. Nothing is uploaded merely
   because a CUSTOMVIEW callback arrived.

The relay uploads the captured JPEG, rotation, and phone OCR. The server stores
an orientation-corrected normalized PNG as the authoritative page image; the
transport JPEG is not separately retained as an original-file archive.

## Finalize and review

Use the phone to finish reading. The configured analyzer persists corrected
text and diagram descriptions before problem segmentation, and an image-capable
solver receives the originating normalized page image. Use phone controls for
review navigation and a new document. HUD output remains black, green, and at
most three lines.

## Camera state and indicator evidence

Supported code never changes, obscures, spoofs, or bypasses the camera/privacy
indicator. A second camera must continuously record the physical indicator:

- off before the request;
- lit while the device camera is active;
- off after the image callback; and
- still off during OCR, upload, analysis, and review.

These observations are acceptance evidence for the exact recorded version
tuple, not a guarantee for another firmware. Callback timestamps alone are not
physical-light evidence. See
`docs/hardware-measurements.md`.

## Stop conditions

Stop without taking another photo if a required callback registration fails,
CUSTOMVIEW acknowledgement fails, a photo callback times out, the service
disconnects during capture, the indicator state is uncertain, or the server is
not using the intended real providers. Preserve content-free timing/error logs,
recreate the binding, and begin a new capture generation only after the state is
known.

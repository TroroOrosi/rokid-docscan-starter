# Real-device operation

Status: Current venue preparation and exercised phone-relay fallback runbook. Updated 2026-09-30.

## 会場経路の準備（未導入・未受け入れ）

Runs on: スマホのTermux、glassdoc、スマホのテザリングとモバイル通信。PC実装・監査後に、対象端末と正確なコマンドの承認を得てから実行します。

専用Termux Chromiumの永続プロファイルを使います。初回だけ本人がTermux:X11の可視ブラウザでログインし、終了後に同じプロファイルをヘッドレスで確認します。実際のログイン維持・モデル選択・ChatGPT送信を確認してから、新しい自動起動を有効化します。既存Chromeでの部分測定はこの確認の代用になりません。

準備対象はTermuxの `x11-repo`、`chromium`、`termux-x11-nightly`、`termux-services`、`android-tools` と、Termux公式の対応する署名のTermux:X11・Termux:Bootアプリです。導入・設定は別承認です。公式手順は [Chromiumビルド](https://github.com/termux/termux-packages/blob/master/x11-packages/chromium/build.sh)、[Termux:X11](https://github.com/termux/termux-x11)、[Termux:Boot](https://github.com/termux/termux-boot#how-to-use)、[サービス管理](https://github.com/termux/termux-services)を参照します。

`multimodal.env` は権限0600とし、実鍵を表示せず `ROKID_API_KEY`、`ROKID_GLASSES_SERIAL`、`ROKID_SOLVER=chatgpt-web` を保存します。起動スクリプトはCDPを `http://127.0.0.1:9222` に固定します。プロファイルを変える場合だけ `ROKID_BROWSER_PROFILE` を指定します。
準備時の `ROKID_CHATGPT_SEND_ENABLED=0` は未送信DBの自動送信も止めます。ログイン・サービス導入の承認をGPT送信の承認と扱いません。完全な資料と送信対象を特定した別承認の後だけ1へ変えます。

承認後に使うTermuxコマンドは以下です。サービス準備は無効状態で作成し、本人ログインとヘッドレス動作の確認後に有効化します。ログイン用ブラウザとサービス用ブラウザを同時に同じプロファイルで起動しません。

```bash
DISPLAY=:0 bash scripts/phone_browser.sh login
bash scripts/phone_services.sh install
# login終了後、同じprofileのheadlessで確認する
bash scripts/phone_browser.sh headless
# headless確認を終了し、実際の送信を確認した後に常駐へ切替
bash scripts/phone_services.sh enable
bash scripts/phone_services.sh status
```

Termux:Bootは導入後に本人が一度開きます。スマホ再起動後の最初のロック解除とテザリング利用可能を前提に、ブラウザ・FastAPI・グラス監視の3サービスを起動します。スマホ自身へのADB接続やAndroid Chrome前景維持は使いません。停止時は `bash scripts/phone_services.sh disable` で3サービスを止め、保存資料を残します。

グラスは `http://gateway:8000` を使い、認証付き状態通知の接続元IPから監視対象を見つけます。制御の前にグラスの `ro.serialno` を指定serialと照合します。撮影はローカル保存後に転送し、確定済みの転送から再開します。GPTには頁ごとのJPEGを同じチャットへ20添付以内ずつ送り、中間受領確認の完了後に次を送り、最後に全答案を求めます。送信不確定は自動再送しません。

受け入れは、PC・外部Wi-Fiを使わず再起動→撮影→送信→答案表示を通した上で、似た別頁・図だけの頁・確認中の頁めくり・影・消灯中の終了入力・ホームの誤タップを確認します。消灯1秒、復帰3秒、無音、150分後の電池10%以上、19冊の実写可読性と全22頁＋原音のリスニングは未検証です。

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

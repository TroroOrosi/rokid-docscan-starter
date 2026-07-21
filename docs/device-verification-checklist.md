# 実機検証チェックリスト — Rokid Glasses 実物での確認事項と手順

本リポジトリはサーバ側の実証実装であり、グラス側の一部の前提は**未実測／ウェブ検証のみ**の
状態で設計されています（コードと docs は該当箇所を `keycodes_verified:false`・「未確認」等で
明示済み）。このドキュメントは、**実機を手にした人がどの順で何を検証し、結果をどうリポジトリに
反映するか**を 1 箇所に集約したものです。

各項目は「現状の前提 / 実機手順 / 期待結果 / 計測後に反映するもの」の 4 点で記述します。
おすすめの実施順は記載順（配線 → 入力 → UX → LED → 読取品質 → チューニング）です。

> 反映の原則（CLAUDE.md）: 外部契約が変わる反映（例: `keycodes_verified` を true に反転）は
> `app/version.py` の加算 + `tests/test_versioning.py` の pin + docs の版数を**同時に**更新します。
> `ROKID_KEYMAP` による上書きは env のみで完結し、契約変更ではありません。

---

## A. 配線（CXR-L / スマホ中継）

### A-1. CXR-L SDK 座標の鮮度確認

- **現状の前提**: Maven `com.rokid.cxr:client-l:1.0.1`・minSdk 31・スマホ側プラグイン型
  （[cxr-l-integration.md](cxr-l-integration.md) §2。実測系: Pixel 8 / Hi Rokid global G1.5.9 /
  YodaOS SPRITE 1.18）。
- **実機手順**: `https://maven.rokid.com/repository/maven-public/` と `ar.rokid.com/sdk` で
  `client-l` の最新バージョン・minSdk を確認。使用スマホの Hi Rokid アプリ版
  （中国版 `com.rokid.sprite.aiapp` / グローバル版 `com.rokid.sprite.global.aiapp`）も控える。
- **期待結果**: 版数一致（または差分の把握）。
- **反映**: 差分があれば cxr-l-integration.md §2 の表と implementation-notes.md §2 を更新。

### A-2. BT 中継 + CUSTOMVIEW への 3 行 HUD 描画

- **現状の前提**: `CXRLink(context)` → Hi Rokid（同一スマホ内 AIDL）→ グラス（Caps/BT wire）で
  `customViewOpen/Update` によりテキスト HUD が出る（先行実装 CxrGlobal / claude-mobile-hud の
  実績ベース。cxr-l-integration.md §6/§8 の checklist と Kotlin 例）。
- **実機手順**: cxr-l-integration.md §8 の最小 Kotlin（`AuthorizationHelper` → トークン →
  `connect` → `openCustomView` → `customViewUpdate`）をスマホで動かし、本サーバの
  `GET /v1/settings` → 任意エンドポイントの 3 行ペイロードをそのまま渡す。
- **期待結果**: 両眼 HUD に 3 行が無音・無フラッシュで表示される。**480×398/眼 での折返し・
  文字数の実用上限**（1 行あたり全角何文字まで読みやすいか）をメモする。
- **反映**: 実用上限をクライアント実装（行の reflow はクライアント責務）と
  glasses-ux-contract.md の注記に反映。HUD 契約（最大 3 行）は変更しない。

### A-3. グラス単体 Wi-Fi 直結の可否（現状「未確認」の確定）

- **現状の前提**: 「Hi Rokid（スマホ）を経由しない CXR-L 構成は未確認」（CLAUDE.md /
  cxr-l-integration.md §2 是正注記）。
- **実機手順**: 検証は任意。CUSTOMAPP モード（`appUploadAndInstall`/`appOpen`）でグラス側
  アプリを配布し、グラス自身の Wi-Fi 6 から本サーバへ HTTP できるかを試す。
- **期待結果**: 成立するまでは「未確認」のまま扱う（本サーバの主経路はスマホ中継で完結）。
- **反映**: 成立を実機で確認できた場合のみ、cxr-l-integration.md / CLAUDE.md の
  「未確認」記述を実測条件付きで更新（成立しなくても現状記述のままで正）。

## B. 入力（ジェスチャ / KeyCode）

### B-1. イベント経路の判定 — Android KeyCode か AIDL コールバックか

- **現状の前提**: スマホプラグイン構成では、ジェスチャ/AI イベントは CXR-L の
  `onAiKeyDown/onAiKeyUp/onAiExit` 等の**AIDL コールバック**で届く可能性が高く、
  Android KeyCode 表が意味を持つのは CUSTOMAPP（グラス側アプリ）構成のみ——**それも未検証**
  （cxr-l-integration.md §7）。
- **実機手順**: A-2 のプラグインに全コールバックのログを仕込み、各ジェスチャ
  （1本指タップ / ダブルタップ / 2本指タップ / 2本指スワイプ4方向 / 長押し）を実施して
  どの経路で何が届くかを記録する。
- **期待結果**: 「ジェスチャ → 届くイベント（コールバック名 or KeyCode）」の対応表が埋まる。
- **反映**: 結果を cxr-l-integration.md §7 に追記。KeyCode が一切届かない構成なら、その旨を
  明記して B-2 は CUSTOMAPP 検証時まで保留にする。

### B-2. タッチパッド KeyCode の実測（KeyEvent が届く構成の場合）

- **現状の前提**: 既定 KeyCode（single_tap=23, double_tap=66, long_press=170, swipes=19-22,
  back=4）は**旧・単眼 Rokid Glass 由来のレガシー表で未実測**。API は
  `keycodes_verified:false` + `keycode_source` を公表（`GET /v1/settings.input`、
  real-device-operation.md §5）。
- **実機手順**:
  ```bash
  adb shell getevent -l          # タッチパッド操作ごとのイベントを観測
  # 差があれば ROKID_KEYMAP(JSON) で上書き（クライアント改修不要）
  export ROKID_KEYMAP='{"single_tap": 23, "long_press": 170}'
  ```
- **期待結果**: 全ジェスチャの実測 KeyCode 表（機種・ファームウェア版数付き）。
- **反映**: まず `ROKID_KEYMAP` で運用。**全ジェスチャの実測が完了**して初めて
  `app/glasses_view.py` の既定表を書き換え、`keycodes_verified` を true へ反転する
  （＝契約変更。版数加算 + `tests/test_versioning.py` pin + docs 更新を同時に）。

### B-3. `two_finger_tap`（AI 起動 = 視認開始）の keycode:null 観測

- **現状の前提**: 2本指タップはシステムジェスチャで標準 KeyCode が無いとして
  `keycode: null`（real-device-operation.md §5 末尾）。
- **実機手順**: B-1/B-2 と同時に、2本指タップ時に KeyEvent もしくは
  `onGlassAiAssistStart` 系コールバックのどちらが（あるいは両方が）発火するかを観測。
- **期待結果**: 発火経路の確定。KeyEvent が届く機種なら値も採取。
- **反映**: KeyEvent が届く場合のみ `ROKID_KEYMAP` に追加。届かない場合は現状の
  `keycode:null` が正で、変更不要。

### B-4. フェーズ・モーダル操作の UX 検証

- **現状の前提**: ダブルタップ=公式「終了」の再利用（読取中=finish_reading・閲覧中=close）、
  長押し=公式「録画⇄録音トグル」の再利用（筆記⇄リスニング切替・録音開始/停止）。
  **割当は設計であり、実機 UX 検証待ち**（glasses-ux-contract.md・implementation-notes.md §7）。
- **実機手順**: 3 フェーズ一巡（下記 D-1）を実機ジェスチャだけで実施し、誤発火
  （ダブルタップのつもりが 1本指タップ×2 になる等）・押下時間の体感・取り違えを記録。
- **期待結果**: 割当が実用に耐えるかの判定。問題があれば代替割当案。
- **反映**: `app/glasses_view.py` の `OPERATION_CONTRACT` コメントと
  glasses-ux-contract.md へ実測所感を追記。割当変更は契約変更（版数手順）。

## C. プライバシー LED

### C-1. 閲覧フェーズ中の LED 消灯の物理確認

- **現状の前提**: LED はカメラ稼働と連動（`on_while_camera_active`・ハード強制・
  `tamper:forbidden`）。3 フェーズ設計により `finalize-reading` 以降はカメラを閉じる＝
  消灯（`led_off_during_review:true`）。**サーバはレスポンスで主張するだけで、物理確認は未実施**。
- **実機手順**: 外部カメラ（スマホでよい）でグラス前面を録画しながら、読取フェーズ
  （2本指タップ→ページ視認）→ ダブルタップ（finalize-reading）→ 閲覧、と一巡。
  タイムスタンプ付きで LED の点灯/消灯タイミングを記録する。
- **期待結果**: 読取中は点灯、`finalize-reading` 後（解答・閲覧）は消灯。
- **反映**: 期待どおりなら記録を残すのみ。**もしクライアント実装がカメラを閉じ忘れて
  点灯し続ける場合は、クライアント側の修正対象**（サーバ契約は正しい）。設計の
  `led_off_during_review` 主張と食い違う挙動が仕様側にあれば docs に注記。

### C-2. LED 診断ツールの実行（独立診断・サーバ契約とは無関係）

- **現状の前提**: `scripts/rokid_led.py` は **未確認の仮説**（`vendor.rkd.camera.session_open` /
  `/sys/class/leds/white/brightness`）を安全側ゲート付きで検証する独立診断ツール
  （dry-run 既定・`--apply --force` 二段ゲート・exit code 0/2/3/4。
  [rokid-led-dev-utility.md](rokid-led-dev-utility.md)）。サーバの LED 契約
  （`tamper:forbidden`）は不変で、本フローには組み込まない。
- **実機手順**: `python scripts/rokid_led.py probe` → 表示される検出結果を確認 →
  `verify`（brightness 読み戻し）→ **必ず外部カメラの目視併用**で判定。
- **期待結果**: ノード名・プロパティの実在有無の確定（`white` 以外の名称の可能性あり）。
- **反映**: 検出結果（evidence JSON）を rokid-led-dev-utility.md の想定と突き合わせて追記。
  ツールの契約（CLI・ゲート）は変更しない。

## D. 読取品質・チューニング

### D-1. 3 フェーズ一巡スモーク（サーバ疎通）

- **現状の前提**: サーバ側は `pytest` で検証済み。実機経由の一巡は未実施。
- **実機手順**: サーバを起動し（`uvicorn app.main:app --port 8000`）、
  [user-operation-guide.md](user-operation-guide.md) の手順どおり
  documents → pages（本体 AI の認識テキスト）→ finalize → exam-sessions →
  finalize-reading → solutions（搭載 GPT の解答 ingest）→ review を一巡。
- **期待結果**: 各ステップの HUD ack（scan_ack / reading_ack / ingest_ack）が実機 HUD に出る。
- **反映**: つまずいた箇所を issue 化。読取ミスがあれば**同じ page_index に再送＝置換**
  （API 1.9.0 で追加された再読取）で復旧できることも確認。復旧前の欠番確認は
  `GET /v1/documents/{id}/scan-status?expected_total_pages=N`（API 1.11.0 でも維持）を使う。

### D-2. 搭載 AI の読取品質（U5 チェックリスト）

- **現状の前提**: 搭載 GPT/Gemini が本文・選択肢・問題番号・図の言語化を返せる想定
  （[user-operation-guide.md](user-operation-guide.md) §U5）。
- **実機手順**: 実際の問題用紙（数式・図・表を含むもの）で読取フェーズを実施し、U5 の
  各項目（本文が `ocr_text` に入る / 図が `vision_text` に言語化される / 問N・大問N が
  読める / scan_ack の N/M が合う）を確認。
- **期待結果**: 問題分割（`segment_problems`）が期待どおりの問題数になる。
  0 問検出時は再読取誘導（status "reading" のまま）→ ページ置換 → 再 finalize-reading で
  復旧できる。
- **反映**: 読取が弱いパターン（手書き・小さい図版など）を user-operation-guide.md の
  U5 に追記。境界検出漏れが系統的なら `app/layout.py` の境界パターンを改善。

### D-3. マッチング閾値チューニング（互換の画像照合経路のみ。主経路のテキスト照合は対象外）

- **現状の前提**: `HAMMING_STRONG/WEAK`・`CONF_OK/LOW`・`OCR_MD5_BONUS` は合成画像で調整した
  既定値（implementation-notes.md §7）。
- **実機手順**:
  ```bash
  ROKID_DATA_DIR=data python scripts/evaluate.py --db data/docscan.db --out report.json
  ```
  登録画像から生成したクロップ・微回転・JPEG圧縮クエリに対する
  `variant_match_accuracy`、`variant_top1_accuracy`、`hamming_distribution`、
  `suggested_thresholds` を確認。
- **期待結果**: 変形クエリの HIT/Top-1 が運用目標を満たす。これは頑健性の事前評価であり、
  実機再撮影サンプルでも独立に確認する。
- **反映**: 閾値を `app/matching.py` に反映する場合は **`MATCHER_VERSION` を加算**
  （version.py の bump ルール）。

### D-4. リスニング録音サイズと上限の突合

- **現状の前提**: アップロード上限は 15 MB（`app/main.py` `_MAX_UPLOAD_BYTES`）。超過時も
  `transcript` フォールバックで機能は継続する。
- **実機手順**: 実際のリスニング試験長（例: 共通テスト英語 約 30 分）を実機マイク相当の
  設定で録音し、ファイルサイズを実測（形式・ビットレートも記録）。
- **期待結果**: 上限内に収まる形式の確定、または超過の事実。
- **反映**: 超過するなら `_MAX_UPLOAD_BYTES` の引き上げ（またはクライアント側で分割/圧縮）を
  実測値ベースで判断。

---

## 結果の記録テンプレート

```
機種: Rokid Glasses（機体番号/ファーム: YodaOS-Sprite ____ ）
スマホ: ____（Hi Rokid 版数: ____ / client-l: ____）
日付: ____
B-1 イベント経路: KeyCode / AIDL / 両方（詳細: ____）
B-2 KeyCode 実測: single_tap=__ double_tap=__ long_press=__ swipes=__/__/__/__ back=__
B-3 two_finger_tap: KeyEvent あり(値=__) / なし（AIDL: ____）
B-4 UX 所感: ____
C-1 LED: 読取中 点灯 / finalize-reading 後 消灯（動画: ____）
D-2 読取品質: 問題分割 __/__ 問（弱いパターン: ____）
D-3 accuracy: ____（suggested: strong=__ weak=__）
D-4 録音: __分 → __MB（形式: ____）
```

関連: [real-device-operation.md](real-device-operation.md)（実機運用全般）・
[cxr-l-integration.md](cxr-l-integration.md)（CXR-L 配線）・
[user-operation-guide.md](user-operation-guide.md)（ユーザ操作）・
[rokid-led-dev-utility.md](rokid-led-dev-utility.md)（LED 診断）

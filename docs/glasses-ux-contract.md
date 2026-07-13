# グラス UX 契約（無音・無フラッシュ・無点滅・音声トグル）

本サーバは**サーバ側**実装です。眼鏡（Rokid Glasses）と伴走アプリ（スマホ＝裏方）が
**必ず守るべき表示・操作の規約**をここに定義します。サーバは守れる範囲を強制し
（HUD は最大3行・音/アニメ指示を持たない・本番モードはロック）、残りはクライアント責務です。

## 役割分担

```
[眼鏡: 唯一のUI]  ──BLE/Wi-Fi──  [スマホ伴走アプリ: 裏方]  ──HTTPS──  [本サーバ]
 撮影 / HUD表示 / 物理操作        保存・通信・HUD中継(画面は見せない)     解析・解答・契約
```

- **ユーザーが操作・閲覧するのは眼鏡だけ**。スマホ/PC はポケット・自宅側で通信と AI 処理を担う裏方。
- 接続は CXR-M 伴走アプリ経由、または **CXR-L プラグイン（スマホの Hi Rokid 経由・Bluetooth）**のいずれでも可。サーバから見れば同じ HTTP 契約。
- 実機ハードウェア（**両眼** 480×398 モノクロ緑 Micro-LED 等）と CXR-M/S/L の役割、
  グラス本体 AI（`com.rokid.sprite.aiapp`）との接続は [cxr-l-integration.md](cxr-l-integration.md) を参照。

## 必須要件（外せない）

| 項目 | 規約 |
|------|------|
| **音** | サーバの HUD 応答は音を要求しない。撮影音・通知音の実挙動は端末/クライアント設定で確認する。 |
| **フラッシュ** | サーバは撮影用フラッシュ/トーチや HUD の白フラッシュを要求しない。実挙動は端末側で確認する。 |
| **アニメーション** | 大きいアニメ禁止。テキスト切替は**フェード無しの即時置換**。 |
| **点滅** | 強い点滅禁止。状態は点滅でなく**静的記号**（✓ / ! / ★）で表す。 |
| **輝度** | 10段階調光の**低位**を既定に。 |
| **行数** | HUD は**最大3行**。1 行の文字数はクライアント責務（表示目安 ~24字/行、サーバは切り詰めない）。長文は**ページ送り**（テレプロンプター式）。 |

> サーバ側の担保:
> - `glasses_view` ペイロードは `sound`/`flash`/`animation`/`blink` 等の指示フィールドを**持たず**、`lines` を**最大3行**に制限。
> - `GET /v1/settings` の `hud` を**機械可読の描画契約**として公示：
>   `silent:true, white_flash:false, transition:"instant", brightness:"low", animations:false, blinking:false, max_lines:3`。
>   クライアントは起動時にこれを唯一の権威ソースとして読む。
> - 撮影成功は `capture_ack`（HUD1行・`ttl_sec:2`）で通知する。サーバ応答は音・白フラッシュを指示しない。
> - `GET /v1/settings.capture` は `image_upload:"primary"`、`text_only_input:"supplemental_no_phash"` を公示する。
>   `shutter_sound:false`、`flash:"off"`、`capture_tone:false`、録音の `silent:true` はクライアントへの
>   要求値であり、対応する `*_guaranteed:false` が示すとおり、端末の実音・発光をサーバは保証できない。
> - **プライバシーLEDは端末管理**：`capture.privacy_led` は `state:"on_while_camera_active", tamper:"forbidden"`。
>   サーバは LED を制御・無効化せず、撮影時の表示は実機仕様に従う。
> - `capture.led_off_during_review:true` は、登録後の解答・閲覧で**新規撮影を要求しない**という契約。
>   物理 LED の状態そのものをサーバが保証する値ではない。

## 音声操作トグル（設定 ON/OFF）

- セッション作成時 `voice_enabled`（既定 `false`）。
  - `false`（既定・無音）: ウェイクワード無効。**物理ボタン＋タッチパッド**で操作。
  - `true`: 「Hi Rokid」等の音声操作（公式の「常時リスニング」設定を利用）。
- サーバは `glasses_view.nav.hint` の文言を `voice_enabled` で切替（音声時=「『次へ』と言う」／ボタン時=「タッチパッドで操作」）。

---

## タッチパッド操作マッピング（公式ジェスチャ / KeyCode）

> ジェスチャ名は**現行 Rokid Glasses の公式操作**（2本指タップ=AI起動 / 1本指タップ=クリック /
> ダブルタップ=終了 / 2本指スワイプ上下=スクロール・左右=前後ページ / 長押し=録画⇄録音切替 /
> 首振り=通話応答。スワイプ方向は Hi Rokid アプリでカスタム可）。サーバは gesture→KeyCode を
> **`GET /v1/settings` の `input` ブロック**として機械可読に公示します
> （`app/glasses_view.py` の `build_input_contract()`）。
>
> ⚠️ **KeyCode 値は未検証**：下表の KeyCode は**旧・単眼 Rokid Glass 由来のレガシー表**で、
> 現行の両眼 Rokid Glasses では**実測されていません**（API も `keycodes_verified:false`・
> `keycode_source` で明示）。実機で `adb shell getevent -l` により計測し
> （手順は [real-device-operation.md](real-device-operation.md) §5）、機種/ファーム差は
> サーバ側の環境変数 **`ROKID_KEYMAP`（JSON）** で上書きしてください（クライアント改修不要）。

| ユーザー操作（公式） | gesture 名 | Android KeyCode（旧機由来・未検証） | 本サーバの用途 |
|---|---|---|---|
| **2本指タップ**（AI 起動） | `two_finger_tap` | なし（システムジェスチャ・`keycode:null`） | **ページ画像を撮影・読取**（画像＋本体 AI 認識 → `POST /pages`） |
| **1本指タップ**（クリック） | `single_tap` | `KEYCODE_DPAD_CENTER = 23` | 表示・確認・段階送り（二次経路） |
| **ダブルタップ**（終了） | `double_tap` | `KEYCODE_ENTER = 66` | **読取完了宣言**（読取中）／**閉じる**（閲覧中） |
| **2本指スワイプ左/右**（前後ページ） | `two_finger_swipe_left/right` | `KEYCODE_DPAD_LEFT/RIGHT = 21/22` | **前後の問題**（閲覧）／前後ページ（二次経路） |
| **2本指スワイプ上/下**（スクロール） | `two_finger_swipe_up/down` | `KEYCODE_DPAD_UP/DOWN = 19/20` | テレプロンプター送り/戻し |
| **長押し**（録画⇄録音切替） | `long_press` | `KEYCODE_TV = 170` | **筆記 ⇄ リスニング切替・録音開始/停止**（フェーズ・モーダル） |
| 戻る | `back` | `KEYCODE_BACK = 4` | 前の画面へ戻る |

> `two_finger_tap`（AI 起動）は標準 KeyCode を持たないため `keycode:null` で公示します。
> ファームが KeyEvent として配送する機種では `ROKID_KEYMAP` で割り当ててください。
> **全操作がグラスのジェスチャに割当済みで、スマホは HTTP 中継のみ（画面不要）**。
> ただし**文書作成・`/finalize`・exam セッション作成の 3 呼び出しはジェスチャ未割当**で、
> 読取開始（初回 2本指タップ）／読取完了宣言（ダブルタップ）に連動して**中継アプリが
> 自動発行**します（[cxr-l-integration.md](cxr-l-integration.md) §5）。ユーザーの入力が
> ジェスチャのみで完結するのは、この中継責務まで実装されている前提です。

---

## 操作セット一覧（モード別）

### ページ照合モード（match）

| 操作 | ジェスチャ | 音声ON時 |
|------|-----------|----------|
| 照合用フレーム取得 | クライアント実装に依存 | 「照合」 |
| HUD 確認・閉じる | ダブルタップ | 「閉じる」 |

### 解答モード（exam-sessions・3 フェーズフロー / 主経路 API 1.10）

> **ページ画像の撮影・認識 → 一括解答 → 登録済み内容の閲覧**。
> 完了前に scan-status で欠番・画像なし・認識なしを確認し、不足だけ再撮影する。登録後の解答・閲覧は新規撮影を要求しない。

| フェーズ | 操作 | 公式ジェスチャ | operation 名 | サーバ側処理 |
|----------|------|---------------|--------------|-------------|
| 1 読取 | 読取開始（文書作成） | （初回 2本指タップに連動・中継が自動発行） | — | `POST /v1/documents`（`title` 必須。同じ操作で得た画像＋認識を page_index=0 として pages へ） |
| 1 読取 | ページ画像を撮影・認識 | **2本指タップ**（AI起動） | `capture_read` | `image`＋本体 AI 認識 → `POST /v1/documents/{id}/pages`（scan_ack） |
| 1 読取 | **読取完了宣言** | **ダブルタップ** | `finish_reading` | `GET .../scan-status?expected_total_pages=N` → 不足だけ再撮影 → `/finalize` → exam セッション作成 → `/finalize-reading` |
| 2 解答 | 筆記 ⇄ リスニング切替 | **長押し**（録画⇄録音） | `mode_toggle` | `POST /v1/exam-sessions/{id}/mode` |
| 2 解答 | リスニング録音 開始/停止 | **長押し**（listening 中） | `record_toggle` | `POST /v1/exam-sessions/{id}/audio` |
| 2 解答 | （自動）搭載 GPT が全問解答 | — | — | `POST /v1/exam-sessions/{id}/solutions`（ingest） |
| 3 閲覧 | 次/前の問題 | **2本指スワイプ左/右** | `review_next_problem` / `review_prev_problem` | `GET …/review?index=k±1` |
| 3 閲覧 | テキスト送り/戻し | **2本指スワイプ下/上** | `scroll_next` / `scroll_prev` | `GET …/review?view_page=n±1` |
| 3 閲覧 | 閲覧を閉じる | **ダブルタップ** | `close` | — |

- **ダブルタップはフェーズ・モーダル**：読取中=読取完了宣言／閲覧中=閉じる（公式の「終了」の転用。
  実機 UX 検証待ちの割当として `OPERATION_CONTRACT` のコメントにも明記）。
- **長押しもフェーズ・モーダル**：筆記中=リスニングへ切替／リスニング中=録音開始/停止
  （公式の録画⇄音声録音トグルに合致）。
- `exam_type`＝`written`(筆記) / `listening`(リスニング)、`answer_format`＝`mark`(マーク) / `written`(記述)。
- 1 問題を開くと**解答＋解法＋根拠＋注意が一括 1 ストリーム**（段階なし）。3 行 HUD 制約は
  テレプロンプター送り（2本指スワイプ上下）で送り読み。
- これらの操作↔用途対応は `GET /v1/settings` の `operations` ブロック（`app/glasses_view.py` の
  `OPERATION_CONTRACT`）としても公示。契約上の `finish_reading` が指すのは
  `finalize-reading` のみ——同じダブルタップで先行する `/finalize`・セッション作成は
  **中継アプリの自動チェーン責務**（契約外・クライアント実装）であり、意図的に
  `OPERATION_CONTRACT` に載せていない。

### 資料解説モード（explain-sessions）登録済み文書の閲覧

> 文書登録時に撮影済みのページ画像・認識結果を利用する。セッション作成直後から解説可能（`status=ready`）。
> ページナビゲーション中は新規画像を送信せず、サーバ内の登録済みページを移動する。
> （`POST /scan`・`POST /commit` は v1.7 で廃止済み。）

| フェーズ | 操作 | 公式ジェスチャ | サーバ側処理 |
|----------|------|---------------|-------------|
| ready | 現在ページの解説表示 | 1本指タップ | `GET /explain` |
| explaining | 次ページへ | 2本指スワイプ左 | `POST /next-page`（新規撮影なし） |
| explaining | 前ページへ | 2本指スワイプ右 | `POST /prev-page`（新規撮影なし） |
| explaining | 次テキストスライス | 2本指スワイプ下 | `GET /explain?view_page=N+1` |
| explaining | 前テキストスライス | 2本指スワイプ上 | `GET /explain?view_page=N-1` |
| explaining | 次解説段階（詳細へ） | 1本指タップ（解説表示中） | `GET /explain?stage=detail` |
| explaining | 解説を閉じる | ダブルタップ | — |

### 解答モード（exam-sessions・文書ページ移動型 / 二次経路・互換）

> ページを移動して**現在ページを解く**従来経路（挙動不変で維持）。ページを視認しながら
> 解くため、主経路（3 フェーズ）より LED 点灯時間が長くなります。

| 操作 | 公式ジェスチャ | サーバ側処理 |
|------|---------------|-------------|
| 次/前ページへ | 2本指スワイプ左/右 | `POST /exam-sessions/{id}/next-page`・`/prev-page` |
| 現在ページを解く | 1本指タップ | `POST /exam-sessions/{id}/solve-current` |
| 次の解説段階 | 1本指タップ（解答表示中） | `GET …/questions/{qid}/view?stage=…` |
| テキスト送り/戻し | 2本指スワイプ下/上 | `…/view?page=N±1`（テレプロンプター） |

設問1枚アップロード型（`POST /questions` → `/solve` → `/view`）も同じジェスチャ体系で互換維持。

---

## HUD 表示の形（段階×ページ送り）

### ページ照合モード

```
PAGE 2/5
設計仕様書 v1
conf 0.93  hd 3
```

### 資料解説モード

セッション作成 / ページ移動後のナビ ACK（`ttl_sec:1.5` で自動消去）:

```
→ P02/5
タップで解説
```

先頭ページで前へ操作したとき:

```
← P01/5
先頭ページ
タップで解説
```

解説 HUD（overview 段階）:

```
P01/5 ★★★
（概要テキスト1行目）
タップ 次段階 / 横スワイプ 次ページ
```

解説 HUD（detail 段階）:

```
P01/5 詳細
（詳細テキスト1行目）
タップ 次段階
```

解説 HUD（evidence 段階）:

```
P01/5 根拠
参照: P03, P05
タップ → 概要へ戻る
```

### 解答モード（3 フェーズ）

読取フェーズ（各ページの scan_ack、2秒で消去）:

```
P02 読取済 ✓
2/5ページ完了
次ページへ            ← 全ページ完了時は「完了: ダブルタップ」
```

読取完了（finalize-reading の reading_ack。以降カメラOFF＝LED消灯）:

```
読取完了 5ページ
4問を検出
カメラOFF 解答へ
```

閲覧フェーズ（review デッキ・**一括 1 ストリーム**、`kind:"review"`）:

```
問2 2/4 ★★☆        ← 問題番号 デッキ位置 確信度
答え: ③
解法                 ← 続きは 2本指スワイプ下で送り読み
```

送り読みの続き（同じ問題の view_page=1 以降）:

```
本文の主題を把握する。
根拠
第2段落より。
```

- 1 問題＝**解答＋解法＋根拠＋注意を一括**（段階めくりなし）。空のセクションは省略。
- 未解答の問題は「未解答 / 本体AIの解答待ち」のプレースホルダ（デッキ巡回は可能）。
- 問題送り＝2本指スワイプ左右、送り読み＝2本指スワイプ上下、終了＝ダブルタップ。

### 解答モード（二次経路・段階表示）

```
P02 問3 ★★★      ← answer: ページ/設問 + 確信度記号
答え: B
解答欄: 下右       ← 方向ヒント（紙への固定描画はしない）
```

- 既定段階は `answer`（まず答え）。`solution → rationale → caution` をタップ/音声で遷移。
- 長い解答全文は `page` 送りでグラス内スクロール。
- 一致度・読取信頼度が低いときは断定せず「近づけて再読取」を表示。

---

## 安全（不正利用防止）

- セッション `mode` ∈ `study | mock | real`。**`real` は既定でロック**（`ROKID_ALLOW_REAL_EXAM_SOLVE=1` が無い限り解答非表示）。
- 学習・模試・研究用途のための機能です。本番試験での使用は不正行為になり得ます。

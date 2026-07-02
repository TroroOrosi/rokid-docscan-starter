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
- 接続は CXR-M 伴走アプリ経由、または **CXR-L 単体アプリ＋Wi-Fi 6 直結**のいずれでも可。サーバから見れば同じ HTTP 契約。
- 実機ハードウェア（**両眼** 480×398 モノクロ緑 Micro-LED 等）と CXR-M/S/L の役割、
  グラス本体 AI（`com.rokid.sprite.aiapp`）との接続は [cxr-l-integration.md](cxr-l-integration.md) を参照。

## 必須要件（外せない）

| 項目 | 規約 |
|------|------|
| **音** | シャッター音・通知音・ビープを**一切鳴らさない**。独自カメラ経路（CXR-S/Camera2）で無音撮影。 |
| **フラッシュ** | 写真用フラッシュなし（光るのは消去不可のプライバシーLEDのみ）。HUD の**白フラッシュ禁止**。 |
| **アニメーション** | 大きいアニメ禁止。テキスト切替は**フェード無しの即時置換**。 |
| **点滅** | 強い点滅禁止。状態は点滅でなく**静的記号**（✓ / ! / ★）で表す。 |
| **輝度** | 10段階調光の**低位**を既定に。 |
| **行数** | HUD は**最大3行・短文**（日本語 ~24字/行）。長文は**ページ送り**（テレプロンプター式）。 |

> サーバ側の担保:
> - `glasses_view` ペイロードは `sound`/`flash`/`animation`/`blink` 等の指示フィールドを**持たず**、`lines` を**最大3行**に制限。
> - `GET /v1/settings` の `hud` を**機械可読の描画契約**として公示：
>   `silent:true, white_flash:false, transition:"instant", brightness:"low", animations:false, blinking:false, max_lines:3`。
>   クライアントは起動時にこれを唯一の権威ソースとして読む。
> - 撮影成功は**無音・無白フラッシュ**の `capture_ack`（HUD1行・`ttl_sec:2`、音/フラッシュ指示なし）で通知。シャッター音や白フラッシュの代替。
> - `GET /v1/settings` の `capture` で **撮影しない**方針を機械可読に公示：`shutter_sound:false`・`flash:"off"`
>   （撮影用フラッシュ/トーチなし）・`capture_tone:false`（無音撮影）・`audio_record:{start_tone:false, stop_tone:false, silent:true}`
>   （リスニング録音も無音）。独自カメラ経路 `cxr-s/camera2`。**フラッシュ・シャッター音・録音音を出さない**。
> - **プライバシーLEDは不可侵**：`capture.privacy_led` を `state:"always_on", tamper:"forbidden"` として公示し、**サーバはLEDを制御・無効化する機能を一切持たない**（カメラ動作中のみ点灯するハードのプライバシー表示。フラッシュではない）。

## 音声操作トグル（設定 ON/OFF）

- セッション作成時 `voice_enabled`（既定 `false`）。
  - `false`（既定・無音）: ウェイクワード無効。**物理ボタン＋タッチパッド**で操作。
  - `true`: 「Hi Rokid」等の音声操作（公式の「常時リスニング」設定を利用）。
- サーバは `glasses_view.nav.hint` の文言を `voice_enabled` で切替（音声時=「『次へ』と言う」／ボタン時=「タッチパッドで操作」）。

---

## タッチパッド操作マッピング（KeyCode）

> 下表は現行の Rokid マッピングです。サーバは gesture→KeyCode を
> **`GET /v1/settings` の `input` ブロック**として機械可読に公示します
> （`app/glasses_view.py` の `INPUT_CONTRACT`）。機種/ファーム差がある場合は、
> サーバ側の環境変数 **`ROKID_KEYMAP`（JSON）** で上書きでき、クライアント改修は
> 不要です（計測手順は [real-device-operation.md](real-device-operation.md) §5）。

| ユーザー操作 | Android KeyCode | 本サーバの用途 |
|---|---|---|
| **TP-単击**（タップ） | `KEYCODE_DPAD_CENTER = 23` | 解説表示・確認（explain-sessions / exam-sessions） |
| **TP-長按** | `KEYCODE_TV = 170` | 解説段階を進める（overview→detail→evidence） |
| **TP-双击**（ダブルタップ） | `KEYCODE_ENTER = 66` | 現在のビューを閉じる |
| **TP-右滑**（スワイプ右） | `KEYCODE_DPAD_RIGHT = 22`（連続） | 前テキストスライス（テレプロンプター戻し） |
| **TP-左滑**（スワイプ左） | `KEYCODE_DPAD_LEFT = 21`（連続） | 次テキストスライス（テレプロンプター送り） |
| **TP-快速右滑**（速スワイプ右） | `KEYCODE_DPAD_DOWN = 20`（単発） | 前ページへ（`POST /prev-page`） |
| **TP-快速左滑**（速スワイプ左） | `KEYCODE_DPAD_UP = 19`（単発） | 次ページへ（`POST /next-page`） |
| **Back-単**（戻るボタン） | `KEYCODE_BACK = 4` | 前の画面へ戻る |
| **Back-長**（長押し） | Intent `homekey.longpress`（`back_long_press`） | **筆記 ⇄ リスニング 切替**（`POST /exam-sessions/{id}/mode`） |
| **TP-双指長按**（二本指長押し） | 独自ジェスチャ（`two_finger_long_press`） | **リスニング録音の開始/停止**（`POST /exam-sessions/{id}/audio`） |

> ⚠️ **スワイプ方向の注意**: 公式キーコード定義では、TP-快速左滑（速スワイプ左）が `KEYCODE_DPAD_UP`（上）、TP-快速右滑（速スワイプ右）が `KEYCODE_DPAD_DOWN`（下）に割り当てられています。方向名と物理操作が直感と逆に見えることがありますが、Rokid 公式仕様に従っています。クライアント実装時は必ず上記の KeyCode でリッスンしてください。
>
> `back_long_press` / `two_finger_long_press` は標準 KeyCode を持たないため、`input.gestures` では `keycode:null`（Intent/独自ジェスチャ）として公示します。機種で具体的な KeyCode を割り当てたい場合は `ROKID_KEYMAP` で上書きできます。**全操作がグラスのジェスチャに割当済みで、スマホは HTTP 中継のみ（画面不要）**。

---

## 操作セット一覧（モード別）

### ページ照合モード（match）

| 操作 | TP/ボタン | 音声ON時 |
|------|-----------|----------|
| 撮影 | Back-単（1回押し） | 「撮影」 |
| HUD 確認・閉じる | TP-双击 | 「閉じる」 |

### 資料解説モード（explain-sessions）v1.7 撮影なし設計

> **v1.7 の設計原則**: スキャンフェーズ（撮影）なし。セッション作成直後から解説可能（`status=ready`）。
> ページナビゲーションはボタン操作のみ。カメラ画像は一切送信しない。

| フェーズ | 操作 | TP/ボタン | KeyCode | サーバ側処理 |
|----------|------|-----------|---------|-------------|
| ready | 現在ページの解説表示 | TP-単击 | `KEYCODE_DPAD_CENTER (23)` | `GET /explain` |
| explaining | 次ページへ | TP-快速左滑 | `KEYCODE_DPAD_UP (19)` 単発 | `POST /next-page`（撮影なし） |
| explaining | 前ページへ | TP-快速右滑 | `KEYCODE_DPAD_DOWN (20)` 単発 | `POST /prev-page`（撮影なし） |
| explaining | 次テキストスライス | TP-左滑 | `KEYCODE_DPAD_LEFT (21)` 連続 | `GET /explain?view_page=N+1` |
| explaining | 前テキストスライス | TP-右滑 | `KEYCODE_DPAD_RIGHT (22)` 連続 | `GET /explain?view_page=N-1` |
| explaining | 次解説段階（詳細へ） | TP-長按 | `KEYCODE_TV (170)` | `GET /explain?stage=detail` |
| explaining | 解説を閉じる | TP-双击 | `KEYCODE_ENTER (66)` | — |

#### 廃止されたエンドポイント（v1.6 → v1.7）

| 旧操作 | 旧エンドポイント | 廃止理由 |
|--------|----------------|----------|
| ページ撮影スキャン | `POST /scan`（画像アップロード） | 撮影不要設計へ移行 |
| 全ページ読取完了宣言 | `POST /commit`（ダブル長押し） | scanningフェーズ廃止 |

### 解答モード（exam-sessions・設問1枚アップロード型）

| 操作 | TP/ボタン | 音声ON時 |
|------|-----------|----------|
| 撮影 | Back-単 | 「撮影」 |
| 解答表示 | TP-単击 | 「答えを表示」 |
| 次の解説段階 | TP-長按 | 「詳しく」 |
| 次テキストページ | TP-左滑 | 「次へ」 |
| 前テキストページ | TP-右滑 | 「前へ」 |
| 閉じる | TP-双击 | 「閉じる」 |

### 解答モード（exam-sessions・文書ページ移動型 / 撮影レス・主経路 v1.7）

> 全ページを撮影レスで登録・`finalize`（＝全ページ読込完了）してから、ページを移動して
> **現在ページを解く**。カメラ撮影は一切発生せず、操作はグラス単独で完結。

| 操作 | TP/ボタン | KeyCode / ジェスチャ | サーバ側処理 |
|------|-----------|----------------------|-------------|
| 次ページへ | TP-快速左滑 | `KEYCODE_DPAD_UP (19)` 単発 | `POST /exam-sessions/{id}/next-page` |
| 前ページへ | TP-快速右滑 | `KEYCODE_DPAD_DOWN (20)` 単発 | `POST /exam-sessions/{id}/prev-page` |
| 現在ページを解く | TP-単击 | `KEYCODE_DPAD_CENTER (23)` | `POST /exam-sessions/{id}/solve-current` |
| 次の解説段階 | TP-長按 | `KEYCODE_TV (170)` | `GET …/questions/{qid}/view?stage=…` |
| テキスト送り/戻し | TP-左/右滑 | `KEYCODE_DPAD_LEFT/RIGHT (21/22)` | `…/view?page=N±1`（テレプロンプター） |
| 筆記 ⇄ リスニング切替 | Back-長按 | `back_long_press`（Intent） | `POST /exam-sessions/{id}/mode` |
| リスニング録音 開始/停止 | TP-双指長按 | `two_finger_long_press`（独自） | `POST /exam-sessions/{id}/audio` |

- `exam_type`＝`written`(筆記) / `listening`(リスニング)、`answer_format`＝`mark`(マーク) / `written`(記述)。
- リスニングは音声を**その場で録音**し、設問は**目の前の資料から読取**（`solve-current` が書き起こしと資料を統合）。
- これらの操作↔用途対応は `GET /v1/settings` の `operations` ブロック（`app/glasses_view.py` の `OPERATION_CONTRACT`）としても公示。

---

## HUD 表示の形（段階×ページ送り）

### ページ照合モード

```
PAGE 2/5
設計仕様書 v1
conf 0.93  hd 3
```

### 資料解説モード（v1.7）

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
長押し 次段階 / 速スワイプ 次ページ
```

解説 HUD（detail 段階）:

```
P01/5 詳細
（詳細テキスト1行目）
長押し 次段階
```

解説 HUD（evidence 段階）:

```
P01/5 根拠
参照: P03, P05
長押し → 概要へ戻る
```

### 解答モード

```
P02 問3 ★★★      ← answer: ページ/設問 + 確信度記号
答え: B
解答欄: 下右       ← 方向ヒント（紙への固定描画はしない）
```

- 既定段階は `answer`（まず答え）。`solution → rationale → caution` をスワイプ/音声で遷移。
- 長い解答全文は `page` 送りでグラス内スクロール。
- 一致度・読取信頼度が低いときは断定せず「近づけて再撮影」を表示。

---

## 安全（不正利用防止）

- セッション `mode` ∈ `study | mock | real`。**`real` は既定でロック**（`ROKID_ALLOW_REAL_EXAM_SOLVE=1` が無い限り解答非表示）。
- 学習・模試・研究用途のための機能です。本番試験での使用は不正行為になり得ます。

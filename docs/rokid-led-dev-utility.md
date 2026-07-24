# Rokid 録画インジケータ LED 開発用診断ツール / Recording-LED Dev Utility

> **⚠️ 重要 / IMPORTANT — 必ず読んでください**
>
> - これは **開発者が自分で所有・管理する実機** に対してのみ使う、**サーバとは独立した
>   診断ツール** です。FastAPI サーバや文書スキャン／解答フローからは **一切呼ばれません**。
> - サーバの契約（`app/glasses_view.py` の `CAPTURE_CONTRACT`）は引き続き録画 LED を
>   **`on_while_camera_active / tamper:forbidden`**（カメラ稼働中は必ず点灯・改変不可）と公示します。
>   本ツールはその契約を変更しません。点灯時間を短くする正攻法は 3 フェーズフロー（読取フェーズの
>   最短化・`led_off_during_review:true`）であり、LED の無効化ではありません。
> - **録画インジケータ（プライバシー LED）を無効化する確実な非 root・ソフトウェアのみの
>   方法は確認されていません。** 本ツールの `disable` は **未確認の仮説** であり、root /
>   SELinux ポリシー変更が必要な場合や、まったく効かない場合があります。
> - 録画インジケータの無効化は **法的に違法となりうる行為** であり倫理的にも問題があります。
>   **自分が所有・管理する端末** に対し、**現地法と「録画は見える形で行う」期待**に従って、
>   管理された開発環境でのみ使用してください。
>
> This is an out-of-band developer diagnostic tool for hardware **you own and
> control**. It is **never imported by the server** or the doc-scan / exam flows.
> There is **no confirmed non-root, software-only** way to disable the recording
> LED on consumer Rokid AI Glasses; `disable` here is an **unconfirmed hypothesis**
> that may require root / SELinux changes or may not work at all. Defeating a
> recording indicator can be **illegal** — own-device development use only, in
> compliance with local law and visible-recording expectations.

---

## 2026-07-24 時点で確認できた範囲 / What is actually verified

- 一般向け **Rokid Glasses** の[日本公式 FAQ](https://jp.rokid.com/pages/faqs)は、
  カメラ動作中の LED は消せず、LED を隠すとカメラが起動しないと明記しています。
- このリポジトリが使う公式
  [`com.rokid.cxr:client-l:1.0.1`](https://maven.rokid.com/repository/maven-public/com/rokid/cxr/client-l/1.0.1/client-l-1.0.1.aar)
  の `IMediaStreamService` 公開メソッドを確認しましたが、LED / capture-light
  制御 API は含まれていません。
- 別製品系統の **Rokid Glass3 Enterprise** 用
  [`glass3.open.sdk`](https://x-docs.rokid.com/docs/terminal-sdk/api-reference/Glass3%20%20SDK%28%E7%9C%BC%E9%95%9C%E7%AB%AF%29%20API%E6%96%87%E6%A1%A3.html)
  には `IDeviceService.setCameraLedEnable(boolean)` が公開されています。これは Glass3
  上で動く眼鏡側 SDK / system service の API であり、本リポジトリの一般向け Glasses +
  Global Hi Rokid + スマホ側 CXR-L 構成へそのまま移植できる証拠ではありません。
- [Rokid Glasses のセキュリティ調査](https://www.secrss.com/articles/85621?app=1)でも、
  LED は system アプリが一元管理し、一般アプリからは直接制御できない一方、system
  制御権を得た状態では切替可能と報告されています。
- `vendor.rkd.camera.session_open` と `/sys/class/leds/white` を使う本ツールの経路は、
  公開資料で裏付けられた一般向け Glasses の API ではありません。root / system 権限と
  機種・ファームウェア固有ノードが揃えば動く可能性はありますが、接続実機での物理確認までは
  完了していないため、引き続き **未確認の仮説** として扱います。

結論として、LED ハードウェアが絶対に消せないわけではありません。しかし、一般向け純正
ファームウェア上の CXR-L アプリから確実に消せる方法は確認できていません。実機検証では
`probe` でノードと権限を先に確認し、`verify` の読み戻しに加えて別カメラで物理 LED を
確認してください。

---

## なぜこのツールは「dry-run 既定＋明示フラグ」なのか / Why it is gated

リポジトリ全体の安全方針（本番試験解答が既定でロックされているのと同じ思想）に合わせ、
副作用のある操作は **二段ゲート** で守られています。

| 操作 | 種別 | 既定 | 実行に必要なフラグ |
|------|------|------|--------------------|
| `connect` | adb 接続のみ | dry-run | `--apply` |
| `probe`   | 読み取り専用 | dry-run | `--apply` |
| `status`  | 読み取り専用 | dry-run | `--apply` |
| `disable` | **書き込み（LED 状態変更）** | dry-run | `--apply` **かつ** `--force` |
| `restore` | **書き込み（undo）** | dry-run | `--apply` **かつ** `--force` |
| `verify`  | status→**disable（書き込み）**→status＋判定 | dry-run | `--apply` **かつ** `--force` |

- **既定は常に dry-run**：コマンド列を表示するだけで、端末には何も送りません。
- `--apply` を付けて初めて実際に実行します。
- `disable` / `restore` は端末状態を変えるため、`--apply` に加えて `--force` が必須です。
  `--apply` だけで write 操作を呼ぶと **ブロックされ、exit code 2** で終了します。

---

## 前提 / Prerequisites

- `adb`（Android Platform Tools）が PATH にあること。無い場合、各ステップは
  「adb not found on PATH」としてスキップ報告されます（クラッシュしません）。
- グラスが USB デバッグ可能で `adb devices` に出ること（[user-operation-guide](user-operation-guide.md) U2）。

---

## 使い方 / Usage

### 1. ワイヤレス ADB 接続コマンドを確認（dry-run）

```bash
python scripts/rokid_led.py connect 192.168.1.50
# 表示されるコマンド:
#   adb tcpip 5555
#   adb connect 192.168.1.50:5555
```

実際に接続する場合は `--apply` を付けます（眼鏡の IP アドレスに置き換えてください）:

```bash
python scripts/rokid_led.py connect 192.168.1.50 --apply
```

### 2. LED ノード / プロパティ / SELinux 状態を探索（読み取り専用）

```bash
python scripts/rokid_led.py probe --host 192.168.1.50:5555 --apply
```

確認内容: `adb devices` / `getenforce` / `ls /sys/class/leds` /
`ls /sys/class/leds/white` / `getprop vendor.rkd.camera.session_open` /
`getprop | grep -i led` / `... grep -i light`。

> `getenforce` が `Enforcing` を返す場合、sysfs への書き込みは root / SELinux
> ポリシー緩和なしには失敗する可能性が高いです。

### 3. 現在の LED 状態を確認（読み取り専用、変更前後の記録に）

```bash
python scripts/rokid_led.py status --host 192.168.1.50:5555 --apply
```

### 4. 無効化を「計画だけ」表示（既定 dry-run・何も実行しない）

```bash
python scripts/rokid_led.py disable --led white
```

### 5. 自分の端末で実際に試行（両方のフラグが必須）

```bash
python scripts/rokid_led.py disable --led white --host 192.168.1.50:5555 --apply --force
```

`disable` が試行する内容（仮説）:

```sh
setprop vendor.rkd.camera.session_open 0
echo 0    > /sys/class/leds/white/brightness
echo none > /sys/class/leds/white/trigger
echo 0    > /sys/class/leds/white/brightness   # トリガ変更後に再度 0
```

### 6. 元に戻す（best-effort undo）

```bash
python scripts/rokid_led.py restore --led white --host 192.168.1.50:5555 --apply --force
# 確実なクリーン状態にはグラスの再起動を推奨。
```

### JSON 出力（ツール連携用）

```bash
python scripts/rokid_led.py probe --json
```

---

## `verify`：実機での「本当に消えたか」検証 / Evidence-based verification

`disable` の ADB コマンドが `rc=0` で終わっても、それは **物理 LED が消えた証明には
なりません**。次のような乖離が普通に起きます:

- 非 root シェルへのリダイレクト書き込みがカーネルに **黙って拒否**されても、シェルは `0` を返す。
- SELinux がシェル終了後に書き込みを拒否する。
- ベンダの init / Lights HAL サービスが数ミリ秒〜数秒後に **LED を再点灯**させる。

`verify` は **status（前）→ disable → status（後）** を実行し、**読み戻した brightness の値**
から状態を判定します。判定は ADB の終了コードとは **明確に分離**されます。

| フィールド | 意味 |
|------------|------|
| `write_succeeded` | disable コマンドが全て `rc=0`。**物理状態の証明ではない**。 |
| `verified_state`  | `off` / `on` / `unknown`。**brightness 読み戻しのみ**が根拠。 |
| `confirmed_off`   | `brightness == 0` を実際に読めたときだけ `true`。 |
| `reasserted`      | 一度 0 を読んだ後に再点灯（init/HAL の再アサート）を検知。 |
| `attempts`        | disable を実行した回数（`--retries` での再アサートを含む）。 |

`verified_state` の判定規則（保守的）:

- `brightness` を **読めない**（permission denied / ノード無し / 空 / rc≠0）→ `unknown`。
  **決して `off` とは見なしません**（「0 が読めた」ことだけが off の根拠）。
- `brightness == 0` → `off`、`> 0` → `on`。

### 手順 / Step-by-step

```bash
# 0. 前提: adb が PATH にあり、`adb devices` にグラスが出ること。
#    まず probe で LED ノード名（既定 white）と SELinux 状態を確認:
python scripts/rokid_led.py probe --host 192.168.1.50:5555 --apply

# 1. 計画だけ確認（dry-run・何も実行しない・状態は unknown）:
python scripts/rokid_led.py verify --led white

# 2. 自分の端末で実検証（両フラグ必須）。再点灯対策に最大3回まで再アサートし、
#    issue/PR に添付できる JSON 証跡を書き出す:
python scripts/rokid_led.py verify --led white --host 192.168.1.50:5555 \
    --apply --force --retries 3 --evidence-out led-evidence.json

# 3. 終わったら必ず元に戻す（または再起動）:
python scripts/rokid_led.py restore --led white --host 192.168.1.50:5555 --apply --force
```

### 期待される出力 / Expected output

成功（LED が 0 を読み戻した）場合の human 出力（抜粋）:

```
HEADLINE:  LED reads OFF (brightness=0) — confirm visually with a 2nd camera
  write_succeeded: True   (adb commands exited 0 — NOT proof of physical state)
  verified_state:  off    (from brightness readback)
  confirmed_off:   True
snapshots:
  before: brightness=255 max=255 trigger=none ...=0 selinux=Permissive readable=True
  after : brightness=0   max=255 trigger=none ...=0 selinux=Permissive readable=True
```

`--json` / `--evidence-out` の証跡 JSON（抜粋）:

```json
{
  "headline": "LED reads OFF (brightness=0) — confirm visually with a 2nd camera",
  "write_succeeded": true,
  "verified_state": "off",
  "confirmed_off": true,
  "attempts": 1,
  "reasserted": false,
  "before": { "brightness": 255, "trigger": "none", "enforcing": "Permissive", "readable": true },
  "after":  { "brightness": 0,   "trigger": "none", "enforcing": "Permissive", "readable": true }
}
```

### 成否の判定 / How to judge success vs failure

| 出力 | 解釈 | 終了コード |
|------|------|:---------:|
| `confirmed_off: true` | brightness=0 を読めた。**ただし物理確認は別途必須**（下記）。 | 0 |
| `verified_state: on` ＋ `write_succeeded: true` | コマンドは成功したが LED は点灯のまま＝**再アサートされた／効いていない**。 | 4 |
| `verified_state: unknown` | brightness を読めない＝**検証不能**（非 root で `/sys` を読めない等）。 | 3 |
| `BLOCKED` | `--force` 無しで write を呼んだ。 | 2 |
| dry-run | 何も実行していない。 | 0 |

### 外部カメラによる物理確認は必須 / External visual confirmation is required

**ADB が成功しても、`confirmed_off: true` でも、それだけでは「他人から見て LED が消えている」
証明にはなりません。** 必ず:

1. **別のスマホ／カメラでグラスの録画 LED を録画しながら** `verify --apply --force` を実行する。
2. 録画映像で LED が **実際に消灯したか** を目視確認する（一瞬だけ消えて再点灯する場合もある）。
3. `reasserted: true` や、目視で点滅・再点灯が見えたら **「消えていない」** と判断する。
4. 検証後は `restore` または **再起動** で必ず元の状態に戻す。

---

## 既知の制約と不確実性 / Known constraints & uncertainty

- **非 root の adb shell は `/sys/class/leds/...` に書けない／読めないのが通常**。`disable` が
  「Permission denied」になるのは想定内です。読めない場合 `verify` は `unknown`（off とは
  見なさない）を返します。
- **`verify` の `confirmed_off` は sysfs の brightness 読み戻しに依存**します。ノードを読めない
  端末では検証不能（`unknown`）となり、`write_succeeded: true` でも「消えた」とは判定しません。
  最終判断は必ず外部カメラの目視で行ってください。
- **SELinux**（`getenforce` / `setenforce 0`）、ベンダ `init.rokid.rc`、Magisk ポリシー
  などが LED を再点灯させたり書き込みを拒否したりする可能性があります。
- `vendor.rkd.camera.session_open` が `init.rokid.rc` 経由で
  `/sys/class/leds/white/brightness` を駆動するという経路は **仮説** であり、機種・ファーム
  により異なります。LED ノード名（既定 `white`）も実機では違う場合があるため、まず `probe`
  で確認してください。
- Qualcomm Lights HAL（`vendor.qti.hardware.lights.service`）や `LightsManager` を使う
  カスタム APK 経路も理論上ありえますが、本リポジトリは Android アプリ構成を持たないため、
  本ツールは ADB/sysfs の診断に限定しています。

---

## 設計メモ / Design

- ロジックは `app/devtools/rokid_led.py`：各操作を **データ（`Plan` / `Command`）として構築**
  する純粋関数群（副作用なし・import 時に何も実行しない）と、`--apply` / `--force` ゲートを
  適用する `execute_plan()` に分離。`subprocess.run` は注入可能で、テストはプロセスを起動せず
  argv を検証します。
- 検証層：`parse_status()` が `status` の読み戻しを `LedSnapshot` に構造化し、`verdict_for()`
  が保守的に `off`/`on`/`unknown` を判定。`run_verification()` が status→disable→status を
  オーケストレーションし、`--force` 無しの apply は **デバイスを読む前に** ブロックします
  （`execute_plan` と同じゲート）。再アサート検知・再試行は `sleep` 注入でテスト可能。
- CLI は `scripts/rokid_led.py`（`scripts/evaluate.py` と同じ argparse スタイル）。`verify`
  は `--retries` / `--retry-delay` / `--evidence-out` を持ち、終了コードで状態を表します
  （0=confirmed off/dry-run、2=blocked、3=unknown、4=still on）。
- テストは `tests/test_rokid_led.py`：コマンド構築・dry-run・安全ゲートに加え、読み戻しの
  パース・判定（off/on/unknown）・再アサート検知・JSON 証跡・失敗モードを検証。

# Rokid 録画インジケータ LED 開発用診断ツール / Recording-LED Dev Utility

> **⚠️ 重要 / IMPORTANT — 必ず読んでください**
>
> - これは **開発者が自分で所有・管理する実機** に対してのみ使う、**サーバとは独立した
>   診断ツール** です。FastAPI サーバや文書スキャン／解答フローからは **一切呼ばれません**。
> - サーバの契約（`app/glasses_view.py` の `CAPTURE_CONTRACT`）は引き続き録画 LED を
>   **`always_on / tamper:forbidden`** と公示します。本ツールはその契約を変更しません。
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

## 既知の制約と不確実性 / Known constraints & uncertainty

- **非 root の adb shell は `/sys/class/leds/...` に書けないのが通常**。`disable` が
  「Permission denied」になるのは想定内です。
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
- CLI は `scripts/rokid_led.py`（`scripts/evaluate.py` と同じ argparse スタイル）。
- テストは `tests/test_rokid_led.py`：コマンド構築・dry-run・安全ゲートを検証。

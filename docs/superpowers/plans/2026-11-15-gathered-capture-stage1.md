# Gathered Capture, Stage 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Status: 実施計画（2026-11-15、本人の承認「承認、進めてよい」を受けて作成）。段階1だけを扱う。Runs on: PC、スマホ（Termux）、机上のグラス（計測アプリ）。掛けない。会場の構成ではない。

**Goal:** 録画から1頁の画像を作る重ね合わせのモジュールを作り、設計の合格条件 G1〜G3 と、設計が「未確認」とした録画の性質を机上で測って、段階2へ進めるかを判定する。

**Architecture:** 重ね合わせは numpy の純粋な関数（フレームの配列を受け取り、選び、帯域を絞った相関で置き、2倍の格子へ足す）。動画の読み出しだけが ffmpeg を呼ぶ。グラス側は計測アプリ `:glassprobe` に「待つ→録る」を繰り返す型を足して測るだけで、本番アプリ `:glassdoc` には触れない。

**Tech Stack:** Python 3.12、numpy、Pillow、ffmpeg（PC とスマホに導入済み）、pytest。Android は Java（camera2、`MediaRecorder`、`TextureView`）。

**Spec:** `docs/superpowers/specs/2026-11-15-gathered-capture-design.md`（6.3、6.5、9章、10章の段階1）。測定の出所は `docs/hardware-measurements.md` §M-24・§M-25。

## Global Constraints

- 足し合わせは測った光の平均だけ。文字を作る・補う処理を入れない（設計 6.7）。入力の録画は書き換えない。
- 位置合わせは帯域を絞った相関を「足し終えた和」に対して取る。位相相関は使わない（§M-25 (5)）。
- 足す格子は、入力の画素の2倍の細かさ（E13：細かい格子なしは誤り 21.2%）。
- 流れの上限は、センサーの画素で 2 画素（設計 6.3）。
- 依存は numpy と ffmpeg まで。scipy・OpenCV は G1 を外した時だけ（設計 6.5）。スマホの numpy は Termux の `python-numpy`。`requirements-phone.txt` には足さない（pip では組み立てになる）。
- `:glassdoc` と本番のサーバーの経路は変えない（それは段階3）。本番アプリを強制停止しない。モデルへは何も送らない。
- 実機：操作する機器を毎回名指しし、シリアルを確かめる。端末上でダンプを早く閉じるフィルターへ流さない。計測アプリは導入後に `cmd package compile -m speed -f` を行う。ギャラリーに写真を足さない。
- 掛けるお願いも、冊子を置くお願いも、この段階ではしない。
- 文書：完了・確認済みと書く時は、コマンドと出力を併記する。机上の測定を実機の使用の確認と呼ばない。

## Review Focus

1. 途中で景色が変わった録画（視線が外れた、手が入った）：置けないフレームは捨て、過半が置けなければ `placed=False` を返す。にじんだ画像を「成功」として返さない。→ Task 1
2. 流れていないフレームが 1 枚も無い録画：例外を出さず、`used=0`・`placed=False` を返す。→ Task 1
3. 添えた記録が無い、またはフレーム数が録画と合わない：選別なしで全フレームを使い、その旨を結果に残す。→ Task 3
4. ffmpeg が無い・動画が壊れている：理由つきの例外で止まる（黙って待ち続けない）。→ Task 3
5. 明るい場面（白とびに近いフレーム）：桁あふれせず、結果が元の明るさの範囲に収まる。→ Task 1

---

### Task 1: 置いて足す（配列だけを扱う中核）

**Files:**
- Create: app/gather.py
- Test: tests/test_gather.py
- Modify: `requirements.txt`（`numpy>=1.26` を足す。試験は `pytest.importorskip("numpy")` で、numpy の無い CI の組では飛ばす）

**Interfaces:**
- Produces:

```python
def shift_of(frame: np.ndarray, reference: np.ndarray, around: tuple[float, float] = (0.0, 0.0), reach: float = 4.0) -> tuple[float, float, float]:
    """(dy, dx, strength): frame(y, x) = reference(y - dy, x - dx); strength = peak / spread of the correlation surface."""

@dataclass(frozen=True)
class Gathered:
    image: np.ndarray        # float32, light, shape = (grid * h, grid * w)
    used: int                # frames added
    total: int               # frames offered
    level_over_noise: float  # of the result, from two halves of the frames added; 0.0 when fewer than 4 were added
    placed: bool             # False when fewer than half of the unsmeared frames could be placed, or none was usable
    selection: str           # "motion" when smear values chose the frames, "none" when every frame was offered

def gather(frames: Iterable[np.ndarray], *, smear: Sequence[float] | None = None, smear_limit: float = 2.0, grid: int = 2) -> Gathered:
    """frames: 2-D float32 arrays of light, all one shape. smear: per frame, pixels moved during its exposure."""
```

- [ ] **Step 1: 試験を書く**（tests/test_gather.py。場面は乱数で作る印字のような模様。個人の写真は使わない）

```python
np = pytest.importorskip("numpy")
from app import gather as g

def scene(seed=1, h=384, w=512):            # paper 0.6, dark strokes 2-4 px wide on a 16 px pitch
def moved(image, dy, dx):                   # sub-pixel shift by a phase ramp on a mirrored copy
def joined(image):                          # 2x2 mean
def frames(scene, shifts, snr1, seed=2):    # joined(moved(scene)) + noise of paper / (2 * snr1), clipped at 0
def alike(a, b):                            # correlation inside a 24 px margin

def test_shift_of_finds_a_known_shift_under_the_venue_noise():
    s = scene(); ref = sum(frames(s, [(0, 0)] * 8, 2.2)) / 8
    dy, dx, strength = g.shift_of(frames(s, [(3.0, -5.0)], 2.2)[0], ref, around=(1.0, -2.0), reach=4.0)
    assert abs(2 * dy - 3.0) <= 0.5 and abs(2 * dx + 5.0) <= 0.5 and strength > 5

def test_gathered_page_keeps_detail_that_plain_averaging_loses():
    s = scene(); walk = np.cumsum(np.random.default_rng(3).normal(0, 0.8, (120, 2)), axis=0); walk -= walk[0]
    fs = frames(s, walk, 2.2)
    result = g.gather(fs)
    plain = np.repeat(np.repeat(sum(fs) / len(fs), 2, 0), 2, 1)
    assert result.placed and result.used >= 110 and result.image.shape == s.shape
    assert alike(result.image, s) > 0.9 and alike(result.image, s) > alike(plain, s) + 0.02

def test_level_over_noise_grows_with_the_frames_added():
    s = scene(); few = g.gather(frames(s, [(0, 0)] * 16, 2.2)); many = g.gather(frames(s, [(0, 0)] * 64, 2.2))
    assert 1.6 < many.level_over_noise / few.level_over_noise < 2.4      # square root of 4

def test_smeared_frames_are_left_out():
    s = scene(); fs = frames(s, [(0, 0)] * 40, 2.2)
    result = g.gather(fs, smear=[0.5] * 20 + [6.0] * 20)
    assert result.used == 20 and result.total == 40 and result.selection == "motion"

def test_a_changed_scene_is_not_added():           # Review Focus 1
    a, b = scene(1), scene(9)
    mixed = g.gather(frames(a, [(0, 0)] * 30, 2.2) + frames(b, [(0, 0)] * 10, 2.2))
    assert mixed.placed and mixed.used <= 32 and alike(mixed.image, a) > 0.9
    lost = g.gather(frames(a, [(0, 0)] * 6, 2.2) + frames(b, [(0, 0)] * 30, 2.2, seed=5))
    assert not lost.placed

def test_no_usable_frame_is_an_answer_not_an_error():   # Review Focus 2
    result = g.gather(frames(scene(), [(0, 0)] * 5, 2.2), smear=[9.0] * 5)
    assert (result.used, result.placed, result.level_over_noise) == (0, False, 0.0)

def test_bright_frames_stay_in_range():                  # Review Focus 5
    bright = [np.full((96, 128), 0.98, np.float32) for _ in range(12)]
    result = g.gather(bright)
    assert np.isfinite(result.image).all() and 0.9 < float(result.image.mean()) < 1.05
```

- [ ] **Step 2: 失敗を確かめる** — `py -3.12 -m pytest -q tests/test_gather.py` → `ModuleNotFoundError` か `AttributeError`（numpy を `py -3.12 -m pip install "numpy>=1.26"` で入れた後）
- [ ] **Step 3: `shift_of` と `gather` を app/gather.py に書く**

決めてあること（試験と署名からは決まらない部分）：
- 帯域：周波数の半径 r（1 画素あたりの周期）について、`r > 4 / min(h, w)` を通し、`exp(-(r / 0.17) ** 2)` を掛ける。窓は Hann。山は `around` から半径 `reach` の中だけで探し、放物線で画素より細かく読む（§M-25 の模擬と同じ）。
- 基準：最初の 8 枚（流れの上限以内のもの）はずれ 0 として和を作らず、1枚目を基準にして順に置く。以後は「置いたフレームを整数画素で戻した和」を基準にする。
- 置けたと見なす条件：`strength` が、同じ録画の先頭 8 枚の中央値の 0.5 倍以上。置けないフレームは捨てる。探す中心は直前に置けたフレームの位置。
- 足し方：フレームの画素 (j, i) の中心は場面の位置 `(grid * j + grid / 2 - dy_g, …)`（`dy_g` は格子の画素でのずれ）。前後2つの格子の画素へ距離の重みで分けて足し（4か所）、重みの和で割る。重みが中央値の 5% 未満の画素は、整数画素で足した平均を拡大した値で埋める。
- `level_over_noise`：置いたフレームを交互に2組へ分けて足した2枚の、差の標準偏差の半分を雑音、平均の 90% 点を明るさとする。

- [ ] **Step 4: 通るのを確かめる** — `py -3.12 -m pytest -q tests/test_gather.py` → `7 passed`。`py -3.12 -m ruff check app/gather.py tests/test_gather.py` → `All checks passed!`
- [ ] **Step 5: Commit** — `feat: gather frames of one page into an image (place by band-passed correlation, add on a finer grid)`

### Task 2: 部分ごとに置いて、傾きと反りに合わせる

**Files:** Modify: app/gather.py、tests/test_gather.py

**Interfaces:**
- Consumes: `shift_of`、`gather`（Task 1）
- Produces: `gather(..., parts: int = 3)`：全体で置いた後、`parts × parts` に分けた部分ごとに `shift_of` を取り（探す半径 2）、外れ値（中央値から 1.5 画素超）を除いて、位置の1次式（`dy = a + b*y + c*x`、`dx` も同じ）を最小二乗で当てはめる。使える部分が 4 未満なら全体のずれだけを使う。足す時のずれは、当てはめた式をフレームの行・列ごとに評価する。`parts=1` は Task 1 と同じ動き。

- [ ] **Step 1: 試験を足す**

```python
def rolled(image, degrees):                 # rotate about the centre, bilinear
def test_a_tilted_head_is_followed_part_by_part():
    s = scene(h=576, w=768); angles = np.random.default_rng(4).normal(0, 0.25, 60)
    fs = [frames(rolled(s, a), [(0, 0)], 2.2, seed=10 + k)[0] for k, a in enumerate(angles)]
    whole = g.gather(fs, parts=1); fitted = g.gather(fs, parts=3)
    assert fitted.placed and alike(fitted.image, s) > alike(whole.image, s) + 0.01
```

- [ ] **Step 2: 失敗を確かめる** — `TypeError: gather() got an unexpected keyword argument 'parts'`
- [ ] **Step 3: 書く**（上の Produces のとおり）
- [ ] **Step 4: 通るのを確かめる** — `py -3.12 -m pytest -q tests/test_gather.py` → `8 passed`
- [ ] **Step 5: Commit** — `feat: follow tilt and bend by placing parts of each frame`

### Task 3: 録画を読む口と、1本を頁にするコマンド

**Files:** Modify: app/gather.py、tests/test_gather.py

**Interfaces:**
- Consumes: `gather`（Task 1・2）
- Produces:

```python
class GatherError(RuntimeError): ...
def read_clip(path: Path, *, crop: tuple[int, int, int, int] | None = None, ffmpeg: str | None = None, black: float = 0.0) -> Iterator[np.ndarray]:
    """Frames of a clip as light (luma, the sRGB curve undone, `black` subtracted). crop = (left, top, width, height).
    ffmpeg: the binary; default ROKID_FFMPEG, else `ffmpeg` on PATH. Raises GatherError when it is missing, exits non-zero or yields no frame."""
def gather_clip(path: Path, record: dict | None = None, **options) -> Gathered:
    """record: the sidecar; uses record["frames"][k]["smear_px"] when its length equals the clip's frame count, else every frame (selection "none")."""
```

`py -3.12 -m app.gather <clip.mp4> [--record <json>] [--crop l,t,w,h] --out <page.png>` は、頁の PNG（16 ビットのグレー、明るさの 99.5% 点を白に）を書き、1行の JSON（`used`、`total`、`level_over_noise`、`placed`、`selection`、`seconds`）を出す。

- [ ] **Step 1: 試験を足す**（ffmpeg が無い環境では `pytest.skip`）

```python
def clip(tmp_path, fs, name="c.mp4"):        # frames -> 8-bit gray -> ffmpeg libx264 -crf 12, 30 a second
def test_a_clip_round_trips_into_a_page(tmp_path):
    s = scene(); fs = frames(s, [(0, 0)] * 40, 4.0)
    result = g.gather_clip(clip(tmp_path, fs))
    assert result.placed and result.total == 40 and alike(result.image, s) > 0.85
def test_a_record_of_another_length_is_not_used(tmp_path):      # Review Focus 3
    result = g.gather_clip(clip(tmp_path, frames(scene(), [(0, 0)] * 20, 4.0)), {"frames": [{"smear_px": 9.0}] * 7})
    assert result.selection == "none" and result.used >= 18
def test_a_missing_ffmpeg_and_a_broken_clip_say_why(tmp_path):  # Review Focus 4
    with pytest.raises(g.GatherError, match="ffmpeg"):
        list(g.read_clip(tmp_path / "c.mp4", ffmpeg=str(tmp_path / "no-such-binary")))
    (tmp_path / "bad.mp4").write_bytes(b"not a video")
    with pytest.raises(g.GatherError):
        list(g.read_clip(tmp_path / "bad.mp4"))
```

- [ ] **Step 2: 失敗を確かめる** — `AttributeError: module 'app.gather' has no attribute 'gather_clip'`
- [ ] **Step 3: 書く** — ffmpeg は `-f rawvideo -pix_fmt gray` を標準出力へ。大きさは `ffmpeg -i` の出力から読む。子プロセスは 120 秒で打ち切り、標準エラーの最後の行を例外に入れる。
- [ ] **Step 4: 通るのを確かめる** — `py -3.12 -m pytest -q tests/test_gather.py` → `11 passed`（ffmpeg が無ければ 8 passed, 3 skipped）
- [ ] **Step 5: Commit** — `feat: read a clip with ffmpeg and gather it into a page from the command line`

### Task 4: 計測アプリに「待つ→録る」の繰り返しと、時刻の記録、表示用の出力の取り出しを足す

**Files:** Modify: `android-relay/glassprobe/src/main/java/dev/rokid/docscanglass/probe/CameraProbe.java`（必要なら同じ場所の `CapabilityProbeActivity.java`）

**Interfaces:**
- Produces（`--es camera_variant` の指定）：
  - `pages=<n>,watch=<ms>,record=<s>`：`preview=320x240` だけのセッションで `watch` だけ待ち → 録画＋表示用（`priv=320x240`）のセッションへ組み直して `record` 秒録り → 止めて戻す、を n 回。頁 k の録画はキャッシュの `probe-clip-<k>.mp4`（`keep` の時だけ残す。残すのは `keepclips=<m>` で先頭 m 本まで）。
  - 頁ごとに1行：`camera probe page=<k> rebuild_ms=<組み直しの要求から録画の最初の撮影結果まで> stop_ms=<止める要求から MediaRecorder.stop の戻りまで> back_ms=<プレビューの最初のフレームまで> results=<撮影結果の数> bytes=<録画の大きさ>`
  - 頁ごとの記録 `probe-clip-<k>.json`：`{"exposure_ns", "iso", "boost", "frame_ns", "results": [センサー時刻 ns, …]}`
  - `texture`：表示用の出力を画面の `TextureView` に流し、0.2 秒ごとに `getBitmap(320, 240)` を取って、1秒ごとに `camera probe texture grabs=<回数> ms_per_grab=<平均> mean=<明るさの平均>` を出す。

- [ ] **Step 1: 書く**（単体試験の対象外。確かめるのは Task 5 の実機）
- [ ] **Step 2: 組み立てる** — `./android-relay/gradlew --no-daemon :glassprobe:testDebugUnitTest :glassprobe:assembleDebug` → `BUILD SUCCESSFUL`。APK の `aapt2 dump badging`（`dev.rokid.docscanglass.probe`）、`apksigner verify`、`sha256sum` を控える。
- [ ] **Step 3: 入れる** — `adb -s 1904092623381086 shell getprop ro.serialno` → `1904092623381086`、`install -r`、`cmd package compile -m speed -f dev.rokid.docscanglass.probe` → `Success`
- [ ] **Step 4: Commit** — `test(glassprobe): a watch-and-record cycle with per-frame timestamps, and reading the display stream`

### Task 5: 机上で測る（グラス、計測アプリ。本番アプリは止めない）

各項目は、コマンド・出力・判定を §M-26 に書く。場面の自動露光（暗さ）を最初に読み、§M-24 の値（70 ms・ISO 800・増幅 7.7〜7.9 倍）と並べる。

- [ ] **5.1 録画のフレームと撮影結果の対応。** `pages=3,record=5,keep` の録画と記録について、`ffprobe -show_entries frame=pts_time` の時刻の差と、センサー時刻の差を突き合わせる。
  判定：ずらして重ねた時に、全フレームで差が 1/4 フレーム間隔以内になる対応が1つだけある → 対応が取れる（今の `MediaRecorder` で進める）。無い → エンコーダーを直接使う方式へ（設計 6.11）。
- [ ] **5.2 録画の視野と、光の量への変換。** 20 秒の録画（約 600 フレーム）と、同じ露光の原寸の YUV 30 枚・同じ大きさの YUV 30 枚を足し、(a) 録画を原寸に重ねる倍率とずれ（縮尺を 0.80〜1.00 で振った相関の山）、(b) 録画の明るさと YUV の明るさの対応（滑らかにした画素どうしの散布を、黒の底上げ＋倍率で当てはめ、残差を見る）を出す。
  判定：倍率が 0.98 以上 → 全視野。それ未満 → 倍率と、目線の枠（縦の 27〜89%）が収まるかを記録する。変換は `read_clip` の `black` と倍率の既定値にする。
- [ ] **5.3 頁ごとに録る型の発熱（G2）。** 約 37℃ まで冷ましてから `pages=40,watch=10000,record=5`（10 分）。30 秒ごとに温度を読み、頁ごとの行を集める。
  判定（設計 9章 G2）：基板（sys-therm-0）が 50℃ 以下で横ばい（最後の 2 分の上昇が 1℃ 以内）、40 頁すべてに録画が残る、カメラのサービスの再起動が無い（`dumpsys` は全文を PC へ取り、`camera.provider` の PID を前後で比べる）。組み直し・停止の時間の中央値と最大、録画の大きさの中央値も出す。
- [ ] **5.4 表示用の出力から小窓の画像。** `texture` を付けた 20 秒。判定：毎秒 4 回以上取れ、1回 50 ms 以内、明るさの平均が 0 でも一定でもない（場面を映している）→ 録っている間も生の画像を出せる。外れる → 設計 6.4 のとおり録り始めの画像のままにする。
- [ ] **5.5 グラス→スマホの送信の速さ（G3）。** グラスがスマホのホットスポットに居ることを読み取りで確かめ、スマホの Termux で受けるだけの口を開き、グラスから 50 MB を送って秒数を測る（3回）。
  判定（G3）：40 頁ぶんの録画（5.3 の大きさの中央値 × 40）のうち、撮影の終了の時点で残る量（10 分間ずっと送り続けた残り）が 3 分以内に届く速さか。届かない → 足りるビットレートを逆算して記録する。ホットスポットに居ない時は、その経路を作る操作をせず、未測定として報告する。

### Task 6: スマホで重ね合わせの所要を測る（G1）

- [ ] **6.1** スマホ（`192.168.0.5:<port>`、シリアル `ZY22LWGDCV` を確認）の Termux で `pkg install -y python-numpy`、`python -c "import numpy; print(numpy.__version__)"`。本番のサーバーは再起動しない（このモジュールをまだ読み込まない）。
- [ ] **6.2** app/gather.py と 5.3 の録画 3 本・記録を `~/codex-trial/gather/` へ置き、`python -m app.gather` を1本ずつと、3本を同時に走らせて、`seconds` を読む。
  判定（G1）：並行して処理して、1頁あたり平均 15 秒以内。外れる → 縮めた画像で位置を合わせる等で軽くして測り直す（Task 1 の試験は保つ）。それでも外れる → 設計の予備案の検討へ戻る（報告して止まる）。

### Task 7: 記録と判定

- [ ] `docs/hardware-measurements.md` に §M-26（5.1〜5.5、6 の結果）。設計書の4章・9章・11章の「未確認」を、測れたものだけ測定値に置き換える。`docs/whole-review-2026-11-14.md`、`docs/defect-register.md` の現在地、`.agents/progress/current.md`、`CLAUDE.md` の該当箇所を、全文を読み直して合わせる。
- [ ] `py -3.12 -m pytest -q tests`（出力をファイルへ、終了コードを表示）、`py -3.12 -m ruff check .`、`./android-relay/gradlew --no-daemon :glassprobe:testDebugUnitTest :glassprobe:assembleDebug`。
- [ ] G1〜G3 の判定と、段階2へ進めるか（冊子を置くお願いが要る）を本人へ報告する。基準を外れたものがあれば、先へ進まない。

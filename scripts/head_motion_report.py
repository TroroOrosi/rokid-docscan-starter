"""What a recorded head-motion trace allows: how often, and after how long a wait, a photo could be taken still.

The glasses app writes the gyroscope at 200 Hz to head-motion.bin in its external files directory for as long as its
camera is open (records: big-endian int64 sensor timestamp in ns, three float32 rad/s). This script pulls that trace, or reads a pulled copy,
and replays capture rules against it. A rule is judged against the motion during the exposure itself, which is what
smears a photo: the allowed turning is BLUR_PIXELS over the exposure through the lens (1900 pixels focal length).

    py -3.12 scripts/head_motion_report.py --glasses <adb serial> [--package <id>] [--keep trace.bin]
    py -3.12 scripts/head_motion_report.py trace.bin

Read-only on the device. A trace recorded with the glasses lying on a desk says nothing about a worn head.
"""

from __future__ import annotations

import argparse
import math
import struct
import subprocess
import sys
from collections import deque
from pathlib import Path

ADB = r"C:\Users\pupu_\AppData\Local\Android\Sdk\platform-tools\adb.exe"
PACKAGE = "dev.rokid.docscanglass.doc"
FOCAL_PIXELS = 1900.0
BLUR_PIXELS = 2.28  # today's gate: 0.12 rad/s at 10 ms
SKEW_S = 0.0284  # rolling shutter, first row to last
GATE_QUIET_S = 0.3  # today's gate: every reading under the limit for this long before the request
LATENCY_S = 0.5  # request to exposure, measured 0.3-0.7 s
BURST_GAP_S = 0.35  # one full-size frame after another, measured
EXPOSURES_MS = (10.0, 16.7, 30.0, 60.0)
RECORD = struct.Struct(">qfff")


def load(raw: bytes) -> tuple[list[float], list[float]]:
    usable = len(raw) - len(raw) % RECORD.size
    t, speed = [], []
    # Two openings of the camera may each write out their last second in either order: put the readings in time order.
    for at, x, y, z in sorted(RECORD.iter_unpack(raw[:usable])):
        t.append(at / 1e9)
        speed.append(math.sqrt(x * x + y * y + z * z))
    return t, speed


def runs(t: list[float]) -> list[tuple[int, int]]:
    """Stretches of continuous recording: the camera closes for a pause and between sessions."""
    edges = [0] + [i for i in range(1, len(t)) if t[i] - t[i - 1] > 0.1] + [len(t)]
    return [(a, b) for a, b in zip(edges, edges[1:], strict=False) if b - a >= 400]


def windowed_peak(speed: list[float], width: int) -> list[float]:
    """Peak over [i, i + width) for every start i."""
    width = max(1, width)
    peaks: list[float] = []
    falling: deque[int] = deque()
    for i, value in enumerate(speed):
        while falling and speed[falling[-1]] <= value:
            falling.pop()
        falling.append(i)
        if falling[0] <= i - width:
            falling.popleft()
        if i >= width - 1:
            peaks.append(speed[falling[0]])
    return peaks


def first_wait(ok: list[bool], period: float, step_s: float = 1.0) -> list[float]:
    """Starting every step_s, seconds until the first moment ok is true; inf where it never is."""
    following = [math.inf] * (len(ok) + 1)
    for i in range(len(ok) - 1, -1, -1):
        following[i] = 0.0 if ok[i] else following[i + 1] + period
    return following[0:len(ok):max(1, round(step_s / period))]


def percentile(values: list[float], percent: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * percent / 100))]


def share(flags: list[bool]) -> str:
    return f"{100 * sum(flags) / len(flags):5.1f}%" if flags else "     -"


def report(t: list[float], speed: list[float]) -> None:
    spans = runs(t)
    print(f"readings {len(t)}, continuous stretches {len(spans)}, {sum(t[b - 1] - t[a] for a, b in spans):.0f} s in all")
    if not spans:
        print("too little to judge")
        return
    every = [value for a, b in spans for value in speed[a:b]]
    period = percentile([t[i + 1] - t[i] for a, b in spans for i in range(a, b - 1)], 50)
    print(f"sample period {period * 1000:.1f} ms; turning speed rad/s: p10 {percentile(every, 10):.3f}, median {percentile(every, 50):.3f}, "
          f"p90 {percentile(every, 90):.3f}, p99 {percentile(every, 99):.3f}")
    latency, quiet, gap = round(LATENCY_S / period), max(1, round(GATE_QUIET_S / period)), round(BURST_GAP_S / period)
    print()
    print("               exposures   today's gate: 0.3 s quiet, photo 0.5 s later   |  shoot when the instant is quiet, 0.5 s later")
    print("  ms   limit   still       wait p50/p90 s   never   photo still           |  wait p50/p90 s   never   photo still")
    burst_rows = []
    for exposure_ms in EXPOSURES_MS:
        limit = BLUR_PIXELS / FOCAL_PIXELS / (exposure_ms / 1000)
        width = max(1, round((exposure_ms / 1000 + SKEW_S) / period))
        still_all: list[bool] = []
        rules = {"gate": ([], []), "instant": ([], [])}  # waits, whether the photo it leads to is still
        burst: dict[int, list[bool]] = {1: [], 2: [], 3: [], 4: []}
        for a, b in spans:
            s = speed[a:b]
            still = [peak <= limit for peak in windowed_peak(s, width)]  # an exposure starting at i
            still_all += still
            passes = [False] * (quiet - 1) + [peak <= limit for peak in windowed_peak(s, quiet)]  # quiet stretch ends at i
            for name, decide in (("gate", passes), ("instant", [value <= limit for value in s])):
                usable = decide[:max(0, len(still) - latency)]
                rules[name][0].extend(first_wait(usable, period))
                rules[name][1].extend(still[i + latency] for i, yes in enumerate(usable) if yes)
            for frames, hits in burst.items():
                usable = len(still) - gap * (frames - 1)
                hits.extend(any(still[i + k * gap] for k in range(frames)) for i in range(max(0, usable)))
        row = f"{exposure_ms:5.1f}  {limit:.3f}   {share(still_all)}   "
        for name in ("gate", "instant"):
            waits, good = rules[name]
            finite = [w for w in waits if math.isfinite(w)]
            row += f"   {percentile(finite, 50):5.1f} /{percentile(finite, 90):5.1f}" if finite else "       - /    -"
            row += f"    {100 * (1 - len(finite) / max(1, len(waits))):4.0f}%   {share(good)}"
            row += "           |" if name == "gate" else ""
        print(row)
        burst_rows.append(f"{exposure_ms:5.1f}       " + "    ".join(share(hits) for hits in burst.values()))
    print()
    print(f"best of a burst started at a random moment (frames {BURST_GAP_S} s apart; the photo is the stillest frame):")
    print("  ms       1 frame   2 frames  3 frames  4 frames have a still one")
    print("\n".join(burst_rows))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("trace", nargs="?", help="a pulled head-motion.bin")
    parser.add_argument("--glasses", help="adb transport of the glasses to pull the trace from")
    parser.add_argument("--package", default=PACKAGE)
    parser.add_argument("--keep", help="save the pulled trace here")
    options = parser.parse_args()
    if options.trace:
        raw = Path(options.trace).read_bytes()
    elif options.glasses:
        raw = subprocess.run([ADB, "-s", options.glasses, "exec-out", "cat", f"/sdcard/Android/data/{options.package}/files/head-motion.bin"],
                             capture_output=True, timeout=120, check=True).stdout
        if len(raw) < RECORD.size or not 0 < RECORD.unpack_from(raw)[0] < 10**16:
            sys.exit("no trace on the glasses: " + raw[:120].decode("utf-8", "replace").strip())
        if options.keep:
            Path(options.keep).write_bytes(raw)
    else:
        parser.error("a trace file or --glasses")
    report(*load(raw))
    return 0


def demo() -> None:
    """A head still for 2 s, turning for 1 s, still for 2 s, at 200 Hz."""
    t = [i * 0.005 for i in range(1000)]
    speed = [0.5 if 2 <= at < 3 else 0.005 for at in t]
    still = [peak <= 0.04 for peak in windowed_peak(speed, 6)]
    assert all(still[:390]) and not any(still[400:600]) and all(still[600:])
    waits = first_wait(still, 0.005)
    assert waits[0] == 0 and abs(waits[2] - 1.0) < 0.05, waits  # starting at 2 s: wait until 3 s
    raw = b"".join(RECORD.pack(int(at * 1e9), value, 0, 0) for at, value in zip(t, speed, strict=True))
    loaded_t, loaded_speed = load(raw + b"\x00\x01")  # a torn last record is ignored
    assert len(loaded_t) == 1000 and abs(loaded_speed[500] - 0.5) < 1e-6 and len(runs(loaded_t)) == 1


if __name__ == "__main__":
    demo()
    sys.exit(main())

"""Stage 2 of the gathered capture: a real page in the venue's darkness, recorded, gathered, read and judged.

One tool for the whole pass, so that the booklet has to be placed once
(docs/superpowers/plans/2026-11-15-gathered-capture-stage2.md holds the conditions and the rules, fixed before any run):

    py -3.12 scripts/gather_stage2.py [--glasses <adb transport>] [--run near] frame   # light and framing, before recording
    py -3.12 scripts/gather_stage2.py --run near capture dark [--only A] [--scale 0.5] # the clips and the direct frames
    py -3.12 scripts/gather_stage2.py --run near gather --page 0.15,0.285,0.40,0.18 --rotate 270
    py -3.12 scripts/gather_stage2.py --run near reads prepare|run|reference|score --phone <adb transport>
    py -3.12 scripts/gather_stage2.py demo                       # self-check of the parts that need no device

Runs on: the glasses on a desk (the measurement app; the real app is not stopped), the phone (the official Codex CLI
reads the page images), this PC. It is not the venue topology and nobody wears the glasses.

The first pass (2026-11-15, M-27) stopped after `gather`: the glasses' recorded frames had lost the print's detail, and
no read was run. The reading part (a plain copy of the page's lines, scored against what repeated reads of the direct
frames agree on) has passed only its self-check.

The prompt, the reply schema and the reference text stay in the untracked data/ folder: an exam's text does not belong
in a public repository.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ADB = r"C:\Users\pupu_\AppData\Local\Android\Sdk\platform-tools\adb.exe"
SERIAL = "1904092623381086"
GLASSES = SERIAL  # the adb transport: the serial over USB, or what scripts/glasses_over_phone.py printed (--glasses)
PROBE ="dev.rokid.docscanglass.probe"
ENV = dict(os.environ, MSYS_NO_PATHCONV="1")
WORK = ROOT / "data" / "gather-stage2" / "run"
PRIVATE = ROOT / "data" / "gather-stage2" / "private"  # prompt.txt, schema.json, reference.json
PHONE_HOME = "/data/data/com.termux/files/home"
VENUE = "the wearer's photos of 2026-11-14 18:46: 60 ms at ISO 4032-5688 (exposure x gain 242-341); the desk of M-24: 70 ms x 6300 (441)"
MIN_CHARACTER = 12  # sensor pixels from one character to the next; under this the page is too far to judge anything
WORN_CHARACTER = 15.8  # the same in the photos a wearer took on 2026-09-22 (M-22): the distance a page is read from

CLIP = "pages=1,watch=3000,keep,keepclips=1"
CAPTURES = {  # name: (variant, seconds the recording itself takes)
    "A": (f"{CLIP},record=10,expose=30000000,bitrate=40000000", 10),
    "A-low": (f"{CLIP},record=10,expose=30000000,bitrate=12000000", 10),
    "W": (f"{CLIP},record=10,still=1920x1080,fps=60,expose=16666666,bitrate=40000000", 10),
    "E10": (f"{CLIP},record=5,expose=10000000,bitrate=40000000", 5),
    "E20": (f"{CLIP},record=5,expose=20000000,bitrate=40000000", 5),
    "E8": (f"{CLIP},record=5,still=1920x1080,fps=60,expose=8333333,bitrate=40000000", 5),
    # A page nearer than it is read from, recorded smaller: 1280 of the sensor's 4032 columns. With characters 25 px apart
    # on the sensor this clip has them 8 px apart, as 2400x1800 has those of a page at the worn distance (9.4) and
    # 1920x1080 has (7.5). 17 Mbit/s is A's bits for each pixel of each frame.
    "F": (f"{CLIP},record=10,still=1280x720,fps=60,expose=16666666,bitrate=17000000", 10),
}
READS = {  # name of the condition read: (capture it comes from, frames gathered)
    "A-288": ("A", 288), "A-144": ("A", 144), "A-72": ("A", 72), "A-36": ("A", 36), "A-low": ("A-low", 288), "W-576": ("W", 576),
    "F-416": ("F", 416), "F-208": ("F", 208), "F-104": ("F", 104), "F-52": ("F", 52),
}
SERIES = {"A": (36, 72, 144, 288), "A-low": (288,), "W": (72, 144, 288, 576), "E10": (30, 60, 120), "E20": (30, 60, 120), "E8": (60, 120, 240),
          "F": (52, 104, 208, 416)}
DIRECT_RUNS = 12  # x 5 stills of 30 ms: 1.8 s of light on a page that does not move
SMALL = 1280 / 4032  # "Ns": the direct frames reduced to F's sampling, with no encoder between


# ---------------------------------------------------------------- the glasses


def sh(command: str, timeout: float = 90) -> str:
    return subprocess.run([ADB, "-s", GLASSES, "shell", command], capture_output=True, timeout=timeout, env=ENV,
                          stdin=subprocess.DEVNULL).stdout.decode("utf-8", "replace")


def probe(variant: str, seconds: float, out: Path) -> str:
    """Run the measurement app once with this variant, wait for its verdict, bring what it kept into `out`."""
    assert sh("getprop ro.serialno").strip() == SERIAL, f"{GLASSES} is not the glasses"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("probe-*"):
        old.unlink()
    sh(f"am force-stop {PROBE}; run-as {PROBE} sh -c 'rm -f cache/probe-capture*.jpg cache/probe-record.mp4 cache/probe-clip-*'")
    stamp = sh("date '+%m-%d %H:%M:%S.000'").strip()
    sh(f"input keyevent KEYCODE_WAKEUP; am start -n {PROBE}/.CapabilityProbeActivity --es camera_variant '{variant}' >/dev/null 2>&1; "
       "sleep 3; D=/dev/input/event1; sendevent $D 1 204 1; sendevent $D 0 0 0; sendevent $D 1 204 0; sendevent $D 0 0 0; "
       "sendevent $D 1 28 1; sendevent $D 0 0 0; sendevent $D 1 28 0; sendevent $D 0 0 0")
    deadline = time.monotonic() + seconds + 45
    log = ""
    while time.monotonic() < deadline:
        time.sleep(2)
        log = subprocess.run([ADB, "-s", GLASSES, "logcat", "-d", "-v", "time", "-T", stamp, "-s", "DocScanGlassProbe:*"], capture_output=True,
                             timeout=60, env=ENV, stdin=subprocess.DEVNULL).stdout.decode("utf-8", "replace")
        if "camera probe OK" in log or "camera probe FAILED" in log:
            break
    (out / "log.txt").write_text(log, encoding="utf-8")
    for name in sh(f"run-as {PROBE} sh -c 'ls cache'").split():
        if name.startswith(("probe-capture-", "probe-clip-")):
            data = subprocess.run([ADB, "-s", GLASSES, "exec-out", f"run-as {PROBE} cat cache/{name}"], capture_output=True, timeout=600,
                                  env=ENV, stdin=subprocess.DEVNULL).stdout
            (out / name).write_bytes(data)
    sh(f"am force-stop {PROBE}; run-as {PROBE} sh -c 'rm -f cache/probe-capture*.jpg cache/probe-clip-*'")
    if "camera probe OK" not in log:
        raise SystemExit(f"the measurement app did not finish [{variant}]: " + " | ".join(line[line.find('camera probe'):][:160]
                         for line in log.splitlines() if "camera probe" in line)[-400:])
    return log


def exposure(log: str) -> tuple[float, int, float]:
    """(exposure ms, ISO, digital gain) of the still the app logged."""
    found = re.search(r"still result exposure_ns=(\d+) iso=(\d+).*?boost=(\d+)", log)
    if not found:
        raise SystemExit("the app logged no exposure")
    return int(found.group(1)) / 1e6, int(found.group(2)), int(found.group(3)) / 100


# ---------------------------------------------------------------- pictures


def light_of(path: Path):
    import numpy as np
    from PIL import Image

    encoded = np.asarray(Image.open(path).convert("L"), dtype=np.float32) / 255.0
    return np.where(encoded <= 0.04045, encoded / 12.92, ((encoded + 0.055) / 1.055) ** 2.4).astype(np.float32)


def bright_box(light, cells: int = 48) -> tuple[float, float, float, float] | None:
    """(left, top, width, height) as shares of the frame of the largest connected bright area, or None: the page, if one is lit.

    Bright is over halfway from the frame's median to its 99th percentile, on a grid of `cells` across.
    """
    import numpy as np

    h, w = light.shape
    step = max(1, w // cells)
    grid = light[:h // step * step, :w // step * step].reshape(h // step, step, w // step, step).mean(axis=(1, 3))
    median, top = float(np.median(grid)), float(np.percentile(grid, 99))
    if top <= median * 1.5:
        return None
    lit = grid > median + 0.5 * (top - median)
    seen = np.zeros_like(lit)
    best: list[tuple[int, int]] = []
    for y, x in zip(*np.nonzero(lit), strict=True):
        if seen[y, x]:
            continue
        stack, area = [(y, x)], []
        seen[y, x] = True
        while stack:
            cy, cx = stack.pop()
            area.append((cy, cx))
            for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                if 0 <= ny < lit.shape[0] and 0 <= nx < lit.shape[1] and lit[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        if len(area) > len(best):
            best = area
    if len(best) < 0.02 * lit.size:
        return None
    ys, xs = [p[0] for p in best], [p[1] for p in best]
    gh, gw = lit.shape
    return min(xs) / gw, min(ys) / gh, (max(xs) + 1 - min(xs)) / gw, (max(ys) + 1 - min(ys)) / gh


def pitch(light) -> tuple[float, float]:
    """(pixels from one line of print to the next across the picture, the same down it): the strongest period of each
    profile between 8 and 120 px, 0.0 where none stands out. Of a page of text the smaller is the characters' pitch."""
    import numpy as np

    found = []
    for axis in (0, 1):
        profile = light.mean(axis=axis)
        profile = (profile - np.convolve(profile, np.ones(101) / 101, "same"))[60:-60]
        if len(profile) < 240 or float(profile.std()) < 1e-4:
            found.append(0.0)
            continue
        power = np.abs(np.fft.rfft(profile * np.hanning(len(profile)))[1:]) ** 2
        periods = len(profile) / np.arange(1, len(power) + 1)
        keep = (periods > 8) & (periods < 120)
        best = int(np.argmax(power[keep]))
        found.append(float(periods[keep][best]) if power[keep][best] > 20 * np.median(power[keep]) else 0.0)
    return found[0], found[1]


def shown(light, white: float | None = None):
    """Light as an 8-bit picture: the brightest half percent is white."""
    import numpy as np
    from PIL import Image

    white = white or float(np.percentile(light, 99.5)) or 1.0
    scaled = np.clip(light / white, 0, 1)
    return Image.fromarray((np.where(scaled <= 0.0031308, scaled * 12.92, 1.055 * scaled ** (1 / 2.4) - 0.055) * 255 + 0.5).astype(np.uint8))


def box_in(box: tuple[float, float, float, float], width: int, height: int, tall_share: float = 1.0) -> tuple[int, int, int, int]:
    """A box given as shares of the whole field, in the pixels of a picture that shows the middle `tall_share` of the
    field's height (1920x1080 clips show 0.75 of it), even-sized as a video crop must be."""
    left, top, wide, tall = box
    top = (top - (1 - tall_share) / 2) / tall_share
    tall = tall / tall_share
    x, y = max(0, round(left * width)), max(0, round(top * height))
    w, h = min(width - x, round(wide * width)), min(height - y, round(tall * height))
    return x // 2 * 2, y // 2 * 2, w // 2 * 2, h // 2 * 2


# ---------------------------------------------------------------- commands on the glasses


def cmd_frame(_: argparse.Namespace) -> int:
    log = probe("preview=320x240,warm=3000,yuvstill,jpeg=97,keep,count=1", 8, WORK / "frame")
    ms, iso, gain = exposure(log)
    print(f"auto exposure now: {ms:.0f} ms, ISO {iso}, digital gain {gain:.2f} (exposure x gain {ms * iso * gain / 1000:.0f})")
    print(f"for comparison: {VENUE}")
    stills = sorted((WORK / "frame").glob("probe-capture*.jpg"))
    light = light_of(stills[0])
    shown(light).resize((1008, 756)).save(WORK / "frame" / "frame.png")
    shown(light).resize((320, 240)).save(WORK / "frame" / f"frame-320-{time.strftime('%H%M%S')}.png")
    box = bright_box(light)
    if box is None:
        print("no lit page found in the view")
        return 1
    h, w = light.shape
    cx, cy = round((box[0] + box[2] / 2) * w), round((box[1] + box[3] / 4) * h)  # a quarter down: inside one page of a spread
    across, down = pitch(light[max(0, cy - 350):cy + 350, max(0, cx - 350):cx + 350])
    character = min((value for value in (across, down) if value), default=0.0)
    print(f"lit area (of the sensor's frame, which lies on its side): left {box[0]:.2f}, top {box[1]:.2f}, width {box[2]:.2f}, height {box[3]:.2f}; "
          f"lines of print every {across:.1f} px across and {down:.1f} px down its middle -> characters about {character:.1f} px apart "
          f"({character / WORN_CHARACTER:.2f} of the worn photos' {WORN_CHARACTER})")
    if character < MIN_CHARACTER:
        print(f"no print found, or under {MIN_CHARACTER} px a character: bring the page closer.")
        return 1
    return 0


def cmd_capture(asked: argparse.Namespace) -> int:
    if asked.light == "bright":
        log = probe("preview=320x240,warm=3000,yuvstill,jpeg=97,keep,count=3,gap=500", 14, WORK / "B")
        print("B: %.0f ms, ISO %d, digital gain %.2f; %d stills" % (*exposure(log), len(list((WORK / "B").glob("probe-capture-*.jpg")))))
        return 0
    names = [asked.only] if asked.only else [*CAPTURES, "N"]
    ms, iso, gain = exposure((WORK / "frame" / "log.txt").read_text(encoding="utf-8"))  # the scene's auto exposure, from `frame`
    now = ms * iso * gain / 1000
    # A darker page is stood for by a shorter exposure: a frame of 30 ms on a page with half this light is one of 15 ms here.
    scale = asked.scale
    print(f"scene: exposure x gain {now:.0f}; exposures are multiplied by {scale:.3f}")
    for name in names:
        started = time.monotonic()
        if name == "N":  # full-size frames taken directly at 30 ms and the scene's own brightness, added without any encoder: ample light
            boost = max(100, min(3199, round(ms * gain / 30 * 100)))
            for run in range(DIRECT_RUNS):  # the app gives one run 15 s, which is five of these stills
                probe(f"preview=320x240,warm=3000,manual,expose={round(30000000 * scale)},iso=800,boost={boost},nr=0,edge=0,frame=33333333,fps=30,"
                      "yuvstill,jpeg=97,keep,count=5", 14, WORK / "N" / f"{run:02d}")
            print(f"N: {len(list((WORK / 'N').glob('*/probe-capture-*.jpg')))} direct frames at gain {boost / 100:.2f} in {time.monotonic() - started:.0f} s")
            continue
        variant, seconds = CAPTURES[name]
        variant = re.sub(r"expose=(\d+)", lambda found: f"expose={round(int(found.group(1)) * scale)}", variant)
        log = probe(variant, seconds + 8, WORK / name)
        page = next((line[line.find("page=1"):] for line in log.splitlines() if "page=1" in line), "?")
        clip = WORK / name / "probe-clip-1.mp4"
        print(f"{name}: {clip.stat().st_size / 1e6:.1f} MB; {page[:150]}")
    return 0


# ---------------------------------------------------------------- gathering on this PC


def cmd_gather(asked: argparse.Namespace) -> int:
    import numpy as np

    from app import gather as g

    box = tuple(float(v) for v in asked.page.split(","))
    pages = WORK / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    rows = []

    def keep(name: str, light, note: str) -> None:
        picture = shown(light)
        if asked.rotate:
            picture = picture.rotate(-asked.rotate, expand=True)
        picture.save(pages / f"{name}.png")
        rows.append(f"{name:8s} {picture.size[0]}x{picture.size[1]}  {note}")

    stills = sorted((WORK / "B").glob("probe-capture-*.jpg"))
    if stills:
        full = light_of(stills[0])
        x, y, w, h = box_in(box, full.shape[1], full.shape[0])
        keep("B", full[y:y + h, x:x + w], "one still in good light")
    direct = sorted((WORK / "N").glob("*/probe-capture-*.jpg"))
    if direct:
        total = None
        for path in direct:
            frame = light_of(path).astype(np.float64)
            total = frame if total is None else total + frame
        mean = (total / len(direct)).astype(np.float32)
        x, y, w, h = box_in(box, mean.shape[1], mean.shape[0])
        keep("N", mean[y:y + h, x:x + w], f"{len(direct)} direct full-size frames added")
        from PIL import Image

        part = Image.fromarray(mean[y:y + h, x:x + w])
        small = np.asarray(part.resize((round(w * SMALL), round(h * SMALL)), Image.BOX), np.float32)
        keep("Ns", small, f"the same reduced to {SMALL:.3f}: the sampling of the 1280x720 clip, no encoder")
    for name, counts in SERIES.items():
        clip = WORK / name / "probe-clip-1.mp4"
        if not clip.exists():
            continue
        width, height, _ = g._described(g._ffmpeg(None), clip)
        crop = box_in(box, width, height, 0.75 if height * 4 < width * 3 else 1.0)
        for count in counts:
            started = time.monotonic()
            result = g.gather_clip(clip, crop=crop, limit=count)
            note = (f"used {result.used}/{result.total} placed {result.placed} level over noise {result.level_over_noise:.1f} "
                    f"in {time.monotonic() - started:.0f} s")
            label = next((read for read, (source, frames) in READS.items() if source == name and frames == count), f"{name}-{count}")
            if result.used:
                keep(label, result.image, note)
            else:
                rows.append(f"{label:8s} nothing gathered  {note}")
    (WORK / "gather.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")
    print("\n".join(rows))
    return 0


# ---------------------------------------------------------------- reading on the phone


def clean(text: object) -> str:
    return "".join(unicodedata.normalize("NFKC", str(text)).split())


def distance(a: str, b: str) -> int:
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        previous, row[0] = row[0], i
        for j, y in enumerate(b, 1):
            previous, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, previous + (x != y))
    return row[-1]


def within(reference: str, reply: str) -> int:
    """Fewest edits that turn some stretch of the reply into the reference. What the reply holds before and after that
    stretch costs nothing: a line cut by the picture's edge is not an error of reading."""
    row = [0] * (len(reply) + 1)
    for i, x in enumerate(reference, 1):
        previous, row[0] = row[0], i
        for j, y in enumerate(reply, 1):
            previous, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, previous + (x != y))
    return min(row)


def text_of(reply: dict) -> str:
    return clean("".join(str(line) for line in reply.get("lines", [])))


def agreed(reads: list[str]) -> str:
    """The text most reads give: the read nearest to all the others, corrected wherever most of the others say otherwise.

    The page's text is not on this PC, so the reference is what repeated reads of the best picture agree on. A character
    all reads get wrong alike stays wrong in it, and counts against every condition alike.
    """
    import difflib
    from collections import Counter

    middle = min(reads, key=lambda one: sum(distance(one, other) for other in reads))
    kept = [Counter() for _ in middle]  # what each read has in place of each character of `middle`
    added = [Counter() for _ in range(len(middle) + 1)]  # and what it has before it
    for read in reads:
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, middle, read, autojunk=False).get_opcodes():
            if tag == "equal":
                for k in range(i2 - i1):
                    kept[i1 + k][middle[i1 + k]] += 1
            elif tag == "insert":
                added[i1][read[j1:j2]] += 1
            else:  # replace or delete: the first character of the stretch takes the read's whole version, the rest nothing
                for k in range(i1, i2):
                    kept[k][read[j1:j2] if k == i1 else ""] += 1
    out = []
    for k in range(len(middle) + 1):
        extra, votes = added[k].most_common(1)[0] if added[k] else ("", 0)
        if votes * 2 > len(reads):
            out.append(extra)
        if k < len(middle):
            out.append(kept[k].most_common(1)[0][0])
    return "".join(out)


def verdicts(means: dict[str, float]) -> list[str]:
    """The plan's rules (as ruled on 2026-11-15 for the page that was placed), applied to the mean share of wrong
    characters (percent) of each condition."""
    def against(a: str, b: str, limit: float, yes: str, no: str) -> str:
        if a not in means or b not in means:
            return f"{a} against {b}: not measured"
        gap = means[a] - means[b]
        call = "undecided (within 0.5 of the limit: read that condition 12 more times)" if abs(gap - limit) <= 0.5 else yes if gap <= limit else no
        return f"{a} - {b} = {gap:+.1f} points (limit {limit:.1f}): {call}"

    if "L30" in means:  # the second pass (M-28): clips the app fed to the encoder from the camera's unsmoothed output
        return [
            "F1 G4, the size as placed  " + against("L30", "N", 2.0, "pass", "fail"),
            "F2 encoder, the worn size  " + against("Fh", "Ns", 2.0, "the encoder keeps it", "lost in the encoder"),
            "F2 the same at 2 bits      " + against("Fh2", "Ns", 2.0, "the encoder keeps it", "lost in the encoder"),
            "F2b sampling, a still page " + against("Ns", "N", 2.0, "half size is fine enough even without movement", "needs the finer grid a moving head gives, or the paper's own pixels"),
            "F3 one second of light     " + against("L30-30", "N", 2.0, "30 frames are enough here", "more than 30 frames"),
            "F4 bit rate                " + against("L30low", "L30", 1.0, "take the lower bit rate", "keep the higher bit rate"),
            "F5 sixty frames a second   " + against("L60", "L30", 2.0, "keep 60 a second as a candidate", "drop 60 a second"),
        ]
    lines = [
        "1 G4 at the worn size   " + against("F-208", "N", 2.0, "pass", "fail"),
        "2 encoder, small print  " + against("F-208", "Ns", 2.0, "the encoder and the gathering keep it", "lost in recording or gathering"),
        "2b sampling alone       " + against("Ns", "N", 2.0, "the whole field at this size is fine enough", "too coarse: record the paper, not the field"),
        "2c encoder, large print " + against("A-288", "N", 2.0, "kept", "lost"),
        "4 bit rate              " + against("A-low", "A-288", 1.0, "take the lower bit rate", "keep the higher bit rate"),
        "5 second shape          " + against("W-576", "A-288", 2.0, "keep 1920x1080 as a candidate", "drop 1920x1080"),
    ]
    if "N" in means:
        enough = [name for name in ("F-52", "F-104", "F-208", "F-416") if name in means and means[name] - means["N"] <= 2.0]
        nothing = [name for name in ("F-416", "F-208", "F-104", "F-52") if name in means and means[name] > 50]
        lines.insert(4, f"3 light needed          fewest frames within 2.0 points of N: {enough[0] if enough else 'none'}; "
                        f"most frames that still read nothing (over 50%): {nothing[0] if nothing else 'none'}")
    return lines


def phone(transport: str, script: str, timeout: float = 120) -> str:
    preface = (f"export PREFIX=/data/data/com.termux/files/usr HOME={PHONE_HOME}\n"
               "export PATH=$PREFIX/bin:$PATH LD_LIBRARY_PATH=$PREFIX/lib TMPDIR=$PREFIX/tmp\n")
    return subprocess.run([ADB, "-s", transport, "shell", "run-as com.termux sh -s"], input=(preface + script).encode("utf-8"),
                          capture_output=True, timeout=timeout, env=ENV).stdout.decode("utf-8", "replace")


LANE = """bin=$PREFIX/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-arm64/vendor/aarch64-unknown-linux-musl/bin/codex
work=$HOME/codex-trial
export SSL_CERT_FILE=$PREFIX/etc/tls/cert.pem HTTPS_PROXY=http://127.0.0.1:PORT
pgrep -f "connect_proxy.py PORT" >/dev/null || { nohup python $work/connect_proxy.py PORT >> $work/proxyPORT.log 2>&1 < /dev/null & sleep 1; }
for job in JOBS; do
  name=${job%%:*}; rep=${job##*:}
  cd $work/s2/RUN/$name || continue
  [ -s out-$rep.json ] && continue
  images=""; for f in tile-*.jpg; do images="$images -i $f"; done
  started=$(date +%s)
  "$bin" exec --json -m gpt-6.1-sol -c model_reasoning_effort=xhigh -s read-only --skip-git-repo-check --ephemeral $images --output-schema schema.json -o out-$rep.json "$(cat prompt.txt)" > out-$rep.jsonl 2> err-$rep.log < /dev/null
  echo "$name rep=$rep exit=$? seconds=$(( $(date +%s) - started ))" >> $work/s2_run.log
done
echo "end-lane PORT" >> $work/s2_run.log
pkill -f "connect_proxy.py PORT"
"""


def cmd_reads(asked: argparse.Namespace) -> int:
    reads = WORK / "reads"
    names = asked.only.split(",") if asked.only else ["N", "Ns", *READS]
    if asked.step == "prepare":
        from PIL import Image

        from app.source_bundle import page_tiles

        base = (PRIVATE / "prompt_text.txt").read_text(encoding="utf-8")
        for name in names:
            page = WORK / "pages" / f"{name}.png"
            if not page.exists():
                print(f"{name}: no page")
                continue
            folder = reads / name
            folder.mkdir(parents=True, exist_ok=True)
            for old in folder.glob("tile-*.jpg"):
                old.unlink()
            tiles = page_tiles(Image.open(page).convert("RGB"), vertical_text=True)
            for index, (tile, _) in enumerate(tiles):
                tile.save(folder / f"tile-{chr(97 + index)}.jpg", format="JPEG", quality=92, subsampling=0)
            prompt = base if len(tiles) == 1 else base + (f" The {len(tiles)} images are overlapping strips of that one part, from right to left "
                                                          "(the first is the right edge); copy a line that two strips show once.")
            (folder / "prompt.txt").write_text(prompt, encoding="utf-8")
            (folder / "schema.json").write_bytes((PRIVATE / "schema_text.json").read_bytes())
            print(f"{name}: {[tile.size for tile, _ in tiles]}")
        return 0
    if asked.step == "run":
        serial = subprocess.run([ADB, "-s", asked.phone, "shell", "getprop ro.serialno"], capture_output=True, timeout=60, env=ENV).stdout.decode().strip()
        assert serial == "ZY22LWGDCV", f"{asked.phone} is not the phone"  # asked outside run-as: an app's user cannot read it
        ready = [name for name in names if (reads / name / "prompt.txt").exists()]
        packed = subprocess.run(["tar", "-C", str(reads), "-cf", "-", "--exclude=out-*", "--exclude=err-*", *ready], capture_output=True, check=True).stdout
        subprocess.run([ADB, "-s", asked.phone, "exec-in", f"run-as com.termux sh -c 'mkdir -p {PHONE_HOME}/codex-trial/s2/{WORK.name} && cd {PHONE_HOME}/codex-trial/s2/{WORK.name} && tar -xf -'"],
                       input=packed, check=True, timeout=300, env=ENV)
        jobs = [f"{name}:{rep}" for rep in range(1, asked.reads + 1) for name in ready]
        lanes = [jobs[k::asked.lanes] for k in range(asked.lanes)]
        running = []
        for index, lane in enumerate(lanes):
            script = LANE.replace("PORT", str(18082 + index)).replace("JOBS", " ".join(lane)).replace("RUN", WORK.name)
            running.append(subprocess.Popen([ADB, "-s", asked.phone, "shell", "run-as com.termux sh -s"], stdin=subprocess.PIPE,
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=ENV))
            running[-1].stdin.write((f"export PREFIX=/data/data/com.termux/files/usr HOME={PHONE_HOME}\n"
                                     "export PATH=$PREFIX/bin:$PATH LD_LIBRARY_PATH=$PREFIX/lib TMPDIR=$PREFIX/tmp\n" + script).encode("utf-8"))
            running[-1].stdin.close()
        print(f"{len(jobs)} reads in {asked.lanes} lanes; waiting")
        for lane in running:
            lane.wait()
    replies: dict[str, list[str]] = {}
    for name in names:
        replies[name] = []
        for rep in range(1, 61):
            target = reads / name / f"out-{rep}.json"
            if asked.phone and not target.exists() and (reads / name).exists():
                raw = subprocess.run([ADB, "-s", asked.phone, "exec-out", f"run-as com.termux cat {PHONE_HOME}/codex-trial/s2/{WORK.name}/{name}/out-{rep}.json"],
                                     capture_output=True, timeout=60, env=ENV).stdout
                if raw.strip().startswith(b"{"):
                    target.write_bytes(raw)
            if target.exists():
                try:
                    replies[name].append(text_of(json.loads(target.read_text(encoding="utf-8"))))
                except ValueError:
                    continue
    if asked.step == "reference":  # what the reads of the best picture agree on, kept outside the repository
        best = replies.get("N", [])
        if len(best) < 6:
            raise SystemExit(f"{len(best)} reads of N: too few to agree on a text")
        text = agreed(best)
        (PRIVATE / "reference_text.txt").write_text(text, encoding="utf-8")
        apart = [100 * distance(text, one) / len(text) for one in best]
        print(f"reference of {len(text)} characters from {len(best)} reads of N; each read differs from it by "
              f"{' '.join(f'{value:.1f}' for value in apart)} %")
        return 0
    if asked.step in ("run", "score"):
        if not (PRIVATE / "reference_text.txt").exists():
            print("no reference text yet: `reads reference` makes it from the reads of N")
            return 0
        reference = (PRIVATE / "reference_text.txt").read_text(encoding="utf-8")
        means, lines = {}, []
        for name in names:
            shares = [100 * min(within(reference, one), len(reference)) / len(reference) for one in replies[name]]
            if shares:
                means[name] = statistics.mean(shares)
                lines.append(f"{name:8s} reads {len(shares):2d}  wrong % mean {means[name]:5.1f}  sd {statistics.pstdev(shares):4.1f}  "
                             f"each {' '.join(f'{value:.1f}' for value in shares)}")
        report = "\n".join([f"reference: {len(reference)} characters", *lines, "", *verdicts(means)])
        (WORK / "reads.txt").write_text(report + "\n", encoding="utf-8")
        print(report)
    return 0


# ---------------------------------------------------------------- self-check


def demo() -> None:
    import numpy as np

    view = np.full((300, 400), 0.02, np.float32)
    view[90:240, 120:320] = 0.3  # a lit page in a dark room
    view[10:20, 10:30] = 0.3  # a small lamp is not the page
    left, top, wide, tall = bright_box(view)
    assert abs(left - 0.30) < 0.03 and abs(top - 0.30) < 0.03 and abs(wide - 0.50) < 0.04 and abs(tall - 0.50) < 0.04, (left, top, wide, tall)
    assert bright_box(np.full((300, 400), 0.02, np.float32)) is None
    assert box_in((0.25, 0.25, 0.5, 0.5), 2400, 1800) == (600, 450, 1200, 900)
    assert box_in((0.25, 0.25, 0.5, 0.5), 1920, 1080, 0.75) == (480, 180, 960, 720)  # the same place in a clip that shows the middle 0.75
    assert within("かきくけこ", "あいうかきくけこさし") == 0  # what a cut line adds before and after is free
    assert within("かきくけこ", "あかき？けこさ") == 1 and within("かきくけこ", "") == 5 and within("かきくけこ", "かきけこ") == 1
    assert text_of({"lines": ["か き", "く\n"]}) == "かきく" and text_of({}) == ""
    assert agreed(["かきくけこ", "かきくけこ", "かきくけ", "かさくけこ", "かきくけここ"]) == "かきくけこ"
    assert agreed(["あかきく", "かきく", "あかきく", "あかきく"]) == "あかきく"  # most reads have what the middle one may lack
    called = verdicts({"N": 2.0, "Ns": 2.6, "A-288": 3.0, "A-low": 3.4, "W-576": 9.0, "F-416": 2.5, "F-208": 3.1, "F-104": 20.0, "F-52": 80.0})
    assert "pass" in called[0] and "keep it" in called[1] and "fine enough" in called[2] and "kept" in called[3], called
    assert "F-208" in called[4].split(";")[0] and "F-52" in called[4].split(";")[1] and "lower" in called[5] and "drop" in called[6], called
    assert "undecided" in verdicts({"N": 2.0, "F-208": 4.3})[0]
    fed = verdicts({"N": 1.0, "Ns": 6.0, "L30": 1.5, "L30-30": 2.0, "L30low": 1.6, "L60": 5.0, "Fh": 6.5})
    assert "pass" in fed[0] and "keeps it" in fed[1] and "not measured" in fed[2] and "finer grid" in fed[3] and "enough" in fed[4], fed
    assert "lower" in fed[5] and "drop" in fed[6], fed
    lines = np.full((400, 600), 0.5, np.float32)
    lines[:, np.arange(600) % 40 < 20] = 0.1  # print every 40 px across, nothing regular down
    assert abs(pitch(lines)[0] - 40) < 1.5 and pitch(lines)[1] == 0.0, pitch(lines)
    print("ok")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--glasses", default=SERIAL, help="adb transport of the glasses (default: their serial, over USB)")
    parser.add_argument("--run", default="run", help="name of this pass: its folder under data/gather-stage2")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("demo")
    commands.add_parser("frame")
    capture = commands.add_parser("capture")
    capture.add_argument("light", choices=("bright", "dark"))
    capture.add_argument("--only", choices=[*CAPTURES, "N"])
    capture.add_argument("--scale", type=float, default=1.0, help="multiply every exposure by this: 0.5 stands for a page with half the light")
    gather = commands.add_parser("gather")
    gather.add_argument("--page", required=True, help="left,top,width,height of the page as shares of the whole frame")
    gather.add_argument("--rotate", type=int, default=0, help="degrees clockwise that make the page upright")
    reads = commands.add_parser("reads")
    reads.add_argument("step", choices=("prepare", "run", "reference", "score"))
    reads.add_argument("--phone", help="adb transport of the phone")
    reads.add_argument("--reads", type=int, default=12)
    reads.add_argument("--lanes", type=int, default=3)
    reads.add_argument("--only")
    asked = parser.parse_args()
    global GLASSES, WORK
    GLASSES, WORK = asked.glasses, WORK.parent / asked.run
    if asked.command == "demo":
        demo()
        return 0
    WORK.mkdir(parents=True, exist_ok=True)
    return {"frame": cmd_frame, "capture": cmd_capture, "gather": cmd_gather, "reads": cmd_reads}[asked.command](asked)


if __name__ == "__main__":
    sys.exit(main())

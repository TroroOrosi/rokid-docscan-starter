"""Gather the frames of one page into one image: place each frame on the sum so far, add it on a finer grid.

At the venue's light one frame cannot be read whatever its exposure (docs/hardware-measurements.md, M-24): its level
over noise is 2.2 to 4.5 where reading needs about 32, and it grows with the square root of the frames added. The
glasses therefore record a few seconds of short exposures a page and this module turns them into the page
(docs/superpowers/specs/2026-11-15-gathered-capture-design.md, 6.5). What it does is fixed by measurements (M-25):

- Frames are placed by a band-passed correlation against the sum of the frames already placed. Textbook phase
  correlation, which weights every frequency alike, misplaced 21 to 29 of 29 real frames this noisy.
- Frames are added on a grid finer than their own pixels, at sub-pixel positions. On a bright photo with noise added,
  half-size frames gathered that way read like full-size ones (2.3% of characters wrong against 3.3%; 21.2% on their
  own grid). On real dark frames the finer grid helped less (6.7% against 3.2% for the paper's own pixels, M-28).

The result is an average of measured light. Nothing is generated, sharpened or filled in from a model.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

REACHES = (4.0, 16.0)  # frame pixels searched around the last placement: first near, then once wider
WIDE_EXTRA = 3.0  # the wider search has sixteen times the places for noise to peak: its peak must be this much stronger
# A frame is placed when its correlation peak stands this far above the rest of the surface (see _peak). Measured on the
# first real page (M-27, 2026-11-15, parts of 512x172 to 960x324 px of clips of a page of print): frames of the page 9.4
# to 187 at the present light and 5.6 to 23 at half of it (the low end against a sum of one frame, rising as frames are
# added); noise alone up to 7.6 within 4 px and 9.3 within 16 px; the facing page of the same booklet up to 5.6, 7.0 at
# half the light. Until that day the peak was judged against the whole surface and a share of the first frames' value,
# with a floor of 7.0 from a desk scene (M-26): on print that measure stays at 4 to 8 whatever the light.
# ponytail: a page whose characters fill their cells exactly like this page's would pass (generated: 11 to 31); the real
# facing page did not. If a real one does, also ask what share of the sum's pattern the frame holds (1 against its own page).
STRENGTH_FLOOR = 8.0
SETTLE = 6  # frames at the start of a clip that are not used: the glasses' first three are darker than asked (M-26)
SURPLUS = 3  # a clip holds up to this many frames more than the glasses logged results for, at its end (M-26)
HOLE_SHARE = 0.05  # a grid cell that received under this share of the typical weight is filled from the plain average
PART_REACH = 2.0  # frame pixels a part of a frame is searched around the whole frame's placement
PART_OUTLIER = 1.5  # a part placed further than this from the parts' median is left out of the fit
PARTS_FROM = 4  # frames in the sum before parts are placed against it
COARSE_SIDE = 384  # a frame is first placed on a copy joined down until its short side is about this many pixels
WINDOW = 256  # frame pixels a side of the piece of each part that is placed
STEP = 0.25  # frame pixels the fitted shift may change across one block that is added at one shift
BLOCKS = (64, 512)  # the smallest and the largest block, frame pixels a side
FLAT = 0.5  # frame pixels: a fitted shift that changes less than this from edge to edge is one shift for the whole frame
FRESH_UNTIL = 16  # while the sum holds fewer frames than this, its transform is taken anew for every frame
REFRESH = 4  # after that, the sum's transform is reused for this many frames: three more frames change it little
DECODE_SECONDS = 30  # the decoder is stuck when one frame takes this long to come; how long the reader takes is its own affair


class GatherError(RuntimeError):
    """A clip could not be read. The message says why."""


class GatherTimeout(GatherError):
    """A clip was not gathered within the time it was given."""


@dataclass(frozen=True)
class Gathered:
    image: np.ndarray  # float32 light on the finer grid: (grid * h, grid * w)
    used: int  # frames added
    total: int  # frames offered
    level_over_noise: float  # of the result, from two halves of the frames added; 0.0 when fewer than 4 were added
    placed: bool  # False when no frame was usable or half or more of the usable ones could not be placed
    selection: str  # "motion" when smear values chose the frames, "none" when every frame was offered


@lru_cache(maxsize=8)
def _tools(shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """The window, and the band kept: above the slow shading, below the finest third where noise rules."""
    h, w = shape
    window = np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)
    radius = np.hypot(np.fft.fftfreq(h)[:, None], np.fft.rfftfreq(w)[None, :])
    band = ((radius > 4.0 / min(h, w)) * np.exp(-(radius / 0.17) ** 2)).astype(np.float32)
    return window, band


def _spectrum(image: np.ndarray) -> np.ndarray:
    window, _ = _tools(image.shape)
    return np.fft.rfft2((image - image.mean()) * window)


def _reference_side(reference: np.ndarray) -> np.ndarray:
    """The half of the correlation that belongs to the sum: reusable while the sum changes little."""
    _, band = _tools(reference.shape)
    return np.conj(_spectrum(reference)) * band


def _own(reference: np.ndarray, side: np.ndarray) -> np.ndarray:
    """The sum correlated with itself: the pattern its own print leaves on every correlation surface, peak at (0, 0)."""
    return np.fft.irfft2(_spectrum(reference) * side, s=reference.shape)


def _peak(cross: np.ndarray, shape: tuple[int, int], around: tuple[float, float], reach: float,
          own: np.ndarray | None = None) -> tuple[float, float, float]:
    """The correlation's peak within `reach` of `around`, from the cross spectrum; sub-pixel by a parabola through it.

    The strength is the peak over the spread of the surface, after the sum's own pattern (`own`, scaled to the peak and
    put at the peak) is taken out of the surface. Print is regular: lines and characters repeat, and the surface of a
    well-placed frame is full of side peaks that are the page, not noise. Judged against them a frame of a real page
    scored 6 to 8 and noise alone up to 7 (M-27); with them taken out the page scores 12 to 200 and noise the same 7.

    The whole surface is transformed back. Computing only the points near `around` by a matrix product is fewer
    operations, but it ran several times slower beside the decoder, which takes the threads the product wants.
    """
    h, w = shape
    surface = np.fft.irfft2(cross, s=shape)
    yy = (np.arange(h) - around[0] + h / 2) % h - h / 2
    xx = (np.arange(w) - around[1] + w / 2) % w - w / 2
    limited = np.where(yy[:, None] ** 2 + xx[None, :] ** 2 <= reach ** 2, surface, -np.inf)
    py, px = np.unravel_index(int(np.argmax(limited)), limited.shape)

    def finer(minus: float, mid: float, plus: float) -> float:
        bend = minus - 2 * mid + plus
        return 0.0 if bend >= 0 else float(np.clip(0.5 * (minus - plus) / bend, -0.5, 0.5))

    dy = py + finer(surface[(py - 1) % h, px], surface[py, px], surface[(py + 1) % h, px])
    dx = px + finer(surface[py, (px - 1) % w], surface[py, px], surface[py, (px + 1) % w])
    top = float(surface[py, px])
    if own is not None and own[0, 0] > 0:
        surface = surface - (top / float(own[0, 0])) * np.roll(own, (py, px), (0, 1))
    spread = float(surface.std())
    return float((dy + h / 2) % h - h / 2), float((dx + w / 2) % w - w / 2), top / spread if spread > 0 else 0.0


def shift_of(frame: np.ndarray, reference: np.ndarray, around: tuple[float, float] = (0.0, 0.0), reach: float = 4.0) -> tuple[float, float, float]:
    """(dy, dx, strength) with frame(y, x) = reference(y - dy, x - dx), looked for within `reach` pixels of `around`.

    strength is the correlation peak over the spread of the rest of the correlation surface (see _peak): high when the
    two show one scene.
    """
    side = _reference_side(reference)
    return _peak(_spectrum(frame) * side, frame.shape, around, reach, _own(reference, side))


def _joined(image: np.ndarray, k: int) -> np.ndarray:
    h, w = image.shape[0] // k * k, image.shape[1] // k * k
    return image[:h, :w].reshape(h // k, k, w // k, k).mean(axis=(1, 3))


class _Planes:
    """Light added at sub-pixel positions. The finer grid is kept as one plane a position inside a frame pixel: plane
    [py, px] holds the grid cells (grid * y + py, grid * x + px), so that adding a frame is a few adds of whole blocks
    of memory. Two halves are kept apart: their difference is the noise."""

    def __init__(self, shape: tuple[int, int], grid: int) -> None:
        self.grid = grid
        self.sums = np.zeros((2, grid, grid, *shape), np.float32)
        self.weights = np.zeros((2, grid, grid, *shape), np.float32)
        self._scratch = np.empty(shape, np.float32)

    def add(self, half: int, block: np.ndarray, dy: float, dx: float, top: int = 0, left: int = 0) -> None:
        """Add a frame (or the block of it that starts at row `top`, column `left`) known to be the scene moved by
        (dy, dx) frame pixels, shared between the two nearest grid cells each way by distance."""
        grid = self.grid
        h, w = self.sums.shape[-2:]
        bh, bw = block.shape
        ty, tx = grid / 2 - 0.5 - grid * dy, grid / 2 - 0.5 - grid * dx  # the cell under the centre of a pixel, less grid * its index
        y0, x0 = math.floor(ty), math.floor(tx)
        for cell_y, share_y in ((y0, 1 - (ty - y0)), (y0 + 1, ty - y0)):
            move_y, plane_y = divmod(cell_y, grid)
            j0, j1 = max(0, -(top + move_y)), min(bh, h - top - move_y)
            for cell_x, share_x in ((x0, 1 - (tx - x0)), (x0 + 1, tx - x0)):
                move_x, plane_x = divmod(cell_x, grid)
                i0, i1 = max(0, -(left + move_x)), min(bw, w - left - move_x)
                share = share_y * share_x
                if share < 0.02 or j1 <= j0 or i1 <= i0:
                    continue
                rows, columns = slice(top + move_y + j0, top + move_y + j1), slice(left + move_x + i0, left + move_x + i1)
                shared = np.multiply(block[j0:j1, i0:i1], share, out=self._scratch[:j1 - j0, :i1 - i0])
                self.sums[half, plane_y, plane_x, rows, columns] += shared
                self.weights[half, plane_y, plane_x, rows, columns] += share

    def _woven(self, planes: np.ndarray) -> np.ndarray:
        grid = self.grid
        h, w = planes.shape[-2:]
        return planes.transpose(2, 0, 3, 1).reshape(grid * h, grid * w)

    def result(self, plain: np.ndarray) -> tuple[np.ndarray, float]:
        """(the image on the finer grid, its level over noise). `plain` is the frames' plain average for cells too little
        reached, NaN where no frame showed that place at all: those cells get the image's median, which claims nothing."""
        weight = self._woven(self.weights[0] + self.weights[1])
        typical = float(np.median(weight))
        image = self._woven(self.sums[0] + self.sums[1]) / np.maximum(weight, 1e-6)
        holes = weight < HOLE_SHARE * typical
        if holes.any():
            image[holes] = np.repeat(np.repeat(plain, self.grid, 0), self.grid, 1)[holes]
            unseen = np.isnan(image)
            if unseen.any():
                image[unseen] = float(np.median(image[~unseen])) if (~unseen).any() else 0.0
        both = (self.weights[0] > HOLE_SHARE * typical / 2) & (self.weights[1] > HOLE_SHARE * typical / 2)
        ratio = 0.0
        if both.any():
            difference = (self.sums[0] / np.maximum(self.weights[0], 1e-6) - self.sums[1] / np.maximum(self.weights[1], 1e-6))[both]
            noise = float(difference.std()) / 2
            ratio = float(np.percentile(image, 90)) / noise if noise > 0 else 0.0
        return image.astype(np.float32), ratio


def _field(frame: np.ndarray, side, dy: float, dx: float, parts: int, reach: float) -> np.ndarray | None:
    """How the shift changes across the frame (a tilted head, a bent page): a piece of each part of the frame is placed
    by itself, and a plane is fitted through the pieces' shifts. Rows: constant, per row, per column; columns: dy, dx.
    None when too few pieces agree, and the whole frame's shift stands. side(box) gives the sum's half of the correlation
    for that piece."""
    h, w = frame.shape
    centres, shifts = [], []
    for py in range(parts):
        for px in range(parts):
            cy, cx = (2 * py + 1) * h // (2 * parts), (2 * px + 1) * w // (2 * parts)
            half_y, half_x = min(WINDOW, h // parts) // 2, min(WINDOW, w // parts) // 2
            box = (slice(cy - half_y, cy + half_y), slice(cx - half_x, cx + half_x))
            sy, sx, _ = _peak(_spectrum(frame[box]) * side(box), (2 * half_y, 2 * half_x), (dy, dx), reach)
            centres.append((cy, cx))
            shifts.append((sy, sx))
    found = np.array(shifts)
    agree = np.hypot(*(found - np.median(found, axis=0)).T) <= PART_OUTLIER
    if int(agree.sum()) < 4:
        return None
    design = np.column_stack([np.ones(int(agree.sum())), np.array(centres, dtype=np.float64)[agree]])
    return np.linalg.lstsq(design, found[agree], rcond=None)[0]


def _add_back(total: np.ndarray, frame: np.ndarray, dy: int, dx: int, count: np.ndarray | None = None) -> None:
    """Add a frame moved back by whole pixels. What moves out is dropped and what moves in is nothing: no wrap-around,
    which would put the far edge's picture at this edge."""
    h, w = frame.shape
    rows, columns = slice(max(0, -dy), min(h, h - dy)), slice(max(0, -dx), min(w, w - dx))
    if rows.stop <= rows.start or columns.stop <= columns.start:
        return
    total[rows, columns] += frame[rows.start + dy:rows.stop + dy, columns.start + dx:columns.stop + dx]
    if count is not None:
        count[rows, columns] += 1


def gather(frames: Iterable[np.ndarray], *, smear: Sequence[float] | None = None, smear_limit: float = 2.0, grid: int = 2,
           parts: int = 3) -> Gathered:
    """Gather frames of one scene into one image on a grid `grid` times finer than the frames.

    frames: 2-D arrays of light, all one shape, in the order taken. smear: for each frame, how many pixels the picture
    moved during its exposure (from the gyroscope); frames over smear_limit are not used. parts: each frame is also
    placed in parts x parts pieces, to follow tilt and bend; 1 moves every frame as a whole.

    A frame is placed in two steps: on a copy joined down to a short side of about COARSE_SIDE pixels, which also says
    whether it shows this scene at all, then piece by piece at full size around that.
    """
    selection = "none" if smear is None else "motion"
    total = usable = used = 0
    planes = reference = coarse = covered = shape = None
    join = 1
    position = (0.0, 0.0)
    held: dict[object, tuple[int, np.ndarray, np.ndarray | None]] = {}

    def side(key: object, source) -> np.ndarray:
        """The sum's half of the correlation for the whole (key None) or a piece (key = its box), taken anew when stale.
        For the whole, the sum's own pattern is kept beside it: it is what the frame's strength is judged without."""
        kept = held.get(key)
        if kept is None or used < FRESH_UNTIL or used - kept[0] >= REFRESH:
            summed = source()
            half = _reference_side(summed)
            kept = (used, half, _own(summed, half) if key is None else None)
            held[key] = kept
        return kept[1]

    for index, frame in enumerate(frames):
        frame = np.asarray(frame, dtype=np.float32)
        if shape is None:
            shape = frame.shape
            join = max(1, min(shape) // COARSE_SIDE)
            planes = _Planes(shape, grid)
        elif frame.shape != shape:
            raise ValueError(f"frame {index} is {frame.shape}, the first was {shape}")
        total += 1
        if smear is not None and (index >= len(smear) or smear[index] > smear_limit):
            continue
        usable += 1
        small = _joined(frame, join) if join > 1 else frame
        field = None
        if reference is None:
            dy = dx = 0.0
        else:
            cross = _spectrum(small) * side(None, lambda: coarse)
            for reach in REACHES:
                dy, dx, strength = _peak(cross, small.shape, (position[0] / join, position[1] / join), max(2.0, reach / join),
                                         held[None][2])
                if strength >= STRENGTH_FLOOR + (WIDE_EXTRA if reach > REACHES[0] else 0.0):
                    break
            else:
                continue  # not this scene: the view left the page, or something came between
            dy, dx = dy * join, dx * join
            if parts > 1 and used >= PARTS_FROM:
                field = _field(frame, lambda box: side((box[0].start, box[1].start), lambda: reference[box]), dy, dx, parts,
                               PART_REACH + (join - 1) / 2)
                if field is not None:
                    dy, dx = (float(v) for v in field[0] + shape[0] / 2 * field[1] + shape[1] / 2 * field[2])
                    if float((np.abs(field[1]) * shape[0] + np.abs(field[2]) * shape[1]).max()) < FLAT:
                        field = None  # no tilt worth following: the whole frame goes in at the fitted centre shift
        position = (dy, dx)
        if field is None:
            planes.add(used % 2, frame, dy, dx)
        else:
            steepest = float(np.abs(field[1:]).max())
            block = int(min(BLOCKS[1], max(BLOCKS[0], STEP / steepest))) if steepest > 0 else BLOCKS[1]
            for top in range(0, shape[0], block):
                for left in range(0, shape[1], block):
                    piece = frame[top:top + block, left:left + block]
                    by, bx = field[0] + (top + piece.shape[0] / 2) * field[1] + (left + piece.shape[1] / 2) * field[2]
                    planes.add(used % 2, piece, float(by), float(bx), top, left)
        if reference is None:
            reference, covered = np.zeros(shape, np.float32), np.zeros(shape, np.uint16)
            coarse = np.zeros(small.shape, np.float32) if join > 1 else reference
        _add_back(reference, frame, round(dy), round(dx), covered)
        if join > 1:
            _add_back(coarse, small, round(dy / join), round(dx / join))
        used += 1
    if shape is None:
        return Gathered(np.zeros((0, 0), np.float32), 0, total, 0.0, False, selection)
    if used == 0:
        return Gathered(np.zeros((grid * shape[0], grid * shape[1]), np.float32), 0, total, 0.0, False, selection)
    image, ratio = planes.result(np.where(covered > 0, reference / np.maximum(covered, 1), np.nan))
    return Gathered(image, used, total, ratio if used >= 4 else 0.0, used * 2 > usable, selection)


def _ffmpeg(binary: str | None) -> str:
    named = binary or os.environ.get("ROKID_FFMPEG") or "ffmpeg"
    found = shutil.which(named)
    if not found:
        raise GatherError(f"ffmpeg is not available ({named})")
    return found


def _described(binary: str, path: Path) -> tuple[int, int, int | None]:
    """(width, height, frames) of a clip's video; frames is None when the container does not say."""
    try:
        said = subprocess.run([binary, "-hide_banner", "-i", str(path), "-map", "0:v:0", "-c", "copy", "-f", "null", "-"],
                              capture_output=True, timeout=DECODE_SECONDS, stdin=subprocess.DEVNULL).stderr.decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired) as error:
        raise GatherError(f"ffmpeg could not read {path.name}: {type(error).__name__}") from error
    size = re.search(r"Video:.*?\b(\d{2,5})x(\d{2,5})\b", said)
    if not size:
        lines = [line.strip() for line in said.splitlines() if line.strip()]
        raise GatherError(f"ffmpeg found no video in {path.name}: {lines[-1] if lines else 'no output'}")
    counted = re.findall(r"frame=\s*(\d+)", said)
    return int(size.group(1)), int(size.group(2)), int(counted[-1]) if counted else None


_LIGHT = np.array([(v / 255 / 12.92) if v / 255 <= 0.04045 else ((v / 255 + 0.055) / 1.055) ** 2.4 for v in range(256)], np.float32)


def read_clip(path: Path, *, crop: tuple[int, int, int, int] | None = None, ffmpeg: str | None = None, black: float = 0.0) -> Iterator[np.ndarray]:
    """The frames of a clip as light: luma with the display curve undone and `black` subtracted, never below zero.

    crop is (left, top, width, height) in the clip's pixels. ffmpeg names the binary; by default ROKID_FFMPEG, else
    `ffmpeg` on the path. Raises GatherError when the binary is missing, the clip cannot be decoded or holds no frame.
    """
    path = Path(path)
    binary = _ffmpeg(ffmpeg)
    width, height, _ = _described(binary, path)
    if crop is not None:
        left, top, width, height = crop
    command = [binary, "-v", "error", "-i", str(path), "-map", "0:v:0"]
    if crop is not None:
        command += ["-vf", f"crop={width}:{height}:{left}:{top}"]
    # passthrough: without it the decoder fills a gap in the clip's times with copies of the last frame, and the frames no
    # longer pair with what the glasses logged
    process = subprocess.Popen([*command, "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "gray", "-"], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
    stuck: list[bool] = []

    def stop() -> None:
        stuck.append(True)
        process.kill()

    count = 0
    try:
        while True:
            watchdog = threading.Timer(DECODE_SECONDS, stop)  # for this one frame: a slow reader is not a stuck decoder
            watchdog.daemon = True
            watchdog.start()
            try:
                raw = process.stdout.read(width * height)
            finally:
                watchdog.cancel()
            if len(raw) < width * height:
                break
            count += 1
            light = _LIGHT[np.frombuffer(raw, np.uint8)].reshape(height, width)
            yield np.maximum(light - black, 0) if black else light
        if stuck:
            raise GatherError(f"ffmpeg timed out on {path.name}: no frame for {DECODE_SECONDS} s after {count} frames")
        said = process.stderr.read().decode("utf-8", "replace").strip().splitlines()
        if process.wait() != 0 or count == 0:
            raise GatherError(f"ffmpeg gave {count} frames of {path.name}: {said[-1] if said else 'no message'}")
    finally:
        process.kill()
        process.stdout.close()
        process.stderr.close()
        process.wait()


def _within(frames: Iterable[np.ndarray], deadline: float) -> Iterator[np.ndarray]:
    for frame in frames:
        if time.monotonic() > deadline:
            raise GatherTimeout("timeout")
        yield frame


def gather_clip(path: Path, record: dict | None = None, *, crop: tuple[int, int, int, int] | None = None, ffmpeg: str | None = None,
                black: float = 0.0, settle: int = SETTLE, limit: int | None = None, seconds: float | None = None,
                **options) -> Gathered:
    """One recorded page into its image.

    record is what the glasses wrote beside the clip: record["frames"][k]["smear_px"] belongs to the clip's frame k and
    chooses the frames. The clip may hold up to SURPLUS frames more than the record (frames encoded after the last
    logged result); they are not used. A record of any other length is not trusted and every frame is offered.
    The first `settle` frames are left out: they are darker than the rest and would set where the page is put.
    limit: use only that many frames after them (how good is the page with less light?).
    seconds: give up with GatherTimeout once this long has passed, looked at before each frame (the server's worker
    must come back to the next page's clip).
    """
    path = Path(path)
    smear = None
    listed = record.get("frames") if isinstance(record, dict) else None
    if isinstance(listed, list) and listed:
        _, _, frames = _described(_ffmpeg(ffmpeg), path)
        if frames is not None and 0 <= frames - len(listed) <= SURPLUS and all(isinstance(entry, dict) and "smear_px" in entry for entry in listed):
            smear = [float(entry["smear_px"]) for entry in listed][settle:]
    end = None if limit is None else settle + limit
    if smear is not None and limit is not None:
        smear = smear[:limit]
    frames = itertools.islice(read_clip(path, crop=crop, ffmpeg=ffmpeg, black=black), settle, end)
    return gather(frames if seconds is None else _within(frames, time.monotonic() + seconds), smear=smear, **options)


def main(arguments: Sequence[str] | None = None) -> int:
    """`python -m app.gather clip.mp4 --out page.png`: the page as a 16-bit grey PNG, and one line of JSON about it."""
    parser = argparse.ArgumentParser(description="Gather one recorded page into an image.")
    parser.add_argument("clip", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--record", type=Path, help="the JSON the glasses wrote beside the clip")
    parser.add_argument("--crop", help="left,top,width,height in the clip's pixels")
    parser.add_argument("--black", type=float, default=0.0, help="light to subtract from every pixel")
    parser.add_argument("--frames", type=int, help="use only this many frames, after the first ones that are always left out")
    asked = parser.parse_args(arguments)
    started = time.monotonic()
    try:
        record = json.loads(asked.record.read_text(encoding="utf-8")) if asked.record else None
        crop = tuple(int(value) for value in asked.crop.split(",")) if asked.crop else None
        result = gather_clip(asked.clip, record, crop=crop, black=asked.black, limit=asked.frames)
    except (GatherError, OSError, ValueError) as error:
        print(json.dumps({"error": str(error)}))
        return 1
    if result.used:
        from PIL import Image

        white = float(np.percentile(result.image, 99.5)) or 1.0
        Image.fromarray(np.round(np.clip(result.image / white, 0, 1) * 65535).astype(np.uint16)).save(asked.out)
    print(json.dumps({"used": result.used, "total": result.total, "level_over_noise": round(result.level_over_noise, 2),
                      "placed": result.placed, "selection": result.selection, "seconds": round(time.monotonic() - started, 2)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

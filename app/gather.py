"""Gather the frames of one page into one image: place each frame on the sum so far, add it on a finer grid.

At the venue's light one frame cannot be read whatever its exposure (docs/hardware-measurements.md, M-24): its level
over noise is 2.2 to 4.5 where reading needs about 32, and it grows with the square root of the frames added. The
glasses therefore record a few seconds of short exposures a page and this module turns them into the page
(docs/superpowers/specs/2026-11-15-gathered-capture-design.md, 6.5). What it does is fixed by measurements (M-25):

- Frames are placed by a band-passed correlation against the sum of the frames already placed. Textbook phase
  correlation, which weights every frequency alike, misplaced 21 to 29 of 29 real frames this noisy.
- Frames are added on a grid finer than their own pixels, at sub-pixel positions. Half-size frames gathered that way
  read like full-size ones (2.3% of characters wrong against 3.3%); added on their own grid they do not (21.2%).

The result is an average of measured light. Nothing is generated, sharpened or filled in from a model.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

REACHES = (4.0, 16.0)  # frame pixels searched around the last placement: first near, then once wider
STRENGTH_SHARE = 0.5  # a frame is placed when its correlation peak is this share of the first frames' typical peak
HOLE_SHARE = 0.05  # a grid cell that received under this share of the typical weight is filled from the plain average
PART_REACH = 2.0  # frame pixels a part of a frame is searched around the whole frame's placement
PART_OUTLIER = 1.5  # a part placed further than this from the parts' median is left out of the fit
PARTS_FROM = 4  # frames in the sum before parts are placed against it
BLOCK = 64  # frame pixels a side: each block is added at the fitted shift of its centre


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


def _surface(frame: np.ndarray, reference: np.ndarray) -> np.ndarray:
    window, band = _tools(frame.shape)
    cross = np.fft.rfft2((frame - frame.mean()) * window) * np.conj(np.fft.rfft2((reference - reference.mean()) * window)) * band
    return np.fft.irfft2(cross, s=frame.shape)


def _peak(surface: np.ndarray, around: tuple[float, float], reach: float) -> tuple[float, float, float]:
    h, w = surface.shape
    yy = (np.arange(h) - around[0] + h / 2) % h - h / 2
    xx = (np.arange(w) - around[1] + w / 2) % w - w / 2
    limited = np.where(yy[:, None] ** 2 + xx[None, :] ** 2 <= reach ** 2, surface, -np.inf)
    py, px = np.unravel_index(int(np.argmax(limited)), limited.shape)

    def finer(minus: float, mid: float, plus: float) -> float:
        bend = minus - 2 * mid + plus
        return 0.0 if bend >= 0 else float(np.clip(0.5 * (minus - plus) / bend, -0.5, 0.5))

    dy = py + finer(surface[(py - 1) % h, px], surface[py, px], surface[(py + 1) % h, px])
    dx = px + finer(surface[py, (px - 1) % w], surface[py, px], surface[py, (px + 1) % w])
    spread = float(surface.std())
    return float((dy + h / 2) % h - h / 2), float((dx + w / 2) % w - w / 2), float(surface[py, px] / spread) if spread > 0 else 0.0


def shift_of(frame: np.ndarray, reference: np.ndarray, around: tuple[float, float] = (0.0, 0.0), reach: float = 4.0) -> tuple[float, float, float]:
    """(dy, dx, strength) with frame(y, x) = reference(y - dy, x - dx), looked for within `reach` pixels of `around`.

    strength is the correlation peak over the spread of the whole correlation surface: high when the two show one scene.
    """
    return _peak(_surface(frame, reference), around, reach)


def _splat(total: np.ndarray, weight: np.ndarray, frame: np.ndarray, dy: float, dx: float, grid: int, top: int = 0, left: int = 0) -> None:
    """Add a frame (or the block of it that starts at row `top`, column `left`) known to be the scene moved by (dy, dx)
    frame pixels onto the finer grid, shared between the two nearest cells each way by distance."""
    h, w = frame.shape
    # the cell under the centre of the block's first pixel
    ty, tx = grid / 2 - 0.5 - grid * dy + grid * top, grid / 2 - 0.5 - grid * dx + grid * left
    y0, x0 = math.floor(ty), math.floor(tx)
    for oy, share_y in ((y0, 1 - (ty - y0)), (y0 + 1, ty - y0)):
        j0, j1 = max(0, math.ceil(-oy / grid)), min(h, (total.shape[0] - 1 - oy) // grid + 1)
        for ox, share_x in ((x0, 1 - (tx - x0)), (x0 + 1, tx - x0)):
            i0, i1 = max(0, math.ceil(-ox / grid)), min(w, (total.shape[1] - 1 - ox) // grid + 1)
            share = share_y * share_x
            if share < 0.02 or j1 <= j0 or i1 <= i0:
                continue
            rows, columns = slice(oy + grid * j0, oy + grid * (j1 - 1) + 1, grid), slice(ox + grid * i0, ox + grid * (i1 - 1) + 1, grid)
            total[rows, columns] += share * frame[j0:j1, i0:i1]
            weight[rows, columns] += share


def _field(frame: np.ndarray, reference: np.ndarray, dy: float, dx: float, parts: int) -> np.ndarray | None:
    """How the shift changes across the frame (a tilted head, a bent page): parts of the frame placed one by one, and
    a plane fitted through their shifts. Rows: constant, per row, per column; columns: dy, dx. None when too few parts
    agree, and the whole frame's shift stands."""
    h, w = frame.shape
    centres, shifts = [], []
    for py in range(parts):
        for px in range(parts):
            box = (slice(py * h // parts, (py + 1) * h // parts), slice(px * w // parts, (px + 1) * w // parts))
            sy, sx, _ = _peak(_surface(frame[box], reference[box]), (dy, dx), PART_REACH)
            centres.append(((box[0].start + box[0].stop) / 2, (box[1].start + box[1].stop) / 2))
            shifts.append((sy, sx))
    found = np.array(shifts)
    agree = np.hypot(*(found - np.median(found, axis=0)).T) <= PART_OUTLIER
    if int(agree.sum()) < 4:
        return None
    design = np.column_stack([np.ones(int(agree.sum())), np.array(centres)[agree]])
    return np.linalg.lstsq(design, found[agree], rcond=None)[0]


def _splat_field(total: np.ndarray, weight: np.ndarray, frame: np.ndarray, field: np.ndarray, grid: int) -> None:
    h, w = frame.shape
    for top in range(0, h, BLOCK):
        for left in range(0, w, BLOCK):
            block = frame[top:top + BLOCK, left:left + BLOCK]
            dy, dx = field[0] + (top + block.shape[0] / 2) * field[1] + (left + block.shape[1] / 2) * field[2]
            _splat(total, weight, block, float(dy), float(dx), grid, top, left)


def gather(frames: Iterable[np.ndarray], *, smear: Sequence[float] | None = None, smear_limit: float = 2.0, grid: int = 2,
           parts: int = 3) -> Gathered:
    """Gather frames of one scene into one image on a grid `grid` times finer than the frames.

    frames: 2-D arrays of light, all one shape, in the order taken. smear: for each frame, how many pixels the picture
    moved during its exposure (from the gyroscope); frames over smear_limit are not used. parts: each frame is also
    placed in parts x parts pieces, to follow tilt and bend; 1 moves every frame as a whole.
    """
    selection = "none" if smear is None else "motion"
    total = usable = used = 0
    sums = weights = reference = shape = None
    strengths: list[float] = []
    position = (0.0, 0.0)
    for index, frame in enumerate(frames):
        frame = np.asarray(frame, dtype=np.float32)
        if sums is None:
            shape = frame.shape
            fine = (grid * shape[0], grid * shape[1])
            sums, weights = np.zeros((2, *fine), np.float32), np.zeros((2, *fine), np.float32)
        elif frame.shape != shape:
            raise ValueError(f"frame {index} is {frame.shape}, the first was {shape}")
        total += 1
        if smear is not None and (index >= len(smear) or smear[index] > smear_limit):
            continue
        usable += 1
        if reference is None:
            dy = dx = 0.0
        else:
            surface = _surface(frame, reference)
            floor = STRENGTH_SHARE * float(np.median(strengths[:7])) if len(strengths) >= 3 else 0.0
            for reach in REACHES:
                dy, dx, strength = _peak(surface, position, reach)
                if strength >= floor:
                    break
            else:
                continue  # not this scene: the view left the page, or something came between
            strengths.append(strength)
        position = (dy, dx)
        field = _field(frame, reference, dy, dx, parts) if parts > 1 and used >= PARTS_FROM else None
        if field is None:
            _splat(sums[used % 2], weights[used % 2], frame, dy, dx, grid)
        else:
            _splat_field(sums[used % 2], weights[used % 2], frame, field, grid)
        back = np.roll(frame, (-round(dy), -round(dx)), (0, 1))
        reference = back.copy() if reference is None else reference + back
        used += 1
    if sums is None:
        return Gathered(np.zeros((0, 0), np.float32), 0, total, 0.0, False, selection)
    if used == 0:
        return Gathered(np.zeros(sums.shape[1:], np.float32), 0, total, 0.0, False, selection)
    weight = weights[0] + weights[1]
    typical = float(np.median(weight))
    image = (sums[0] + sums[1]) / np.maximum(weight, 1e-6)
    holes = weight < HOLE_SHARE * typical
    if holes.any():
        image[holes] = np.repeat(np.repeat(reference / used, grid, 0), grid, 1)[holes]
    ratio = 0.0
    if used >= 4:
        both = (weights[0] > HOLE_SHARE * typical / 2) & (weights[1] > HOLE_SHARE * typical / 2)
        if both.any():
            difference = (sums[0] / np.maximum(weights[0], 1e-6) - sums[1] / np.maximum(weights[1], 1e-6))[both]
            noise = float(difference.std()) / 2
            ratio = float(np.percentile(image[both], 90)) / noise if noise > 0 else 0.0
    return Gathered(image.astype(np.float32), used, total, ratio, used * 2 > usable, selection)

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
import logging
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

REACHES = (4.0, 16.0)  # frame pixels searched around where the frame is expected: first near, then once wider
# Frame pixels a frame is looked for around the frame before it, to follow the head between the frames that are added.
# Worn (M-31, 30 frames a second): a step of 2 to 4 px in the middle, 5 to 12 px one frame in ten, 23 px at most while
# a page was read; twice that at 15 frames a second.
TRACK_REACH = 64.0
# A frame that lies further than this (frame pixels) from where the first one lay is laid on the page by a map of its own:
# shift, turn, scale and perspective, a homography. A head does not only move the picture, it tilts and sees the page
# from another side: against a move of 44 px the edges of a worn frame lay another 15 to 19 px off, and added at one
# shift the page was sharp in the middle and double towards its edges (M-31). Once one frame needed a map, every later
# one gets one. A clip from glasses that lie still never moves this far, and goes the way it was measured on (M-29).
FAR = 8.0
# The map is found coarse to fine, on copies joined this many times more than the placing copy. Not on that copy itself:
# found down to it the pages were no better (the turning head of the tests 0.9515 against 0.9516 alike, a worn page's
# fine detail 26.35 both ways) and took 56 s instead of 40. Stopping one size sooner still, the detail fell (26.15).
MAP_SIZES = (8, 4, 2)
MAP_STEPS = 6  # Gauss-Newton steps a size at most
MAP_STANDS = 0.02  # pixels of that size: a step that moves no place further has found the map
MAP_LEAST = 32  # pixels a side under which a size is skipped
MAP_FLOOR = 0.15  # how alike (correlation, in the band) the frame brought back and the page must be for it to be added
# The same where no single shift placed the frame and the map alone says that it shows the page: a head that came back
# from looking away a little further from the page, its picture an eighth smaller in area, matched the page at one
# shift with 7.1 to 8.2 where 8 is asked, and a run of twenty still frames was lost (M-31). Worn frames laid by a map
# were 0.67 to 0.98 alike to their page.
MAP_SURE = 0.5
# How far a frame's map may differ in area from the first frame's (the map's own measure at the frame's corner) and
# still be believed. On 2026-11-17 one worn clip lost 27 of its 58 still frames at 0.791 to 0.797, each 0.76 to 0.87
# alike to its page (M-44 (15)(c)), and the limit looked a hair too tight. Widened to 0.7, those frames were added
# (33 to 60, level over noise 39.0 to 47.5) and did not lie on the page: against the first frames their picture was
# off by 12 px and more at the left edge, 4 to 9 px beside it, 0 to 3 px on the right, and the strongest edges of
# print were 17% flatter in the left third. One map does not carry a view that far from the first frame's onto the
# page (a synthetic picture, which has no lens and no curl, cannot show this: there the frames lie exactly). Kept.
MAP_AREA = (0.8, 1.25)
# A page is begun again at a still frame that does not go on it when at least this many times its frames are still to
# come (begun_again). 4: a head that looked away and came back (10, 10, then 20 frames) keeps its page; the clip of
# 2026-11-17 that was not placed held 3 frames with 58 to come.
AGAIN = 4
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


_LOG = logging.getLogger(__name__)


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


def _banded(image: np.ndarray, fill: float | None = None, where: np.ndarray | None = None) -> np.ndarray:
    """The picture without its slow shading, which stays with the lens and not with the page, and without the finest
    third, where noise rules. Places outside `where` are given `fill` first, so that no edge is made there."""
    if where is not None:
        image = np.where(where, image, fill)
    radius = np.hypot(np.fft.fftfreq(image.shape[0])[:, None], np.fft.rfftfreq(image.shape[1])[None, :])
    band = np.exp(-(radius / 0.25) ** 2) - np.exp(-(radius / 0.03) ** 2)
    return np.fft.irfft2(np.fft.rfft2(image - image.mean()) * band, s=image.shape).astype(np.float32)


def _units(shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray, float]:
    """Pixel centres about the picture's centre in units of half its longer side: one map serves every size of a picture."""
    h, w = shape
    unit = max(h, w) / 2
    return (((np.arange(h) - (h - 1) / 2) / unit).astype(np.float32)[:, None],
            ((np.arange(w) - (w - 1) / 2) / unit).astype(np.float32)[None, :], unit)


def _through(m: np.ndarray, y: np.ndarray, x: np.ndarray, unit: float, centre: tuple[float, float]) -> tuple[np.ndarray, np.ndarray]:
    """(row, column) in pixels of the places (y, x in units) taken through m. Scaling to pixels and the centre are
    folded into the numerators: three sums of a column and a row and two divisions, in the pictures' single precision."""
    (a, b, c), (d, e, f), (g, k, n) = m.tolist()
    den = np.float32(g) * x + (np.float32(k) * y + np.float32(n))
    column = (np.float32(a * unit + centre[1] * g) * x + (np.float32(b * unit + centre[1] * k) * y + np.float32(c * unit + centre[1] * n))) / den
    row = (np.float32(d * unit + centre[0] * g) * x + (np.float32(e * unit + centre[0] * k) * y + np.float32(f * unit + centre[0] * n))) / den
    return row, column


def _brought_back(frame: np.ndarray, m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """frame(m p) for every place p of the page, between its four nearest pixels, and where m p lies inside the frame.
    m maps a place of the page (x, y, 1 in units) to the frame's."""
    h, w = frame.shape
    y, x, unit = _units(frame.shape)
    v, u = _through(m, y, x, unit, ((h - 1) / 2, (w - 1) / 2))
    inside = (v >= 0) & (v <= h - 1) & (u >= 0) & (u <= w - 1)
    y0, x0 = np.clip(np.floor(v), 0, h - 2), np.clip(np.floor(u), 0, w - 2)
    fy, fx = np.clip(v - y0, 0, 1), np.clip(u - x0, 0, 1)
    first = y0.astype(np.intp) * w + x0.astype(np.intp)
    flat = frame.reshape(-1)
    top = flat[first]
    top += (flat[first + 1] - top) * fx
    bottom = flat[first + w]
    bottom += (flat[first + w + 1] - bottom) * fx
    top += (bottom - top) * fy
    return top, inside


def _laid(page: np.ndarray, known: np.ndarray, frame: np.ndarray, m: np.ndarray) -> tuple[np.ndarray, float] | None:
    """The map made better on one size, by Gauss-Newton steps on page(p) = frame(m p) where the page is `known`, and
    how alike the two are under it (correlation). None when too little of the page is seen or the steps lead nowhere."""
    y, x, unit = _units(page.shape)
    alike = 0.0
    for _ in range(MAP_STEPS):
        back, inside = _brought_back(frame, m)
        use = inside & known
        use[[0, -1], :] = False
        use[:, [0, -1]] = False
        if int(use.sum()) < 64:
            return None
        counted = use.astype(np.float32)  # as a factor: taking the pixels out by a mask is slower than carrying zeros
        seen, shown = (page * counted).reshape(-1), (back * counted).reshape(-1)
        scale = math.sqrt(float(seen @ seen) * float(shown @ shown))
        alike = float(seen @ shown) / scale if scale > 0 else 0.0  # under the map this step starts from
        gy, gx = np.gradient(back)
        gy *= counted * np.float32(unit)
        gx *= counted * np.float32(unit)
        along = gx * x + gy * y
        design = np.stack((gx * x, gx * y, gx, gy * x, gy * y, gy, -along * x, -along * y)).reshape(8, -1)
        normal = (design @ design.T).astype(np.float64)
        try:
            delta = np.linalg.solve(normal + 1e-9 * np.trace(normal) / 8 * np.eye(8), (design @ (seen - shown)).astype(np.float64))
        except np.linalg.LinAlgError:
            return None
        if not np.isfinite(delta).all() or float(np.abs(delta).max()) > 0.5:
            return None
        m = m @ np.array([[1 + delta[0], delta[1], delta[2]], [delta[3], 1 + delta[4], delta[5]], [delta[6], delta[7], 1.0]])
        if abs(m[2, 0]) + abs(m[2, 1]) >= 0.9 * abs(m[2, 2]):
            return None  # so bent that a place of the page would lie at or behind the camera: no picture of a page
        if float(np.abs(delta).max()) * unit < MAP_STANDS:
            break
    return m, alike


def _places(shape: tuple[int, int], m: np.ndarray, size: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """Where on the page each pixel of a frame of `shape` lies (row, column, in frame pixels), by the inverse of m.
    `size` is the part of the frame the map's units were taken on: the frame without the rows and columns that joining
    left out."""
    unit = max(size) / 2
    y = ((np.arange(shape[0]) - (size[0] - 1) / 2) / unit).astype(np.float32)[:, None]
    x = ((np.arange(shape[1]) - (size[1] - 1) / 2) / unit).astype(np.float32)[None, :]
    return _through(np.linalg.inv(m), y, x, unit, ((size[0] - 1) / 2, (size[1] - 1) / 2))


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

    def lay(self, half: int, frame: np.ndarray, row: np.ndarray, column: np.ndarray) -> None:
        """Add a frame whose pixels lie on the page at (row, column) frame pixels, each into the grid cell nearest to it.
        No sharing between cells: the cell is a quarter of a frame pixel at most from where the pixel lies, and a
        frame that is turned or seen from another side cannot be added as blocks of memory. The cells are noisier
        for it: about 1.5 times, which the level over noise of a page laid this way shows.

        Two pixels of one frame lie a frame pixel apart, `grid` cells: they never fall into one cell, so each cell
        is added to once. (Were a frame seen at under half its size they would, and the later pixel alone would
        count; no such frame is laid.)"""
        grid = self.grid
        h, w = self.sums.shape[-2:]
        cell_y = np.rint(grid * row + (grid - 1) / 2).astype(np.int32)
        cell_x = np.rint(grid * column + (grid - 1) / 2).astype(np.int32)
        on = (cell_y >= 0) & (cell_y < grid * h) & (cell_x >= 0) & (cell_x < grid * w)
        cell_y, cell_x = cell_y[on], cell_x[on]
        # the plane a cell lies in, then its place there: (cell % grid) planes of h * w or w places, cell // grid rows or columns
        if grid & (grid - 1) == 0:  # a power of two, as the grid is: bits, where dividing whole numbers is slow
            bits = grid.bit_length() - 1
            flat = (cell_y & (grid - 1)) * (grid * h * w) + (cell_y >> bits) * w
            flat += (cell_x & (grid - 1)) * (h * w) + (cell_x >> bits)
        else:
            flat = ((cell_y % grid) * grid + cell_x % grid) * (h * w) + (cell_y // grid) * w + cell_x // grid
        flat = flat.astype(np.intp)  # worked out in 32 bits, which is quicker; added through the index's own size, which is too
        self.sums[half].reshape(-1)[flat] += frame[on]
        self.weights[half].reshape(-1)[flat] += 1

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

    A frame that lies further than FAR from the first is laid on the page by a map of its own (a homography, found
    from the pictures coarse to fine), and so is every frame after it: a head that moved has also tilted and sees
    the page from another side, and one shift fits such a frame in its middle only. Frames of glasses that lie still
    never get a map; they are added as they were measured.

    Where a frame is looked for is where the last added frame was, moved by what the picture has travelled since: every
    frame, added or not, is placed against the frame before it on the joined copies. On a worn head the picture moved
    46 to 301 px between two runs of still frames (M-31); looked for around the last added frame alone, every run
    after the first was lost.
    """
    selection = "none" if smear is None else "motion"
    # Still frames from each frame on, itself counted: what a page begun at that frame could still be given.
    ahead = None if smear is None else list(itertools.accumulate(reversed([value <= smear_limit for value in smear])))[::-1]
    total = usable = used = 0
    planes = reference = coarse = covered = shape = before = None
    join = 1
    position = (0.0, 0.0)
    travelled = [0.0, 0.0]  # frame pixels the picture has moved since the last frame that was added
    pose = None  # the map of the last frame that was laid on the page by one; None while one shift has done
    held: dict[object, tuple] = {}  # what is made from the sum and reused while it changes little: (frames then, ...)

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

    def page_sizes() -> list[tuple[int, np.ndarray, np.ndarray]]:
        """The page so far on the sizes a map is found on, in the band, and where enough frames have shown it."""
        kept = held.get("map")
        if kept is None or used < FRESH_UNTIL or used - kept[0] >= REFRESH:
            mean = reference / np.maximum(covered, 1)
            shown = (covered.astype(np.float32) * 4 >= used).astype(np.float32)
            if join > 1:
                mean, shown = _joined(mean, join), _joined(shown, join)
            level = float(mean[shown > 0.5].mean()) if (shown > 0.5).any() else 0.0
            sizes = []
            for k in MAP_SIZES:
                if min(mean.shape) // k < MAP_LEAST:
                    continue
                known = (_joined(shown, k) if k > 1 else shown) > 0.5
                sizes.append((k, _banded(_joined(mean, k) if k > 1 else mean, level, known), known))
            kept = (used, sizes, None)
            held["map"] = kept
        return kept[1]

    def mapped(small: np.ndarray, start: np.ndarray, near: bool, floor: float = MAP_FLOOR) -> tuple[np.ndarray | None, str]:
        """The frame's map onto the page, from `start`, coarse to fine; from the two finest sizes alone when the start
        is the map of the frame just before. None when the frame cannot be laid on the page; and how it went."""
        m, alike = start, 0.0
        sizes = page_sizes()
        for k, page, known in sizes[-2:] if near else sizes:
            found = _laid(page, known, _banded(_joined(small, k) if k > 1 else small), m)
            if found is None:
                return None, f"no map at size {k}"
            m, alike = found
        m = m / m[2, 2]
        turn, lean = float(np.linalg.det(m[:2, :2])), float(np.abs(m[2, :2]).max())
        went = f"alike {alike:.3f} area {turn:.3f} lean {lean:.3f}"
        return (m if alike >= floor and MAP_AREA[0] < turn < MAP_AREA[1] and lean <= 0.2 else None), went

    def begun_again(index: int) -> bool:
        """This still frame does not go on the page. Is the page begun again from it? When the page holds a small
        share of the still frames that are still to come: the clip started on something else (the paper was moved,
        the head had not arrived), and what follows is the page."""
        nonlocal planes, reference, coarse, covered, used, pose, position
        if ahead is None or index >= len(ahead) or ahead[index] < AGAIN * max(used, 1):
            return False
        _LOG.debug("frame %d: the page is begun again here (%d frames on it, %d still frames to come)", index, used, ahead[index])
        planes = _Planes(shape, grid)
        reference = coarse = covered = pose = None
        used, position = 0, (0.0, 0.0)
        held.clear()
        return True

    for index, frame in enumerate(frames):
        frame = np.asarray(frame, dtype=np.float32)
        if shape is None:
            shape = frame.shape
            join = max(1, min(shape) // COARSE_SIDE)
            planes = _Planes(shape, grid)
        elif frame.shape != shape:
            raise ValueError(f"frame {index} is {frame.shape}, the first was {shape}")
        total += 1
        small = _joined(frame, join) if join > 1 else frame
        spectrum = _spectrum(small)
        if before is not None and travelled is not None:
            step_y, step_x, sure = _peak(spectrum * before[0], small.shape, (0.0, 0.0), max(2.0, TRACK_REACH / join), before[1])
            if sure >= STRENGTH_FLOOR:
                travelled[0] += step_y * join
                travelled[1] += step_x * join
            else:
                # Not the frame before moved: the view left the page, or the head turned further than is looked for.
                # Worn frames matched the frame before with 42 or more, frames of two different pages with 7.3 at most
                # (M-31). From here only the last added frame says where to look, until a frame is added again.
                _LOG.debug("frame %d: the frame before is not found in it (%.1f)", index, sure)
                travelled = None
        mine = np.conj(spectrum) * _tools(small.shape)[1]
        before = (mine, np.fft.irfft2(spectrum * mine, s=small.shape))
        if smear is not None and (index >= len(smear) or smear[index] > smear_limit):
            continue
        usable += 1
        field = laid = None
        if reference is None:
            dy = dx = 0.0
        else:
            cross = spectrum * side(None, lambda: coarse)
            moved = travelled or (0.0, 0.0)
            expected = ((position[0] + moved[0]) / join, (position[1] + moved[1]) / join)
            unit = max(small.shape) * join / 2
            for reach in REACHES:
                dy, dx, strength = _peak(cross, small.shape, expected, max(2.0, reach / join), held[None][2])
                if strength >= STRENGTH_FLOOR + (WIDE_EXTRA if reach > REACHES[0] else 0.0):
                    break
            else:
                # No single shift places it. Where the picture has been followed to, a map is tried from there: the
                # head may have come back turned, or further from the page.
                went = ""
                if parts > 1 and travelled is not None:
                    there = np.array([[1.0, 0.0, expected[1] * join / unit], [0.0, 1.0, expected[0] * join / unit], [0.0, 0.0, 1.0]])
                    if pose is not None:
                        there = np.array([[1.0, 0.0, travelled[1] / unit], [0.0, 1.0, travelled[0] / unit], [0.0, 0.0, 1.0]]) @ pose
                    laid, went = mapped(small, there, False, MAP_SURE)
                _LOG.debug("frame %d %s: %.1f at its best within %.0f px of %+.0f %+.0f%s %s", index,
                           "laid without a shift" if laid is not None else "not placed", strength, REACHES[-1], expected[0] * join,
                           expected[1] * join, "" if travelled is not None else " (track lost)", went)
                if laid is None:
                    if not begun_again(index):
                        continue  # not this scene: the view left the page, or something came between
                    dy = dx = 0.0  # this frame is where the page is put now
                else:
                    dy, dx = float(laid[1, 2]) * unit / join, float(laid[0, 2]) * unit / join  # where the page's middle lies in it
            dy, dx = dy * join, dx * join
            if laid is not None:
                pass
            elif parts > 1 and (pose is not None or math.hypot(dy, dx) > FAR):
                near = pose is not None and travelled is not None and math.hypot(*travelled) <= FAR
                if near:  # the frame before, moved by what the picture has travelled since
                    start = np.array([[1.0, 0.0, travelled[1] / unit], [0.0, 1.0, travelled[0] / unit], [0.0, 0.0, 1.0]]) @ pose
                else:  # frame(p) = page(p - d): the page's place p is the frame's p + d
                    start = np.array([[1.0, 0.0, dx / unit], [0.0, 1.0, dy / unit], [0.0, 0.0, 1.0]])
                laid, went = mapped(small, start, near)
                if laid is None and near:
                    laid, went = mapped(small, np.array([[1.0, 0.0, dx / unit], [0.0, 1.0, dy / unit], [0.0, 0.0, 1.0]]), False)
                _LOG.debug("frame %d at %+.0f %+.0f %s: %s", index, dy, dx, "laid" if laid is not None else "left out", went)
                if laid is None:
                    if not begun_again(index):
                        continue  # it shows the page, but not so that it can be laid on it: left out rather than added double
                    dy = dx = 0.0
            elif parts > 1 and used >= PARTS_FROM:
                field = _field(frame, lambda box: side((box[0].start, box[1].start), lambda: reference[box]), dy, dx, parts,
                               PART_REACH + (join - 1) / 2)
                if field is not None:
                    dy, dx = (float(v) for v in field[0] + shape[0] / 2 * field[1] + shape[1] / 2 * field[2])
                    if float((np.abs(field[1]) * shape[0] + np.abs(field[2]) * shape[1]).max()) < FLAT:
                        field = None  # no tilt worth following: the whole frame goes in at the fitted centre shift
        position = (dy, dx)
        travelled = [0.0, 0.0]
        if laid is not None:
            pose = laid
            size = (small.shape[0] * join, small.shape[1] * join)
            row, column = _places(shape, laid, size)
            planes.lay(used % 2, frame, row, column)
            at_y, at_x = np.rint(row).astype(np.int32), np.rint(column).astype(np.int32)
            on = (at_y >= 0) & (at_y < shape[0]) & (at_x >= 0) & (at_x < shape[1])
            flat = (at_y * shape[1] + at_x)[on].astype(np.intp)
            # the frame as the page saw it, at whole pixels: where two of its pixels fall on one place the later
            # one stands, where none falls nothing is added
            light, times = np.zeros(shape, np.float32), np.zeros(shape, np.float32)
            light.reshape(-1)[flat] = frame[on]
            times.reshape(-1)[flat] = 1
            reference += light
            covered += times.astype(np.uint16)
            if join > 1:  # joined: the mean of the pixels that fell into each joined cell
                coarse += _joined(light, join) / np.maximum(_joined(times, join), 1.0 / (join * join))
            used += 1
            continue
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

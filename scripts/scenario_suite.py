#!/usr/bin/env python3
"""Situations for the whole route: photo-like images of exam paper, sent as the glasses send, judged by rule.

    py -3.12 scripts/scenario_suite.py build --out data/scenarios [--only NAME,...] [--set NAME.PARAM=VALUE ...]
    py -3.12 scripts/scenario_suite.py run --server http://127.0.0.1:18000 --scenarios data/scenarios \
        --report data/scenarios/_reports/RUN [--only NAME,...] [--force]
    py -3.12 scripts/scenario_suite.py check data/scenarios/_reports/RUN
    py -3.12 scripts/scenario_suite.py --self-check

`build` makes, for every scenario in SCENARIOS, a folder of images and a scenario.json (what it imitates, its
parameters, the expectation in a form `evaluate` reads, the files in order with each page's corners). `run` sends
each folder through scripts/run_exam_deck.py's own server route (its `run`, so: /v1/documents, the pages with
image_rotation 270, finalize, an exam session, finalize-reading?solve=background, answer-bundle), then judges the
bundle. The server's key is read from ROKID_API_KEY by run_exam_deck and never printed. `check` judges saved
bundles again without a server.

`run` spends the operator's usage: one booklet answered by the server's solver per scenario. It stops the whole
suite as soon as the server stops a batch (a usage limit, an uncertain send), and never sends a scenario whose
result is already in the report folder unless --force.

A scene is built upright, 3024x4032, and stored the way `run_exam_deck.py --images` expects a glassdoc original:
landscape 4032x3024, upright again after the server's turn for image_rotation 270.

What this is not: a photo. Paper is flat, the light even, the blur and the noise are a Gaussian each, nothing
moves; a page that the recorded route would deliver travels here as a still, so the server neither knows it is
greyscale nor leaves it unenlarged. A pass here says the route handles these images.

The exam pages are copyrighted: `build` writes only under an ignored data/ folder, and nothing here prints page text.
Needs Pillow and numpy; pypdfium2 to read a PDF (as run_exam_deck does), httpx for `run`.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
import unicodedata
import zlib
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts import run_exam_deck as deck  # noqa: E402

FRAME_W, FRAME_H = 3024, 4032  # the still, upright
MARGIN = 240  # desk kept around the frame, so that the slanted view pulls in desk and not nothing
LUMA = np.array([0.299, 0.587, 0.114], np.float32)

MATERIALS = "C:/rokid-exam-materials/kyotsu"
KEYED = f"{MATERIALS}/butsuri_kiso.pdf"  # 14 pages; the same pages as the rendered page001..014.jpg
KEY_FILE = f"{MATERIALS}/seikai/butsuri_kiso-key.json"
# Read off the keyed booklet's pages on 2026-11-16. The number printed at the foot of each of the 14 pages (13 and
# 17 are blank pages the PDF leaves out), and the pages each 解答番号 cannot be answered without.
KEYED_PRINTED = [4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15, 16, 18, 19]
KEYED_NEEDS = {101: [1], 102: [2], 103: [3], 104: [4], 105: [5, 6], 106: [5, 7], 107: [5, 7, 8], 108: [9],
               109: [10], 110: [11], 111: [11], 112: [12], 113: [13, 14], 114: [13, 14]}
# Where the character pitch is measured: a page of the keyed booklet and the part of it (fractions: left, top,
# right, bottom) that holds nothing but lines of body text.
PITCH_PAGE, PITCH_BOX = 5, (0.15, 0.20, 0.87, 0.53)

# A still in good light. width_frac: the spread's share of the frame's width. keystone: how much wider the view is
# at the far (top) edge, per side, as a share of the width. yaw: the paper's turn, +-degrees. blur: Gaussian
# radius, px. noise: Gaussian sigma per channel, in 8-bit levels. grain: the noise's cell, px (2 for a recorded
# page, whose grid is twice as fine as the camera's). first_on: the side the earlier page of a spread lies on.
STILL = {"source": KEYED, "keyed": True, "pages": 14, "first_on": "left", "width_frac": 0.60, "centre": [0.5, 0.60], "jitter": 0.03,
         "keystone": 0.04, "yaw": 1.5, "blur": 1.2, "noise": 4.0, "grain": 1, "grey": False, "jpeg_quality": 95,
         "paper": [236, 233, 224], "ink": [34, 34, 38], "seed": 0}
# A page as the recorded route delivers it: one page (page_frac of the frame's width, its neighbour showing at
# the side), greyscale. level_over_noise: (paper tone - ink tone) / noise sigma; it sets the noise.
CLIP = {**STILL, "page_frac": 0.75, "centre": [0.5, 0.5], "blur": 1.6, "grain": 2, "grey": True,
        "paper": [200, 200, 200], "ink": [36, 36, 36], "level_over_noise": 40}
# part_frac: the share of the sheet's width one photo shows; edge: how far a photo reaches past the sheet's edge.
SHEET = {**STILL, "sheet": [[1, 2], [3, 4]], "part_frac": 0.62, "edge": 0.02, "part_blur": 2.0, "withhold": None}

SCENARIOS = {
    "spread_baseline": dict(STILL, plan="spreads", mode="strict",
                            imitates="seven spreads in page order, each across 60% of the frame, on a desk"),
    "spread_far": dict(STILL, plan="spreads", mode="tolerant", width_frac=0.45,
                       imitates="the same spreads from further away: each across 45% of the frame"),
    "single_pages_clip": dict(CLIP, plan="clip", mode="strict",
                              imitates="fourteen single pages as the recorded route delivers them: greyscale, "
                                       "on the fine grid, slightly noisy"),
    "large_sheet_parts": dict(SHEET, plan="large_sheet", mode="strict",
                              imitates="pages 1-4 as one large sheet (2x2) taken as four overlapping parts, then "
                                       "pages 5-14 as spreads"),
    "large_sheet_missing_part": dict(SHEET, plan="large_sheet", mode="strict", withhold="br", min_needs_input=1,
                                     imitates="the large sheet with its lower right part never taken: text is "
                                              "cut at an image edge"),
    "shuffled_and_repeated": dict(STILL, plan="spreads", mode="strict", order=[4, 1, 6, 2, 7, 4, 3, 5],
                                  imitates="the spreads out of order, one of them photographed twice"),
    "page_skipped": dict(STILL, plan="spreads", mode="strict", order=[1, 3, 4, 5, 6, 7], min_needs_input=1,
                         name_gap=True, imitates="one spread never photographed; the page numbers show the gap"),
    "answer_sheet_beside": dict(STILL, plan="spreads", mode="strict", beside=True, centre=[0.335, 0.60],
                                jitter=0.015, imitates="each photo also shows a blank answer sheet of our own "
                                                       "making and a pencil case"),
    "sideways": dict(STILL, plan="spreads", mode="tolerant", angle=90, tilted_shot=4, tilt=15, centre=[0.5, 0.55],
                     imitates="the wearer looked from the side: spreads turned 90 degrees, one tilted 15 degrees"),
    "hand_over_page": dict(STILL, plan="spreads", mode="strict", cover={"page": 2, "box": [0.17, 0.29, 0.72, 0.51]},
                           imitates="a hand lies over one question's choices"),
    # Looked at on 2026-11-16: at 8 the 42 px print is grainy and still read by eye; at 4 with effort; at 2 not.
    "dark_noisy_16": dict(CLIP, plan="clip", mode="tolerant", paper=[150, 150, 150], ink=[40, 40, 40],
                          level_over_noise=16, imitates="recorded pages in poor light: level over noise 16"),
    "dark_noisy_8": dict(CLIP, plan="clip", mode="unreadable", paper=[150, 150, 150], ink=[40, 40, 40],
                         level_over_noise=8, imitates="recorded pages in poor light: level over noise 8"),
    "long_booklet_40": dict(STILL, plan="spreads", mode="complete", keyed=False, source=f"{MATERIALS}/sugaku2BC.pdf", pages=40,
                            imitates="a long booklet: forty pages as twenty spreads"),
    "english_horizontal": dict(STILL, plan="spreads", mode="complete", keyed=False,
                               source=f"{MATERIALS}/eigo_reading.pdf", pages=8, imitates="English: eight pages as four spreads"),
}


# ---- geometry ----------------------------------------------------------------------------------------------------

def homography(dst, src) -> np.ndarray:
    """The 8 coefficients of PIL's PERSPECTIVE transform that send each output point dst[i] to the input point src[i]."""
    rows, rhs = [], []
    for (x, y), (u, v) in zip(dst, src):
        rows += [[x, y, 1, 0, 0, 0, -u * x, -u * y], [0, 0, 0, x, y, 1, -v * x, -v * y]]
        rhs += [u, v]
    return np.linalg.solve(np.array(rows, float), np.array(rhs, float))


def through(coeffs, points, inverse: bool = False) -> np.ndarray:
    """Points sent through those coefficients (output to input), or back (input to output)."""
    matrix = np.append(coeffs, 1.0).reshape(3, 3)
    if inverse:
        matrix = np.linalg.inv(matrix)
    sent = np.c_[np.asarray(points, float), np.ones(len(points))] @ matrix.T
    return sent[:, :2] / sent[:, 2:]


def as_stored(upright: Image.Image) -> Image.Image:
    """The upright scene as glassdoc's file: landscape. The server's turn for image_rotation 270 is ROTATE_90
    (app/main.py _rotate_image_for_ocr), which undoes this."""
    return upright.transpose(Image.Transpose.ROTATE_270)


def lay(canvas: Image.Image, img: Image.Image, at, angle: float, anchor=(0.5, 0.5), mask: Image.Image | None = None):
    """Lay img on the canvas, turned by `angle` degrees counter-clockwise, its point `anchor` (fractions of img) at
    the canvas point `at`, with a shadow. Returns the function from a point of img, in fractions, to canvas px."""
    mask = mask or Image.new("L", img.size, 255)
    turned = img.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    turned_mask = mask.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    cos, sin = math.cos(math.radians(angle)), math.sin(math.radians(angle))

    def from_centre(u, v):
        dx, dy = (u - 0.5) * img.width, (v - 0.5) * img.height
        return dx * cos + dy * sin, -dx * sin + dy * cos

    ax, ay = from_centre(*anchor)
    corner = (round(at[0] - ax - turned.width / 2), round(at[1] - ay - turned.height / 2))
    cx, cy = corner[0] + turned.width / 2, corner[1] + turned.height / 2
    canvas.paste((70, 52, 36), (corner[0] + 9, corner[1] + 12), turned_mask.point(lambda a: a * 0.45))
    canvas.paste(turned, corner, turned_mask)
    return lambda u, v: (cx + from_centre(u, v)[0], cy + from_centre(u, v)[1])


def part_windows(part_frac: float, edge: float, sheet_aspect: float) -> dict[str, tuple[float, float, float, float]]:
    """The four photos of a large sheet, each as the window (u0, v0, u1, v1) it shows, in fractions of the sheet.

    A window is the frame: `part_frac` of the sheet's width, and the frame's own shape. Two across and two down,
    each reaching `edge` past the sheet's own edges, so neighbours overlap by what is left over.
    """
    wide, high = part_frac, part_frac * (FRAME_H / FRAME_W) / sheet_aspect
    return {name: (u, v, u + wide, v + high)
            for name, u, v in (("tl", -edge, -edge), ("tr", 1 + edge - wide, -edge),
                               ("bl", -edge, 1 + edge - high), ("br", 1 + edge - wide, 1 + edge - high))}


def hidden_pages(grid, windows, need: float = 0.97) -> list[int]:
    """The pages of a sheet (rows of page numbers) of which the windows together show less than `need`."""
    rows, cols = len(grid), len(grid[0])
    steps = (np.arange(40) + 0.5) / 40
    hidden = []
    for r, row in enumerate(grid):
        for c, number in enumerate(row):
            u, v = np.meshgrid((c + steps) / cols, (r + steps) / rows)
            seen = np.zeros(u.shape, bool)
            for u0, v0, u1, v1 in windows:
                seen |= (u >= u0) & (u <= u1) & (v >= v0) & (v <= v1)
            if seen.mean() < need:
                hidden.append(number)
    return hidden


def rectify(frame: Image.Image, quad) -> Image.Image:
    """The paper inside `quad` (its corners in the frame: top left, top right, bottom right, bottom left) as an
    upright rectangle at the frame's own scale."""
    q = np.asarray(quad, float)
    width = round((np.linalg.norm(q[1] - q[0]) + np.linalg.norm(q[2] - q[3])) / 2)
    height = round((np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])) / 2)
    return frame.transform((width, height), Image.Transform.QUAD, (*q[0], *q[3], *q[2], *q[1]),
                           Image.Resampling.BICUBIC)


def _auto(profile: np.ndarray) -> np.ndarray:
    """A profile's autocorrelation by lag, 1 at lag 0."""
    centred = profile - profile.mean()
    auto = np.correlate(centred, centred, "full")[len(centred) - 1:]
    return auto / auto[0] if auto[0] else auto


def _repeat(auto: np.ndarray, hi: int) -> float:
    """The distance, to a fraction of a px, at which a profile repeats: among its autocorrelation's peaks after the
    first dip and no later than `hi`, the first that is at least 0.6 as high as the highest (print repeats at two
    and three characters almost as well as at one). 0 when there is no peak."""
    dip = np.nonzero(np.diff(auto) > 0)[0]
    hi = min(hi, len(auto) - 2)
    if not len(dip) or dip[0] >= hi:
        return 0.0
    lags = np.arange(max(1, dip[0]), hi + 1)
    lags = lags[(auto[lags] >= auto[lags - 1]) & (auto[lags] >= auto[lags + 1])]
    if not len(lags):
        return 0.0
    k = int(lags[auto[lags] >= 0.6 * auto[lags].max()][0])
    a, b, c = auto[k - 1], auto[k], auto[k + 1]
    return k + (0.5 * (a - c) / (a - 2 * b + c) if a - 2 * b + c else 0.0)


def text_pitch(grey: np.ndarray) -> tuple[float, float]:
    """(line pitch, character pitch) in px, for an upright grey array of horizontal lines of full-width print.

    Line pitch: the distance at which the ink summed along each row repeats best. Character pitch: each line (a run
    of rows holding ink) gives the autocorrelation of its ink summed down each column; the lines' autocorrelations
    are added, and the pitch is the distance, within three line heights, at which that sum repeats.
    """
    ink = np.clip(np.median(grey) - grey.astype(np.float32), 0, None)
    rows = ink.sum(1)
    line = _repeat(_auto(rows), len(rows) // 2)
    inked = np.r_[False, rows > 0.3 * rows.max(), False]
    edges = np.nonzero(inked[1:] != inked[:-1])[0]
    lines = [(top, bottom) for top, bottom in zip(edges[::2], edges[1::2]) if bottom - top >= 5]
    if not lines:
        return float(line), 0.0
    together = sum(_auto(ink[top:bottom].sum(0)) for top, bottom in lines)
    return float(line), float(_repeat(together, round(3 * np.median([bottom - top for top, bottom in lines]))))


# ---- the scene ---------------------------------------------------------------------------------------------------

@lru_cache(maxsize=16)
def page(source: str, number: int, width: int) -> Image.Image:
    """Page `number` (1-based) of a PDF, or of a folder of page images in name order, `width` px wide, RGB."""
    path = Path(source)
    if path.is_dir():
        files = sorted(p for p in path.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
        with Image.open(files[number - 1]) as img:
            return img.convert("RGB").resize((width, round(width * img.height / img.width)), Image.Resampling.LANCZOS)
    import pypdfium2 as pdfium

    leaf = pdfium.PdfDocument(str(path))[number - 1]
    return leaf.render(scale=width / leaf.get_size()[0]).to_pil().convert("RGB")


def tone(img: Image.Image, paper, ink) -> Image.Image:
    """Print as paper under the desk's light: white becomes the paper's tone, black the ink's."""
    paper, ink = np.array(paper, np.float32), np.array(ink, np.float32)
    return Image.fromarray((ink + np.asarray(img, np.float32) / 255 * (paper - ink)).astype(np.uint8))


@lru_cache(maxsize=2)
def sheet_image(source: str, grid: tuple, page_w: int, paper: tuple, ink: tuple) -> Image.Image:
    """Pages edge to edge as one sheet (rows of 1-based page numbers), darker along each fold."""
    w, h = page(source, grid[0][0], page_w).size
    sheet = Image.new("RGB", (w * len(grid[0]), h * len(grid)), "white")
    for r, row in enumerate(grid):
        for c, number in enumerate(row):
            sheet.paste(page(source, number, page_w), (c * w, r * h))
    lit = np.asarray(tone(sheet, paper, ink), np.float32)
    for axis, count, size in ((1, len(grid[0]), w), (0, len(grid), h)):
        along = np.arange(lit.shape[axis], dtype=np.float32)
        fold = np.ones_like(along)
        for i in range(1, count):
            fold *= 1 - 0.25 * np.exp(-((along - i * size) / (0.02 * w)) ** 2)
        lit *= fold[None, :, None] if axis else fold[:, None, None]
    return Image.fromarray(lit.astype(np.uint8))


@lru_cache(maxsize=1)
def desk() -> Image.Image:
    """A desk top: brown, grained along its length, with slow changes of tone. Made here, not photographed."""
    w, h = FRAME_W + 2 * MARGIN, FRAME_H + 2 * MARGIN
    rng = np.random.default_rng(7)

    def field(rows, cols):
        small = Image.fromarray(rng.normal(0, 1, (rows, cols)).astype(np.float32))
        return np.asarray(small.resize((w, h), Image.Resampling.BICUBIC))

    shade = 1 + 0.05 * field(8, 6) + 0.035 * field(h // 3, 40) + 0.02 * field(80, 60)
    return Image.fromarray(np.clip(np.array([168, 132, 96], np.float32) * shade[..., None], 0, 255).astype(np.uint8))


@lru_cache(maxsize=1)
def falloff() -> np.ndarray:
    """The lens's light: full at the centre, 0.86 of it in the corners."""
    y, x = np.mgrid[-1:1:FRAME_H * 1j, -1:1:FRAME_W * 1j].astype(np.float32)
    return 1 - 0.07 * (x * x + y * y)


def answer_sheet(width: int) -> Image.Image:
    """A blank answer sheet of our own making: 101-125, each beside an empty box, in two columns. It holds more
    numbers than the keyed booklet has, as a mark sheet does, so an item made from it shows by its number."""
    height = round(width * 1.41)
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=round(width * 0.034))
    line = max(2, width // 350)
    draw.rectangle((width * 0.05, height * 0.04, width * 0.95, height * 0.96), outline="black", width=line)
    pitch = height * 0.86 / 13
    for i, number in enumerate(range(101, 126)):
        column, row = divmod(i, 13)
        x, y = width * (0.10 + 0.43 * column), height * 0.07 + row * pitch
        draw.text((x, y + pitch * 0.22), str(number), fill="black", font=font)
        draw.rectangle((x + width * 0.10, y + pitch * 0.12, x + width * 0.34, y + pitch * 0.82),
                       outline="black", width=line)
    return img


def hand(canvas: Image.Image, where, box) -> None:
    """A hand over `box` (corners, in the fractions `where` takes): a skin-coloured palm covering all of it, fingers
    beyond it, the forearm leaving by the frame's lower right."""
    (x0, y0), (x1, y1) = where(box[0], box[1]), where(box[2], box[3])
    cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, abs(x1 - x0) * 0.72, abs(y1 - y0) * 0.72
    draw, skin = ImageDraw.Draw(canvas), (214, 164, 130)
    draw.line([(cx + rx * 0.3, cy + ry * 0.3), (canvas.width, canvas.height * 0.93)], fill=skin, width=round(ry * 1.3))
    draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=skin)
    for i in range(4):
        fx, fy = cx - rx * (0.85 - 0.42 * i), cy - ry * (0.8 + 0.12 * (i % 2))
        draw.ellipse((fx - rx * 0.19, fy - ry * 0.5, fx + rx * 0.19, fy + ry * 0.5), fill=skin)


def photograph(canvas: Image.Image, spec: dict, rng) -> tuple[Image.Image, np.ndarray, np.ndarray]:
    """The canvas as the camera's frame: seen at a slant (the far edge smaller), soft, darker to the corners, noisy.

    Returns the frame, the same frame before noise, and the perspective coefficients (frame px to canvas px).
    Noise: Gaussian, sigma `noise`, or (paper tone - ink tone) / `level_over_noise` where that is given; one draw
    per `grain` x `grain` px, per channel.
    """
    k, j = spec["keystone"] * FRAME_W, 0.004 * FRAME_W
    seen = [(MARGIN - k, MARGIN), (MARGIN + FRAME_W + k, MARGIN),
            (MARGIN + FRAME_W, MARGIN + FRAME_H), (MARGIN, MARGIN + FRAME_H)]
    seen = [(x + rng.uniform(-j, j), y + rng.uniform(-j, j)) for x, y in seen]
    coeffs = homography([(0, 0), (FRAME_W, 0), (FRAME_W, FRAME_H), (0, FRAME_H)], seen)
    frame = canvas.transform((FRAME_W, FRAME_H), Image.Transform.PERSPECTIVE, tuple(coeffs), Image.Resampling.BICUBIC)
    clean = np.asarray(frame.filter(ImageFilter.GaussianBlur(spec["blur"])), np.float32) * falloff()[..., None]
    if spec["grey"]:
        clean = clean @ LUMA
    sigma = spec["noise"]
    if spec.get("level_over_noise"):
        sigma = float((np.array(spec["paper"], np.float32) - np.array(spec["ink"], np.float32)) @ LUMA
                      ) / spec["level_over_noise"]
    g = spec["grain"]
    noise = rng.normal(0, sigma, (-(-FRAME_H // g), -(-FRAME_W // g), *clean.shape[2:])).astype(np.float32)
    noise = noise.repeat(g, 0).repeat(g, 1)[:FRAME_H, :FRAME_W]
    return Image.fromarray(np.clip(clean + noise, 0, 255).astype(np.uint8)), clean, coeffs


def render(shot: dict, spec: dict, rng) -> tuple[Image.Image, np.ndarray, dict[int, list]]:
    """One photo, upright: the frame, the frame before noise, and the corners of each of its pages in the frame
    (top left, top right, bottom right, bottom left; a page partly outside the frame has corners outside it)."""
    spec = {**spec, **shot.get("camera", {})}
    canvas = desk().copy()

    def point(fx, fy):
        return MARGIN + fx * FRAME_W, MARGIN + fy * FRAME_H

    if spec.get("beside"):
        case = Image.new("RGB", (round(0.33 * FRAME_W), round(0.085 * FRAME_W)), (40, 44, 60))
        ImageDraw.Draw(case).line([(30, case.height // 2), (case.width - 30, case.height // 2)], fill=(90, 94, 108), width=6)
        shape = Image.new("L", case.size, 0)
        ImageDraw.Draw(shape).rounded_rectangle((0, 0, case.width - 1, case.height - 1), case.height // 3, fill=255)
        lay(canvas, case, point(0.42, 0.30), 6 + rng.uniform(-3, 3), mask=shape)
        lay(canvas, tone(answer_sheet(shot["page_w"]), spec["paper"], spec["ink"]),
            point(0.82, spec["centre"][1] + rng.uniform(-0.02, 0.02)), rng.uniform(-4, 4))
    grid = tuple(map(tuple, shot["grid"]))
    rows, cols = len(grid), len(grid[0])
    sheet = sheet_image(spec["source"], grid, shot["page_w"], tuple(spec["paper"]), tuple(spec["ink"]))
    where = lay(canvas, sheet, point(*shot["at"]), shot["angle"], shot["anchor"])
    if shot.get("cover"):
        r, c = next((r, row.index(shot["cover"]["page"])) for r, row in enumerate(grid) if shot["cover"]["page"] in row)
        hand(canvas, lambda u, v: where((c + u) / cols, (r + v) / rows), shot["cover"]["box"])
    frame, clean, coeffs = photograph(canvas, spec, rng)
    quads = {}
    for r, row in enumerate(grid):
        for c, number in enumerate(row):
            corners = [where((c + du) / cols, (r + dv) / rows) for du, dv in ((0, 0), (1, 0), (1, 1), (0, 1))]
            quads[number] = through(coeffs, corners, inverse=True).round(1).tolist()
    return frame, clean, quads


# ---- the scenarios' photos and expectations ------------------------------------------------------------------------

def pairs(first: int, last: int, first_on: str) -> list[list[int]]:
    """Pages first..last two to a spread, consecutive as run_exam_deck.pair_spreads pairs them (not by the
    booklet's own leaves: a blank page the source leaves out shifts every later pair). `first_on`: the side the
    earlier page lies on, left for a booklet of horizontal text, right for one of vertical text."""
    out = [list(range(i, min(i + 2, last + 1))) for i in range(first, last + 1, 2)]
    return out if first_on == "left" else [pair[::-1] for pair in out]


def spread_shot(spec: dict, rng, pair: list[int], angle: float = 0.0) -> dict:
    j = spec["jitter"]
    return {"grid": [pair], "page_w": round(spec["width_frac"] * FRAME_W / 2), "anchor": [0.5, 0.5],
            "at": [spec["centre"][0] + rng.uniform(-j, j), spec["centre"][1] + rng.uniform(-j, j)],
            "angle": angle + rng.uniform(-spec["yaw"], spec["yaw"])}


def plan_spreads(spec: dict, rng) -> tuple[list[dict], set[int]]:
    """Spreads in `order` (1-based; default all, once). Returns the shots and the pages no shot shows whole."""
    spreads = pairs(1, spec["pages"], spec["first_on"])
    order = spec.get("order") or list(range(1, len(spreads) + 1))
    cover = spec.get("cover")
    shots = []
    for i, number in enumerate(order, 1):
        shot = spread_shot(spec, rng, spreads[number - 1], spec["tilt"] if i == spec.get("tilted_shot") else spec.get("angle", 0))
        if cover and cover["page"] in spreads[number - 1]:
            shot["cover"] = cover
        shots.append(shot)
    left_out = {n for i, pair in enumerate(spreads, 1) if i not in order for n in pair}
    return shots, left_out | ({cover["page"]} if cover else set())


def plan_clip(spec: dict, rng) -> tuple[list[dict], set[int]]:
    """Every page by itself, in page order: its spread laid down, the frame centred on the one page."""
    shots = []
    for pair in pairs(1, spec["pages"], spec["first_on"]):
        for number in sorted(pair):
            shots.append({"grid": [pair], "page_w": round(spec["page_frac"] * FRAME_W),
                          "anchor": [(pair.index(number) + 0.5) / len(pair), 0.5],
                          "at": [0.5 + rng.uniform(-0.02, 0.02), 0.5 + rng.uniform(-0.02, 0.02)],
                          "angle": rng.uniform(-spec["yaw"], spec["yaw"])})
    return shots, set()


def plan_large_sheet(spec: dict, rng) -> tuple[list[dict], set[int]]:
    """The pages of `sheet` as one sheet taken in overlapping parts (all but `withhold`), then the rest as spreads."""
    grid = spec["sheet"]
    page_w = round(FRAME_W / spec["part_frac"] / len(grid[0]))
    w, h = page(spec["source"], grid[0][0], page_w).size
    windows = part_windows(spec["part_frac"], spec["edge"], (h * len(grid)) / (w * len(grid[0])))
    kept = [window for name, window in windows.items() if name != spec["withhold"]]
    shots = [{"grid": grid, "page_w": page_w, "anchor": [(u0 + u1) / 2, (v0 + v1) / 2], "at": [0.5, 0.5],
              "angle": rng.uniform(-spec["yaw"], spec["yaw"]), "camera": {"blur": spec["part_blur"]}}
             for u0, v0, u1, v1 in kept]
    after = max(n for row in grid for n in row) + 1
    shots += [spread_shot(spec, rng, pair) for pair in pairs(after, spec["pages"], spec["first_on"])]
    return shots, set(hidden_pages(grid, kept))


PLANS = {"spreads": plan_spreads, "clip": plan_clip, "large_sheet": plan_large_sheet}


def expectation(spec: dict, left_out: set[int]) -> dict:
    """What `evaluate` holds a bundle to. Only the keyed booklet has answers to compare; anything else has to
    come back whole (mode complete)."""
    if not spec["keyed"]:
        return {"mode": "complete"}
    key = deck.load_answer_key(KEY_FILE)
    withheld = sorted(n for n, needs in KEYED_NEEDS.items() if left_out & set(needs))
    expect = {"mode": spec["mode"], "key": {str(n): a for n, a in key.items()},
              "answerable": sorted(set(key) - set(withheld)), "withheld": withheld,
              "known_gap_pages": sorted(set(range(KEYED_PRINTED[0], KEYED_PRINTED[-1])) - set(KEYED_PRINTED)),
              "min_needs_input": spec.get("min_needs_input", 0)}
    if spec.get("name_gap"):
        expect["gap_pages"] = [KEYED_PRINTED[n - 1] for n in sorted(left_out)]
    return expect


def build_scenario(name: str, spec: dict, out: Path) -> dict:
    rng = np.random.default_rng([zlib.crc32(name.encode()), spec["seed"]])
    shots, left_out = PLANS[spec["plan"]](spec, rng)
    folder = out / name
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("[0-9][0-9].jpg"):  # run_exam_deck sends every image in the folder
        old.unlink()
    files, measured = [], {}
    for i, shot in enumerate(shots, 1):
        frame, clean, quads = render(shot, spec, rng)
        path = folder / f"{i:02d}.jpg"
        as_stored(frame).save(path, "JPEG", quality=spec["jpeg_quality"])
        files.append({"file": path.name, "quads": {str(n): quad for n, quad in quads.items()}})
        if i == 1:
            (out / "_preview").mkdir(exist_ok=True)
            frame.resize((FRAME_W // 4, FRAME_H // 4), Image.Resampling.LANCZOS).save(out / "_preview" / f"{name}.jpg", quality=85)
        with Image.open(path) as stored:  # measured on the file, turned as the server turns it
            sent = stored.transpose(Image.Transpose.ROTATE_90).convert("L")
        if i == 1 and spec.get("level_over_noise"):  # in the middle half of the frame, where the page lies
            middle = (slice(FRAME_H // 4, 3 * FRAME_H // 4), slice(FRAME_W // 4, 3 * FRAME_W // 4))
            flat, noisy = clean[middle], np.asarray(sent, np.float32)[middle]
            paper, ink = float(np.median(flat)), float(flat.min())  # the darkest ink, as the blur leaves it
            measured |= {"paper_level": round(paper, 1), "ink_level": round(ink, 1),
                         "noise_sigma": round(float((noisy - flat).std()), 2),
                         "level_over_noise": round((paper - ink) / float((noisy - flat).std()), 1),
                         "paper_over_noise": round(paper / float((noisy - flat).std()), 1)}
        quad = quads.get(PITCH_PAGE) if spec["keyed"] else None
        if quad and "char_pitch_px" not in measured and np.all((np.array(quad) >= 0) & (np.array(quad) <= (FRAME_W, FRAME_H))):
            leaf = rectify(sent, quad)
            line, char = text_pitch(np.asarray(leaf.crop([round(f * s) for f, s in zip(PITCH_BOX, leaf.size * 2)])))
            measured |= {"pitch_file": path.name, "line_pitch_px": round(line, 1), "char_pitch_px": round(char, 1)}
    scenario = {"name": name, "imitates": spec["imitates"], "rotation": deck.GLASSDOC_ROTATION,
                "params": {k: v for k, v in spec.items() if k != "imitates"}, "expect": expectation(spec, left_out),
                "measured": measured, "files": files}
    (folder / "scenario.json").write_text(json.dumps(scenario, ensure_ascii=False, indent=1), encoding="utf-8")
    return scenario


# ---- judging a bundle ---------------------------------------------------------------------------------------------

_WORST_FIRST = ("wrong", "failed", "flagged_wrong", "needs_input", "flagged_match", "match")


def _names(item: dict, pages: list[int]) -> bool:
    """Whether an item's words name a run of printed pages: one of them, or the page before it and the page after."""
    words = unicodedata.normalize("NFKC", " ".join(str(item.get(k) or "") for k in ("issue", "question_label", "group_label")))
    seen = {int(digits) for digits in re.findall(r"\d+", words)}
    return bool(pages) and (bool(seen & set(pages)) or {min(pages) - 1, max(pages) + 1} <= seen)


def evaluate(expect: dict, items: list[dict], stopped: str | None = None) -> dict:
    """Hold an answer bundle's items to a scenario's expectation.

    Each keyed 解答番号 gets one state: match (ready and equal to the key), wrong (ready and not: the failure
    measure, "wrong and unflagged"), flagged_match / flagged_wrong (needs_review: shown, and marked to be checked),
    needs_input, failed, or absent (in no item). A number in two items takes the worse state and counts as twice.

    FAIL: the run stopped; an item failed or is pending; any wrong; a number twice; an item with a number the key
    does not hold, or an answer with no number (made from something that is not the booklet); a number that should
    have been answered and was not, where the mode is strict; a number gone with no needs_input item anywhere;
    fewer needs_input items than `min_needs_input` (known gaps of the source not counted).
    LOOK: in mode tolerant, a number that came back flagged or needs_input instead of answered; in mode unreadable,
    a number that was answered; a withheld number that came back ready and right; no needs_input item naming
    `gap_pages`; a needs_input item about nothing the photos leave out.
    PASS: none of these. Mode complete (no key): every item ready, needs_review or needs_input.

    What a needs_input item with no keyed number is about is told from the numbers in its words alone: a known gap
    of the source (`known_gap_pages`), the scenario's own gap, or neither. One item worded about two of these, or
    naming no page, can be filed wrongly; `known_gap_notices` and `other_notices` keep the words to read.
    """
    mode = expect["mode"]
    key = {int(n): a for n, a in (expect.get("key") or {}).items()}
    answerable, withheld = expect.get("answerable", sorted(key)), expect.get("withheld", [])
    statuses = [item.get("status") for item in items]
    fails, looks, notes = [], [], []
    if stopped:
        fails.append(f"the run stopped: {stopped}")
    if not items:
        fails.append("no item came back")
    undone = sum(1 for status in statuses if status not in ("ready", "needs_review", "needs_input"))
    if undone:
        fails.append(f"{undone} item(s) failed or pending")

    states: dict[int, list[str]] = {}
    strangers, reports = 0, []
    for item in items:
        status = item.get("status")
        numbers = [n for n in item.get("answer_no", []) if isinstance(n, int)]
        answered = status in ("ready", "needs_review")
        given = deck.answers_by_number(item) if answered else {}
        if key and (set(numbers) - set(key) or (answered and not numbers)):
            strangers += 1
        if status == "needs_input" and not set(numbers) & set(key):
            reports.append(item)
        for n in set(numbers) & set(key):
            if answered:
                right = deck.normalize_answer(given.get(n, "")) == deck.normalize_answer(key[n])
                state = ("" if status == "ready" else "flagged_") + ("match" if right else "wrong")
            else:
                state = status if status == "needs_input" else "failed"
            states.setdefault(n, []).append(state)
    worst = {n: min(found, key=_WORST_FIRST.index) for n, found in states.items()}
    gap = expect.get("gap_pages") or []
    known = [r for r in reports
             if not _names(r, gap) and any(_names(r, [g]) for g in expect.get("known_gap_pages", []))]
    noticed = statuses.count("needs_input") - len(known)
    stray = [] if withheld or mode in ("unreadable", "complete") else [r for r in reports if r not in known]

    wrong = sorted(n for n, state in worst.items() if state == "wrong")
    if wrong:
        fails.append("wrong and unflagged: " + ", ".join(str(n) for n in wrong))
    twice = sorted(n for n, found in states.items() if len(found) > 1)
    if twice:
        fails.append("answer number twice: " + ", ".join(str(n) for n in twice))
    if strangers:
        fails.append(f"{strangers} item(s) not of the booklet's answer numbers")
    matched = [n for n in answerable if worst.get(n) in ("match", "flagged_match")]
    for n in answerable:
        state = worst.get(n, "absent")
        if state in ("match", "flagged_match", "wrong"):
            continue
        if mode == "strict" or state == "failed" or (state == "absent" and noticed <= 0):
            fails.append(f"{n} {state}")
        elif mode == "tolerant":
            looks.append(f"{n} {state}")
    if mode == "unreadable" and matched:
        looks.append(f"{len(matched)} answered where unreadable was expected")
    for n in withheld:
        state = worst.get(n, "absent")
        if state == "match":
            looks.append(f"withheld {n} came back ready and right: was it a guess?")
        elif state == "absent" and noticed <= 0:
            fails.append(f"withheld {n} gone with no needs_input item")
    if noticed < expect.get("min_needs_input", 0):
        fails.append("no needs_input item for what the photos leave out")
    elif gap and not any(_names(item, gap) for item in items if item.get("status") == "needs_input"):
        looks.append(f"no needs_input item names printed page {'-'.join(map(str, gap))}")
    if stray:
        looks.append(f"{len(stray)} needs_input item(s) about nothing the photos leave out")
    flagged = sum(1 for n in answerable if worst.get(n) == "flagged_match")
    if flagged:
        notes.append(f"{flagged} right answer(s) marked for review")
    return {
        "verdict": "FAIL" if fails else "LOOK" if looks else "PASS",
        "reason": "; ".join(fails or looks or notes) or "as expected",
        "items": len(items), "ready": statuses.count("ready"), "needs_review": statuses.count("needs_review"),
        "needs_input": statuses.count("needs_input"), "matches": len(matched), "of": len(answerable),
        "twice": twice, "wrong_unflagged": wrong,
        "unexpected_needs_input": 0 if mode == "unreadable" else len(stray) + sum(1 for n in answerable if worst.get(n) == "needs_input"),
        "fails": fails, "looks": looks, "notes": notes,
        "per_number": {str(n): worst.get(n, "absent") for n in sorted(key)},
        "known_gap_notices": [str(r.get("issue"))[:200] for r in known],
        "other_notices": [str(r.get("issue"))[:200] for r in reports if r not in known],
    }


def summarize(report: Path) -> int:
    """Judge every saved result in `report` again, print the table, write summary.txt. 1 if any FAIL."""
    heads = ["scenario", "photos", "items", "ready", "needs_input", "key", "twice", "unexpected needs_input",
             "wrong unflagged", "seconds", "verdict", "reason"]
    rows = []
    for path in report.glob("*.json"):
        saved = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(saved, dict) or "scenario" not in saved or "deck" not in saved:
            continue
        scenario, ran = saved["scenario"], saved["deck"]
        judged = evaluate(scenario["expect"], ran["bundle"]["items"], ran.get("stopped"))
        if judged != saved.get("evaluation"):
            saved["evaluation"] = judged
            path.write_text(json.dumps(saved, ensure_ascii=False, indent=1), encoding="utf-8")
        rows.append([scenario["name"], len(scenario["files"]), judged["items"], judged["ready"], judged["needs_input"],
                     f"{judged['matches']}/{judged['of']}" if judged["of"] else "-", len(judged["twice"]),
                     judged["unexpected_needs_input"], len(judged["wrong_unflagged"]), ran["elapsed_s"],
                     judged["verdict"], judged["reason"]])
    names = list(SCENARIOS)
    rows.sort(key=lambda row: names.index(row[0]) if row[0] in names else len(names))
    table = [heads, *([str(cell) for cell in row] for row in rows)]
    widths = [max(len(row[i]) for row in table) for i in range(len(heads) - 1)]
    print()
    for row in table:
        print("  ".join(cell.ljust(width) for cell, width in zip(row, widths)) + "  " + row[-1])
    lines = ["| " + " | ".join(row) + " |" for row in table]
    lines.insert(1, "|" + " --- |" * len(heads))
    (report / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n{report / 'summary.txt'}")
    return 1 if any(row[-2] == "FAIL" for row in rows) else 0


# ---- commands -----------------------------------------------------------------------------------------------------

def _chosen(only: str | None) -> list[str]:
    names = [name for name in (only or "").split(",") if name] or list(SCENARIOS)
    unknown = [name for name in names if name not in SCENARIOS]
    if unknown:
        raise SystemExit(f"no such scenario: {', '.join(unknown)} (there are: {', '.join(SCENARIOS)})")
    return names


def cmd_build(args) -> int:
    out = Path(args.out).resolve()
    if REPO in out.parents and REPO / "data" not in (out, *out.parents):
        raise SystemExit("the pages are copyrighted: inside this repository they go under data/ only (git ignores it)")
    for change in args.set:
        target, _, value = change.partition("=")
        name, _, param = target.partition(".")
        if name not in SCENARIOS or not param:
            raise SystemExit(f"--set takes NAME.PARAM=VALUE with a scenario's name, not {change!r}")
        try:
            SCENARIOS[name][param] = json.loads(value)
        except ValueError:
            SCENARIOS[name][param] = value
    for name in _chosen(args.only):
        started = time.monotonic()
        scenario = build_scenario(name, SCENARIOS[name], out)
        size = sum((out / name / f["file"]).stat().st_size for f in scenario["files"]) / 1e6
        print(f"{name:<26} {len(scenario['files']):>2} photos {size:6.1f} MB {time.monotonic() - started:5.0f} s  "
              f"{json.dumps(scenario['measured'])}", flush=True)
    return 0


def cmd_run(args) -> int:
    root, report = Path(args.scenarios), Path(args.report)
    scenarios = []
    for name in _chosen(args.only):
        path = root / name / "scenario.json"
        if path.exists():
            scenarios.append(json.loads(path.read_text(encoding="utf-8")))
        elif args.only:
            raise SystemExit(f"{path} is not there: build it first")
    report.mkdir(parents=True, exist_ok=True)
    print(f"{len(scenarios)} scenario(s), {sum(len(s['files']) for s in scenarios)} photos; "
          "each scenario is one booklet answered by the server's own solver")
    cut_short = False
    try:
        for scenario in scenarios:
            name = scenario["name"]
            result = report / f"{name}.json"
            if result.exists() and not args.force:
                print(f"skip  {name}: {result} is there (--force sends it again)")
                continue
            print(f"\n== {name}: {len(scenario['files'])} photos, {scenario['imitates']}")
            own = report / f"{name}.deck.json"  # run_exam_deck's own report, folded into ours below
            own.unlink(missing_ok=True)
            started = time.monotonic()
            deck.run(deck.parse_args(["--images", str(root / name), "--server", args.server, "--out", str(own), "--force"]))
            if not own.exists():
                print(f"STOP  {name}: the route gave no answer bundle; nothing is recorded and the suite stops here")
                cut_short = True
                break
            ran = json.loads(own.read_text(encoding="utf-8"))
            own.unlink()
            saved = {"scenario": scenario, "wall_s": round(time.monotonic() - started, 1), "deck": ran,
                     "evaluation": evaluate(scenario["expect"], ran["bundle"]["items"], ran.get("stopped"))}
            result.write_text(json.dumps(saved, ensure_ascii=False, indent=1), encoding="utf-8")
            if ran.get("stopped"):
                print(f"STOP  {name}: the server stopped; sending more would repeat it, the suite stops here")
                cut_short = True
                break
    finally:
        failed = summarize(report)
    return 1 if cut_short else failed


def self_check() -> int:
    """The geometry and the judging on made-up input; no exam material, no server."""
    import tempfile

    dst, src = [(0, 0), (100, 0), (100, 80), (0, 80)], [(-5, 2), (108, -1), (101, 83), (3, 79)]
    coeffs = homography(dst, src)
    assert np.allclose(through(coeffs, dst), src) and np.allclose(through(coeffs, src, inverse=True), dst)

    upright = Image.fromarray(np.arange(12, dtype=np.uint8).reshape(4, 3))  # 3 wide, 4 high
    stored = as_stored(upright)
    assert stored.size == (4, 3), "stored landscape, as run_exam_deck.load_images requires"
    assert np.array_equal(np.asarray(stored.transpose(Image.Transpose.ROTATE_90)), np.asarray(upright))

    canvas, dot = Image.new("RGB", (400, 400)), Image.new("RGB", (200, 100))
    ImageDraw.Draw(dot).ellipse((147, 17, 153, 23), fill="white")  # centred on (150, 20): fractions (0.75, 0.2)
    where = lay(canvas, dot, (200, 200), 30)
    ys, xs = np.nonzero(np.asarray(canvas)[..., 2] > 128)
    assert abs(xs.mean() - where(0.75, 0.2)[0]) < 1.5 and abs(ys.mean() - where(0.75, 0.2)[1]) < 1.5

    windows = part_windows(0.62, 0.02, 1.41)
    assert all(abs(u1 - u0 - 0.62) < 1e-9 for u0, _, u1, _ in windows.values())
    assert hidden_pages([[1, 2], [3, 4]], windows.values()) == []
    assert hidden_pages([[1, 2], [3, 4]], [w for name, w in windows.items() if name != "br"]) == [4]
    assert pairs(1, 5, "left") == [[1, 2], [3, 4], [5]] and pairs(1, 4, "right") == [[2, 1], [4, 3]]

    with tempfile.TemporaryDirectory() as folder:  # two pages of blocks 20 px apart on lines 36 px apart
        for n in (1, 2):
            leaf = Image.new("L", (600, 846), 255)
            for y in range(80, 760, 36):
                for x in range(60, 540, 20):
                    ImageDraw.Draw(leaf).rectangle((x, y, x + 13, y + 15), fill=0)
            leaf.save(Path(folder) / f"page{n:03d}.png")
        shot = {"grid": [[1, 2]], "page_w": 600, "anchor": [0.5, 0.5], "at": [0.5, 0.6], "angle": 1.0}
        frame, clean, quads = render(shot, {**STILL, "source": folder}, np.random.default_rng(1))
        page.cache_clear()
        sheet_image.cache_clear()
    assert frame.size == (FRAME_W, FRAME_H) and clean.shape == (FRAME_H, FRAME_W, 3)
    line, char = text_pitch(np.asarray(rectify(frame, quads[1]).convert("L"))[60:-60, 50:-50])
    assert abs(line - 36) < 2.5 and abs(char - 20) < 1.4, (line, char)  # the slant shrinks it by about 3%

    def item(status, numbers=(), answer="", issue=""):
        return {"status": status, "answer_no": list(numbers), "answer": answer, "issue": issue, "question_label": ""}

    expect = {"mode": "strict", "key": {"101": "4", "102": "2", "110": "5", "111": "6"}, "known_gap_pages": [13]}
    good = [item("ready", [101], "④"), item("ready", [102], "2"), item("ready", [110, 111], "⑤,⑥"),
            item("needs_input", issue="印刷ページ13が未収録です。")]
    judged = evaluate(expect, good)
    assert (judged["verdict"], judged["matches"], judged["unexpected_needs_input"]) == ("PASS", 4, 0), judged
    assert evaluate(expect, good + [item("needs_input", issue="端で切れています")])["verdict"] == "LOOK"
    wrong = evaluate(expect, [item("ready", [101], "3"), *good[1:]])
    assert wrong["verdict"] == "FAIL" and wrong["wrong_unflagged"] == [101]
    assert evaluate(expect, good + [item("ready", [102], "2")])["twice"] == [102]
    assert evaluate(expect, good + [item("ready", [120], "1")])["verdict"] == "FAIL"  # made from the answer sheet
    assert evaluate(expect, good[1:])["verdict"] == "FAIL"  # 101 gone
    assert evaluate(expect, good, stopped="usage limit")["verdict"] == "FAIL"
    flagged = [item("needs_review", [101], "3"), *good[1:]]
    assert evaluate(expect, flagged)["verdict"] == "FAIL"
    assert evaluate({**expect, "mode": "tolerant"}, flagged)["verdict"] == "LOOK"
    skipped = {**expect, "answerable": [101, 110, 111], "withheld": [102], "min_needs_input": 1, "gap_pages": [6, 7]}
    rest = [good[0], good[2]]
    assert evaluate(skipped, rest)["verdict"] == "FAIL"  # nothing says a page is missing
    assert evaluate(skipped, rest + [item("needs_input", issue="ページ5の次が8です")])["verdict"] == "PASS"
    assert evaluate(skipped, rest + [item("needs_input", [102], issue="表が隠れています")])["verdict"] == "LOOK"
    assert evaluate(skipped, rest + [item("needs_input", [102], issue="印刷ページ6が未収録")])["verdict"] == "PASS"
    assert evaluate(skipped, rest + [item("needs_input", issue="印刷ページ6、7、13が未収録")])["verdict"] == "PASS"
    assert evaluate(skipped, rest + [good[3]])["verdict"] == "FAIL"  # only the source's own gap is reported
    assert evaluate(skipped, rest + [item("ready", [102], "5"), good[3]])["verdict"] == "FAIL"
    dark = {**expect, "mode": "unreadable"}
    assert evaluate(dark, [item("needs_input", issue="判読できません")])["verdict"] == "PASS"
    assert evaluate(dark, good)["verdict"] == "LOOK"
    assert evaluate({"mode": "complete"}, [item("ready", answer="x"), item("needs_input")])["verdict"] == "PASS"
    assert evaluate({"mode": "complete"}, [item("failed")])["verdict"] == "FAIL"
    print("self-check ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # the bundle's answers hold characters cp932 cannot print
        stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--self-check", action="store_true", help="check the geometry and the judging on made-up input")
    commands = parser.add_subparsers(dest="command")
    build = commands.add_parser("build", help="make every scenario's images and scenario.json")
    build.add_argument("--out", required=True, help="data/scenarios")
    build.add_argument("--only", help="NAME,...")
    build.add_argument("--set", action="append", default=[], metavar="NAME.PARAM=VALUE",
                       help="one parameter of one scenario, e.g. spread_far.width_frac=0.4")
    run = commands.add_parser("run", help="send each scenario through the server and judge the answers")
    run.add_argument("--server", required=True, help="e.g. http://127.0.0.1:18000 (the key: ROKID_API_KEY)")
    run.add_argument("--scenarios", required=True)
    run.add_argument("--report", required=True)
    run.add_argument("--only", help="NAME,...")
    run.add_argument("--force", action="store_true", help="send a scenario again though its result is saved")
    check = commands.add_parser("check", help="judge saved results again, without a server")
    check.add_argument("dir")
    args = parser.parse_args(argv)
    if args.self_check:
        return self_check()
    if args.command == "build":
        return cmd_build(args)
    if args.command == "run":
        return cmd_run(args)
    if args.command == "check":
        return summarize(Path(args.dir))
    parser.error("give a command, or --self-check")


if __name__ == "__main__":
    raise SystemExit(main())

"""A located page is enlarged and cut, along its lines of text, into as few images as are each read in full detail.

Measured on the phone on 2026-11-15 (docs/hardware-measurements.md, M-23, E8): one worn photo of vertical text with
characters of 15.8 px, the same pixels at twice the size, six reads each. The whole page as one image (4,560 patches
of 32 px): 4.10% of 199 characters wrong, a wrong answer in four reads of six. Two strips along the lines (1,920 and
2,880 patches): 1.59%, a wrong answer in one of six. Four strips: 2.60%, none. Cut across the lines (E3): 3.5 to 5.5%.
One input read twice differs by up to 6.5 points, so nothing here rests on a single read.
"""
from __future__ import annotations

import math

import pytest
from PIL import Image, ImageDraw

from app.source_bundle import MAX_IMAGE_PATCHES, page_tiles


def _rows(width, height, blocks):
    """A white page with lines of horizontal text: grey bars inside each (top, bottom) band."""
    page = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(page)
    for top, bottom in blocks:
        for y in range(top, bottom, 12):
            draw.rectangle([40, y, width - 40, y + 6], fill=(40, 40, 40))
    return page


def _columns(width, height, blocks):
    """A white page with lines of vertical text: grey bars, top to bottom, inside each (left, right) band."""
    page = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(page)
    for left, right in blocks:
        for x in range(left, right, 12):
            draw.rectangle([x, 40, x + 6, height - 40], fill=(40, 40, 40))
    return page


def _patches(tile):
    return math.ceil(tile.width / 32) * math.ceil(tile.height / 32)


def _boxes(page, **options):
    return [box for _, box in page_tiles(page, **options)]


def test_a_page_is_enlarged_until_its_long_side_reaches_the_target():
    tiles = page_tiles(_rows(900, 1250, [(60, 1190)]), vertical_text=False, target_long=2500)
    assert all(tile.size == (round((box[2] - box[0]) * 2), round((box[3] - box[1]) * 2)) for tile, box in tiles)


def test_a_page_is_never_enlarged_past_the_limit_and_never_reduced():
    [(small, _)] = page_tiles(_rows(400, 560, [(40, 520)]), target_long=2500, max_scale=2.5)
    assert small.size == (1000, 1400)
    large = page_tiles(_rows(1900, 2600, [(60, 2500)]), target_long=2500)
    assert all(tile.size == (box[2] - box[0], box[3] - box[1]) for tile, box in large)


@pytest.mark.parametrize("vertical", [True, False, None])
@pytest.mark.parametrize("size", [(910, 1270), (1380, 2020), (2200, 1700), (3024, 4032), (600, 2600)])
def test_every_image_stays_inside_the_size_that_was_read_best(size, vertical):
    page = _columns(*size, [(60, size[0] - 60)]) if vertical else _rows(*size, [(60, size[1] - 60)])
    for tile, _ in page_tiles(page, vertical_text=vertical):
        assert _patches(tile) <= MAX_IMAGE_PATCHES, tile.size
    assert MAX_IMAGE_PATCHES <= 2900, "strips of 1,920 and 2,880 patches were read best; one image of 4,560 was not"


@pytest.mark.parametrize("vertical", [True, False])
@pytest.mark.parametrize("size", [(910, 1270), (2200, 1700), (3024, 4032)])
def test_the_images_cover_the_whole_page_and_neighbours_share_what_the_measured_strips_shared(size, vertical):
    page = _columns(*size, [(60, size[0] - 60)]) if vertical else _rows(*size, [(60, size[1] - 60)])
    boxes = _boxes(page, vertical_text=vertical)
    covered = Image.new("1", size, 0)
    for left, top, right, bottom in boxes:
        covered.paste(1, (left, top, right, bottom))
    assert covered.histogram()[0] == 0, "no part of the page is left out"
    edges = sorted((box[0], box[2]) if vertical else (box[1], box[3]) for box in boxes)
    part = (size[0] if vertical else size[1]) / len(boxes)
    assert all(earlier[1] - later[0] >= part * 0.06 for earlier, later in zip(edges, edges[1:])), edges


def test_vertical_text_is_cut_into_strips_down_the_page_between_its_lines_and_the_rightmost_comes_first():
    """Vertical Japanese text is read from the right; a band across it cuts every line (3.5 to 5.5% wrong)."""
    page = _columns(910, 1270, [(60, 300), (420, 850)])
    boxes = _boxes(page, vertical_text=True)
    assert len(boxes) == 2 and all(box[1] == 0 and box[3] == 1270 for box in boxes), boxes
    assert boxes[0][0] > boxes[1][0], "the first image is the right edge"
    cut = (boxes[0][0] + boxes[1][2]) / 2  # the two strips overlap around it
    assert boxes[0][0] < boxes[1][2] and 300 <= cut <= 420, "the cut is in the blank band, off the middle"


def test_horizontal_text_is_cut_into_bands_across_the_page_between_its_lines_from_the_top():
    page = _rows(910, 1270, [(60, 520), (700, 1210)])
    boxes = _boxes(page, vertical_text=False)
    assert len(boxes) == 2 and all(box[0] == 0 and box[2] == 910 for box in boxes), boxes
    assert boxes[0][1] < boxes[1][1]
    cut = (boxes[1][1] + boxes[0][3]) / 2
    assert boxes[1][1] < boxes[0][3] and 520 <= cut <= 700, "the cut is in the blank band, off the middle"


def test_when_the_direction_is_not_known_the_longer_side_is_cut():
    assert all(box[0] == 0 and box[2] == 910 for box in _boxes(_rows(910, 1270, [(60, 1210)])))
    assert all(box[1] == 0 and box[3] == 910 for box in _boxes(_columns(1270, 910, [(60, 1210)])))


def test_a_page_that_fits_is_one_image():
    [(tile, box)] = page_tiles(_rows(600, 800, [(40, 760)]), vertical_text=False, target_long=1200)
    assert box == (0, 0, 600, 800) and tile.size == (900, 1200)


def test_a_cut_moved_to_a_blank_band_never_leaves_an_image_too_large():
    """The only blank band is well off the middle; moving the cut there makes one part longer than an even share."""
    page = _rows(910, 1270, [(60, 760), (840, 1210)])
    tiles = page_tiles(page, vertical_text=False)
    assert all(_patches(tile) <= MAX_IMAGE_PATCHES for tile, _ in tiles), [tile.size for tile, _ in tiles]

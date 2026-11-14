"""A located page is enlarged and cut into tiles the model receives at full size.

Measured on the phone on 2026-11-14 (docs/hardware-measurements.md, M-22): a photo with characters of 15.8 px was read
with 18% of them wrong as it was and with none wrong when the question's block was sent at twice the size; the whole
page at twice the size went past the model side's limits, and a cut through a line of text cost characters beside it.
"""
from __future__ import annotations

import math

import pytest
from PIL import Image, ImageDraw

from app.source_bundle import MAX_TILE_PATCHES, MAX_TILE_SIDE, page_tiles


def _page(width, height, blocks):
    """A white page with grey text-like bars inside each (top, bottom) band."""
    page = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(page)
    for top, bottom in blocks:
        for y in range(top, bottom, 12):
            draw.rectangle([40, y, width - 40, y + 6], fill=(40, 40, 40))
    return page


def _patches(tile):
    return math.ceil(tile.width / 32) * math.ceil(tile.height / 32)


def test_a_page_is_enlarged_until_its_long_side_reaches_the_target():
    tiles = page_tiles(_page(900, 1250, [(60, 1190)]), target_long=2500)
    assert sum(tile.height for tile, _ in tiles) >= 2500
    assert all(tile.width == 1800 for tile, _ in tiles)


def test_a_page_is_never_enlarged_past_the_limit_and_never_reduced():
    small = page_tiles(_page(400, 560, [(40, 520)]), target_long=2500, max_scale=2.5)
    assert small[0][0].width == 1000
    large = page_tiles(_page(1900, 2600, [(60, 2500)]), target_long=2500)
    assert max(box[2] for _, box in large) == 1900 and max(box[3] for _, box in large) == 2600
    assert sum(tile.height for tile, _ in large) >= 2600


@pytest.mark.parametrize("size", [(900, 1250), (1380, 2020), (2200, 1700), (3024, 4032), (600, 2600)])
def test_every_tile_stays_inside_what_the_model_side_takes_without_reducing(size):
    for tile, _ in page_tiles(_page(*size, [(60, size[1] - 60)])):
        assert max(tile.size) <= MAX_TILE_SIDE
        assert _patches(tile) <= MAX_TILE_PATCHES


@pytest.mark.parametrize("size", [(900, 1250), (2200, 1700), (3024, 4032)])
def test_the_tiles_cover_the_whole_page_and_neighbours_overlap(size):
    boxes = [box for _, box in page_tiles(_page(*size, [(60, size[1] - 60)]))]
    covered = Image.new("1", size, 0)
    for left, top, right, bottom in boxes:
        covered.paste(1, (left, top, right, bottom))
    assert covered.getbbox() == (0, 0, *size) and covered.histogram()[0] == 0
    columns = sorted({(box[0], box[2]) for box in boxes})
    rows = sorted({(box[1], box[3]) for box in boxes if (box[0], box[2]) == columns[0]})
    assert all(later[0] < earlier[1] for earlier, later in zip(rows, rows[1:])), "bands of one column must overlap"
    assert all(later[0] < earlier[1] for earlier, later in zip(columns, columns[1:])), "columns must overlap"


def test_a_cut_falls_in_the_blank_band_between_two_blocks_of_text_not_through_a_line():
    """The blank band is off the middle: a cut at the midpoint would run through the lower block's first lines."""
    page = _page(900, 1250, [(60, 520), (700, 1190)])
    rows = sorted({(box[1], box[3]) for _, box in page_tiles(page, target_long=2500)})
    assert len(rows) == 2
    upper_end, lower_start = rows[0][1], rows[1][0]
    assert 520 <= lower_start <= upper_end <= 700, (lower_start, upper_end)


def test_a_page_that_fits_is_one_tile():
    [(tile, box)] = page_tiles(_page(600, 800, [(40, 760)]), target_long=1200)
    assert box == (0, 0, 600, 800) and tile.size == (900, 1200)


def test_a_cut_moved_to_a_blank_band_never_leaves_a_tile_too_large():
    """The only blank band is well below the middle; moving the cut there makes the upper part longer than half."""
    page = _page(900, 1250, [(60, 720), (800, 1190)])
    tiles = page_tiles(page, target_long=2500)
    assert any(720 <= box[3] <= 830 for _, box in tiles), "the cut should still use the blank band"
    for tile, _ in tiles:
        assert max(tile.size) <= MAX_TILE_SIDE and _patches(tile) <= MAX_TILE_PATCHES, tile.size

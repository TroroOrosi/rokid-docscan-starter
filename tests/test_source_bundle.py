import io

import pytest
from PIL import Image, ImageDraw

from app.source_bundle import source_bundle


def _near(pixel, colour, tolerance=6):
    return all(abs(a - b) <= tolerance for a, b in zip(pixel, colour))


def pages_at(tmp_path, count):
    pages = []
    for i in range(count):
        path = tmp_path / f"{i}.png"
        Image.new("RGB", (32, 48), (i, 50, 100)).save(path)
        pages.append({"page_number": i + 1, "image_path": str(path),
                      "ocr_text": f"本文{i + 1}", "question_ids": [f"q{i}"]})
    return pages


def test_primary_bundle_keeps_shared_pages_without_ocr_or_transcript(tmp_path):
    pages = pages_at(tmp_path, 8)
    files = source_bundle(pages)
    assert [f["name"] for f in files] == [f"page{i:03d}.jpg" for i in range(1, 9)]
    assert {f["mimeType"] for f in files} == {"image/jpeg"}
    image = Image.open(io.BytesIO(files[6]["buffer"]))
    assert image.width == 32
    assert _near(image.getpixel((0, image.height - 1)), (6, 50, 100))


@pytest.mark.parametrize("count", [19, 20, 21, 39, 40, 55])
def test_merged_bundle_preserves_every_page_pixel(tmp_path, count):
    files = source_bundle(pages_at(tmp_path, count))
    assert len(files) <= 20
    pixels = []
    for item in files:
        image = Image.open(io.BytesIO(item["buffer"]))
        pixels += [image.getpixel((x, y)) for y in range(image.height) for x in range(image.width)]
    # JPEG is lossy by a few levels; every page's colour is still there.
    assert all(any(_near(p, (i, 50, 100)) for p in pixels) for i in range(count))


def test_no_renumbering_or_silent_missing_images(tmp_path):
    pages = pages_at(tmp_path, 3)
    pages[1]["ocr_text"] = ""
    files = source_bundle(pages)
    assert files[1]["name"] == "page002.jpg"
    pages[1]["image_path"] = "missing"
    with pytest.raises(ValueError, match="Page 002"):
        source_bundle(pages)


def test_dark_photo_is_brightened_and_trimmed_to_the_paper(tmp_path):
    """A dark shot of a page on a blue map, as the glasses took it on 2026-09-22."""
    photo = Image.new("RGB", (800, 1000), (10, 20, 70))
    photo.paste((80, 80, 80), (200, 300, 600, 700))
    photo.paste((12, 12, 12), (250, 400, 550, 410))
    path = tmp_path / "dark.png"
    photo.save(path)
    before = path.read_bytes()
    sent = Image.open(io.BytesIO(source_bundle([{"page_number": 1, "image_path": str(path)}])[0]["buffer"]))
    assert 400 <= sent.width < 800 and 400 < sent.height < 1000
    assert min(sent.getpixel((sent.width // 2, sent.height // 2))) > 200
    assert path.read_bytes() == before


def test_an_oversized_page_drops_jpeg_quality_never_resolution(tmp_path, monkeypatch):
    import random
    import app.source_bundle as source

    path = tmp_path / "noise.png"
    Image.frombytes("RGB", (640, 640), random.Random(3).randbytes(640*640*3)).save(path)
    first = source_bundle([{"page_number": 1, "image_path": str(path)}])[0]["buffer"]
    monkeypatch.setattr(source, "MAX_IMAGE_BYTES", len(first) - 1)
    files = source_bundle([{"page_number": 1, "image_path": str(path)}])
    assert files[0]["mimeType"] == "image/jpeg" and len(files[0]["buffer"]) < len(first)
    assert Image.open(io.BytesIO(files[0]["buffer"])).size == (640, 666)
    assert path.read_bytes().startswith(b"\x89PNG")


def spread_at(tmp_path, size=(1200, 800), fold=680):
    """Paper with columns of character-sized marks, and a shaded fold unless fold is None."""
    photo = Image.new("RGB", size, (235, 235, 235))
    draw = ImageDraw.Draw(photo)
    for x in range(100, size[0] - 100, 30):
        if fold is None or not fold - 60 < x < fold + 60:
            for y in range(120, size[1] - 120, 24):
                draw.rectangle((x, y, x + 10, y + 10), fill=(30, 30, 30))
    if fold is not None:
        for i in range(30):  # the shadow deepens into the fold, as on 2026-09-22
            draw.line((fold - 30 + i, 0, fold - 30 + i, size[1]), fill=(235 - 4 * i,) * 3)
    path = tmp_path / f"{size[0]}x{size[1]}-{fold}.png"
    photo.save(path)
    return path


def test_a_spread_is_sent_as_its_right_page_then_its_left(tmp_path):
    """Run 4b: a whole spread fitted in 768 px was unreadable; one page is not."""
    files = source_bundle([{"page_number": 2, "image_path": str(spread_at(tmp_path))}])
    assert [f["name"] for f in files] == ["page002R.jpg", "page002L.jpg"]
    right, left = (Image.open(io.BytesIO(f["buffer"])) for f in files)
    assert abs(right.width - 520) <= 12 and right.width + left.width == 1200


@pytest.mark.parametrize("size, fold", [((800, 1200), 400), ((1200, 800), None)])
def test_a_single_page_is_sent_whole(tmp_path, size, fold):
    files = source_bundle([{"page_number": 1, "image_path": str(spread_at(tmp_path, size, fold))}])
    assert [f["name"] for f in files] == ["page001.jpg"]
    assert Image.open(io.BytesIO(files[0]["buffer"])).width == size[0]


@pytest.mark.parametrize("photos, max_files, per_file", [(15, 20, 2), (15, 19, 2), (25, 20, 3), (40, 20, None)])
def test_split_pages_keep_the_budget_order_and_page_width(tmp_path, photos, max_files, per_file):
    """Every third photo is a single page; the rest are spreads."""
    spread, single = spread_at(tmp_path), spread_at(tmp_path, (800, 1200), None)
    pages = [{"page_number": n, "image_path": str(spread if n % 3 else single)}
             for n in range(1, photos + 1)]
    if per_file is None:
        with pytest.raises(ValueError, match="too many pages"):
            source_bundle(pages, max_files=max_files)
        return
    files = source_bundle(pages, max_files=max_files)
    labels = [f["name"][4:-4].split("-") for f in files]
    assert len(files) <= max_files and {len(group) for group in labels[:-1]} == {per_file}
    assert [label for group in labels for label in group] == [
        f"{n:03d}{side}" for n in range(1, photos + 1) for side in (("R", "L") if n % 3 else ("",))]
    assert all(Image.open(io.BytesIO(f["buffer"])).width <= 800 for f in files)

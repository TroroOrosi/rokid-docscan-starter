import io

import pytest
from PIL import Image

from app.source_bundle import source_bundle


def pages_at(tmp_path, count):
    pages = []
    for i in range(count):
        path = tmp_path / f"{i}.png"
        Image.new("RGB", (32, 48), (i, 50, 100)).save(path)
        pages.append({"page_number": i + 1, "image_path": str(path),
                      "ocr_text": f"本文{i + 1}", "question_ids": [f"q{i}"]})
    return pages


@pytest.mark.parametrize("mode", ["images", "ocr-images", "merged-images"])
def test_primary_bundle_keeps_shared_pages_without_ocr_or_transcript(tmp_path, mode):
    pages = pages_at(tmp_path, 8)
    files = source_bundle(pages, mode=mode)
    assert [f["name"] for f in files] == [f"page{i:03d}.png" for i in range(1, 9)]
    image = Image.open(io.BytesIO(files[6]["buffer"]))
    assert image.width == 32
    assert image.getpixel((0, image.height - 1)) == (6, 50, 100)


@pytest.mark.parametrize("count", [19, 20, 21, 39, 40, 55])
def test_merged_bundle_preserves_every_page_pixel(tmp_path, count):
    files = source_bundle(pages_at(tmp_path, count), mode="merged-images")
    assert len(files) <= 20
    pixels = set()
    for item in files:
        image = Image.open(io.BytesIO(item["buffer"]))
        pixels.update(image.getpixel((x, y)) for y in range(image.height) for x in range(image.width))
    assert all((i, 50, 100) in pixels for i in range(count))


def test_no_renumbering_or_silent_missing_images(tmp_path):
    pages = pages_at(tmp_path, 3)
    pages[1]["ocr_text"] = ""
    files = source_bundle(pages)
    assert files[1]["name"] == "page002.png"
    pages[1]["image_path"] = "missing"
    with pytest.raises(ValueError, match="Page 002"):
        source_bundle(pages)


def test_oversized_png_uses_full_size_jpeg(tmp_path, monkeypatch):
    import random
    import app.source_bundle as source

    path = tmp_path / "noise.png"
    Image.frombytes("RGB", (640, 640), random.Random(3).randbytes(640*640*3)).save(path)
    monkeypatch.setattr(source, "MAX_IMAGE_BYTES", 1_100_000)
    files = source_bundle([{"page_number": 1, "image_path": str(path)}])
    assert files[0]["mimeType"] == "image/jpeg"
    assert Image.open(io.BytesIO(files[0]["buffer"])).size == (640, 666)
    assert path.read_bytes().startswith(b"\x89PNG")

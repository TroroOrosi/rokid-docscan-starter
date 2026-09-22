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


def test_primary_bundle_uses_all_text_but_only_the_questions_original_pages(tmp_path):
    pages = pages_at(tmp_path, 21)
    files = source_bundle(pages, page_numbers=[7, 8], document_id="doc9")
    assert [f["name"] for f in files] == ["document.md", "page007.png", "page008.png"]
    text = files[0]["buffer"].decode()
    assert "Page 001" in text and "Page 021" in text and "q6" in text
    image = Image.open(io.BytesIO(files[1]["buffer"]))
    assert image.width == 32
    assert image.getpixel((0, image.height - 1)) == (6, 50, 100)


@pytest.mark.parametrize("count", [19, 20, 21, 39, 40, 55])
def test_merged_bundle_counts_markdown_and_preserves_every_page_pixel(tmp_path, count):
    files = source_bundle(pages_at(tmp_path, count), mode="merged-images")
    assert len(files) <= 20
    pixels = set()
    for item in files[1:]:
        image = Image.open(io.BytesIO(item["buffer"]))
        pixels.update(image.getpixel((x, y)) for y in range(image.height) for x in range(image.width))
    assert all((i, 50, 100) in pixels for i in range(count))


def test_no_renumbering_or_silent_missing_images(tmp_path):
    pages = pages_at(tmp_path, 3)
    pages[1]["ocr_text"] = ""
    files = source_bundle(pages, page_numbers=[2])
    assert "OCR unavailable" in files[0]["buffer"].decode()
    assert files[1]["name"] == "page002.png"
    pages[1]["image_path"] = "missing"
    with pytest.raises(ValueError, match="Page 002"):
        source_bundle(pages, page_numbers=[2])


def test_oversized_png_uses_full_size_jpeg(tmp_path, monkeypatch):
    import random
    import app.source_bundle as source

    path = tmp_path / "noise.png"
    Image.frombytes("RGB", (640, 640), random.Random(3).randbytes(640*640*3)).save(path)
    monkeypatch.setattr(source, "MAX_IMAGE_BYTES", 1_100_000)
    files = source_bundle([{"page_number": 1, "image_path": str(path)}])
    assert files[1]["mimeType"] == "image/jpeg"
    assert Image.open(io.BytesIO(files[1]["buffer"])).size == (640, 666)
    assert path.read_bytes().startswith(b"\x89PNG")

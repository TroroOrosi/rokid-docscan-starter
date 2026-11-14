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


@pytest.mark.parametrize("count", [19, 20, 21, 39, 40, 55, 61, 120])
def test_each_page_keeps_its_own_image_without_a_booklet_limit(tmp_path, count):
    files = source_bundle(pages_at(tmp_path, count))
    assert len(files) == count
    assert all(Image.open(io.BytesIO(item["buffer"])).size == (32, 48) for item in files)
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


def test_fine_coloured_lines_keep_their_separate_colours(tmp_path):
    photo = Image.new("RGB", (96, 144), "white")
    draw = ImageDraw.Draw(photo)
    for x in range(24, 72):
        draw.line((x, 24, x, 120), fill=(240, 48, 48) if x % 2 == 0 else (48, 48, 240))
    path = tmp_path / "fine-coloured-lines.png"
    photo.save(path)
    before = path.read_bytes()

    payload = source_bundle([{"page_number": 1, "image_path": str(path)}])[0]
    with Image.open(io.BytesIO(payload["buffer"])) as sent:
        red = sent.getpixel((40, 72))
        blue = sent.getpixel((41, 72))
        assert red[0] - red[2] > 140
        assert blue[2] - blue[0] > 140
        assert sent.size == photo.size
    assert path.read_bytes() == before


def _sent(path, number=1):
    return [Image.open(io.BytesIO(f["buffer"])) for f in source_bundle([{"page_number": number, "image_path": str(path)}])]


def test_a_dark_page_on_a_desk_is_brightened_cropped_with_a_margin_and_its_original_kept(tmp_path):
    """A dark shot of a page on a blue map, as the glasses took it on 2026-09-22."""
    photo = Image.new("RGB", (800, 1000), (10, 20, 70))
    photo.paste((80, 80, 80), (200, 300, 600, 700))
    photo.paste((12, 12, 12), (250, 400, 550, 410))
    path = tmp_path / "dark.png"
    photo.save(path)
    before = path.read_bytes()
    sent, = _sent(path)
    # The whole 400x400 page with 4% of the frame's short side (32 px) around it.
    assert all(400 + 2 * 24 <= side <= 400 + 2 * 40 for side in sent.size)
    assert min(sent.getpixel((sent.width // 2, sent.height // 2))) > 80
    assert _near(sent.getpixel((2, 2)), (10 * 3, 20 * 3, 70 * 3), 40)  # the desk is still around it
    assert path.read_bytes() == before


def desk_with(tmp_path, name, paper, *, frame=(1200, 1600), shade=None):
    """A grey sheet at ``paper`` on a dark desk; ``shade`` darkens a box of it to a shadow."""
    photo = Image.new("RGB", frame, (12, 14, 20))
    photo.paste((230, 230, 230), paper)
    draw = ImageDraw.Draw(photo)
    for x in range(paper[0] + 40, paper[2] - 40, 30):
        for y in range(paper[1] + 40, paper[3] - 40, 24):
            draw.rectangle((x, y, x + 10, y + 10), fill=(30, 30, 30))
    if shade:
        shadow = photo.crop(shade).point(lambda value: value * 2 // 5)
        photo.paste(shadow, shade)
    path = tmp_path / f"{name}.png"
    photo.save(path)
    return path


def test_a_sheet_on_a_desk_is_sent_as_the_sheet_and_a_margin(tmp_path):
    """Chat fits the long edge to 2048 px; the desk must not use them up."""
    sent, = _sent(desk_with(tmp_path, "sheet", (300, 700, 800, 1400)))
    margin = 0.04 * 1200
    assert 500 + 2 * margin - 16 <= sent.width <= 500 + 2 * margin + 16
    assert 700 + 2 * margin - 16 <= sent.height <= 700 + 2 * margin + 16


@pytest.mark.parametrize("name, paper, shade", [
    # The sheet runs out of the frame on two sides: its real extent is unknown.
    ("corner", (0, 0, 700, 900), None),
    # Smaller than any sheet the crop was checked on (25% to 49% of the frame).
    ("small", (500, 700, 800, 1100), None),
    # A shadow hides the lower third: the lit part alone looks like a smaller sheet.
    ("shadow", (300, 500, 900, 1400), (300, 1100, 900, 1400)),
])
def test_an_uncertain_paper_box_sends_the_whole_frame(tmp_path, name, paper, shade):
    sent, = _sent(desk_with(tmp_path, name, paper, shade=shade))
    assert sent.size == (1200, 1600)


@pytest.mark.parametrize("box", [(25, 25, 475, 675), (60, 200, 440, 620)])
def test_a_ruled_box_on_a_page_that_fills_the_frame_is_not_taken_for_the_paper(tmp_path, box):
    """A rendered or close-up page: the print outside the box is paper too."""
    page = Image.new("RGB", (500, 700), "white")
    draw = ImageDraw.Draw(page)
    draw.rectangle(box, outline="black", width=3)
    draw.text((30, 8), "outside the box", fill="black")
    path = tmp_path / "ruled.png"
    page.save(path)
    sent, = _sent(path)
    assert sent.size == (500, 700)


def test_a_frame_without_paper_is_sent_whole(tmp_path):
    path = tmp_path / "desk.png"
    Image.new("RGB", (1200, 1600), (12, 14, 20)).save(path)
    sent, = _sent(path)
    assert sent.size == (1200, 1600)


def test_an_oversized_page_drops_jpeg_quality_never_resolution(tmp_path, monkeypatch):
    import random
    import app.source_bundle as source

    path = tmp_path / "noise.png"
    Image.frombytes("RGB", (640, 640), random.Random(3).randbytes(640*640*3)).save(path)
    first = source_bundle([{"page_number": 1, "image_path": str(path)}])[0]["buffer"]
    monkeypatch.setattr(source, "MAX_IMAGE_BYTES", len(first) - 1)
    files = source_bundle([{"page_number": 1, "image_path": str(path)}])
    assert files[0]["mimeType"] == "image/jpeg" and len(files[0]["buffer"]) < len(first)
    assert Image.open(io.BytesIO(files[0]["buffer"])).size == (640, 640)
    assert path.read_bytes().startswith(b"\x89PNG")


def spread_at(tmp_path, size=(1200, 800), fold=680, mark=10):
    """Paper with columns of character-sized marks, and a shaded fold unless fold is None."""
    photo = Image.new("RGB", size, (235, 235, 235))
    draw = ImageDraw.Draw(photo)
    for x in range(100, size[0] - 100, 30):
        if fold is None or not fold - 60 < x < fold + 60:
            for y in range(120, size[1] - 120, 24):
                draw.rectangle((x, y, x + 10, y + mark), fill=(30, 30, 30))
    if fold is not None:
        for i in range(30):  # the shadow deepens into the fold, as on 2026-09-22
            draw.line((fold - 30 + i, 0, fold - 30 + i, size[1]), fill=(235 - 4 * i,) * 3)
    path = tmp_path / f"{size[0]}x{size[1]}-{fold}-{mark}.png"
    photo.save(path)
    return path


def test_a_spread_is_sent_as_its_right_page_then_its_left(tmp_path):
    """Run 4b: a whole spread fitted in 768 px was unreadable; one page is not."""
    files = source_bundle([{"page_number": 2, "image_path": str(spread_at(tmp_path))}])
    assert [f["name"] for f in files] == ["page002R.jpg", "page002L.jpg"]
    right, left = (Image.open(io.BytesIO(f["buffer"])) for f in files)
    assert abs(right.width - 520) <= 12 and right.width + left.width == 1200


def test_a_spread_inside_a_portrait_photo_is_cropped_to_the_spread_then_split(tmp_path):
    """The 2026-09-30 run that read nothing sent a cropped spread whole; the split followed it."""
    spread = Image.open(spread_at(tmp_path, mark=5))
    photo = Image.new("RGB", (1400, 1800), (10, 20, 70))
    photo.paste(spread, (100, 700))
    path = tmp_path / "portrait-with-spread.png"
    photo.save(path)
    files = source_bundle([{"page_number": 1, "image_path": str(path)}])
    assert [f["name"] for f in files] == ["page001R.jpg", "page001L.jpg"]
    right, left = (Image.open(io.BytesIO(f["buffer"])) for f in files)
    margin = 0.04 * 1400
    # Both pages whole, the margin kept, the empty upper frame gone.
    assert 1200 + 2 * margin - 16 <= right.width + left.width <= 1200 + 2 * margin + 16
    assert 800 + 2 * margin - 16 <= right.height == left.height <= 800 + 2 * margin + 16
    assert abs(right.width - (520 + margin)) <= 20


@pytest.mark.parametrize("size, fold", [((800, 1200), 400), ((1200, 800), None)])
def test_a_single_page_is_sent_whole(tmp_path, size, fold):
    files = source_bundle([{"page_number": 1, "image_path": str(spread_at(tmp_path, size, fold))}])
    assert [f["name"] for f in files] == ["page001.jpg"]
    assert Image.open(io.BytesIO(files[0]["buffer"])).width == size[0]


@pytest.mark.parametrize("photos", [15, 25, 40])
def test_split_pages_keep_their_order_and_page_width(tmp_path, photos):
    """Every third photo is a single page; the rest are spreads."""
    spread, single = spread_at(tmp_path), spread_at(tmp_path, (800, 1200), None)
    pages = [{"page_number": n, "image_path": str(spread if n % 3 else single)}
             for n in range(1, photos + 1)]
    files = source_bundle(pages)
    assert [f["name"][4:-4] for f in files] == [
        f"{n:03d}{side}" for n in range(1, photos + 1) for side in (("R", "L") if n % 3 else ("",))]
    assert all(Image.open(io.BytesIO(f["buffer"])).width <= 800 for f in files)


def test_attachment_names_are_known_without_encoding_a_jpeg(tmp_path, monkeypatch):
    """The Chat route counts its files against the upload window before attaching any."""
    from app.source_bundle import source_image_names

    spread, single = spread_at(tmp_path), spread_at(tmp_path, (800, 1200), None)
    pages = [{"page_number": 2, "image_path": str(single)}, {"page_number": 1, "image_path": str(spread)}]
    expected = [f["name"] for f in source_bundle(pages)]
    assert expected == ["page001R.jpg", "page001L.jpg", "page002.jpg"]
    monkeypatch.setattr(Image.Image, "save", lambda *a, **k: pytest.fail("counting must not encode"))
    assert source_image_names(pages) == expected

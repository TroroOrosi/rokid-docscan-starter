"""Complete original page images with stable capture-order labels; no OCR text."""
from __future__ import annotations

import io
import itertools
import math

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps


MAX_IMAGE_BYTES = 20 * 1024 * 1024
# The first that fits MAX_IMAGE_BYTES is sent; resolution is never reduced.
JPEG_QUALITIES = (92, 85, 75)


def _payload(name, mime, data):
    return {"name": name, "mimeType": mime, "buffer": data}


def _readable(photo: Image.Image) -> Image.Image:
    """Stretch the levels and trim what surrounds the paper. Adds no detail.

    Glasses photos arrive dark and include the desk. On 2026-09-22 the whole-frame
    p99 was 83. The paper is the bright, unsaturated region. A 4% margin keeps
    its darker, vignetted edges. The stored page image is never changed.
    """
    photo = ImageOps.autocontrast(photo, cutoff=(1, 1))
    if min(photo.size) < 400:
        return photo
    small = photo.reduce(8)
    _, saturation, value = small.convert("HSV").split()
    histogram, seen = value.histogram(), 0
    for level, count in enumerate(histogram):
        seen += count
        if seen >= small.width * small.height * 0.99:
            break
    bright = value.point(lambda x, t=level * 0.55: 255 if x > t else 0)
    plain = saturation.point(lambda x: 255 if x < 70 else 0)
    mask = ImageChops.multiply(bright, plain).filter(ImageFilter.MinFilter(7)).filter(ImageFilter.MaxFilter(7))
    box = mask.getbbox()
    if not box:
        return photo
    # ponytail: brightness/saturation heuristic. On a white desk the box covers too
    # much and the full frame is kept. Use a page-edge detector if that happens often.
    mx, my = small.width * 0.04, small.height * 0.04
    box = (max(0, box[0] - mx), max(0, box[1] - my),
           min(small.width, box[2] + mx), min(small.height, box[3] + my))
    if not 0.15 <= (box[2] - box[0]) * (box[3] - box[1]) / (small.width * small.height) <= 0.9:
        return photo
    return photo.crop(tuple(min(int(c * 8), limit) for c, limit in
                            zip(box, (photo.width, photo.height, photo.width, photo.height))))


def _gutter(photo: Image.Image) -> int | None:
    """x of the fold of a two-page spread, or None to keep the photo whole.

    The darkest column band (shadow and fold) within 15% of the paper box centre;
    the trimmed photo is that box plus an even margin. A column's median over the
    middle half ignores most text, and the blur thins a text column more than a
    fold. A fold must lie 40 below the paper within 4% on each side, and 15 below
    every other column in the window, which a repeating text column never is.
    Glasses photos on this PC, 2026-09-30: the two 4b folds 56 and 75 deep, 27
    below the rest; any other landscape photo at most 32 deep.
    """
    if photo.width <= photo.height or min(photo.size) < 400:
        return None
    gray = photo.convert("L")
    gray.thumbnail((320, 320))
    gray = gray.filter(ImageFilter.BoxBlur(1))
    w, h = gray.size
    band = gray.crop((0, h // 4, w, h - h // 4)).tobytes()
    column = [sorted(band[x::w])[len(band) // w // 2] for x in range(w)]
    lo, hi, near = round(w * 0.35), round(w * 0.65), round(w * 0.04)
    x = min(range(lo, hi), key=column.__getitem__)
    depth = min(max(column[x - near:x]), max(column[x + 1:x + near + 1])) - column[x]
    runner_up = min(column[i] for i in range(lo, hi) if abs(i - x) > near)
    # ponytail: fixed levels. A flat, evenly lit spread with only a thin fold line
    # (32 deep on 2026-09-16) stays whole, as before; a line detector would split it.
    if depth < 40 or runner_up - column[x] < 15:
        return None
    return round((x + 0.5) * photo.width / w)


def _page_images(pages: list[dict]):
    """(label, readable image) in capture order; a spread is its right page, then its left."""
    for page in pages:
        number = f"{page['page_number']:03d}"
        try:
            with Image.open(page["image_path"]) as source:
                photo = _readable(source.convert("RGB"))
        except (OSError, TypeError) as error:
            raise ValueError(f"Page {number} image unavailable") from error
        x = _gutter(photo)
        if x is None:
            yield number, photo
            continue
        with photo:  # Japanese booklets read right to left
            right, left = photo.crop((x, 0, photo.width, photo.height)), photo.crop((0, 0, x, photo.height))
        yield f"{number} R", right
        yield f"{number} L", left


def source_bundle(pages: list[dict], *, max_files: int = 20) -> list[dict]:
    """Keep all source pages, including shared material that OCR did not identify.

    Merging keeps source resolution. Oversized PNGs use high-quality JPEG. It cannot prevent
    a model from resizing the image internally. Missing selected images fail closed.
    """
    # Images only. A PDF is not an option: outside Enterprise, ChatGPT reads a
    # PDF's text layer and discards its images (OpenAI File Uploads FAQ), and a
    # photographed page has no text layer.
    if not 1 <= max_files <= 20:
        raise ValueError("invalid attachment budget")
    numbers = [p["page_number"] for p in pages]
    if any(type(n) is not int or n < 1 for n in numbers) or len(set(numbers)) != len(numbers):
        raise ValueError("page numbers must be unique positive integers")
    selected = sorted(pages, key=lambda page: page["page_number"])
    if not selected:
        raise ValueError("no source pages")
    # One image per page: fitting a whole spread in 768 px blurred its text in
    # run 4b (2026-09-30); one page at 768 px wide read clearly. Counted first,
    # so each photo is decoded twice, but no more than a group is held at once.
    count = sum(1 for _ in _page_images(selected))
    files = []
    group_size = max(1, math.ceil(count / max_files))
    if group_size > 3:
        raise ValueError("too many pages for a complete image bundle")
    parts = _page_images(selected)
    while group := list(itertools.islice(parts, group_size)):
        try:
            width = max(photo.width for _, photo in group)
            header = max(24, width // 24)
            with Image.new("RGB", (width, sum(p.height + header for _, p in group)), "white") as sheet:
                y = 0
                for text, photo in group:
                    with Image.new("RGB", (100, 20), "white") as label:
                        ImageDraw.Draw(label).text((2, 2), f"Page {text}", fill="black")
                        label.thumbnail((width, header))
                        label_width = min(width, header * 5)
                        with label.resize((label_width, header)) as scaled:
                            sheet.paste(scaled, (0, y))
                    sheet.paste(photo, (0, y + header))
                    y += photo.height + header
                # Full resolution, JPEG. PNG was 227 MB for 20 stored pages,
                # 303 MB as base64, over the 100 MB DevTools receive buffer;
                # quality 92 averages about 3.45 MB a page.
                for quality in JPEG_QUALITIES:
                    output = io.BytesIO()
                    sheet.save(output, format="JPEG", quality=quality)
                    data = output.getvalue()
                    if len(data) <= MAX_IMAGE_BYTES:
                        break
                extension, mime = ".jpg", "image/jpeg"
            if len(data) > MAX_IMAGE_BYTES:
                raise ValueError("image attachment exceeds 20MB; use individual page images")
            name = "page" + "-".join(text.replace(" ", "") for text, _ in group) + extension
            files.append(_payload(name, mime, data))
        finally:
            for _, photo in group:
                photo.close()
    return files

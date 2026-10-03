"""Complete original page images with stable capture-order labels; no OCR text."""
from __future__ import annotations

import io

from PIL import Image, ImageChops, ImageFilter, ImageOps


MAX_IMAGE_BYTES = 20 * 1024 * 1024
# The first that fits MAX_IMAGE_BYTES is sent; resolution is never reduced.
JPEG_QUALITIES = (92, 85, 75)


def _payload(name, mime, data):
    return {"name": name, "mimeType": mime, "buffer": data}


def _readable(photo: Image.Image) -> Image.Image:
    """Lift levels without clipping the dark paper edges or cutting any pixels."""
    return ImageOps.autocontrast(photo)


def shadow_corrected(photo: Image.Image) -> Image.Image:
    """A full-frame comparison candidate; originals and the default stay intact.

    ponytail: a blurred background also contains large diagrams. Compare against
    the original before choosing it; use measured page masks if diagrams lose contrast.
    """
    background = photo.filter(ImageFilter.BoxBlur(max(1, min(photo.size) // 24)))
    return ImageOps.autocontrast(ImageChops.subtract(photo, background, offset=235))


def _gutter(photo: Image.Image) -> int | None:
    """x of the fold of a two-page spread, or None to keep the photo whole.

    The darkest column band (shadow and fold) within 15% of the paper box centre;
    A column's median over the
    middle half ignores most text, and the blur thins a text column more than a
    fold. A fold must lie 40 below the paper within 4% on each side, and 15 below
    every other column in the window, which a repeating text column never is.
    Glasses photos on this PC, 2026-09-30: the two 4b folds 56 and 75 deep, 27
    below the rest; any other landscape photo at most 32 deep.
    """
    if min(photo.size) < 400:
        return None
    small = ImageOps.autocontrast(photo, cutoff=(1, 1))
    small.thumbnail((320, 320))
    _, saturation, value = small.convert("HSV").split()
    histogram, seen = value.histogram(), 0
    for level, count in enumerate(histogram):
        seen += count
        if seen >= small.width * small.height * 0.99:
            break
    mask = ImageChops.multiply(value.point(lambda x: 255 if x > level * 0.55 else 0),
                               saturation.point(lambda x: 255 if x < 70 else 0))
    mask = mask.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.MaxFilter(5))
    box = mask.getbbox()
    if not box or box[2] - box[0] <= box[3] - box[1]:
        return None
    # The paper box locates the fold only: it never cuts dark page edges out of
    # the evidence. A landscape booklet can occupy part of a portrait photo.
    gray = small.convert("L").crop(box)
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
    return round((box[0] + x + 0.5) * photo.width / small.width)


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


def source_images(pages: list[dict]):
    """One full-resolution JPEG per page, in order; no booklet-size limit."""
    numbers = [p["page_number"] for p in pages]
    if any(type(n) is not int or n < 1 for n in numbers) or len(set(numbers)) != len(numbers):
        raise ValueError("page numbers must be unique positive integers")
    selected = sorted(pages, key=lambda page: page["page_number"])
    if not selected:
        raise ValueError("no source pages")
    for label, photo in _page_images(selected):
        with photo:
            for quality in JPEG_QUALITIES:
                output = io.BytesIO()
                photo.save(output, format="JPEG", quality=quality)
                data = output.getvalue()
                if len(data) <= MAX_IMAGE_BYTES:
                    break
            if len(data) > MAX_IMAGE_BYTES:
                raise ValueError(f"Page {label} image attachment exceeds 20MB")
        yield _payload("page" + label.replace(" ", "") + ".jpg", "image/jpeg", data)


def source_bundle(pages: list[dict]) -> list[dict]:
    """Materialize source_images for PC inspection; the phone streams one batch."""
    return list(source_images(pages))

"""Complete original page images with stable capture-order labels; no OCR text."""
from __future__ import annotations

import io
import math

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


def _paper_mask(photo: Image.Image, floor: float = 0.55) -> tuple[Image.Image, Image.Image]:
    """(thumbnail, mask of bright unsaturated paper): brighter than ``floor`` of the
    frame's 99th percentile, thin structures removed."""
    small = ImageOps.autocontrast(photo, cutoff=(1, 1))
    small.thumbnail((320, 320))
    _, saturation, value = small.convert("HSV").split()
    histogram, seen = value.histogram(), 0
    for level, count in enumerate(histogram):
        seen += count
        if seen >= small.width * small.height * 0.99:
            break
    mask = ImageChops.multiply(value.point(lambda x: 255 if x > level * floor else 0),
                               saturation.point(lambda x: 255 if x < 70 else 0))
    return small, mask.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.MaxFilter(5))


def _largest_box(mask: Image.Image) -> tuple[int, int, int, int] | None:
    """Bounding box of the largest connected white region, by runs joined row to row."""
    w, h = mask.size
    data = mask.tobytes()
    parent: list[int] = []
    runs: list[tuple[int, int, int, int]] = []  # label, y, start, end

    def find(i):
        while parent[i] != i:
            parent[i] = i = parent[parent[i]]
        return i

    above: list[tuple[int, int, int]] = []
    for y in range(h):
        row, current, x = data[y * w:(y + 1) * w], [], 0
        while (x := row.find(b"\xff", x)) != -1:
            end = row.find(b"\x00", x)
            end = w if end == -1 else end
            label = len(parent)
            parent.append(label)
            for start, stop, other in above:
                if start < end and stop > x:
                    parent[find(other)] = find(label)
            current.append((x, end, label))
            runs.append((label, y, x, end))
            x = end
        above = current
    regions: dict[int, list[int]] = {}
    for label, y, x, end in runs:
        box = regions.setdefault(find(label), [0, x, y, end, y + 1])
        box[:] = [box[0] + end - x, min(box[1], x), min(box[2], y), max(box[3], end), y + 1]
    return tuple(max(regions.values())[1:]) if regions else None


# Each side of the paper box is widened by this share of the frame's short side.
CROP_MARGIN = 0.04


def _paper_crop(photo: Image.Image) -> tuple[int, int, int, int] | None:
    """The paper and a margin, or None to send the whole frame.

    ChatGPT web fits an attachment's long edge to 2048 px (observed 2026-09-30).
    A sheet is under half of the glasses' frame, so the desk used up the pixels
    the text needed. The box is the largest bright unsaturated region. It is used
    only when all five hold; anything else keeps the frame as it was sent before:

    - it covers at least 15% of the frame;
    - it touches at most one frame side (a sheet leaving the frame on two is
      larger than the frame, or mostly outside it);
    - the same region found with the brightness floor lowered from 0.55 to 0.25
      still lies inside the margin (a shadow across the sheet moves that box,
      and the lit part alone looks like a smaller sheet);
    - at most 5% of everything paper-like lies outside the crop (a ruled box on a
      page that fills the frame is not the paper; the print around it is);
    - the crop keeps at most 65% of the frame (more saves little, and a page that
      fills the frame can continue behind a ruled line a few pixels from its edge).

    Every real 4032x3024 photo on this PC, 2026-11-10 (27 distinct, looked at one
    by one): 23 hold a whole spread and their boxes cover 25% to 49%. 14 of the
    16 taken by glassdoc are cropped and none loses paper (at most 3.1% paper-like
    outside, at most 50% of the frame kept); 2 stay whole because a keyboard beside the sheet joins it at the
    lower floor, and so do all 7 from the glasses' own camera app, whose bright
    desk reads as paper. The other 4 are refused, each by at least two of the
    conditions: a spread larger than the frame with a shadow over its lower half,
    a sheet partly lit in a corner (6% of the frame, cut by the box) and two
    frames whose brightest region is a wall (11% to 71% paper-like outside). The
    fold is looked for after the crop: a cropped spread sent whole is what the
    model could not read on 2026-09-30 (commit 1134404).
    """
    if min(photo.size) < 400:
        return None
    small, mask = _paper_mask(photo)
    box, loose = _largest_box(mask), _largest_box(_paper_mask(photo, 0.25)[1])
    if box is None or loose is None:
        return None
    w, h = small.size
    margin = CROP_MARGIN * min(w, h)
    crop = (box[0] - margin, box[1] - margin, box[2] + margin, box[3] + margin)
    if ((box[2] - box[0]) * (box[3] - box[1]) < 0.15 * w * h
            or (box[0] <= 1) + (box[1] <= 1) + (box[2] >= w - 1) + (box[3] >= h - 1) > 1
            or loose[0] < crop[0] or loose[1] < crop[1] or loose[2] > crop[2] or loose[3] > crop[3]):
        return None
    kept = (max(0, math.floor(crop[0])), max(0, math.floor(crop[1])),
            min(w, math.ceil(crop[2])), min(h, math.ceil(crop[3])))
    if (mask.crop(kept).histogram()[255] < 0.95 * mask.histogram()[255]
            or (kept[2] - kept[0]) * (kept[3] - kept[1]) > 0.65 * w * h):
        return None
    scale = photo.width / w
    return (max(0, round(crop[0] * scale)), max(0, round(crop[1] * scale)),
            min(photo.width, round(crop[2] * scale)), min(photo.height, round(crop[3] * scale)))


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
    small, mask = _paper_mask(photo)
    box = mask.getbbox()
    if not box or box[2] - box[0] <= box[3] - box[1]:
        return None
    # The paper box locates the fold only. A landscape booklet can occupy part of
    # a portrait photo.
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
    """(label, readable image) in capture order: the paper when its box is certain, else
    the frame; a spread is its right page, then its left."""
    for page in pages:
        number = f"{page['page_number']:03d}"
        try:
            with Image.open(page["image_path"]) as source:
                photo = _readable(source.convert("RGB"))
        except (OSError, TypeError) as error:
            raise ValueError(f"Page {number} image unavailable") from error
        box = _paper_crop(photo)
        if box is not None:
            with photo:
                photo = photo.crop(box)
        x = _gutter(photo)
        if x is None:
            yield number, photo
            continue
        with photo:  # Japanese booklets read right to left
            right, left = photo.crop((x, 0, photo.width, photo.height)), photo.crop((0, 0, x, photo.height))
        yield f"{number} R", right
        yield f"{number} L", left


def _ordered(pages: list[dict]) -> list[dict]:
    numbers = [p["page_number"] for p in pages]
    if any(type(n) is not int or n < 1 for n in numbers) or len(set(numbers)) != len(numbers):
        raise ValueError("page numbers must be unique positive integers")
    if not pages:
        raise ValueError("no source pages")
    return sorted(pages, key=lambda page: page["page_number"])


def _name(label: str) -> str:
    return "page" + label.replace(" ", "") + ".jpg"


def source_image_names(pages: list[dict]) -> list[str]:
    """The names source_images will yield, without encoding a JPEG.

    A spread is two files, so the count is known only after each photo is
    decoded; the caller compares it with the plan's upload window before
    anything is attached.

    ponytail: every page is decoded a second time (0.24 s per photo on the PC,
    2026-11-10; the phone is unmeasured). Skip the pass when two files per page
    already fit the window, if the phone shows the delay matters.
    """
    names = []
    for label, photo in _page_images(_ordered(pages)):
        photo.close()
        names.append(_name(label))
    return names


def source_images(pages: list[dict]):
    """One full-resolution colour JPEG per page; no booklet-size limit."""
    for label, photo in _page_images(_ordered(pages)):
        with photo:
            for quality in JPEG_QUALITIES:
                output = io.BytesIO()
                # Keep fine coloured labels and graph lines at native chroma
                # resolution; the encoder's default subsampling blends them.
                photo.save(output, format="JPEG", quality=quality, subsampling=0)
                data = output.getvalue()
                if len(data) <= MAX_IMAGE_BYTES:
                    break
            if len(data) > MAX_IMAGE_BYTES:
                raise ValueError(f"Page {label} image attachment exceeds 20MB")
        yield _payload(_name(label), "image/jpeg", data)


def source_bundle(pages: list[dict]) -> list[dict]:
    """Materialize source_images for PC inspection; the phone streams one batch."""
    return list(source_images(pages))

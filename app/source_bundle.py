"""Complete original page images with stable capture-order labels; no OCR text."""
from __future__ import annotations

import io
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from .page_pdf import images_to_pdf

MAX_IMAGE_BYTES = 20 * 1024 * 1024


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


def source_bundle(pages: list[dict], *, mode: str = "images",
                  max_files: int = 20) -> list[dict]:
    """Keep all source pages, including shared material that OCR did not identify.

    Merging keeps source resolution. Oversized PNGs use high-quality JPEG. It cannot prevent
    a model from resizing the image internally. Missing selected images fail closed.
    """
    # Old settings remain readable, but cannot re-enable OCR-first input.
    if mode not in ("images", "ocr-images", "merged-images", "pdf") or not 1 <= max_files <= 20:
        raise ValueError("invalid source bundle mode or attachment budget")
    numbers = [p["page_number"] for p in pages]
    if any(type(n) is not int or n < 1 for n in numbers) or len(set(numbers)) != len(numbers):
        raise ValueError("page numbers must be unique positive integers")
    selected = sorted(pages, key=lambda page: page["page_number"])
    if not selected:
        raise ValueError("no source pages")
    files = []
    if mode == "pdf":
        try:
            raw = [Path(p["image_path"]).read_bytes() for p in selected]
        except (OSError, TypeError) as error:
            raise ValueError("PDF source image missing") from error
        return [_payload("pages.pdf", "application/pdf", images_to_pdf(raw))]
    group_size = max(1, math.ceil(len(selected) / max_files))
    if group_size > 3:
        raise ValueError("too many pages for a complete image bundle")
    for start in range(0, len(selected), group_size):
        group = selected[start:start + group_size]
        images = []
        try:
            for page in group:
                try:
                    with Image.open(page["image_path"]) as source:
                        images.append(_readable(source.convert("RGB")))
                except (OSError, TypeError) as error:
                    raise ValueError(f"Page {page['page_number']:03d} image unavailable") from error
            width = max(i.width for i in images)
            header = max(24, width // 24)
            with Image.new("RGB", (width, sum(i.height + header for i in images)), "white") as sheet:
                y = 0
                for page, photo in zip(group, images):
                    with Image.new("RGB", (100, 20), "white") as label:
                        ImageDraw.Draw(label).text((2, 2), f"Page {page['page_number']:03d}", fill="black")
                        label.thumbnail((width, header))
                        label_width = min(width, header * 5)
                        with label.resize((label_width, header)) as scaled:
                            sheet.paste(scaled, (0, y))
                    sheet.paste(photo, (0, y + header))
                    y += photo.height + header
                output = io.BytesIO()
                sheet.save(output, format="PNG")
                data = output.getvalue()
                extension, mime = ".png", "image/png"
                if len(data) > MAX_IMAGE_BYTES:
                    for quality in (98, 95, 92):
                        output = io.BytesIO()
                        sheet.save(output, format="JPEG", quality=quality, subsampling=0)
                        data = output.getvalue()
                        extension, mime = ".jpg", "image/jpeg"
                        if len(data) <= MAX_IMAGE_BYTES:
                            break
            if len(data) > MAX_IMAGE_BYTES:
                raise ValueError("image attachment exceeds 20MB; use individual page images")
            name = "page" + "-".join(f"{p['page_number']:03d}" for p in group) + extension
            files.append(_payload(name, mime, data))
        finally:
            for photo in images:
                photo.close()
    return files

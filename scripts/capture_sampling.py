"""Bounded saved-photo measurements; no camera, model, network or acceptance gate."""
from __future__ import annotations

import math

from PIL import Image

# Keep in agreement with JapaneseOcr.sampleSizeFor; this is an estimate of input
# geometry, not an implementation of Android's decoder or ML Kit recognition.
OCR_MIN_EDGE = 1200
DETAIL_EDGE = 1024
MAX_DETAILS = 5


# Official Rokid Glasses specification, checked 2026-09-17; not measured on this device.
# See docs/rokid-capture-research.md. No range sensor or AF is inferred here.
ROKID_NEAR_CM = 34.0


def capture_distance(distance: object = None) -> dict:
    result = {"official_near_limit_cm": ROKID_NEAR_CM, "operator_distance_cm": None,
              "assessment": "not_measured", "basis": "published_spec_not_device_calibration"}
    if distance is not None:
        if (isinstance(distance, bool) or not isinstance(distance, (int, float))
                or not math.isfinite(distance) or distance <= 0):
            raise ValueError("distance must be a finite positive measurement in centimetres")
        result.update({"operator_distance_cm": distance,
                       "assessment": "below_official_near_limit" if distance < ROKID_NEAR_CM
                       else "not_below_limit_not_a_pass"})
    return result


def ocr_sampling(width: int, height: int, rotation: int, glyph: object = None) -> dict:
    sample = 1
    while max(width, height) // (sample * 2) >= OCR_MIN_EDGE:
        sample *= 2
    size = [math.ceil(width / sample), math.ceil(height / sample)]
    upright = [width, height]
    if rotation in (90, 270):
        size.reverse()
        upright.reverse()
    result = {"sample_size": sample, "estimated_upright_size": size,
              "estimated_rgb565_bytes": size[0] * size[1] * 2,
              "glyph_assessment": "not_measured"}
    if glyph is not None:
        if not isinstance(glyph, (list, tuple)) or len(glyph) != 2:
            raise ValueError("glyph pixels needs width and height of one actual glyph")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or
               not math.isfinite(v) or v <= 0 or v > bound for v, bound in zip(glyph, upright)):
            raise ValueError("glyph pixels must be finite, positive and within the upright image")
        scaled = [v / sample for v in glyph]
        result.update({"source_glyph_pixels": list(glyph), "estimated_glyph_pixels": scaled,
                       "glyph_assessment": "below_16px_guidance" if min(scaled) < 16
                       else "not_below_16px_not_a_pass"})
    return result


def detail_boxes(details: object, width: int, height: int) -> list[tuple[int, int, int, int]]:
    if details is None:
        return []
    if not isinstance(details, (list, tuple)) or not 1 <= len(details) <= MAX_DETAILS:
        raise ValueError("details needs 1..5 upright normalized rectangles")
    boxes = []
    for rectangle in details:
        if not isinstance(rectangle, (list, tuple)) or len(rectangle) != 4:
            raise ValueError("detail rectangle needs left,top,right,bottom")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or
               not math.isfinite(v) or not 0 <= v <= 1 for v in rectangle):
            raise ValueError("detail coordinates must be finite numbers in 0..1")
        left, top, right, bottom = rectangle
        if not left < right or not top < bottom:
            raise ValueError("detail rectangle must have positive width and height")
        box = (math.floor(left * width), math.floor(top * height),
               math.ceil(right * width), math.ceil(bottom * height))
        if box[2] - box[0] > DETAIL_EDGE or box[3] - box[1] > DETAIL_EDGE:
            raise ValueError("each original-scale detail must fit within 1024x1024 pixels")
        boxes.append(box)
    return boxes


def photographic_exif(image: Image.Image) -> dict[str, float]:
    """Allowlist numbers only. Never export GPS, names, comments or serials."""
    output = {}
    try:
        exif = image.getexif()
        values = exif.get_ifd(34665) if 34665 in exif else exif
        for tag, name in ((33434, "exposure_seconds"), (33437, "f_number"),
                          (34855, "iso"), (37386, "focal_length_mm")):
            raw = values.get(tag)
            # Reject strings and bytes even if float() could parse them.
            if raw is None or isinstance(raw, (str, bytes, bool, list, tuple)):
                continue
            try:
                number = float(raw)
                if math.isfinite(number) and number > 0:
                    output[name] = number
            except (TypeError, ValueError, OverflowError, ZeroDivisionError):
                continue
    except (OSError, ValueError, TypeError, KeyError, SyntaxError):
        # Optional/corrupt EXIF cannot certify or invalidate readable pixel data.
        pass
    return output

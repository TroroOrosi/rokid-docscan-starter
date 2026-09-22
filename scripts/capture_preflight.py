"""Inspect saved capture images offline; never capture, upload, OCR or edit originals.

Run from the repository root: python -m scripts.capture_preflight IMAGE --out DIR
--rotation 270. Use 0 for already-normalized server PNGs. Optional --corners is
JSON containing TL, TR, BR, BL normalized coordinates in the UPRIGHT image.
Output is diagnostic evidence, never a physical/recognition acceptance result.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import uuid
import warnings
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from scripts.capture_sampling import capture_distance, detail_boxes, ocr_sampling, photographic_exif

MAX_BYTES = 16 * 1024 * 1024
MAX_PIXELS = 25_000_000
PREVIEW_EDGE = 1280
PAPER_EDGE = 2560


def _upright(image: Image.Image, rotation: int) -> Image.Image:
    method = {90: Image.Transpose.ROTATE_270, 180: Image.Transpose.ROTATE_180,
              270: Image.Transpose.ROTATE_90}.get(rotation)
    return image.copy() if method is None else image.transpose(method)


def _gray(image: Image.Image) -> Image.Image:
    # The HUD's green-channel luminance, not Pillow's default RGB->L weights.
    return image.convert("L", (.213, .715, .072, 0))


def _levels(image: Image.Image) -> tuple[int, int, int]:
    histogram = _gray(image).histogram()
    total = sum(histogram)
    def percentile(fraction: float) -> int:
        threshold = total * fraction
        count = 0
        for value, frequency in enumerate(histogram):
            count += frequency
            if count > threshold:
                return value
        return 255
    return percentile(.01), percentile(.5), percentile(.99)


def _readable(image: Image.Image) -> Image.Image:
    low, _, high = _levels(image)
    if high - low < 16:
        low, high = 0, 255
    table = [max(0, min(255, round((value - low) * 255 / (high - low))))
             for value in range(256)]
    return _gray(image).point(table)


def _validate_corners(corners: object) -> tuple[list[tuple[float, float]], float]:
    try:
        if not isinstance(corners, (list, tuple)) or len(corners) != 4:
            raise ValueError("four corners are required")
        points = []
        for point in corners:
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise ValueError("each corner needs x,y")
            x, y = float(point[0]), float(point[1])
            if not math.isfinite(x) or not math.isfinite(y) or not (0 <= x <= 1 and 0 <= y <= 1):
                raise ValueError("corner coordinates must be finite and within 0..1")
            points.append((x, y))
    except (TypeError, OverflowError) as error:
        raise ValueError("invalid corners") from error
    # Positive, convex winding in image coordinates (TL,TR,BR,BL); reject crossings.
    for index in range(4):
        a, b, c = points[index], points[(index+1) % 4], points[(index+2) % 4]
        cross = (b[0]-a[0])*(c[1]-b[1]) - (b[1]-a[1])*(c[0]-b[0])
        if cross <= 1e-8:
            raise ValueError("corners must form a convex TL,TR,BR,BL quadrilateral")
    area = sum(points[i][0]*points[(i+1) % 4][1] - points[(i+1) % 4][0]*points[i][1]
               for i in range(4)) / 2
    if area < .001:
        raise ValueError("paper region is too small for a reliable transform")
    return points, area


def _solve(matrix: list[list[float]]) -> list[float]:
    """Pivoted elimination of the small 8x8 inverse-perspective system."""
    for column in range(8):
        pivot = max(range(column, 8), key=lambda row: abs(matrix[row][column]))
        if abs(matrix[pivot][column]) < 1e-10:
            raise ValueError("degenerate paper transform")
        matrix[column], matrix[pivot] = matrix[pivot], matrix[column]
        scale = matrix[column][column]
        matrix[column] = [value / scale for value in matrix[column]]
        for row in range(8):
            if row != column:
                factor = matrix[row][column]
                matrix[row] = [a - factor*b for a, b in zip(matrix[row], matrix[column])]
    return [row[-1] for row in matrix]


def _rectify(image: Image.Image, points: list[tuple[float, float]]) -> Image.Image:
    source = [(x*(image.width-1), y*(image.height-1)) for x, y in points]
    width = max(math.dist(source[0], source[1]), math.dist(source[3], source[2]))
    height = max(math.dist(source[0], source[3]), math.dist(source[1], source[2]))
    reduction = max(1., max(width, height) / PAPER_EDGE)
    width, height = max(2, round(width/reduction)), max(2, round(height/reduction))
    target = [(0, 0), (width-1, 0), (width-1, height-1), (0, height-1)]
    matrix = []
    for (u, v), (x, y) in zip(target, source):
        matrix.extend([[u, v, 1, 0, 0, 0, -x*u, -x*v, x],
                       [0, 0, 0, u, v, 1, -y*u, -y*v, y]])
    return image.transform((width, height), Image.Transform.PERSPECTIVE,
                           _solve(matrix), Image.Resampling.BICUBIC)


def inspect_capture(source: Path, output_root: Path, *, rotation: int,
                    corners: object = None, details: object = None,
                    glyph_pixels: object = None, distance_cm: object = None) -> Path:
    """Create a fresh local report directory, returning report.json's path.

    Only explicit corners/details produce region derivatives. No guessed
    edges, automatic rotation, acceptance score, original write or network I/O.
    Android RGB565 memory is an estimate, not a measurement of whole-process RSS.
    """
    if rotation not in (0, 90, 180, 270):
        raise ValueError("rotation must be 0, 90, 180 or 270")
    distance = capture_distance(distance_cm)
    points, area = _validate_corners(corners) if corners is not None else (None, None)
    source, output_root = Path(source), Path(output_root)
    with source.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if not data or len(data) > MAX_BYTES:
        raise ValueError("image byte limit exceeded or empty image")
    digest = hashlib.sha256(data).hexdigest()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as opened:
                if opened.format not in ("JPEG", "PNG") or getattr(opened, "n_frames", 1) != 1:
                    raise ValueError("only a single JPEG or PNG image is supported")
                width, height = opened.size
                if width < 2 or height < 2 or width * height > MAX_PIXELS:
                    raise ValueError("image pixel limit exceeded or dimensions invalid")
                exif_orientation = opened.getexif().get(274, 1)
                if not isinstance(exif_orientation, int) or exif_orientation not in range(1, 9):
                    exif_orientation = None
                photo_exif = photographic_exif(opened)
                upright_size = (width, height) if rotation in (0, 180) else (height, width)
                boxes = detail_boxes(details, *upright_size)
                sampling = ocr_sampling(width, height, rotation, glyph_pixels)
                sample = 1
                while max(width, height) // sample > PREVIEW_EDGE:
                    sample *= 2
                # JPEG draft avoids a full 12MP decode for preview-only diagnostics.
                preview_size = (math.ceil(width/sample), math.ceil(height/sample))
                if points is None and not boxes:
                    opened.draft("RGB", preview_size)
                rgb = opened.convert("RGB")
                full = _upright(rgb, rotation)
                rgb.close()
    except (UnidentifiedImageError, Image.DecompressionBombError,
            Image.DecompressionBombWarning, OSError) as error:
        raise ValueError("invalid or oversized image") from error
    expected_preview = preview_size if rotation in (0, 180) else preview_size[::-1]
    preview = full.resize(expected_preview, Image.Resampling.LANCZOS)
    low, median, high = _levels(preview)
    flags = []
    if median < 32 or high < 64:
        flags.append("dark_frame")
    if high - low < 16:
        flags.append("low_tonal_range")
    if exif_orientation != 1:
        flags.append("exif_not_applied_explicit_rotation_only")
    report = {
        "schema": 2, "source_sha256": digest, "source_bytes": len(data),
        "source_size": [width, height], "rotation_clockwise": rotation,
        "exif_orientation": exif_orientation, "exif_applied": False,
        "photographic_exif": photo_exif, "ocr_sampling": sampling, "capture_distance": distance,
        "details": [{"file": f"detail-{index}.png", "box_upright_pixels": list(box),
                     "scale": "source_pixels_1_to_1"} for index, box in enumerate(boxes, 1)],
        "upright_size": [width, height] if rotation in (0, 180) else [height, width],
        "preview_size": list(preview.size), "android_sample_size": sample,
        "estimated_android_rgb565_bytes": preview.width * preview.height * 2,
        "luminance_p01_p50_p99": [low, median, high], "warnings": flags,
        "paper_corners": "not_identified" if points is None else "operator_supplied",
        "paper_area_fraction": area, "corners_upright_normalized": points,
        "ocr": "not_run", "acceptance": "not_evaluated",
        "notes": ["Warning thresholds are uncalibrated; they are not page-quality verdicts.",
                  "Display correction does not recover clipped, blurred or occluded text.",
                  "Preview approximates HUD luminance; native Canvas tests remain separate.",
                  "RGB565 bytes exclude camera buffers, rotation overlap, OCR and process memory.",
                  "OCR geometry estimates the current 1200-edge power-of-two policy, not accuracy.",
                  "Measure actual glyph pixels, not line/column pitch; 16px guidance is not a pass.",
                  "Explicit details/corners need a full decode on the PC; they do not run on glasses.",
                  "EXIF is optional and is not proof of the Camera2 request or a focus-distance limit."],
    }
    paper = _rectify(full, points) if points is not None else None
    crops = [full.crop(box) for box in boxes]
    full.close()
    # Validate before creating output; every run owns a new directory, never overwrites.
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / (digest[:12] + "-" + uuid.uuid4().hex[:12])
    output.mkdir()
    for index, crop in enumerate(crops, 1):
        # Crops may inherit the input metadata through Pillow's info dictionary.
        crop.info.clear()
        crop.save(output / f"detail-{index}.png")
        crop.close()
    preview.info.clear()
    preview.save(output / "source-preview.png")
    green = _readable(preview)
    blank = Image.new("L", preview.size, 0)
    display = Image.merge("RGB", (blank, green, blank))
    display.save(output / "display-preview.png")
    display.close()
    blank.close()
    green.close()
    preview.close()
    if paper is not None:
        report["rectified_size"] = list(paper.size)
        paper.info.clear()
        paper.save(output / "paper-rectified.png")
        readable = _readable(paper)
        readable.save(output / "paper-readable.png")
        readable.close()
        paper.close()
    report_path = output / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--rotation", type=int, choices=[0, 90, 180, 270], required=True)
    parser.add_argument("--corners", help="JSON: [[x,y],...] TL,TR,BR,BL on the upright image, 0..1")
    parser.add_argument("--details", help="JSON: 1..5 upright [left,top,right,bottom] rectangles; each <=1024px")
    parser.add_argument("--distance-cm", type=float,
                        help="operator-measured lens-to-page distance; not inferred from EXIF or pixels")
    parser.add_argument("--glyph-pixels", nargs=2, type=float, metavar=("WIDTH", "HEIGHT"),
                        help="actual glyph dimensions measured in upright original pixels, not column pitch")
    args = parser.parse_args(argv)
    try:
        points = json.loads(args.corners) if args.corners is not None else None
        details = json.loads(args.details) if args.details is not None else None
        report = inspect_capture(args.image, args.out, rotation=args.rotation, corners=points,
                                 details=details, glyph_pixels=args.glyph_pixels, distance_cm=args.distance_cm)
    except (ValueError, OSError) as error:
        parser.exit(2, f"capture preflight failed: {error}\n")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

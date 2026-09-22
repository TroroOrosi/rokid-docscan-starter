"""Build PC-only source-pixel packets. No OCR, network, or quality approval.

python -m scripts.capture_quality IMAGE --out DIR --rotation 270 --tone
Use rotation 0 for normalized server PNGs. Outputs remain local and private.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import shutil
import tempfile
import warnings
from contextlib import ExitStack
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from scripts.capture_geometry import detect_paper, focus_metrics, rectify
from scripts.capture_preflight import MAX_BYTES, MAX_PIXELS, PREVIEW_EDGE, _upright
from scripts.capture_sampling import capture_distance


def tile_boxes(width: int, height: int, *, edge: int = 1024, overlap: int = 64) -> list:
    if (any(type(v) is not int for v in (width, height, edge, overlap))
            or min(width, height) < 2 or width * height > MAX_PIXELS
            or not 256 <= edge <= 1536 or not 0 <= overlap <= edge // 4):
        raise ValueError("invalid dimensions, tile edge (256..1536), or overlap (0..edge/4)")
    def starts(size):
        positions = [0]
        while positions[-1] + edge < size:
            positions.append(positions[-1] + edge - overlap)
        return positions
    xs, ys = starts(width), starts(height)
    if len(xs) * len(ys) > 96:
        raise ValueError("packet exceeds 96 tiles")
    return [(x, y, min(x + edge, width), min(y + edge, height)) for y in ys for x in xs]


def measure_tile(image: Image.Image) -> dict:
    if min(image.size) < 1 or image.width * image.height > MAX_PIXELS:
        raise ValueError("invalid measurement dimensions")
    with image.convert("L") as gray:
        histogram = gray.histogram()
        values = gray.tobytes()
    total = len(values)
    def percentile(fraction):
        count = 0
        for level, frequency in enumerate(histogram):
            count += frequency
            if count > total * fraction:
                return level
        return 255
    width, height = image.size
    stride = max(1, math.ceil(math.sqrt((width - 1) * (height - 1) / 65536)))
    difference = count = 0
    for y in range(0, height - 1, stride):
        for x in range(0, width - 1, stride):
            i = y * width + x
            difference += abs(values[i] - values[i + 1]) + abs(values[i] - values[i + width])
            count += 2
    return {"luminance_p05_p50_p95": [percentile(p) for p in (.05, .5, .95)],
            "near_black_fraction": sum(histogram[:9]) / total,
            "near_white_fraction": sum(histogram[247:]) / total,
            "mean_adjacent_difference": difference / count if count else 0,
            "adjacent_sample_count": count,
            "focus": focus_metrics(image) if min(image.size) >= 2 else {
                "assessment": "insufficient_texture", "calibrated": False,
                "sample_count": 0, "laplacian_variance": None}}


def tone_candidate(image: Image.Image) -> tuple[Image.Image, dict]:
    with image.convert("L") as gray:
        histogram = gray.histogram()
    total, count, median = sum(histogram), 0, 0
    for level, frequency in enumerate(histogram):
        count += frequency
        if count > total / 2:
            median = level
            break
    occupied = [level for level, frequency in enumerate(histogram) if frequency]
    gamma = 1.0
    if occupied and occupied[-1] - occupied[0] >= 16 and 0 < median < 128:
        gamma = max(.6, min(1., math.log(.5) / math.log(median / 255)))
    table = [round(255 * (level / 255) ** gamma) for level in range(256)]
    with image.convert("RGB") as rgb:
        output = rgb.point(table * 3)
    output.info.clear()
    return output, {"method": "monotonic_rgb_gamma", "gamma": gamma,
                    "recovers_lost_detail": False}


def _save(image: Image.Image, output: Path, name: str) -> dict:
    image.info.clear()
    path = output / name
    image.save(path, format="PNG")
    return {"file": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def build_packet(source: Path, output_root: Path, *, rotation: int, edge: int = 1024,
                 overlap: int = 64, tone: bool = False, auto_rectify: bool = False,
                 layout: str = "unknown", corners: object = None,
                 distance_cm: object = None) -> Path:
    if type(rotation) is not int or rotation not in (0, 90, 180, 270):
        raise ValueError("rotation must be an explicit integer: 0/90/180/270")
    if layout not in ("single", "spread", "unknown"):
        raise ValueError("layout must be single/spread/unknown")
    if type(tone) is not bool or type(auto_rectify) is not bool:
        raise ValueError("tone and auto_rectify must be booleans")
    if auto_rectify and corners is not None:
        raise ValueError("auto_rectify and corners are mutually exclusive")
    distance = capture_distance(distance_cm)
    with Path(source).open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if not data or len(data) > MAX_BYTES:
        raise ValueError("image byte limit exceeded or empty image")
    digest = hashlib.sha256(data).hexdigest()
    with ExitStack() as buffers:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as opened:
                    if opened.format not in ("JPEG", "PNG") or getattr(opened, "n_frames", 1) != 1:
                        raise ValueError("only single-frame JPEG/PNG images are supported")
                    width, height = opened.size
                    upright_size = (width, height) if rotation in (0, 180) else (height, width)
                    boxes = tile_boxes(*upright_size, edge=edge, overlap=overlap)
                    # No draft/downsample or EXIF transpose: tiles must retain every source pixel.
                    with opened.convert("RGB") as rgb:
                        full = buffers.enter_context(_upright(rgb, rotation))
        except (UnidentifiedImageError, Image.DecompressionBombWarning,
                Image.DecompressionBombError, OSError) as error:
            raise ValueError("invalid or oversized image") from error
        detection = detect_paper(full, layout=layout) if auto_rectify else None
        points = detection["corners_upright_normalized"] if detection else corners
        corrected = geometry = None
        if points is not None:
            corrected, geometry = rectify(full, points)
            buffers.enter_context(corrected)
        report = {"schema": 2, "source_sha256": digest, "source_bytes": len(data),
                  "source_size": [width, height], "rotation_clockwise": rotation,
                  "upright_size": list(full.size), "exif_applied": False,
                  "layout": layout, "capture_distance": distance, "source_metrics": measure_tile(full),
                  "decision": "hold", "auto_registration_allowed": False,
                  "paper_completeness": "unknown", "semantic_coverage": "unknown",
                  "ocr": "not_run", "paper_detection": detection, "rectified": None, "tiles": []}
        root = Path(output_root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        output = Path(tempfile.mkdtemp(prefix=digest[:12] + "-", dir=root))
        try:
            with full.copy() as overview:
                overview.thumbnail((PREVIEW_EDGE, PREVIEW_EDGE), Image.Resampling.LANCZOS)
                report["overview"] = _save(overview, output, "overview.png")
            for index, box in enumerate(boxes, 1):
                with full.crop(box) as tile:
                    entry = dict(_save(tile, output, f"tile-{index:03d}.png"),
                                 box_upright_pixels=list(box), scale="source_pixels_1_to_1",
                                 metrics=measure_tile(tile))
                    if tone:
                        candidate, correction = tone_candidate(tile)
                        with candidate:
                            entry["tone"] = dict(correction, **_save(candidate, output, f"tile-{index:03d}-tone.png"))
                    report["tiles"].append(entry)
            if corrected is not None:
                report["rectified"] = dict(geometry, **_save(corrected, output, "paper-rectified.png"))
            path = output / "report.json"
            path.write_text(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
            return path
        except BaseException:
            # Only this call's fresh directory is owned; never delete previous packets or sources.
            if output.resolve().parent == root and not output.is_symlink():
                shutil.rmtree(output)
            raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--rotation", type=int, choices=(0, 90, 180, 270), required=True)
    parser.add_argument("--edge", type=int, default=1024)
    parser.add_argument("--overlap", type=int, default=64)
    parser.add_argument("--tone", action="store_true")
    geometry = parser.add_mutually_exclusive_group()
    geometry.add_argument("--auto-rectify", action="store_true")
    geometry.add_argument("--corners", help="JSON: upright TL,TR,BR,BL coordinates in 0..1")
    parser.add_argument("--layout", choices=("single", "spread", "unknown"), default="unknown")
    parser.add_argument("--distance-cm", type=float, help="measured lens-to-page distance only")
    args = parser.parse_args(argv)
    try:
        path = build_packet(args.image, args.out, rotation=args.rotation, edge=args.edge,
                            overlap=args.overlap, tone=args.tone, auto_rectify=args.auto_rectify,
                            layout=args.layout, corners=json.loads(args.corners) if args.corners else None,
                            distance_cm=args.distance_cm)
    except (ValueError, OSError) as error:
        parser.exit(2, f"capture quality failed: {error}\n")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

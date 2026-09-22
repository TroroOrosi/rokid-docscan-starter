"""Offline synthetic packet checks, not physical capture acceptance."""
import hashlib
import importlib
import json

import pytest
from PIL import Image, ImageChops


def quality():
    return importlib.import_module("scripts.capture_quality")


def photo(path, size=(537, 301)):
    with Image.new("RGB", size) as image:
        image.putdata([(x % 256, y % 256, (x + y) % 256)
                       for y in range(size[1]) for x in range(size[0])])
        exif = Image.Exif()
        exif[274] = 6
        exif[270] = "private metadata"
        image.save(path, exif=exif)
    return path


@pytest.mark.parametrize("rotation,transpose", [
    (0, None), (90, Image.Transpose.ROTATE_270),
    (180, Image.Transpose.ROTATE_180), (270, Image.Transpose.ROTATE_90),
])
def test_native_tiles_cover_source_exactly_without_exif_rotation(tmp_path, rotation, transpose):
    source = photo(tmp_path / "source.png")
    before = source.read_bytes()
    path = quality().build_packet(source, tmp_path / "out", rotation=rotation, edge=256, overlap=64)
    report = json.loads(path.read_text(encoding="utf-8"))
    assert source.read_bytes() == before
    assert report["source_sha256"] == hashlib.sha256(before).hexdigest()
    assert report["source_bytes"] == len(before)
    assert report["schema"] == 2
    assert report["decision"] == "hold"
    assert report["auto_registration_allowed"] is False
    assert report["paper_completeness"] == report["semantic_coverage"] == "unknown"
    assert report["exif_applied"] is False
    with Image.open(source) as original:
        with original.transpose(transpose) if transpose else original.copy() as upright:
            assert report["upright_size"] == list(upright.size)
            covered = bytearray(upright.width * upright.height)
            for entry in report["tiles"]:
                left, top, right, bottom = entry["box_upright_pixels"]
                file = path.parent / entry["file"]
                assert hashlib.sha256(file.read_bytes()).hexdigest() == entry["sha256"]
                with Image.open(file) as tile, upright.crop((left, top, right, bottom)) as crop:
                    assert tile.size == crop.size
                    assert ImageChops.difference(tile, crop).getbbox() is None
                    assert not tile.getexif() and not tile.info
                for y in range(top, bottom):
                    covered[y * upright.width + left:y * upright.width + right] = b"\1" * (right - left)
            assert all(covered)
    with Image.open(path.parent / "overview.png") as overview:
        assert max(overview.size) <= 1280
        assert not overview.getexif()


@pytest.mark.parametrize("width,height,edge,overlap", [
    (0, 10, 256, 0), (True, 10, 256, 0), (10, 10, 255, 0),
    (10, 10, 1537, 0), (10, 10, 256, -1), (10, 10, 256, 65),
    (5000, 5000, 256, 64), (10, 10, 256.0, 0), (10, 10, 256, False),
])
def test_tile_limits(width, height, edge, overlap):
    with pytest.raises(ValueError):
        quality().tile_boxes(width, height, edge=edge, overlap=overlap)


def test_default_tiles_are_bounded_for_camera_size():
    boxes = quality().tile_boxes(3024, 4032)
    assert len(boxes) <= 96
    assert all(right - left <= 1024 and bottom - top <= 1024 for left, top, right, bottom in boxes)
    assert max(r for _, _, r, _ in boxes) == 3024
    assert max(b for _, _, _, b in boxes) == 4032


@pytest.mark.parametrize("kwargs", [
    {"rotation": 1}, {"rotation": False}, {"rotation": float("nan")},
    {"distance_cm": float("inf")}, {"distance_cm": -1}, {"layout": "auto"},
    {"auto_rectify": True, "corners": [[0, 0], [1, 0], [1, 1], [0, 1]]},
])
def test_invalid_arguments_preserve_source_and_create_no_packet(tmp_path, kwargs):
    source = photo(tmp_path / "source.png")
    before = source.read_bytes()
    with pytest.raises(ValueError):
        quality().build_packet(source, tmp_path / "out", **{"rotation": 0, **kwargs})
    assert source.read_bytes() == before
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("kind", ["broken", "bytes", "pixels", "frames", "gif"])
def test_input_limits(tmp_path, kind):
    source = tmp_path / "source"
    if kind == "broken":
        source.write_bytes(b"not an image")
    elif kind == "bytes":
        with source.open("wb") as stream:
            stream.truncate(16 * 1024 * 1024 + 1)
    else:
        with Image.new("RGB", (5001, 5000) if kind == "pixels" else (32, 32)) as image:
            if kind == "frames":
                with Image.new("RGB", image.size, "white") as other:
                    image.save(source, format="PNG", save_all=True, append_images=[other])
            else:
                image.save(source, format="GIF" if kind == "gif" else "PNG")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        quality().build_packet(source, tmp_path / "out", rotation=0)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert not (tmp_path / "out").exists()


def test_tone_is_monotonic_bounded_and_preserves_original_tiles(tmp_path):
    source = photo(tmp_path / "source.png")
    path = quality().build_packet(source, tmp_path / "out", rotation=0, tone=True)
    report = json.loads(path.read_text())
    entry = report["tiles"][0]
    with Image.open(path.parent / entry["file"]) as raw:
        with Image.open(path.parent / entry["tone"]["file"]) as toned:
            assert raw.size == toned.size
            assert .6 <= entry["tone"]["gamma"] <= 1
            assert not toned.getexif()
    with Image.new("RGB", (256, 2)) as ramp:
        ramp.putdata([(x, x, x) for _ in range(2) for x in range(256)])
        candidate, metrics = quality().tone_candidate(ramp)
        with candidate:
            levels = [candidate.getpixel((x, 0))[0] for x in range(256)]
            assert levels == sorted(levels)
            assert levels[0] == 0 and levels[-1] == 255
            assert .6 <= metrics["gamma"] <= 1


@pytest.mark.parametrize("level", [0, 64, 255])
def test_flat_images_are_not_amplified_or_called_in_focus(level):
    with Image.new("RGB", (32, 32), (level, level, level)) as image:
        candidate, report = quality().tone_candidate(image)
        with candidate:
            assert candidate.tobytes() == image.tobytes()
        assert report["gamma"] == 1
        metrics = quality().measure_tile(image)
        assert metrics["luminance_p05_p50_p95"] == [level] * 3
        assert metrics["focus"]["assessment"] == "insufficient_texture"
        assert metrics["mean_adjacent_difference"] == 0


def test_failed_output_removes_only_its_own_directory(tmp_path, monkeypatch):
    source = photo(tmp_path / "source.png")
    before = source.read_bytes()
    root = tmp_path / "out"
    previous = quality().build_packet(source, root, rotation=0)
    previous_bytes = previous.read_bytes()
    save = Image.Image.save
    calls = 0
    def fail(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return save(*args, **kwargs)
        raise OSError("synthetic disk full")
    monkeypatch.setattr(Image.Image, "save", fail)
    with pytest.raises(OSError, match="disk full"):
        quality().build_packet(source, root, rotation=0)
    assert list(root.iterdir()) == [previous.parent]
    assert previous.read_bytes() == previous_bytes and source.read_bytes() == before


def test_edge_tiles_use_the_requested_overlap_without_extra_repeated_pixels():
    boxes = quality().tile_boxes(537, 301, edge=256, overlap=64)
    first_row = [box for box in boxes if box[1] == 0]
    assert all(left[2] - right[0] == 64 for left, right in zip(first_row, first_row[1:]))


def test_one_pixel_tail_is_preserved_without_inventing_focus_evidence(tmp_path):
    source = photo(tmp_path / "source.png", size=(257, 257))
    path = quality().build_packet(source, tmp_path / "out", rotation=0, edge=256, overlap=0)
    report = json.loads(path.read_text())
    assert len(report["tiles"]) == 4
    tail = report["tiles"][-1]
    assert tail["box_upright_pixels"] == [256, 256, 257, 257]
    assert tail["metrics"]["focus"]["assessment"] == "insufficient_texture"


def test_cli_requires_rotation_and_reports_failure(tmp_path, capsys):
    source = photo(tmp_path / "source.png")
    with pytest.raises(SystemExit) as error:
        quality().main([str(source), "--out", str(tmp_path / "out")])
    assert error.value.code == 2
    assert quality().main([str(source), "--out", str(tmp_path / "out"), "--rotation", "0"]) == 0
    assert "report.json" in capsys.readouterr().out
    with pytest.raises(SystemExit) as error:
        quality().main([str(source), "--out", str(tmp_path / "out"), "--rotation", "0", "--distance-cm", "nan"])
    assert error.value.code == 2

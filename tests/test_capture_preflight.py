"""Offline capture diagnostics never certify a page or touch original inputs."""
import hashlib
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from scripts.capture_preflight import inspect_capture


def photo(tmp_path, size=(4032, 3024), dark=False):
    path = tmp_path / "source.jpg"
    image = Image.new("RGB", size, (24, 24, 24) if dark else "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((size[0] // 4, size[1] // 4, size[0] // 2, size[1] // 2), fill=(8, 8, 8))
    image.save(path, quality=85)
    return path


def test_report_is_offline_source_preserving_and_not_a_quality_pass(tmp_path, monkeypatch):
    source = photo(tmp_path, dark=True)
    before = source.read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError("preflight must never connect")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    report_path = inspect_capture(source, tmp_path / "reports", rotation=270)
    report = json.loads(report_path.read_text())
    assert source.read_bytes() == before
    assert report["source_sha256"] == hashlib.sha256(before).hexdigest()
    assert report["source_size"] == [4032, 3024]
    assert report["upright_size"] == [3024, 4032]
    assert report["preview_size"] == [756, 1008]
    assert report["estimated_android_rgb565_bytes"] == 756 * 1008 * 2
    assert "dark_frame" in report["warnings"]
    assert report["acceptance"] == "not_evaluated"
    assert report["ocr"] == "not_run"
    assert report["paper_corners"] == "not_identified"
    assert "source.jpg" not in report_path.read_text()
    assert not (report_path.parent / "paper-rectified.png").exists()
    with Image.open(report_path.parent / "display-preview.png") as preview:
        assert preview.getextrema()[0] == (0, 0)
        assert preview.getextrema()[2] == (0, 0)


@pytest.mark.parametrize("rotation,expected", [(0, [320, 240]), (90, [240, 320]), (180, [320, 240]), (270, [240, 320])])
def test_explicit_rotation_matches_glasses_without_double_applying_exif(tmp_path, rotation, expected):
    source = photo(tmp_path, size=(320, 240))
    with Image.open(source) as image:
        exif = image.getexif()
        exif[274] = 6
        image.save(source, exif=exif)
    report = json.loads(inspect_capture(source, tmp_path / "out", rotation=rotation).read_text())
    assert report["upright_size"] == expected
    assert report["exif_orientation"] == 6
    assert report["exif_applied"] is False


def test_explicit_corners_generate_derivatives_without_changing_source(tmp_path):
    source = tmp_path / "page.png"
    image = Image.new("RGB", (400, 300), (10, 10, 10))
    draw = ImageDraw.Draw(image)
    draw.polygon([(80, 30), (320, 60), (300, 270), (100, 240)], fill=(60, 60, 60))
    draw.line([(130, 100), (270, 110)], fill=(20, 20, 20), width=8)
    image.save(source)
    before = source.read_bytes()
    corners = [[80/399, 30/299], [320/399, 60/299], [300/399, 270/299], [100/399, 240/299]]
    report_path = inspect_capture(source, tmp_path / "out", rotation=0, corners=corners)
    report = json.loads(report_path.read_text())
    assert report["paper_corners"] == "operator_supplied"
    assert report["acceptance"] == "not_evaluated"
    assert source.read_bytes() == before
    with Image.open(report_path.parent / "paper-rectified.png") as raw:
        assert raw.getpixel((raw.width//2, raw.height//2))[0] in range(55, 66)
    with Image.open(report_path.parent / "paper-readable.png") as corrected:
        assert corrected.getextrema()[1] > 180
    assert report["paper_area_fraction"] == pytest.approx(0.386, abs=.01)


@pytest.mark.parametrize("corners", [
    [[0, 0], [1, 1], [1, 0], [0, 1]],
    [[0, 0], [0, 0], [1, 1], [0, 1]],
    [[-1, 0], [1, 0], [1, 1], [0, 1]],
    [[float("nan"), 0], [1, 0], [1, 1], [0, 1]],
    [[0, 0], [1, 0], [1, 1]],
])
def test_invalid_corners_fail_before_creating_output(tmp_path, corners):
    source = photo(tmp_path, size=(100, 80))
    with pytest.raises(ValueError):
        inspect_capture(source, tmp_path / "out", rotation=0, corners=corners)
    assert not (tmp_path / "out").exists()


def test_reports_never_overwrite_previous_results(tmp_path):
    source = photo(tmp_path, size=(100, 80))
    first = inspect_capture(source, tmp_path / "out", rotation=0)
    previous = first.read_bytes()
    second = inspect_capture(source, tmp_path / "out", rotation=0)
    assert first != second
    assert first.read_bytes() == previous


def test_rejects_invalid_rotation_and_non_images(tmp_path):
    source = photo(tmp_path, size=(100, 80))
    with pytest.raises(ValueError):
        inspect_capture(source, tmp_path / "out", rotation=45)
    source.write_bytes(b"not an image")
    with pytest.raises(ValueError):
        inspect_capture(source, tmp_path / "out", rotation=0)


def test_rejects_excessive_pixels_before_decode(tmp_path, monkeypatch):
    import scripts.capture_preflight as module
    source = photo(tmp_path, size=(100, 80))
    monkeypatch.setattr(module, "MAX_PIXELS", 100)
    with pytest.raises(ValueError, match="pixel"):
        inspect_capture(source, tmp_path / "out", rotation=0)


def test_cli_outputs_report_and_never_requires_devices_or_model_config(tmp_path):
    source = photo(tmp_path, size=(100, 80))
    result = subprocess.run([sys.executable, "-m", "scripts.capture_preflight", str(source),
                             "--out", str(tmp_path / "out"), "--rotation", "0"],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()).is_file()

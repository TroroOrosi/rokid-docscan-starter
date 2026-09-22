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


def test_reports_actual_ocr_sampling_separately_from_hud(tmp_path):
    source = photo(tmp_path)
    report = json.loads(inspect_capture(source, tmp_path / "out", rotation=270).read_text())
    assert report["ocr_sampling"]["sample_size"] == 2
    assert report["ocr_sampling"]["estimated_upright_size"] == [1512, 2016]
    assert report["android_sample_size"] == 4
    assert report["ocr_sampling"]["glyph_assessment"] == "not_measured"
    assert report["capture_distance"]["assessment"] == "not_measured"


def test_manual_glyph_pixels_are_scaled_not_inferred_from_column_pitch(tmp_path):
    source = photo(tmp_path)
    report = json.loads(inspect_capture(source, tmp_path / "out", rotation=270,
                                       glyph_pixels=(24, 30)).read_text())
    assert report["ocr_sampling"]["estimated_glyph_pixels"] == [12, 15]
    assert report["ocr_sampling"]["glyph_assessment"] == "below_16px_guidance"
    assert report["acceptance"] == "not_evaluated"
    assert report["ocr"] == "not_run"


@pytest.mark.parametrize("glyph", [(0, 20), (float("nan"), 20), (True, 20), (20,), (20, 5000)])
def test_bad_manual_glyph_measurement_has_no_output(tmp_path, glyph):
    source = photo(tmp_path, size=(100, 80))
    with pytest.raises(ValueError):
        inspect_capture(source, tmp_path / "out", rotation=0, glyph_pixels=glyph)
    assert not (tmp_path / "out").exists()


def test_detail_is_original_scale_after_explicit_rotation_and_contains_no_exif(tmp_path):
    source = tmp_path / "page.png"
    image = Image.new("RGB", (2400, 1600), "white")
    # High frequency strokes disappear from the downsampled preview, but not the detail.
    draw = ImageDraw.Draw(image)
    for x in range(0, 200, 2):
        draw.line((x, 0, x, 199), fill="black")
    image.save(source)
    before = source.read_bytes()
    path = inspect_capture(source, tmp_path / "out", rotation=270,
                           details=[[0, .95, .1, 1]])
    report = json.loads(path.read_text())
    with Image.open(source) as raw, Image.open(path.parent / "detail-1.png") as detail:
        expected = raw.transpose(Image.Transpose.ROTATE_90).crop((0, 2280, 160, 2400))
        assert detail.size == (160, 120)
        assert detail.tobytes() == expected.tobytes()
        assert not detail.getexif()
    assert report["details"][0]["scale"] == "source_pixels_1_to_1"
    assert source.read_bytes() == before


@pytest.mark.parametrize("details", [
    [[0, 0, 1, 1]], [[.5, 0, .4, 1]], [[0, 0, float("nan"), 1]],
    [[0, 0, 1, 1]] * 6, [[False, 0, .1, .1]],
])
def test_invalid_or_unbounded_detail_regions_fail_before_output(tmp_path, details):
    source = photo(tmp_path)
    with pytest.raises(ValueError):
        inspect_capture(source, tmp_path / "out", rotation=0, details=details)
    assert not (tmp_path / "out").exists()


def test_only_numeric_photographic_exif_is_reported(tmp_path):
    from PIL.TiffImagePlugin import IFDRational
    source = photo(tmp_path, size=(100, 80))
    with Image.open(source) as image:
        exif = Image.Exif()
        exif[315] = "private photographer"
        exif[34665] = {33434: IFDRational(1, 30), 33437: IFDRational(225, 100),
                       34855: 800, 37510: b"private comment"}
        image.save(source, exif=exif)
    text = inspect_capture(source, tmp_path / "out", rotation=0).read_text()
    report = json.loads(text)
    assert report["photographic_exif"]["exposure_seconds"] == pytest.approx(1 / 30)
    assert report["photographic_exif"]["f_number"] == 2.25
    assert report["photographic_exif"]["iso"] == 800
    assert "private" not in text
    assert "37510" not in text


def test_detail_cli_and_glyph_measurement(tmp_path):
    source = photo(tmp_path, size=(100, 80))
    result = subprocess.run([sys.executable, "-m", "scripts.capture_preflight", str(source),
                             "--out", str(tmp_path / "out"), "--rotation", "0",
                             "--details", "[[0,0,0.5,0.5]]", "--glyph-pixels", "20", "20",
                             "--distance-cm", "30"],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    report = json.loads(Path(result.stdout.strip()).read_text())
    assert report["ocr_sampling"]["glyph_assessment"] == "not_below_16px_not_a_pass"
    assert report["capture_distance"]["assessment"] == "below_official_near_limit"
    assert (Path(result.stdout.strip()).parent / "detail-1.png").is_file()


def test_all_generated_images_strip_original_exif(tmp_path):
    source = photo(tmp_path, size=(100, 80))
    with Image.open(source) as image:
        exif = Image.Exif()
        exif[315] = "private photographer"
        exif[274] = 6
        image.save(source, exif=exif)
    path = inspect_capture(source, tmp_path / "out", rotation=0,
                           details=[[0, 0, .5, .5]],
                           corners=[[0, 0], [1, 0], [1, 1], [0, 1]])
    for output in path.parent.glob("*.png"):
        with Image.open(output) as image:
            assert not image.getexif(), output.name


@pytest.mark.parametrize("distance,assessment", [
    (30, "below_official_near_limit"), (34, "not_below_limit_not_a_pass"),
    (50, "not_below_limit_not_a_pass"),
])
def test_distance_is_operator_measured_not_inferred_from_exif(tmp_path, distance, assessment):
    source = photo(tmp_path, size=(100, 80))
    path = inspect_capture(source, tmp_path / "out", rotation=0, distance_cm=distance)
    report = json.loads(path.read_text())
    assert report["capture_distance"]["operator_distance_cm"] == distance
    assert report["capture_distance"]["official_near_limit_cm"] == 34
    assert report["capture_distance"]["assessment"] == assessment
    assert report["acceptance"] == "not_evaluated"


@pytest.mark.parametrize("distance", [0, -1, True, float("nan"), float("inf"), "34"])
def test_invalid_distance_has_no_output(tmp_path, distance):
    source = photo(tmp_path, size=(100, 80))
    with pytest.raises(ValueError):
        inspect_capture(source, tmp_path / "out", rotation=0, distance_cm=distance)
    assert not (tmp_path / "out").exists()

"""Packet integration; the independent geometry core tests stay unchanged."""
import hashlib
import importlib
import json

import pytest
from PIL import Image, ImageDraw


def test_auto_geometry_saves_candidate_and_original_tiles(tmp_path):
    quality = importlib.import_module("scripts.capture_quality")
    source = tmp_path / "page.png"
    with Image.new("RGB", (600, 500), (20, 20, 20)) as image:
        ImageDraw.Draw(image).polygon([(130, 60), (510, 100), (460, 440), (90, 390)], fill="white")
        image.save(source)
    for layout in ("single", "spread", "unknown"):
        path = quality.build_packet(source, tmp_path / "out", rotation=0, auto_rectify=True, layout=layout)
        report = json.loads(path.read_text())
        assert report["tiles"] and report["decision"] == "hold"
        if layout == "single":
            rectified = report["rectified"]
            assert rectified["resampled"] is True
            assert len(rectified["output_to_source_homography"]) == 8
            assert rectified["sha256"] == hashlib.sha256((path.parent / rectified["file"]).read_bytes()).hexdigest()
        else:
            assert report["paper_detection"]["reason"] == "single_page_required"
            assert report["rectified"] is None
            assert not (path.parent / "paper-rectified.png").exists()


@pytest.mark.parametrize("corners", [
    [[0, 0], [1, 1], [1, 0], [0, 1]], [[0, 0]] * 4,
    [[0, 0], [float("nan"), 0], [1, 1], [0, 1]],
    [[False, 0], [1, 0], [1, 1], [0, 1]],
])
def test_bad_manual_geometry_preserves_source(tmp_path, corners):
    quality = importlib.import_module("scripts.capture_quality")
    source = tmp_path / "page.png"
    with Image.new("RGB", (32, 32)) as image:
        image.save(source)
    before = source.read_bytes()
    with pytest.raises(ValueError):
        quality.build_packet(source, tmp_path / "out", rotation=0, corners=corners)
    assert source.read_bytes() == before
    assert not (tmp_path / "out").exists()

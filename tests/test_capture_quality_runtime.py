"""Phone-runtime quality checks with synthetic pixels and an injected checker."""
from __future__ import annotations

import copy
import hashlib
import io
import zipfile

import pytest
from PIL import Image, ImageChops

from app.capture_quality import (
    assess_captured_image,
    check_captured_image,
    prepare_captured_image,
)


def test_diagnostic_packet_is_bounded_lossless_and_cannot_admit_a_page(tmp_path, monkeypatch):
    from app import capture_quality as quality
    source = tmp_path / "original.png"
    with Image.new("RGB", (2200, 1700), "white") as image:
        image.putpixel((2199, 1699), (17, 29, 31))
        image.putpixel((1100, 850), (73, 91, 117))
        image.save(source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setattr(quality, "tile_boxes", lambda *a, **k: pytest.fail("all tiles allocated"))
    packet = quality.prepare_diagnostic_image(source, tmp_path / "packet", source_sha256=digest,
                                              owner={"capture_id": "actual-capture"}, rotation=0)
    assert 2 <= len(packet["images"]) <= 6
    assert packet["scope"] == "bounded_regions_only"
    assert packet["guarantees_all_content"] is False
    assert packet["auto_registration_allowed"] is False
    assert sum((tmp_path / "packet" / item["file"]).stat().st_size for item in packet["images"]) <= 16 * 1024 * 1024
    original_entry = packet["images"][0]
    assert original_entry["role"] == "source_original"
    assert original_entry["sha256"] == digest
    assert (tmp_path / "packet" / original_entry["file"]).read_bytes() == source.read_bytes()
    with Image.open(source) as original:
        for item in packet["images"]:
            if item["role"] != "native_roi":
                continue
            with Image.open(tmp_path / "packet" / item["file"]) as roi, original.crop(item["box_upright_pixels"]) as crop:
                assert max(roi.size) <= 1024
                assert ImageChops.difference(roi, crop).getbbox() is None
        assert not any(item["box_upright_pixels"][0] <= 1100 < item["box_upright_pixels"][2]
                       and item["box_upright_pixels"][1] <= 850 < item["box_upright_pixels"][3]
                       for item in packet["images"] if item["role"] == "native_roi")
    from app.capture_inspection import _package
    file = list(_package(packet, tmp_path / "packet"))[0]
    assert len(file["buffer"]) == packet["package_bytes"]
    with zipfile.ZipFile(io.BytesIO(file["buffer"])) as archive:
        raw = archive.read(original_entry["file"])
        assert raw == source.read_bytes()
        with Image.open(io.BytesIO(raw)) as reachable:
            assert reachable.getpixel((1100, 850)) == (73, 91, 117)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest


def test_diagnostic_budget_shrinks_only_overview_and_omits_optional_rois(tmp_path, monkeypatch):
    from app import capture_quality as quality, capture_inspection as inspection
    source = tmp_path / "original.png"
    with Image.effect_noise((1600, 1200), 64).convert("RGB") as image:
        image.save(source)
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    full = quality.prepare_diagnostic_image(source, tmp_path / "full", source_sha256=digest, owner={}, rotation=0)
    overview = next(item for item in full["images"] if item["role"] == "overview")
    original = full["images"][0]
    # ZIP_STORED: EOCD=22, each local+central entry=76+2*filename bytes.
    budget = 22 + sum(item["bytes"] + 76 + 2 * len(item["file"].encode())
                      for item in (original, overview)) - 1
    monkeypatch.setattr(quality, "MAX_DIAGNOSTIC_BYTES", budget)
    monkeypatch.setattr(inspection, "MAX_DIAGNOSTIC_BYTES", budget)
    packet = quality.prepare_diagnostic_image(source, tmp_path / "bounded", source_sha256=digest, owner={}, rotation=0)
    assert [item["role"] for item in packet["images"]] == ["source_original", "overview"]
    overview = packet["images"][1]
    with Image.open(tmp_path / "bounded" / overview["file"]) as image:
        assert max(image.size) == 1024
    assert (tmp_path / "bounded" / original["file"]).read_bytes() == raw
    assert len(list(inspection._package(packet, tmp_path / "bounded"))[0]["buffer"]) <= budget


def test_diagnostic_original_zip_boundary_is_checked_before_decode(tmp_path, monkeypatch):
    from app import capture_quality as quality, capture_inspection as inspection
    source = tmp_path / "original.png"
    source.write_bytes(photo())
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    exact = len(raw) + 22 + 76 + 2 * len("source_original.png")
    monkeypatch.setattr(quality, "MAX_DIAGNOSTIC_BYTES", exact)
    monkeypatch.setattr(inspection, "MAX_DIAGNOSTIC_BYTES", exact)
    packet = quality.prepare_diagnostic_image(source, tmp_path / "exact", source_sha256=digest, owner={}, rotation=0)
    assert [item["role"] for item in packet["images"]] == ["source_original"]
    assert len(list(inspection._package(packet, tmp_path / "exact"))[0]["buffer"]) == exact
    monkeypatch.setattr(quality, "MAX_DIAGNOSTIC_BYTES", exact - 1)
    monkeypatch.setattr(quality.Image, "open", lambda *a, **k: pytest.fail("over-budget original decoded"))
    with pytest.raises(ValueError, match="original_png_over_budget"):
        quality.prepare_diagnostic_image(source, tmp_path / "over", source_sha256=digest, owner={}, rotation=0)
    assert not (tmp_path / "over").exists()
    assert source.read_bytes() == raw


@pytest.mark.parametrize("rotation,transpose", [
    (0, None), (90, Image.Transpose.ROTATE_270),
    (180, Image.Transpose.ROTATE_180), (270, Image.Transpose.ROTATE_90),
])
def test_diagnostic_rotation_changes_derivatives_but_never_original_png(tmp_path, rotation, transpose):
    from app import capture_quality as quality
    source = tmp_path / "original.png"
    raw = photo()  # Contains EXIF rotation=6, which must not be applied again.
    source.write_bytes(raw)
    packet = quality.prepare_diagnostic_image(source, tmp_path / "packet", source_sha256=hashlib.sha256(raw).hexdigest(),
                                              owner={}, rotation=rotation)
    assert (tmp_path / "packet" / packet["images"][0]["file"]).read_bytes() == raw
    assert packet["rotation"] == rotation and packet["source_size"] == [537, 301]
    with Image.open(io.BytesIO(raw)) as original:
        with original.transpose(transpose) if transpose else original.copy() as upright:
            assert packet["upright_size"] == list(upright.size)
            for item in packet["images"][1:]:
                with Image.open(tmp_path / "packet" / item["file"]) as image:
                    assert ImageChops.difference(image, upright).getbbox() is None


def test_diagnostic_remaining_budget_can_include_one_optional_native_roi(tmp_path, monkeypatch):
    from app import capture_quality as quality, capture_inspection as inspection
    source = tmp_path / "original.png"
    with Image.new("RGB", (2200, 1700), "white") as image:
        image.putpixel((1100, 850), (20, 33, 90))
        image.save(source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    full = quality.prepare_diagnostic_image(source, tmp_path / "full", source_sha256=digest, owner={}, rotation=0)
    budget = 22 + sum(item["bytes"] + 76 + 2 * len(item["file"].encode()) for item in full["images"][:3])
    monkeypatch.setattr(quality, "MAX_DIAGNOSTIC_BYTES", budget)
    monkeypatch.setattr(inspection, "MAX_DIAGNOSTIC_BYTES", budget)
    packet = quality.prepare_diagnostic_image(source, tmp_path / "bounded", source_sha256=digest, owner={}, rotation=0)
    assert [item["role"] for item in packet["images"]] == ["source_original", "overview", "native_roi"]
    assert packet["images"][0]["sha256"] == digest
    assert len(list(inspection._package(packet, tmp_path / "bounded"))[0]["buffer"]) == budget


def test_diagnostic_will_not_replace_original_jpeg_with_a_converted_png(tmp_path):
    from app import capture_quality as quality
    source = tmp_path / "source.jpg"
    with Image.new("RGB", (32, 24), "white") as image:
        image.save(source)
    raw = source.read_bytes()
    with pytest.raises(ValueError, match="original_png_required"):
        quality.prepare_diagnostic_image(source, tmp_path / "packet", source_sha256=hashlib.sha256(raw).hexdigest(),
                                          owner={}, rotation=0)
    assert source.read_bytes() == raw and not (tmp_path / "packet").exists()


def test_diagnostic_packet_rejects_changed_source_and_invalid_roi_before_output(tmp_path):
    from app import capture_quality as quality
    source = tmp_path / "original.png"
    source.write_bytes(photo())
    with pytest.raises(ValueError, match="hash"):
        quality.prepare_diagnostic_image(source, tmp_path / "bad", source_sha256="0" * 64,
                                          owner={}, rotation=0)
    assert not (tmp_path / "bad").exists()


def photo():
    with Image.new("RGB", (537, 301)) as image:
        image.putdata([(x % 256, y % 256, (x + y) % 256)
                       for y in range(image.height) for x in range(image.width)])
        exif = Image.Exif()
        exif[274] = 6
        stream = io.BytesIO()
        image.save(stream, format="PNG", exif=exif)
        return stream.getvalue()


def prepare(data=None, **kwargs):
    return prepare_captured_image(
        photo() if data is None else data,
        **dict(session_id="session-a", capture_id="capture-a", generation=7,
               page_turn=3, revision=1, rotation=270, edge=256, overlap=64, **kwargs),
    )


def reply(prepared):
    return {
        "schema": 1,
        "capture": prepared.identity,
        "inspected_image_ids": [image.image_id for image in prepared.images],
        "evidence": {
            "schema": 1, "source_sha256": prepared.identity["source_sha256"],
            "rotation": 270, "inventory_complete": True,
            "profile_id": "checked-fixture", "layout": "single",
            "pages": [{"id": "p4", "printed_page_number": "4", "question_numbers": ["2"],
                       "paper_bounds": "pass", "occlusion": "pass",
                       "regions": [{"id": "r1", "kind": "math", "source_detail": "pass",
                                    "exposure": "pass", "readability": "pass"}]}],
        },
    }


def assess(prepared, response, **kwargs):
    return assess_captured_image(
        prepared, response, current_identity=prepared.identity,
        validated_profiles=("checked-fixture",), **kwargs,
    )


def test_quality_receipt_is_bound_to_source_and_never_claims_complete_booklet():
    prepared = prepare()
    result = assess(prepared, reply(prepared))
    assert result["decision"] == "eligible"
    assert result["capture"] == prepared.identity
    assert result["guarantees_all_content"] is False
    assert result["inspection_claim"]["independently_verified"] is False


@pytest.mark.parametrize("rotation,transpose", [
    (0, None), (90, Image.Transpose.ROTATE_270),
    (180, Image.Transpose.ROTATE_180), (270, Image.Transpose.ROTATE_90),
])
def test_inspection_tiles_keep_every_original_pixel_and_rotation(rotation, transpose):
    data = photo()
    prepared = prepare_captured_image(data, session_id="s", capture_id="c", generation=1,
                                      page_turn=0, revision=1, rotation=rotation,
                                      edge=256, overlap=64)
    assert prepared.identity["source_sha256"] == hashlib.sha256(data).hexdigest()
    assert prepared.request["coordinate_system"] == "upright_pixels_after_clockwise_rotation"
    assert prepared.request["exif_applied"] is False
    with Image.open(io.BytesIO(data)) as source:
        with source.transpose(transpose) if transpose else source.copy() as upright:
            covered = bytearray(upright.width * upright.height)
            for part in prepared.images[1:]:
                left, top, right, bottom = part.box_upright_pixels
                with Image.open(io.BytesIO(part.data)) as tile, upright.crop(part.box_upright_pixels) as crop:
                    assert ImageChops.difference(tile, crop).getbbox() is None
                    assert tile.size == (right - left, bottom - top)
                for y in range(top, bottom):
                    covered[y * upright.width + left:y * upright.width + right] = b"\1" * (right - left)
            assert all(covered)
    assert data == photo()


def test_unconfigured_checker_and_uncalibrated_profile_hold():
    prepared = prepare()
    result = check_captured_image(prepared, checker=None, current_identity=lambda: prepared.identity)
    assert result["decision"] == "hold" and result["reasons"] == ["checker_not_configured"]
    result = assess_captured_image(prepared, reply(prepared), current_identity=prepared.identity)
    assert result["decision"] == "hold"
    assert result["reasons"] == ["profile_not_validated_by_caller"]


@pytest.mark.parametrize("field,value", [
    ("session_id", "session-b"), ("capture_id", "capture-b"), ("generation", 8),
    ("page_turn", 4), ("revision", 2), ("rotation", 0), ("source_sha256", "a" * 64),
    ("generation", 7.0), ("revision", True),
])
def test_delayed_or_wrong_receipt_cannot_accept_another_capture(field, value):
    prepared = prepare()
    response = reply(prepared)
    response["capture"][field] = value
    result = assess(prepared, response)
    assert result["decision"] == "hold"
    assert result["reasons"] == ["capture_identity_mismatch"]


def test_page_turn_while_checker_runs_invalidates_the_result():
    prepared = prepare()
    current = prepared.identity

    def checker(request, images):
        current["page_turn"] += 1
        return reply(prepared)

    result = check_captured_image(prepared, checker=checker, current_identity=lambda: current,
                                  validated_profiles=("checked-fixture",))
    assert result["decision"] == "hold"
    assert result["reasons"] == ["stale_capture"]


@pytest.mark.parametrize("mutation", ["missing_tile", "duplicate", "malformed", "nan", "wrong_source"])
def test_missing_inspections_or_bad_json_do_not_pass(mutation):
    prepared = prepare()
    response = reply(prepared)
    if mutation == "missing_tile":
        response["inspected_image_ids"].pop()
    elif mutation == "duplicate":
        response["inspected_image_ids"][-1] = response["inspected_image_ids"][0]
    elif mutation == "malformed":
        response = "eligible"
    elif mutation == "nan":
        response["evidence"]["confidence"] = float("nan")
    else:
        response["evidence"]["source_sha256"] = "b" * 64
    assert assess(prepared, response)["decision"] == "hold"


def test_known_blur_requests_retake_and_unknown_holds_without_guessing():
    prepared = prepare()
    response = reply(prepared)
    region = response["evidence"]["pages"][0]["regions"][0]
    region["readability"] = "fail"
    assert assess(prepared, response)["decision"] == "retake"
    region["readability"] = "unknown"
    assert assess(prepared, response)["decision"] == "hold"


def test_checker_receives_pixels_but_cannot_rewrite_bound_identity():
    prepared = prepare()
    expected = copy.deepcopy(prepared.request)

    def checker(request, images):
        assert images == prepared.images
        assert request == expected
        request["capture"]["generation"] = 500
        raise TimeoutError("private provider details")

    result = check_captured_image(prepared, checker=checker, current_identity=lambda: prepared.identity)
    assert result["decision"] == "hold" and result["reasons"] == ["checker_timeout"]
    assert prepared.request == expected
    assert "private" not in str(result)


def test_stale_work_does_not_spend_another_checker_call():
    prepared = prepare()
    stale = dict(prepared.identity, generation=8)

    def checker(request, images):
        pytest.fail("a stale candidate must not be sent for another inspection")

    result = check_captured_image(prepared, checker=checker, current_identity=lambda: stale)
    assert result["decision"] == "hold" and result["reasons"] == ["stale_capture"]


def test_unavailable_current_capture_holds_without_leaking_provider_details():
    prepared = prepare()

    def current():
        raise OSError("private session storage path")

    result = check_captured_image(prepared, checker=lambda *_: reply(prepared), current_identity=current)
    assert result["decision"] == "hold"
    assert result["reasons"] == ["current_capture_unavailable"]
    assert "private" not in str(result)


def test_real_jpeg_pixels_are_not_recompressed_or_rotated_from_exif_twice():
    with Image.new("RGB", (48, 32), "white") as source:
        source.paste("black", (0, 0, 12, 7))
        exif = Image.Exif()
        exif[274] = 6
        stream = io.BytesIO()
        source.save(stream, format="JPEG", exif=exif)
    data = stream.getvalue()
    prepared = prepare(data)
    assert prepared.identity["source_sha256"] == hashlib.sha256(data).hexdigest()
    assert prepared.upright_size == (32, 48)
    with Image.open(io.BytesIO(data)) as original:
        with original.transpose(Image.Transpose.ROTATE_90) as upright:
            with Image.open(io.BytesIO(prepared.images[1].data)) as tile:
                assert ImageChops.difference(tile, upright).getbbox() is None
                assert not tile.getexif()


@pytest.mark.parametrize("kwargs", [
    {"generation": True}, {"page_turn": 1.0}, {"rotation": False},
    {"session_id": ""}, {"revision": -1}, {"edge": 255},
])
def test_invalid_capture_or_tile_configuration_fails_before_inspection(kwargs):
    identity = dict(session_id="s", capture_id="c", generation=1, page_turn=0,
                    revision=1, rotation=0)
    identity.update(kwargs)
    with pytest.raises(ValueError):
        prepare_captured_image(photo(), **identity)


def test_runtime_accepts_large_valid_maximum_rgb_png_without_upload_size_assumption():
    # A real, deliberately uncompressed PNG exercises encoded size independently
    # of image detail. The phone normalizes uploads to RGB PNG before inspection.
    with Image.new("RGB", (5000, 5000), (123, 125, 127)) as source:
        stream = io.BytesIO()
        source.save(stream, format="PNG", compress_level=0)
    data = stream.getvalue()
    assert len(data) > 16 * 1024 * 1024
    prepared = prepare_captured_image(data, session_id="s", capture_id="c", generation=1,
                                      page_turn=0, revision=1, rotation=0)
    assert prepared.source_size == prepared.upright_size == (5000, 5000)
    assert prepared.identity["source_sha256"] == hashlib.sha256(data).hexdigest()
    assert max(part.box_upright_pixels[2] for part in prepared.images[1:]) == 5000
    assert max(part.box_upright_pixels[3] for part in prepared.images[1:]) == 5000
    for part in (prepared.images[1], prepared.images[-1]):
        with Image.open(io.BytesIO(part.data)) as tile:
            assert tile.getpixel((0, 0)) == (123, 125, 127)


def test_runtime_rejects_excess_encoded_bytes_before_decoding(monkeypatch):
    import app.capture_quality as runtime

    def decode(_):
        pytest.fail("the encoded-byte bound must be checked before image decoding")

    monkeypatch.setattr(runtime.Image, "open", decode)
    with pytest.raises(ValueError, match="oversized image bytes"):
        prepare(b"x" * (runtime.MAX_CAPTURE_BYTES + 1))


def test_larger_encoded_limit_does_not_admit_more_than_25_megapixels():
    with Image.new("RGB", (5001, 5000), "white") as source:
        stream = io.BytesIO()
        source.save(stream, format="PNG")
    with pytest.raises(ValueError, match="invalid dimensions"):
        prepare_captured_image(stream.getvalue(), session_id="s", capture_id="c", generation=1,
                               page_turn=0, revision=1, rotation=0)

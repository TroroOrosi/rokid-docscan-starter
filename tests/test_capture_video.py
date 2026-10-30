"""Local synthetic movie comparisons; no camera, paper or venue acceptance."""
import hashlib
import importlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageDraw, ImageFilter


def video():
    return importlib.import_module("app.capture_video")


def run(argv):
    result = subprocess.run(argv, capture_output=True, timeout=45, check=False)
    assert result.returncode == 0, result.stderr.decode(errors="replace")[-2000:]
    return result.stdout


@pytest.fixture(scope="module")
def movie(tmp_path_factory):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("existing ffmpeg/ffprobe required; nothing is installed by this test")
    directory = tmp_path_factory.mktemp("video-fixture")
    for index in range(6):
        with Image.new("RGB", (160, 120), "white") as image:
            draw = ImageDraw.Draw(image)
            for box, color in [((0, 0, 12, 12), "red"), ((147, 0, 159, 12), "green"),
                               ((0, 107, 12, 119), "blue"), ((147, 107, 159, 119), "black")]:
                draw.rectangle(box, fill=color)
            draw.text((19, 25), "x^2 + 1 = 17", fill="black")
            draw.text((19, 48), "fine 1Il0O ()", fill="black")
            # A very similar next scene must not collapse into the previous one.
            draw.text((19, 75), "scene B" if index >= 3 else "scene A", fill="black")
            if index in (1, 4):
                image = image.filter(ImageFilter.GaussianBlur(2))
            image.save(directory / f"source-{index}.png")
    listing = directory / "frames.txt"
    listing.write_text("".join(f"file 'source-{i}.png'\nduration {duration}\n"
                               for i, duration in enumerate((.04, .12, .08, .16, .04, .12))),
                       encoding="utf-8")
    source = directory / "original.mp4"
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "1",
         "-i", str(listing), "-vf", "setpts=PTS+2/TB", "-fps_mode", "passthrough", "-c:v", "libx264",
         "-pix_fmt", "yuv444p", "-crf", "12", "-bf", "2", "-g", "100",
         "-x264-params", "b-adapt=0:scenecut=0", "-y", str(source)])
    probe = json.loads(run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames",
                            "-show_streams", "-of", "json", str(source)]))
    frames = probe["frames"]
    assert len(frames) == 6 and int(frames[0]["pts"]) > 0
    assert len({int(b["pts"]) - int(a["pts"]) for a, b in zip(frames, frames[1:])}) > 1
    assert any(frame["pict_type"] == "B" for frame in frames)
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-copyts", "-noautorotate", "-i",
         str(source), "-fps_mode", "passthrough", "-pix_fmt", "rgb24", str(directory / "reference-%03d.png")])
    return source, directory, probe


def prepare(source, output, **kwargs):
    return video().prepare_video_candidates(source, output, session_id="session-1",
                                            capture_id="capture-1", generation=4, revision=2,
                                            rotation=270, frame_indices=(0, 2, 5), **kwargs)


def test_real_vfr_b_frames_keep_full_original_and_exact_index_pts_pixels(movie, tmp_path):
    source, references, probe = movie
    original = source.read_bytes()
    result = prepare(source, tmp_path)
    assert result["decision"] == "comparison_only", result
    assert result["guarantees_all_content"] is False
    assert result["auto_registration_allowed"] is False
    packet = Path(result["packet_dir"])
    assert (packet / "original.mp4").read_bytes() == original == source.read_bytes()
    assert result["source"]["sha256"] == hashlib.sha256(original).hexdigest()
    assert result["source"]["time_base"] == probe["streams"][0]["time_base"]
    assert [item["decoded_index"] for item in result["candidates"]] == [0, 2, 5]
    for item in result["candidates"]:
        assert item["pts"] == probe["frames"][item["decoded_index"]]["pts"]
        assert item["rotation"] == 270 and item["dimensions"] == [160, 120]
        image_path = packet / item["file"]
        assert item["sha256"] == hashlib.sha256(image_path.read_bytes()).hexdigest()
        with Image.open(image_path) as image, Image.open(
                references / f"reference-{item['decoded_index'] + 1:03d}.png") as expected:
            assert image.size == expected.size == (160, 120)
            assert ImageChops.difference(image.convert("RGB"), expected.convert("RGB")).getbbox() is None
        assert item["scene_id"] is None
        assert item["metrics"]["focus"]["calibrated"] is False
    assert result["comparisons"] == []
    assert json.loads((packet / "report.json").read_text(encoding="utf-8")) == result


def test_two_similar_scenes_are_never_ranked_against_each_other(movie, tmp_path):
    source, _, probe = movie
    frames = probe["frames"]
    result = prepare(source, tmp_path, scene_intervals=(
        {"scene_id": "A", "start_pts": frames[0]["pts"], "end_pts": frames[3]["pts"],
         "time_base": probe["streams"][0]["time_base"], "origin": "decoded_video"},
        {"scene_id": "B", "start_pts": frames[3]["pts"], "end_pts": frames[5]["pts"] + 1,
         "time_base": probe["streams"][0]["time_base"], "origin": "decoded_video"}))
    assert result["decision"] == "comparison_only", result
    assert [row["scene_id"] for row in result["candidates"]] == ["A", "A", "B"]
    assert result["comparisons"][0]["scene_id"] == "A"
    assert set(result["comparisons"][0]["ranked_indices"]) == {0, 2}
    assert result["comparisons"][0]["calibrated"] is False


@pytest.mark.parametrize("mutation", [
    {"generation": True}, {"revision": -1}, {"rotation": 45},
    {"frame_indices": (False,)}, {"frame_indices": (0, 0)},
    {"frame_indices": tuple(range(13))}, {"capture_id": "../outside"},
])
def test_invalid_requests_create_nothing(movie, tmp_path, mutation):
    source, _, _ = movie
    kwargs = dict(session_id="s", capture_id="c", generation=1, revision=0,
                  rotation=0, frame_indices=(0,))
    kwargs.update(mutation)
    result = video().prepare_video_candidates(source, tmp_path, **kwargs)
    assert result["decision"] == "hold"
    assert result["reasons"] == ["invalid_arguments"]
    assert list(tmp_path.iterdir()) == []


def test_external_url_and_source_parent_output_are_rejected(movie, tmp_path):
    source, _, _ = movie
    result = prepare("https://example.invalid/movie.mp4", tmp_path)
    assert result["decision"] == "hold" and list(tmp_path.iterdir()) == []
    result = prepare(source, source)
    assert result["decision"] == "hold"
    assert source.is_file()


def test_missing_decoder_holds_without_install_or_output(movie, tmp_path, monkeypatch):
    source, _, _ = movie
    monkeypatch.setattr(video().shutil, "which", lambda name: None)
    result = prepare(source, tmp_path)
    assert result["decision"] == "hold" and result["reasons"] == ["decoder_unavailable"]
    assert list(tmp_path.iterdir()) == []


def test_one_probe_and_one_selected_decode_for_many_candidates(movie, tmp_path, monkeypatch):
    source, _, _ = movie
    real, commands = video()._run, []

    def record(argv, **kwargs):
        commands.append(argv)
        return real(argv, **kwargs)

    monkeypatch.setattr(video(), "_run", record)
    result = prepare(source, tmp_path)
    assert result["decision"] == "comparison_only", result
    assert len(commands) == 2
    assert "-show_frames" in commands[0] and "-vf" in commands[1]
    assert "-ss" not in commands[1]


@pytest.mark.parametrize("mutation,reason", [
    ("missing_pts", "missing_or_unsupported_frame_pts"),
    ("duplicate_pts", "ambiguous_frame_pts"),
    ("reversed_pts", "ambiguous_frame_pts"),
    ("dimensions", "unsupported_video_dimensions"),
    ("extra_track", "unsupported_video_tracks"),
    ("program_version", "invalid_probe"),
    ("duration", "unsupported_duration"),
    ("frame_stream", "missing_or_unsupported_frame_pts"),
])
def test_unusable_probe_never_invents_timestamps_or_exposes_images(movie, tmp_path, monkeypatch,
                                                                 mutation, reason):
    source, _, _ = movie
    real = video()._run

    def changed(argv, **kwargs):
        out, err = real(argv, **kwargs)
        if "-show_frames" in argv:
            data = json.loads(out)
            if mutation == "missing_pts":
                data["frames"][0]["best_effort_timestamp"] = data["frames"][0].pop("pts")
            elif mutation == "duplicate_pts":
                data["frames"][1]["pts"] = data["frames"][0]["pts"]
            elif mutation == "reversed_pts":
                data["frames"][1]["pts"] = data["frames"][0]["pts"] - 1
            elif mutation == "dimensions":
                data["streams"][0]["width"] = video().MAX_PIXELS + 1
            elif mutation == "extra_track":
                data["streams"].append(dict(data["streams"][0], index=1))
            elif mutation == "duration":
                data["streams"][0]["duration"] = "1e999999999"
            elif mutation == "frame_stream":
                data["frames"][0]["stream_index"] = False
            else:
                data["program_version"] = None
            out = json.dumps(data).encode()
        return out, err

    monkeypatch.setattr(video(), "_run", changed)
    result = prepare(source, tmp_path)
    assert result["decision"] == "hold" and result["reasons"] == [reason]
    packet = Path(result["packet_dir"])
    assert (packet / "original.mp4").read_bytes() == source.read_bytes()
    assert result["candidates"] == [] and list(packet.glob("frame-*.png")) == []


@pytest.mark.parametrize("failure,reason", [
    ("pts", "decode_index_pts_mismatch"), ("time_base", "decode_time_base_mismatch"),
    ("partial", "partial_extraction"),
])
def test_decode_trace_and_actual_pngs_must_both_match_probe(movie, tmp_path, monkeypatch, failure, reason):
    source, _, _ = movie
    real = video()._run

    def changed(argv, **kwargs):
        out, err = real(argv, **kwargs)
        if "-vf" in argv:
            if failure == "pts":
                replacement = re.sub(rb"(n:\s*2\s+pts:)\s*-?\d+", rb"\g<1> -123", err, count=1)
                assert replacement != err
                err = replacement
            elif failure == "time_base":
                replacement = re.sub(rb"(config in time_base:)\s*\d+/\d+", rb"\g<1> 0/0", err, count=1)
                assert replacement != err
                err = replacement
            else:
                (kwargs["packet"] / "frame-002.png").unlink()
        return out, err

    monkeypatch.setattr(video(), "_run", changed)
    result = prepare(source, tmp_path)
    assert result["decision"] == "hold" and result["reasons"] == [reason]
    packet = Path(result["packet_dir"])
    assert result["candidates"] == [] and not list(packet.glob("frame-*.png"))
    assert (packet / "original.mp4").read_bytes() == source.read_bytes()


def test_source_change_during_decode_preserves_snapshot_but_holds(movie, tmp_path, monkeypatch):
    original, _, _ = movie
    source = tmp_path / "mutable.mp4"
    source.write_bytes(original.read_bytes())
    real = video()._run

    def changed(argv, **kwargs):
        result = real(argv, **kwargs)
        if "-vf" in argv:
            source.write_bytes(source.read_bytes() + b"changed by another actor")
        return result

    monkeypatch.setattr(video(), "_run", changed)
    result = prepare(source, tmp_path / "packets")
    assert result["decision"] == "hold" and result["reasons"] == ["source_changed"]
    assert (Path(result["packet_dir"]) / "original.mp4").read_bytes() == original.read_bytes()
    assert result["candidates"] == []


def test_superseded_generation_or_revision_cannot_publish_candidates(movie, tmp_path):
    source, _, _ = movie
    identity = dict(session_id="session-1", capture_id="capture-1", generation=4, revision=2, rotation=270)
    calls = 0

    def current():
        nonlocal calls
        calls += 1
        return identity if calls == 1 else dict(identity, revision=3)

    result = prepare(source, tmp_path, current_identity=current)
    assert result["decision"] == "hold" and result["reasons"] == ["stale_capture"]
    assert result["candidates"] == []


@pytest.mark.parametrize("name,value,reason", [
    ("MAX_SOURCE_BYTES", 1, "source_budget_exceeded"),
    ("MAX_DECODED_FRAMES", 3, "frame_budget_exceeded"),
    ("MAX_DURATION_SECONDS", 0, "duration_budget_exceeded"),
    ("MAX_OUTPUT_BYTES", 1, "derived_budget_exceeded"),
    ("MAX_PROBE_BYTES", 1, "decoder_output_budget_exceeded"),
])
def test_budgets_hold_without_truncation_or_registration(movie, tmp_path, monkeypatch, name, value, reason):
    source, _, _ = movie
    monkeypatch.setattr(video(), name, value)
    result = video().prepare_video_candidates(source, tmp_path, session_id="s", capture_id="c",
                                              generation=1, revision=0, rotation=0, frame_indices=(0,))
    assert result["decision"] == "hold" and result["reasons"] == [reason]
    assert result["candidates"] == [] and result["auto_registration_allowed"] is False


def test_real_subprocess_deadline_and_pipe_limits_are_enforced():
    with pytest.raises(video()._Hold, match="decoder_timeout"):
        video()._run([sys.executable, "-c", "import time; time.sleep(5)"],
                     deadline=time.monotonic() + .03, stdout_limit=100, stderr_limit=100)
    with pytest.raises(video()._Hold, match="decoder_output_budget_exceeded"):
        video()._run([sys.executable, "-c", "import sys; sys.stdout.write('x'*10000)"],
                     deadline=time.monotonic() + 5, stdout_limit=20, stderr_limit=100)


def test_receipt_write_failure_cannot_return_success(movie, tmp_path, monkeypatch):
    source, _, _ = movie
    real = Path.write_text

    def failed(path, *args, **kwargs):
        if path.name == "report.json.partial":
            raise OSError("full storage")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", failed)
    result = prepare(source, tmp_path)
    assert result["decision"] == "hold" and result["reasons"] == ["receipt_persistence_failed"]
    assert result["candidates"] == []
    assert (Path(result["packet_dir"]) / "original.mp4").is_file()


def test_cli_returns_comparison_receipt_and_hold_exit_codes(movie, tmp_path, capsys):
    source, _, _ = movie
    cli = importlib.import_module("scripts.capture_video")
    argv = [str(source), "--out", str(tmp_path), "--session-id", "s", "--capture-id", "c",
            "--generation", "1", "--revision", "0", "--rotation", "0", "--frame-index", "2"]
    assert cli.main(argv) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["decision"] == "comparison_only" and Path(result["report"]).is_file()
    assert cli.main([*argv, "--frame-index", "999"]) == 2
    assert json.loads(capsys.readouterr().out)["decision"] == "hold"


def test_same_scene_blur_proxy_does_not_become_character_approval(movie, tmp_path):
    source, _, probe = movie
    scene = {"scene_id": "same", "start_pts": probe["frames"][0]["pts"],
             "end_pts": probe["frames"][2]["pts"], "origin": "decoded_video",
             "time_base": probe["streams"][0]["time_base"]}
    result = video().prepare_video_candidates(source, tmp_path, session_id="s", capture_id="c",
                                              generation=0, revision=0, rotation=0,
                                              frame_indices=(0, 1), scene_intervals=(scene,))
    assert result["decision"] == "comparison_only", result
    assert result["comparisons"][0]["ranked_indices"] == [0, 1]
    assert result["guarantees_all_content"] is False
    assert result["comparisons"][0]["calibrated"] is False
    assert all(c["metrics"]["focus"]["calibrated"] is False for c in result["candidates"])


def test_container_display_rotation_is_not_automatically_applied(movie, tmp_path):
    source, references, _ = movie
    rotated = tmp_path / "display-rotated.mp4"
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(source),
         "-c", "copy", "-metadata:s:v:0", "rotate=90", str(rotated)])
    result = prepare(rotated, tmp_path / "packets")
    assert result["decision"] == "comparison_only", result
    for item in result["candidates"]:
        with Image.open(Path(result["packet_dir"]) / item["file"]) as image, Image.open(
                references / f"reference-{item['decoded_index'] + 1:03d}.png") as expected:
            assert image.size == (160, 120)
            assert ImageChops.difference(image.convert("RGB"), expected.convert("RGB")).getbbox() is None


@pytest.mark.parametrize("mutation,reason", [
    ({"origin": "camera_sensor"}, "scene_mapping_unknown"),
    ({"time_base": "1/1000"}, "scene_mapping_unknown"),
    ({"start_pts": True}, "invalid_scene_intervals"),
    ({"scene_id": "../outside"}, "invalid_scene_intervals"),
])
def test_scene_timebase_or_sensor_mapping_is_never_guessed(movie, tmp_path, mutation, reason):
    source, _, probe = movie
    scene = {"scene_id": "s", "start_pts": probe["frames"][0]["pts"],
             "end_pts": probe["frames"][-1]["pts"] + 1, "origin": "decoded_video",
             "time_base": probe["streams"][0]["time_base"]}
    result = prepare(source, tmp_path, scene_intervals=(dict(scene, **mutation),))
    assert result["decision"] == "hold" and result["reasons"] == [reason]
    assert result["candidates"] == []


def test_corrupt_movie_is_retained_and_unavailable_identity_creates_no_packet(tmp_path):
    source = tmp_path / "broken.mp4"
    source.write_bytes(b"not an MP4")
    result = prepare(source, tmp_path / "packets")
    assert result["decision"] == "hold"
    assert (Path(result["packet_dir"]) / "original.mp4").read_bytes() == b"not an MP4"
    assert result["candidates"] == []

    def unavailable():
        raise RuntimeError("session disappeared")

    result = prepare(source, tmp_path / "no-packets", current_identity=unavailable)
    assert result["reasons"] == ["current_identity_unavailable"]
    assert not (tmp_path / "no-packets").exists()


def test_output_traversal_never_writes_outside_the_selected_root(movie, tmp_path):
    source, _, _ = movie
    outside = tmp_path / ".." / "must-not-create-video-packet"
    result = prepare(source, outside)
    assert result["decision"] == "hold" and result["packet_dir"] is None
    assert not outside.exists()
    assert source.is_file()


def test_failed_partial_cleanup_is_still_a_hold_and_keeps_original(movie, tmp_path, monkeypatch):
    source, _, _ = movie
    real = Path.unlink

    def unavailable(path, *args, **kwargs):
        if path.name.startswith("frame-"):
            raise OSError("storage cleanup unavailable")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unavailable)
    identity = dict(session_id="session-1", capture_id="capture-1", generation=4, revision=2, rotation=270)
    calls = 0

    def stale():
        nonlocal calls
        calls += 1
        return identity if calls == 1 else dict(identity, generation=5)

    result = prepare(source, tmp_path, current_identity=stale)
    assert result["decision"] == "hold" and result["candidates"] == []
    assert (Path(result["packet_dir"]) / "original.mp4").read_bytes() == source.read_bytes()

"""Bounded local-MP4 comparisons, without camera, upload, AI or page approval.

The caller chooses a few real decoded frame indices. One probe and one selected
decode bind those frames to observed integer PTS; a nearest-time seek is never
an exact-frame receipt. These evaluation budgets are not booklet page limits.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
import threading
import time
from fractions import Fraction
from pathlib import Path
from typing import Callable

from PIL import Image

from scripts.capture_preflight import MAX_PIXELS
from scripts.capture_quality import measure_tile

MAX_SOURCE_BYTES = 128 * 1024 * 1024
MAX_DURATION_SECONDS = 60
MAX_DECODED_FRAMES = 1800
MAX_CANDIDATES = 12
MAX_OUTPUT_BYTES = 256 * 1024 * 1024
MAX_PROBE_BYTES = 2 * 1024 * 1024
MAX_TRACE_BYTES = 2 * 1024 * 1024
PROCESS_SECONDS = 60
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_TRACE = re.compile(r"\[Parsed_showinfo_0 @ [^\]]+\].*?n:\s*(\d+)\s+pts:\s*(-?\d+)\s.*?s:(\d+)x(\d+)")
_TIMEBASE = re.compile(r"\[Parsed_showinfo_0 @ [^\]]+\].*?config in time_base:\s*(\d+)/(\d+)")


class _Hold(Exception):
    pass


def _integer(value: object, minimum: int, maximum: int = 2**63 - 1) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _time_base(value: object) -> Fraction:
    if type(value) is not str or not re.fullmatch(r"[1-9]\d{0,18}/[1-9]\d{0,18}", value):
        raise _Hold("unsupported_time_base")
    numerator, denominator = map(int, value.split("/"))
    if max(numerator, denominator) > 2**63 - 1:
        raise _Hold("unsupported_time_base")
    return Fraction(numerator, denominator)


def _hash(path: Path) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            size += len(block)
            if size > MAX_SOURCE_BYTES:
                raise _Hold("source_budget_exceeded")
            digest.update(block)
    return digest.hexdigest(), size


def _current(callback: Callable | None, expected: dict) -> None:
    if callback is None:
        return
    try:
        actual = callback()
    except Exception as error:  # noqa: BLE001 - unavailable identity never admits a comparison
        raise _Hold("current_identity_unavailable") from error
    if (type(actual) is not dict or actual.keys() != expected.keys()
            or any(type(actual[key]) is not type(value) or actual[key] != value
                   for key, value in expected.items())):
        raise _Hold("stale_capture")


def _run(argv: list[str], *, deadline: float, stdout_limit: int, stderr_limit: int,
         packet: Path | None = None) -> tuple[bytes, bytes]:
    """Drain bounded pipes while watching one process and its own PNG outputs."""
    buffers = [bytearray(), bytearray()]
    overflow = threading.Event()
    with subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, shell=False) as process:
        def drain(stream, target, limit):
            try:
                while block := stream.read(64 * 1024):
                    if len(target) + len(block) > limit:
                        overflow.set()
                        process.kill()
                        return
                    target.extend(block)
            except OSError:
                overflow.set()

        readers = [threading.Thread(target=drain, args=(stream, buffers[i], limit), daemon=True)
                   for i, (stream, limit) in enumerate(((process.stdout, stdout_limit),
                                                       (process.stderr, stderr_limit)))]
        for reader in readers:
            reader.start()
        reason = None
        try:
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    reason = "decoder_timeout"
                    break
                if overflow.is_set():
                    reason = "decoder_output_budget_exceeded"
                    break
                if packet is not None and sum(p.stat().st_size for p in packet.glob("frame-*.png")) > MAX_OUTPUT_BYTES:
                    reason = "derived_budget_exceeded"
                    break
                try:
                    process.wait(timeout=min(.05, max(.001, deadline - time.monotonic())))
                except subprocess.TimeoutExpired:
                    pass
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            for reader in readers:
                reader.join(timeout=5)
        if reason:
            raise _Hold(reason)
        if overflow.is_set() or any(reader.is_alive() for reader in readers):
            raise _Hold("decoder_output_budget_exceeded")
        if process.returncode:
            raise _Hold("decoder_failed")
    return bytes(buffers[0]), bytes(buffers[1])


def _json(data: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise _Hold("invalid_probe")
            result[key] = value
        return result

    try:
        result = json.loads(data, object_pairs_hook=pairs,
                            parse_constant=lambda _: (_ for _ in ()).throw(_Hold("invalid_probe")))
    except (ValueError, RecursionError) as error:
        raise _Hold("invalid_probe") from error
    if type(result) is not dict:
        raise _Hold("invalid_probe")
    return result


def _probe(data: bytes) -> tuple[dict, list[dict], str]:
    value = _json(data)
    streams, frames = value.get("streams"), value.get("frames")
    if (type(streams) is not list or len(streams) != 1
            or type(streams[0]) is not dict or streams[0].get("codec_type") != "video"):
        raise _Hold("unsupported_video_tracks")
    stream = streams[0]
    if (type(value.get("format")) is not dict
            or "mp4" not in str(value["format"].get("format_name", "")).split(",")):
        raise _Hold("unsupported_container")
    width, height, index = stream.get("width"), stream.get("height"), stream.get("index")
    if (not _integer(width, 2, MAX_PIXELS) or not _integer(height, 2, MAX_PIXELS)
            or width * height > MAX_PIXELS or not _integer(index, 0, 255)
            or type(stream.get("codec_name")) is not str):
        raise _Hold("unsupported_video_dimensions")
    base = _time_base(stream.get("time_base"))
    if type(frames) is not list or not frames:
        raise _Hold("missing_frames")
    if len(frames) > MAX_DECODED_FRAMES:
        raise _Hold("frame_budget_exceeded")
    previous = None
    for frame in frames:
        if (type(frame) is not dict or not _integer(frame.get("pts"), -(2**63))
                or not _integer(frame.get("stream_index"), 0, 255) or frame["stream_index"] != index
                or type(frame.get("width")) is not int or frame["width"] != width
                or type(frame.get("height")) is not int or frame["height"] != height):
            raise _Hold("missing_or_unsupported_frame_pts")
        if previous is not None and frame["pts"] <= previous:
            raise _Hold("ambiguous_frame_pts")
        previous = frame["pts"]
    try:
        if (type(stream.get("duration")) is not str
                or not re.fullmatch(r"\d{1,12}(?:\.\d{1,9})?", stream["duration"])):
            raise _Hold("unsupported_duration")
        duration = Fraction(stream["duration"])
    except (KeyError, ValueError, TypeError, ZeroDivisionError) as error:
        raise _Hold("unsupported_duration") from error
    if duration <= 0 or duration > MAX_DURATION_SECONDS or (frames[-1]["pts"] - frames[0]["pts"]) * base > MAX_DURATION_SECONDS:
        raise _Hold("duration_budget_exceeded")
    program = value.get("program_version", {})
    if type(program) is not dict or type(program.get("version", "unreported")) is not str:
        raise _Hold("invalid_probe")
    return stream, frames, program.get("version", "unreported")[:160]


def _scenes(intervals: tuple, time_base: str) -> list[dict]:
    if type(intervals) is not tuple or len(intervals) > MAX_CANDIDATES:
        raise _Hold("invalid_scene_intervals")
    result, names = [], set()
    for item in intervals:
        if (type(item) is not dict or set(item) != {"scene_id", "start_pts", "end_pts", "time_base", "origin"}
                or type(item["scene_id"]) is not str or not _ID.fullmatch(item["scene_id"])
                or item["scene_id"] in names or not _integer(item["start_pts"], -(2**63))
                or not _integer(item["end_pts"], -(2**63)) or item["start_pts"] >= item["end_pts"]):
            raise _Hold("invalid_scene_intervals")
        if item["origin"] != "decoded_video" or item["time_base"] != time_base:
            raise _Hold("scene_mapping_unknown")
        names.add(item["scene_id"])
        result.append(dict(item))
    result.sort(key=lambda row: row["start_pts"])
    if any(a["end_pts"] > b["start_pts"] for a, b in zip(result, result[1:])):
        raise _Hold("ambiguous_scene_intervals")
    return result


def _verify_trace(data: bytes, stream: dict, frames: list[dict], indices: tuple[int, ...]) -> str:
    text = data.decode("utf-8", errors="replace")
    bases = _TIMEBASE.findall(text)
    try:
        if len(bases) != 1 or _time_base("/".join(bases[0])) != _time_base(stream["time_base"]):
            raise _Hold("decode_time_base_mismatch")
    except _Hold as error:
        raise _Hold("decode_time_base_mismatch") from error
    observed = _TRACE.findall(text)
    if not observed or len(observed) > len(frames):
        raise _Hold("decode_index_pts_mismatch")
    for expected, (index, pts, width, height) in enumerate(observed):
        if (int(index) != expected or int(pts) != frames[expected]["pts"]
                or (int(width), int(height)) != (stream["width"], stream["height"])):
            raise _Hold("decode_index_pts_mismatch")
    if max(indices) >= len(observed):
        raise _Hold("partial_extraction")
    version = re.search(r"^ffmpeg version (\S+)", text, re.MULTILINE)
    return version.group(1)[:160] if version else "unreported"


def _discard_pngs(packet: Path) -> bool:
    clean = True
    for path in packet.glob("frame-*.png"):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            clean = False
    return clean


def prepare_video_candidates(source: Path, output_root: Path, *, session_id: str, capture_id: str,
                             generation: int, revision: int, rotation: int,
                             frame_indices: tuple[int, ...], scene_intervals: tuple[dict, ...] = (),
                             current_identity: Callable | None = None) -> dict:
    """Compare explicitly requested frames; never approve a page or select a booklet.

    Successful packets keep a full original.mp4 snapshot and every requested PNG.
    A failed packet keeps that original and a hold receipt, removing only its own
    partial PNGs. No current-identity callback means no external freshness claim.
    """
    report = {"schema": 1, "decision": "hold", "reasons": [], "capture": None, "source": None,
              "candidates": [], "comparisons": [], "scene_intervals": [], "packet_dir": None,
              "receipt_file": None,
              "guarantees_all_content": False, "auto_registration_allowed": False,
              "scope": "local_requested_video_frames_only",
              "not_implemented": ["camera_recording", "phone_transfer", "automatic_full_video_selection",
                                  "AI_inspection", "all_page_or_character_acceptance", "venue_acceptance"],
              "budgets": {"source_bytes": MAX_SOURCE_BYTES, "duration_seconds": MAX_DURATION_SECONDS,
                          "decoded_frames": MAX_DECODED_FRAMES, "requested_frames": MAX_CANDIDATES,
                          "derived_bytes": MAX_OUTPUT_BYTES, "decoder_seconds": PROCESS_SECONDS}}
    packet = None
    started = time.monotonic()
    try:
        if (any(type(v) is not str or not _ID.fullmatch(v) for v in (session_id, capture_id))
                or not _integer(generation, 0) or not _integer(revision, 0)
                or type(rotation) is not int or rotation not in (0, 90, 180, 270)
                or type(frame_indices) is not tuple or not 1 <= len(frame_indices) <= MAX_CANDIDATES
                or any(not _integer(i, 0, MAX_DECODED_FRAMES - 1) for i in frame_indices)
                or len(set(frame_indices)) != len(frame_indices)
                or (current_identity is not None and not callable(current_identity))):
            raise _Hold("invalid_arguments")
        identity = {"session_id": session_id, "capture_id": capture_id, "generation": generation,
                    "revision": revision, "rotation": rotation}
        report["capture"] = identity
        if (not isinstance(source, (str, Path)) or not isinstance(output_root, (str, Path))
                or re.match(r"(?i)^[a-z][a-z0-9+.-]*:", str(source)) and not re.match(r"^[A-Za-z]:[\\/]", str(source))
                or str(source).startswith(("//", "\\\\")) or "\x00" in str(source)):
            raise _Hold("invalid_source_path")
        source, output_root = Path(source), Path(output_root)
        if (source.suffix.lower() != ".mp4" or source.is_symlink() or not source.is_file()
                or ".." in output_root.parts or output_root.is_symlink()
                or (output_root.exists() and not output_root.is_dir())):
            raise _Hold("invalid_source_or_output_path")
        source = source.resolve(strict=True)
        if not 0 < source.stat().st_size <= MAX_SOURCE_BYTES:
            raise _Hold("source_budget_exceeded")
        _current(current_identity, identity)
        ffprobe, ffmpeg = shutil.which("ffprobe"), shutil.which("ffmpeg")
        if not ffprobe or not ffmpeg:
            raise _Hold("decoder_unavailable")
        output_root.mkdir(parents=True, exist_ok=True)
        packet = Path(tempfile.mkdtemp(prefix="video-", dir=output_root)).resolve()
        report["packet_dir"] = str(packet)
        snapshot = packet / "original.mp4"
        digest, size = hashlib.sha256(), 0
        with source.open("rb") as original, snapshot.open("xb") as saved:
            while block := original.read(1024 * 1024):
                size += len(block)
                if size > MAX_SOURCE_BYTES:
                    raise _Hold("source_budget_exceeded")
                digest.update(block)
                saved.write(block)
        report["source"] = {"file": "original.mp4", "sha256": digest.hexdigest(), "bytes": size}
        if _hash(source) != (digest.hexdigest(), size):
            raise _Hold("source_changed")
        deadline = time.monotonic() + PROCESS_SECONDS
        probe, _ = _run([ffprobe, "-v", "error", "-protocol_whitelist", "file", "-select_streams", "v",
                         "-show_frames", "-show_streams", "-show_format", "-show_program_version",
                         "-show_entries", "format=format_name:program_version=version:stream=index,codec_type,codec_name,width,height,time_base,duration:frame=stream_index,pts,width,height",
                         "-of", "json", str(snapshot)], deadline=deadline,
                        stdout_limit=MAX_PROBE_BYTES, stderr_limit=64 * 1024)
        stream, frames, probe_version = _probe(probe)
        indices = tuple(sorted(frame_indices))
        if max(indices) >= len(frames):
            raise _Hold("frame_index_unavailable")
        scenes = _scenes(scene_intervals, stream["time_base"])
        report["scene_intervals"] = scenes
        report["source"].update({"dimensions": [stream["width"], stream["height"]],
                                  "codec": stream["codec_name"], "stream_index": stream["index"],
                                  "time_base": stream["time_base"], "observed_frame_count": len(frames)})
        select = "+".join(f"eq(n\\,{i})" for i in indices)
        _, trace = _run([ffmpeg, "-nostdin", "-loglevel", "info", "-copyts", "-noautorotate",
                         "-protocol_whitelist", "file", "-i", str(snapshot), "-map", f"0:{stream['index']}",
                         "-an", "-sn", "-dn", "-vf", f"showinfo,select={select}",
                         "-fps_mode", "passthrough", "-frames:v", str(len(indices)),
                         "-pix_fmt", "rgb24", "-c:v", "png", "-threads:v", "1",
                         "-f", "image2", str(packet / "frame-%03d.png")], deadline=deadline,
                        stdout_limit=1024, stderr_limit=MAX_TRACE_BYTES, packet=packet)
        ffmpeg_version = _verify_trace(trace, stream, frames, indices)
        paths = sorted(packet.glob("frame-*.png"))
        if [p.name for p in paths] != [f"frame-{i:03d}.png" for i in range(1, len(indices) + 1)]:
            raise _Hold("partial_extraction")
        if sum(p.stat().st_size for p in paths) > MAX_OUTPUT_BYTES:
            raise _Hold("derived_budget_exceeded")
        candidates = []
        for index, path in zip(indices, paths):
            if path.is_symlink():
                raise _Hold("invalid_derived_path")
            pts = frames[index]["pts"]
            scene = next((s["scene_id"] for s in scenes if s["start_pts"] <= pts < s["end_pts"]), None)
            with Image.open(path) as image:
                if (image.format != "PNG" or getattr(image, "n_frames", 1) != 1
                        or image.size != (stream["width"], stream["height"])):
                    raise _Hold("derived_dimensions_mismatch")
                metrics = measure_tile(image)
            candidates.append({"source_kind": "video_frame", "decoded_index": index, "pts": pts,
                               "time_base": stream["time_base"], "file": path.name,
                               "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                               "dimensions": [stream["width"], stream["height"]],
                               "rotation": rotation, "scene_id": scene, "metrics": metrics})
        if _hash(source) != (digest.hexdigest(), size) or _hash(snapshot) != (digest.hexdigest(), size):
            raise _Hold("source_changed")
        _current(current_identity, identity)
        report["candidates"] = candidates
        for scene in scenes:
            group = [c for c in candidates if c["scene_id"] == scene["scene_id"]]
            if len(group) < 2:
                continue
            if all(type(c["metrics"]["focus"].get("laplacian_variance")) in (int, float)
                   and math.isfinite(c["metrics"]["focus"]["laplacian_variance"]) for c in group):
                group.sort(key=lambda c: c["metrics"]["focus"]["laplacian_variance"], reverse=True)
                report["comparisons"].append({"scene_id": scene["scene_id"],
                                              "ranked_indices": [c["decoded_index"] for c in group],
                                              "metric": "laplacian_variance_proxy", "calibrated": False})
        report.update(decision="comparison_only", reasons=[],
                      tools={"ffprobe": probe_version, "ffmpeg": ffmpeg_version},
                      implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      current_identity_checked=current_identity is not None)
    except _Hold as error:
        report["reasons"] = [str(error)]
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError, subprocess.SubprocessError):
        report["reasons"] = ["media_or_storage_unavailable"]
    if report["decision"] == "hold":
        report["candidates"], report["comparisons"] = [], []
        if packet is not None:
            report["partial_derivatives_removed"] = _discard_pngs(packet)
    report["component_elapsed_seconds"] = round(time.monotonic() - started, 6)
    if packet is not None:
        try:
            report["receipt_file"] = "report.json"
            temporary = packet / "report.json.partial"
            temporary.write_text(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2)
                                 + "\n", encoding="utf-8")
            temporary.replace(packet / "report.json")
        except OSError:
            report.update(decision="hold", reasons=["receipt_persistence_failed"], receipt_file=None,
                          candidates=[], comparisons=[])
            report["partial_derivatives_removed"] = _discard_pngs(packet)
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass  # A partial receipt has no committed receipt_file and cannot admit images.
    return report

"""Automatic, uncalibrated temporal nominations for bounded video diagnostics.

No group is a physical page identity. Every decoded interval remains unknown,
including similar fine detail, blank/blurred frames and intervals over budget.
Camera2 timestamps are deliberately not accepted as decoded video timestamps.
"""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path
import shutil
import tempfile
import time

from . import capture_video as video

PROXY_WIDTH, PROXY_HEIGHT = 96, 72
PROXY_BYTES = PROXY_WIDTH * PROXY_HEIGHT


def group_proxy_frames(path: Path, frames: list[dict], time_base: str) -> list[dict]:
    """Bounded proxy hypotheses; never global pHash deduplication or approval."""
    groups, previous = [], None
    base = Fraction(time_base)
    with path.open("rb") as source:
        for index, frame in enumerate(frames):
            raw = source.read(PROXY_BYTES)
            if len(raw) != PROXY_BYTES:
                raise ValueError("partial proxy decode")
            delta = sum(abs(a - b) for a, b in zip(previous, raw)) / PROXY_BYTES if previous is not None else None
            # A time cut limits long unchanged hypotheses; neither this nor the
            # uncalibrated change threshold certifies fine-character sameness.
            cut = not groups or delta > 8 or (frame["pts"] - groups[-1]["start_pts"]) * base >= Fraction(1, 2)
            if cut:
                groups.append({"first_index": index, "last_index": index, "start_pts": frame["pts"],
                               "end_pts": frame["pts"], "time_base": time_base, "origin": "decoded_video",
                               "nominated_index": index, "coverage": "unknown", "calibrated": False})
            group = groups[-1]
            group.update(last_index=index, end_pts=frame["pts"])
            # Nominate the last stable observation, not a cross-page focus win.
            # A flat/blurred group is still nominated and retained as unknown.
            if previous is not None and delta <= 8:
                group["nominated_index"] = index
            previous = raw
        if source.read(1):
            raise ValueError("unexpected proxy frames")
    return groups


def _uninspected(frames, selected, time_base):
    result = []
    for index, frame in enumerate(frames):
        if index in selected:
            continue
        if not result or result[-1]["last_index"] != index - 1:
            result.append({"first_index": index, "last_index": index, "start_pts": frame["pts"],
                           "end_pts": frame["pts"], "time_base": time_base, "coverage": "unknown"})
        else:
            result[-1].update(last_index=index, end_pts=frame["pts"])
    return result


def nominate_video_frames(source: Path, output: Path, *, source_sha256: str, owner: dict,
                           check_current=None) -> dict:
    """Nominate chronologically then reuse the exact-index/PTS PNG extractor.

    Only sealed local clips within the existing comparison budgets are decoded.
    A missing decoder, stale source or exhausted candidate budget stays explicit.
    Output is a diagnostic feeder, not automatic page registration.
    """
    result = {"status": "unknown", "reasons": [], "groups": [], "uninspected_intervals": [],
              "comparison": None, "all_pages_or_characters_verified": False,
              "sensor_to_video_pts": "unknown", "candidate_budget": video.MAX_CANDIDATES}
    source, output = Path(source), Path(output)
    try:
        if source.is_symlink() or source.suffix.lower() != ".mp4" or video._hash(source)[0] != source_sha256:
            raise ValueError("video source hash changed")
        if check_current:
            check_current()
        probe_tool, decoder = shutil.which("ffprobe"), shutil.which("ffmpeg")
        if not probe_tool or not decoder:
            result["reasons"] = ["decoder_unavailable"]
            return result
        deadline = time.monotonic() + video.PROCESS_SECONDS
        raw, _ = video._run([probe_tool, "-v", "error", "-protocol_whitelist", "file", "-select_streams", "v",
            "-show_frames", "-show_streams", "-show_format", "-show_program_version", "-show_entries",
            "format=format_name:program_version=version:stream=index,codec_type,codec_name,width,height,time_base,duration:frame=stream_index,pts,width,height",
            "-of", "json", str(source)], deadline=deadline, stdout_limit=video.MAX_PROBE_BYTES, stderr_limit=64 * 1024)
        stream, frames, _ = video._probe(raw)
        output.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="proxy-", dir=output) as directory:
            proxy = Path(directory) / "proxy.gray"
            _, trace = video._run([decoder, "-nostdin", "-loglevel", "info", "-copyts", "-noautorotate",
                "-protocol_whitelist", "file", "-i", str(source), "-map", f"0:{stream['index']}", "-an", "-sn", "-dn",
                "-vf", f"showinfo,scale={PROXY_WIDTH}:{PROXY_HEIGHT}:flags=area,format=gray", "-fps_mode", "passthrough",
                "-frames:v", str(len(frames)), "-threads:v", "1", "-f", "rawvideo", str(proxy)],
                deadline=deadline, stdout_limit=1024, stderr_limit=video.MAX_TRACE_BYTES)
            video._verify_trace(trace, stream, frames, (len(frames) - 1,))
            if proxy.stat().st_size != len(frames) * PROXY_BYTES:
                raise ValueError("partial proxy decode")
            groups = group_proxy_frames(proxy, frames, stream["time_base"])
        selected = tuple(group["nominated_index"] for group in groups[:video.MAX_CANDIDATES])
        result.update(groups=groups, uninspected_intervals=_uninspected(frames, set(selected), stream["time_base"]))
        for number, group in enumerate(groups):
            group["diagnostic_status"] = "nominated" if number < video.MAX_CANDIDATES else "deferred_candidate_budget"
        if check_current:
            check_current()
        if video._hash(source)[0] != source_sha256:
            raise ValueError("video source hash changed")
        packet = video.prepare_video_candidates(source, output, session_id=str(owner["session_id"]),
            capture_id=owner["clip_id"], generation=owner["generation"], revision=0,
            rotation=owner["rotation"], frame_indices=selected)
        # revision=0 is this existing comparison utility's revision parameter,
        # never invented native capture metadata or a physical page-turn count.
        result["comparison"] = packet
        if packet["decision"] != "comparison_only":
            result["reasons"] = packet["reasons"]
            return result
        if video._hash(source)[0] != source_sha256:
            raise ValueError("video source hash changed")
        if check_current:
            check_current()
        result["status"] = "nominated"
    except (OSError, ValueError, TypeError, KeyError, video._Hold) as error:
        result.update(status="unknown", reasons=[str(error)[:160] or "video_unavailable"])
    return result

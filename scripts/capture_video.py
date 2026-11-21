"""Compare requested local MP4 frame indices; no recording, transfer or page approval.

Run with python -m scripts.capture_video. Existing ffmpeg/ffprobe are required;
this command never installs tools or sends the original or candidates anywhere.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.capture_video import prepare_video_candidates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--capture-id", required=True)
    parser.add_argument("--generation", type=int, required=True)
    parser.add_argument("--revision", type=int, required=True)
    parser.add_argument("--rotation", type=int, choices=(0, 90, 180, 270), required=True)
    parser.add_argument("--frame-index", type=int, action="append", required=True)
    parser.add_argument("--scenes", type=Path,
                        help="local JSON list of decoded_video intervals with integer PTS/time_base")
    args = parser.parse_args(argv)
    try:
        scenes = []
        if args.scenes is not None:
            if not args.scenes.is_file() or args.scenes.stat().st_size > 16 * 1024:
                raise ValueError("invalid scene file")
            scenes = json.loads(args.scenes.read_text(encoding="utf-8"))
            if type(scenes) is not list:
                raise ValueError("invalid scene list")
    except (OSError, ValueError, UnicodeError, RecursionError):
        print(json.dumps({"decision": "hold", "reasons": ["invalid_scene_file"], "report": None}))
        return 2
    result = prepare_video_candidates(args.video, args.out, session_id=args.session_id,
                                      capture_id=args.capture_id, generation=args.generation,
                                      revision=args.revision, rotation=args.rotation,
                                      frame_indices=tuple(args.frame_index), scene_intervals=tuple(scenes))
    report = str(Path(result["packet_dir"]) / result["receipt_file"]) if result["receipt_file"] else None
    print(json.dumps({"decision": result["decision"], "reasons": result["reasons"], "report": report}))
    return 0 if result["decision"] == "comparison_only" else 2


if __name__ == "__main__":
    raise SystemExit(main())

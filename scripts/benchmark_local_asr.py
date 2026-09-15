"""Measure the configured local ASR on a supplied mono PCM16/16 kHz WAV, without printing speech."""

import argparse
import io
import json
import sys
import tempfile
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.local_asr import transcribe_chunk  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", type=Path)
    args = parser.parse_args()
    started = time.monotonic()
    results = []
    with wave.open(str(args.wav), "rb") as source, tempfile.TemporaryDirectory(prefix="rokid-benchmark-") as work:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, 16000):
            raise ValueError("requires mono PCM16/16 kHz WAV")
        total = source.getnframes()
        for offset in range(0, total, 480000):
            start = max(0, offset - 16000)
            source.setpos(start)
            data = source.readframes(min(total-offset, 480000) + offset-start)
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as target:
                target.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                target.writeframes(data)
            path = Path(work) / "chunk.wav"
            path.write_bytes(buffer.getvalue())
            result = transcribe_chunk(path, start_sample=start)
            results.append({"start_sample": start, "samples": result["samples"],
                            "asr_seconds": result["asr_seconds"], "real_time_factor": result["real_time_factor"],
                            "segments": len(result["segments"]),
                            "bounds_ms": [[s["start_ms"], s["end_ms"]] for s in result["segments"]]})
    elapsed = time.monotonic() - started
    print(json.dumps({"audio_seconds": total/16000, "wall_seconds": round(elapsed, 3),
                      "real_time_factor": round(elapsed/(total/16000), 3) if total else None,
                      "chunks": results}))


if __name__ == "__main__":
    main()

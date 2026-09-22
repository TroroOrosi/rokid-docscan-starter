"""On-phone whisper.cpp CLI + Silero VAD. No cloud ASR or shell execution."""

import json
import os
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path

# ponytail: one phone / one model process; use a resident worker only if model reload dominates.
_MODEL_LOCK = threading.Lock()


def local_asr_settings():
    paths = [os.environ.get(key, "") for key in (
        "ROKID_WHISPER_CLI", "ROKID_WHISPER_MODEL", "ROKID_WHISPER_VAD_MODEL")]
    if any(not path or not Path(path).is_file() for path in paths):
        raise ValueError("local ASR requires whisper-cli, English model and Silero VAD model paths")
    return paths


def wav_samples(path):
    with wave.open(str(path), "rb") as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate(), source.getcomptype()) != (1, 2, 16000, "NONE"):
            raise ValueError("listening requires mono PCM16 WAV at 16000 Hz")
        count = source.getnframes()
        if count < 1 or count > 31 * 16000 or len(source.readframes(count)) != count * 2:
            raise ValueError("invalid or oversized listening chunk")
        return count


def transcribe_chunk(path, *, start_sample=0):
    samples = wav_samples(path)
    cli, model, vad = local_asr_settings()
    with _MODEL_LOCK, tempfile.TemporaryDirectory(prefix="rokid-asr-") as work:
        output = str(Path(work) / "result")
        started = time.monotonic()
        # v1.8.3 remaps segment offsets to the ORIGINAL WAV timeline after VAD.
        # Token timestamps are not used (they follow a different mapping path).
        try:
            subprocess.run([
                cli, "-m", model, "-f", str(Path(path).resolve()), "-l", "en",
                "-t", "4", "-ojf", "-of", output, "--vad", "--vad-model", vad,
                "--vad-speech-pad-ms", "200", "--no-prints",
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=300, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError) as error:
            raise ValueError("local ASR failed; original recording retained") from error
        result_path = Path(output + ".json")
        if not result_path.is_file() or result_path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("local ASR did not produce bounded JSON")
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        rows = payload.get("transcription") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or len(rows) > 1000:
            raise ValueError("invalid ASR segments")
        segments = []
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("offsets"), dict):
                raise ValueError("invalid ASR segment")
            if not {"from", "to"}.issubset(row["offsets"]) or "text" not in row:
                raise ValueError("missing ASR segment fields")
            start, end = row["offsets"]["from"], row["offsets"]["to"]
            text = row["text"]
            if (type(start) is not int or type(end) is not int or not 0 <= start <= min(end, samples // 16)
                    or end > samples / 16 + 100
                    or not isinstance(text, str) or len(text) > 10000):
                raise ValueError("invalid ASR timestamp or text")
            if not text.strip():
                continue
            tokens = row.get("tokens", [])
            if not isinstance(tokens, list) or any(not isinstance(token, dict) for token in tokens):
                raise ValueError("invalid ASR tokens")
            uncertain = not tokens or any(isinstance(token.get("p"), (float, int)) and token["p"] < .5 for token in tokens)
            segments.append({"start_ms": start_sample // 16 + start,
                             "end_ms": start_sample // 16 + min(end, samples // 16),
                             "text": text.strip(), "needs_audio_check": uncertain})
        elapsed = time.monotonic() - started
        return {"segments": segments, "samples": samples, "asr_seconds": round(elapsed, 3),
                "real_time_factor": round(elapsed / (samples / 16000), 3)}

import json
import wave
from pathlib import Path

import pytest

from app.local_asr import transcribe_chunk


def test_local_vad_asr_preserves_original_timeline_and_reports_failure(tmp_path, monkeypatch):
    for key in ("ROKID_WHISPER_CLI", "ROKID_WHISPER_MODEL", "ROKID_WHISPER_VAD_MODEL"):
        p = tmp_path / key
        p.write_bytes(b"model placeholder")
        monkeypatch.setenv(key, str(p))
    path = tmp_path / "chunk.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\x00\x00" * 16000)

    def cli(args, **kwargs):
        assert "--vad" in args and args[args.index("-l") + 1] == "en"
        assert kwargs["stderr"] is not None and kwargs["timeout"] == 300
        Path(args[args.index("-of") + 1] + ".json").write_text(json.dumps({"transcription": [
            {"offsets": {"from": 200, "to": 800}, "text": "Question two", "tokens": [{"p": .4}]}]}))
    monkeypatch.setattr("app.local_asr.subprocess.run", cli)
    result = transcribe_chunk(path, start_sample=480000)
    assert result["segments"] == [{"start_ms": 30200, "end_ms": 30800, "text": "Question two", "needs_audio_check": True}]
    monkeypatch.delenv("ROKID_WHISPER_MODEL")
    with pytest.raises(ValueError, match="requires"):
        transcribe_chunk(path)
    assert path.exists()

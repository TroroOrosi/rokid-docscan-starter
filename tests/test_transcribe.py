"""Tests for listening-mode transcription (offline-safe, provider-agnostic).

Exercises the whole real path via an injected fake SDK (no network, no creds):
  * openai  -> audio.transcriptions.create(...).text
  * gemini  -> models.generate_content(...).text
  * no transcriber / no audio / exception -> provided transcript fallback
"""

from types import SimpleNamespace

from app.llm import LLMClient, _audio_media_type
from app.transcribe import transcribe_audio


def _openai_client(text: str) -> LLMClient:
    sdk = SimpleNamespace(
        audio=SimpleNamespace(
            transcriptions=SimpleNamespace(
                create=lambda **kw: SimpleNamespace(text=text)
            )
        )
    )
    return LLMClient(sdk, provider="openai", model="gpt-4o-transcribe")


def _gemini_client(text: str) -> LLMClient:
    sdk = SimpleNamespace(
        models=SimpleNamespace(generate_content=lambda **kw: SimpleNamespace(text=text))
    )
    return LLMClient(sdk, provider="gemini", model="gemini-test")


def _write_audio(tmp_path, name="rec.wav", data=b"RIFF0000WAVEdata"):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def test_openai_transcribes(tmp_path):
    path = _write_audio(tmp_path)
    out = transcribe_audio(path, client=_openai_client("hello world"))
    assert out == "hello world"


def test_gemini_transcribes(tmp_path):
    path = _write_audio(tmp_path)
    out = transcribe_audio(path, client=_gemini_client("bonjour"))
    assert out == "bonjour"


def test_no_transcriber_uses_provided_transcript(tmp_path):
    path = _write_audio(tmp_path)
    # client=None and (in tests) no ROKID_TRANSCRIBER configured -> fallback.
    out = transcribe_audio(path, provided_transcript="given text", client=None)
    assert out == "given text"


def test_no_audio_uses_provided_transcript():
    out = transcribe_audio(None, provided_transcript="only text", client=_openai_client("x"))
    assert out == "only text"


def test_empty_model_reply_falls_back(tmp_path):
    path = _write_audio(tmp_path)
    out = transcribe_audio(path, provided_transcript="fb", client=_openai_client("   "))
    assert out == "fb"


def test_exception_falls_back(tmp_path):
    path = _write_audio(tmp_path)

    def boom(**kw):
        raise RuntimeError("network down")

    sdk = SimpleNamespace(
        audio=SimpleNamespace(transcriptions=SimpleNamespace(create=boom))
    )
    client = LLMClient(sdk, provider="openai", model="m")
    out = transcribe_audio(path, provided_transcript="safe", client=client)
    assert out == "safe"


def test_transcriber_setup_failure_falls_back(tmp_path, monkeypatch):
    """Configured provider whose SDK is missing must not 500: use the transcript."""
    import app.transcribe as tr
    from app.llm import LLMConfigError

    path = _write_audio(tmp_path)
    monkeypatch.setattr(tr.config, "TRANSCRIBER", "openai")
    monkeypatch.setattr(tr, "_provider_key", lambda provider: "key-present")

    def _boom(provider):
        raise LLMConfigError("openai SDK not installed")

    monkeypatch.setattr(tr, "_build_sdk", _boom)
    # client=None -> _load_transcriber runs, raises inside the guard -> fallback.
    assert tr.transcribe_audio(path, provided_transcript="fb", client=None) == "fb"


def test_audio_media_type_detection():
    assert _audio_media_type(b"RIFF0000WAVEmore") == "audio/wav"
    assert _audio_media_type(b"ID3xxxxx") == "audio/mpeg"
    assert _audio_media_type(b"OggS0000") == "audio/ogg"
    assert _audio_media_type(b"fLaC0000") == "audio/flac"
    assert _audio_media_type(b"\x00\x00\x00\x00") == "audio/mpeg"

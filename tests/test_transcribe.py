"""Tests for listening-mode transcription (offline-safe, provider-agnostic).

Exercises the whole real path via an injected fake SDK (no network, no creds):
  * openai  -> audio.transcriptions.create(...).text
  * gemini  -> models.generate_content(...).text
  * no transcriber / no audio / exception -> provided transcript fallback
"""

from types import SimpleNamespace

import pytest

from app.audio_formats import AUDIO_FORMATS, safe_audio_suffix
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


def test_openai_transcription_supplies_supported_filename_and_mime(tmp_path):
    captured: dict = {}

    def _create(**kw):
        captured.update(kw)
        return SimpleNamespace(text="ok")

    sdk = SimpleNamespace(
        audio=SimpleNamespace(transcriptions=SimpleNamespace(create=_create))
    )
    client = LLMClient(sdk, provider="openai", model="unused")
    audio = b"RIFF0000WAVEdata"
    assert transcribe_audio(_write_audio(tmp_path, data=audio), client=client) == "ok"
    assert captured["file"] == ("audio.wav", audio, "audio/wav")


def test_openai_id3v2_tagged_mp3_remains_supported(tmp_path):
    captured: dict = {}

    def _create(**kw):
        captured.update(kw)
        return SimpleNamespace(text="ok")

    sdk = SimpleNamespace(
        audio=SimpleNamespace(transcriptions=SimpleNamespace(create=_create))
    )
    client = LLMClient(sdk, provider="openai", model="unused")
    audio = b"ID3\x04\x00\x00\x00\x00\x00\x00\xff\xfbmp3-frame"

    assert (
        transcribe_audio(
            _write_audio(tmp_path, name="recording.mp3", data=audio),
            client=client,
        )
        == "ok"
    )
    assert captured["file"] == ("audio.mp3", audio, "audio/mpeg")


@pytest.mark.parametrize(
    "audio",
    [
        b"\xff\xf1raw-aac",
        b"ID3\x04\x00\x00\x00\x00\x00\x00\xff\xf1raw-aac",
    ],
    ids=["adts", "id3v2-adts"],
)
def test_openai_raw_aac_falls_back_without_calling_the_sdk(tmp_path, audio):
    called = False

    def _create(**kw):
        nonlocal called
        called = True
        return SimpleNamespace(text="must not be used")

    sdk = SimpleNamespace(
        audio=SimpleNamespace(transcriptions=SimpleNamespace(create=_create))
    )
    client = LLMClient(sdk, provider="openai", model="unused")
    path = _write_audio(tmp_path, name="recording.aac", data=audio)

    assert (
        transcribe_audio(path, provided_transcript="safe fallback", client=client)
        == "safe fallback"
    )
    assert called is False


@pytest.mark.parametrize(
    "audio",
    [b"OggS0000payload", b"fLaC0000payload"],
    ids=["ogg", "flac"],
)
def test_openai_ogg_and_flac_fall_back_without_calling_the_sdk(tmp_path, audio):
    called = False

    def _create(**kw):
        nonlocal called
        called = True
        return SimpleNamespace(text="must not be used")

    sdk = SimpleNamespace(
        audio=SimpleNamespace(transcriptions=SimpleNamespace(create=_create))
    )
    client = LLMClient(sdk, provider="openai", model="unused")
    path = _write_audio(tmp_path, name="recording.bin", data=audio)

    assert (
        transcribe_audio(path, provided_transcript="safe fallback", client=client)
        == "safe fallback"
    )
    assert called is False


@pytest.mark.parametrize(
    "audio",
    [b"ADIFraw-aac", b"not-a-supported-audio-container"],
    ids=["adif-aac", "unrecognized"],
)
def test_openai_unsupported_audio_falls_back_without_calling_the_sdk(
    tmp_path, audio
):
    called = False

    def _create(**kw):
        nonlocal called
        called = True
        return SimpleNamespace(text="must not be used")

    sdk = SimpleNamespace(
        audio=SimpleNamespace(transcriptions=SimpleNamespace(create=_create))
    )
    client = LLMClient(sdk, provider="openai", model="unused")
    path = _write_audio(tmp_path, name="recording.bin", data=audio)

    assert (
        transcribe_audio(path, provided_transcript="safe fallback", client=client)
        == "safe fallback"
    )
    assert called is False


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


def test_empty_transcribe_model_env_falls_back_to_default(tmp_path, monkeypatch):
    # docker-compose passes ROKID_TRANSCRIBE_MODEL="" when unset; the OpenAI
    # request must still use the default model, not an empty model="".
    monkeypatch.setenv("ROKID_TRANSCRIBE_MODEL", "")
    captured: dict = {}

    def _create(**kw):
        captured.update(kw)
        return SimpleNamespace(text="ok")

    sdk = SimpleNamespace(
        audio=SimpleNamespace(transcriptions=SimpleNamespace(create=_create))
    )
    client = LLMClient(sdk, provider="openai", model="unused")
    out = transcribe_audio(_write_audio(tmp_path), client=client)
    assert out == "ok"
    assert captured["model"] == "gpt-4o-transcribe"


def test_transcribe_model_env_overrides_default(tmp_path, monkeypatch):
    monkeypatch.setenv("ROKID_TRANSCRIBE_MODEL", "whisper-x")
    captured: dict = {}

    def _create(**kw):
        captured.update(kw)
        return SimpleNamespace(text="ok")

    sdk = SimpleNamespace(
        audio=SimpleNamespace(transcriptions=SimpleNamespace(create=_create))
    )
    client = LLMClient(sdk, provider="openai", model="unused")
    transcribe_audio(_write_audio(tmp_path), client=client)
    assert captured["model"] == "whisper-x"


def test_empty_gemini_model_env_uses_default(monkeypatch):
    import app.transcribe as tr

    monkeypatch.setenv("ROKID_LLM_MODEL", "")
    monkeypatch.setattr(tr, "_provider_key", lambda provider: "key-present")
    monkeypatch.setattr(tr, "_build_sdk", lambda provider: object())
    client = tr._load_transcriber("gemini")
    assert client is not None
    assert client.model == "gemini-2.5-flash"


def test_audio_media_type_detection():
    assert _audio_media_type(b"RIFF0000WAVEmore") == "audio/wav"
    assert _audio_media_type(b"ID3xxxxx") == "audio/mpeg"
    assert _audio_media_type(b"OggS0000") == "audio/ogg"
    assert _audio_media_type(b"fLaC0000") == "audio/flac"
    assert _audio_media_type(b"\xff\xf1aac") == "audio/aac"
    assert _audio_media_type(b"\x00\x00\x00\x18ftypM4A ") == "audio/mp4"
    assert _audio_media_type(b"\x1aE\xdf\xa3webm") == "audio/webm"
    assert _audio_media_type(b"\x00\x00\x00\x00") == "audio/mpeg"


def test_aac_detection_accepts_adts_headers_with_or_without_crc():
    assert _audio_media_type(b"\xff\xf0aac-with-crc") == "audio/aac"
    assert _audio_media_type(b"\xff\xf1aac-without-crc") == "audio/aac"
    assert _audio_media_type(b"\xff\xf8aac-with-crc") == "audio/aac"
    assert _audio_media_type(b"\xff\xf9aac-without-crc") == "audio/aac"


def test_audio_registry_keeps_storage_and_provider_metadata_consistent():
    for audio_format in AUDIO_FORMATS:
        assert safe_audio_suffix(
            "../untrusted.not-audio",
            f"{audio_format.mime_type}; charset=binary",
        ) == audio_format.persisted_suffix
        assert audio_format.upload_name.endswith(audio_format.persisted_suffix)

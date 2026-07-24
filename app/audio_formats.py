"""Canonical audio filename, suffix, and MIME metadata."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AudioFormat:
    mime_type: str
    upload_name: str
    persisted_suffix: str
    filename_suffixes: tuple[str, ...]
    mime_aliases: tuple[str, ...] = ()
    openai_supported: bool = True


WAV = AudioFormat("audio/wav", "audio.wav", ".wav", (".wav",), ("audio/x-wav",))
MPEG = AudioFormat(
    "audio/mpeg",
    "audio.mp3",
    ".mp3",
    (".mp3", ".mpeg", ".mpga"),
)
OGG = AudioFormat("audio/ogg", "audio.ogg", ".ogg", (".ogg",))
FLAC = AudioFormat("audio/flac", "audio.flac", ".flac", (".flac",))
AAC = AudioFormat(
    "audio/aac",
    "audio.aac",
    ".aac",
    (".aac",),
    openai_supported=False,
)
MP4 = AudioFormat("audio/mp4", "audio.m4a", ".m4a", (".m4a", ".mp4"))
WEBM = AudioFormat("audio/webm", "audio.webm", ".webm", (".webm",))

AUDIO_FORMATS = (WAV, MPEG, OGG, FLAC, AAC, MP4, WEBM)
_SAFE_SUFFIXES = frozenset(
    suffix
    for audio_format in AUDIO_FORMATS
    for suffix in audio_format.filename_suffixes
)
_FORMAT_BY_MIME = {
    mime: audio_format
    for audio_format in AUDIO_FORMATS
    for mime in (audio_format.mime_type, *audio_format.mime_aliases)
}


def safe_audio_suffix(filename: str | None, content_type: str | None) -> str:
    """Return an allow-listed suffix without reusing an untrusted path."""
    suffix = Path(filename or "").suffix.lower()
    if suffix in _SAFE_SUFFIXES:
        return suffix
    normalized_mime = (content_type or "").partition(";")[0].strip().lower()
    audio_format = _FORMAT_BY_MIME.get(normalized_mime)
    return audio_format.persisted_suffix if audio_format is not None else ".bin"


def _detect_audio_magic(audio: bytes) -> AudioFormat | None:
    """Return a recognized audio format without guessing a fallback."""
    if audio[:4] == b"RIFF" and audio[8:12] == b"WAVE":
        return WAV
    if audio[:4] == b"OggS":
        return OGG
    if audio[:4] == b"fLaC":
        return FLAC
    if audio[:4] == b"ADIF":
        return AAC
    if audio[4:8] == b"ftyp":
        return MP4
    if audio[:4] == b"\x1aE\xdf\xa3":
        return WEBM
    if len(audio) >= 2 and audio[0] == 0xFF:
        # ADTS AAC has a 12-bit sync word and zero layer bits. The final bit
        # varies depending on whether a CRC follows the header.
        if audio[1] & 0xF6 == 0xF0:
            return AAC
        if audio[1] & 0xE0 == 0xE0:
            return MPEG
    return None


def detect_audio_format(audio: bytes) -> AudioFormat:
    """Best-effort audio format detection from magic bytes."""
    if audio[:3] == b"ID3":
        return MPEG
    return _detect_audio_magic(audio) or MPEG


def _after_id3v2_tag(audio: bytes) -> bytes:
    """Return the audio payload following one valid leading ID3v2 tag."""
    if audio[:3] != b"ID3" or len(audio) < 10:
        return audio
    major_version = audio[3]
    size_bytes = audio[6:10]
    if major_version not in (2, 3, 4) or any(value & 0x80 for value in size_bytes):
        return audio
    tag_size = (
        (size_bytes[0] << 21)
        | (size_bytes[1] << 14)
        | (size_bytes[2] << 7)
        | size_bytes[3]
    )
    footer_size = 10 if major_version == 4 and audio[5] & 0x10 else 0
    payload_offset = 10 + tag_size + footer_size
    return audio[payload_offset:] if payload_offset <= len(audio) else audio


def detect_openai_audio_format(audio: bytes) -> AudioFormat:
    """Return documented OpenAI upload metadata or reject the container."""
    audio_format = _detect_audio_magic(_after_id3v2_tag(audio))
    if audio_format is None:
        raise ValueError("OpenAI transcription requires a recognized audio container")
    if not audio_format.openai_supported:
        raise ValueError(
            f"OpenAI transcription does not support raw {audio_format.mime_type}"
        )
    return audio_format

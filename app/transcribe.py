"""Listening-mode audio transcription (offline-safe, provider-agnostic).

English-listening exams record the audio on the spot; this turns that recording
into text for the solver. It is credential-free by default: with no transcriber
configured (or on any failure) it returns the client-provided transcript, so the
server always has something to solve against and never hard-depends on an ASR.

Config (see app/config.py):
  ROKID_TRANSCRIBER       openai | gemini | (unset = use provided transcript)
  ROKID_TRANSCRIBE_MODEL  openai transcription model (default gpt-4o-transcribe)
  OPENAI_API_KEY / GOOGLE_API_KEY   provider key
Anthropic has no ASR, so it is never used here.
"""

from __future__ import annotations

import os

from . import config
from .llm import LLMClient, _build_sdk, _provider_key


def _load_transcriber(provider: str | None) -> "LLMClient | None":
    """Build a transcription client for openai/gemini, or None if unavailable."""
    if provider not in ("openai", "gemini") or not _provider_key(provider):
        return None
    # openai's model is the transcription model; gemini needs an audio-capable
    # chat model (reuse ROKID_LLM_MODEL, else a sensible default).
    if provider == "openai":
        model = os.environ.get("ROKID_TRANSCRIBE_MODEL", "gpt-4o-transcribe")
    else:
        model = os.environ.get("ROKID_LLM_MODEL", "gemini-2.5-flash")
    return LLMClient(_build_sdk(provider), provider=provider, model=model)


def transcribe_audio(
    audio_path: str | None,
    *,
    provided_transcript: str | None = None,
    client: "LLMClient | None" = None,
) -> str:
    """Return a transcript for the recorded audio.

    Falls back to ``provided_transcript`` when no transcriber is configured, no
    audio is present, or the call fails — so listening mode works offline.
    """
    fallback = (provided_transcript or "").strip()
    try:
        # _load_transcriber may raise LLMConfigError (provider key set but its SDK
        # not installed); keep it inside the guard so /audio never 500s — listening
        # degrades to the client-provided transcript.
        transcriber = client or _load_transcriber(config.TRANSCRIBER)
        if transcriber is None or not audio_path:
            return fallback
        with open(audio_path, "rb") as fh:
            audio = fh.read()
        text = transcriber.transcribe(audio)
        return text.strip() or fallback
    except Exception:  # noqa: BLE001 - never break listening; degrade to provided text
        return fallback

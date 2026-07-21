"""Runtime configuration. Local filesystem + SQLite only, no secrets."""

from __future__ import annotations

import json
import os
from pathlib import Path

# Environment files are loaded explicitly by the process launcher
# (README: uvicorn --env-file .env), never as a side effect of importing this
# module. This keeps pytest and library imports isolated from a developer's
# local credentials while exported environment variables retain precedence.

# Project data root. Override with ROKID_DATA_DIR for tests / containers.
DATA_DIR = Path(os.environ.get("ROKID_DATA_DIR", "data")).resolve()
IMAGE_DIR = DATA_DIR / "images"
AUDIO_DIR = DATA_DIR / "audio"   # listening-mode recordings (その場で録音)
DB_PATH = DATA_DIR / "docscan.db"

# Safety guardrail (案16): real-exam answering is locked off by default. It must
# be explicitly enabled, and is intended only for learning/mock/research use.
ALLOW_REAL_EXAM_SOLVE = os.environ.get("ROKID_ALLOW_REAL_EXAM_SOLVE", "0") == "1"

# Retrieval (Phase 3): when enabled, a real dense-embedding retriever may be
# used for RAG context. Until an analyzer supplies embeddings, app/retrieval.py
# falls back to its dependency-free lexical scorer regardless of this flag.
ENABLE_EMBEDDING = os.environ.get("ROKID_ENABLE_EMBEDDING", "0") == "1"

# Explainer adapter selection (explain-sessions).
# Default: "local" (LocalPlaceholderExplainer — offline, no credentials).
# Override with ROKID_EXPLAINER=openai|gemini|claude to swap in a real adapter.
# The value must match an Explainer.name registered in app/explainers/registry.py.
ROKID_EXPLAINER = os.environ.get("ROKID_EXPLAINER", "local")

# --- Real cloud-model adapters (opt-in, credential-gated) -------------------
# PRIMARY solving path: the glasses' onboard AI (natively GPT/Gemini) solves and
# its answers are ingested via POST /v1/exam-sessions/{id}/solutions — no server
# adapter needed. The adapters below are the OPTIONAL upgrade path for a more
# capable model, routed per port (openai|gemini|claude) with that provider's
# API key. All optional; with none set the server runs fully offline on local.
#   ROKID_ANALYZER=openai|gemini|claude   real page summarization (finalize)
#   ROKID_SOLVER=openai|gemini|claude     real exam solving; a non-local value
#                                         also makes finalize-reading solve ALL
#                                         problems server-side in one batch
#   ROKID_EXPLAINER=openai|gemini|claude  real page explanation (explain-sessions)
#   ROKID_EXTRACTOR=openai|gemini|claude  real formula/table/figure extraction
# Backing model + credentials (read in app/llm.py):
#   OPENAI_API_KEY / GOOGLE_API_KEY / ANTHROPIC_API_KEY  provider API key
#   ROKID_LLM_MODEL   optional override; every provider has a default
#                     (openai "gpt-4o" / gemini "gemini-2.5-flash" /
#                     anthropic "claude-opus-4-8" — see app/llm.py)
#   ROKID_LLM_MAX_TOKENS   default 1024
# Optional deps (install only for the provider you use):
#   pip install openai | google-genai | anthropic
# Listening transcription (English listening mode). The recorded audio is
# transcribed by ROKID_TRANSCRIBER (openai|gemini). Anthropic has no ASR, so
# unset/anthropic → the client-provided transcript is used as-is (offline-safe).
#   ROKID_TRANSCRIBER       openai | gemini | (unset = use provided transcript)
#   ROKID_TRANSCRIBE_MODEL  default "gpt-4o-transcribe" (openai); gemini uses
#                           ROKID_LLM_MODEL (an audio-capable gemini model)
TRANSCRIBER = os.environ.get("ROKID_TRANSCRIBER") or None

# --- On-glasses input (KeyCode) override ------------------------------------
# The server publishes a gesture->KeyCode contract at GET /v1/settings (see
# app/glasses_view.py INPUT_CONTRACT) so the on-glass CXR-L client has one
# authoritative source. Defaults follow Rokid's current mapping; override any
# gesture for a specific device/firmware via ROKID_KEYMAP (JSON), e.g.
#   ROKID_KEYMAP='{"single_tap": 23, "long_press": 170}'
def _load_keymap() -> dict:
    raw = os.environ.get("ROKID_KEYMAP")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {str(k): int(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


KEYMAP = _load_keymap()

# --- Optional server auth (off by default) ----------------------------------
# When ROKID_API_KEY is set, mutating/reading endpoints require
# `Authorization: Bearer <ROKID_API_KEY>`. Unset (default) = no auth, so local
# dev and CI are unaffected. Discovery endpoints (/health, /v1/version,
# /v1/settings) stay open so a client can negotiate before authenticating.
API_KEY = os.environ.get("ROKID_API_KEY") or None
AUTH_EXEMPT_PATHS = ("/health", "/v1/version", "/v1/settings", "/docs", "/openapi.json", "/redoc")


def ensure_dirs() -> None:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

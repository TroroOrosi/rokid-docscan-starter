"""Runtime configuration. Local filesystem + SQLite only, no secrets."""

from __future__ import annotations

import json
import os
from pathlib import Path

# Project data root. Override with ROKID_DATA_DIR for tests / containers.
DATA_DIR = Path(os.environ.get("ROKID_DATA_DIR", "data")).resolve()
IMAGE_DIR = DATA_DIR / "images"
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
# Override with ROKID_EXPLAINER=claude to swap in the real Anthropic adapter.
# The value must match an Explainer.name registered in app/explainers/registry.py.
ROKID_EXPLAINER = os.environ.get("ROKID_EXPLAINER", "local")

# --- Real cloud-model adapters (opt-in, credential-gated) -------------------
# The placeholder adapters become production-usable by routing to a provider
# adapter (claude|openai|gemini) in each registry and providing that provider's
# API key. All optional; with none set the server runs fully offline on local.
#   ROKID_ANALYZER=claude|openai|gemini   real page summarization (finalize)
#   ROKID_SOLVER=claude|openai|gemini     real question answering (exam-sessions)
#   ROKID_EXPLAINER=claude|openai|gemini  real page explanation (explain-sessions)
#   ROKID_EXTRACTOR=claude|openai|gemini  real formula/table/figure extraction
# Backing model + credentials (read in app/llm.py):
#   ANTHROPIC_API_KEY / OPENAI_API_KEY / GOOGLE_API_KEY  provider API key
#   ROKID_LLM_MODEL   Anthropic default "claude-opus-4-8"; REQUIRED for
#                     openai/gemini (set a current model id)
#   ROKID_LLM_MAX_TOKENS   default 1024
# Optional deps (install only for the provider you use):
#   pip install anthropic | openai | google-genai
LLM_MODEL = os.environ.get("ROKID_LLM_MODEL", "claude-opus-4-8")
LLM_ENABLED = bool(
    os.environ.get("ANTHROPIC_API_KEY")
    or os.environ.get("OPENAI_API_KEY")
    or os.environ.get("GOOGLE_API_KEY")
    or os.environ.get("GEMINI_API_KEY")
)

# --- On-glasses input (KeyCode) override ------------------------------------
# The server publishes a gesture->KeyCode contract at GET /v1/settings (see
# app/glasses_view.py INPUT_CONTRACT) so the on-glass CXR-L client has one
# authoritative source. Defaults follow Rokid's current mapping; override any
# gesture for a specific device/firmware via ROKID_KEYMAP (JSON), e.g.
#   ROKID_KEYMAP='{"tap": 23, "long_press": 170}'
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

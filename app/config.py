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

# Physical-device sessions must fail closed instead of silently serving local
# placeholder analyzer/solver output. Development and CI remain offline-first
# unless this flag is explicitly enabled before process start.
REAL_MODE = os.environ.get("ROKID_REAL_MODE", "0") == "1"


def require_real_provider(kind: str, provider):
    """Reject placeholder or unready providers in a physical-device session."""
    if not REAL_MODE:
        return provider
    info = provider.info()
    if getattr(provider, "placeholder", info.get("offline")) or not info.get("ready"):
        raise RuntimeError(
            "ROKID_REAL_MODE=1 rejects placeholder or unready "
            f"{kind} provider '{info.get('name', 'unknown')}'"
        )
    return provider

# Explainer adapter selection (explain-sessions).
# Default: "local" (LocalPlaceholderExplainer — offline, no credentials).
# Override with ROKID_EXPLAINER=openai|gemini|claude to swap in a real adapter.
# The value must match an Explainer.name registered in app/explainers/registry.py.
ROKID_EXPLAINER = os.environ.get("ROKID_EXPLAINER", "local")

# --- Real cloud-model adapters (opt-in, credential-gated) -------------------
# Physical-device solving uses the configured server adapters. The public CXR-L
# surface inspected by this project does not export arbitrary answers from an
# AI running on the glasses. Local placeholders remain available for development
# only and are rejected when ROKID_REAL_MODE=1.
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
#
# Subscription-only GPT route (no API key): ROKID_SOLVER=chatgpt-web answers out
# of the operator's own signed-in ChatGPT web session, driven over a Chrome
# debugging port. Automating that UI is against OpenAI's terms of use and risks
# the account; the API route above does not. Chrome must already be running:
#   chrome.exe --remote-debugging-port=9222 --user-data-dir=<real profile>
#   pip install playwright            (no `playwright install` — real Chrome)
#   ROKID_CHATGPT_CDP                 default http://127.0.0.1:9222
#   ROKID_CHATGPT_COMPOSER_SEL        default #prompt-textarea
#   ROKID_CHATGPT_ASSISTANT_SEL       default [data-message-author-role=...]
#   ROKID_CHATGPT_FILE_INPUT_SEL      default input[data-testid=
#                                     "upload-photos-input"] — NOT a bare
#                                     input[type=file]: five of those exist and
#                                     Playwright rejects the ambiguous locator
#   ROKID_CHATGPT_ATTACHMENT_SEL      upload-finished thumbnail (form img)
#   ROKID_CHATGPT_STOP_SEL            streaming indicator. It is present for the
#                                     WHOLE generation including the thinking
#                                     phase, so nothing on screen is the answer
#                                     while it exists
#   ROKID_CHATGPT_UPLOAD_S            default 20 (a confirmed upload took 0.11s)
#   ROKID_CHATGPT_ATTEMPTS            default 3 tries per question, fresh chat
#   ROKID_CHATGPT_RETRY_S             default 5, multiplied by the attempt
#   ROKID_CHATGPT_TIMEOUT_S           default 180
#   ROKID_CHATGPT_READY_S             default 30 (composer mount wait)
#   ROKID_CHATGPT_POLL_S              default 0.25
#   ROKID_CHATGPT_STABLE_POLLS        default 4  (0.25 x 4 = 1s of silence)
# Use a DEDICATED --user-data-dir and sign in there once. Passing the flag to an
# already-running Chrome only opens a tab in it and never opens the port, and a
# signed-out chatgpt.com serves a placeholder shell with no composer at all.
# The selectors are OpenAI's page, not ours: when the UI changes, retune these
# rather than editing app/solvers/chatgpt_web.py. The page image and the OCR
# text are sent as two separate parts (attachment + typed message), as the API
# solvers do, so figures survive. `extras["image_attached"]` records whether
# the upload was confirmed; verify with
#   py -3.12 -m app.solvers.chatgpt_web "<question>" <page image>
# Listening transcription (English listening mode). The recorded audio is
# transcribed by ROKID_TRANSCRIBER (openai|gemini). Anthropic has no ASR, so
# unset/anthropic → the client-provided transcript is used as-is (offline-safe).
#   ROKID_TRANSCRIBER       openai | gemini | (unset = use provided transcript)
#   ROKID_TRANSCRIBE_MODEL  default "gpt-4o-transcribe" (openai); gemini uses
#                           ROKID_LLM_MODEL (an audio-capable gemini model)
TRANSCRIBER = os.environ.get("ROKID_TRANSCRIBER") or None

# --- HUD line width ---------------------------------------------------------
# The on-glasses HUD wraps a logical line at ROKID_HUD_MAX_COLUMNS columns
# (default 18; a full-width glyph costs 2, so 9 Japanese characters). It never
# truncates: a longer line becomes more lines and more view pages. The budget
# is read by app.glasses_view.MAX_COLUMNS and published at GET /v1/settings.
# It is an ESTIMATE — 34sp across a 480 px logical screen — not a measurement
# of the CUSTOMVIEW overlay's text area, which has never been measured.
# Set 0 to disable wrapping.

# --- Diagnostic glasses KeyCode map -----------------------------------------
# GET /v1/settings publishes an unverified gesture->KeyCode map for diagnostics.
# It does not enable operator actions in the supported phone-controlled relay.
# Override a measured map for a specific device/firmware via ROKID_KEYMAP, e.g.
#   ROKID_KEYMAP='{"single_tap": 23, "long_press": 170}'  # diagnostics only
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

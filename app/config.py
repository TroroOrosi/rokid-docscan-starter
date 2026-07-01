"""Runtime configuration. Local filesystem + SQLite only, no secrets."""

from __future__ import annotations

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
# The placeholder adapters become production-usable by routing to the "claude"
# adapter in each registry and providing an Anthropic API key. All optional;
# with none set the server runs fully offline on the local placeholders.
#   ROKID_ANALYZER=claude   real page summarization (finalize)
#   ROKID_SOLVER=claude     real question answering (exam-sessions)
#   ROKID_EXPLAINER=claude  real page explanation (explain-sessions)
#   ROKID_EXTRACTOR=claude  real formula/table/figure extraction
# Backing model + credentials (read in app/llm.py):
#   ANTHROPIC_API_KEY       required to actually call the model (else -> local)
#   ROKID_LLM_MODEL         default "claude-opus-4-8" (e.g. claude-haiku-4-5)
#   ROKID_LLM_MAX_TOKENS    default 1024
# Requires the optional dependency: pip install anthropic
LLM_MODEL = os.environ.get("ROKID_LLM_MODEL", "claude-opus-4-8")
LLM_ENABLED = bool(os.environ.get("ANTHROPIC_API_KEY"))


def ensure_dirs() -> None:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

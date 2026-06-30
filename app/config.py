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
# Override with ROKID_EXPLAINER=gemini|openai|claude to swap in an LLM adapter.
# The value must match an Explainer.name registered in app/explainers/registry.py.
ROKID_EXPLAINER = os.environ.get("ROKID_EXPLAINER", "local")


def ensure_dirs() -> None:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

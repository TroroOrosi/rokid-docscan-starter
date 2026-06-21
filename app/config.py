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


def ensure_dirs() -> None:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

"""Runtime configuration. Local filesystem + SQLite only, no secrets."""

from __future__ import annotations

import os
from pathlib import Path

# Project data root. Override with ROKID_DATA_DIR for tests / containers.
DATA_DIR = Path(os.environ.get("ROKID_DATA_DIR", "data")).resolve()
IMAGE_DIR = DATA_DIR / "images"
DB_PATH = DATA_DIR / "docscan.db"


def ensure_dirs() -> None:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

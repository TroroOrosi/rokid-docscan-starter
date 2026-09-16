"""Content identity, deliberately separate from perceptual page similarity."""
from __future__ import annotations

import hashlib
from pathlib import Path


def file_sha256(path: str | Path | None) -> str:
    """Stream a file on Python 3.10+; distinguish absent evidence from empty bytes.

    Permission/read failures propagate rather than inventing a valid identity.
    No stat-only cache: a same-size, same-path replacement must change identity.
    """
    if not path:
        return "absent"
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except FileNotFoundError:
        return "missing"
    return digest.hexdigest()

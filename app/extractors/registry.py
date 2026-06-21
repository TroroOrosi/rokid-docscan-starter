"""Media-extractor registry + model routing (mirrors app/analyzers/registry.py).

A tiny provider registry so the active extractor is chosen by name/feature
flag, not hard-coded. Future math-OCR / table / chart adapters register here
under their own key; routing picks one based on config without touching
endpoints.

Routing precedence:
  1. explicit `prefer` argument (e.g. per-request hint),
  2. ROKID_EXTRACTOR env var,
  3. DEFAULT_EXTRACTOR.

If the requested extractor is missing (e.g. cloud adapter not installed / no
creds), we fall back to the offline local placeholder so the server keeps
working.
"""

from __future__ import annotations

import os

from .base import MediaExtractor
from .local_placeholder import LocalPlaceholderExtractor

DEFAULT_EXTRACTOR = "local"

_REGISTRY: dict[str, MediaExtractor] = {}


def register_extractor(extractor: MediaExtractor, *, replace: bool = False) -> None:
    if extractor.name in _REGISTRY and not replace:
        raise ValueError(f"extractor '{extractor.name}' already registered")
    _REGISTRY[extractor.name] = extractor


def list_extractors() -> list[dict]:
    return [e.info() for e in _REGISTRY.values()]


def _select_name(prefer: str | None) -> str:
    return prefer or os.environ.get("ROKID_EXTRACTOR") or DEFAULT_EXTRACTOR


def get_extractor(prefer: str | None = None) -> MediaExtractor:
    """Return an extractor by routing rules, falling back to the local one."""
    name = _select_name(prefer)
    extractor = _REGISTRY.get(name)
    if extractor is None:
        extractor = _REGISTRY.get(DEFAULT_EXTRACTOR)
    if extractor is None:  # registry empty -> lazily install the local default
        extractor = LocalPlaceholderExtractor()
        register_extractor(extractor, replace=True)
    return extractor


# Register the offline default at import time so the server always has one.
register_extractor(LocalPlaceholderExtractor(), replace=True)

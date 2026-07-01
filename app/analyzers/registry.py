"""Analyzer registry + model routing.

A tiny provider registry so the active analyzer is chosen by name/feature
flag, not hard-coded. Future Gemini/OpenAI/Rizon/on-device adapters register
here under their own key; routing picks one based on config without touching
endpoints.

Routing precedence:
  1. explicit `prefer` argument (e.g. per-request hint),
  2. ROKID_ANALYZER env var,
  3. DEFAULT_ANALYZER.

If the requested analyzer is missing (e.g. cloud adapter not installed / no
creds), we fall back to the offline local analyzer so the server keeps
working.
"""

from __future__ import annotations

import os

from .base import Analyzer
from .claude import ClaudeAnalyzer
from .local_placeholder import LocalPlaceholderAnalyzer

DEFAULT_ANALYZER = "local"

_REGISTRY: dict[str, Analyzer] = {}


def register_analyzer(analyzer: Analyzer, *, replace: bool = False) -> None:
    if analyzer.name in _REGISTRY and not replace:
        raise ValueError(f"analyzer '{analyzer.name}' already registered")
    _REGISTRY[analyzer.name] = analyzer


def list_analyzers() -> list[dict]:
    return [a.info() for a in _REGISTRY.values()]


def _select_name(prefer: str | None) -> str:
    return prefer or os.environ.get("ROKID_ANALYZER") or DEFAULT_ANALYZER


def get_analyzer(prefer: str | None = None) -> Analyzer:
    """Return an analyzer by routing rules, falling back to the local one."""
    name = _select_name(prefer)
    analyzer = _REGISTRY.get(name)
    if analyzer is None:
        analyzer = _REGISTRY.get(DEFAULT_ANALYZER)
    if analyzer is None:  # registry empty -> lazily install the local default
        analyzer = LocalPlaceholderAnalyzer()
        register_analyzer(analyzer, replace=True)
    return analyzer


# Register the offline default at import time so the server always has one.
register_analyzer(LocalPlaceholderAnalyzer(), replace=True)
# Register the real cloud analyzer (Anthropic Claude). It defers to local when
# unconfigured (no ANTHROPIC_API_KEY) or on any error, so finalize never breaks.
register_analyzer(ClaudeAnalyzer(), replace=True)

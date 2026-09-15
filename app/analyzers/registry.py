"""Analyzer registry + model routing.

A tiny provider registry so the active analyzer is chosen by name/feature
flag, not hard-coded (routing rules: app/provider_registry.py — prefer arg >
ROKID_ANALYZER > local). Future on-device adapters register here under their
own key; routing picks one based on config without touching endpoints.

If the requested analyzer is missing (e.g. cloud adapter not installed / no
creds), we fall back to the offline local analyzer so the server keeps
working.
"""

from __future__ import annotations

from .. import config
from ..llm import ADAPTER_PROVIDERS
from ..provider_registry import ProviderRegistry
from .base import Analyzer
from .llm_adapter import LLMAnalyzer
from .local_placeholder import ClientOcrAnalyzer, LocalPlaceholderAnalyzer

DEFAULT_ANALYZER = "local"

_registry = ProviderRegistry(
    kind="analyzer",
    env_var="ROKID_ANALYZER",
    default_factory=LocalPlaceholderAnalyzer,
    default_name=DEFAULT_ANALYZER,
)


def register_analyzer(analyzer: Analyzer, *, replace: bool = False) -> None:
    _registry.register(analyzer, replace=replace)


def list_analyzers() -> list[dict]:
    return _registry.list()


def get_analyzer(prefer: str | None = None) -> Analyzer:
    """Return an analyzer by routing rules, falling back to the local one."""
    return config.require_real_provider("analyzer", _registry.get(prefer))


# Register the offline default at import time so the server always has one.
register_analyzer(LocalPlaceholderAnalyzer(), replace=True)
register_analyzer(ClientOcrAnalyzer(), replace=True)
# Register the real cloud analyzers (OpenAI GPT / Google Gemini / Anthropic Claude).
# Each defers to local when unconfigured or on any error, so finalize never breaks.
for _name, _provider in ADAPTER_PROVIDERS:
    register_analyzer(LLMAnalyzer(name=_name, provider=_provider), replace=True)

"""Media-extractor registry + model routing (mirrors app/analyzers/registry.py).

A tiny provider registry so the active extractor is chosen by name/feature
flag, not hard-coded (routing rules: app/provider_registry.py — prefer arg >
ROKID_EXTRACTOR > local). Future math-OCR / table / chart adapters register
here under their own key; routing picks one based on config without touching
endpoints.

If the requested extractor is missing (e.g. cloud adapter not installed / no
creds), we fall back to the offline local placeholder so the server keeps
working.
"""

from __future__ import annotations

from ..llm import ADAPTER_PROVIDERS
from ..provider_registry import ProviderRegistry
from .base import MediaExtractor
from .llm_adapter import LLMExtractor
from .local_placeholder import LocalPlaceholderExtractor

DEFAULT_EXTRACTOR = "local"

_registry = ProviderRegistry(
    kind="extractor",
    env_var="ROKID_EXTRACTOR",
    default_factory=LocalPlaceholderExtractor,
    default_name=DEFAULT_EXTRACTOR,
)


def register_extractor(extractor: MediaExtractor, *, replace: bool = False) -> None:
    _registry.register(extractor, replace=replace)


def list_extractors() -> list[dict]:
    return _registry.list()


def get_extractor(prefer: str | None = None) -> MediaExtractor:
    """Return an extractor by routing rules, falling back to the local one."""
    return _registry.get(prefer)


# Register the offline default at import time so the server always has one.
register_extractor(LocalPlaceholderExtractor(), replace=True)
# Register the real cloud extractors (OpenAI GPT / Google Gemini / Anthropic Claude).
# Each defers to local when unconfigured or on any error, so add_question is safe.
for _name, _provider in ADAPTER_PROVIDERS:
    register_extractor(LLMExtractor(name=_name, provider=_provider), replace=True)

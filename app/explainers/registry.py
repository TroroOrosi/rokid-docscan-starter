"""Explainer registry + model routing (mirrors app/analyzers/registry.py).

Routing rules: app/provider_registry.py — prefer arg > ROKID_EXPLAINER >
local. If the requested explainer is missing (e.g. cloud adapter not
installed / no creds), falls back to the offline local placeholder.
"""

from __future__ import annotations

from ..explainer import Explainer
from ..llm import ADAPTER_PROVIDERS
from ..provider_registry import ProviderRegistry
from .llm_adapter import LLMExplainer
from .local_placeholder import LocalPlaceholderExplainer

DEFAULT_EXPLAINER = "local"

_registry = ProviderRegistry(
    kind="explainer",
    env_var="ROKID_EXPLAINER",
    default_factory=LocalPlaceholderExplainer,
    default_name=DEFAULT_EXPLAINER,
)


def register_explainer(explainer: Explainer, *, replace: bool = False) -> None:
    _registry.register(explainer, replace=replace)


def list_explainers() -> list[dict]:
    return _registry.list()


def get_explainer(prefer: str | None = None) -> Explainer:
    """Return an explainer by routing rules, falling back to the local one."""
    return _registry.get(prefer)


# Register the offline default at import time so the server always has one.
register_explainer(LocalPlaceholderExplainer(), replace=True)
# Register the real cloud explainers (OpenAI GPT / Google Gemini / Anthropic Claude).
# Each defers to local when unconfigured or on any error, so the HUD always renders.
for _name, _provider in ADAPTER_PROVIDERS:
    register_explainer(LLMExplainer(name=_name, provider=_provider), replace=True)

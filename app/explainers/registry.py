"""Explainer registry + model routing (mirrors app/analyzers/registry.py).

Routing precedence:
  1. explicit `prefer` argument,
  2. ROKID_EXPLAINER env var,
  3. DEFAULT_EXPLAINER.

If the requested explainer is missing (e.g. cloud adapter not installed /
no creds), falls back to the offline local placeholder.
"""

from __future__ import annotations

import os

from ..explainer import Explainer
from ..llm import ADAPTER_PROVIDERS
from .llm_adapter import LLMExplainer
from .local_placeholder import LocalPlaceholderExplainer

DEFAULT_EXPLAINER = "local"

_REGISTRY: dict[str, Explainer] = {}


def register_explainer(explainer: Explainer, *, replace: bool = False) -> None:
    if explainer.name in _REGISTRY and not replace:
        raise ValueError(f"explainer '{explainer.name}' already registered")
    _REGISTRY[explainer.name] = explainer


def list_explainers() -> list[dict]:
    return [e.info() for e in _REGISTRY.values()]


def _select_name(prefer: str | None) -> str:
    return prefer or os.environ.get("ROKID_EXPLAINER") or DEFAULT_EXPLAINER


def get_explainer(prefer: str | None = None) -> Explainer:
    """Return an explainer by routing rules, falling back to the local one."""
    name = _select_name(prefer)
    explainer = _REGISTRY.get(name)
    if explainer is None:
        explainer = _REGISTRY.get(DEFAULT_EXPLAINER)
    if explainer is None:
        explainer = LocalPlaceholderExplainer()
        register_explainer(explainer, replace=True)
    return explainer


# Register the offline default at import time so the server always has one.
register_explainer(LocalPlaceholderExplainer(), replace=True)
# Register the real cloud explainers (OpenAI GPT / Google Gemini / Anthropic Claude).
# Each defers to local when unconfigured or on any error, so the HUD always renders.
for _name, _provider in ADAPTER_PROVIDERS:
    register_explainer(LLMExplainer(name=_name, provider=_provider), replace=True)

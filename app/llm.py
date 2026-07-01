"""Real cloud-model bridge — provider-agnostic (Anthropic / OpenAI / Gemini).

This module turns the offline *placeholder* adapters into working,
production-usable ones.  It is isolated so the rest of the server keeps
depending only on the provider-agnostic ports (`Analyzer`, `Solver`,
`Explainer`, `MediaExtractor`) — see app/*/base.py.

Design constraints (identical to the rest of the repo):

  * **Credential-free by default.**  Nothing here runs, and no provider SDK is
    imported, unless a caller routes to a cloud adapter AND that provider's API
    key is present.  With no key the server runs fully offline on the local
    placeholders.
  * **No new hard dependency.**  The official provider SDKs (`anthropic`,
    `openai`, `google-genai`) are *optional* extras, imported lazily; their
    absence only matters once you opt in to that provider.
  * **Injectable.**  Adapters accept an `LLMClient`, and `LLMClient` wraps any
    object exposing the selected provider's call surface.  Tests pass a fake,
    so the whole real path is exercised offline with no network and no creds.

Routing is by adapter name == provider: `ROKID_SOLVER=openai` selects the
OpenAI-backed solver, etc.  The backing model is `ROKID_LLM_MODEL` (Anthropic
has a sensible default; OpenAI/Gemini require it be set to a current model id).
"""

from __future__ import annotations

import json
import os
import re

PROVIDERS = ("anthropic", "openai", "gemini")

# Per-provider model defaults. Anthropic has a verified current default; for
# OpenAI/Gemini the operator must set ROKID_LLM_MODEL to a current id (a wrong
# id just fails the call and the adapter falls back to local, but we prefer to
# not ship a likely-stale guess).
DEFAULT_MODELS = {"anthropic": "claude-opus-4-8", "openai": None, "gemini": None}
DEFAULT_MAX_TOKENS = 1024

# Env var holding each provider's API key.
_KEY_ENV = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "gemini": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
}

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


class LLMConfigError(RuntimeError):
    """Raised when a cloud adapter is selected but cannot be configured.

    e.g. the provider's API key is set but its SDK is not installed. The solver
    fallback treats this like any tier failure and drops back to local.
    """


def _provider_key(provider: str) -> str | None:
    for name in _KEY_ENV.get(provider, ()):
        val = os.environ.get(name)
        if val:
            return val
    return None


class LLMClient:
    """Thin wrapper around a provider's chat/messages client.

    ``sdk`` is the provider client object (``anthropic.Anthropic()`` /
    ``openai.OpenAI()`` / ``google.genai.Client()``); tests inject a fake with
    the matching call surface. ``provider`` selects how ``complete`` calls it.
    """

    def __init__(
        self,
        sdk,
        *,
        provider: str = "anthropic",
        model: str = DEFAULT_MODELS["anthropic"],
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ):
        self._sdk = sdk
        self.provider = provider
        self.model = model
        self.max_tokens = max_tokens

    @classmethod
    def load(cls, provider: str = "anthropic") -> "LLMClient | None":
        """Build a client for ``provider`` from the env, or ``None`` if unconfigured.

        Returns ``None`` when the provider's API key is absent, or (for
        OpenAI/Gemini) when ``ROKID_LLM_MODEL`` is unset. Raises
        :class:`LLMConfigError` when a key IS present but the provider SDK is
        missing, so the misconfiguration is loud rather than silent.
        """
        if provider not in PROVIDERS:
            return None
        if not _provider_key(provider):
            return None
        model = os.environ.get("ROKID_LLM_MODEL") or DEFAULT_MODELS[provider]
        if not model:
            # OpenAI/Gemini have no safe default id — require an explicit one.
            return None
        try:
            max_tokens = int(os.environ.get("ROKID_LLM_MAX_TOKENS", str(DEFAULT_MAX_TOKENS)))
        except ValueError:
            max_tokens = DEFAULT_MAX_TOKENS
        sdk = _build_sdk(provider)
        return cls(sdk, provider=provider, model=model, max_tokens=max_tokens)

    def complete(self, *, system: str, prompt: str) -> str:
        """Return the model's single-turn text response for the provider."""
        if self.provider == "anthropic":
            return _text_anthropic(self._sdk, self.model, self.max_tokens, system, prompt)
        if self.provider == "openai":
            return _text_openai(self._sdk, self.model, self.max_tokens, system, prompt)
        if self.provider == "gemini":
            return _text_gemini(self._sdk, self.model, self.max_tokens, system, prompt)
        raise LLMConfigError(f"unknown provider: {self.provider}")

    def complete_json(self, *, system: str, prompt: str) -> dict:
        """Call the model and parse its reply as a JSON object (tolerant)."""
        return extract_json(self.complete(system=system, prompt=prompt))


# --- provider SDK construction (lazy) ---------------------------------------

def _build_sdk(provider: str):
    try:
        if provider == "anthropic":
            import anthropic  # noqa: PLC0415

            return anthropic.Anthropic()
        if provider == "openai":
            import openai  # noqa: PLC0415

            return openai.OpenAI()
        if provider == "gemini":
            from google import genai  # noqa: PLC0415

            return genai.Client()
    except ImportError as exc:  # pragma: no cover - exercised via stub in tests
        pkg = {"anthropic": "anthropic", "openai": "openai", "gemini": "google-genai"}[provider]
        raise LLMConfigError(
            f"provider '{provider}' selected and its API key is set, but the "
            f"'{pkg}' package is not installed. Run: pip install {pkg}"
        ) from exc
    raise LLMConfigError(f"unknown provider: {provider}")  # pragma: no cover


# --- provider response extraction -------------------------------------------

def _text_anthropic(sdk, model, max_tokens, system, prompt) -> str:
    msg = sdk.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    parts = [
        getattr(b, "text", "")
        for b in getattr(msg, "content", [])
        if getattr(b, "type", None) == "text"
    ]
    return "".join(parts).strip()


def _text_openai(sdk, model, max_tokens, system, prompt) -> str:
    resp = sdk.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    )
    return (resp.choices[0].message.content or "").strip()


def _text_gemini(sdk, model, max_tokens, system, prompt) -> str:
    resp = sdk.models.generate_content(
        model=model,
        contents=prompt,
        config={"system_instruction": system, "max_output_tokens": max_tokens},
    )
    return (getattr(resp, "text", "") or "").strip()


# --- helpers ----------------------------------------------------------------

def extract_json(text: str) -> dict:
    """Parse the first JSON object found in ``text`` (tolerant of fences/prose)."""
    text = (text or "").strip()
    if not text:
        raise ValueError("empty model response")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = _JSON_OBJECT_RE.search(text)
    if match:
        return json.loads(match.group(0))
    raise ValueError("no JSON object in model response")


def get_client(client: "LLMClient | None", provider: str = "anthropic") -> "LLMClient | None":
    """Return the injected client, else one built from the env for ``provider``."""
    return client if client is not None else LLMClient.load(provider)

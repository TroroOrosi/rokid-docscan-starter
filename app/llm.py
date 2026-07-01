"""Real cloud-model bridge (Anthropic Claude Messages API).

This module is what turns the offline *placeholder* adapters into working,
production-usable ones.  It is deliberately isolated so the rest of the server
keeps depending only on the provider-agnostic ports (`Analyzer`, `Solver`,
`Explainer`, `MediaExtractor`) — see app/*/base.py.

Design constraints (kept identical to the rest of the repo):

  * **Credential-free by default.**  Nothing here runs, and the `anthropic`
    package is not imported, unless a caller routes to a `claude` adapter AND
    `ANTHROPIC_API_KEY` is set.  With no key the server still runs fully
    offline on the local placeholders.
  * **No new hard dependency.**  The official Anthropic SDK is an *optional*
    extra (`pip install anthropic`).  It is imported lazily; its absence only
    matters once you actually opt in to a cloud model.
  * **Injectable.**  Adapters accept an `LLMClient`, and `LLMClient` wraps any
    object exposing `messages.create(...)`.  Tests pass a fake, so the whole
    real path is exercised offline with no network and no credentials.

Configuration (all optional; read from the environment):

  ANTHROPIC_API_KEY     Anthropic API key. Absent  -> adapters fall back to the
                        offline placeholder (analyzer/explainer/extractor) or
                        raise (solver, so the two-tier fallback picks local).
  ROKID_LLM_MODEL       Claude model id. Default: ``claude-opus-4-8``.
                        Set ``claude-haiku-4-5`` for a cheaper/faster option.
  ROKID_LLM_MAX_TOKENS  Max output tokens per call. Default: ``1024``.
"""

from __future__ import annotations

import json
import os
import re

# Sensible defaults. The model id is overridable so an operator can trade cost
# for capability (e.g. claude-haiku-4-5) without touching code.
DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_MAX_TOKENS = 1024

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


class LLMConfigError(RuntimeError):
    """Raised when a cloud adapter is selected but cannot be configured.

    e.g. ``ANTHROPIC_API_KEY`` is set but the ``anthropic`` package is not
    installed. The solver fallback treats this like any other tier failure and
    drops back to the offline local solver.
    """


class LLMClient:
    """Thin wrapper around an Anthropic Messages client.

    ``sdk`` is any object with a ``messages.create(model, max_tokens, system,
    messages)`` method returning an object whose ``.content`` is a list of
    blocks (text blocks have ``.type == "text"`` and ``.text``). In production
    this is ``anthropic.Anthropic()``; tests inject a fake.
    """

    def __init__(self, sdk, *, model: str = DEFAULT_MODEL, max_tokens: int = DEFAULT_MAX_TOKENS):
        self._sdk = sdk
        self.model = model
        self.max_tokens = max_tokens

    @classmethod
    def load(cls) -> "LLMClient | None":
        """Build a client from the environment, or ``None`` if unconfigured.

        Returns ``None`` when ``ANTHROPIC_API_KEY`` is absent (the common
        offline case). Raises :class:`LLMConfigError` when a key IS present but
        the ``anthropic`` package is missing, so the misconfiguration is loud
        rather than silently ignored.
        """
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return None
        try:
            import anthropic  # noqa: PLC0415 - lazy, optional dependency
        except ImportError as exc:  # pragma: no cover - exercised via tests w/ stub
            raise LLMConfigError(
                "A 'claude' adapter was selected and ANTHROPIC_API_KEY is set, "
                "but the 'anthropic' package is not installed. Run: "
                "pip install anthropic"
            ) from exc

        model = os.environ.get("ROKID_LLM_MODEL", DEFAULT_MODEL)
        try:
            max_tokens = int(os.environ.get("ROKID_LLM_MAX_TOKENS", str(DEFAULT_MAX_TOKENS)))
        except ValueError:
            max_tokens = DEFAULT_MAX_TOKENS
        # anthropic.Anthropic() reads ANTHROPIC_API_KEY from the environment.
        return cls(anthropic.Anthropic(), model=model, max_tokens=max_tokens)

    def complete(self, *, system: str, prompt: str) -> str:
        """Return the concatenated text of a single-turn Claude response."""
        msg = self._sdk.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        parts = [
            getattr(block, "text", "")
            for block in getattr(msg, "content", [])
            if getattr(block, "type", None) == "text"
        ]
        return "".join(parts).strip()

    def complete_json(self, *, system: str, prompt: str) -> dict:
        """Call the model and parse its reply as a JSON object.

        The system prompt instructs the model to answer with JSON only; this
        additionally tolerates stray prose or code fences around the object.
        """
        return extract_json(self.complete(system=system, prompt=prompt))


def extract_json(text: str) -> dict:
    """Parse the first JSON object found in ``text``.

    Real model output is usually clean JSON (we ask for it), but this stays
    robust to a leading sentence or a ```json fence. Raises ``ValueError`` if
    no JSON object can be parsed.
    """
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


def get_client(client: "LLMClient | None") -> "LLMClient | None":
    """Return the injected client, else one built from the environment."""
    return client if client is not None else LLMClient.load()

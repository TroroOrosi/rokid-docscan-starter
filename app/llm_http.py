"""Minimal OpenAI-compatible chat client over plain HTTP.

Exists for one deployment: the server running on the phone in Termux, where
the official ``openai`` SDK cannot be installed — its ``jiter`` and
``pydantic-core`` wheels are Rust extensions with no Android build, and
``pip install openai`` fails at build time on the device. The local
``llama-server`` speaks the OpenAI chat-completions API, so the only thing
actually missing is the HTTP call itself.

This shim exposes the exact surface ``app.llm._text_openai`` uses --
``sdk.chat.completions.create(...)`` returning ``.choices[0].message.content``
-- so the solver, analyzer, explainer and extractor adapters keep working
unchanged. It deliberately implements nothing else: no streaming, no audio, no
retries. A cloud deployment should keep using the real SDK.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class _Message:
    content: str


@dataclass
class _Choice:
    message: _Message


@dataclass
class _Response:
    choices: list[_Choice]


class _Completions:
    def __init__(self, base_url: str, api_key: str, timeout: float):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    def create(self, *, model: str, messages: list, max_tokens: int | None = None, **extra):
        payload = {"model": model, "messages": messages}
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        payload.update(extra)
        request = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as error:
            raise RuntimeError(f"local LLM endpoint unreachable: {error}") from error
        choices = body.get("choices") or []
        if not choices:
            raise RuntimeError(f"local LLM returned no choices: {body}")
        content = (choices[0].get("message") or {}).get("content") or ""
        return _Response(choices=[_Choice(message=_Message(content=content))])


class _Chat:
    def __init__(self, completions: _Completions):
        self.completions = completions


class OpenAICompatibleSDK:
    """Duck-typed stand-in for ``openai.OpenAI()`` over urllib."""

    def __init__(self, base_url: str, api_key: str = "local", timeout: float = 900.0):
        # A local 4B model on a phone answers in tens of seconds to minutes, so
        # the default timeout is generous on purpose; a short one turns a slow
        # but working answer into a failed tier.
        self.chat = _Chat(_Completions(base_url, api_key, timeout))

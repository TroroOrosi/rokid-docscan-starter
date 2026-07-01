"""Tests for the LLM bridge (app/llm.py) — offline, no network, no creds.

A fake Anthropic-shaped SDK stands in for anthropic.Anthropic(), so the whole
real code path (request shaping, text extraction, JSON parsing) is exercised
without a key or a network call.
"""

from types import SimpleNamespace

import pytest

from app.llm import DEFAULT_MODEL, LLMClient, extract_json, get_client


class FakeMessages:
    def __init__(self, text):
        self._text = text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self._text)]
        )


class FakeSDK:
    def __init__(self, text):
        self.messages = FakeMessages(text)


def test_complete_passes_model_and_extracts_text():
    sdk = FakeSDK("hello world")
    client = LLMClient(sdk, model="claude-test", max_tokens=32)
    out = client.complete(system="sys", prompt="hi")
    assert out == "hello world"
    call = sdk.messages.calls[0]
    assert call["model"] == "claude-test"
    assert call["max_tokens"] == 32
    assert call["system"] == "sys"
    assert call["messages"] == [{"role": "user", "content": "hi"}]


def test_complete_json_parses_object():
    client = LLMClient(FakeSDK('{"answer": "B", "n": 3}'), model="m")
    data = client.complete_json(system="s", prompt="p")
    assert data == {"answer": "B", "n": 3}


def test_complete_json_tolerates_fences_and_prose():
    client = LLMClient(
        FakeSDK('Sure!\n```json\n{"summary": "ok"}\n```'), model="m"
    )
    assert client.complete_json(system="s", prompt="p") == {"summary": "ok"}


def test_extract_json_raises_on_garbage():
    with pytest.raises(ValueError):
        extract_json("no json here")
    with pytest.raises(ValueError):
        extract_json("")


def test_load_returns_none_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert LLMClient.load() is None


def test_get_client_prefers_injected():
    injected = LLMClient(FakeSDK("x"), model="m")
    assert get_client(injected) is injected


def test_default_model_is_current_claude():
    assert DEFAULT_MODEL == "claude-opus-4-8"

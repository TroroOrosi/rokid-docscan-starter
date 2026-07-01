"""Tests for the multi-provider LLM bridge (app/llm.py) — offline, no creds.

Fake provider-shaped SDKs stand in for anthropic.Anthropic() / openai.OpenAI()
/ google.genai.Client(), so the whole real code path (request shaping, text
extraction, JSON parsing, per-provider dispatch) runs without a key or network.
"""

from types import SimpleNamespace

import pytest

from app.llm import DEFAULT_MODELS, LLMClient, extract_json, get_client


# --- fakes per provider shape -----------------------------------------------

def _anthropic_sdk(text):
    calls = []

    def create(**kw):
        calls.append(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])

    sdk = SimpleNamespace(messages=SimpleNamespace(create=create))
    sdk.calls = calls
    return sdk


def _openai_sdk(text):
    calls = []

    def create(**kw):
        calls.append(kw)
        msg = SimpleNamespace(content=text)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    sdk.calls = calls
    return sdk


def _gemini_sdk(text):
    calls = []

    def generate_content(**kw):
        calls.append(kw)
        return SimpleNamespace(text=text)

    sdk = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    sdk.calls = calls
    return sdk


# --- anthropic ---------------------------------------------------------------

def test_anthropic_complete_passes_model_and_extracts_text():
    sdk = _anthropic_sdk("hello world")
    client = LLMClient(sdk, provider="anthropic", model="claude-test", max_tokens=32)
    assert client.complete(system="sys", prompt="hi") == "hello world"
    call = sdk.calls[0]
    assert call["model"] == "claude-test"
    assert call["max_tokens"] == 32
    assert call["system"] == "sys"
    assert call["messages"] == [{"role": "user", "content": "hi"}]


# --- openai ------------------------------------------------------------------

def test_openai_complete_uses_chat_completions():
    sdk = _openai_sdk('{"answer": "B"}')
    client = LLMClient(sdk, provider="openai", model="gpt-test")
    assert client.complete_json(system="s", prompt="p") == {"answer": "B"}
    call = sdk.calls[0]
    assert call["model"] == "gpt-test"
    assert call["messages"][0] == {"role": "system", "content": "s"}
    assert call["messages"][1] == {"role": "user", "content": "p"}


# --- gemini ------------------------------------------------------------------

def test_gemini_complete_uses_generate_content():
    sdk = _gemini_sdk("plain text")
    client = LLMClient(sdk, provider="gemini", model="gemini-test", max_tokens=64)
    assert client.complete(system="s", prompt="p") == "plain text"
    call = sdk.calls[0]
    assert call["model"] == "gemini-test"
    assert call["contents"] == "p"
    assert call["config"]["system_instruction"] == "s"
    assert call["config"]["max_output_tokens"] == 64


# --- JSON parsing ------------------------------------------------------------

def test_complete_json_tolerates_fences_and_prose():
    client = LLMClient(_anthropic_sdk('Sure!\n```json\n{"summary": "ok"}\n```'))
    assert client.complete_json(system="s", prompt="p") == {"summary": "ok"}


def test_extract_json_raises_on_garbage():
    with pytest.raises(ValueError):
        extract_json("no json here")
    with pytest.raises(ValueError):
        extract_json("")


# --- load() gating (no network / no creds) ----------------------------------

def test_load_returns_none_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert LLMClient.load("anthropic") is None


def test_load_openai_requires_key_and_model(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert LLMClient.load("openai") is None
    # Key present but no explicit model -> still None (no safe default id).
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("ROKID_LLM_MODEL", raising=False)
    assert LLMClient.load("openai") is None


def test_load_unknown_provider_is_none():
    assert LLMClient.load("bogus") is None


def test_get_client_prefers_injected():
    injected = LLMClient(_anthropic_sdk("x"))
    assert get_client(injected, "anthropic") is injected


def test_default_models():
    assert DEFAULT_MODELS["anthropic"] == "claude-opus-4-8"
    assert DEFAULT_MODELS["openai"] is None
    assert DEFAULT_MODELS["gemini"] is None

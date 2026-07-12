"""Tests for the multi-provider LLM bridge (app/llm.py) — offline, no creds.

Fake provider-shaped SDKs stand in for anthropic.Anthropic() / openai.OpenAI()
/ google.genai.Client(), so the whole real code path (request shaping, text
extraction, JSON parsing, per-provider dispatch) runs without a key or network.
"""

from types import SimpleNamespace

import pytest

from app.llm import (
    DEFAULT_MODELS,
    LLMClient,
    LLMConfigError,
    clamp01,
    extract_json,
    get_client,
)


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


def test_extract_json_takes_first_object_despite_trailing_braces():
    # Prose containing braces AFTER the object must not break parsing (a
    # greedy regex captured to the last brace and raised here).
    assert extract_json('{"answer": "A"} note: units in {m}') == {"answer": "A"}
    # Two objects -> the first one wins.
    assert extract_json('{"a": 1} then {"b": 2}') == {"a": 1}
    # Nested objects stay intact.
    assert extract_json('prefix {"a": {"b": 1}} suffix') == {"a": {"b": 1}}
    # Braces inside strings don't confuse the scan.
    assert extract_json('{"t": "curly } inside"} rest') == {"t": "curly } inside"}


def test_clamp01_rejects_non_finite_confidence():
    assert clamp01(float("nan"), default=0.5) == 0.5
    assert clamp01(float("inf"), default=0.25) == 0.25
    assert clamp01(float("-inf"), default=0.75) == 0.75
    assert clamp01(2.0) == 1.0
    assert clamp01(-1.0) == 0.0


# --- load() gating (no network / no creds) ----------------------------------

def test_load_returns_none_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert LLMClient.load("anthropic") is None


def test_load_openai_keyless_is_none_key_without_sdk_is_loud(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert LLMClient.load("openai") is None
    # Key present, default model applies, but the SDK is not installed in the
    # offline test env -> a LOUD LLMConfigError (callers catch and degrade),
    # never a silent None that hides the misconfiguration.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("ROKID_LLM_MODEL", raising=False)
    with pytest.raises(LLMConfigError):
        LLMClient.load("openai")


def test_load_unknown_provider_is_none():
    assert LLMClient.load("bogus") is None


def test_get_client_prefers_injected():
    injected = LLMClient(_anthropic_sdk("x"))
    assert get_client(injected, "anthropic") is injected


def test_default_models_are_gpt_first_and_complete():
    # CLAUDE.md: GPT (openai) is cited first; every provider works key-only.
    assert list(DEFAULT_MODELS) == ["openai", "gemini", "anthropic"]
    assert DEFAULT_MODELS["openai"] == "gpt-4o"
    assert DEFAULT_MODELS["gemini"] == "gemini-2.5-flash"
    assert DEFAULT_MODELS["anthropic"] == "claude-opus-4-8"


# --- vision: image attachment per provider ----------------------------------

_PNG = b"\x89PNG\r\n\x1a\n" + b"payload"
_JPEG = b"\xff\xd8\xff" + b"payload"


def test_anthropic_attaches_image():
    sdk = _anthropic_sdk("ok")
    LLMClient(sdk, provider="anthropic", model="m").complete(system="s", prompt="p", image=_PNG)
    content = sdk.calls[0]["messages"][0]["content"]
    assert isinstance(content, list)
    kinds = [b["type"] for b in content]
    assert "image" in kinds and "text" in kinds
    img = next(b for b in content if b["type"] == "image")
    assert img["source"]["media_type"] == "image/png"


def test_openai_attaches_image_as_data_url():
    sdk = _openai_sdk("ok")
    LLMClient(sdk, provider="openai", model="m").complete(system="s", prompt="p", image=_JPEG)
    content = sdk.calls[0]["messages"][1]["content"]
    url = next(b for b in content if b["type"] == "image_url")["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")


def test_gemini_attaches_inline_image():
    sdk = _gemini_sdk("ok")
    LLMClient(sdk, provider="gemini", model="m").complete(system="s", prompt="p", image=_PNG)
    contents = sdk.calls[0]["contents"]
    assert isinstance(contents, list)
    assert any("inline_data" in part for part in contents)


def test_no_image_stays_text_only():
    sdk = _anthropic_sdk("ok")
    LLMClient(sdk, provider="anthropic", model="m").complete(system="s", prompt="p")
    assert sdk.calls[0]["messages"][0]["content"] == "p"

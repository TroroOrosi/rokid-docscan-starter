"""Real cloud-model bridge — provider-agnostic (OpenAI / Gemini / Anthropic).

This module turns the offline *placeholder* adapters into working,
production-usable ones.  It is isolated so the rest of the server keeps
depending only on the provider-agnostic ports (`Analyzer`, `Solver`,
`Explainer`, `MediaExtractor`) — see app/*/base.py.

Design constraints (identical to the rest of the repo):

  * **Credential-free by default.**  Nothing here runs, and no provider SDK is
    imported, unless a caller routes to a cloud adapter AND that provider's API
    key is present.  With no key the server runs fully offline on the local
    placeholders.
  * **No new hard dependency.**  The official provider SDKs (`openai`,
    `google-genai`, `anthropic`) are *optional* extras, imported lazily; their
    absence only matters once you opt in to that provider.
  * **Injectable.**  Adapters accept an `LLMClient`, and `LLMClient` wraps any
    object exposing the selected provider's call surface.  Tests pass a fake,
    so the whole real path is exercised offline with no network and no creds.

Routing is by adapter name == provider: `ROKID_SOLVER=openai` selects the
OpenAI-backed solver (GPT — the same family as the glasses' onboard AI), etc.
Every provider has a working default model; `ROKID_LLM_MODEL` overrides it.
"""

from __future__ import annotations

import base64
import json
import math
import os

from .audio_formats import detect_audio_format

PROVIDERS = ("openai", "gemini", "anthropic")

# Per-provider model defaults, GPT (openai) first — the onboard AI's family.
# A stale id degrades safely: the call fails and the adapter falls back to
# local; ROKID_LLM_MODEL overrides without a code change.
DEFAULT_MODELS = {
    "openai": "gpt-4o",  # family-consistent with the gpt-4o-transcribe default
    "gemini": "gemini-2.5-flash",  # matches the transcriber default
    "anthropic": "claude-opus-4-8",
}
DEFAULT_MAX_TOKENS = 1024

# (adapter registration name, llm provider) pairs shared by all four adapter
# families (solvers/analyzers/explainers/extractors) — GPT (openai) first.
ADAPTER_PROVIDERS = (
    ("openai", "openai"),
    ("gemini", "gemini"),
    ("claude", "anthropic"),
)

# Env var holding each provider's API key.
_KEY_ENV = {
    "openai": ("OPENAI_API_KEY",),
    "gemini": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "anthropic": ("ANTHROPIC_API_KEY",),
}

# NOTE: JSON extraction uses a brace-balanced scan (see extract_json), not a
# regex — a greedy regex captures to the LAST brace and breaks whenever the
# model appends prose containing braces after the JSON object.


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

        Returns ``None`` when the provider's API key is absent (the offline
        default). Raises :class:`LLMConfigError` when a key IS present but the
        provider SDK is missing, so the misconfiguration is loud rather than
        silent. Every provider has a default model; ``ROKID_LLM_MODEL``
        overrides it.
        """
        if provider not in PROVIDERS:
            return None
        if not _provider_key(provider):
            return None
        model = os.environ.get("ROKID_LLM_MODEL") or DEFAULT_MODELS[provider]
        try:
            max_tokens = int(os.environ.get("ROKID_LLM_MAX_TOKENS", str(DEFAULT_MAX_TOKENS)))
        except ValueError:
            max_tokens = DEFAULT_MAX_TOKENS
        sdk = _build_sdk(provider)
        return cls(sdk, provider=provider, model=model, max_tokens=max_tokens)

    def complete(self, *, system: str, prompt: str, image: bytes | None = None) -> str:
        """Return the model's single-turn text response for the provider.

        When ``image`` (raw bytes) is supplied, it is attached so a vision-capable
        model can read figures / equations / tables directly (used by the exam
        solver to answer from the scanned page, not just the OCR text).
        """
        if self.provider == "anthropic":
            return _text_anthropic(self._sdk, self.model, self.max_tokens, system, prompt, image)
        if self.provider == "openai":
            return _text_openai(self._sdk, self.model, self.max_tokens, system, prompt, image)
        if self.provider == "gemini":
            return _text_gemini(self._sdk, self.model, self.max_tokens, system, prompt, image)
        raise LLMConfigError(f"unknown provider: {self.provider}")

    def complete_json(self, *, system: str, prompt: str, image: bytes | None = None) -> dict:
        """Call the model and parse its reply as a JSON object (tolerant)."""
        return extract_json(self.complete(system=system, prompt=prompt, image=image))

    def transcribe(self, audio: bytes) -> str:
        """Transcribe recorded audio to text (English-listening mode).

        openai -> Audio API (ROKID_TRANSCRIBE_MODEL, default gpt-4o-transcribe);
        gemini -> generate_content over inline audio. Anthropic has no ASR.
        """
        if self.provider == "openai":
            # `or` (not get's default arg) so an explicitly empty env value —
            # e.g. docker-compose passing `ROKID_TRANSCRIBE_MODEL=` when unset —
            # still falls back to the default instead of requesting model="".
            model = os.environ.get("ROKID_TRANSCRIBE_MODEL") or "gpt-4o-transcribe"
            audio_format = detect_audio_format(audio)
            resp = self._sdk.audio.transcriptions.create(
                model=model,
                file=(
                    audio_format.upload_name,
                    audio,
                    audio_format.mime_type,
                ),
            )
            return (getattr(resp, "text", "") or "").strip()
        if self.provider == "gemini":
            audio_format = detect_audio_format(audio)
            resp = self._sdk.models.generate_content(
                model=self.model,
                contents=[
                    {
                        "inline_data": {
                            "mime_type": audio_format.mime_type,
                            "data": _b64(audio),
                        }
                    },
                    {"text": "Transcribe the audio verbatim."},
                ],
            )
            return (getattr(resp, "text", "") or "").strip()
        raise LLMConfigError(f"provider '{self.provider}' has no audio transcription")


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

def _text_anthropic(sdk, model, max_tokens, system, prompt, image=None) -> str:
    if image is not None:
        content = [
            {"type": "image", "source": {
                "type": "base64", "media_type": _media_type(image), "data": _b64(image)}},
            {"type": "text", "text": prompt},
        ]
    else:
        content = prompt
    msg = sdk.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": content}],
    )
    parts = [
        getattr(b, "text", "")
        for b in getattr(msg, "content", [])
        if getattr(b, "type", None) == "text"
    ]
    return "".join(parts).strip()


def _text_openai(sdk, model, max_tokens, system, prompt, image=None) -> str:
    if image is not None:
        user_content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {
                "url": f"data:{_media_type(image)};base64,{_b64(image)}"}},
        ]
    else:
        user_content = prompt
    resp = sdk.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
    )
    return (resp.choices[0].message.content or "").strip()


def _text_gemini(sdk, model, max_tokens, system, prompt, image=None) -> str:
    if image is not None:
        contents = [
            {"inline_data": {"mime_type": _media_type(image), "data": _b64(image)}},
            {"text": prompt},
        ]
    else:
        contents = prompt
    resp = sdk.models.generate_content(
        model=model,
        contents=contents,
        config={"system_instruction": system, "max_output_tokens": max_tokens},
    )
    return (getattr(resp, "text", "") or "").strip()


# --- helpers ----------------------------------------------------------------

def _b64(image: bytes) -> str:
    return base64.standard_b64encode(image).decode("ascii")


def _media_type(image: bytes) -> str:
    """Best-effort image MIME from magic bytes (saved pages are PNG)."""
    if image[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if image[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if image[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if image[:4] == b"RIFF" and image[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def _audio_media_type(audio: bytes) -> str:
    """Best-effort audio MIME from magic bytes (default audio/mpeg)."""
    return detect_audio_format(audio).mime_type


def clamp01(value, default: float = 0.0) -> float:
    """Coerce ``value`` to float and clamp into [0, 1]; ``default`` on junk.

    Model-reported confidences (and client-supplied ones) arrive as anything —
    strings, 0-100 scales, null — and must never inflate HUD ★ symbols.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    # Python's min/max do not sanitize NaN: min(1.0, nan) yields 1.0, which
    # would turn an invalid model/client confidence into a maximum-confidence
    # HUD result. Infinity is not a meaningful confidence either.
    if not math.isfinite(number):
        return default
    return max(0.0, min(1.0, number))


def extract_json(text: str) -> dict:
    """Parse the FIRST complete JSON object found in ``text``.

    Tolerant of code fences and surrounding prose — including prose that
    itself contains braces after the object (e.g. ``{"answer":"A"} note: {m}``)
    — via a brace-balanced scan over every candidate start position.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("empty model response")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for start, ch in enumerate(text):
        if ch != "{":
            continue
        depth = 0
        in_string = False
        escaped = False
        for end in range(start, len(text)):
            c = text[end]
            if in_string:
                if escaped:
                    escaped = False
                elif c == "\\":
                    escaped = True
                elif c == '"':
                    in_string = False
                continue
            if c == '"':
                in_string = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : end + 1])
                    except json.JSONDecodeError:
                        break  # not valid JSON; try the next '{'
        # unbalanced from this start; try the next '{'
    raise ValueError("no JSON object in model response")


def get_client(client: "LLMClient | None", provider: str = "anthropic") -> "LLMClient | None":
    """Return the injected client, else one built from the env for ``provider``."""
    return client if client is not None else LLMClient.load(provider)

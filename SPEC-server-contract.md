# Spec: server-contract

## Objective

Align server behavior and documentation for image authority, real-device
fail-closed operation, supported provider media, and retention disclosures.

## Tech Stack

Python 3.12 baseline, FastAPI, SQLite, Pillow, pytest, Ruff; optional OpenAI,
Anthropic, and Google Gen AI SDKs.

## Commands

- Focused tests: `py -3.12 -m pytest -q tests/test_config.py tests/test_transcribe.py tests/test_llm.py`
- Full tests: `py -3.12 -m pytest -q`
- Lint: `ruff check .`

## Project Structure

- `app/config.py`: environment and security policy.
- `app/main.py`: upload/finalization API.
- `app/audio_formats.py`, `app/llm.py`: provider boundaries.
- `tests/`: API and adapter contracts.

## Code Style

```python
if settings.real_mode and adapter.is_placeholder:
    raise RuntimeError("real mode requires configured non-placeholder adapters")
```

Errors name the rejected contract and never silently fall back in real mode.

## Testing Strategy

Test configuration and startup/request guards, normalized PNG persistence,
provider-format rejection/conversion boundaries, and custom Gemini endpoint
construction without making live provider calls.

## Boundaries

- Always: normalized, orientation-corrected PNG is the authoritative stored
  image; provider failures are explicit in real mode; secrets/content stay out
  of logs.
- Ask first: schema changes, raw-upload retention, or new dependencies.
- Never: claim raw JPEG is persisted when it is not, or send unsupported media
  to a provider.

## Success Criteria

- `ROKID_REAL_MODE=1` cannot use placeholder analyzer/solver paths.
- OGG/FLAC are not sent directly to OpenAI unless converted to a documented
  supported container.
- Gemini custom base URL is either explicitly passed to the SDK or rejected.
- Docs disclose local and provider retention limitations.

## Open Questions

Raw JPEG retention is out of scope; normalized PNG is the accepted authority.

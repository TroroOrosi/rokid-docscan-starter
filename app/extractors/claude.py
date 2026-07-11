"""Back-compat import shim — the multi-provider adapter lives in llm_adapter.py."""

from .llm_adapter import ClaudeExtractor, LLMExtractor  # noqa: F401

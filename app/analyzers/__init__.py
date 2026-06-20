"""Provider-agnostic document analyzers (OCR / summary / embeddings).

The server never talks to a concrete model vendor directly. It asks the
registry for an analyzer by name and uses the stable `Analyzer` interface.
Swapping local OCR <-> Gemini <-> OpenAI <-> a future Rokid Rizon workflow is
a registry change, not an endpoint change. See app/analyzers/base.py.
"""

from .base import Analyzer, AnalyzerResult
from .registry import get_analyzer, list_analyzers, register_analyzer

__all__ = [
    "Analyzer",
    "AnalyzerResult",
    "get_analyzer",
    "list_analyzers",
    "register_analyzer",
]

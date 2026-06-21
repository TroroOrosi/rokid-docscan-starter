"""Provider-agnostic media extractors (formula / figure / graph / table).

The server never talks to a concrete vision vendor directly. It asks the
registry for an extractor by name and uses the stable `MediaExtractor`
interface. Swapping a local placeholder <-> a real math-OCR / table / chart
model is a registry change, not an endpoint change. See app/extractors/base.py.
"""

from .base import KINDS, ExtractorResult, MediaExtractor
from .local_placeholder import LocalPlaceholderExtractor, detect_media
from .registry import get_extractor, list_extractors, register_extractor

__all__ = [
    "KINDS",
    "ExtractorResult",
    "MediaExtractor",
    "LocalPlaceholderExtractor",
    "detect_media",
    "get_extractor",
    "list_extractors",
    "register_extractor",
]

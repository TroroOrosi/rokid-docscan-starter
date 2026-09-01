"""Quarantined compatibility stub for a removed indicator experiment.

This module intentionally contains no device commands, command builders, or
execution path. It remains importable only so old automation receives a clear
failure instead of an ambiguous missing-module error.
"""

from __future__ import annotations


def quarantine_reason() -> str:
    return (
        "Unsupported camera-indicator modification experiment: no operation "
        "is available. Use the independent physical observation checklist."
    )


class IndicatorExperimentUnavailable(RuntimeError):
    """Raised by compatibility callers of the quarantined experiment."""


def __getattr__(name: str):
    if name.startswith("__"):
        raise AttributeError(name)
    raise IndicatorExperimentUnavailable(quarantine_reason())

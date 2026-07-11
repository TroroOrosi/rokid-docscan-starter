"""Generic provider registry shared by the four adapter families.

app/{analyzers,solvers,explainers,extractors}/registry.py used to carry four
near-identical copies of the same register/list/route logic; they now each
build one :class:`ProviderRegistry` and keep only their public wrapper names
(``register_solver`` …) so callers and tests are untouched.

Routing precedence (identical across families):
  1. explicit ``prefer`` argument (e.g. per-request hint),
  2. the family's env var (``ROKID_SOLVER`` …),
  3. the offline default ("local").

If the requested adapter is missing (e.g. cloud adapter not installed / no
creds), :meth:`get` falls back to the offline local default so the server
keeps working.
"""

from __future__ import annotations

import os
from typing import Callable


class ProviderRegistry:
    def __init__(
        self,
        *,
        kind: str,
        env_var: str,
        default_factory: Callable[[], object],
        default_name: str = "local",
    ):
        self._kind = kind
        self._env_var = env_var
        self._default_factory = default_factory
        self.default_name = default_name
        self._items: dict[str, object] = {}

    def register(self, item, *, replace: bool = False) -> None:
        if item.name in self._items and not replace:
            raise ValueError(f"{self._kind} '{item.name}' already registered")
        self._items[item.name] = item

    def list(self) -> list[dict]:
        return [item.info() for item in self._items.values()]

    def select_name(self, prefer: str | None) -> str:
        return prefer or os.environ.get(self._env_var) or self.default_name

    def get(self, prefer: str | None = None):
        """Return an adapter by routing rules, falling back to the default."""
        item = self._items.get(self.select_name(prefer))
        if item is None:
            item = self._items.get(self.default_name)
        if item is None:  # registry empty -> lazily install the default
            item = self._default_factory()
            self.register(item, replace=True)
        return item

    def __contains__(self, name: str) -> bool:
        return name in self._items

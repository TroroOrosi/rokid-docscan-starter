"""Unit tests for the shared ProviderRegistry (app/provider_registry.py).

The four family registries (analyzers/solvers/explainers/extractors) are thin
wrappers over this class; their behavior is covered by the existing suites.
Here we pin the generic routing/registration contract itself.
"""

from types import SimpleNamespace

import pytest

from app.provider_registry import ProviderRegistry


def _item(name):
    return SimpleNamespace(name=name, info=lambda: {"name": name})


def _make(**kw):
    return ProviderRegistry(
        kind="widget",
        env_var="ROKID_TEST_WIDGET",
        default_factory=lambda: _item("local"),
        **kw,
    )


def test_duplicate_register_raises_unless_replace():
    reg = _make()
    reg.register(_item("a"))
    with pytest.raises(ValueError, match="widget 'a' already registered"):
        reg.register(_item("a"))
    reg.register(_item("a"), replace=True)  # no raise


def test_routing_prefers_arg_then_env_then_default(monkeypatch):
    reg = _make()
    reg.register(_item("local"))
    reg.register(_item("cloud"))
    monkeypatch.delenv("ROKID_TEST_WIDGET", raising=False)
    assert reg.get().name == "local"
    monkeypatch.setenv("ROKID_TEST_WIDGET", "cloud")
    assert reg.get().name == "cloud"
    assert reg.get("local").name == "local"  # explicit arg wins over env


def test_unknown_name_falls_back_to_default(monkeypatch):
    reg = _make()
    reg.register(_item("local"))
    monkeypatch.delenv("ROKID_TEST_WIDGET", raising=False)
    assert reg.get("does-not-exist").name == "local"


def test_empty_registry_lazily_installs_default(monkeypatch):
    reg = _make()
    monkeypatch.delenv("ROKID_TEST_WIDGET", raising=False)
    assert reg.get().name == "local"
    assert "local" in reg
    assert [x["name"] for x in reg.list()] == ["local"]


def test_contains_and_list():
    reg = _make()
    reg.register(_item("a"))
    assert "a" in reg and "b" not in reg
    assert reg.list() == [{"name": "a"}]

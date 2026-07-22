"""Configuration import isolation."""

import importlib


def test_config_import_does_not_load_dotenv(monkeypatch):
    """Importing app.config must not pull credentials from a local .env."""
    import dotenv
    import app.config as config

    calls = []
    monkeypatch.setattr(
        dotenv,
        "load_dotenv",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    importlib.reload(config)

    assert calls == []

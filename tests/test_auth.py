"""Tests for the optional bearer auth (ROKID_API_KEY)."""

import importlib

from fastapi.testclient import TestClient


def _make_client(tmp_path, monkeypatch, api_key=None):
    monkeypatch.setenv("ROKID_DATA_DIR", str(tmp_path))
    if api_key is None:
        monkeypatch.delenv("ROKID_API_KEY", raising=False)
    else:
        monkeypatch.setenv("ROKID_API_KEY", api_key)
    import app.config as config
    importlib.reload(config)
    import app.db as db
    importlib.reload(db)
    import app.main as main
    importlib.reload(main)
    main.ensure_dirs()
    main.db.init_db()
    return TestClient(main.app)


def test_no_auth_by_default(tmp_path, monkeypatch):
    c = _make_client(tmp_path, monkeypatch, api_key=None)
    assert c.get("/health").status_code == 200
    assert c.post("/v1/documents", json={"title": "x"}).status_code == 201


def test_auth_required_when_key_set(tmp_path, monkeypatch):
    c = _make_client(tmp_path, monkeypatch, api_key="secret")

    # Protected endpoint without / with wrong bearer -> 401.
    assert c.post("/v1/documents", json={"title": "x"}).status_code == 401
    assert c.post(
        "/v1/documents", json={"title": "x"}, headers={"Authorization": "Bearer nope"}
    ).status_code == 401

    # Correct bearer -> 201.
    ok = c.post(
        "/v1/documents", json={"title": "x"}, headers={"Authorization": "Bearer secret"}
    )
    assert ok.status_code == 201

    # Discovery endpoints stay open (client negotiates before authenticating).
    assert c.get("/health").status_code == 200
    assert c.get("/v1/version").status_code == 200
    assert c.get("/v1/settings").status_code == 200
    # A trailing slash on a discovery URL must not lock the client out.
    assert c.get("/v1/settings/", follow_redirects=True).status_code == 200

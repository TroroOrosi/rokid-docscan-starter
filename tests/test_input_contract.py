"""Tests for the on-glasses input (KeyCode) contract at GET /v1/settings."""

import importlib

from fastapi.testclient import TestClient


def _make_client(tmp_path, monkeypatch, **env):
    monkeypatch.setenv("ROKID_DATA_DIR", str(tmp_path))
    for key, val in env.items():
        if val is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, val)
    import app.config as config
    importlib.reload(config)
    import app.db as db
    importlib.reload(db)
    import app.glasses_view as gv
    importlib.reload(gv)
    import app.main as main
    importlib.reload(main)
    main.ensure_dirs()
    main.db.init_db()
    return TestClient(main.app)


def test_input_contract_default(tmp_path, monkeypatch):
    c = _make_client(tmp_path, monkeypatch, ROKID_KEYMAP=None)
    inp = c.get("/v1/settings").json()["input"]
    g = inp["gestures"]
    assert g["tap"] == {"keycode": 23, "keyevent": "KEYCODE_DPAD_CENTER"}
    assert g["long_press"]["keycode"] == 170
    assert g["fast_swipe_left"]["keycode"] == 19
    assert g["back"]["keycode"] == 4
    assert inp["keycodes_verified"] is True
    assert inp["overridden"] is False


def test_input_contract_override(tmp_path, monkeypatch):
    c = _make_client(tmp_path, monkeypatch, ROKID_KEYMAP='{"tap": 99, "long_press": 88}')
    inp = c.get("/v1/settings").json()["input"]
    assert inp["gestures"]["tap"]["keycode"] == 99
    assert inp["gestures"]["long_press"]["keycode"] == 88
    # keyevent name is preserved on override; other gestures keep defaults.
    assert inp["gestures"]["tap"]["keyevent"] == "KEYCODE_DPAD_CENTER"
    assert inp["gestures"]["swipe_left"]["keycode"] == 21
    assert inp["overridden"] is True
    assert inp["keycodes_verified"] is True


def test_input_contract_ignores_bad_keymap(tmp_path, monkeypatch):
    # Malformed JSON is ignored (no crash), defaults stand.
    c = _make_client(tmp_path, monkeypatch, ROKID_KEYMAP="not json")
    inp = c.get("/v1/settings").json()["input"]
    assert inp["gestures"]["tap"]["keycode"] == 23
    assert inp["overridden"] is False

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
    # Official gesture names; KeyCode values are the legacy Rokid Glass table.
    assert g["single_tap"] == {"keycode": 23, "keyevent": "KEYCODE_DPAD_CENTER"}
    assert g["long_press"]["keycode"] == 170
    assert g["two_finger_swipe_up"]["keycode"] == 19
    assert g["back"]["keycode"] == 4
    # Honest flag: legacy keycodes are NOT verified on the current hardware.
    assert inp["keycodes_verified"] is False
    assert "unverified" in inp["keycode_source"]
    assert inp["overridden"] is False


def test_input_contract_override(tmp_path, monkeypatch):
    c = _make_client(
        tmp_path, monkeypatch, ROKID_KEYMAP='{"single_tap": 99, "long_press": 88}'
    )
    inp = c.get("/v1/settings").json()["input"]
    assert inp["gestures"]["single_tap"]["keycode"] == 99
    assert inp["gestures"]["long_press"]["keycode"] == 88
    # keyevent name is preserved on override; other gestures keep defaults.
    assert inp["gestures"]["single_tap"]["keyevent"] == "KEYCODE_DPAD_CENTER"
    assert inp["gestures"]["two_finger_swipe_left"]["keycode"] == 21
    assert inp["overridden"] is True
    # An override still doesn't make the defaults "verified".
    assert inp["keycodes_verified"] is False


def test_input_contract_ignores_bad_keymap(tmp_path, monkeypatch):
    # Malformed JSON is ignored (no crash), defaults stand.
    c = _make_client(tmp_path, monkeypatch, ROKID_KEYMAP="not json")
    inp = c.get("/v1/settings").json()["input"]
    assert inp["gestures"]["single_tap"]["keycode"] == 23
    assert inp["overridden"] is False


def test_input_contract_has_ai_activation_gesture(tmp_path, monkeypatch):
    # two_finger_tap (AI activation = 視認) is a system gesture with no
    # standard KeyCode; published so the glasses app can bind it if the
    # firmware delivers it as a KeyEvent (assign via ROKID_KEYMAP).
    c = _make_client(tmp_path, monkeypatch, ROKID_KEYMAP=None)
    g = c.get("/v1/settings").json()["input"]["gestures"]
    assert "two_finger_tap" in g
    assert g["two_finger_tap"]["keycode"] is None


def test_operations_cover_three_phase_flow(tmp_path, monkeypatch):
    c = _make_client(tmp_path, monkeypatch, ROKID_KEYMAP=None)
    ops = c.get("/v1/settings").json()["operations"]
    # Phase 1 読取: ephemeral recognition; device firmware owns camera/LED state.
    assert ops["recognize_page"] == "two_finger_tap"
    assert "capture_read" not in ops
    assert ops["finish_reading"] == "double_tap"
    # Phase 2 解答: the client handles long-press as mode/microphone audio only.
    assert ops["mode_toggle"] == "long_press"
    assert ops["audio_record_toggle"] == "long_press"
    assert "record_toggle" not in ops
    # Phase 3 閲覧 (visual sensor not needed): per-problem deck navigation
    assert ops["review_next_problem"] == "two_finger_swipe_left"
    assert ops["review_prev_problem"] == "two_finger_swipe_right"
    assert ops["scroll_next"] == "two_finger_swipe_down"
    assert ops["scroll_prev"] == "two_finger_swipe_up"
    assert ops["close"] == "double_tap"
    # Secondary/compat solve-current型 operations stay published.
    assert ops["exam_next_page"] == "two_finger_swipe_left"
    assert ops["exam_prev_page"] == "two_finger_swipe_right"
    assert ops["exam_solve_current"] == "single_tap"

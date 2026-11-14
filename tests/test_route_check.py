"""The check before use: every booklet route is tried as it stands, and the result is kept where the glasses can read it.

At the venue nothing told the wearer that a route had stopped (sign-in expired, usage limit, a changed page) until a
booklet had been photographed and sent (docs/whole-review-2026-11-14.md, 10.3 item 4).
"""
import importlib
import json

from fastapi.testclient import TestClient

from app.solvers.chatgpt_web import ChatGptWebAuthenticationRequired, ChatGptWebRateLimit

HEADERS = {"Authorization": "Bearer test-key"}


def _server(tmp_path, monkeypatch, *, primary="codex-cli", fallbacks=None):
    monkeypatch.setenv("ROKID_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ROKID_API_KEY", "test-key")
    monkeypatch.setenv("ROKID_SOLVER", primary)
    if fallbacks is None:
        monkeypatch.delenv("ROKID_SOLVER_FALLBACKS", raising=False)
    else:
        monkeypatch.setenv("ROKID_SOLVER_FALLBACKS", fallbacks)
    from app import config, db, main
    for module in (config, db, main):
        importlib.reload(module)
    main.ensure_dirs()
    main.db.init_db()
    return main


def _routes(monkeypatch, outcomes):
    """Each named route's check returns or raises what ``outcomes`` gives it; the calls made are returned."""
    from app.solvers.chatgpt_web import ChatGptWebSolver
    from app.solvers.codex_cli import CodexCliSolver
    called = []

    def stand_in(name):
        def check(self):
            called.append(name)
            outcome = outcomes[name]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return check

    monkeypatch.setattr(CodexCliSolver, "check", stand_in("codex-cli"))
    monkeypatch.setattr(ChatGptWebSolver, "check", stand_in("chatgpt-web"))
    return called


def test_a_check_tries_every_booklet_route_in_order_and_says_which_proof_was_a_real_request(tmp_path, monkeypatch):
    main = _server(tmp_path, monkeypatch)
    called = _routes(monkeypatch, {"codex-cli": True, "chatgpt-web": False})

    result = TestClient(main.app).post("/v1/route-check", headers=HEADERS).json()

    assert called == ["codex-cli", "chatgpt-web"]
    assert result["ok"] is True and result["checked_at"] > 0
    assert [(route["name"], route["ok"], route["code"], route["real"]) for route in result["routes"]] == [
        ("codex-cli", True, "ok", True), ("chatgpt-web", True, "ok", False)]
    assert all(route["seconds"] >= 0 for route in result["routes"])


def test_a_stopped_route_is_reported_by_its_code_and_never_by_the_providers_words(tmp_path, monkeypatch):
    main = _server(tmp_path, monkeypatch)
    _routes(monkeypatch, {"codex-cli": ChatGptWebRateLimit("You've hit your usage limit, secret-detail"),
                          "chatgpt-web": ChatGptWebAuthenticationRequired("login page for someone")})

    response = TestClient(main.app).post("/v1/route-check", headers=HEADERS)

    result = response.json()
    assert result["ok"] is False
    assert [(route["name"], route["ok"], route["code"]) for route in result["routes"]] == [
        ("codex-cli", False, "rate_limited"), ("chatgpt-web", False, "authentication_failed")]
    assert "secret-detail" not in response.text and "someone" not in response.text


def test_the_first_route_down_and_the_next_one_up_is_usable_and_says_so(tmp_path, monkeypatch):
    main = _server(tmp_path, monkeypatch)
    _routes(monkeypatch, {"codex-cli": ChatGptWebRateLimit("limit"), "chatgpt-web": False})

    result = TestClient(main.app).post("/v1/route-check", headers=HEADERS).json()

    assert result["ok"] is True and result["routes"][0]["ok"] is False and result["routes"][1]["ok"] is True


def test_the_last_result_is_kept_across_a_restart_and_shown_in_the_settings_the_glasses_read(tmp_path, monkeypatch):
    main = _server(tmp_path, monkeypatch)
    assert TestClient(main.app).get("/v1/settings").json()["route_check"] is None
    _routes(monkeypatch, {"codex-cli": True, "chatgpt-web": False})
    first = TestClient(main.app).post("/v1/route-check", headers=HEADERS).json()

    main = _server(tmp_path, monkeypatch)
    shown = TestClient(main.app).get("/v1/settings").json()["route_check"]

    assert shown == first
    assert json.loads((tmp_path / "route-check.json").read_text(encoding="utf-8")) == first


def test_running_a_check_needs_the_key(tmp_path, monkeypatch):
    main = _server(tmp_path, monkeypatch)
    called = _routes(monkeypatch, {"codex-cli": True, "chatgpt-web": False})

    assert TestClient(main.app).post("/v1/route-check").status_code == 401
    assert called == []


def test_a_check_is_due_when_none_was_made_or_the_last_is_older_than_the_interval(tmp_path, monkeypatch):
    main = _server(tmp_path, monkeypatch)
    _routes(monkeypatch, {"codex-cli": True, "chatgpt-web": False})

    assert main.route_check_due(now=1_000_000.0, interval=86400) is True
    checked = TestClient(main.app).post("/v1/route-check", headers=HEADERS).json()["checked_at"]
    assert main.route_check_due(now=checked + 3600, interval=86400) is False
    assert main.route_check_due(now=checked + 86400, interval=86400) is True
    assert main.route_check_due(now=checked + 10 * 86400, interval=0) is False, "0 turns the daily check off"


def test_a_route_without_a_check_of_its_own_is_looked_at_and_not_sent_to(tmp_path, monkeypatch):
    """The stand-in and the per-question routes answer ready() and make no request."""
    main = _server(tmp_path, monkeypatch, primary="recorded", fallbacks="")

    result = TestClient(main.app).post("/v1/route-check", headers=HEADERS).json()

    assert [(route["name"], route["real"]) for route in result["routes"]] == [("recorded", False)]

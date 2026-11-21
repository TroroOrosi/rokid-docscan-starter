"""The Codex CLI is kept at its newest stable release without anyone at the phone.

The operator, 2026-11-18: tools and models are to be kept at the latest. `codex exec` never looks for a newer
version of itself (codex-rs at rust-v0.170.0: only the interactive screen does, and it only says so), and the
service tells a CLI only of the models its version may use: GPT-6.2 Sol was out a day before the phone's CLI, one
release behind, could name it. These tests stand npm, the registry and the CLI in with functions.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from app import codex_update, config
from app.solvers import codex_cli

BINARY = "node_modules/@openai/codex-linux-arm64/vendor/aarch64-unknown-linux-musl/bin/codex"


class Host:
    """npm and the CLI on a made-up host: what was run, and what each run does."""

    def __init__(self, tmp_path: Path, have: str = "0.170.0", npm_fails: bool = False, wrong_version: str | None = None):
        self.old = tmp_path / "global" / "codex"
        self.old.parent.mkdir(parents=True)
        self.old.write_text(have, encoding="utf-8")
        self.npm_fails, self.wrong_version, self.ran = npm_fails, wrong_version, []

    def run(self, command, **options):
        command = [str(part) for part in command]
        self.ran.append(command)
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, f"codex-cli {Path(command[0]).read_text(encoding='utf-8')}\n", "")
        assert command[1:3] == ["install", "--prefix"], command
        if self.npm_fails:
            return subprocess.CompletedProcess(command, 1, "", "npm error network")
        wanted = command[4].rpartition("@")[2]
        binary = Path(command[3]) / BINARY
        binary.parent.mkdir(parents=True)
        binary.write_text(self.wrong_version or wanted, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "added 2 packages", "")

    def installs(self):
        return [command for command in self.ran if "install" in command]


@pytest.fixture
def host(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.delenv("ROKID_CODEX_BIN", raising=False)
    monkeypatch.delenv("ROKID_CODEX_UPDATE_HOURS", raising=False)
    return Host(tmp_path)


def _update(host, latest="0.171.0", verify=lambda binary: None):
    return codex_update.update(command=[str(host.old)], verify=verify, run=host.run, fetch=lambda: latest, npm="npm")


def test_a_newer_release_is_installed_beside_the_one_in_use_tried_and_only_then_used(host, tmp_path):
    tried = []
    result = _update(host, verify=tried.append)

    new = tmp_path / "data" / "codex-versions" / "0.171.0" / BINARY
    assert result == {"result": "updated", "from": "0.170.0", "to": "0.171.0"}
    assert tried == [str(new)], "one real request with the new binary before anything uses it"
    assert codex_update.chosen() == str(new) and host.old.read_text(encoding="utf-8") == "0.170.0", "the old one is left alone"
    [install] = host.installs()
    assert install[3:5] == [str(new.parents[6]), "@openai/codex@0.171.0"]
    # Termux calls itself android: without these npm leaves out the package that holds the binary.
    assert {"--os=linux", "--cpu=arm64", "--libc=musl"} <= set(install)
    state = codex_update.state()
    assert state["result"] == "updated" and state["version"] == "0.171.0" and state["checked_at"] <= time.time()


@pytest.mark.parametrize("change, step", [({"verify": "fails"}, "verify"), ({"npm_fails": True}, "install"),
                                          ({"wrong_version": "0.170.5"}, "version")])
def test_an_update_that_does_not_install_or_does_not_answer_changes_nothing(host, tmp_path, change, step):
    host.npm_fails, host.wrong_version = change.get("npm_fails", False), change.get("wrong_version")

    def verify(binary):
        if change.get("verify"):
            raise RuntimeError("the made-up request did not come back")

    result = _update(host, verify=verify)

    assert result == {"result": "failed", "step": step, "from": "0.170.0", "to": "0.171.0"}
    assert codex_update.chosen() is None and not (tmp_path / "data" / "codex-versions" / "0.171.0").exists()
    assert codex_update.state()["version"] == "0.170.0"


@pytest.mark.parametrize("latest, result", [("0.170.0", "current"), ("0.169.1", "current"), (None, "unknown"),
                                            ("0.171.0-alpha.13", "unknown"), ("latest", "unknown")])
def test_nothing_is_installed_when_the_registry_has_nothing_newer_and_stable(host, latest, result):
    assert _update(host, latest=latest)["result"] == result
    assert not host.installs() and codex_update.chosen() is None


def test_the_release_before_is_kept_and_older_ones_are_removed(host, tmp_path):
    for latest in ("0.171.0", "0.172.0", "0.173.0"):
        current = [codex_update.chosen() or str(host.old)]
        assert codex_update.update(command=current, verify=lambda binary: None, run=host.run, fetch=lambda: latest,
                                   npm="npm")["result"] == "updated"
    kept = sorted(path.name for path in (tmp_path / "data" / "codex-versions").iterdir() if path.is_dir())
    assert kept == ["0.172.0", "0.173.0"] and "0.173.0" in codex_update.chosen()


def test_the_route_runs_the_binary_an_update_chose_unless_one_is_named(host, tmp_path, monkeypatch):
    monkeypatch.setattr(codex_cli.shutil, "which", lambda name: str(host.old))
    monkeypatch.delenv("PREFIX", raising=False)
    assert codex_cli._command() == [str(host.old)]
    _update(host)
    assert codex_cli._command() == [codex_update.chosen()]
    Path(codex_update.chosen()).unlink()  # gone (storage cleared): back to the installed one, not a missing file
    assert codex_cli._command() == [str(host.old)]
    monkeypatch.setenv("ROKID_CODEX_BIN", str(host.old))
    assert codex_cli._command() == [str(host.old)]


def _at(hour: int, day: int = 19) -> float:
    return time.mktime((2026, 11, day, hour, 30, 0, 0, 0, -1))


def test_an_update_is_looked_for_once_a_night_and_never_in_the_hours_of_use(host, monkeypatch):
    """A release is some 70 MB to fetch and npm takes the phone's processor: at night, when the phone is at home."""
    assert [codex_update.due(_at(hour)) for hour in (0, 1, 4, 5, 9, 13, 23)] == [False, True, True, False, False, False, False]
    codex_update.note({"result": "current", "version": "0.170.0"}, now=_at(1))
    assert not codex_update.due(_at(4)), "once that night"
    assert codex_update.due(_at(2, day=20)), "and again the night after"
    monkeypatch.setenv("ROKID_CODEX_UPDATE_HOURS", "13-15")
    assert codex_update.due(_at(13, day=20)) and not codex_update.due(_at(2, day=21))
    monkeypatch.setenv("ROKID_CODEX_UPDATE_HOURS", "whenever")
    assert codex_update.due(_at(2, day=21)), "a setting that is no pair of hours is the night as it was"


def test_the_server_makes_an_attempt_only_when_set_to_and_checks_the_routes_after_an_update(host, monkeypatch, capsys):
    from app import main

    calls = []
    monkeypatch.setattr(codex_update, "due", lambda now: True)
    monkeypatch.setattr(codex_update, "update", lambda **given: calls.append(sorted(given)) or {
        "result": "updated", "from": "0.170.0", "to": "0.171.0"})
    monkeypatch.setattr(main, "run_route_check", lambda **given: calls.append("route check"))
    monkeypatch.delenv("ROKID_CODEX_AUTO_UPDATE", raising=False)
    main._update_codex()
    assert calls == [], "a host that is not set to keep the CLI up to date asks nothing"
    monkeypatch.setenv("ROKID_CODEX_AUTO_UPDATE", "1")
    main._update_codex()
    assert calls == [["command", "verify"], "route check"]
    assert '"codex_update"' in capsys.readouterr().out
    monkeypatch.setattr(codex_update, "due", lambda now: False)
    main._update_codex()
    assert len(calls) == 2, "not outside the night's hours"
    monkeypatch.setattr(codex_update, "due", lambda now: True)
    monkeypatch.setattr(codex_update, "update", lambda **given: (_ for _ in ()).throw(RuntimeError("made up")))
    main._update_codex()  # never raises: the thread that calls it also checks the routes every day
    assert '"codex_update_failed"' in capsys.readouterr().out


def test_the_state_kept_names_versions_and_times_only(host):
    _update(host, verify=lambda binary: (_ for _ in ()).throw(RuntimeError("a made-up sentence of the service")))
    kept = json.dumps(codex_update.state())
    assert "made-up" not in kept and set(codex_update.state()) <= {"result", "step", "from", "to", "version", "checked_at"}


def test_the_settings_say_what_the_last_attempt_found(host):
    from fastapi.testclient import TestClient

    from app import main

    assert TestClient(main.app).get("/v1/settings").json()["codex_update"] is None, "a host that never looked"
    _update(host)
    shown = TestClient(main.app).get("/v1/settings").json()["codex_update"]
    assert (shown["result"], shown["version"]) == ("updated", "0.171.0") and set(shown) == {"result", "from", "to", "version", "checked_at"}

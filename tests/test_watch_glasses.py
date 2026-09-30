"""Watcher checks run only against fake HTTP state and fake device calls."""

import subprocess

import pytest

from scripts import watch_glasses


def _watch(monkeypatch, states, spread=None, fail_launch=False, fail_once=None):
    observations = iter(states)
    spreads = iter(spread or ["1"] * len(states))
    commands = []
    failed_once = False

    def adb(serial, *args):
        nonlocal failed_once
        assert serial == "glasses:5555"
        if args == ("shell", "getprop", "ro.serialno"):
            return "expected"
        if args == ("shell", "getprop", "vendor.rkd.glasses.is_spread"):
            return next(spreads)
        commands.append(args)
        if fail_once in args and not failed_once:
            failed_once = True
            raise subprocess.CalledProcessError(1, "device")
        if fail_launch and "am" in args:
            raise subprocess.TimeoutExpired("device", 10)
        return ""

    monkeypatch.setattr(watch_glasses, "adb", adb)
    monkeypatch.setattr(watch_glasses, "fetch_state", lambda *args: next(observations))
    monkeypatch.setattr(watch_glasses.time, "sleep", lambda _: None)
    with pytest.raises(StopIteration):
        watch_glasses.watch("glasses:5555", "expected", 0.5)
    return commands


STATE = {"device_id": "expected", "source_ip": "10.0.0.10", "session_id": 7,
         "generation": 3, "sequence": 1, "phase": "capturing", "answer_ready": False}


def test_analyzing_sleeps_and_one_final_answer_wakes_only_the_matching_run(monkeypatch):
    waiting = {**STATE, "phase": "analyzing", "sequence": 2}
    answer = {**waiting, "answer_ready": True}
    done = {**answer, "phase": "writing_done", "sequence": 3}
    commands = _watch(monkeypatch, [STATE, waiting, waiting, answer, answer, done, done])
    power = [c for c in commands if "keyevent" in c]
    assert power == [("shell", "input", "-d", "0", "keyevent", "KEYCODE_SLEEP"),
                     ("shell", "input", "-d", "0", "keyevent", "KEYCODE_SLEEP")]
    launches = [c for c in commands if "am" in c]
    assert launches == [("shell", "am", "start", "-W", "-n", watch_glasses.COMPONENT,
                         "--ei", "wake_session_id", "7", "--el", "wake_generation", "3")]


@pytest.mark.parametrize("terminal", ["writing_done", "closed"])
def test_completion_after_ready_snapshot_never_lights_before_the_activity_validates(monkeypatch, terminal):
    ready = {**STATE, "phase": "analyzing", "answer_ready": True, "sequence": 2}
    snapshots = iter([ready, {**ready, "phase": terminal, "sequence": 3}])
    phase_on_glasses = "analyzing"
    commands = []
    accepted = []

    def fetch(*args):
        nonlocal phase_on_glasses
        snapshot = next(snapshots)
        # The phone GET returned an old ready snapshot; the user then finished.
        phase_on_glasses = terminal
        return snapshot

    def adb(serial, *args):
        if args == ("shell", "getprop", "ro.serialno"):
            return "expected"
        if args == ("shell", "getprop", "vendor.rkd.glasses.is_spread"):
            return "1"
        commands.append(args)
        if "am" in args:
            accepted.append(phase_on_glasses == "analyzing")
        return ""

    monkeypatch.setattr(watch_glasses, "fetch_state", fetch)
    monkeypatch.setattr(watch_glasses, "adb", adb)
    monkeypatch.setattr(watch_glasses.time, "sleep", lambda _: None)
    with pytest.raises(StopIteration):
        watch_glasses.watch("glasses:5555", "expected", 0.5)
    assert accepted == [False]
    assert [c for c in commands if "am" in c] == [
        ("shell", "am", "start", "-W", "-n", watch_glasses.COMPONENT,
         "--ei", "wake_session_id", "7", "--el", "wake_generation", "3")]
    assert not any("KEYCODE_WAKEUP" in command for command in commands)


def test_finished_or_closed_sessions_never_wake_from_a_late_answer(monkeypatch):
    commands = _watch(monkeypatch, [{**STATE, "phase": phase, "answer_ready": True}
                                   for phase in ("writing_done", "writing_done", "closed", "closed")])
    assert not any("am" in command or "KEYCODE_WAKEUP" in command for command in commands)


def test_fold_then_open_relaunches_chooser_once_and_an_unknown_launch_is_not_repeated(monkeypatch):
    commands = _watch(monkeypatch, [STATE] * 4, ["0", "1", "1", "1"], fail_launch=True)
    assert [c for c in commands if "KEYCODE_WAKEUP" in c] == [
        ("shell", "input", "-d", "0", "keyevent", "KEYCODE_WAKEUP")]
    assert [c for c in commands if "am" in c] == [
        ("shell", "am", "start", "-W", "-n", watch_glasses.COMPONENT, "--ez", "chooser", "true")]


@pytest.mark.parametrize("operation", ["KEYCODE_SLEEP", "wake_session_id"])
def test_failed_delivery_retries_the_same_run_after_reconnection(monkeypatch, operation):
    state = {**STATE, "phase": "analyzing", "answer_ready": operation == "wake_session_id"}
    commands = _watch(monkeypatch, [state] * 3, fail_once=operation)
    attempts = [command for command in commands if operation in command]
    assert len(attempts) == 2  # first failed; second succeeds; third is already delivered
    assert attempts[0] == attempts[1]


def test_discovery_chooses_the_android_identity_only_after_serial_verification(monkeypatch):
    selection = []
    phases = iter([{"devices": [{**STATE, "device_id": "android-id"}]},
                   {**STATE, "device_id": "android-id"}])
    monkeypatch.setattr(watch_glasses, "fetch_state", lambda server, device: (selection.append(device), next(phases))[1])
    monkeypatch.setattr(watch_glasses, "target", lambda requested, expected, state: "glasses:5555")
    monkeypatch.setattr(watch_glasses, "adb", lambda serial, *args: "expected" if "ro.serialno" in args else "1")
    monkeypatch.setattr(watch_glasses.time, "sleep", lambda _: None)
    with pytest.raises(StopIteration):
        watch_glasses.watch("glasses:5555", "expected", 0.5)
    assert selection == [None, "android-id", "android-id"]


def test_serial_mismatch_never_changes_display_or_volume(monkeypatch):
    monkeypatch.setattr(watch_glasses, "fetch_state", lambda *args: STATE)
    monkeypatch.setattr(watch_glasses, "adb", lambda *args: "different")
    with pytest.raises(SystemExit, match="identity"):
        watch_glasses.watch("glasses:5555", "expected", 0.5)


def test_auto_uses_only_the_authenticated_source_and_verifies_serial(monkeypatch):
    connects = []
    monkeypatch.setattr(watch_glasses.subprocess, "run", lambda args, **kw: connects.append(args))
    monkeypatch.setattr(watch_glasses, "adb", lambda serial, *args: "expected")
    assert watch_glasses.target("auto", "expected", STATE) == "10.0.0.10:5555"
    assert connects == [["adb", "connect", "10.0.0.10:5555"]]
    with pytest.raises(ValueError):
        watch_glasses.target("auto", "expected", {**STATE, "source_ip": "untrusted.example"})
    assert watch_glasses.target("glasses:5555", "expected", STATE) == "glasses:5555"


def test_fetch_state_distinguishes_server_and_authentication_failures(monkeypatch):
    import urllib.error
    monkeypatch.setenv("ROKID_API_KEY", "test-key")
    failures = iter([urllib.error.URLError("refused"), urllib.error.HTTPError("", 401, "", {}, None)])

    def urlopen(request, **kwargs):
        assert request.full_url == "http://127.0.0.1:8000/v1/glasses/state?device_id=expected"
        assert request.get_header("Authorization") == "Bearer test-key"
        raise next(failures)

    monkeypatch.setattr(watch_glasses.urllib.request, "urlopen", urlopen)
    for code in ("server_stopped", "authentication_failed"):
        with pytest.raises(watch_glasses.StateUnavailable, match=code):
            watch_glasses.fetch_state("http://127.0.0.1:8000", "expected")
    with pytest.raises(ValueError, match="loopback"):
        watch_glasses.fetch_state("http://example.org", "expected")

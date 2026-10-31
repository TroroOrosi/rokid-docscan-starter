"""Watcher checks run only against fake HTTP state and fake device calls."""

import subprocess
import asyncio
import io
import json
import socket
import struct
import sys
import time
from types import SimpleNamespace

import pytest

from scripts import watch_glasses

_REAL_APP_RUNNING = watch_glasses.app_running
_REAL_POPEN = subprocess.Popen


def _watch(monkeypatch, states, spread=None, fail_launch=False, fail_once=None, app_running=True, tick=0.5):
    observations = iter(states)
    spreads = iter(spread or ["1"] * len(states))
    commands = []
    failed_once = False
    elapsed = [0.0]

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
    def fetch(*args):
        observation = next(observations)
        if isinstance(observation, Exception):
            raise observation
        return observation

    monkeypatch.setattr(watch_glasses, "fetch_state", fetch)
    monkeypatch.setattr(watch_glasses, "app_running", lambda serial: app_running, raising=False)
    monkeypatch.setattr(watch_glasses.time, "monotonic", lambda: elapsed[0])
    def sleep(_):
        elapsed[0] += tick
    monkeypatch.setattr(watch_glasses.time, "sleep", sleep)
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
    assert power == [("shell", "input", "-d", "0", "keyevent", "KEYCODE_SOFT_SLEEP"),
                     ("shell", "input", "-d", "0", "keyevent", "KEYCODE_SOFT_SLEEP")]
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
    monkeypatch.setattr(watch_glasses, "app_running", lambda serial: True)
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


@pytest.mark.parametrize("operation", ["KEYCODE_SOFT_SLEEP", "wake_session_id"])
def test_failed_delivery_retries_the_same_run_after_reconnection(monkeypatch, operation):
    state = {**STATE, "phase": "analyzing", "answer_ready": operation == "wake_session_id"}
    commands = _watch(monkeypatch, [state] * 3, fail_once=operation)
    attempts = [command for command in commands if operation in command]
    assert len(attempts) == 2  # first failed; second succeeds; third is already delivered
    assert attempts[0] == attempts[1]


@pytest.mark.parametrize("failure", [watch_glasses.StateUnavailable("server_stopped"),
                                     subprocess.CalledProcessError(1, "device")])
def test_connection_recovery_redelivers_an_unacknowledged_revision_without_a_new_send(monkeypatch, failure):
    ready = {**STATE, "phase": "analyzing", "answer_ready": True,
             "available_stage": "reading", "answer_revision": 1}
    commands = _watch(monkeypatch, [ready, failure, ready, ready])
    launches = [command for command in commands if "wake_session_id" in command]
    assert len(launches) == 2
    assert launches[0] == launches[1]
    assert not any("KEYCODE_WAKEUP" in command for command in commands)


def test_discovery_chooses_the_android_identity_only_after_serial_verification(monkeypatch):
    selection = []
    phases = iter([{"devices": [{**STATE, "device_id": "android-id"}]},
                   {**STATE, "device_id": "android-id"}])
    monkeypatch.setattr(watch_glasses, "fetch_state", lambda server, device: (selection.append(device), next(phases))[1])
    monkeypatch.setattr(watch_glasses, "target", lambda requested, expected, state: "glasses:5555")
    monkeypatch.setattr(watch_glasses, "adb", lambda serial, *args: "expected" if "ro.serialno" in args else "1")
    monkeypatch.setattr(watch_glasses, "app_running", lambda serial: True)
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


def test_explicit_chooser_waits_for_sleep_and_same_phase_can_sleep_again_after_input(monkeypatch):
    awake = {**STATE, "phase": "chooser", "session_id": None, "display_request": "wake"}
    asleep = {**awake, "sequence": 2, "display_request": "sleep"}
    awake_again = {**awake, "sequence": 3}
    asleep_again = {**asleep, "sequence": 4}
    commands = _watch(monkeypatch, [awake, awake, asleep, asleep, awake_again, asleep_again, asleep_again])
    assert len([c for c in commands if "KEYCODE_SOFT_SLEEP" in c]) == 2
    assert not any("am" in c for c in commands), "ordinary wake is never a chooser-entry command"


@pytest.mark.parametrize("phase", ["capturing", "reading"])
def test_a_new_active_phase_cancels_a_sleep_snapshot_before_device_input(monkeypatch, phase):
    sleep = {**STATE, "phase": "analyzing", "display_request": "sleep"}
    active = {**sleep, "phase": phase, "sequence": 2, "display_request": "wake"}
    commands = _watch(monkeypatch, [sleep, active])
    assert not any("KEYCODE_SOFT_SLEEP" in c for c in commands)


def test_mixed_answers_notify_each_new_revision_even_while_the_reader_is_open(monkeypatch):
    reading = {**STATE, "phase": "waiting", "answer_ready": True,
               "available_stage": "reading", "answer_revision": 1, "display_request": "sleep"}
    complete = {**reading, "phase": "reading", "sequence": 2,
                "available_stage": "complete", "answer_revision": 2, "display_request": "wake"}
    commands = _watch(monkeypatch, [reading, reading, complete, complete,
                                   {**complete, "phase": "writing_done", "sequence": 3}])
    launches = [c for c in commands if "wake_session_id" in c]
    assert len(launches) == 2
    assert launches[0][-2:] == ("answer_revision", "1")
    assert launches[1][-2:] == ("answer_revision", "2")


def test_only_received_revision_acknowledges_delivery_not_reader_phase_or_interim_waiting(monkeypatch):
    first = {**STATE, "phase": "analyzing", "answer_ready": True, "available_stage": "reading",
             "answer_revision": 1, "ack_answer_revision": None}
    received = {**first, "phase": "reading", "sequence": 2, "ack_answer_revision": 1}
    waiting = {**received, "phase": "waiting", "sequence": 3}
    final = {**waiting, "phase": "reading", "available_stage": "complete", "answer_revision": 2}
    final_received = {**final, "sequence": 4, "ack_answer_revision": 2}
    commands = _watch(monkeypatch, [first, first, received, waiting, final, final, final_received, final_received], tick=5)
    revisions = [command[-1] for command in commands if "wake_session_id" in command]
    assert revisions == ["1", "1", "2", "2"], "no receipt or phase inference may suppress the retry"


def test_acknowledged_revision_does_not_reopen_after_api_recovery_or_at_terminal(monkeypatch):
    received = {**STATE, "phase": "waiting", "answer_ready": True, "available_stage": "reading",
                "answer_revision": 1, "ack_answer_revision": 1}
    terminal = {**received, "phase": "writing_done", "sequence": 2, "ack_answer_revision": None}
    commands = _watch(monkeypatch, [received, watch_glasses.StateUnavailable("server_stopped"), received, terminal], tick=5)
    assert not any("wake_session_id" in command for command in commands)


def test_interim_reading_done_sleeps_after_its_received_revision_but_a_new_revision_prevents_sleep(monkeypatch):
    received = {**STATE, "phase": "waiting", "sequence": 2, "display_request": "sleep", "answer_ready": True,
                "available_stage": "reading", "answer_revision": 1, "ack_answer_revision": 1}
    final = {**received, "sequence": 3, "available_stage": "complete", "answer_revision": 2}
    commands = _watch(monkeypatch, [received, received, final, final], tick=0.5)
    assert len([command for command in commands if "KEYCODE_SOFT_SLEEP" in command]) == 1
    assert len([command for command in commands if "wake_session_id" in command]) == 1


def test_an_older_generation_or_sequence_never_applies_a_late_display_request(monkeypatch):
    active = {**STATE, "phase": "reading", "generation": 4, "sequence": 5, "display_request": "wake"}
    stale = {**active, "phase": "analyzing", "generation": 3, "sequence": 99, "display_request": "sleep"}
    commands = _watch(monkeypatch, [active, stale])
    assert not any("KEYCODE_SOFT_SLEEP" in c for c in commands)


def test_sleep_readback_failure_is_unknown_and_does_not_change_the_display(monkeypatch):
    sleep = {**STATE, "phase": "analyzing", "display_request": "sleep"}
    commands = _watch(monkeypatch, [sleep, watch_glasses.StateUnavailable("server_stopped"), STATE])
    assert not any("KEYCODE_SOFT_SLEEP" in c for c in commands)


def test_sleep_dispatch_and_cancellation_report_only_fixed_power_metadata(monkeypatch, capsys):
    asleep = {**STATE, "phase": "chooser", "session_id": None, "display_request": "sleep"}
    commands = _watch(monkeypatch, [asleep, asleep])
    assert len([command for command in commands if "KEYCODE_SOFT_SLEEP" in command]) == 1
    output = capsys.readouterr().out
    assert "Display action=sleep outcome=dispatched generation=3 sequence=1 phase=chooser" in output
    assert "expected" not in output and "10.0.0.10" not in output

    active = {**asleep, "phase": "reading", "sequence": 2, "display_request": "wake"}
    commands = _watch(monkeypatch, [asleep, active])
    assert not any("KEYCODE_SOFT_SLEEP" in command for command in commands)
    assert "Display action=sleep outcome=suppressed generation=3 sequence=1 phase=chooser" in capsys.readouterr().out


def test_unknown_sleep_delivery_is_logged_without_claiming_display_off(monkeypatch, capsys):
    asleep = {**STATE, "phase": "chooser", "session_id": None, "display_request": "sleep"}
    _watch(monkeypatch, [asleep, asleep], fail_once="KEYCODE_SOFT_SLEEP")
    output = capsys.readouterr().out
    assert "Display action=sleep outcome=unknown generation=3 sequence=1 phase=chooser" in output
    assert "outcome=dispatched" not in output


@pytest.mark.parametrize("protected_phase", ["capturing", "reading", "chooser"])
def test_sleep_delivery_respects_the_os_display_hold_after_the_final_http_read(monkeypatch, protected_phase):
    asleep = {**STATE, "phase": "waiting", "display_request": "sleep"}
    active = {**asleep, "phase": protected_phase, "sequence": 2, "display_request": "wake"}
    snapshots = iter([asleep, asleep, active])
    reads = 0
    holding = False
    interactive = True

    def fetch(*args):
        nonlocal reads, holding
        snapshot = next(snapshots)
        reads += 1
        if reads == 2:
            # The Activity enters capture/reading after the last GET: PMS must
            # evaluate its current WindowManager screen hold when handling input.
            holding = True
        return snapshot

    def adb(serial, *args):
        nonlocal interactive
        if args == ("shell", "getprop", "ro.serialno"):
            return "expected"
        if args == ("shell", "getprop", "vendor.rkd.glasses.is_spread"):
            return "1"
        if "keyevent" in args:
            if "KEYCODE_SLEEP" in args or ("KEYCODE_SOFT_SLEEP" in args and not holding):
                interactive = False
        return ""

    monkeypatch.setattr(watch_glasses, "fetch_state", fetch)
    monkeypatch.setattr(watch_glasses, "adb", adb)
    monkeypatch.setattr(watch_glasses, "app_running", lambda serial: True)
    monkeypatch.setattr(watch_glasses.time, "sleep", lambda _: None)
    with pytest.raises(StopIteration):
        watch_glasses.watch("glasses:5555", "expected", 0.5)
    assert interactive, "a late sleep must respect the hold at input delivery, not the old HTTP snapshot"


def test_initial_already_spread_bootstraps_a_stopped_app_once_without_claiming_wear(monkeypatch):
    commands = _watch(monkeypatch, [STATE] * 3, app_running=False)
    launches = [c for c in commands if "am" in c]
    assert launches == [("shell", "am", "start", "-W", "-n", watch_glasses.COMPONENT,
                        "--ez", "chooser", "true", "--ez", "wear_bootstrap", "true")]
    assert not any("wear_origin" in c for c in commands), "spread is only a sensor/bootstrap entrance"


def test_confirmed_wear_entry_uses_a_fresh_chooser_and_never_old_answer_extras(monkeypatch):
    worn = {**STATE, "generation": 4, "phase": "chooser", "session_id": None,
            "display_request": "wake", "entry_request": "chooser"}
    commands = _watch(monkeypatch, [worn] * 3)
    assert [c for c in commands if "am" in c] == [
        ("shell", "am", "start", "-W", "-n", watch_glasses.COMPONENT, "--ez", "chooser", "true",
         "--ez", "wear_origin", "true", "--el", "wear_generation", "4")]
    assert not any("wake_session_id" in c or "KEYCODE_WAKEUP" in c for c in commands)


def test_only_a_clean_process_miss_authorizes_the_bootstrap(monkeypatch):
    monkeypatch.setattr(watch_glasses, "app_running", _REAL_APP_RUNNING)
    values = iter([subprocess.CompletedProcess([], 0, "123 456\n", ""),
                   subprocess.CompletedProcess([], 1, "", ""),
                   subprocess.CompletedProcess([], 1, "", "device offline")])
    def run(args, **kwargs):
        assert args == ["adb", "-s", "glasses:5555", "shell", "pidof", "dev.rokid.docscanglass.doc"]
        return next(values)
    monkeypatch.setattr(watch_glasses.subprocess, "run", run)
    assert watch_glasses.app_running("glasses:5555")
    assert not watch_glasses.app_running("glasses:5555")
    with pytest.raises(subprocess.SubprocessError):
        watch_glasses.app_running("glasses:5555")


def _discovery_watch(monkeypatch, states, rows, *, launch_unknown=False, identities=None, ticks=20, spreads=None,
                     fallback=None, native_code=0):
    """Exercise the watcher through HTTP/ADB/socket boundaries, without devices."""
    observations = iter(states)
    advertisements = iter([rows] * len(states) if isinstance(rows, str) else rows)
    calls, selections = [], []
    elapsed, running = [0.0], [False]
    spread_values = iter(spreads) if spreads else None

    class DiscoveryProcess:
        def __init__(self, args, **kwargs):
            assert kwargs["stdout"] == subprocess.PIPE and kwargs["stderr"] == subprocess.DEVNULL
            calls.append(tuple(args))
            if args == ["adb", "mdns", "services"]:
                raw, self.returncode = next(advertisements).encode(), native_code
            else:
                assert args == [sys.executable, "-B", str(watch_glasses.Path(watch_glasses.__file__).resolve()),
                                "--mdns-unicast-child"]
                raw, self.returncode = json.dumps(fallback or []).encode(), 0
            self.stdout = io.BytesIO(raw)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stdout.close()

        def poll(self):
            return self.returncode

        def kill(self):
            self.returncode = -9

        def wait(self, **kwargs):
            return self.returncode

    class RouteSocket:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def connect(self, address):
            pass  # UDP route lookup only; no packet is sent.

        def getsockname(self):
            return ("10.248.83.1", 35000)

    def fetch(server, selected):
        selections.append(selected)
        calls.append(("fetch", selected))
        state = next(observations)
        if isinstance(state, Exception):
            raise state
        return state

    def run(args, **kwargs):
        calls.append(tuple(args))
        if args[:2] == ["adb", "connect"] and args[2] == "10.0.0.10:5555":
            raise subprocess.TimeoutExpired("old source", kwargs["timeout"])
        output, code = "", 0
        if "ro.serialno" in args:
            output = (identities or {}).get(args[2], "expected")
            if isinstance(output, Exception):
                raise output
        elif "vendor.rkd.glasses.is_spread" in args:
            output = next(spread_values) if spread_values else "1"
        elif "pidof" in args:
            output, code = ("123", 0) if running[0] else ("", 1)
        elif "wear_bootstrap" in args:
            if launch_unknown:
                raise subprocess.TimeoutExpired("launch", kwargs["timeout"])
            running[0] = True
        return subprocess.CompletedProcess(args, code, output, "")

    monkeypatch.setattr(watch_glasses.subprocess, "Popen", DiscoveryProcess)
    monkeypatch.setattr(watch_glasses.subprocess, "run", run)
    monkeypatch.setattr(socket, "socket", lambda *args: RouteSocket())
    monkeypatch.setattr(watch_glasses, "fetch_state", fetch)
    monkeypatch.setattr(watch_glasses.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(watch_glasses.time, "sleep", lambda _: elapsed.__setitem__(0, elapsed[0] + ticks))
    with pytest.raises(StopIteration):
        watch_glasses.watch("auto", "expected", 0.5)
    return calls, selections


@pytest.mark.parametrize("first", [{"devices": [STATE]}, {"devices": []},
                                   watch_glasses.StateUnavailable("waiting_for_glasses")])
def test_missing_or_old_source_discovers_serial_before_bootstrap_then_uses_real_state(monkeypatch, first):
    real = {**STATE, "device_id": "real-android-id", "source_ip": "10.248.83.42", "generation": 9}
    calls, selections = _discovery_watch(monkeypatch, [first, {"devices": [real]}, real, real],
                                         "List of discovered mdns services\nnot-an-android-id\t_adb._tcp\t10.248.83.42:5555\n")
    launches = [call for call in calls if "am" in call]
    assert launches == [("adb", "-s", "10.248.83.42:5555", "shell", "am", "start", "-W", "-n",
                         watch_glasses.COMPONENT, "--ez", "chooser", "true", "--ez", "wear_bootstrap", "true")]
    assert ("adb", "mdns", "services") in calls
    assert calls.index(launches[0]) < [i for i, call in enumerate(calls) if call[0] == "fetch"][1]
    assert calls.index(("adb", "-s", "10.248.83.42:5555", "shell", "getprop", "ro.serialno")) < calls.index(launches[0])
    assert "real-android-id" in selections and "not-an-android-id" not in selections
    assert not any("wear_origin" in call or "wake_session_id" in call for call in calls)


def test_mdns_never_controls_tls_self_wrong_port_or_serial_mismatch(monkeypatch):
    rows = ("phone\t_adb._tcp\t10.248.83.1:5555\n"
            "tls\t_adb-tls-connect._tcp\t10.248.83.43:5555\n"
            "pair\t_adb-tls-pairing._tcp\t10.248.83.44:5555\n"
            "v6\t_adb._tcp\t[::1]:5555\n"
            "other-port\t_adb._tcp\t10.248.83.45:4444\n"
            "loopback\t_adb._tcp\t127.0.0.1:5555\n"
            "wrong\t_adb._tcp\t10.248.83.46:5555\n"
            "right\t_adb._tcp.\t10.248.83.42:5555\n"
            "duplicate\t_adb._tcp\t10.248.83.42:5555\n")
    calls, _ = _discovery_watch(monkeypatch, [{"devices": []}], rows,
                                 identities={"10.248.83.46:5555": "different"})
    assert [c for c in calls if c[:2] == ("adb", "connect")] == [
        ("adb", "connect", "10.248.83.46:5555"), ("adb", "connect", "10.248.83.42:5555")]
    controls = [c for c in calls if "am" in c or "settings" in c or "keyevent" in c or "volume" in c]
    assert len(controls) == 1 and controls[0][2] == "10.248.83.42:5555"


@pytest.mark.parametrize("identity", ["different", subprocess.TimeoutExpired("identity", 3)])
def test_unknown_or_mismatched_discovery_identity_has_no_device_control(monkeypatch, identity):
    calls, _ = _discovery_watch(monkeypatch, [{"devices": []}], "candidate\t_adb._tcp\t10.248.83.42:5555\n",
                                 identities={"10.248.83.42:5555": identity})
    assert not any("am" in c or "keyevent" in c or "settings" in c or "volume" in c or "pidof" in c for c in calls)


def test_unknown_bootstrap_is_not_repeated_when_advertised_IP_changes(monkeypatch):
    calls, selections = _discovery_watch(monkeypatch, [{"devices": []}] * 2,
                                           [f"same-device\t_adb._tcp\t10.248.83.{n}:5555\n" for n in (42, 43)],
                                           launch_unknown=True)
    assert len([c for c in calls if "ro.serialno" in c]) == 2
    assert len([c for c in calls if "wear_bootstrap" in c]) == 1
    assert set(selections) == {None}
    assert not any("KEYCODE_WAKEUP" in c or "wake_session_id" in c or "wear_origin" in c for c in calls)


def test_discovered_fold_open_bootstrap_does_not_repeat_chooser_after_authenticated_notice(monkeypatch):
    real = {**STATE, "source_ip": "10.248.83.42"}
    calls, _ = _discovery_watch(monkeypatch, [{"devices": []}, {"devices": []}, {"devices": [real]}, real],
                                 "glasses\t_adb._tcp\t10.248.83.42:5555\n", spreads=["0", "1", "1"])
    launches = [c for c in calls if "am" in c]
    assert len(launches) == 1 and "wear_bootstrap" in launches[0]
    assert not any("KEYCODE_WAKEUP" in c for c in calls)


def test_reachable_authenticated_source_does_not_query_mdns(monkeypatch):
    state = {**STATE, "source_ip": "10.248.83.42"}
    calls, _ = _discovery_watch(monkeypatch, [state, state], "must not be read")
    assert ("adb", "mdns", "services") not in calls


@pytest.mark.parametrize("code", ["authentication_failed", "server_stopped", "state_unavailable"])
def test_api_authentication_or_unknown_state_failure_does_not_start_discovery(monkeypatch, code):
    calls, _ = _discovery_watch(monkeypatch, [watch_glasses.StateUnavailable(code)], "must not be read")
    assert not any(call[0] == "adb" for call in calls)


@pytest.mark.parametrize("rows", ["x" * 8193,
                                  "\n".join(f"c{n}\t_adb._tcp\t10.248.83.{n}:5555" for n in range(10, 15)),
                                  "not a service\n" * 66, "List of discovered mdns services\n"],
                         ids=["oversized", "too_many_candidates", "too_many_rows", "empty_or_unsupported"])
def test_unavailable_overflow_or_too_many_advertisements_never_guess_a_target(monkeypatch, rows):
    calls, _ = _discovery_watch(monkeypatch, [{"devices": []}], rows)
    assert not any(call[:2] == ("adb", "connect") for call in calls)


@pytest.mark.parametrize("script", ["import time;time.sleep(30)",
                                    "import sys,time;sys.stdout.buffer.write(b'x'*8193);sys.stdout.flush();time.sleep(30)"])
def test_mdns_output_and_time_limits_reap_only_the_owned_short_lived_cli(monkeypatch, script):
    children = []
    def popen(args, **kwargs):
        assert args == ["adb", "mdns", "services"]
        child = _REAL_POPEN([sys.executable, "-B", "-c", script], **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(watch_glasses.subprocess, "Popen", popen)
    monkeypatch.setattr(watch_glasses, "MDNS_TIMEOUT_SECONDS", 0.2)
    started = time.monotonic()
    with pytest.raises(watch_glasses.StateUnavailable, match="discovery_unavailable"):
        watch_glasses.mdns_services()
    assert time.monotonic() - started < 3 and len(children) == 1 and children[0].poll() is not None


@pytest.mark.parametrize("native_code", [0, 1])
def test_native_empty_or_unavailable_uses_child_before_serial_verified_bootstrap(monkeypatch, native_code):
    calls, selections = _discovery_watch(monkeypatch, [{"devices": []}], "", native_code=native_code,
                                         fallback=["10.248.83.42:5555"])
    child = next(c for c in calls if "--mdns-unicast-child" in c)
    identity = ("adb", "-s", "10.248.83.42:5555", "shell", "getprop", "ro.serialno")
    launch = next(c for c in calls if "wear_bootstrap" in c)
    assert calls.index(child) < calls.index(identity) < calls.index(launch)
    assert selections == [None, None]


def test_native_candidate_does_not_start_library_after_serial_mismatch(monkeypatch):
    calls, _ = _discovery_watch(monkeypatch, [{"devices": []}], "candidate\t_adb._tcp\t10.248.83.42:5555\n",
                                 fallback=["10.248.83.43:5555"], identities={"10.248.83.42:5555": "other"})
    assert not any("--mdns-unicast-child" in c or "wear_bootstrap" in c for c in calls)


def test_hotspot_address_is_read_again_without_interface_enumeration(monkeypatch):
    addresses = iter(["10.129.169.180", "10.248.83.1"])
    bindings = []

    def ioctl(fd, request, data):
        assert fd == 7 and request == 0x8915 and data == struct.pack("256s", b"ap0")
        return b"\0" * 16 + struct.pack("H", socket.AF_INET) + b"\0\0" + socket.inet_aton(next(addresses))

    class AP:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def fileno(self):
            return 7

        def bind(self, address):
            bindings.append(address)

    monkeypatch.setitem(sys.modules, "fcntl", SimpleNamespace(ioctl=ioctl))
    monkeypatch.setattr(socket, "socket", lambda *args: AP())
    monkeypatch.setattr(socket, "if_nameindex", lambda: pytest.fail("restricted enumeration"))
    assert watch_glasses._hotspot_ipv4() == "10.129.169.180"
    assert watch_glasses._hotspot_ipv4() == "10.248.83.1"
    assert bindings == [("10.129.169.180", 0), ("10.248.83.1", 0)]


@pytest.mark.parametrize("raw", [b'log\n["10.248.83.42:5555"]', b'[]\nlog', b'{}',
                                 b'["127.0.0.1:5555"]', b'["10.248.83.42:4444"]',
                                 b'["10.248.83.42:5555", "10.248.83.42:5555"]',
                                 json.dumps([f"10.248.83.{n}:5555" for n in range(10, 15)]).encode()])
def test_unicast_child_rejects_pollution_shape_and_candidate_overflow(monkeypatch, raw):
    monkeypatch.setattr(watch_glasses, "_mdns_output", lambda *args: raw)
    with pytest.raises(watch_glasses.StateUnavailable, match="discovery_unavailable"):
        watch_glasses.unicast_mdns_candidates(4)


@pytest.mark.parametrize("script", ["import time;time.sleep(30)",
                                    "import sys,time;sys.stdout.buffer.write(b'x'*8193);sys.stdout.flush();time.sleep(30)"])
def test_unicast_timeout_or_overflow_kills_only_owned_library_child(monkeypatch, script):
    children = []

    def popen(args, **kwargs):
        assert args == [sys.executable, "-B", str(watch_glasses.Path(watch_glasses.__file__).resolve()),
                        "--mdns-unicast-child"]
        child = _REAL_POPEN([sys.executable, "-B", "-c", script], **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(watch_glasses.subprocess, "Popen", popen)
    started = time.monotonic()
    with pytest.raises(watch_glasses.StateUnavailable, match="discovery_unavailable"):
        watch_glasses.unicast_mdns_candidates(0.2)
    assert time.monotonic() - started < 3 and len(children) == 1 and children[0].poll() is not None


@pytest.mark.parametrize("overflow", [None, "candidates", "services"])
def test_library_explicit_ipv4_unicast_resolves_only_legacy_port_and_excludes_self(monkeypatch, overflow):
    added, removed = object(), object()
    events = []
    state = SimpleNamespace(Added=added, Updated=object(), Removed=removed)
    version = SimpleNamespace(V4Only=object())

    class Client:
        def __init__(self, **kwargs):
            assert kwargs == {"interfaces": ["10.129.169.180"], "ip_version": version.V4Only, "unicast": True}
            self.zeroconf = self

        async def async_get_service_info(self, service, name, timeout):
            assert service == "_adb._tcp.local." and 0 < timeout <= 500
            events.append(name)
            addresses = ([f"10.129.169.{n}" for n in range(10, 15)] if overflow == "candidates"
                         else ["10.129.169.180", "10.129.169.42", "127.0.0.1", "::1"])
            return SimpleNamespace(port=5555 if name.startswith("right") else 4444,
                                   parsed_addresses=lambda v: addresses)

        async def async_close(self):
            events.append("closed")

    class Browser:
        def __init__(self, zc, service, handlers):
            assert service == "_adb._tcp.local."
            names = ([f"right{n}._adb._tcp.local." for n in range(65)] if overflow == "services"
                     else ["wrong._adb._tcp.local.", "right._adb._tcp.local."])
            for name in names:
                handlers[0](zeroconf=zc, service_type=service, name=name, state_change=added)

        async def async_cancel(self):
            events.append("cancelled")

    monkeypatch.setitem(sys.modules, "zeroconf", SimpleNamespace(__version__="0.151.6", IPVersion=version,
                                                                ServiceStateChange=state))
    monkeypatch.setitem(sys.modules, "zeroconf.asyncio", SimpleNamespace(AsyncZeroconf=Client, AsyncServiceBrowser=Browser))
    if overflow:
        with pytest.raises(watch_glasses.StateUnavailable, match="discovery_unavailable"):
            asyncio.run(watch_glasses._unicast_services("10.129.169.180"))
        assert events[-2:] == ["cancelled", "closed"]
    else:
        assert asyncio.run(watch_glasses._unicast_services("10.129.169.180")) == ["10.129.169.42:5555"]
        assert events == ["wrong._adb._tcp.local.", "right._adb._tcp.local.", "cancelled", "closed"]

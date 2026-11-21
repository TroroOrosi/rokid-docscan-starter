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

_REAL_POPEN = subprocess.Popen


@pytest.fixture(autouse=True)
def _no_real_process(monkeypatch):
    """A test that forgets its fake fails; it never starts adb."""
    def refuse(argv, **kwargs):
        raise AssertionError(f"unfaked process: {argv[0]}")

    monkeypatch.setattr(watch_glasses.subprocess, "run", refuse)


def _device(argv, command, check=False, **_):
    """Stand in for subprocess.run, adb and the device's sh.

    The watcher sends one command with its words as arguments, or one line of
    several commands with a status mark after each but the last. `command(words)`
    answers each device command with (exit status, output), or raises.
    """
    status, output = 0, ""
    for part in " ".join(argv[4:]).split("; "):
        if part == "echo __watch_step:$?":
            output += f"__watch_step:{status}\n"
            continue
        try:
            status, text = command(tuple(part.removesuffix(" 2>&1").split()))
        except subprocess.TimeoutExpired as late:
            # As subprocess.run does on the phone: what was printed so far, as bytes.
            raise subprocess.TimeoutExpired(argv, late.timeout, output=output.encode() or None) from None
        output += f"{text}\n" if text else ""
    if check and status:
        raise subprocess.CalledProcessError(status, argv)
    return subprocess.CompletedProcess(argv, status, output, "")


def _fake_device(monkeypatch, adb, running=True):
    """Answer every adb process from `adb(serial, "shell", *words)`.

    That is the shape these tests' fakes always had: one call for each device
    command, also when several arrive in one line. What it returns is the
    command's output and a CalledProcessError it raises is a nonzero exit
    status. pidof is answered by `running`; None is an answer that cannot be
    told. Returns the processes started, each as the arguments after the serial.
    """
    trips = []

    def run(argv, **kwargs):
        assert argv[:2] == ["adb", "-s"] and argv[3] == "shell"
        trips.append(tuple(argv[3:]))

        def command(words):
            if words[0] == "pidof":
                return {True: (0, "123"), False: (1, ""), None: (2, "")}[running]
            try:
                return 0, adb(argv[2], "shell", *words)
            except subprocess.CalledProcessError:
                return 1, ""

        return _device(argv, command, **kwargs)

    monkeypatch.setattr(watch_glasses.subprocess, "run", run)
    return trips


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

    _fake_device(monkeypatch, adb, running=app_running)
    def fetch(*args):
        observation = next(observations)
        if isinstance(observation, Exception):
            raise observation
        return observation

    monkeypatch.setattr(watch_glasses, "fetch_state", fetch)
    monkeypatch.setattr(watch_glasses.time, "monotonic", lambda: elapsed[0])
    def sleep(_):
        elapsed[0] += tick
    monkeypatch.setattr(watch_glasses.time, "sleep", sleep)
    with pytest.raises(StopIteration):
        watch_glasses.watch("glasses:5555", "expected", 0.5)
    return commands


STATE = {"device_id": "expected", "source_ip": "10.0.0.10", "session_id": 7,
         "generation": 3, "sequence": 1, "phase": "capturing", "answer_ready": False}
READY = {**STATE, "phase": "analyzing", "sequence": 2, "answer_ready": True}

# The lines the watcher sends as one adb round trip, written out: each is the
# argument after the serial. `__watch_step:$?` prints the exit status of the
# command before it.
MUTE_BUT_LAST = ("settings put system sound_effects_enabled 0 2>&1; echo __watch_step:$?; "
                 "cmd media_session volume --stream 1 --set 0 2>&1; echo __watch_step:$?; "
                 "cmd media_session volume --stream 2 --set 0 2>&1; echo __watch_step:$?; "
                 "cmd media_session volume --stream 3 --set 0 2>&1; echo __watch_step:$?; "
                 "cmd media_session volume --stream 4 --set 0 2>&1; echo __watch_step:$?; "
                 "cmd media_session volume --stream 5 --set 0 2>&1; echo __watch_step:$?; "
                 "cmd media_session volume --stream 8 --set 0 2>&1; echo __watch_step:$?; ")
MUTE = ("shell", MUTE_BUT_LAST + "cmd media_session volume --stream 10 --set 0")
MUTE_THEN = MUTE_BUT_LAST + "cmd media_session volume --stream 10 --set 0 2>&1; echo __watch_step:$?; "
FOLD_AND_PROCESS = ("shell", "getprop vendor.rkd.glasses.is_spread 2>&1; echo __watch_step:$?; "
                             "pidof dev.rokid.docscanglass.doc")
SERIAL_READ = ("shell", "getprop", "ro.serialno")
VOLUME_READ = ("shell", "cmd", "media_session", "volume", "--stream", "3", "--get")
WAKE = ("am start -W -n dev.rokid.docscanglass.doc/dev.rokid.docscanglass.doc.DocScanGlassActivity "
        "--ei wake_session_id 7 --el wake_generation 3")


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
    _fake_device(monkeypatch, adb)
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
    _fake_device(monkeypatch, lambda serial, *args: "expected" if "ro.serialno" in args else "1")
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


def test_a_verified_idle_request_precedes_slow_fold_and_process_diagnostics(monkeypatch):
    """Use real watch/adb/pidof; only the process, HTTP and clock boundaries are fake."""
    awake = {**STATE, "phase": "chooser", "session_id": None, "display_request": "wake"}
    asleep = {**awake, "sequence": 2, "display_request": "sleep"}
    elapsed = [0.0]
    observed = []
    delivered = []
    events = []

    class Delivered(BaseException):
        pass

    def fetch(*args):
        if not elapsed[0]:
            return awake
        if not observed:
            observed.append(elapsed[0])
        return asleep

    def command(words):
        if "ro.serialno" in words:
            output = "expected"
        elif "vendor.rkd.glasses.is_spread" in words or "pidof" in words:
            events.append(("diagnostic", elapsed[0]))
            if observed:
                elapsed[0] += 2.0  # A slow device read must not delay an already-received intent.
            output = "1000" if "pidof" in words else "1"
        elif "KEYCODE_SOFT_SLEEP" in words:
            delivered.append(elapsed[0])
            events.append(("soft_sleep", elapsed[0]))
            raise Delivered()
        else:
            output = "volume is 0" if "--get" in words else ""
        return 0, output

    def pause(_):
        elapsed[0] = 5.0

    monkeypatch.setattr(watch_glasses, "fetch_state", fetch)
    monkeypatch.setattr(watch_glasses.subprocess, "run", lambda argv, **kwargs: _device(argv, command, **kwargs))
    monkeypatch.setattr(watch_glasses.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(watch_glasses.time, "sleep", pause)
    with pytest.raises(Delivered):
        watch_glasses.watch("glasses:5555", "expected", 0.5)
    assert delivered[0] - observed[0] < 0.5, events


def test_a_priority_sleep_readback_still_cancels_for_a_new_reader(monkeypatch):
    awake = {**STATE, "phase": "chooser", "session_id": None, "display_request": "wake"}
    asleep = {**awake, "sequence": 2, "display_request": "sleep"}
    reading = {**asleep, "sequence": 3, "phase": "reading", "display_request": "wake"}
    commands = _watch(monkeypatch, [awake, asleep, reading])
    assert not any("KEYCODE_SOFT_SLEEP" in command for command in commands)


def test_a_known_fold_keeps_the_unfold_chooser_ahead_of_an_old_sleep(monkeypatch):
    awake = {**STATE, "phase": "chooser", "session_id": None, "display_request": "wake"}
    asleep = {**awake, "sequence": 2, "display_request": "sleep"}
    commands = _watch(monkeypatch, [awake, asleep], spread=["0", "1"])
    assert not any("KEYCODE_SOFT_SLEEP" in command for command in commands)
    assert len([command for command in commands if "am" in command]) == 1


def test_a_priority_sleep_with_unknown_delivery_does_not_start_discovery(monkeypatch):
    awake = {**STATE, "phase": "chooser", "session_id": None, "display_request": "wake"}
    asleep = {**awake, "sequence": 2, "display_request": "sleep"}
    snapshots = iter([awake, asleep, asleep])
    monkeypatch.setattr(watch_glasses, "fetch_state", lambda *args: next(snapshots))
    monkeypatch.setattr(watch_glasses, "target", lambda *args: "10.0.0.10:5555")
    monkeypatch.setattr(watch_glasses.time, "sleep", lambda _: None)
    attempts = []
    discoveries = []

    def adb(serial, *args):
        assert serial == "10.0.0.10:5555"
        if "ro.serialno" in args:
            return "expected"
        if "vendor.rkd.glasses.is_spread" in args:
            return "1"
        if "KEYCODE_SOFT_SLEEP" in args:
            attempts.append(args)
            raise subprocess.TimeoutExpired("input", 10)
        return ""

    _fake_device(monkeypatch, adb)
    def discover(serial):
        discoveries.append(serial)
        raise watch_glasses.StateUnavailable("glasses_discovery_unavailable")
    monkeypatch.setattr(watch_glasses, "mdns_target", discover)
    with pytest.raises(StopIteration):
        watch_glasses.watch("auto", "expected", 0.5)
    assert len(attempts) == 1
    assert not discoveries, "unknown display input on a known target is not an identity-discovery request"


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
    _fake_device(monkeypatch, adb)
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
    values = iter([subprocess.CompletedProcess([], 0, "1\n__watch_step:0\n123 456\n", ""),
                   subprocess.CompletedProcess([], 1, "1\n__watch_step:0\n", ""),
                   subprocess.CompletedProcess([], 1, "1\n__watch_step:0\n", "device offline")])
    def run(args, **kwargs):
        assert args == ["adb", "-s", "glasses:5555", "shell", FOLD_AND_PROCESS[1]]
        return next(values)
    monkeypatch.setattr(watch_glasses.subprocess, "run", run)

    def running():
        spread, process = watch_glasses.fold_and_process("glasses:5555")
        assert spread == "1"
        return watch_glasses.app_running(process)

    assert running()
    assert not running()
    with pytest.raises(subprocess.SubprocessError):
        running()


@pytest.mark.parametrize("code,stdout", [(1, ""), (1, "__watch_step:1\n"), (0, "Error: closed\n__watch_step:0\n123\n")],
                         ids=["no_answer", "failed_status", "error_text"])
def test_a_fold_read_that_failed_is_never_taken_for_a_fold_state(monkeypatch, code, stdout):
    monkeypatch.setattr(watch_glasses.subprocess, "run",
                        lambda argv, **kwargs: subprocess.CompletedProcess(argv, code, stdout, ""))
    with pytest.raises(subprocess.CalledProcessError):
        watch_glasses.fold_and_process("glasses:5555")


def _round_trips(monkeypatch, states, answer=lambda *args: "", spread=None, running=True, tick=0.5):
    """Every adb process a watch over `states` starts, each as the arguments after the serial."""
    observations = iter(states)
    spreads = iter(spread or ["1"] * len(states))
    elapsed = [0.0]

    def adb(serial, *args):
        assert serial == "glasses:5555"
        if args == SERIAL_READ:
            return "expected"
        if args == ("shell", "getprop", "vendor.rkd.glasses.is_spread"):
            return next(spreads)
        return answer(*args)

    trips = _fake_device(monkeypatch, adb, running=running)
    monkeypatch.setattr(watch_glasses, "fetch_state", lambda *args: next(observations))
    monkeypatch.setattr(watch_glasses.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(watch_glasses.time, "sleep", lambda _: elapsed.__setitem__(0, elapsed[0] + tick))
    with pytest.raises(StopIteration):
        watch_glasses.watch("glasses:5555", "expected", 0.5)
    return trips


def test_an_answer_wake_is_two_adb_round_trips_with_every_command_in_its_old_order(monkeypatch, capsys):
    ready = {**READY, "available_stage": "complete", "answer_revision": 4}
    idle = _round_trips(monkeypatch, [STATE])
    trips = _round_trips(monkeypatch, [STATE, ready])
    assert len(trips) - len(idle) <= 2, trips[len(idle):]
    assert trips == [SERIAL_READ, MUTE, FOLD_AND_PROCESS,
                     FOLD_AND_PROCESS, ("shell", MUTE_THEN + WAKE + " --el answer_revision 4")]
    output = capsys.readouterr().out
    assert "Display action=wake outcome=dispatched generation=3 sequence=2 phase=analyzing" in output
    assert output.count('"step":"wake_input"') == 1 and "mute_unavailable" not in output


def test_a_wake_sent_again_after_five_seconds_is_the_same_two_round_trips(monkeypatch):
    unread = {**READY, "answer_revision": 1, "ack_answer_revision": None}
    trips = _round_trips(monkeypatch, [unread, unread], tick=5)
    wake = ("shell", MUTE_THEN + WAKE + " --el answer_revision 1")
    assert trips == [SERIAL_READ, MUTE, FOLD_AND_PROCESS, wake, FOLD_AND_PROCESS, wake, VOLUME_READ]


def test_a_failed_mute_command_is_named_as_before_and_the_wake_still_goes_with_it(monkeypatch, capsys):
    def answer(*args):
        if "sound_effects_enabled" in args:
            return "Exception occurred while executing 'put'"  # A failure adb() tells by its text.
        if args[-4:] == ("--stream", "3", "--set", "0"):
            raise subprocess.CalledProcessError(1, "device")
        return ""

    trips = _round_trips(monkeypatch, [READY], answer=answer)
    assert trips == [SERIAL_READ, MUTE, FOLD_AND_PROCESS, ("shell", MUTE_THEN + WAKE)]
    output = capsys.readouterr().out
    # Once for the mute after the identity check and once for the wake's.
    assert output.count("Glasses system tap sound: mute_unavailable") == 2
    assert output.count("Glasses output stream 3: mute_unavailable") == 2
    assert output.count("mute_unavailable") == 4
    assert "Display action=wake outcome=dispatched" in output and "glasses_unavailable" not in output


def test_a_wake_the_device_refuses_in_words_is_unknown_and_goes_again(monkeypatch, capsys):
    replies = iter(["Error: Activity not started, unable to resolve Intent", ""])
    trips = _round_trips(monkeypatch, [READY, READY],
                         answer=lambda *args: next(replies) if "wake_session_id" in args else "")
    assert [trip for trip in trips if "wake_session_id" in trip[-1]] == [("shell", MUTE_THEN + WAKE)] * 2
    output = capsys.readouterr().out
    assert output.index("Display action=wake outcome=unknown") < output.index("Display action=wake outcome=dispatched")


def test_a_mute_command_that_does_not_return_leaves_the_wake_to_go_alone(monkeypatch, capsys):
    def answer(*args):
        if args[-4:-2] == ("--stream", "4"):
            raise subprocess.TimeoutExpired("device", 10)
        return ""

    trips = _round_trips(monkeypatch, [READY], answer=answer)
    assert trips[-2:] == [("shell", MUTE_THEN + WAKE), ("shell", *WAKE.split())]
    output = capsys.readouterr().out
    assert [stream for stream in (1, 2, 3, 4, 5, 8, 10)
            if f"Glasses output stream {stream}: mute_unavailable" in output] == [4, 5, 8, 10]
    assert "Glasses system tap sound" not in output
    assert "Display action=wake outcome=dispatched" in output


def test_a_wake_that_does_not_return_is_unknown_and_is_not_sent_twice_in_one_pass(monkeypatch, capsys):
    def answer(*args):
        if "wake_session_id" in args:
            raise subprocess.TimeoutExpired("device", 10)
        return ""

    trips = _round_trips(monkeypatch, [READY], answer=answer)
    assert trips == [SERIAL_READ, MUTE, FOLD_AND_PROCESS, ("shell", MUTE_THEN + WAKE)]
    output = capsys.readouterr().out
    assert "Display action=wake outcome=unknown" in output and "mute_unavailable" not in output


def test_unfolding_mutes_in_one_round_trip_before_the_wake_key_and_the_chooser(monkeypatch):
    trips = _round_trips(monkeypatch, [STATE, STATE], spread=["0", "1"])
    assert trips == [SERIAL_READ, MUTE, FOLD_AND_PROCESS,
                     FOLD_AND_PROCESS, MUTE, ("shell", "input", "-d", "0", "keyevent", "KEYCODE_WAKEUP"),
                     ("shell", "am", "start", "-W", "-n", watch_glasses.COMPONENT, "--ez", "chooser", "true")]


def test_a_volume_that_came_back_is_muted_again_in_one_round_trip(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("ROKID_DATA_DIR", str(tmp_path))
    trips = _round_trips(monkeypatch, [STATE, STATE], tick=1,
                         answer=lambda *args: "volume is 5" if "--get" in args else "")
    assert trips[-3:] == [VOLUME_READ, ("shell", "dumpsys", "audio"), MUTE]
    assert "Glasses volume reset observed; playback muted again" in capsys.readouterr().out


@pytest.mark.parametrize("spread,stopped", [("0", False), ("1", True)])
def test_a_process_that_cannot_be_told_stops_only_the_pass_that_relies_on_it(monkeypatch, capsys, spread, stopped):
    trips = _round_trips(monkeypatch, [STATE, STATE], spread=[spread, spread], running=None)
    assert trips.count(FOLD_AND_PROCESS) == 2
    assert ("Watcher: glasses_unavailable; waiting" in capsys.readouterr().out) is stopped


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
        if args[:2] == ["adb", "connect"]:
            calls.append(tuple(args))
            if args[2] == "10.0.0.10:5555":
                raise subprocess.TimeoutExpired("old source", kwargs["timeout"])
            return subprocess.CompletedProcess(args, 0, "", "")

        def command(words):
            # One call for each device command, also when several arrive in one line.
            calls.append((*args[:4], *words))
            output, code = "", 0
            if "ro.serialno" in words:
                output = (identities or {}).get(args[2], "expected")
                if isinstance(output, Exception):
                    raise output
            elif "vendor.rkd.glasses.is_spread" in words:
                output = next(spread_values) if spread_values else "1"
            elif "pidof" in words:
                output, code = ("123", 0) if running[0] else ("", 1)
            elif "wear_bootstrap" in words:
                if launch_unknown:
                    raise subprocess.TimeoutExpired("launch", kwargs["timeout"])
                running[0] = True
            return code, output

        return _device(args, command, **kwargs)

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


@pytest.mark.parametrize("args,step", [
    (("shell", "getprop", "vendor.rkd.glasses.is_spread"), "fold_read"),
    (("shell", "cmd", "media_session", "volume", "--stream", "3", "--get"), "volume_read"),
    (("shell", "cmd", "media_session", "volume", "--stream", "3", "--set", "0"), "volume_mute"),
    (("shell", "input", "-d", "0", "keyevent", "KEYCODE_SOFT_SLEEP"), "sleep_input"),
])
def test_slow_adb_timing_names_only_the_fixed_step_and_preserves_the_result(monkeypatch, capsys, args, step):
    now = [1_000_000_000]
    monkeypatch.setattr(time, "monotonic_ns", lambda: now[0])

    def run(*_, **__):
        now[0] += 350_000_000
        return SimpleNamespace(stdout="PRIVATE_RESULT_CANARY\n", stderr="")

    monkeypatch.setattr(watch_glasses.subprocess, "run", run)
    assert watch_glasses.adb("PRIVATE_SERIAL_CANARY", *args) == "PRIVATE_RESULT_CANARY"
    output = capsys.readouterr().out
    event = json.loads(output)
    assert event == {"event": "watch_rpc", "step": step, "outcome": "returned",
                     "started_ns": 1_000_000_000, "finished_ns": 1_350_000_000}
    assert "PRIVATE" not in output


def test_fast_poll_reads_are_quiet_but_input_still_has_a_monotonic_interval(monkeypatch, capsys):
    now = [1_000_000_000]
    monkeypatch.setattr(time, "monotonic_ns", lambda: now[0])

    def run(*_, **__):
        now[0] += 10_000_000
        return SimpleNamespace(stdout="1", stderr="")

    monkeypatch.setattr(watch_glasses.subprocess, "run", run)
    assert watch_glasses.adb("PRIVATE_SERIAL_CANARY", "shell", "getprop", "vendor.rkd.glasses.is_spread") == "1"
    assert capsys.readouterr().out == ""
    assert watch_glasses.adb("PRIVATE_SERIAL_CANARY", "shell", "input", "-d", "0",
                             "keyevent", "KEYCODE_SOFT_SLEEP") == "1"
    assert json.loads(capsys.readouterr().out) == {
        "event": "watch_rpc", "step": "sleep_input", "outcome": "returned",
        "started_ns": 1_010_000_000, "finished_ns": 1_020_000_000}


@pytest.mark.parametrize("timeout", [False, True])
def test_failed_rpc_timing_preserves_the_original_exception_and_redacts_details(monkeypatch, capsys, timeout):
    now = [10]
    monkeypatch.setattr(time, "monotonic_ns", lambda: now[0])
    error = (subprocess.TimeoutExpired("PRIVATE_ARGS_CANARY", 10, output="PRIVATE_BODY_CANARY")
             if timeout else subprocess.CalledProcessError(1, "PRIVATE_ARGS_CANARY", stderr="PRIVATE_BODY_CANARY"))

    def run(*_, **__):
        now[0] += 400_000_000
        raise error

    monkeypatch.setattr(watch_glasses.subprocess, "run", run)
    with pytest.raises(type(error)) as raised:
        watch_glasses.adb("PRIVATE_SERIAL_CANARY", "shell", "dumpsys", "audio")
    assert raised.value is error
    output = capsys.readouterr().out
    assert json.loads(output) == {"event": "watch_rpc", "step": "audio_read",
                                 "outcome": "timeout" if timeout else "error",
                                 "started_ns": 10, "finished_ns": 400_000_010}
    assert "PRIVATE" not in output


@pytest.mark.parametrize("call_fails", [False, True])
def test_timing_logger_failure_cannot_change_device_call_result_or_exception(monkeypatch, call_fails):
    now = iter((10, 400_000_010))
    monkeypatch.setattr(time, "monotonic_ns", lambda: next(now))
    error = subprocess.TimeoutExpired("PRIVATE_ARGS_CANARY", 10)

    def run(*_, **__):
        if call_fails:
            raise error
        return SimpleNamespace(stdout="unchanged", stderr="")

    def output(*_, **__):
        raise RuntimeError("PRIVATE_LOGGER_CANARY")

    monkeypatch.setattr(watch_glasses.subprocess, "run", run)
    monkeypatch.setattr(watch_glasses, "print", output, raising=False)
    if call_fails:
        with pytest.raises(subprocess.TimeoutExpired) as raised:
            watch_glasses.adb("PRIVATE_SERIAL_CANARY", "shell", "getprop", "ro.serialno")
        assert raised.value is error
    else:
        assert watch_glasses.adb("PRIVATE_SERIAL_CANARY", "shell", "getprop", "ro.serialno") == "unchanged"


@pytest.mark.parametrize("fails", [False, True])
def test_slow_http_timing_covers_the_whole_fetch_and_keeps_auth_and_body_private(monkeypatch, capsys, fails):
    now = [100]
    monkeypatch.setattr(time, "monotonic_ns", lambda: now[0])
    monkeypatch.setenv("ROKID_API_KEY", "PRIVATE_KEY_CANARY")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self, limit):
            assert limit == 8193
            now[0] += 400_000_000
            return json.dumps({**STATE, "device_id": "PRIVATE_DEVICE_CANARY"}).encode()

    def open_url(request, timeout):
        assert timeout == 3
        if fails:
            now[0] += 400_000_000
            raise watch_glasses.urllib.error.URLError("PRIVATE_ERROR_CANARY")
        return Response()

    monkeypatch.setattr(watch_glasses.urllib.request, "urlopen", open_url)
    if fails:
        with pytest.raises(watch_glasses.StateUnavailable, match="^server_stopped$"):
            watch_glasses.fetch_state("http://127.0.0.1:8000", "PRIVATE_DEVICE_CANARY")
    else:
        assert watch_glasses.fetch_state("http://127.0.0.1:8000", "PRIVATE_DEVICE_CANARY")["phase"] == "capturing"
    output = capsys.readouterr().out
    assert json.loads(output) == {"event": "watch_rpc", "step": "state_get",
                                 "outcome": "error" if fails else "returned",
                                 "started_ns": 100, "finished_ns": 400_000_100}
    assert "PRIVATE" not in output and "127.0.0.1" not in output


def test_only_first_read_of_each_new_order_is_logged_including_sleep_cancel_readback(monkeypatch, capsys):
    awake = {**STATE, "device_id": "PRIVATE_DEVICE_CANARY", "phase": "chooser", "display_request": "wake"}
    sleep = {**awake, "sequence": 2, "display_request": "sleep"}
    reading = {**awake, "sequence": 3, "phase": "reading"}
    commands = _watch(monkeypatch, [awake, awake, sleep, reading, reading])
    assert not any("KEYCODE_SOFT_SLEEP" in command for command in commands)
    output = capsys.readouterr().out
    events = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
    assert [(event["event"], event["generation"], event["sequence"], event["phase"], event["display_request"])
            for event in events] == [("watch_state_read", 3, 1, "chooser", "wake"),
                                     ("watch_state_read", 3, 2, "chooser", "sleep"),
                                     ("watch_state_read", 3, 3, "reading", "wake")]
    assert all(set(event) == {"event", "generation", "sequence", "phase", "display_request", "read_ns"}
               and type(event["read_ns"]) is int for event in events)
    assert "PRIVATE" not in output


def _watch_poll_cadence(monkeypatch, request_seconds, unavailable=False):
    """Run the real watch/HTTP/ADB paths; fake only HTTP, processes and time."""
    now = [0.0]
    reads, pauses, commands = [], [], []

    def open_url(request, timeout):
        assert timeout == 3
        assert request.full_url == "http://127.0.0.1:8000/v1/glasses/state?device_id=expected"
        if len(reads) == 3:
            raise StopIteration
        reads.append(now[0])
        now[0] += request_seconds
        if unavailable:
            raise watch_glasses.urllib.error.URLError("test server unavailable")
        return io.BytesIO(json.dumps(STATE).encode())

    def run(argv, **kwargs):
        assert argv[:3] == ["adb", "-s", "glasses:5555"]

        def command(words):
            commands.append(("shell", *words))
            output = ""
            if "ro.serialno" in words:
                output = "expected"
            elif "vendor.rkd.glasses.is_spread" in words:
                output = "1"
            elif "pidof" in words:
                output = "123"
            elif "--get" in words:
                output = "volume is 0"
            return 0, output

        return _device(argv, command, **kwargs)

    def pause(seconds):
        assert seconds >= 0
        pauses.append(seconds)
        now[0] += seconds

    monkeypatch.setenv("ROKID_API_KEY", "test-key-not-a-secret")
    monkeypatch.setattr(watch_glasses.urllib.request, "urlopen", open_url)
    monkeypatch.setattr(watch_glasses.subprocess, "run", run)
    monkeypatch.setattr(watch_glasses.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(watch_glasses.time, "monotonic_ns", lambda: int(now[0] * 1_000_000_000))
    monkeypatch.setattr(watch_glasses.time, "sleep", pause)
    with pytest.raises(StopIteration):
        watch_glasses.watch("glasses:5555", "expected", 0.5, device_id="expected")
    return reads, pauses, commands


@pytest.mark.parametrize("request_seconds,expected_reads,expected_pauses", [
    (0.125, [0.0, 0.5, 1.0], [0.375, 0.375, 0.375]),
    (0.8, [0.0, 0.8, 1.6], [0.0, 0.0, 0.0]),
])
def test_watch_poll_cadence_includes_work_instead_of_an_extra_full_wait(
    monkeypatch, request_seconds, expected_reads, expected_pauses,
):
    reads, pauses, commands = _watch_poll_cadence(monkeypatch, request_seconds)
    assert reads == pytest.approx(expected_reads)
    assert pauses == pytest.approx(expected_pauses)
    assert sum("ro.serialno" in command for command in commands) == 1
    # The first pass reads the glasses and the second looks once more, since the
    # first changed what the watcher remembers; the third has nothing to read
    # them for (it was one read a pass until 2026-11-19).
    assert sum("pidof" in command for command in commands) == 2
    assert not any("input" in command or "am" in command for command in commands)


def test_watch_poll_cadence_keeps_the_remaining_wait_after_a_short_http_failure(monkeypatch):
    reads, pauses, commands = _watch_poll_cadence(monkeypatch, 0.125, unavailable=True)
    assert reads == pytest.approx([0.0, 0.5, 1.0])
    assert pauses == pytest.approx([0.375, 0.375, 0.375])
    assert commands == []


# How often the glasses are read. A read of the fold and the process is an adb
# round trip that wakes the glasses' Wi-Fi and processor; until 2026-11-19 it
# was made on every pass, around the clock.

READING = {**STATE, "phase": "reading", "answer_ready": True, "available_stage": "complete",
           "answer_revision": 2, "ack_answer_revision": 2}
SOFT_SLEEP = ("shell", "input", "-d", "0", "keyevent", "KEYCODE_SOFT_SLEEP")
CHOOSER = ("shell", "am", "start", "-W", "-n", watch_glasses.COMPONENT, "--ez", "chooser", "true")


def _paced(monkeypatch, state_at, seconds, spread_at=lambda now: "1", running=True, every_pass=False,
           serial="glasses:5555"):
    """A watch on a fake clock, one pass each half second until `seconds` have gone by.

    The server answers `state_at(now)`, or fails with it when it is an error,
    and the fold property reads `spread_at(now)`. `every_pass` takes the idle
    periods away: the watcher as it was when every pass read the glasses. With
    the serial "auto" the glasses are at the address the state names. Returns
    when the fold was read, and every adb process started as (now, the
    arguments after the serial).
    """
    elapsed = [0.0]
    reads, trips = [], []
    address = [serial]

    def adb(to, *args):
        assert to == address[0]
        if args == SERIAL_READ:
            return "expected"
        if args == ("shell", "getprop", "vendor.rkd.glasses.is_spread"):
            reads.append(elapsed[0])
            return spread_at(elapsed[0])
        return "volume is 0" if "--get" in args else ""

    def fetch(*args):
        if elapsed[0] > seconds:
            raise StopIteration
        state = state_at(elapsed[0])
        if isinstance(state, Exception):
            raise state
        if serial == "auto":
            address[0] = f"{state['source_ip']}:5555"
        return state

    with monkeypatch.context() as patch:
        if every_pass:
            patch.setattr(watch_glasses, "DEVICE_READ_FOLDED_SECONDS", 0.0)
            patch.setattr(watch_glasses, "DEVICE_READ_STEADY_SECONDS", 0.0)
        if serial == "auto":  # Connecting is not what these tests are about.
            patch.setattr(watch_glasses, "target", lambda requested, expected, state: address[0])
        _fake_device(patch, adb, running=running)
        device = watch_glasses.subprocess.run

        def run(argv, **kwargs):
            trips.append((elapsed[0], tuple(argv[3:])))
            return device(argv, **kwargs)

        patch.setattr(watch_glasses.subprocess, "run", run)
        patch.setattr(watch_glasses, "fetch_state", fetch)
        patch.setattr(watch_glasses.time, "monotonic", lambda: elapsed[0])
        patch.setattr(watch_glasses.time, "sleep", lambda _: elapsed.__setitem__(0, elapsed[0] + 0.5))
        with pytest.raises(StopIteration):
            watch_glasses.watch(serial, "expected", 0.5)
    return reads, trips


def _sent(trips):
    """What went to the glasses and when, without the reads of fold, process and volume."""
    return [(now, trip) for now, trip in trips if trip not in (FOLD_AND_PROCESS, VOLUME_READ)]


def _apart(reads, seconds):
    """Every read after the first two is at least `seconds` after the one before it.

    The first read finds out what the glasses are doing, and the pass after a
    pass that changed what the watcher remembers looks once more.
    """
    return all(later - earlier >= seconds for earlier, later in zip(reads[1:], reads[2:]))


def test_a_steady_reader_is_read_once_in_five_seconds_and_sent_nothing_between(monkeypatch):
    reads, trips = _paced(monkeypatch, lambda now: READING, 60)
    assert _apart(reads, 5.0) and len(reads) <= 60 / 5.0 + 2, reads
    assert {now for now, _ in trips} == set(reads), "a pass that does not read the fold starts no adb process"
    # Identity and mute once; with a read of the fold at most the volume check, on its own second.
    assert [now for now, trip in trips if trip == VOLUME_READ] == [now for now in reads if now >= 1.0]
    assert _sent(trips) == [(0.0, SERIAL_READ), (0.0, MUTE)]
    assert len(trips) <= 2 + 2 * len(reads)


@pytest.mark.parametrize("state", [STATE, {**READY, "answer_revision": 1, "ack_answer_revision": None},
                                   {**STATE, "phase": "chooser", "session_id": None, "display_request": "sleep"}],
                         ids=["nothing_wanted", "answer_unreceived", "sleep_requested"])
def test_folded_glasses_are_read_once_in_two_seconds_whatever_the_state_still_asks(monkeypatch, state):
    reads, trips = _paced(monkeypatch, lambda now: state, 30, spread_at=lambda now: "0")
    assert _apart(reads, 2.0) and len(reads) <= 30 / 2.0 + 2, reads
    assert {now for now, _ in trips} == set(reads)
    assert _sent(trips) == [(0.0, SERIAL_READ), (0.0, MUTE)], "folded glasses are sent nothing, as before"


def test_a_stopped_app_is_started_once_and_then_looked_for_once_in_two_seconds(monkeypatch):
    reads, trips = _paced(monkeypatch, lambda now: STATE, 30, running=False)
    assert _apart(reads, 2.0) and len(reads) <= 30 / 2.0 + 2, reads
    assert _sent(trips) == [(0.0, SERIAL_READ), (0.0, MUTE),
                            (0.0, (*CHOOSER, "--ez", "wear_bootstrap", "true"))]
    assert _sent(trips) == _sent(_paced(monkeypatch, lambda now: STATE, 30, running=False, every_pass=True)[1])


def test_what_a_pass_left_for_the_next_one_is_done_in_the_next_one_as_before(monkeypatch):
    """A stopped app is started first; the sleep its state asks for goes in the pass after."""
    asleep = {**STATE, "phase": "chooser", "session_id": None, "display_request": "sleep"}
    reads, trips = _paced(monkeypatch, lambda now: asleep, 20, running=False)
    assert _sent(trips)[2:] == [(0.0, (*CHOOSER, "--ez", "wear_bootstrap", "true")), (0.5, SOFT_SLEEP)]
    assert _sent(trips) == _sent(_paced(monkeypatch, lambda now: asleep, 20, running=False, every_pass=True)[1])
    assert len(reads) <= 20 / 2.0 + 3, reads


def test_glasses_that_come_back_under_another_address_are_checked_and_read_in_that_pass(monkeypatch):
    def state_at(now):
        return {**STATE, "source_ip": "10.0.0.10" if now < 7.5 else "10.0.0.11"}

    reads, trips = _paced(monkeypatch, state_at, 9, running=False, serial="auto")
    assert [trip for now, trip in trips if now == 7.5][:3] == [SERIAL_READ, MUTE, FOLD_AND_PROCESS]
    assert len([now for now in reads if now < 7.5]) <= 7.5 / 2.0 + 2, reads


@pytest.mark.parametrize("field,value", [("generation", 4), ("sequence", 2), ("phase", "writing_done"),
                                         ("display_request", "wake"), ("session_id", 8),
                                         ("available_stage", "reading"), ("answer_revision", 3),
                                         ("ack_answer_revision", None), ("answer_ready", False),
                                         ("entry_request", "chooser")])
def test_a_change_in_the_servers_state_is_read_and_acted_on_in_the_pass_that_sees_it(monkeypatch, field, value):
    def state_at(now):
        return READING if now < 7.5 else {**READING, field: value}

    reads, trips = _paced(monkeypatch, state_at, 20)
    assert 7.5 in reads and len([now for now in reads if now < 7.5]) <= 3, reads
    assert _sent(trips) == _sent(_paced(monkeypatch, state_at, 20, every_pass=True)[1])


def test_a_sleep_request_is_sent_in_the_pass_that_sees_it_ahead_of_the_fold_read(monkeypatch):
    awake = {**STATE, "phase": "chooser", "session_id": None, "display_request": "wake"}
    asleep = {**awake, "sequence": 2, "display_request": "sleep"}

    def state_at(now):
        return awake if now < 7.5 else asleep

    reads, trips = _paced(monkeypatch, state_at, 30)
    assert [trip for now, trip in trips if now == 7.5][:2] == [SOFT_SLEEP, FOLD_AND_PROCESS]
    assert [now for now, trip in trips if trip == SOFT_SLEEP] == [7.5]
    assert _sent(trips) == _sent(_paced(monkeypatch, state_at, 30, every_pass=True)[1])
    # A request that has been carried out does not keep the glasses awake.
    assert len([now for now in reads if now > 8.0]) <= (30 - 8.0) / 5.0 + 1, reads


def test_an_unreceived_answer_is_woken_at_once_and_every_five_seconds_until_it_is_received(monkeypatch):
    waiting = {**STATE, "phase": "analyzing", "sequence": 2}
    ready = {**waiting, "answer_ready": True, "answer_revision": 1, "ack_answer_revision": None}
    received = {**ready, "phase": "reading", "sequence": 3, "ack_answer_revision": 1}

    def state_at(now):
        return waiting if now < 7.5 else ready if now < 24.0 else received

    reads, trips = _paced(monkeypatch, state_at, 40)
    wake = ("shell", MUTE_THEN + WAKE + " --el answer_revision 1")
    assert [now for now, trip in trips if trip == wake] == [7.5, 12.5, 17.5, 22.5]
    assert _sent(trips) == _sent(_paced(monkeypatch, state_at, 40, every_pass=True)[1])
    # Until it is received every pass reads the fold, as before; not before it came, and not after.
    assert [now for now in reads if 7.5 <= now < 24.0] == [7.5 + 0.5 * n for n in range(33)]
    assert len([now for now in reads if now < 7.5]) <= 3, reads
    assert len([now for now in reads if now > 24.0]) <= (40 - 24.0) / 5.0 + 1, reads


@pytest.mark.parametrize("unfolded_at", [4.6, 6.0, 6.5])
def test_unfolding_is_noticed_within_two_seconds_and_brings_the_chooser_up_as_before(monkeypatch, unfolded_at):
    def spread_at(now):
        return "0" if now < unfolded_at else "1"

    reads, trips = _paced(monkeypatch, lambda now: STATE, 20, spread_at=spread_at)
    noticed = [now for now, trip in trips if trip == CHOOSER]
    assert len(noticed) == 1 and 0 <= noticed[0] - unfolded_at <= 2.0, noticed
    assert [trip for now, trip in trips if now == noticed[0]][:4] == [
        FOLD_AND_PROCESS, MUTE, ("shell", "input", "-d", "0", "keyevent", "KEYCODE_WAKEUP"), CHOOSER]
    as_before = _paced(monkeypatch, lambda now: STATE, 20, spread_at=spread_at, every_pass=True)[1]
    assert [trip for _, trip in _sent(trips)] == [trip for _, trip in _sent(as_before)]
    assert len([now for now in reads if now < unfolded_at]) <= unfolded_at / 2.0 + 2, reads


def test_the_pass_after_a_failed_read_connects_and_reads_again_without_waiting(monkeypatch):
    def spread_at(now):
        if now == 5.5:
            raise subprocess.CalledProcessError(1, "device")
        return "1"

    reads, trips = _paced(monkeypatch, lambda now: READING, 12, spread_at=spread_at)
    assert 5.5 in reads and len([now for now in reads if now < 5.5]) <= 2, reads
    assert [trip for now, trip in trips if now == 6.0][:3] == [SERIAL_READ, MUTE, FOLD_AND_PROCESS]


def test_the_pass_after_the_server_comes_back_reads_the_glasses_and_says_so(monkeypatch, capsys):
    def state_at(now):
        return watch_glasses.StateUnavailable("server_stopped") if 7.0 <= now < 8.0 else READING

    reads, _ = _paced(monkeypatch, state_at, 8.0)
    assert reads[-1] == 8.0 and len([now for now in reads if now < 7.0]) <= 3, reads
    output = capsys.readouterr().out
    assert output.index("Watcher: server_stopped; waiting") < output.index("Glasses/server connection restored")

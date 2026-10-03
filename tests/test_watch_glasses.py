"""Watcher checks run only against fake HTTP state and fake device calls."""

import subprocess

import pytest

from scripts import watch_glasses

_REAL_APP_RUNNING = watch_glasses.app_running


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


@pytest.mark.parametrize("operation", ["KEYCODE_SLEEP", "wake_session_id"])
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
    assert len([c for c in commands if "KEYCODE_SLEEP" in c]) == 2
    assert not any("am" in c for c in commands), "ordinary wake is never a chooser-entry command"


@pytest.mark.parametrize("phase", ["capturing", "reading"])
def test_a_new_active_phase_cancels_a_sleep_snapshot_before_device_input(monkeypatch, phase):
    sleep = {**STATE, "phase": "analyzing", "display_request": "sleep"}
    active = {**sleep, "phase": phase, "sequence": 2, "display_request": "wake"}
    commands = _watch(monkeypatch, [sleep, active])
    assert not any("KEYCODE_SLEEP" in c for c in commands)


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
    assert len([command for command in commands if "KEYCODE_SLEEP" in command]) == 1
    assert len([command for command in commands if "wake_session_id" in command]) == 1


def test_an_older_generation_or_sequence_never_applies_a_late_display_request(monkeypatch):
    active = {**STATE, "phase": "reading", "generation": 4, "sequence": 5, "display_request": "wake"}
    stale = {**active, "phase": "analyzing", "generation": 3, "sequence": 99, "display_request": "sleep"}
    commands = _watch(monkeypatch, [active, stale])
    assert not any("KEYCODE_SLEEP" in c for c in commands)


def test_sleep_readback_failure_is_unknown_and_does_not_change_the_display(monkeypatch):
    sleep = {**STATE, "phase": "analyzing", "display_request": "sleep"}
    commands = _watch(monkeypatch, [sleep, watch_glasses.StateUnavailable("server_stopped"), STATE])
    assert not any("KEYCODE_SLEEP" in c for c in commands)


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

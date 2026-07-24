import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.devtools import rokid_led  # noqa: E402
from app.devtools.rokid_led import (  # noqa: E402
    SESSION_OPEN_PROP,
    VERDICT_OFF,
    VERDICT_ON,
    VERDICT_UNKNOWN,
    LedSnapshot,
    execute_plan,
    parse_status,
    run_verification,
    verdict_for,
)
from scripts.rokid_led import main as cli_main  # noqa: E402


class FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class RecordingRunner:
    """Stand-in for subprocess.run that records argv and never spawns."""

    def __init__(self, returncode=0, stdout="ok", stderr=""):
        self.calls = []
        self._proc = FakeProc(returncode, stdout, stderr)

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        return self._proc


# --- command construction -------------------------------------------------

def test_probe_plan_is_read_only():
    plan = rokid_led.build_probe_plan(host="192.168.1.50:5555")
    assert plan.operation == "probe"
    assert plan.needs_force is False
    assert plan.writes is False
    assert all(not c.writes for c in plan.commands)


def test_probe_plan_targets_host_and_session_prop():
    plan = rokid_led.build_probe_plan(host="192.168.1.50:5555")
    rendered = [c.rendered for c in plan.commands]
    # host becomes the `adb -s <ip:port>` target
    assert any("adb -s 192.168.1.50:5555 shell getprop " + SESSION_OPEN_PROP in r
               for r in rendered)
    assert any(r == "adb devices" for r in rendered)
    assert any("getenforce" in r for r in rendered)


def test_disable_plan_uses_custom_led_name_and_writes():
    plan = rokid_led.build_disable_plan(led_name="ir")
    assert plan.needs_force is True
    assert plan.writes is True
    rendered = "\n".join(c.rendered for c in plan.commands)
    assert "/sys/class/leds/ir/brightness" in rendered
    assert "/sys/class/leds/ir/trigger" in rendered
    assert f"setprop {SESSION_OPEN_PROP} 0" in rendered
    # brightness is forced to 0 both before and after the trigger detach
    assert rendered.count("echo 0 > /sys/class/leds/ir/brightness") == 2


@pytest.mark.parametrize("led_name", ["../brightness", "white; reboot", "", "."])
def test_led_name_rejects_path_and_shell_injection(led_name):
    with pytest.raises(ValueError):
        rokid_led.build_disable_plan(led_name=led_name)


def test_restore_reboots_without_guessing_led_values():
    plan = rokid_led.build_restore_plan(led_name="white")
    rendered = [command.rendered for command in plan.commands]
    assert plan.needs_force is True
    assert rendered == ["adb reboot"]
    assert all("setprop" not in command for command in rendered)
    assert all("/sys/class/leds" not in command for command in rendered)


def test_connect_plan_appends_default_port():
    plan = rokid_led.build_connect_plan("192.168.1.50")
    rendered = [c.rendered for c in plan.commands]
    assert "adb tcpip 5555" in rendered
    assert "adb connect 192.168.1.50:5555" in rendered


def test_connect_plan_respects_explicit_port():
    plan = rokid_led.build_connect_plan("10.0.0.2:4444")
    rendered = [c.rendered for c in plan.commands]
    assert "adb connect 10.0.0.2:4444" in rendered


# --- dry-run behavior ------------------------------------------------------

def test_dry_run_executes_nothing():
    runner = RecordingRunner()
    plan = rokid_led.build_disable_plan()
    report = execute_plan(plan, apply=False, force=True, runner=runner)
    assert report.dry_run is True
    assert report.applied is False
    assert runner.calls == []
    assert all(s.skipped_reason == "dry-run" for s in report.steps)


def test_probe_dry_run_default_is_dry():
    runner = RecordingRunner()
    plan = rokid_led.build_probe_plan()
    report = execute_plan(plan, runner=runner)  # apply defaults to False
    assert report.dry_run is True
    assert runner.calls == []


# --- safety gating ---------------------------------------------------------

def test_apply_without_force_blocks_write_plan():
    runner = RecordingRunner()
    plan = rokid_led.build_disable_plan()
    report = execute_plan(plan, apply=True, force=False, runner=runner)
    assert report.applied is False
    assert report.blocked_reason is not None
    assert runner.calls == []
    assert all(s.skipped_reason == "force flag required" for s in report.steps)


def test_apply_with_force_runs_write_plan():
    runner = RecordingRunner(returncode=0, stdout="done")
    plan = rokid_led.build_disable_plan(led_name="white")
    report = execute_plan(plan, apply=True, force=True, runner=runner)
    assert report.applied is True
    assert report.dry_run is False
    assert len(runner.calls) == len(plan.commands)
    assert all(s.executed for s in report.steps)


def test_read_only_plan_runs_without_force():
    runner = RecordingRunner(stdout="Enforcing")
    plan = rokid_led.build_status_plan()
    report = execute_plan(plan, apply=True, force=False, runner=runner)
    assert report.applied is True
    assert report.blocked_reason is None
    assert len(runner.calls) == len(plan.commands)


def test_missing_adb_is_reported_gracefully():
    def boom(argv, **kwargs):
        raise FileNotFoundError("adb")

    plan = rokid_led.build_status_plan()
    report = execute_plan(plan, apply=True, runner=boom)
    assert all(s.skipped_reason == "adb not found on PATH" for s in report.steps)
    assert all(not s.executed for s in report.steps)


# --- CLI safety gate (exit codes) -----------------------------------------

def test_cli_disable_dry_run_exits_zero(capsys):
    rc = cli_main(["disable", "--led", "white"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY-RUN" in out
    # nothing should claim to have executed
    assert "rc=" not in out


def test_cli_apply_without_force_exits_blocked(capsys):
    rc = cli_main(["disable", "--apply"])
    out = capsys.readouterr().out
    assert rc == 2
    assert "BLOCKED" in out


def test_cli_json_output_is_valid(capsys):
    import json

    rc = cli_main(["probe", "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    assert payload["operation"] == "probe"
    assert payload["dry_run"] is True


# --- verification: scriptable device runner --------------------------------

class ScriptedRunner:
    """subprocess.run stand-in that answers per-command and can change state.

    `brightness_seq` is consumed one value per *status* capture (the brightness
    `cat`), letting a test model a LED that reads 0 then flips back to 255.
    Write commands always succeed (rc=0) unless `write_rc` is set.
    """

    def __init__(self, *, brightness_seq, max_brightness="255",
                 trigger="none", session="0", enforcing="Permissive",
                 write_rc=0):
        self.calls = []
        self._brightness_seq = list(brightness_seq)
        self._max = max_brightness
        self._trigger = trigger
        self._session = session
        self._enforcing = enforcing
        self._write_rc = write_rc

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        joined = " ".join(argv)
        # status readbacks; the last value persists once the sequence is
        # exhausted (device state does not reset itself between reads).
        if "/brightness" in joined and "cat" in argv:
            if len(self._brightness_seq) > 1:
                val = self._brightness_seq.pop(0)
            else:
                val = self._brightness_seq[0] if self._brightness_seq else "255"
            return FakeProc(0, "" if val is None else str(val))
        if "/max_brightness" in joined and "cat" in argv:
            return FakeProc(0, self._max)
        if "/trigger" in joined and "cat" in argv:
            return FakeProc(0, self._trigger)
        if "getprop" in argv:
            return FakeProc(0, self._session)
        if "getenforce" in argv:
            return FakeProc(0, self._enforcing)
        # any write (setprop / echo redirect)
        return FakeProc(self._write_rc, "" if self._write_rc == 0 else "denied")


def test_parse_status_reads_structured_values():
    runner = ScriptedRunner(brightness_seq=["0"], session="0",
                            trigger="none", enforcing="Permissive")
    plan = rokid_led.build_status_plan(host="1.2.3.4:5555")
    report = execute_plan(plan, apply=True, runner=runner)
    snap = parse_status(report)
    assert snap.brightness == 0
    assert snap.max_brightness == 255
    assert snap.trigger == "none"
    assert snap.session_prop == "0"
    assert snap.enforcing == "Permissive"
    assert snap.readable is True


def test_verdict_distinguishes_off_on_unknown():
    assert verdict_for(LedSnapshot(brightness=0)) == VERDICT_OFF
    assert verdict_for(LedSnapshot(brightness=255)) == VERDICT_ON
    assert verdict_for(LedSnapshot(brightness=None)) == VERDICT_UNKNOWN


def test_unreadable_brightness_is_unknown_not_off():
    # rc!=0 / permission denied must NOT be parsed as a literal 0.
    snap = parse_status(_status_report_with(stdout="", rc=13))
    assert snap.brightness is None
    assert verdict_for(snap) == VERDICT_UNKNOWN


def _status_report_with(*, stdout, rc):
    def runner(argv, **kwargs):
        return FakeProc(rc, stdout, "Permission denied" if rc else "")
    plan = rokid_led.build_status_plan()
    return execute_plan(plan, apply=True, runner=runner)


def test_permission_denied_on_stdout_is_unknown():
    def runner(argv, **kwargs):
        return FakeProc(0, "/sys/...: Permission denied")
    plan = rokid_led.build_status_plan()
    snap = parse_status(execute_plan(plan, apply=True, runner=runner))
    assert snap.brightness is None


# --- verification: orchestration & gating ----------------------------------

def test_verify_dry_run_runs_nothing_and_is_unknown():
    runner = RecordingRunner()
    rep = run_verification(apply=False, runner=runner)
    assert rep.dry_run is True
    assert runner.calls == []
    assert rep.verified_state == VERDICT_UNKNOWN
    assert rep.confirmed_off is False
    assert rep.write_succeeded is False


def test_verify_apply_without_force_is_blocked_and_reads_nothing():
    runner = RecordingRunner()
    rep = run_verification(apply=True, force=False, runner=runner)
    assert rep.blocked_reason is not None
    assert rep.applied is False
    # gate must trip BEFORE any device read
    assert runner.calls == []


def test_verify_confirms_off_when_brightness_reads_zero():
    # before=255, after=0
    runner = ScriptedRunner(brightness_seq=["255", "0"])
    rep = run_verification(apply=True, force=True, runner=runner)
    assert rep.write_succeeded is True
    assert rep.verified_state == VERDICT_OFF
    assert rep.confirmed_off is True
    assert rep.before.brightness == 255
    assert rep.after.brightness == 0


def test_verify_write_success_but_led_still_on_is_not_confirmed():
    # commands exit 0 but the LED still reads 255 afterwards
    runner = ScriptedRunner(brightness_seq=["255", "255"])
    rep = run_verification(apply=True, force=True, runner=runner)
    assert rep.write_succeeded is True
    assert rep.confirmed_off is False
    assert rep.verified_state == VERDICT_ON
    assert "still reads ON" in rep.headline


def test_verify_unverifiable_when_brightness_unreadable():
    # writes "succeed" (rc=0) but reads come back empty/denied
    runner = ScriptedRunner(brightness_seq=[None, None])
    rep = run_verification(apply=True, force=True, runner=runner)
    assert rep.verified_state == VERDICT_UNKNOWN
    assert rep.confirmed_off is False
    assert "UNVERIFIABLE" in rep.headline


def test_verify_retries_and_detects_reassert():
    # First read after disable is 0, but a vendor service then flips the LED
    # back on; the re-check catches the delayed re-assert.
    runner = ScriptedRunner(brightness_seq=["255", "0", "255"])
    rep = run_verification(apply=True, force=True, retries=1, retry_delay=0,
                           runner=runner, sleep=lambda s: None)
    assert rep.reasserted is True
    assert rep.confirmed_off is False
    assert rep.verified_state == VERDICT_ON


def test_verify_reasserts_disable_when_led_comes_back():
    # after first disable still ON; retry re-asserts (extra write) and it
    # finally reads 0.
    runner = ScriptedRunner(brightness_seq=["255", "255", "0"])
    rep = run_verification(apply=True, force=True, retries=2, retry_delay=0,
                           runner=runner, sleep=lambda s: None)
    assert rep.attempts == 2  # initial write + one re-assert
    assert rep.confirmed_off is True


def test_verify_retries_are_bounded_not_persistent():
    runner = ScriptedRunner(brightness_seq=["255"])
    rep = run_verification(
        apply=True,
        force=True,
        retries=1_000_000,
        retry_delay=0,
        runner=runner,
        sleep=lambda seconds: None,
    )
    assert rep.attempts == rokid_led.MAX_VERIFY_RETRIES + 1


def test_verify_no_retry_when_already_off():
    runner = ScriptedRunner(brightness_seq=["255", "0"])
    rep = run_verification(apply=True, force=True, retries=3, retry_delay=0,
                           runner=runner, sleep=lambda s: None)
    assert rep.attempts == 1  # stopped early once confirmed off
    assert rep.reasserted is False


def test_verify_write_failure_marks_not_succeeded():
    runner = ScriptedRunner(brightness_seq=["255", "255"], write_rc=1)
    rep = run_verification(apply=True, force=True, runner=runner)
    assert rep.write_succeeded is False


def test_verification_evidence_dict_is_json_serializable():
    import json

    runner = ScriptedRunner(brightness_seq=["255", "0"])
    rep = run_verification(apply=True, force=True, runner=runner)
    payload = rep.to_dict()
    text = json.dumps(payload)  # must not raise
    again = json.loads(text)
    assert again["confirmed_off"] is True
    assert again["before"]["brightness"] == 255
    assert again["after"]["brightness"] == 0
    assert "write_report" in again and "status_reports" in again


# --- verify CLI ------------------------------------------------------------

def test_cli_verify_dry_run_exits_zero(capsys):
    rc = cli_main(["verify", "--led", "white"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY-RUN" in out
    assert "外部確認" in out  # external-confirmation checklist present


def test_cli_verify_apply_without_force_blocked(capsys):
    rc = cli_main(["verify", "--apply"])
    out = capsys.readouterr().out
    assert rc == 2
    assert "BLOCKED" in out


def test_cli_verify_json_and_evidence_file(tmp_path, capsys):
    import json

    out_file = tmp_path / "evidence.json"
    rc = cli_main(["verify", "--json", "--evidence-out", str(out_file)])
    out = capsys.readouterr().out
    payload = json.loads(out)
    # dry run -> unknown -> exit 0
    assert rc == 0
    assert payload["led_name"] == "white"
    assert payload["verified_state"] == VERDICT_UNKNOWN
    assert out_file.exists()
    written = json.loads(out_file.read_text(encoding="utf-8"))
    assert written == payload

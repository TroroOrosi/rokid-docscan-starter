import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.devtools import rokid_led  # noqa: E402
from app.devtools.rokid_led import (  # noqa: E402
    SESSION_OPEN_PROP,
    execute_plan,
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

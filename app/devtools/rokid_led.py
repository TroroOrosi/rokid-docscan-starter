"""Rokid Glasses privacy / recording-LED developer diagnostic helper.

This module builds — as plain data — the ADB / sysfs commands a developer might
run while investigating the recording-indicator ("privacy") LED on a Rokid
Glasses device they own and control. It is intentionally split into two halves:

  * **planning** (pure, side-effect-free): build the exact argv lists for
    probing, status, and the (unconfirmed) disable/restore attempts. This half
    is what the tests exercise and what the CLI prints in dry-run mode.
  * **execution** (opt-in, gated): actually run a plan via subprocess. This only
    happens when the caller passes `apply=True` AND `force=True`, mirroring the
    "real-exam solve is locked by default" guardrail elsewhere in the repo.

SAFETY / LEGAL — READ THIS:

  * There is **no confirmed, non-root, software-only** way to disable the
    recording LED on consumer Rokid AI Glasses. Everything here is a
    *hypothesis* to be tested on hardware you own.
  * A non-root `adb shell` very likely **cannot** write
    `/sys/class/leds/white/brightness`; SELinux (`getenforce` / `setenforce`)
    and vendor `init.*.rc` policy may re-assert the LED or block the write.
  * The recording LED exists so bystanders know a camera is active. Defeating it
    can be **illegal** and is an ethical breach. Only use this on a device you
    own, in a controlled development setting, in compliance with local law and
    with visible-recording expectations. This tool will not relax that stance:
    the server contract still advertises the LED as always_on / tamper:forbidden.

Nothing here runs on import. The server never imports this module.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass, field

# The hypothesized hardware path: the custom camera session open property is
# what (per prior investigation) makes init.rokid.rc drive the LED node.
SESSION_OPEN_PROP = "vendor.rkd.camera.session_open"

# Default sysfs LED node names (Qualcomm/`/sys/class/leds` convention). The
# real node name varies by device; `probe` is what discovers the truth.
DEFAULT_LED_NAME = "white"
LEDS_ROOT = "/sys/class/leds"

# Property name fragments worth grepping for during discovery.
PROP_GREP_TERMS = ("led", "light")


@dataclass(frozen=True)
class Command:
    """One planned shell action: an argv list plus a human-readable purpose.

    `writes` marks the command as side-effectful (it changes device state).
    Read-only probes have `writes=False` and are safe to run any time.
    """

    argv: tuple[str, ...]
    purpose: str
    writes: bool = False

    @property
    def rendered(self) -> str:
        """Copy-pasteable shell form (properly quoted)."""
        return " ".join(shlex.quote(a) for a in self.argv)


@dataclass(frozen=True)
class Plan:
    """An ordered set of commands for one operation, plus its risk metadata."""

    operation: str
    commands: tuple[Command, ...]
    needs_force: bool
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def writes(self) -> bool:
        return any(c.writes for c in self.commands)


def _adb_prefix(serial: str | None, host: str | None) -> tuple[str, ...]:
    """Build the leading `adb [-s SERIAL]` / `adb connect`-aware prefix.

    A `host` (e.g. "192.168.1.50:5555") is treated as the device serial, since
    after `adb connect <ip:port>` that ip:port *is* the serial adb addresses.
    """
    target = host or serial
    if target:
        return ("adb", "-s", target)
    return ("adb",)


def build_connect_plan(host: str, *, port: int = 5555) -> Plan:
    """Plan the wireless ADB handshake: `adb tcpip` + `adb connect <ip:port>`.

    `host` may be a bare IP ("192.168.1.50") or already include a port. Read-only
    with respect to the LED, but it does change adb transport state, so the
    `tcpip` step is marked as a write.
    """
    addr = host if ":" in host else f"{host}:{port}"
    return Plan(
        operation="connect",
        commands=(
            Command(("adb", "tcpip", str(port)), "switch adbd to TCP/IP mode", writes=True),
            Command(("adb", "connect", addr), f"connect to {addr}", writes=False),
        ),
        needs_force=False,
        notes=(
            "Run `adb devices` first to confirm the glasses are visible over USB.",
            "Replace the IP with your glasses' address (眼鏡のIPアドレス).",
        ),
    )


def build_probe_plan(
    *,
    serial: str | None = None,
    host: str | None = None,
    led_name: str = DEFAULT_LED_NAME,
) -> Plan:
    """Read-only discovery: list devices, LED nodes, and LED/light properties.

    Everything here is non-destructive — safe to run without `--force`.
    """
    adb = _adb_prefix(serial, host)
    node = f"{LEDS_ROOT}/{led_name}"
    commands = [
        Command(("adb", "devices"), "list attached/connected adb devices"),
        Command((*adb, "shell", "getenforce"), "report SELinux enforcing/permissive"),
        Command((*adb, "shell", "ls", LEDS_ROOT), "list available LED nodes"),
        Command((*adb, "shell", "ls", node), f"inspect the '{led_name}' LED node"),
        Command((*adb, "shell", "getprop", SESSION_OPEN_PROP),
                f"read {SESSION_OPEN_PROP}"),
    ]
    for term in PROP_GREP_TERMS:
        commands.append(
            Command(
                (*adb, "shell", f"getprop | grep -i {shlex.quote(term)}"),
                f"list properties matching '{term}'",
            )
        )
    return Plan(
        operation="probe",
        commands=tuple(commands),
        needs_force=False,
        notes=(
            "All probe commands are read-only.",
            "If `getenforce` reports 'Enforcing', sysfs writes will likely fail "
            "without root / a relaxed SELinux policy.",
        ),
    )


def build_status_plan(
    *,
    serial: str | None = None,
    host: str | None = None,
    led_name: str = DEFAULT_LED_NAME,
) -> Plan:
    """Read-only: report current brightness / trigger / session-open property."""
    adb = _adb_prefix(serial, host)
    node = f"{LEDS_ROOT}/{led_name}"
    return Plan(
        operation="status",
        commands=(
            Command((*adb, "shell", "cat", f"{node}/brightness"),
                    "current LED brightness"),
            Command((*adb, "shell", "cat", f"{node}/max_brightness"),
                    "max LED brightness"),
            Command((*adb, "shell", "cat", f"{node}/trigger"),
                    "current LED trigger binding"),
            Command((*adb, "shell", "getprop", SESSION_OPEN_PROP),
                    f"current {SESSION_OPEN_PROP}"),
        ),
        needs_force=False,
        notes=("Read-only. Use this to capture state before and after a change.",),
    )


def build_disable_plan(
    *,
    serial: str | None = None,
    host: str | None = None,
    led_name: str = DEFAULT_LED_NAME,
) -> Plan:
    """Side-effectful, UNCONFIRMED attempt to turn the recording LED off.

    Mirrors the hypothesized sequence from prior investigation:
      1. clear the property that drives the camera session / LED,
      2. detach the LED's kernel trigger,
      3. force brightness to 0 (twice — before and after the trigger change,
         since some drivers re-assert brightness when the trigger is rebound).

    Requires `force=True` to execute. May require root + SELinux changes and may
    simply not work on a stock device.
    """
    adb = _adb_prefix(serial, host)
    node = f"{LEDS_ROOT}/{led_name}"
    return Plan(
        operation="disable",
        commands=(
            Command((*adb, "shell", "setprop", SESSION_OPEN_PROP, "0"),
                    f"clear {SESSION_OPEN_PROP} (camera/LED session hint)",
                    writes=True),
            Command((*adb, "shell", f"echo 0 > {node}/brightness"),
                    "force LED brightness to 0", writes=True),
            Command((*adb, "shell", f"echo none > {node}/trigger"),
                    "detach the kernel LED trigger", writes=True),
            Command((*adb, "shell", f"echo 0 > {node}/brightness"),
                    "force brightness to 0 again after trigger change",
                    writes=True),
        ),
        needs_force=True,
        notes=(
            "UNCONFIRMED: no known reliable non-root method exists.",
            "A non-root adb shell typically cannot write under /sys/class/leds.",
            "SELinux may block this; you may need root/Magisk and a policy change.",
            "Defeating a recording indicator may be illegal — own-device dev use only.",
        ),
    )


def build_restore_plan(
    *,
    serial: str | None = None,
    host: str | None = None,
    led_name: str = DEFAULT_LED_NAME,
) -> Plan:
    """Side-effectful attempt to put the LED back under normal control.

    Rebinds the default kernel trigger and restores the session property, so a
    developer can undo a `disable` attempt. Requires `force=True`.
    """
    adb = _adb_prefix(serial, host)
    node = f"{LEDS_ROOT}/{led_name}"
    return Plan(
        operation="restore",
        commands=(
            Command((*adb, "shell", f"echo timer > {node}/trigger"),
                    "rebind a default kernel trigger", writes=True),
            Command((*adb, "shell", "setprop", SESSION_OPEN_PROP, "1"),
                    f"restore {SESSION_OPEN_PROP}", writes=True),
        ),
        needs_force=True,
        notes=(
            "Best-effort undo of `disable`. The exact default trigger varies by "
            "device; reboot the glasses to guarantee a clean LED state.",
        ),
    )


PLAN_BUILDERS = {
    "probe": build_probe_plan,
    "status": build_status_plan,
    "disable": build_disable_plan,
    "restore": build_restore_plan,
}


@dataclass
class StepResult:
    command: Command
    executed: bool
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    skipped_reason: str | None = None


@dataclass
class RunReport:
    operation: str
    dry_run: bool
    applied: bool
    steps: list[StepResult]
    blocked_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "operation": self.operation,
            "dry_run": self.dry_run,
            "applied": self.applied,
            "blocked_reason": self.blocked_reason,
            "steps": [
                {
                    "command": s.command.rendered,
                    "purpose": s.command.purpose,
                    "writes": s.command.writes,
                    "executed": s.executed,
                    "returncode": s.returncode,
                    "stdout": s.stdout,
                    "stderr": s.stderr,
                    "skipped_reason": s.skipped_reason,
                }
                for s in self.steps
            ],
        }


def execute_plan(
    plan: Plan,
    *,
    apply: bool = False,
    force: bool = False,
    runner=subprocess.run,
    timeout: float = 20.0,
) -> RunReport:
    """Execute (or dry-run) a plan under the safety gate.

    Default behavior is a DRY RUN: no command is executed, the plan is just
    described. To actually run anything the caller must pass `apply=True`. To run
    a write-bearing plan (disable/restore) the caller must ALSO pass `force=True`.

    `runner` is injected so tests can assert on argv without spawning processes.
    """
    dry_run = not apply

    # Safety gate: write-bearing plans need an explicit force, even with apply.
    if apply and plan.needs_force and not force:
        return RunReport(
            operation=plan.operation,
            dry_run=False,
            applied=False,
            blocked_reason=(
                f"operation '{plan.operation}' changes device state and requires "
                "an explicit force flag; refusing to run"
            ),
            steps=[
                StepResult(command=c, executed=False,
                           skipped_reason="force flag required")
                for c in plan.commands
            ],
        )

    steps: list[StepResult] = []
    for cmd in plan.commands:
        if dry_run:
            steps.append(
                StepResult(command=cmd, executed=False, skipped_reason="dry-run")
            )
            continue
        try:
            proc = runner(
                list(cmd.argv),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            steps.append(
                StepResult(
                    command=cmd,
                    executed=True,
                    returncode=proc.returncode,
                    stdout=(proc.stdout or "").strip(),
                    stderr=(proc.stderr or "").strip(),
                )
            )
        except FileNotFoundError:
            steps.append(
                StepResult(command=cmd, executed=False,
                           skipped_reason="adb not found on PATH")
            )
        except subprocess.TimeoutExpired:
            steps.append(
                StepResult(command=cmd, executed=False,
                           skipped_reason="command timed out")
            )

    return RunReport(
        operation=plan.operation,
        dry_run=dry_run,
        applied=apply,
        steps=steps,
    )

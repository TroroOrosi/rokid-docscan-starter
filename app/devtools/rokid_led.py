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
import time
from dataclasses import dataclass, field

# The hypothesized hardware path: the custom camera session open property is
# what (per prior investigation) makes init.rokid.rc drive the LED node.
SESSION_OPEN_PROP = "persist.vendor.rkd.camera.session_open"

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
            Command((*adb, "shell", "getenforce"),
                    "current SELinux enforcing state"),
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


# ---------------------------------------------------------------------------
# Verification layer
#
# Running a command and getting `rc=0` does NOT prove the physical LED is off.
# A non-root shell may report success on a redirect that the kernel silently
# rejects, SELinux may deny the write after the shell exited 0, or a vendor
# init/HAL service may re-assert brightness milliseconds later. This layer
# parses the *readback* values from a `status` plan into structured evidence
# and renders a conservative verdict that is explicitly separate from the
# command exit codes.
# ---------------------------------------------------------------------------

# Sentinel string for a value we could not read (permission denied, missing
# node, adb absent, dry-run, ...). Kept distinct from a real "0".
UNKNOWN = "?"


def _classify_readback(stdout: str, stderr: str, returncode: int | None) -> str | None:
    """Extract the meaningful value from a `cat`/`getprop` step.

    Returns the trimmed first line on success, or ``None`` when the value is
    unknowable (non-zero rc, permission denied, no such file, empty output).
    A returned ``None`` is later surfaced as :data:`UNKNOWN` — never confused
    with a literal ``"0"``.
    """
    if returncode not in (0, None):
        return None
    blob = (stdout or "").strip()
    if not blob:
        return None
    first = blob.splitlines()[0].strip()
    low = first.lower()
    # adb/toybox error text sometimes arrives on stdout with rc=0.
    if any(t in low for t in ("permission denied", "no such file", "not found")):
        return None
    return first


def _parse_brightness(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        return None


@dataclass
class LedSnapshot:
    """Parsed, structured readback of a single ``status`` capture.

    Every field is either the observed value or :data:`UNKNOWN`/``None`` — we
    never invent a default that could be mistaken for a real reading.
    """

    brightness: int | None = None
    max_brightness: int | None = None
    trigger: str = UNKNOWN
    session_prop: str = UNKNOWN
    enforcing: str = UNKNOWN  # filled in only when a probe is folded in
    readable: bool = False  # did we manage to read brightness at all?

    def to_dict(self) -> dict:
        return {
            "brightness": self.brightness,
            "max_brightness": self.max_brightness,
            "trigger": self.trigger,
            "session_prop": self.session_prop,
            "enforcing": self.enforcing,
            "readable": self.readable,
        }


def parse_status(report: RunReport) -> LedSnapshot:
    """Turn an executed ``status`` :class:`RunReport` into a :class:`LedSnapshot`.

    Matches steps by their command purpose so it is robust to ordering. Steps
    that did not execute (dry-run, adb missing) yield UNKNOWN fields.
    """
    snap = LedSnapshot()
    for step in report.steps:
        val = _classify_readback(step.stdout, step.stderr, step.returncode) \
            if step.executed else None
        purpose = step.command.purpose
        if purpose == "current LED brightness":
            snap.brightness = _parse_brightness(val)
            snap.readable = snap.brightness is not None
        elif purpose == "max LED brightness":
            snap.max_brightness = _parse_brightness(val)
        elif purpose == "current LED trigger binding":
            snap.trigger = val if val is not None else UNKNOWN
        elif purpose == "current SELinux enforcing state":
            snap.enforcing = val if val is not None else UNKNOWN
        elif purpose.startswith("current ") and SESSION_OPEN_PROP in purpose:
            snap.session_prop = val if val is not None else UNKNOWN
    return snap


# Verdict vocabulary, kept deliberately small and conservative.
VERDICT_OFF = "off"          # brightness readable AND 0
VERDICT_ON = "on"            # brightness readable AND > 0
VERDICT_UNKNOWN = "unknown"  # could not read brightness — claim nothing


def verdict_for(snapshot: LedSnapshot) -> str:
    """Conservative state from a snapshot. Unreadable brightness => UNKNOWN.

    We never report ``off`` from a non-zero exit code or a missing readback —
    only from an actual ``brightness == 0`` reading.
    """
    if snapshot.brightness is None:
        return VERDICT_UNKNOWN
    return VERDICT_OFF if snapshot.brightness == 0 else VERDICT_ON


@dataclass
class VerificationReport:
    """Evidence bundle for one disable-and-verify attempt.

    Separates three things that are easy to conflate:
      * ``write_succeeded`` — did the disable commands exit 0,
      * ``verified_state``  — what the *readback* actually shows,
      * ``confirmed_off``   — only true when the readback proves brightness 0.
    """

    led_name: str
    dry_run: bool
    applied: bool
    blocked_reason: str | None = None
    before: LedSnapshot = field(default_factory=LedSnapshot)
    after: LedSnapshot = field(default_factory=LedSnapshot)
    attempts: int = 0
    reasserted: bool = False
    write_report: RunReport | None = None
    status_reports: list[RunReport] = field(default_factory=list)

    @property
    def write_succeeded(self) -> bool:
        wr = self.write_report
        if wr is None or not wr.applied:
            return False
        return all(
            (s.executed and s.returncode == 0) for s in wr.steps if s.command.writes
        )

    @property
    def verified_state(self) -> str:
        return verdict_for(self.after)

    @property
    def confirmed_off(self) -> bool:
        return self.verified_state == VERDICT_OFF

    @property
    def headline(self) -> str:
        if self.blocked_reason:
            return "blocked"
        if self.dry_run:
            return "dry-run (no device state changed)"
        if self.confirmed_off:
            return "LED reads OFF (brightness=0) — confirm visually with a 2nd camera"
        if self.verified_state == VERDICT_ON:
            if self.write_succeeded:
                return "commands succeeded BUT LED still reads ON (likely re-asserted)"
            return "LED reads ON"
        # unknown
        if self.write_succeeded:
            return "commands exited 0 but state UNVERIFIABLE (brightness unreadable)"
        return "state UNVERIFIABLE (brightness unreadable; writes may have failed)"

    def to_dict(self) -> dict:
        return {
            "led_name": self.led_name,
            "dry_run": self.dry_run,
            "applied": self.applied,
            "blocked_reason": self.blocked_reason,
            "headline": self.headline,
            "write_succeeded": self.write_succeeded,
            "verified_state": self.verified_state,
            "confirmed_off": self.confirmed_off,
            "attempts": self.attempts,
            "reasserted": self.reasserted,
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
            "write_report": self.write_report.to_dict() if self.write_report else None,
            "status_reports": [r.to_dict() for r in self.status_reports],
        }


def run_verification(
    *,
    serial: str | None = None,
    host: str | None = None,
    led_name: str = DEFAULT_LED_NAME,
    apply: bool = False,
    force: bool = False,
    retries: int = 0,
    retry_delay: float = 1.0,
    runner=subprocess.run,
    sleep=time.sleep,
) -> VerificationReport:
    """Capture status, attempt a disable, then re-capture and judge.

    Flow (only when ``apply and force``):
      1. ``status`` before  -> :attr:`before`
      2. ``disable`` write  -> :attr:`write_report`
      3. ``status`` after   -> :attr:`after`
      4. while the LED is *not* confirmed off and retries remain, wait
         ``retry_delay`` seconds, re-assert the disable, and re-read. This
         catches the case where a vendor init/HAL service turns the LED back
         on shortly after the write (``reasserted`` is then True).

    Without ``apply`` it is a pure dry-run: no commands execute, both snapshots
    are UNKNOWN, and the verdict is ``unknown``. Without ``force`` (but with
    ``apply``) the write is blocked exactly like :func:`execute_plan`, and the
    ``blocked_reason`` is propagated — no status is captured, nothing runs.
    """
    rep = VerificationReport(
        led_name=led_name, dry_run=not apply, applied=apply,
    )

    # Mirror the execute_plan safety gate up front so a non-forced apply does
    # not even read the device. Keeps the privacy/tamper contract intact.
    disable_plan = build_disable_plan(serial=serial, host=host, led_name=led_name)
    if apply and disable_plan.needs_force and not force:
        rep.blocked_reason = (
            f"operation 'disable' changes device state and requires an explicit "
            f"force flag; refusing to run"
        )
        rep.applied = False
        return rep

    status_plan = build_status_plan(serial=serial, host=host, led_name=led_name)

    def capture() -> LedSnapshot:
        r = execute_plan(status_plan, apply=apply, force=False, runner=runner)
        rep.status_reports.append(r)
        return parse_status(r)

    rep.before = capture()

    rep.write_report = execute_plan(
        disable_plan, apply=apply, force=force, runner=runner
    )
    rep.attempts = 1 if apply else 0
    rep.after = capture()

    # Re-check loop. Each pass waits, re-reads, and — if the LED is back on —
    # re-asserts the disable. This catches a vendor init/HAL service that turns
    # the LED back on shortly after the first write. We keep re-checking even
    # after an apparent "off" so a *delayed* re-assert is still detected; the
    # loop stops early only once a check confirms off AND the prior check also
    # confirmed off (state is stable).
    prev_off = verdict_for(rep.after) == VERDICT_OFF
    for _ in range(max(0, retries)) if (apply and force) else ():
        sleep(retry_delay)
        if verdict_for(rep.after) != VERDICT_OFF:
            # LED is on/unknown: actively re-assert the disable.
            rep.write_report = execute_plan(
                disable_plan, apply=apply, force=force, runner=runner
            )
            rep.attempts += 1
        new_after = capture()
        if prev_off and verdict_for(new_after) == VERDICT_ON:
            rep.reasserted = True
        now_off = verdict_for(new_after) == VERDICT_OFF
        rep.after = new_after
        if prev_off and now_off:
            break  # two consecutive off reads -> stable, stop early
        prev_off = now_off

    return rep

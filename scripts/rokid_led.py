#!/usr/bin/env python3
"""Rokid Glasses privacy / recording-LED developer diagnostic CLI.

Out-of-band developer tool. It is NOT wired into the server or the doc-scan /
exam flows — the running service still advertises the recording LED as
always_on / tamper:forbidden (see app/glasses_view.py). Use this only on a
device you own and control.

Subcommands:
  connect <ip>   plan the wireless ADB handshake (adb tcpip + adb connect)
  probe          read-only discovery of LED nodes / properties / SELinux state
  status         read-only report of current LED brightness / trigger / prop
  disable        UNCONFIRMED attempt to turn the recording LED off  (gated)
  restore        best-effort undo of `disable`                       (gated)

SAFETY:
  * DRY RUN by default — nothing touches the device. Add --apply to execute.
  * `disable` / `restore` change device state and ALSO require --force.
  * There is no confirmed non-root, software-only way to disable the LED;
    SELinux / vendor init policy / root may all get in the way.
  * Defeating a recording indicator can be ILLEGAL. Own-device dev use only,
    in compliance with local law and visible-recording expectations.

Examples:
  # See the wireless-connect commands (dry run, nothing executed):
  python scripts/rokid_led.py connect 192.168.1.50

  # Discover LED nodes / properties on the connected device:
  python scripts/rokid_led.py probe --host 192.168.1.50:5555

  # Report current LED state:
  python scripts/rokid_led.py status --host 192.168.1.50:5555

  # Print the disable plan WITHOUT running it (default dry run):
  python scripts/rokid_led.py disable --led white

  # Actually attempt it on your own device (both flags required):
  python scripts/rokid_led.py disable --led white --apply --force

  # JSON output (e.g. for tooling):
  python scripts/rokid_led.py probe --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# allow running as a plain script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.devtools import rokid_led  # noqa: E402
from app.devtools.rokid_led import DEFAULT_LED_NAME, execute_plan  # noqa: E402

WARNING_BANNER = (
    "!! Rokid recording-LED dev tool — own-device use only. Disabling a "
    "recording indicator may be illegal; no confirmed non-root method exists."
)


def build_plan(args: argparse.Namespace):
    if args.command == "connect":
        return rokid_led.build_connect_plan(args.host, port=args.port)
    builder = rokid_led.PLAN_BUILDERS[args.command]
    return builder(serial=args.serial, host=args.host, led_name=args.led)


def _print_human(plan, report) -> None:
    print(WARNING_BANNER)
    print(f"\noperation: {plan.operation}")
    if report.blocked_reason:
        mode = "BLOCKED"
    elif report.applied:
        mode = "APPLY"
    else:
        mode = "DRY-RUN"
    print(f"mode:      {mode}{' (writes device state)' if plan.writes else ''}")
    if report.blocked_reason:
        print(f"BLOCKED:   {report.blocked_reason}")
    if plan.notes:
        print("notes:")
        for n in plan.notes:
            print(f"  - {n}")
    print("\nsteps:")
    for i, step in enumerate(report.steps, 1):
        mark = "W" if step.command.writes else "r"
        print(f"  [{i}] ({mark}) {step.command.purpose}")
        print(f"        $ {step.command.rendered}")
        if step.executed:
            print(f"        -> rc={step.returncode}")
            if step.stdout:
                print(f"        out: {step.stdout}")
            if step.stderr:
                print(f"        err: {step.stderr}")
        elif step.skipped_reason:
            print(f"        (skipped: {step.skipped_reason})")


def run(args: argparse.Namespace) -> int:
    plan = build_plan(args)
    report = execute_plan(plan, apply=args.apply, force=args.force)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        _print_human(plan, report)
    # Non-zero exit if an apply was blocked by the safety gate.
    return 2 if report.blocked_reason else 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Rokid recording-LED developer diagnostic (dry-run by default)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=WARNING_BANNER,
    )
    sub = ap.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser, *, with_led: bool = True) -> None:
        p.add_argument("--serial", help="adb device serial (adb -s)")
        p.add_argument("--host", help="device ip:port after `adb connect` (e.g. 192.168.1.50:5555)")
        if with_led:
            p.add_argument("--led", default=DEFAULT_LED_NAME,
                           help=f"LED node name under /sys/class/leds (default: {DEFAULT_LED_NAME})")
        p.add_argument("--apply", action="store_true",
                       help="actually execute (default is a dry run)")
        p.add_argument("--force", action="store_true",
                       help="required to execute write/destructive operations")
        p.add_argument("--json", action="store_true", help="emit a JSON report")

    pc = sub.add_parser("connect", help="plan wireless ADB handshake")
    pc.add_argument("host", help="glasses IP, optionally ip:port")
    pc.add_argument("--port", type=int, default=5555, help="tcpip port (default 5555)")
    pc.add_argument("--serial", default=None, help=argparse.SUPPRESS)
    pc.add_argument("--led", default=DEFAULT_LED_NAME, help=argparse.SUPPRESS)
    pc.add_argument("--apply", action="store_true",
                    help="actually execute (default is a dry run)")
    pc.add_argument("--force", action="store_true", help=argparse.SUPPRESS)
    pc.add_argument("--json", action="store_true", help="emit a JSON report")

    add_common(sub.add_parser("probe", help="read-only LED/property discovery"))
    add_common(sub.add_parser("status", help="read-only current LED state"))
    add_common(sub.add_parser("disable", help="UNCONFIRMED LED-off attempt (gated)"))
    add_common(sub.add_parser("restore", help="best-effort undo of disable (gated)"))
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())

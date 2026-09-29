"""Run in phone Termux: reopen the chooser after the glasses unfold."""

import argparse
import subprocess
import time
from pathlib import Path

COMPONENT = "dev.rokid.docscanglass.doc/.DocScanGlassActivity"
# Written by the server (app/main.py _remember_glasses_address) from the
# glasses' own requests: the phone hotspot picks their address.
ADDRESS_FILE = Path(__file__).resolve().parent.parent / "data" / "glasses-address"


def target(serial: str) -> str:
    """The adb target; "auto" connects to the address the server last saw."""
    if serial != "auto":
        return serial
    address = ADDRESS_FILE.read_text(encoding="ascii").strip()
    subprocess.run(["adb", "connect", f"{address}:5555"], capture_output=True, timeout=10)
    return f"{address}:5555"


def adb(serial: str, *args: str) -> str:
    result = subprocess.run(
        ["adb", "-s", serial, *args], check=True, capture_output=True,
        text=True, timeout=10,
    )
    # Android's am can report an error while its process returns zero.
    output = result.stdout + result.stderr
    if "Error:" in output or "Exception" in output:
        raise subprocess.CalledProcessError(1, "adb")
    return result.stdout.strip()


def watch(requested: str, expected_serial: str, interval: float) -> None:
    folded = False
    verified = False
    disconnected = False
    serial = requested
    while True:
        try:
            if not verified:
                serial = target(requested)
                if adb(serial, "shell", "getprop", "ro.serialno") != expected_serial:
                    raise SystemExit("Glasses identity mismatch; watcher stopped")
                verified = True
            spread = adb(serial, "shell", "getprop", "vendor.rkd.glasses.is_spread")
            if spread not in ("0", "1"):
                raise subprocess.CalledProcessError(1, "getprop")
            if disconnected:
                print("Glasses connection restored", flush=True)
                disconnected = False
            if spread == "0":
                folded = True
            elif folded:
                # Consume before side effects: a lost reply must not relaunch after exit.
                folded = False
                adb(serial, "shell", "input", "-d", "0", "keyevent", "KEYCODE_WAKEUP")
                adb(serial, "shell", "am", "start", "-W", "-n", COMPONENT)
                print("Glasses unfolded: chooser started", flush=True)
        except (subprocess.SubprocessError, OSError):
            verified = False
            if not disconnected:
                print("Glasses unavailable; waiting without starting capture", flush=True)
                disconnected = True
        time.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--serial", required=True,
        help='Existing authorized phone adb target, or "auto" for the address the server last saw')
    parser.add_argument("--expected-serial", required=True, help="Glasses ro.serialno")
    parser.add_argument("--interval", type=float, default=0.5, help="Fold polling interval in seconds")
    args = parser.parse_args()
    if not 0.1 <= args.interval <= 5:
        parser.error("interval must be between 0.1 and 5 seconds")
    try:
        watch(args.serial, args.expected_serial, args.interval)
    except KeyboardInterrupt:
        pass

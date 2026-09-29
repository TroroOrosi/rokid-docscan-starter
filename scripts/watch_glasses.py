"""Run in phone Termux: reopen the chooser after the glasses unfold."""

import argparse
import re
import subprocess
import time

COMPONENT = "dev.rokid.docscanglass.doc/.DocScanGlassActivity"
# phone_serve.sh connects this, the phone's own adbd, before the server starts.
PHONE = "127.0.0.1:5555"
# `dumpsys tethering` lists each hotspot client as "client: /10.248.83.167 (mac)".
_CLIENT = re.compile(r"client: /(\d+\.\d+\.\d+\.\d+) ")


def hotspot_clients() -> list[str]:
    """Addresses the phone's hotspot has handed out, as the phone itself reports.

    The hotspot picks the glasses' address, and 2026-09-30 showed the app can
    fail before it ever talks to the server, so the phone is the one source.
    """
    # Not adb(): the dump's own history contains the word "Exception".
    result = subprocess.run(["adb", "-s", PHONE, "shell", "dumpsys", "tethering"],
                            check=True, capture_output=True, text=True, timeout=10)
    return _CLIENT.findall(result.stdout)


def target(serial: str, expected_serial: str) -> str:
    """The adb target; "auto" is the hotspot client whose serial matches."""
    if serial != "auto":
        return serial
    for address in hotspot_clients():
        candidate = f"{address}:5555"
        try:
            # A PC on the hotspot has no adbd, and its connect times out.
            subprocess.run(["adb", "connect", candidate], capture_output=True, timeout=5)
            if adb(candidate, "shell", "getprop", "ro.serialno") == expected_serial:
                return candidate
        except (subprocess.SubprocessError, OSError):
            continue  # a PC or another client on the hotspot
    raise subprocess.CalledProcessError(1, "adb connect")


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
                serial = target(requested, expected_serial)
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
        help='Existing authorized phone adb target, or "auto" to find it among the hotspot clients')
    parser.add_argument("--expected-serial", required=True, help="Glasses ro.serialno")
    parser.add_argument("--interval", type=float, default=0.5, help="Fold polling interval in seconds")
    args = parser.parse_args()
    if not 0.1 <= args.interval <= 5:
        parser.error("interval must be between 0.1 and 5 seconds")
    try:
        watch(args.serial, args.expected_serial, args.interval)
    except KeyboardInterrupt:
        pass

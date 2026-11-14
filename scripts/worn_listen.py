"""Listen while the wearer uses the glasses by themself: nothing is driven from this PC after the preparation.

A worn check has to be the use itself: put the glasses on, start with one's own double tap, read, take them off. On
2026-11-14 two attempts failed because the check was built around this PC (a cable, a start sent from here, a wait for
a signal from here). This prepares the test-only app (which answers through the stand-in server and can never reach
the model), then only reads: the app's log, and every 10 s the temperatures, battery and display state.

    py -3.12 scripts/worn_listen.py --glasses <adb transport, e.g. from glasses_over_phone.py> --out <dir>
        [--server http://127.0.0.1:8765 --key <test api key>] [--minutes 90]

The wearer: put the glasses on (the chooser appears; a tap brings it back if it has gone dark), double tap to start,
read and turn pages, then either take them off or double tap to end and read the stand-in's answers.
Afterwards: scripts/head_motion_report.py --glasses <transport> --package dev.rokid.docscanglass.doc.routecheck.
Stop with Ctrl-C or by ending the process; the real app's wear detection returns when the real app is next opened.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ADB = os.environ.get("ADB", r"C:\Users\pupu_\AppData\Local\Android\Sdk\platform-tools\adb.exe")
PACKAGE = "dev.rokid.docscanglass.doc.routecheck"
REAL_PACKAGE = "dev.rokid.docscanglass.doc"
GLASSES_SERIAL = "1904092623381086"
ENV = dict(os.environ, MSYS_NO_PATHCONV="1")
SAMPLE = ('echo "$(date +%H:%M:%S) soc=$(cat /sys/class/thermal/thermal_zone0/temp) '
          'board=$(for z in /sys/class/thermal/thermal_zone*; do [ "$(cat $z/type)" = sys-therm-0 ] && cat $z/temp; done) '
          'battery=$(cat /sys/class/power_supply/battery/capacity)% $(cat /sys/class/power_supply/battery/status) '
          'current_ua=$(cat /sys/class/power_supply/battery/current_now) voltage_uv=$(cat /sys/class/power_supply/battery/voltage_now) '
          'spread=$(getprop vendor.rkd.glasses.is_spread) $(dumpsys power | grep -o "mWakefulness=[A-Za-z]*")"')


def adb(glasses: str, *args: str, timeout: int = 40) -> str:
    try:
        return subprocess.run([ADB, "-s", glasses, *args], capture_output=True, timeout=timeout, env=ENV,
                              stdin=subprocess.DEVNULL).stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--glasses", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--server", default="http://127.0.0.1:8765")
    parser.add_argument("--key", required=True)
    parser.add_argument("--minutes", type=float, default=90)
    options = parser.parse_args()
    out = Path(options.out)
    out.mkdir(parents=True, exist_ok=True)
    glasses = options.glasses
    if adb(glasses, "shell", "getprop ro.serialno").strip() != GLASSES_SERIAL:
        print("these are not the glasses")
        return 1
    port = options.server.rsplit(":", 1)[-1]
    adb(glasses, "reverse", f"tcp:{port}", f"tcp:{port}")
    # Only the test-only app may answer the wear sensor: the real app's end of capture goes to the model.
    adb(glasses, "shell", f"am force-stop {REAL_PACKAGE}; am force-stop {PACKAGE}; "
        f"rm -f /sdcard/Android/data/{PACKAGE}/files/head-motion.bin; input keyevent KEYCODE_WAKEUP; "
        f"am start -n {PACKAGE}/dev.rokid.docscanglass.doc.DocScanGlassActivity --es server {options.server} "
        f"--es key {options.key} --ez chooser true")
    print("prepared: the test-only app shows its chooser; from here this PC only listens", flush=True)
    log = open(out / "app-log.txt", "wb")  # noqa: SIM115 - held for the life of the listener
    reader = None  # the device's log is read from now on and never cleared
    deadline = time.monotonic() + options.minutes * 60
    with open(out / "samples.txt", "a", encoding="utf-8") as samples:
        while time.monotonic() < deadline:
            if reader is None or reader.poll() is not None:  # the link drops when the wearer walks; pick it up again
                subprocess.run([ADB, "connect", glasses], capture_output=True, timeout=20, env=ENV) if ":" in glasses else None
                adb(glasses, "reverse", f"tcp:{port}", f"tcp:{port}")
                reader = subprocess.Popen([ADB, "-s", glasses, "logcat", "-v", "time", "-T", "1", "-s", "DocScanGlassDoc:*"],
                                          stdout=log, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, env=ENV)
            line = adb(glasses, "shell", SAMPLE).strip()
            samples.write((line or f"{time.strftime('%H:%M:%S')} unreachable") + "\n")
            samples.flush()
            time.sleep(10)
    if reader:
        reader.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())

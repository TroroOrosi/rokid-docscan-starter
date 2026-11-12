"""Take one automatic photo on the connected glasses, with nobody touching them.

Run this after every change to the glasses' camera path, before asking the wearer
to try anything. A PC test uses a fake camera: it showed neither the frame handler
that took 145-285 ms on the device nor the still that firmware 1.29.013 never
returned (2026-11-12). This starts the installed app, sends the start tap, and
waits for the app's own log to say a full-size photo was taken and saved.

    py -3.12 scripts/glasses_capture_smoke.py --serial 127.0.0.1:5556

After the first photo is saved it keeps watching (--watch seconds): on
2026-11-12 an unmoving page was photographed five times in 15 s, which one
photo and an immediate stop had hidden, and the stop cut off the upload.

It never sends the double tap that ends a capture, so nothing is sent to GPT.
The photo is uploaded to the phone server as one page of a new document when the
server is reachable. The glasses may lie on a desk; a dark frame still passes,
because this checks that the camera path works, not what the picture shows.
Exit code 0 on PASS, 1 on FAIL.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time

PACKAGE = "dev.rokid.docscanglass.doc"
GLASSES_SERIAL = "1904092623381086"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--serial", required=True, help="adb transport of the glasses")
    parser.add_argument("--expect-serialno", default=GLASSES_SERIAL)
    parser.add_argument("--seconds", type=int, default=40)
    parser.add_argument("--watch", type=int, default=15, help="seconds to keep watching after the first photo")
    options = parser.parse_args()
    adb = shutil.which("adb") or os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe")

    def shell(command: str) -> str:
        return subprocess.run([adb, "-s", options.serial, "shell", command], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=options.seconds + options.watch + 30).stdout

    if shell("getprop ro.serialno").strip() != options.expect_serialno:
        print("FAIL: this transport is not the expected glasses")
        return 1
    if shell("getprop vendor.rkd.glasses.is_spread").strip() != "1":
        print("FAIL: the temple arms are folded; the system stops the app while they are")
        return 1
    version = re.search(r"versionName=(\S+)", shell(f"dumpsys package {PACKAGE} | grep versionName"))
    started = shell('date "+%m-%d %H:%M:%S.000"').strip()
    shell(f"am force-stop {PACKAGE}; input keyevent KEYCODE_WAKEUP; sleep 1; "
          f"am start -n {PACKAGE}/.DocScanGlassActivity >/dev/null; sleep 4; "
          "input keyevent KEYCODE_NOTIFICATION KEYCODE_ENTER")
    deadline, log = time.monotonic() + options.seconds, ""
    while time.monotonic() < deadline:
        log = shell(f'logcat -d -v time -t "{started}" -s DocScanGlassDoc:*')
        if "Photo committed locally" in log or "capture failed" in log or "ERROR:" in log:
            break
        time.sleep(2)
    if "Photo committed locally" in log:
        time.sleep(options.watch)
        later = ""
        for _ in range(3):  # a read through the phone relay came back empty once (2026-11-12)
            later = shell(f'logcat -d -v time -t "{started}" -s DocScanGlassDoc:*')
            if "Photo committed locally" in later:
                break
            time.sleep(2)
        if "Photo committed locally" not in later:
            print("FAIL: the log could not be read back after the photo; the adb connection is unreliable")
            return 1
        log = later
    status = [line for line in log.splitlines() if "preview_status" in line]
    work = [int(value) for value in re.findall(r"max_work_ms=(\d+)", "\n".join(status[1:]))]
    captured = re.search(r"captured (\d+)x(\d+) (\d+)B in (\d+)ms", log)
    photos = len(re.findall(r"captured \d+x\d+ \d+B in", log))
    shell(f"am force-stop {PACKAGE}")
    for line in log.splitlines():
        if re.search(r"captured \d+x|capture failed|ERROR:|preview failed|Photo committed|still_", line):
            print("  " + line[:200])
    print(f"app {version.group(1) if version else 'unknown'}; preview frame handling "
          f"{max(work) if work else 'unknown'} ms at most over {len(work)} s")
    if not captured or "Photo committed locally" not in log:
        print("FAIL: no photo was taken and saved")
        return 1
    if int(captured.group(1)) < 4000:
        print("FAIL: the photo is not full size")
        return 1
    if work and max(work) > 100:
        print("FAIL: the preview frame handler is too slow to keep metering current")
        return 1
    if photos > 2:
        print(f"FAIL: {photos} photos in {options.watch} s; an unmoving page is being taken again and again")
        return 1
    print(f"PASS: {captured.group(1)}x{captured.group(2)}, {captured.group(3)} bytes, {captured.group(4)} ms; "
          f"{photos} photo(s) in the {options.watch} s after the first was saved")
    return 0


if __name__ == "__main__":
    sys.exit(main())

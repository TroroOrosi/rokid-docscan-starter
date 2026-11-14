"""Reach the glasses' adb from this PC without a cable, through the phone.

The glasses are on the phone's hotspot; the phone is also on the home network, where this PC's adb already reaches it.
`start` puts scripts/phone_adb_relay.py on the phone (Termux), runs it, connects this PC's adb to it and prints the
transport to pass as --glasses to the other scripts. `stop` disconnects and ends the relay.

    py -3.12 scripts/glasses_over_phone.py start --phone <phone adb transport> [--port 5556]
    py -3.12 scripts/glasses_over_phone.py stop  --phone <phone adb transport> [--port 5556]
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ADB = os.environ.get("ADB", r"C:\Users\pupu_\AppData\Local\Android\Sdk\platform-tools\adb.exe")
GLASSES_SERIAL = "1904092623381086"
ENV = dict(os.environ, MSYS_NO_PATHCONV="1")
TERMUX = ("export PREFIX=/data/data/com.termux/files/usr HOME=/data/data/com.termux/files/home; "
          "export PATH=$PREFIX/bin:$PATH LD_LIBRARY_PATH=$PREFIX/lib TMPDIR=$PREFIX/tmp; ")


def adb(*args: str, stdin: bytes | None = None, timeout: int = 60) -> str:
    return subprocess.run([ADB, *args], input=stdin, capture_output=True, timeout=timeout, env=ENV,
                          stdin=None if stdin is not None else subprocess.DEVNULL).stdout.decode("utf-8", "replace")


def termux(phone: str, script: str) -> str:
    return adb("-s", phone, "shell", "run-as com.termux sh -s", stdin=(TERMUX + script + "\n").encode())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("action", choices=["start", "stop"])
    parser.add_argument("--phone", required=True)
    parser.add_argument("--port", type=int, default=5556)
    options = parser.parse_args()
    host = options.phone.split(":")[0]
    transport = f"{host}:{options.port}"
    adb("disconnect", transport)
    termux(options.phone, "pkill -f phone_adb_relay.py; true")
    if options.action == "stop":
        print("relay stopped")
        return 0
    found = re.search(r"^(\d+\.\d+\.\d+\.\d+):5555\s+device", termux(options.phone, "adb devices </dev/null"), re.M)
    if not found:
        print("the phone's own adb has no link to the glasses (hotspot off, or the glasses are not on it)")
        return 1
    relay = Path(__file__).with_name("phone_adb_relay.py").read_bytes().replace(b"\r\n", b"\n")
    adb("-s", options.phone, "shell", "run-as com.termux sh -c 'cat > /data/data/com.termux/files/home/phone_adb_relay.py'", stdin=relay)
    termux(options.phone, f"cd $HOME; setsid nohup python phone_adb_relay.py {host} {options.port} {found.group(1)} >/dev/null 2>&1 &")
    for _ in range(10):
        time.sleep(1)
        adb("connect", transport)
        if adb("-s", transport, "shell", "getprop ro.serialno").strip() == GLASSES_SERIAL:
            print(transport)
            return 0
    print(f"no glasses behind {transport}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

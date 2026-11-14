"""Watch the whole system, not one component, while the glasses run a capture.

Drives the glasses app through its screens with events written to the touchpad's own input device (the path a real
touch takes) and, on the glasses and the phone at once, samples load, memory, temperature, battery and the server's
response time, then reads every log buffer of both devices for the run and counts warnings and errors by source.
It never sends the double tap that ends a capture (that sends the pages to the model): the app is force-stopped.

    py -3.12 scripts/system_observation.py --glasses <transport> --phone <transport> --out <dir> [--seconds 40]

Dumps are read whole on the PC; nothing is piped into an early-closing filter on a device (that killed the camera
provider on 2026-11-13). The camera service is not dumped while the camera may be streaming.
"""
from __future__ import annotations

import argparse
import collections
import os
import re
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

ADB = os.environ.get("ADB", r"C:\Users\pupu_\AppData\Local\Android\Sdk\platform-tools\adb.exe")
PACKAGE = "dev.rokid.docscanglass.doc"
TOUCHPAD = "/dev/input/event1"
KEYS = {"DASHBOARD": 204, "ENTER": 28, "BACK": 158}
ENV = dict(os.environ, MSYS_NO_PATHCONV="1")
BAD = re.compile(r"lowmemorykiller|Low on memory|has died|Fatal signal|FATAL EXCEPTION|ANR in|Skipped \d+ frames|thermal|"
                 r"throttl|avc: denied|Out of memory|OOM|DEAD_OBJECT|signal \d+|watchdog|Slow dispatch|Slow delivery|"
                 r"binder.*fail|disconnect|Connection reset|timed out|timeout", re.I)


def adb(serial: str, *args: str, timeout: int = 90) -> str:
    done = subprocess.run([ADB, "-s", serial, *args], capture_output=True, timeout=timeout, env=ENV)
    return done.stdout.decode("utf-8", "replace")


def sh(serial: str, command: str, timeout: int = 90) -> str:
    return adb(serial, "shell", command, timeout=timeout)


def gesture(serial: str, *names: str) -> None:
    parts = []
    for name in names:
        code = KEYS[name]
        parts.append(f"sendevent {TOUCHPAD} 1 {code} 1; sendevent {TOUCHPAD} 0 0 0; "
                     f"sendevent {TOUCHPAD} 1 {code} 0; sendevent {TOUCHPAD} 0 0 0; sleep 0.08")
    sh(serial, "; ".join(parts))


def snapshot(serial: str) -> dict[str, str]:
    """One whole-device reading; every command's output is read to the end."""
    top = sh(serial, "top -b -n 1 -m 8")
    mem = sh(serial, "cat /proc/meminfo")
    heat = sh(serial, "for z in /sys/class/thermal/thermal_zone*; do echo $(cat $z/type 2>/dev/null) $(cat $z/temp 2>/dev/null); done")
    battery = sh(serial, "dumpsys battery")
    return {"top": top, "mem": mem, "heat": heat, "battery": battery, "load": sh(serial, "cat /proc/loadavg")}


def digest(reading: dict[str, str]) -> str:
    cpu = re.search(r"(\d+)%cpu\s+(\d+)%user.*?(\d+)%sys.*?(\d+)%idle", reading["top"])
    rows = [line.split() for line in reading["top"].splitlines() if re.match(r"\s*\d+\s", line)]
    busy = ", ".join(f"{row[-1][-28:]} {row[8]}%" for row in rows[:4] if len(row) > 9)
    free = re.search(r"MemAvailable:\s+(\d+)", reading["mem"])
    temps = [int(t) for t in re.findall(r"\S+ (-?\d+)", reading["heat"]) if 1000 < abs(int(t)) < 200000]
    level = re.search(r"level: (\d+)", reading["battery"])
    warm = re.search(r"temperature: (\d+)", reading["battery"])
    return (f"idle={cpu.group(4) if cpu else '?'}% of {cpu.group(1) if cpu else '?'}% load={reading['load'].split()[0] if reading['load'] else '?'} "
            f"free={int(free.group(1)) // 1024 if free else '?'}MB hottest={max(temps) / 1000 if temps else '?'}C "
            f"battery={level.group(1) if level else '?'}% {int(warm.group(1)) / 10 if warm else '?'}C | {busy}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--glasses", required=True)
    parser.add_argument("--phone", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--seconds", type=int, default=40)
    parser.add_argument("--server", default="http://192.168.0.5:8000/health")
    options = parser.parse_args()
    out = Path(options.out)
    out.mkdir(parents=True, exist_ok=True)
    devices = {"glasses": options.glasses, "phone": options.phone}

    print("== before")
    stamps = {}
    for name, serial in devices.items():
        stamps[name] = sh(serial, "date '+%m-%d %H:%M:%S.000'").strip()
        clock = sh(serial, "date +%s").strip()
        about = sh(serial, "getprop ro.build.fingerprint; uptime; df -h /data")
        (out / f"{name}-before.txt").write_text(about + "\n" + sh(serial, "getprop"), encoding="utf-8")
        print(f"{name:8s} clock_skew={int(clock) - int(time.time()) if clock.isdigit() else '?'}s {digest(snapshot(serial))}")
        print("         " + " | ".join(line.strip() for line in about.splitlines()[1:4])[:230])

    samples: list[str] = []
    running = True

    def watch() -> None:
        while running:
            started = time.monotonic()
            try:
                began = time.monotonic()
                urllib.request.urlopen(options.server, timeout=5).read()
                health = f"{(time.monotonic() - began) * 1000:.0f}ms"
            except OSError as error:
                health = type(error).__name__
            line = f"t={time.monotonic() - zero:5.1f}s server={health}"
            for name, serial in devices.items():
                try:
                    line += f"\n   {name:8s} {digest(snapshot(serial))}"
                except (subprocess.TimeoutExpired, OSError) as error:
                    line += f"\n   {name:8s} unreadable: {type(error).__name__}"
            samples.append(line)
            time.sleep(max(0.0, 4 - (time.monotonic() - started)))

    glasses = options.glasses
    sh(glasses, f"am force-stop {PACKAGE}; input keyevent KEYCODE_WAKEUP; sleep 1; "
                f"am start -W -n {PACKAGE}/.DocScanGlassActivity --ez chooser true --ez wear_bootstrap true >/dev/null 2>&1")
    zero = time.monotonic()
    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    time.sleep(4)
    gesture(glasses, "DASHBOARD", "DASHBOARD", "BACK")  # on the chooser: start the selected reading
    time.sleep(options.seconds * 0.6)
    gesture(glasses, "DASHBOARD", "ENTER")  # pause
    time.sleep(4)
    gesture(glasses, "DASHBOARD", "ENTER")  # resume
    time.sleep(options.seconds * 0.4)
    sh(glasses, f"am force-stop {PACKAGE}")  # never the double tap: it would send the pages to the model
    running = False
    watcher.join(timeout=30)
    print("\n== during")
    print("\n".join(samples))
    (out / "samples.txt").write_text("\n".join(samples), encoding="utf-8")

    print("\n== logs of the run, every buffer")
    for name, serial in devices.items():
        text = adb(serial, "logcat", "-b", "all", "-d", "-v", "time", "-t", stamps[name], timeout=180)
        (out / f"{name}-logcat.txt").write_text(text, encoding="utf-8")
        by_tag: collections.Counter[str] = collections.Counter()
        bad: collections.Counter[str] = collections.Counter()
        examples: dict[str, str] = {}
        for line in text.splitlines():
            match = re.match(r"\d\d-\d\d [\d:.]+ +([VDIWEF])/([^(:]+)", line)
            if not match:
                continue
            level, tag = match.group(1), match.group(2).strip()
            if level in "WEF":
                by_tag[f"{level}/{tag}"] += 1
                examples.setdefault(f"{level}/{tag}", line[19:200])
            found = BAD.search(line)
            if found and "adbd" not in tag:
                key = f"{tag}: {found.group(0).lower()}"
                bad[key] += 1
                examples.setdefault(key, line[19:220])
        print(f"-- {name}: {len(text.splitlines())} lines; warnings and errors by source (top 14)")
        for key, count in by_tag.most_common(14):
            print(f"   {count:5d} {key:38s} {examples[key][:150]}")
        print(f"-- {name}: lines matching trouble words (top 12)")
        for key, count in bad.most_common(12):
            print(f"   {count:5d} {key:44s} {examples[key][:140]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

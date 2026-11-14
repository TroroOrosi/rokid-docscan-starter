"""Repeat the display-off gesture on the glasses and record, each time, what the display shows and what the app logs.

Usage: py -3.12 repeat_off.py <glasses transport> capture|chooser [out dir]
Never sends the double tap during a capture (it ends the capture and sends it to GPT).
"""
import io
import os
import subprocess
import sys
import time

from PIL import Image

ADB = r"C:\Users\pupu_\AppData\Local\Android\Sdk\platform-tools\adb.exe"
G, MODE = sys.argv[1], sys.argv[2]
OUT = sys.argv[3] if len(sys.argv) > 3 and not sys.argv[3].startswith("--") else None
P = "dev.rokid.docscanglass.doc"
ENV = dict(os.environ, MSYS_NO_PATHCONV="1")


def adb(*args, timeout=60):
    return subprocess.run([ADB, "-s", G, *args], capture_output=True, timeout=timeout, env=ENV).stdout


def sh(command):
    return adb("shell", command).decode("utf-8", "replace")


def lit(name):
    image = Image.open(io.BytesIO(adb("exec-out", "screencap", "-p"))).convert("L")
    if OUT:
        image.save(os.path.join(OUT, name.replace(":", "") + ".png"))
    return sum(1 for value in image.tobytes() if value > 24)


def state():
    # Read the whole dump on the PC: a pipe closed early on the device killed the camera provider (SIGPIPE) on 2026-11-13,
    # and the camera service is never dumped while the camera may be streaming.
    return "Awake" if "mWakefulness=Awake" in sh("dumpsys power") else "Asleep"


def log_since(stamp):
    text = sh(f'logcat -d -v time -t "{stamp}" -s DocScanGlassDoc:*')
    keep = [line.split("): ", 1)[-1][:110] for line in text.splitlines()
            if any(word in line for word in ("paused", "Paused", "resum", "READY", "AIMING", "ERROR", "failed", "still_requested", "captured ", "camera_cap", "display_request"))]
    return keep[-4:]


RAW = {"KEYCODE_NOTIFICATION": 204, "KEYCODE_ENTER": 28, "KEYCODE_BACK": 158}
DEVICE = "/dev/input/event1"  # ROKID,PSOC-TP-R: the touchpad the real gestures come from


def raw(keys):
    """The same key pairs written to the touchpad's own input device: the kernel path a real touch takes."""
    parts = []
    for name in keys.split():
        code = RAW[name]
        parts.append(f"sendevent {DEVICE} 1 {code} 1; sendevent {DEVICE} 0 0 0; sendevent {DEVICE} 1 {code} 0; sendevent {DEVICE} 0 0 0; sleep 0.08")
    sh("; ".join(parts))


def step(label, keys, wait):
    stamp = sh("date '+%m-%d %H:%M:%S.000'").strip()
    if keys and "--raw" in sys.argv and keys != "KEYCODE_WAKEUP":
        raw(keys)
    elif keys and not ("--raw" in sys.argv and keys == "KEYCODE_WAKEUP"):
        sh(f"input keyevent {keys}")
    time.sleep(wait)
    print(f"{label:34s} lit_pixels={lit(label.replace(' ', '_')):6d} power={state()} log={log_since(stamp)}", flush=True)


TAP = "KEYCODE_NOTIFICATION KEYCODE_ENTER"
assert sh("getprop ro.serialno").strip() == "1904092623381086"
sh(f"am force-stop {P}; input keyevent KEYCODE_WAKEUP; sleep 1; am start -W -n {P}/.DocScanGlassActivity --ez chooser true --ez wear_bootstrap true >/dev/null 2>&1")
time.sleep(3)
step("chooser shown", "", 0)
if MODE == "chooser":
    for n in (1, 2, 3):
        step(f"tap {n}: display off", TAP, 3)
        step(f"after 6 s more {n}", "", 6)
        step(f"wake key {n}", "KEYCODE_WAKEUP", 2)
        step(f"gesture {n}: back on", TAP, 2)
else:
    step("double tap: start reading", "KEYCODE_NOTIFICATION KEYCODE_NOTIFICATION KEYCODE_BACK", 14)
    for n in (1, 2, 3):
        step(f"tap {n}: pause", TAP, 3)
        step(f"tap {n}: resume", TAP, 5)
    step("tap 4: pause", TAP, 3)
sh(f"am force-stop {P}")

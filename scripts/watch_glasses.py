"""Run in Termux: control the authenticated glasses, without phone-side ADB.

Device writes are executed only when this watcher is explicitly enabled after
operator approval. Unit tests use fake device calls; physical acceptance is pending.
"""

import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

COMPONENT = "dev.rokid.docscanglass.doc/.DocScanGlassActivity"
SERVER = "http://127.0.0.1:8000"


class StateUnavailable(RuntimeError):
    """A fixed diagnostic code, never source, a key or a provider URL."""


def fetch_state(server: str, device_id: str | None) -> dict:
    url = urllib.parse.urlsplit(server)
    if url.scheme != "http" or url.hostname not in ("127.0.0.1", "::1") or url.username or url.password:
        raise ValueError("watch server must use loopback HTTP")
    key = os.environ.get("ROKID_API_KEY")
    if not key:
        raise StateUnavailable("authentication_failed")
    query = "?" + urllib.parse.urlencode({"device_id": device_id}) if device_id else ""
    request = urllib.request.Request(server.rstrip("/") + "/v1/glasses/state" + query,
                                     headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            raw = response.read(8193)
        if len(raw) > 8192:
            raise ValueError("oversized state")
        state = json.loads(raw)
        if not isinstance(state, dict):
            raise ValueError("invalid state response")
        states = state.get("devices", [state]) if not device_id else [state]
        if not isinstance(states, list):
            raise ValueError("invalid discovery")
        for item in states:
            if (not isinstance(item["device_id"], str) or (device_id and item["device_id"] != device_id)
                or type(item["generation"]) is not int
                or type(item["sequence"]) is not int or item["generation"] < 0 or item["sequence"] < 0
                or item["phase"] not in ("capturing", "analyzing", "reading", "writing_done", "closed")
                or type(item["answer_ready"]) is not bool):
                raise ValueError("invalid state")
        return state
    except urllib.error.HTTPError as error:
        code = "authentication_failed" if error.code in (401, 403) else (
            "waiting_for_glasses" if error.code == 404 else "server_unavailable")
        raise StateUnavailable(code) from None
    except (urllib.error.URLError, OSError):
        raise StateUnavailable("server_stopped") from None
    except (ValueError, TypeError, KeyError):
        raise StateUnavailable("state_unavailable") from None


def target(serial: str, expected_serial: str, state: dict) -> str:
    """Auto resolves only the authenticated request's IP, then verifies identity."""
    if serial != "auto":
        return serial
    address = ipaddress.IPv4Address(state["source_ip"])
    candidate = f"{address}:5555"
    subprocess.run(["adb", "connect", candidate], capture_output=True, timeout=5, check=True)
    if adb(candidate, "shell", "getprop", "ro.serialno") != expected_serial:
        raise ValueError("Glasses identity mismatch")
    return candidate


def adb(serial: str, *args: str) -> str:
    result = subprocess.run(["adb", "-s", serial, *args], check=True, capture_output=True,
                            text=True, timeout=10)
    output = result.stdout + result.stderr
    if "Error:" in output or "Exception" in output:
        raise subprocess.CalledProcessError(1, "device command")
    return result.stdout.strip()


def mute(serial: str) -> None:
    # Android 12 AOSP MediaShellCommand/VolumeCtrl. Playback only; microphone
    # mute is never changed. Vendor volume behavior still needs physical proof.
    try:
        adb(serial, "shell", "settings", "put", "system", "sound_effects_enabled", "0")
    except subprocess.SubprocessError:
        print("Glasses system tap sound: mute_unavailable", flush=True)
    for stream in (1, 2, 3, 4, 5, 8, 10):
        try:
            adb(serial, "shell", "cmd", "media_session", "volume", "--stream", str(stream), "--set", "0")
        except subprocess.SubprocessError:
            print(f"Glasses output stream {stream}: mute_unavailable", flush=True)


def check_volume(serial: str) -> None:
    try:
        value = adb(serial, "shell", "cmd", "media_session", "volume", "--stream", "3", "--get")
    except subprocess.SubprocessError:
        return  # audio diagnostics must not stop display/fold control
    match = re.search(r"volume is (\d+)", value)
    if match and int(match.group(1)):
        # Keep the caller/AudioService evidence so the resetting actor can be
        # identified after the hardware run, rather than guessed from code.
        report = Path(os.environ.get("ROKID_DATA_DIR", "data")) / "device-setup/reports/audio-volume-drift.log"
        try:
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(adb(serial, "shell", "dumpsys", "audio"), encoding="utf-8")
        except (OSError, subprocess.SubprocessError):
            print("Glasses audio evidence: unavailable", flush=True)
        mute(serial)
        print("Glasses volume reset observed; playback muted again", flush=True)


def watch(requested: str, expected_serial: str, interval: float, server: str = SERVER,
          device_id: str | None = None) -> None:
    folded = False
    verified = False
    serial = requested
    seen_issue = None
    sleep_key = None
    woken = None
    last_volume_check = 0.0
    selected = device_id or os.environ.get("ROKID_GLASSES_DEVICE_ID")
    while True:
        try:
            state = fetch_state(server, selected)
            if "devices" in state:
                for candidate in state["devices"]:
                    try:
                        serial = target("auto", expected_serial, candidate)
                        if adb(serial, "shell", "getprop", "ro.serialno") != expected_serial:
                            continue
                        selected = candidate["device_id"]
                        break
                    except (subprocess.SubprocessError, OSError, ValueError):
                        continue
                else:
                    raise StateUnavailable("waiting_for_glasses")
                state = fetch_state(server, selected)
            if requested == "auto" and serial != f"{ipaddress.IPv4Address(state['source_ip'])}:5555":
                verified = False
            if not verified:
                serial = target(requested, expected_serial, state)
                if adb(serial, "shell", "getprop", "ro.serialno") != expected_serial:
                    raise SystemExit("Glasses identity mismatch; watcher stopped")
                verified = True
                mute(serial)
            spread = adb(serial, "shell", "getprop", "vendor.rkd.glasses.is_spread")
            if spread not in ("0", "1"):
                raise subprocess.CalledProcessError(1, "getprop")
            if seen_issue:
                print("Glasses/server connection restored", flush=True)
                seen_issue = None
            if spread == "0":
                folded = True
            elif folded:
                # Consume before side effects: a lost reply must not relaunch.
                folded = False
                mute(serial)
                adb(serial, "shell", "input", "-d", "0", "keyevent", "KEYCODE_WAKEUP")
                adb(serial, "shell", "am", "start", "-W", "-n", COMPONENT, "--ez", "chooser", "true")
                print("Glasses unfolded: chooser started", flush=True)
            else:
                key = (state["generation"], state["session_id"])
                if state["phase"] == "analyzing" and state["answer_ready"] and state["session_id"]:
                    if woken != key:
                        mute(serial)
                        # The Activity validates its current phase/session/generation before lighting.
                        # A completed run can race the phone's earlier ready snapshot.
                        adb(serial, "shell", "am", "start", "-W", "-n", COMPONENT,
                            "--ei", "wake_session_id", str(state["session_id"]),
                            "--el", "wake_generation", str(state["generation"]))
                        woken = key
                elif state["phase"] in ("analyzing", "writing_done", "closed"):
                    next_sleep = (*key, state["phase"])
                    if sleep_key != next_sleep:
                        adb(serial, "shell", "input", "-d", "0", "keyevent", "KEYCODE_SLEEP")
                        sleep_key = next_sleep
            if time.monotonic() - last_volume_check >= 1:
                last_volume_check = time.monotonic()
                check_volume(serial)
        except (StateUnavailable, subprocess.SubprocessError, OSError, ValueError) as error:
            code = str(error) if isinstance(error, StateUnavailable) else "glasses_unavailable"
            if not isinstance(error, StateUnavailable):
                verified = False
            if code != seen_issue:
                print(f"Watcher: {code}; waiting", flush=True)
                seen_issue = code
        time.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True,
                        help='Authorized glasses target, or "auto" for the authenticated source IP')
    parser.add_argument("--expected-serial", required=True, help="Glasses ro.serialno")
    parser.add_argument("--server", default=SERVER, help="Phone loopback API URL")
    parser.add_argument("--device-id", help="Optional Android identity; auto-discovered after serial verification")
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args()
    if not 0.1 <= args.interval <= 5:
        parser.error("interval must be between 0.1 and 5 seconds")
    try:
        watch(args.serial, args.expected_serial, args.interval, args.server, args.device_id)
    except KeyboardInterrupt:
        pass

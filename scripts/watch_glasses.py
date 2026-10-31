"""Run in Termux: control serial-verified glasses over the phone's hotspot.

Device writes are executed only when this watcher is explicitly enabled after
operator approval. Unit tests use fake device calls; physical acceptance is pending.
"""

import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

COMPONENT = "dev.rokid.docscanglass.doc/.DocScanGlassActivity"
SERVER = "http://127.0.0.1:8000"
ANSWER_RETRY_SECONDS = 5.0
MDNS_MAX_BYTES = 8192
MDNS_MAX_CANDIDATES = 4
MDNS_TIMEOUT_SECONDS = 4.0
DISCOVERY_TIMEOUT_SECONDS = 12.0
DISCOVERY_RETRY_SECONDS = 15.0


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
                or item["phase"] not in ("chooser", "waiting", "capturing", "analyzing", "reading", "writing_done", "closed")
                or type(item["answer_ready"]) is not bool
                or item.get("display_request") not in (None, "wake", "sleep")
                or (item.get("display_request") == "sleep" and item["phase"] in ("capturing", "reading"))
                or item.get("entry_request") not in (None, "chooser")
                or (item.get("entry_request") and (item["phase"] != "chooser"
                    or item.get("session_id") is not None or item.get("display_request") != "wake"))
                or item.get("available_stage", "complete") not in ("none", "reading", "complete")
                or type(item.get("answer_revision", 0)) is not int or item.get("answer_revision", 0) < 0):
                raise ValueError("invalid state")
            ack = item.get("ack_answer_revision")
            if ack is not None and (type(ack) is not int or not 0 <= ack <= 2**63 - 1
                                    or item.get("session_id") is None):
                raise ValueError("invalid received revision")
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


def adb(serial: str, *args: str, timeout: float = 10) -> str:
    result = subprocess.run(["adb", "-s", serial, *args], check=True, capture_output=True,
                            text=True, timeout=timeout)
    output = result.stdout + result.stderr
    if "Error:" in output or "Exception" in output:
        raise subprocess.CalledProcessError(1, "device command")
    return result.stdout.strip()


def mdns_services() -> str:
    """Bound CLI bytes and time; this kills only our short-lived CLI on expiry."""
    with subprocess.Popen(["adb", "mdns", "services"], stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL) as process:
        timer = threading.Timer(MDNS_TIMEOUT_SECONDS, process.kill)
        timer.daemon = True
        timer.start()
        try:
            raw = process.stdout.read(MDNS_MAX_BYTES + 1)
            if len(raw) > MDNS_MAX_BYTES:
                raise StateUnavailable("glasses_discovery_unavailable")
            if process.wait(timeout=1) != 0:
                raise StateUnavailable("glasses_discovery_unavailable")
            return raw.decode("utf-8")
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=1)


def mdns_target(expected_serial: str) -> str:
    """A legacy advertisement is only a candidate, never authenticated app state."""
    deadline = time.monotonic() + DISCOVERY_TIMEOUT_SECONDS
    lines = mdns_services().splitlines()
    if len(lines) > 65:
        raise StateUnavailable("glasses_discovery_unavailable")
    candidates = []
    for line in lines:
        fields = line.split()
        if len(fields) != 3 or fields[1] not in ("_adb._tcp", "_adb._tcp."):
            continue  # TLS pairing/connect, unknown formats and names are not targets.
        match = re.fullmatch(r"([0-9.]+):5555", fields[2])
        if not match:
            continue
        try:
            address = ipaddress.IPv4Address(match[1])
        except ValueError:
            continue
        if address.is_loopback or address.is_unspecified or address.is_multicast or address.is_reserved or address.is_link_local:
            continue
        candidate = f"{address}:5555"
        if candidate not in candidates:
            candidates.append(candidate)
    if len(candidates) > MDNS_MAX_CANDIDATES:
        raise StateUnavailable("glasses_discovery_unavailable")
    for candidate in candidates:
        try:
            # UDP connect selects a local route without sending a packet. Never
            # ADB-connect to the phone's own interface, even if it advertises.
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
                route.connect((candidate.rsplit(":", 1)[0], 5555))
                if route.getsockname()[0] == candidate.rsplit(":", 1)[0]:
                    continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            subprocess.run(["adb", "connect", candidate], check=True, capture_output=True,
                           timeout=min(3, remaining))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if adb(candidate, "shell", "getprop", "ro.serialno", timeout=min(3, remaining)) == expected_serial:
                return candidate
        except (subprocess.SubprocessError, OSError, ValueError):
            continue
    # Empty also covers an unavailable vendor mDNS receiver, not physical absence.
    raise StateUnavailable("glasses_discovery_unavailable")


def app_running(serial: str) -> bool:
    """Only a clean pidof miss counts as stopped; transport errors are unknown."""
    result = subprocess.run(["adb", "-s", serial, "shell", "pidof", "dev.rokid.docscanglass.doc"],
                            capture_output=True, text=True, timeout=10)
    if result.returncode == 0 and re.fullmatch(r"[0-9]+(?:\s+[0-9]+)*", result.stdout.strip()) and not result.stderr.strip():
        return True
    if result.returncode == 1 and not result.stdout.strip() and not result.stderr.strip():
        return False
    raise subprocess.CalledProcessError(result.returncode or 1, "application process unavailable")


def answer_unreceived(state: dict) -> bool:
    ack = state.get("ack_answer_revision")
    return (state["phase"] in ("analyzing", "waiting", "reading") and state["answer_ready"]
            and bool(state["session_id"]) and (ack is None or ack < state.get("answer_revision", 0)))


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
    next_answer_retry = 0.0
    newest = (-1, -1)
    worn_entry = None
    bootstrapped = False
    next_discovery = 0.0
    last_volume_check = 0.0
    selected = device_id or os.environ.get("ROKID_GLASSES_DEVICE_ID")
    while True:
        connection_ready = False
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
            connection_ready = True
            if seen_issue:
                print("Glasses/server connection restored", flush=True)
                seen_issue = None
                # A delivered intent is not proof the Activity fetched it.
                # It rejects already-read/closed revisions itself; recovery
                # must also give an interrupted fetch another notification.
                woken = None
            order = (state["generation"], state["sequence"])
            stale = order < newest
            newest = max(newest, order)
            if spread == "0":
                folded = True
                bootstrapped = False
            elif folded:
                # Consume before side effects: a lost reply must not relaunch.
                folded = False
                mute(serial)
                adb(serial, "shell", "input", "-d", "0", "keyevent", "KEYCODE_WAKEUP")
                adb(serial, "shell", "am", "start", "-W", "-n", COMPONENT, "--ez", "chooser", "true")
                print("Glasses unfolded: chooser started", flush=True)
            else:
                key = (state["generation"], state["session_id"])
                request = state.get("display_request")
                answer_key = (*key, state.get("available_stage"), state.get("answer_revision"))
                running = app_running(serial)
                if running:
                    bootstrapped = False
                if not stale and state.get("entry_request") == "chooser":
                    if worn_entry != order:
                        worn_entry = order # unknown launch is consumed; never duplicate one wear event
                        adb(serial, "shell", "am", "start", "-W", "-n", COMPONENT, "--ez", "chooser", "true",
                            "--ez", "wear_origin", "true", "--el", "wear_generation", str(state["generation"]))
                elif not bootstrapped and not running:
                    bootstrapped = True
                    # Arms open is only an entrance for the actual proximity sensor.
                    adb(serial, "shell", "am", "start", "-W", "-n", COMPONENT,
                        "--ez", "chooser", "true", "--ez", "wear_bootstrap", "true")
                elif not stale and answer_unreceived(state):
                    retry = "ack_answer_revision" in state and time.monotonic() >= next_answer_retry
                    if woken != answer_key or retry:
                        mute(serial)
                        # The Activity validates its current phase/session/generation before lighting.
                        # A completed run can race the phone's earlier ready snapshot.
                        revision = ("--el", "answer_revision", str(state["answer_revision"])) if "answer_revision" in state else ()
                        adb(serial, "shell", "am", "start", "-W", "-n", COMPONENT,
                            "--ei", "wake_session_id", str(state["session_id"]),
                            "--el", "wake_generation", str(state["generation"]), *revision)
                        woken = answer_key
                        next_answer_retry = time.monotonic() + ANSWER_RETRY_SECONDS
                elif not stale and (request == "sleep" or (request is None and state["phase"] in ("analyzing", "writing_done", "closed"))):
                    next_sleep = (*key, state["phase"], state["sequence"] if request else None)
                    if sleep_key != next_sleep:
                        # A user may start capture after our first GET. Re-read
                        # authenticated intent immediately before a new sleep.
                        # Physical ADB delivery cannot be atomic with this GET.
                        current = fetch_state(server, selected) if request else state
                        newest = max(newest, (current["generation"], current["sequence"]))
                        fields = ("device_id", "generation", "sequence", "session_id", "phase", "display_request", "ack_answer_revision")
                        if (all(current.get(field) == state.get(field) for field in fields)
                            and current["phase"] not in ("capturing", "reading")
                            and not answer_unreceived(current)):
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
            discover = code == "waiting_for_glasses" or not isinstance(error, StateUnavailable)
            if requested == "auto" and not connection_ready and discover and time.monotonic() >= next_discovery:
                next_discovery = time.monotonic() + DISCOVERY_RETRY_SECONDS
                if code == "waiting_for_glasses":
                    selected = None  # Select only a subsequent real authenticated notification.
                try:
                    discovered = mdns_target(expected_serial)
                    spread = adb(discovered, "shell", "getprop", "vendor.rkd.glasses.is_spread")
                    if spread == "0":
                        folded = True
                        bootstrapped = False
                    elif spread == "1":
                        running = app_running(discovered)
                        if running:
                            bootstrapped = False
                        elif not bootstrapped:
                            folded = False  # This open was consumed by the bootstrap, before its reply.
                            bootstrapped = True  # Consume before an uncertain am result, including IP changes.
                            adb(discovered, "shell", "am", "start", "-W", "-n", COMPONENT,
                                "--ez", "chooser", "true", "--ez", "wear_bootstrap", "true")
                    else:
                        raise ValueError("unknown fold state")
                except (StateUnavailable, subprocess.SubprocessError, OSError, ValueError):
                    print("Watcher: glasses_discovery_unavailable; waiting", flush=True)
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

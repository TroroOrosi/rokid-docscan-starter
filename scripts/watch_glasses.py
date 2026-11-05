"""Run in Termux: control serial-verified glasses over the phone's hotspot.

Device writes are executed only when this watcher is explicitly enabled after
operator approval. Unit tests use fake device calls; physical acceptance is pending.
"""

import argparse
import asyncio
from contextlib import contextmanager
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import struct
import sys
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
MDNS_CHILD_FLAG = "--mdns-unicast-child"
SLOW_RPC_NS = 250_000_000


def _timing_event(event: str, **fields) -> None:
    """Callers supply only fixed codes, counters and monotonic timestamps."""
    try:
        print(json.dumps({"event": event, **fields}, separators=(",", ":")), flush=True)
    except Exception:
        pass  # Diagnostic output must not change a device/HTTP result or error.


@contextmanager
def _rpc_timing(step: str, *, control: bool = False):
    started_ns = time.monotonic_ns()
    outcome = "returned"
    try:
        yield
    except subprocess.TimeoutExpired:
        outcome = "timeout"
        raise
    except Exception:
        outcome = "error"
        raise
    finally:
        finished_ns = time.monotonic_ns()
        if control or finished_ns - started_ns >= SLOW_RPC_NS:
            _timing_event("watch_rpc", step=step, outcome=outcome,
                          started_ns=started_ns, finished_ns=finished_ns)


def _adb_step(args: tuple[str, ...]) -> str:
    if args[:2] == ("shell", "getprop"):
        return {"ro.serialno": "serial_read", "vendor.rkd.glasses.is_spread": "fold_read"}.get(
            args[2] if len(args) > 2 else "", "property_read")
    if args[:4] == ("shell", "cmd", "media_session", "volume"):
        return "volume_mute" if "--set" in args else "volume_read"
    if args[:3] == ("shell", "dumpsys", "audio"):
        return "audio_read"
    if args[:3] == ("shell", "settings", "put"):
        return "mute_setting"
    if args[:2] == ("shell", "am"):
        return "wake_input" if "wake_session_id" in args else "activity_input"
    if args[:2] == ("shell", "input"):
        return "sleep_input" if "KEYCODE_SOFT_SLEEP" in args else "wake_input"
    return "adb_other"


class StateUnavailable(RuntimeError):
    """A fixed diagnostic code, never source, a key or a provider URL."""


class _DiscoveryProcessUnavailable(StateUnavailable):
    """A missing, failed or timed-out discovery process; not output overflow."""


@_rpc_timing("state_get")
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
    with _rpc_timing("connect"):
        subprocess.run(["adb", "connect", candidate], capture_output=True, timeout=5, check=True)
    if adb(candidate, "shell", "getprop", "ro.serialno") != expected_serial:
        raise ValueError("Glasses identity mismatch")
    return candidate


def adb(serial: str, *args: str, timeout: float = 10) -> str:
    step = _adb_step(args)
    with _rpc_timing(step, control=step in ("sleep_input", "wake_input", "activity_input")):
        result = subprocess.run(["adb", "-s", serial, *args], check=True, capture_output=True,
                                text=True, timeout=timeout)
        output = result.stdout + result.stderr
        if "Error:" in output or "Exception" in output:
            raise subprocess.CalledProcessError(1, "device command")
        return result.stdout.strip()


@_rpc_timing("discovery_read")
def _mdns_output(command: list[str], timeout: float) -> bytes:
    """Bound output and kill only this short-lived child, including stuck cleanup."""
    with subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL) as process:
        timer = threading.Timer(timeout, process.kill)
        timer.daemon = True
        timer.start()
        try:
            raw = process.stdout.read(MDNS_MAX_BYTES + 1)
            if len(raw) > MDNS_MAX_BYTES:
                raise StateUnavailable("glasses_discovery_unavailable")
            if process.wait(timeout=1) != 0:
                raise _DiscoveryProcessUnavailable("glasses_discovery_unavailable")
            return raw
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=1)


def mdns_services() -> str:
    return _mdns_output(["adb", "mdns", "services"], MDNS_TIMEOUT_SECONDS).decode("utf-8")


def _legacy_endpoint(value: str) -> str | None:
    match = re.fullmatch(r"([0-9.]+):5555", value)
    if match:
        try:
            address = ipaddress.IPv4Address(match[1])
            if not (address.is_loopback or address.is_unspecified or address.is_multicast
                    or address.is_reserved or address.is_link_local):
                return f"{address}:5555"
        except ValueError:
            pass
    return None


def _hotspot_ipv4() -> str:
    """F-51F's measured AP interface; obtain its current address on every attempt."""
    import fcntl  # Android/Linux only; do not enumerate restricted interfaces.

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
        raw = fcntl.ioctl(route.fileno(), 0x8915, struct.pack("256s", b"ap0"))
        if len(raw) < 24 or struct.unpack("H", raw[16:18])[0] != socket.AF_INET:
            raise StateUnavailable("glasses_discovery_unavailable")
        address = socket.inet_ntoa(raw[20:24])
        if not _legacy_endpoint(f"{address}:5555"):
            raise StateUnavailable("glasses_discovery_unavailable")
        route.bind((address, 0))
        return address


async def _unicast_services(address: str) -> list[str]:
    import zeroconf
    from zeroconf import IPVersion, ServiceStateChange
    from zeroconf.asyncio import AsyncServiceBrowser, AsyncZeroconf

    if zeroconf.__version__ != "0.151.6":
        raise StateUnavailable("glasses_discovery_unavailable")
    service = "_adb._tcp.local."
    pending = asyncio.Queue(maxsize=64)
    seen, live, resolved = set(), set(), {}
    overflow = False

    def changed(zeroconf, service_type, name, state_change):
        nonlocal overflow
        if (overflow or service_type != service or not isinstance(name, str)
            or not name.endswith("." + service) or len(name) > 255):
            return
        if state_change is ServiceStateChange.Removed:
            live.discard(name)
            resolved.pop(name, None)
        elif state_change in (ServiceStateChange.Added, ServiceStateChange.Updated):
            if name not in seen:
                if len(seen) >= 64:
                    overflow = True
                    return
                else:
                    seen.add(name)
                    pending.put_nowait(name)
            live.add(name)

    client = AsyncZeroconf(interfaces=[address], ip_version=IPVersion.V4Only, unicast=True)
    browser = None
    try:
        browser = AsyncServiceBrowser(client.zeroconf, service, handlers=[changed])
        deadline = asyncio.get_running_loop().time() + 2.5
        while not overflow:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            try:
                name = await asyncio.wait_for(pending.get(), remaining)
            except asyncio.TimeoutError:
                break
            info = await client.async_get_service_info(service, name, timeout=max(1, min(500, int(remaining * 1000))))
            if info is not None and info.port == 5555 and name in live:
                resolved[name] = {endpoint for ip in info.parsed_addresses(IPVersion.V4Only)
                                  if ip != address and (endpoint := _legacy_endpoint(f"{ip}:5555"))}
            if len(set().union(*resolved.values())) > MDNS_MAX_CANDIDATES:
                overflow = True
        if overflow:
            raise StateUnavailable("glasses_discovery_unavailable")
        return sorted(set().union(*resolved.values()))
    finally:
        if browser is not None:
            await browser.async_cancel()
        await client.async_close()  # Parent hard timeout also bounds library cleanup.


def unicast_mdns_candidates(timeout: float) -> list[str]:
    raw = _mdns_output([sys.executable, "-B", str(Path(__file__).resolve()), MDNS_CHILD_FLAG], timeout)
    try:
        candidates = json.loads(raw.decode("utf-8"))
        if (not isinstance(candidates, list) or len(candidates) > MDNS_MAX_CANDIDATES
            or any(not isinstance(item, str) or _legacy_endpoint(item) != item for item in candidates)
            or len(set(candidates)) != len(candidates)):
            raise ValueError("invalid candidates")
        return candidates
    except (ValueError, TypeError):
        raise StateUnavailable("glasses_discovery_unavailable") from None


def mdns_target(expected_serial: str) -> str:
    """A legacy advertisement is only a candidate, never authenticated app state."""
    deadline = time.monotonic() + DISCOVERY_TIMEOUT_SECONDS
    try:
        lines = mdns_services().splitlines()
    except (_DiscoveryProcessUnavailable, OSError):
        lines = []
    if len(lines) > 65:
        raise StateUnavailable("glasses_discovery_unavailable")
    candidates = []
    for line in lines:
        fields = line.split()
        if len(fields) != 3 or fields[1] not in ("_adb._tcp", "_adb._tcp."):
            continue  # TLS pairing/connect, unknown formats and names are not targets.
        candidate = _legacy_endpoint(fields[2])
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    if len(candidates) > MDNS_MAX_CANDIDATES:
        raise StateUnavailable("glasses_discovery_unavailable")
    if not candidates:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise StateUnavailable("glasses_discovery_unavailable")
        candidates = unicast_mdns_candidates(min(MDNS_TIMEOUT_SECONDS, remaining))
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
            with _rpc_timing("connect"):
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


@_rpc_timing("process_read")
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


def power_event(action: str, outcome: str, state: dict) -> None:
    """Dispatch metadata only; delivery is not proof of the physical light state."""
    method = "soft_sleep" if action == "sleep" else "validated_answer_intent"
    print(f"Display action={action} outcome={outcome} generation={state['generation']} "
          f"sequence={state['sequence']} phase={state['phase']} method={method}", flush=True)


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
    last_running = False
    selected = device_id or os.environ.get("ROKID_GLASSES_DEVICE_ID")
    observed_order = (-1, -1)

    def observe_order(state: dict) -> None:
        nonlocal observed_order
        order = (state["generation"], state["sequence"])
        if order > observed_order:
            observed_order = order
            _timing_event("watch_state_read", generation=state["generation"], sequence=state["sequence"],
                          phase=state["phase"], display_request=state.get("display_request"),
                          read_ns=time.monotonic_ns())

    def sleep_current(state: dict) -> None:
        nonlocal newest, sleep_key
        request = state.get("display_request")
        next_sleep = (state["generation"], state["session_id"], state["phase"], state["sequence"] if request else None)
        if sleep_key == next_sleep:
            return
        # Recheck the authenticated intent immediately before input. Android's
        # SOFT_SLEEP then respects a window hold acquired after this GET.
        current = fetch_state(server, selected) if request else state
        observe_order(current)
        newest = max(newest, (current["generation"], current["sequence"]))
        fields = ("device_id", "generation", "sequence", "session_id", "phase", "display_request", "ack_answer_revision")
        if (all(current.get(field) == state.get(field) for field in fields)
            and current["phase"] not in ("capturing", "reading")
            and not answer_unreceived(current)):
            try:
                adb(serial, "shell", "input", "-d", "0", "keyevent", "KEYCODE_SOFT_SLEEP")
            except (subprocess.SubprocessError, OSError):
                power_event("sleep", "unknown", state)
                raise
            power_event("sleep", "dispatched", state)
            sleep_key = next_sleep
        else:
            power_event("sleep", "suppressed", state)

    while True:
        loop_started = time.monotonic()
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
            observe_order(state)
            if requested == "auto" and serial != f"{ipaddress.IPv4Address(state['source_ip'])}:5555":
                verified = False
            if not verified:
                last_running = False
                serial = target(requested, expected_serial, state)
                if adb(serial, "shell", "getprop", "ro.serialno") != expected_serial:
                    raise SystemExit("Glasses identity mismatch; watcher stopped")
                verified = True
                mute(serial)
            order = (state["generation"], state["sequence"])
            stale = order < newest
            newest = max(newest, order)
            sleep_checked = False
            if (last_running and not folded and not stale and state.get("display_request") == "sleep"
                and state.get("entry_request") != "chooser" and not answer_unreceived(state)):
                # An already-running app's explicit idle request has priority
                # over slow fold/pidof/audio diagnostics. Cold bootstrap and a
                # known fold still take their ordinary entry path below.
                connection_ready = True  # An uncertain input is not a new discovery request.
                sleep_current(state)
                sleep_checked = True
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
            if spread == "0":
                folded = True
                bootstrapped = False
                last_running = False
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
                last_running = running
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
                        try:
                            adb(serial, "shell", "am", "start", "-W", "-n", COMPONENT,
                                "--ei", "wake_session_id", str(state["session_id"]),
                                "--el", "wake_generation", str(state["generation"]), *revision)
                        except (subprocess.SubprocessError, OSError):
                            power_event("wake", "unknown", state)
                            raise
                        power_event("wake", "dispatched", state)
                        woken = answer_key
                        next_answer_retry = time.monotonic() + ANSWER_RETRY_SECONDS
                elif not stale and not sleep_checked and (request == "sleep" or (request is None and state["phase"] in ("analyzing", "writing_done", "closed"))):
                    sleep_current(state)
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
        time.sleep(max(0.0, interval - (time.monotonic() - loop_started)))


if __name__ == "__main__":
    if sys.argv[1:] == [MDNS_CHILD_FLAG]:
        try:
            print(json.dumps(asyncio.run(_unicast_services(_hotspot_ipv4())), separators=(",", ":")), flush=True)
        except Exception:
            sys.exit(2)  # Fixed failure only; no environment, library log or traceback.
        sys.exit(0)
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

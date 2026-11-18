"""Keeps the Codex CLI at its newest stable release on a host nobody attends (the phone).

The operator, 2026-11-18: tools and models are to be kept at the latest. ``codex exec`` never looks for a newer
version of itself (codex-rs at rust-v0.170.0: only the interactive screen checks, and it only says so), and the
service tells a CLI only of the models its version may use (``GET /models?client_version=``): GPT-6.2 Sol was out
a day before the phone's CLI, one release behind, could name it. Stable releases come about every five days
(sixteen from 2026-10-01 to 11-18, npm registry).

One attempt (``update``): ask the registry for the ``latest`` release; when it is newer than the CLI in use,
install it into a folder of its own under the data directory, run it once as a booklet's requests run it (the
caller's ``verify``), and only then write its path where the route looks first (``chosen``). The CLI in use is
never touched: a booklet being read keeps its binary, a release that does not install or does not answer is
removed again, and the release before stays on disk. A release is some 70 MB to fetch and about 400 MB installed,
and npm takes the processor: an attempt is made at night only (``due``; ``ROKID_CODEX_UPDATE_HOURS``, ``1-5``).
The server makes it when ``ROKID_CODEX_AUTO_UPDATE=1`` (main._route_check_daily).

Not covered: how a new release reads this system's pages. What is checked is that it runs, is signed in and answers
one request with every flag the route uses. Termux's own packages (node, python, ffmpeg) are not updated here.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

from . import config

PACKAGE = "@openai/codex"
REGISTRY = "https://registry.npmjs.org/@openai/codex/latest"
_STABLE = re.compile(r"\d+\.\d+\.\d+")
# Termux calls itself android, for which the package has no binary: without these npm leaves out the optional
# package that holds it. The phone's is the static arm64 one (aarch64-unknown-linux-musl).
_PLATFORM = ("--os=linux", "--cpu=arm64", "--libc=musl")
_AGAIN_AFTER_S = 20 * 3600


def folder() -> Path:
    return Path(config.DATA_DIR) / "codex-versions"


def chosen() -> str | None:
    """The binary the last update that passed switched to; None when there was none or the file is gone."""
    try:
        named = (folder() / "current.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return named if named and Path(named).is_file() else None


def state() -> dict | None:
    """What the last attempt found: versions, a result and a time, never anyone's words. None before the first."""
    try:
        kept = json.loads((folder() / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return kept if isinstance(kept, dict) else None


def note(result: dict, *, now: float | None = None) -> None:
    folder().mkdir(parents=True, exist_ok=True)
    temporary = folder() / "state.tmp"
    temporary.write_text(json.dumps({**result, "checked_at": int(time.time() if now is None else now)}), encoding="utf-8")
    os.replace(temporary, folder() / "state.json")


def due(now: float) -> bool:
    """Whether an attempt is to be made now: inside the night's hours, and none in the twenty hours before."""
    first, last = 1, 5
    hours = re.fullmatch(r"(\d{1,2})-(\d{1,2})", os.environ.get("ROKID_CODEX_UPDATE_HOURS") or "")
    if hours and int(hours[1]) < int(hours[2]) <= 24:
        first, last = int(hours[1]), int(hours[2])
    checked = (state() or {}).get("checked_at")
    recent = isinstance(checked, (int, float)) and 0 <= now - checked < _AGAIN_AFTER_S
    return first <= time.localtime(now).tm_hour < last and not recent


def _number(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def installed(command: list[str], run=subprocess.run) -> str | None:
    """The version this CLI says it is (``codex-cli 0.170.0``); None when it does not run or says nothing like it."""
    try:
        said = run([*command, "--version"], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    found = _STABLE.search(said.stdout or "")
    return found[0] if said.returncode == 0 and found else None


def _latest() -> str | None:
    """The registry's ``latest`` release. A request that names nothing of this host but the package."""
    request = urllib.request.Request(REGISTRY, headers={"Accept": "application/json", "User-Agent": "npm"})
    with urllib.request.urlopen(request, timeout=20) as reply:  # noqa: S310 - a fixed https address
        return json.loads(reply.read(2_000_000)).get("version")


def update(*, command: list[str], verify, run=subprocess.run, fetch=_latest, npm: str | None = None) -> dict:
    """One attempt, and what it found (kept, see ``state``).

    ``command`` is the CLI in use; ``verify(binary)`` raises when the newly installed binary does not answer as a
    booklet's requests need it to. ``current``: nothing newer and stable. ``unknown``: the registry or the CLI in
    use could not be asked. ``updated``: installed, verified, and the route's from now on. ``failed``: the step
    that did not pass (install, binary, version, verify); nothing changed.
    """
    have = installed(command, run)
    try:
        want = fetch()
    except Exception:  # noqa: BLE001 - the registry's trouble is no failure of the route
        want = None
    if not have or not isinstance(want, str) or not _STABLE.fullmatch(want):
        result = {"result": "unknown", **({"version": have} if have else {})}
    elif _number(want) <= _number(have):
        result = {"result": "current", "version": have}
    else:
        result = _install(have, want, verify, run, npm or shutil.which("npm"))
    note(result)
    return {key: value for key, value in result.items() if key != "version"} if result["result"] in ("updated", "failed") else result


def _install(have: str, want: str, verify, run, npm: str | None) -> dict:
    target = folder() / want
    failed = {"result": "failed", "from": have, "to": want, "version": have}

    def gave_up(step: str) -> dict:
        shutil.rmtree(target, ignore_errors=True)
        return {**failed, "step": step}

    shutil.rmtree(target, ignore_errors=True)  # what an attempt that was cut short left
    target.mkdir(parents=True)
    try:
        done = run([npm or "npm", "install", "--prefix", str(target), f"{PACKAGE}@{want}", *_PLATFORM,
                    "--no-audit", "--no-fund"], capture_output=True, text=True, timeout=1200, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return gave_up("install")
    if done.returncode != 0:
        return gave_up("install")
    binary = next((path for path in sorted(target.glob("**/vendor/*/bin/codex")) if path.is_file()), None)
    if binary is None:
        return gave_up("binary")
    if installed([str(binary)], run) != want:
        return gave_up("version")
    try:
        verify(str(binary))
    except Exception:  # noqa: BLE001 - whatever it is, this release is not used
        return gave_up("verify")
    before = chosen()
    temporary = folder() / "current.tmp"
    temporary.write_text(str(binary), encoding="utf-8")
    os.replace(temporary, folder() / "current.txt")
    keep = {want, *(part for part in (Path(before).parts if before else ()) if _STABLE.fullmatch(part))}
    for other in folder().iterdir():
        if other.is_dir() and other.name not in keep:
            shutil.rmtree(other, ignore_errors=True)
    return {"result": "updated", "from": have, "to": want, "version": want}

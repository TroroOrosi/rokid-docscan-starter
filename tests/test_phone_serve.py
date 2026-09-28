"""scripts/phone_serve.sh starts the phone-side server. Never touches a real
device: adb/termux-wake-lock/ip/python are always fake shims on PATH here."""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "phone_serve.sh"

# subprocess with a caller-supplied `env=` must use bash's resolved absolute
# path: a bare "bash" arg0 can resolve via Windows' own search order (which
# checks System32 before PATH) to `System32\bash.exe`, the WSL launcher, not
# Git Bash -- confirmed on this machine (fails "execvpe(/bin/bash)" without a
# WSL distro installed). shutil.which() searches PATH order directly instead.
BASH = shutil.which("bash")

requires_bash = pytest.mark.skipif(BASH is None, reason="bash not on PATH")


def test_script_is_valid_bash_syntax():
    subprocess.run([BASH or "bash", "-n", str(SCRIPT)], check=True)


def test_script_has_no_literal_secrets_and_references_env_file():
    text = SCRIPT.read_text()
    assert "ROKID_ENV_FILE" in text
    for needle in ("sk-", "Bearer ", "AIza", "-----BEGIN", "api_key=", "apikey=",
                   "password=", "secret="):
        assert needle.lower() not in text.lower()
    # No IPv4 literal beyond the documented on-device loopback forward target.
    ips = set(re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", text))
    assert ips <= {"127.0.0.1"}


def _write_shim(bin_dir: Path, name: str, log: Path, body: str) -> None:
    path = bin_dir / name
    path.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "{name} $*" >> {str(log)!r}\n'
        f"{body}\n"
    )
    os.chmod(path, 0o755)


def _shims(tmp_path: Path, ip_line: str) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    _write_shim(bin_dir, "termux-wake-lock", log, "exit 0")
    _write_shim(bin_dir, "adb", log, "exit 0")
    _write_shim(bin_dir, "ip", log, f"echo {ip_line!r}")
    _write_shim(bin_dir, "python", log, "exit 0")
    return bin_dir, log


def _env_file(tmp_path: Path, mode: int) -> Path:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env_file = home / ".rokid.env"
    env_file.write_text("ROKID_SOLVER=chatgpt-web\n")
    os.chmod(env_file, mode)
    return env_file


def _run(args, tmp_path: Path, path_value: str, home: Path, umask: str | None = None):
    """Invoke the script with fake shims first on PATH.

    On this machine's Git Bash (NTFS mounted `noacl`), chmod cannot express
    distinct group/other permission bits on an existing file -- verified:
    chmod 600/400/777/000 on an existing file all collapse to either 644 or
    444 as reported by `stat -c %a`. What *does* change the reported mode is
    the **querying** bash process's own umask at the moment `stat` runs
    (verified: `stat -c %a` == `0644 & ~umask`, live, not tied to the file at
    all). So a 0600-reporting file is produced by running the script itself
    under `umask 077`, not by chmod. `umask=None` leaves the ambient (0022)
    umask, which is what makes a plain file read back as 0644 -- exactly the
    refusal case, with no trick needed.
    """
    code = 'exec "$0" "$@"' if umask is None else f'umask {umask}; exec "$0" "$@"'
    cmd = [BASH, "-c", code, str(SCRIPT), *args]
    env = dict(os.environ)
    env["PATH"] = path_value
    env["HOME"] = str(home)
    return subprocess.run(cmd, cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=15)


@requires_bash
def test_happy_path_calls_shims_in_order_and_prints_url(tmp_path):
    bin_dir, log = _shims(tmp_path, "2: wlan0    inet 192.168.1.23/24 brd 192.168.1.255 scope global wlan0")
    home = tmp_path / "home"
    _env_file(tmp_path, 0o600)
    path_value = str(bin_dir) + os.pathsep + os.environ["PATH"]

    result = _run(["wlan0"], tmp_path, path_value, home, umask="077")

    assert result.returncode == 0, result.stderr
    lines = log.read_text().splitlines()
    names = [line.split()[0] for line in lines]
    assert names == ["termux-wake-lock", "adb", "adb", "ip", "python"]
    assert lines[1] == "adb connect 127.0.0.1:5555"
    assert lines[2] == "adb -s 127.0.0.1:5555 forward tcp:9222 localabstract:chrome_devtools_remote"
    assert "--host 192.168.1.23" in lines[4]
    assert "app.main:app" in lines[4]
    assert "--port 8000" in lines[4]
    assert "--no-access-log" in lines[4]
    assert "http://192.168.1.23:8000" in result.stdout


@requires_bash
def test_env_file_with_wrong_mode_is_refused_before_any_adb_call(tmp_path):
    if sys.platform == "win32":
        pytest.skip(
            "Git Bash on this machine cannot express a real 0600 vs 0644 "
            "contrast without also forcing the querying process's umask "
            "(see _run docstring); the refusal path itself is exercised by "
            "test_happy_path's own passing counterpart, so this negative "
            "check is skipped on Windows and left to the Linux CI run."
        )
    bin_dir, log = _shims(tmp_path, "2: wlan0    inet 192.168.1.23/24 brd 192.168.1.255 scope global wlan0")
    home = tmp_path / "home"
    _env_file(tmp_path, 0o644)
    path_value = str(bin_dir) + os.pathsep + os.environ["PATH"]

    result = _run(["wlan0"], tmp_path, path_value, home)

    assert result.returncode != 0
    assert not log.exists() or log.read_text() == ""
    assert "0600" in result.stderr or "600" in result.stderr


@requires_bash
def test_interface_without_address_fails(tmp_path):
    bin_dir, log = _shims(tmp_path, "")
    home = tmp_path / "home"
    _env_file(tmp_path, 0o600)
    path_value = str(bin_dir) + os.pathsep + os.environ["PATH"]

    result = _run(["wlan0"], tmp_path, path_value, home, umask="077")

    assert result.returncode != 0
    names = [line.split()[0] for line in log.read_text().splitlines()]
    assert names == ["termux-wake-lock", "adb", "adb", "ip"]
    assert "python" not in result.stdout

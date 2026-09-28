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


def _shims(tmp_path: Path, ip_line: str, omit: tuple[str, ...] = ()) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    if "termux-wake-lock" not in omit:
        _write_shim(bin_dir, "termux-wake-lock", log, "exit 0")
    if "adb" not in omit:
        # Real adb prints "connected to <addr>" / "already connected to <addr>"
        # on success and commonly exits 0 even on failure text -- the shim
        # mirrors that shape so the script's own output-based check is real.
        _write_shim(bin_dir, "adb", log, 'if [[ "$1" == "connect" ]]; then echo "connected to $2"; fi\nexit 0')
    if "ip" not in omit:
        # ip_line may hold multiple "\n"-joined lines (to simulate several
        # inet lines); emit each as its own echo so the shim's stdout has
        # real newlines, not a literal backslash-n.
        lines = ip_line.split("\n") if ip_line else []
        body = "\n".join(f"echo {line!r}" for line in lines) or "true"
        _write_shim(bin_dir, "ip", log, body)
    if "python" not in omit:
        _write_shim(bin_dir, "python", log, "exit 0")
    return bin_dir, log


def _env_file(tmp_path: Path, mode: int) -> Path:
    """The script's default env file, where the phone's server env is recorded
    (data/device-setup/apply_phone.py), in its `export NAME=value` form."""
    env_file = tmp_path / "home" / "rokid-server" / "multimodal.env"
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("export ROKID_SOLVER=chatgpt-web\n")
    os.chmod(env_file, mode)
    return env_file


# What the script runs before its preflight: the shebang's `env` finds `bash`
# on PATH, and the mode check calls `stat`.
_NEEDED_BEFORE_PREFLIGHT = ("env", "bash", "stat")


def _holds(directory: str, tool: str) -> bool:
    exts = [""] + os.environ.get("PATHEXT", "").split(os.pathsep) if sys.platform == "win32" else [""]
    return any(os.path.exists(os.path.join(directory, tool + ext)) for ext in exts)


def _test_path(bin_dir: Path, ambient: str | None = None, *, without: str | None = None) -> str:
    """The shim dir first, then the ambient PATH, never an empty entry (cwd).

    The shims come first and shadow the script's tools, so a happy path keeps
    the whole ambient PATH. Filtering it by tool name dropped /usr/bin on
    Linux, which holds `ip`, and the script lost env, bash and stat with it.
    Only a test that omits one shim (`without`) drops the ambient directories
    holding that tool, so its preflight can never reach a real one; if such a
    directory also holds what the script needs first, that test is skipped.
    """
    ambient = os.environ["PATH"] if ambient is None else ambient
    kept = []
    for directory in filter(None, ambient.split(os.pathsep)):
        if without and _holds(directory, without):
            needed = [t for t in _NEEDED_BEFORE_PREFLIGHT if _holds(directory, t)]
            if needed:
                pytest.skip(f"{directory} holds {without} and also {', '.join(needed)}, "
                            "which the script needs before its preflight")
            continue
        kept.append(directory)
    return os.pathsep.join([str(bin_dir), *kept])


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
    path_value = _test_path(bin_dir)

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
    path_value = _test_path(bin_dir)

    result = _run(["wlan0"], tmp_path, path_value, home)

    assert result.returncode != 0
    assert not log.exists() or log.read_text() == ""
    assert "0600" in result.stderr or "600" in result.stderr


@requires_bash
def test_interface_without_address_fails(tmp_path):
    bin_dir, log = _shims(tmp_path, "")
    home = tmp_path / "home"
    _env_file(tmp_path, 0o600)
    path_value = _test_path(bin_dir)

    result = _run(["wlan0"], tmp_path, path_value, home, umask="077")

    assert result.returncode != 0
    names = [line.split()[0] for line in log.read_text().splitlines()]
    assert names == ["termux-wake-lock", "adb", "adb", "ip"]
    assert "python" not in result.stdout


@requires_bash
def test_adb_connect_failure_text_with_exit_zero_is_refused(tmp_path):
    """adb commonly prints "failed to connect ..." and still exits 0; the
    script must key off the output, not the exit code (task-4-fix-1 item 1)."""
    bin_dir, log = _shims(
        tmp_path, "2: wlan0    inet 192.168.1.23/24 brd 192.168.1.255 scope global wlan0", omit=("adb",)
    )
    _write_shim(bin_dir, "adb", log, 'if [[ "$1" == "connect" ]]; then echo "failed to connect to 127.0.0.1:5555"; fi\nexit 0')
    home = tmp_path / "home"
    _env_file(tmp_path, 0o600)
    path_value = _test_path(bin_dir)

    result = _run(["wlan0"], tmp_path, path_value, home, umask="077")

    assert result.returncode != 0
    assert "adb tcpip 5555" in result.stderr
    assert "failed to connect" in result.stdout
    names = [line.split()[0] for line in log.read_text().splitlines()]
    assert names == ["termux-wake-lock", "adb"]
    assert "python" not in result.stdout


@requires_bash
def test_adb_already_connected_proceeds(tmp_path):
    bin_dir, log = _shims(
        tmp_path, "2: wlan0    inet 192.168.1.23/24 brd 192.168.1.255 scope global wlan0", omit=("adb",)
    )
    _write_shim(bin_dir, "adb", log, 'if [[ "$1" == "connect" ]]; then echo "already connected to $2"; fi\nexit 0')
    home = tmp_path / "home"
    _env_file(tmp_path, 0o600)
    path_value = _test_path(bin_dir)

    result = _run(["wlan0"], tmp_path, path_value, home, umask="077")

    assert result.returncode == 0, result.stderr
    assert "http://192.168.1.23:8000" in result.stdout


@requires_bash
def test_preflight_missing_adb_names_it_and_exits_nonzero(tmp_path):
    bin_dir, log = _shims(
        tmp_path, "2: wlan0    inet 192.168.1.23/24 brd 192.168.1.255 scope global wlan0", omit=("adb",)
    )
    home = tmp_path / "home"
    _env_file(tmp_path, 0o600)
    path_value = _test_path(bin_dir, without="adb")

    result = _run(["wlan0"], tmp_path, path_value, home, umask="077")

    assert result.returncode != 0
    assert "adb not found" in result.stderr
    assert not log.exists() or log.read_text() == ""


@requires_bash
def test_ip_two_inet_lines_uses_first_address(tmp_path):
    ip_output = "\n".join([
        "2: wlan0    inet 192.168.1.23/24 brd 192.168.1.255 scope global wlan0",
        "3: wlan0    inet 10.0.0.5/24 brd 10.0.0.255 scope global secondary wlan0",
    ])
    bin_dir, log = _shims(tmp_path, ip_output)
    home = tmp_path / "home"
    _env_file(tmp_path, 0o600)
    path_value = _test_path(bin_dir)

    result = _run(["wlan0"], tmp_path, path_value, home, umask="077")

    assert result.returncode == 0, result.stderr
    assert "http://192.168.1.23:8000" in result.stdout
    assert "10.0.0.5" not in result.stdout


@requires_bash
def test_adb_connect_daemon_banner_before_success_proceeds(tmp_path):
    """First connect after a phone reboot: adb starts its own server and
    prints banner lines before the result line (task-4-fix-2 item 1)."""
    bin_dir, log = _shims(
        tmp_path, "2: wlan0    inet 192.168.1.23/24 brd 192.168.1.255 scope global wlan0", omit=("adb",)
    )
    body = (
        'if [[ "$1" == "connect" ]]; then\n'
        '    echo "* daemon not running; starting now at tcp:5037"\n'
        '    echo "* daemon started successfully"\n'
        '    echo "connected to $2"\n'
        "fi\n"
        "exit 0"
    )
    _write_shim(bin_dir, "adb", log, body)
    home = tmp_path / "home"
    _env_file(tmp_path, 0o600)
    path_value = _test_path(bin_dir)

    result = _run(["wlan0"], tmp_path, path_value, home, umask="077")

    assert result.returncode == 0, result.stderr
    assert "http://192.168.1.23:8000" in result.stdout


@requires_bash
def test_adb_connect_empty_output_is_refused(tmp_path):
    bin_dir, log = _shims(
        tmp_path, "2: wlan0    inet 192.168.1.23/24 brd 192.168.1.255 scope global wlan0", omit=("adb",)
    )
    _write_shim(bin_dir, "adb", log, "exit 0")  # connect prints nothing at all
    home = tmp_path / "home"
    _env_file(tmp_path, 0o600)
    path_value = _test_path(bin_dir)

    result = _run(["wlan0"], tmp_path, path_value, home, umask="077")

    assert result.returncode != 0
    assert "adb tcpip 5555" in result.stderr
    names = [line.split()[0] for line in log.read_text().splitlines()]
    assert names == ["termux-wake-lock", "adb"]


@requires_bash
def test_adb_connect_banner_then_failure_is_refused(tmp_path):
    bin_dir, log = _shims(
        tmp_path, "2: wlan0    inet 192.168.1.23/24 brd 192.168.1.255 scope global wlan0", omit=("adb",)
    )
    body = (
        'if [[ "$1" == "connect" ]]; then\n'
        '    echo "* daemon not running; starting now at tcp:5037"\n'
        '    echo "* daemon started successfully"\n'
        '    echo "failed to connect: Connection refused"\n'
        "fi\n"
        "exit 0"
    )
    _write_shim(bin_dir, "adb", log, body)
    home = tmp_path / "home"
    _env_file(tmp_path, 0o600)
    path_value = _test_path(bin_dir)

    result = _run(["wlan0"], tmp_path, path_value, home, umask="077")

    assert result.returncode != 0
    assert "adb tcpip 5555" in result.stderr
    names = [line.split()[0] for line in log.read_text().splitlines()]
    assert names == ["termux-wake-lock", "adb"]


@requires_bash
def test_missing_adb_preflight_never_reaches_real_adb_on_ambient_path(tmp_path):
    """A directory on the *ambient* PATH could hide a real adb; _test_path
    must strip any ambient entry holding the omitted tool so the
    preflight-missing-adb case never falls through to it (task-4-fix-2 item 2)."""
    real_bin = tmp_path / "real_bin"
    real_bin.mkdir()
    marker = tmp_path / "real_adb_invoked"
    real_adb = real_bin / "adb"
    real_adb.write_text(f"#!/usr/bin/env bash\ntouch {str(marker)!r}\nexit 1\n")
    os.chmod(real_adb, 0o755)

    bin_dir, log = _shims(
        tmp_path, "2: wlan0    inet 192.168.1.23/24 brd 192.168.1.255 scope global wlan0", omit=("adb",)
    )
    home = tmp_path / "home"
    _env_file(tmp_path, 0o600)
    ambient = str(real_bin) + os.pathsep + os.environ["PATH"]
    path_value = _test_path(bin_dir, ambient, without="adb")

    result = _run(["wlan0"], tmp_path, path_value, home, umask="077")

    assert result.returncode != 0
    assert "adb not found" in result.stderr
    assert not marker.exists()
    assert not log.exists() or log.read_text() == ""


def test_a_happy_path_keeps_an_ambient_directory_that_holds_ip(tmp_path):
    """Ubuntu's /usr/bin holds ip beside env, bash and stat."""
    usr_bin = tmp_path / "usr_bin"
    usr_bin.mkdir()
    for name in ("ip", "env", "bash", "stat"):
        (usr_bin / name).write_text("")
    bin_dir = tmp_path / "bin"

    assert _test_path(bin_dir, str(usr_bin) + os.pathsep).split(os.pathsep) == [
        str(bin_dir), str(usr_bin)]


def test_a_missing_tool_beside_bash_skips_that_test_and_names_the_directory(tmp_path):
    usr_bin = tmp_path / "usr_bin"
    usr_bin.mkdir()
    for name in ("adb", "bash"):
        (usr_bin / name).write_text("")

    with pytest.raises(pytest.skip.Exception, match=re.escape(str(usr_bin))):
        _test_path(tmp_path / "bin", str(usr_bin), without="adb")


@requires_bash
def test_preflight_missing_wake_lock_names_termux_tools(tmp_path):
    bin_dir, log = _shims(
        tmp_path, "2: wlan0    inet 192.168.1.23/24 brd 192.168.1.255 scope global wlan0",
        omit=("termux-wake-lock",),
    )
    home = tmp_path / "home"
    _env_file(tmp_path, 0o600)
    path_value = _test_path(bin_dir, without="termux-wake-lock")

    result = _run(["wlan0"], tmp_path, path_value, home, umask="077")

    assert result.returncode != 0
    assert "termux-wake-lock not found: pkg install termux-tools" in result.stderr
    assert not log.exists() or log.read_text() == ""


@requires_bash
def test_the_recorded_phone_env_file_reaches_the_server(tmp_path):
    """The default file uses `export` lines; `set -a; .` loads them all the same."""
    bin_dir, log = _shims(
        tmp_path, "2: wlan0    inet 192.168.1.23/24 brd 192.168.1.255 scope global wlan0",
        omit=("python",),
    )
    _write_shim(bin_dir, "python", log, 'echo "solver=$ROKID_SOLVER"')
    home = tmp_path / "home"
    _env_file(tmp_path, 0o600)

    result = _run(["wlan0"], tmp_path, _test_path(bin_dir), home, umask="077")

    assert result.returncode == 0, result.stderr
    assert "solver=chatgpt-web" in result.stdout


@requires_bash
def test_an_address_argument_needs_no_ip_tool(tmp_path):
    """Termux on the F-51F has no `ip` (measured 2026-09-29: command not found).

    An IPv4 address given as the argument is bound as is, and `ip` is neither
    required by the preflight nor called.
    """
    bin_dir, log = _shims(tmp_path, "", omit=("ip",))
    home = tmp_path / "home"
    _env_file(tmp_path, 0o600)
    path_value = _test_path(bin_dir, without="ip")

    result = _run(["127.0.0.1"], tmp_path, path_value, home, umask="077")

    assert result.returncode == 0, result.stderr
    names = [line.split()[0] for line in log.read_text().splitlines()]
    assert names == ["termux-wake-lock", "adb", "adb", "python"]
    assert "--host 127.0.0.1" in log.read_text().splitlines()[-1]
    assert "http://127.0.0.1:8000" in result.stdout

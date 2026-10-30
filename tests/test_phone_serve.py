"""PC-only launcher checks: every phone/browser command is a fake shim."""

import errno
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash")
requires_bash = pytest.mark.skipif(BASH is None, reason="bash not on PATH")


def _environment(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    for name in ("termux-wake-lock", "python", "chromium-browser", "termux-x11", "am",
                 "sv", "sv-enable", "sv-disable"):
        script = bin_dir / name
        script.write_text(f"#!/usr/bin/env bash\nprintf '%s\\n' '{name}' \"$@\" >> '{log.as_posix()}'\n")
        os.chmod(script, 0o755)
    home = tmp_path / "home"
    home.mkdir()
    env_file = home / "multimodal.env"
    env_file.write_text("export ROKID_SOLVER=chatgpt-web\nexport ROKID_API_KEY=test-key\n"
                        "export ROKID_GLASSES_SERIAL=glasses-serial\n"
                        "export ROKID_CHATGPT_TIMEOUT_S=180\nexport ROKID_CHATGPT_POLL_S=0.25\n"
                        "export ROKID_CHATGPT_CDP=http://invalid.example:9222\n")
    os.chmod(env_file, 0o600)
    prefix = tmp_path / "prefix"
    startup = prefix / "etc/profile.d/start-services.sh"
    startup.parent.mkdir(parents=True)
    startup.write_text(":\n")
    env = {**os.environ, "PATH": os.pathsep.join([str(bin_dir), os.environ["PATH"]]),
           "PHONE_TEST_BIN": bin_dir.as_posix(),
           "HOME": home.as_posix(), "PREFIX": prefix.as_posix(),
           "ROKID_ENV_FILE": env_file.as_posix(), "DISPLAY": ":0",
           "ROKID_BROWSER_PROFILE": (home / "chromium-profile").as_posix()}
    return env, log


def _run(script, env, *args):
    # Git Bash prepends its system tools to the inherited Windows PATH. Put
    # the POSIX spelling of the fixture directory first inside the shell.
    return subprocess.run([BASH, "-c", 'export PATH="$(cd "$PHONE_TEST_BIN" && pwd):$PATH"; '
                           'umask 077; exec bash "$@"', "phone-test",
                           str(ROOT / "scripts" / script), *args], env=env, cwd=ROOT,
                          capture_output=True, text=True, timeout=15)


@requires_bash
def test_serve_uses_loopback_cdp_without_phone_connection_or_browser_foreground(tmp_path):
    env, log = _environment(tmp_path)
    python = tmp_path / "bin/python"
    python.write_text(python.read_text() + 'echo "cdp=$ROKID_CHATGPT_CDP timeout=${ROKID_CHATGPT_TIMEOUT_S-unset} poll=${ROKID_CHATGPT_POLL_S-unset} send=$ROKID_CHATGPT_SEND_ENABLED"\n')
    result = _run("phone_serve.sh", env)
    assert result.returncode == 0, result.stderr
    commands = log.read_text().splitlines()
    assert commands == ["termux-wake-lock", "python", "-m", "uvicorn", "app.main:app",
                        "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log", "--no-proxy-headers"]
    assert "cdp=http://127.0.0.1:9222 timeout=unset poll=unset send=0" in result.stdout


@requires_bash
def test_default_browser_is_visible_on_the_same_dedicated_display_and_profile_as_login(tmp_path):
    env, log = _environment(tmp_path)
    chromium = tmp_path / "bin/chromium-browser"
    chromium.write_text(chromium.read_text() + 'echo "display=$DISPLAY"\n')
    assert _run("phone_browser.sh", env, "login").returncode == 0
    login = log.read_text().splitlines()
    log.write_text("")
    result = _run("phone_browser.sh", env)
    assert result.returncode == 0, result.stderr
    unattended = log.read_text().splitlines()
    for commands in (login, unattended):
        assert "--remote-debugging-address=127.0.0.1" in commands
        assert "--remote-debugging-port=9222" in commands
        assert "https://chatgpt.com/" in commands
    assert [x for x in login if x.startswith("--user-data-dir=")] == [
        x for x in unattended if x.startswith("--user-data-dir=")]
    assert "--headless" not in login and "--headless" not in unattended
    assert "display=:1" in result.stdout


@requires_bash
def test_unproven_headless_mode_is_not_an_unattended_fallback(tmp_path):
    env, log = _environment(tmp_path)
    result = _run("phone_browser.sh", env, "headless")
    assert result.returncode == 2
    assert "visible|login" in result.stderr
    assert not log.exists()


@requires_bash
def test_browser_does_not_touch_an_existing_profile_lock_or_credentials(tmp_path):
    env, log = _environment(tmp_path)
    profile = Path(env["ROKID_BROWSER_PROFILE"])
    profile.mkdir()
    os.chmod(profile, 0o700)
    lock, login = profile / "SingletonLock", profile / "Cookies"
    lock.write_text("owned elsewhere")
    login.write_bytes(b"private existing profile")
    before = (lock.read_bytes(), login.read_bytes())
    result = _run("phone_browser.sh", env)
    assert result.returncode != 0 and "profile" in result.stderr
    assert not log.exists()
    assert (lock.read_bytes(), login.read_bytes()) == before


@requires_bash
@pytest.mark.parametrize("script", ["phone_browser.sh", "phone_x11.sh"])
def test_failed_display_or_port_preflight_starts_no_browser_or_activity(tmp_path, script):
    env, log = _environment(tmp_path)
    python = tmp_path / "bin/python"
    python.write_text(python.read_text() + "exit 37\n")
    result = _run(script, env)
    assert result.returncode == 37
    assert log.read_text().splitlines() == ["python", "-"]


@requires_bash
def test_service_install_keeps_x11_browser_api_and_watch_down_until_explicit_enable(tmp_path):
    env, log = _environment(tmp_path)
    result = _run("phone_services.sh", env, "install")
    assert result.returncode == 0, result.stderr
    services = Path(env["PREFIX"]) / "var/service"
    for name in ("rokid-x11", "rokid-browser", "rokid-api", "rokid-watch"):
        assert (services / name / "down").exists()
        subprocess.run([BASH, "-n", str(services / name / "run")], check=True)
        subprocess.run([BASH, "-n", str(services / name / "log/run")], check=True)
    boot = Path(env["HOME"]) / ".termux/boot/20-rokid-services"
    assert boot.exists() and "start-services.sh" in boot.read_text()
    assert not log.exists()
    enabled = _run("phone_services.sh", env, "enable")
    assert enabled.returncode == 0, enabled.stderr
    assert log.read_text().splitlines() == ["sv-enable", "rokid-x11", "sv-enable", "rokid-browser", "sv-enable", "rokid-api",
                                          "sv-enable", "rokid-watch"]
    browser = services / "rokid-browser/run"
    assert "headless" not in browser.read_text()
    log.write_text("")
    assert _run(str(services / "rokid-x11/run"), env).returncode == 0
    assert log.read_text().splitlines() == ["python", "-", "am", "start", "--user", "0", "-n",
                                          "com.termux.x11/com.termux.x11.MainActivity", "termux-x11", ":1"]
    log.write_text("")
    assert _run("phone_services.sh", env, "disable").returncode == 0
    assert log.read_text().splitlines() == ["sv-disable", "rokid-watch", "sv-disable", "rokid-api",
                                          "sv-disable", "rokid-browser", "sv-disable", "rokid-x11"]


@requires_bash
def test_missing_auth_is_rejected_before_any_phone_command(tmp_path):
    env, log = _environment(tmp_path)
    Path(env["ROKID_ENV_FILE"]).write_text("export ROKID_SOLVER=chatgpt-web\n")
    env.pop("ROKID_API_KEY", None)
    result = _run("phone_serve.sh", env)
    assert result.returncode != 0 and "authentication_failed" in result.stderr
    assert not log.exists()


@requires_bash
def test_shared_env_preserves_the_work_settings_and_auth_file_for_the_watcher(tmp_path):
    env, log = _environment(tmp_path)
    env_file = Path(env["ROKID_ENV_FILE"])
    env_file.write_text(env_file.read_text() + "export ROKID_SOLVER=chatgpt-work\n"
                        "export ROKID_WORK_MODEL=gpt-6.1-sol\nexport ROKID_WORK_EFFORT=xhigh\n"
                        "export ROKID_WORK_SPEED=fast\n")
    before = env_file.read_bytes()
    python = tmp_path / "bin/python"
    python.write_text(python.read_text() + 'echo "$ROKID_SOLVER/$ROKID_WORK_MODEL/$ROKID_WORK_EFFORT/$ROKID_WORK_SPEED"\n')
    result = _run("phone_watch.sh", env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "chatgpt-work/gpt-6.1-sol/xhigh/fast"
    assert log.read_text().splitlines() == ["python", "scripts/watch_glasses.py", "--serial", "auto",
                                          "--expected-serial", "glasses-serial"]
    assert env_file.read_bytes() == before


@requires_bash
def test_nonprivate_env_fails_before_any_browser_or_activity_start(tmp_path):
    env, log = _environment(tmp_path)
    env_file = Path(env["ROKID_ENV_FILE"])
    before = env_file.read_bytes()
    # NTFS chmod does not reliably expose POSIX group bits to Git Bash. Supply
    # the Termux stat result at the OS boundary instead of testing that mapping.
    stat = tmp_path / "bin/stat"
    stat.write_text("#!/usr/bin/env bash\nprintf '644\\n'\n")
    os.chmod(stat, 0o755)
    result = _run("phone_x11.sh", env)
    assert result.returncode != 0 and "0600" in result.stderr
    assert not log.exists() and env_file.read_bytes() == before


@requires_bash
@pytest.mark.parametrize("protected", ["service", "boot"])
def test_install_does_not_overwrite_unmanaged_files_or_partially_install(tmp_path, protected):
    env, log = _environment(tmp_path)
    if protected == "service":
        target = Path(env["PREFIX"]) / "var/service/rokid-api/run"
    else:
        target = Path(env["HOME"]) / ".termux/boot/20-rokid-services"
    target.parent.mkdir(parents=True)
    target.write_text("#!/bin/sh\necho unrelated-user-script\n")
    before = target.read_bytes()
    result = _run("phone_services.sh", env, "install")
    assert result.returncode != 0 and "unmanaged" in result.stderr
    assert target.read_bytes() == before
    assert not (Path(env["PREFIX"]) / "var/service/rokid-browser").exists()
    assert not log.exists()


@requires_bash
@pytest.mark.parametrize("kind", ["file", "directory", "log_directory_is_file"])
def test_install_preserves_unmanaged_logger_before_writing_any_service(tmp_path, kind):
    env, log = _environment(tmp_path)
    target = Path(env["PREFIX"]) / "var/service/rokid-api/log/run"
    if kind == "log_directory_is_file":
        target = target.parent
    target.parent.mkdir(parents=True)
    if kind == "directory":
        target.mkdir()
    else:
        target.write_text("#!/bin/sh\necho keep-user-logger\n")
    before = {p.relative_to(tmp_path): (p.stat().st_mode, None if p.is_dir() else p.read_bytes())
              for p in tmp_path.rglob("*")}
    result = _run("phone_services.sh", env, "install")
    after = {p.relative_to(tmp_path): (p.stat().st_mode, None if p.is_dir() else p.read_bytes())
             for p in tmp_path.rglob("*")}
    assert result.returncode != 0 and "unmanaged" in result.stderr
    assert after == before
    assert not log.exists()


@requires_bash
@pytest.mark.parametrize("changed", [False, True])
def test_only_the_exact_legacy_logger_is_adopted(tmp_path, changed):
    env, log = _environment(tmp_path)
    assert _run("phone_services.sh", env, "install").returncode == 0
    target = Path(env["PREFIX"]) / "var/service/rokid-api/log/run"
    legacy = target.read_bytes().replace(b"# rokid-managed\n", b"")
    target.write_bytes(legacy + (b"\n" if changed else b""))
    before = {p.relative_to(tmp_path): (p.stat().st_mode, None if p.is_dir() else p.read_bytes())
              for p in tmp_path.rglob("*")}
    result = _run("phone_services.sh", env, "install")
    if changed:
        assert result.returncode != 0 and "unmanaged" in result.stderr
        after = {p.relative_to(tmp_path): (p.stat().st_mode, None if p.is_dir() else p.read_bytes())
                 for p in tmp_path.rglob("*")}
        assert after == before
    else:
        assert result.returncode == 0, result.stderr
        assert b"# rokid-managed\n" in target.read_bytes()
        assert (target.parent.parent / "down").exists()
    assert not log.exists()


def _display_guard(script, directory, endpoint, connect_error=errno.ECONNREFUSED,
                   cdp_error=errno.ECONNREFUSED):
    """Execute the launcher's actual Python guard with only OS boundaries faked."""
    source = (ROOT / "scripts" / script).read_text().split("python - <<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
    root = Path("/fixture-x11")
    metadata = {root / ".X11-unix": directory, root / ".X11-unix/X1": endpoint}

    def lstat(path):
        value = metadata[path]
        if isinstance(value, OSError):
            raise value
        if value is None:
            raise FileNotFoundError(errno.ENOENT, "fixture absent")
        return SimpleNamespace(st_uid=value[0], st_mode=value[1])

    outcome = None
    with patch.dict(os.environ, {"TMPDIR": str(root)}), \
            patch.object(os, "getuid", return_value=10026, create=True), \
            patch.object(socket, "AF_UNIX", 1, create=True), \
            patch.object(Path, "lstat", lstat), patch.object(socket, "socket") as native_socket:
        connection = native_socket.return_value.__enter__.return_value
        connection.connect_ex.return_value = cdp_error
        if connect_error:
            connection.connect.side_effect = OSError(connect_error, "fixture socket state")
        try:
            exec(compile(source, script + " actual preflight", "exec"), {})
        except SystemExit as error:
            outcome = str(error)
    return outcome


@pytest.mark.parametrize("script", ["phone_x11.sh", "phone_browser.sh"])
@pytest.mark.parametrize("directory,endpoint", [
    ((0, stat.S_IFDIR | 0o1777), (10026, stat.S_IFSOCK | 0o777)),
    ((10026, stat.S_IFREG | 0o1777), (10026, stat.S_IFSOCK | 0o777)),
    ((10026, stat.S_IFLNK | 0o1777), (10026, stat.S_IFSOCK | 0o777)),
    ((10026, stat.S_IFDIR | 0o777), (10026, stat.S_IFSOCK | 0o777)),
    (None, None),
    (PermissionError(errno.EACCES, "fixture denied"), None),
    ((10026, stat.S_IFDIR | 0o1777), (0, stat.S_IFSOCK | 0o777)),
    ((10026, stat.S_IFDIR | 0o1777), (10026, stat.S_IFREG | 0o777)),
    ((10026, stat.S_IFDIR | 0o1777), (10026, stat.S_IFLNK | 0o777)),
    ((10026, stat.S_IFDIR | 0o1777), (10026, stat.S_IFSOCK | 0o700)),
    ((10026, stat.S_IFDIR | 0o1777), PermissionError(errno.EACCES, "fixture denied")),
])
def test_actual_display_guard_rejects_unknown_endpoint_identity(script, directory, endpoint):
    assert _display_guard(script, directory, endpoint, 0) is not None


@pytest.mark.parametrize("endpoint,connect_error", [
    (None, errno.ENOENT), ((10026, stat.S_IFSOCK | 0o777), errno.ECONNREFUSED),
])
def test_actual_x11_guard_allows_absent_or_known_owned_stale_socket(endpoint, connect_error):
    assert _display_guard("phone_x11.sh", (10026, stat.S_IFDIR | 0o1777), endpoint, connect_error) is None


def test_actual_x11_guard_refuses_a_live_owned_display():
    assert "existing display" in _display_guard("phone_x11.sh", (10026, stat.S_IFDIR | 0o1777),
                                                (10026, stat.S_IFSOCK | 0o777), 0)


@pytest.mark.parametrize("connect_error,cdp_error,allowed", [
    (0, errno.ECONNREFUSED, True), (errno.ECONNREFUSED, errno.ECONNREFUSED, False),
    (0, 0, False), (0, errno.EACCES, False),
])
def test_actual_browser_guard_requires_a_live_owned_display_and_free_cdp(connect_error, cdp_error, allowed):
    outcome = _display_guard("phone_browser.sh", (10026, stat.S_IFDIR | 0o1777),
                             (10026, stat.S_IFSOCK | 0o777), connect_error, cdp_error)
    assert (outcome is None) == allowed


@requires_bash
def test_all_phone_launchers_are_valid_bash():
    for name in ("phone_env.sh", "phone_serve.sh", "phone_browser.sh", "phone_x11.sh", "phone_watch.sh", "phone_services.sh"):
        subprocess.run([BASH, "-n", str(ROOT / "scripts" / name)], check=True)

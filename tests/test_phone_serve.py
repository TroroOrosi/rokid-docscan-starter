"""PC-only launcher checks: every phone/browser command is a fake shim."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash")
requires_bash = pytest.mark.skipif(BASH is None, reason="bash not on PATH")


def _environment(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    for name in ("termux-wake-lock", "python", "chromium-browser", "sv", "sv-enable", "sv-disable"):
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
           "HOME": home.as_posix(), "PREFIX": prefix.as_posix(),
           "ROKID_ENV_FILE": env_file.as_posix(), "DISPLAY": ":0"}
    return env, log


def _run(script, env, *args):
    return subprocess.run([BASH, "-c", 'umask 077; exec bash "$@"', "phone-test",
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
def test_browser_login_and_headless_share_one_private_profile_and_local_cdp(tmp_path):
    env, log = _environment(tmp_path)
    assert _run("phone_browser.sh", env, "login").returncode == 0
    login = log.read_text().splitlines()
    log.write_text("")
    assert _run("phone_browser.sh", env, "headless").returncode == 0
    unattended = log.read_text().splitlines()
    for commands in (login, unattended):
        assert "--remote-debugging-address=127.0.0.1" in commands
        assert "--remote-debugging-port=9222" in commands
        assert "https://chatgpt.com/" in commands
    assert [x for x in login if x.startswith("--user-data-dir=")] == [
        x for x in unattended if x.startswith("--user-data-dir=")]
    assert "--headless" not in login and "--headless" in unattended


@requires_bash
def test_visible_login_requires_a_display_and_never_falls_back_to_headless(tmp_path):
    env, log = _environment(tmp_path)
    env.pop("DISPLAY", None)
    result = _run("phone_browser.sh", env, "login")
    assert result.returncode != 0
    assert "Termux:X11" in result.stderr
    assert not log.exists()


@requires_bash
def test_service_install_keeps_all_three_services_down_until_explicit_enable(tmp_path):
    env, log = _environment(tmp_path)
    result = _run("phone_services.sh", env, "install")
    assert result.returncode == 0, result.stderr
    services = Path(env["PREFIX"]) / "var/service"
    for name in ("rokid-browser", "rokid-api", "rokid-watch"):
        assert (services / name / "down").exists()
        subprocess.run([BASH, "-n", str(services / name / "run")], check=True)
        subprocess.run([BASH, "-n", str(services / name / "log/run")], check=True)
    boot = Path(env["HOME"]) / ".termux/boot/20-rokid-services"
    assert boot.exists() and "start-services.sh" in boot.read_text()
    assert not log.exists()
    enabled = _run("phone_services.sh", env, "enable")
    assert enabled.returncode == 0, enabled.stderr
    assert log.read_text().splitlines() == ["sv-enable", "rokid-browser", "sv-enable", "rokid-api",
                                          "sv-enable", "rokid-watch"]


@requires_bash
def test_missing_auth_is_rejected_before_any_phone_command(tmp_path):
    env, log = _environment(tmp_path)
    Path(env["ROKID_ENV_FILE"]).write_text("export ROKID_SOLVER=chatgpt-web\n")
    env.pop("ROKID_API_KEY", None)
    result = _run("phone_serve.sh", env)
    assert result.returncode != 0 and "authentication_failed" in result.stderr
    assert not log.exists()


@requires_bash
def test_all_phone_launchers_are_valid_bash():
    for name in ("phone_env.sh", "phone_serve.sh", "phone_browser.sh", "phone_watch.sh", "phone_services.sh"):
        subprocess.run([BASH, "-n", str(ROOT / "scripts" / name)], check=True)

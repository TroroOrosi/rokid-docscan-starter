#!/usr/bin/env bash
# Runs on Termux. Both login and supervised runs use the measured visible
# Termux:X11 route and the same private persistent profile.
# Package/flags: termux/termux-packages x11-packages/chromium/build.sh and
# chromium-launcher.sh.in and termux/termux-x11 README.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/phone_env.sh"
mode="${1:-visible}"
case "$mode" in
    visible|login) ;;
    *) echo "usage: phone_browser.sh [visible|login]" >&2; exit 2 ;;
esac
phone_need chromium-browser "pkg install x11-repo; pkg install chromium"
phone_need python "pkg install python"
umask 077
profile="${ROKID_BROWSER_PROFILE:-${ROKID_DATA_DIR:-$repo_root/data}/chromium-profile}"
if [[ -L "$profile" || ( -e "$profile" && ! -d "$profile" ) ]]; then
    echo "phone_browser: private profile must be a directory" >&2
    exit 1
fi
mkdir -p "$profile"
if [[ "$(stat -c '%a' "$profile")" != 700 || "$(stat -c '%u' "$profile")" != "$(id -u)" ]]; then
    echo "phone_browser: private profile must be owned by this user with mode 0700" >&2
    exit 1
fi
if [[ -e "$profile/SingletonLock" || -L "$profile/SingletonLock" ]]; then
    echo "phone_browser: existing profile lock retained; hand over the owned browser before starting services" >&2
    exit 1
fi
# Runit may start services concurrently at boot. A usable local X socket must
# precede Chromium, and an existing CDP owner is never replaced or killed.
python - <<'PY'
import errno
import os
from pathlib import Path
import socket
import stat
import sys

endpoint = Path(os.environ["TMPDIR"]) / ".X11-unix" / "X1"
try:
    directory, existing = endpoint.parent.lstat(), endpoint.lstat()
    if (directory.st_uid != os.getuid() or not stat.S_ISDIR(directory.st_mode)
            or stat.S_IMODE(directory.st_mode) != 0o1777):
        sys.exit("phone_browser: unexpected local display directory identity")
    if (existing.st_uid != os.getuid() or not stat.S_ISSOCK(existing.st_mode)
            or stat.S_IMODE(existing.st_mode) != 0o777):
        sys.exit("phone_browser: unexpected local display socket identity")
except OSError:
    sys.exit("phone_browser: local display identity is unavailable")

try:
    with socket.socket(socket.AF_UNIX) as display:
        display.settimeout(1)
        display.connect(str(endpoint))
    with socket.socket() as cdp:
        cdp.settimeout(1)
        available = cdp.connect_ex(("127.0.0.1", 9222)) == errno.ECONNREFUSED
except OSError:
    available = False
if not available:
    sys.exit("phone_browser: X11 is not ready or local CDP is occupied/unavailable")
PY
exec chromium-browser --user-data-dir="$profile" \
    --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 \
    --no-first-run --no-default-browser-check https://chatgpt.com/

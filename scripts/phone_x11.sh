#!/usr/bin/env bash
# Termux:X11 command and Android Activity have separate lifetimes (upstream
# README). Runit owns the foreground command; no PC/ADB bridge is involved.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/phone_env.sh"
phone_need termux-x11 "pkg install x11-repo; pkg install termux-x11-nightly"
phone_need python "pkg install python"
# Leave a pre-existing server alone. Only a known owned socket may be handed
# to X11 after connection refusal; never unlink a socket or lock here.
python - <<'PY'
import errno
import os
from pathlib import Path
import socket
import stat
import sys

endpoint = Path(os.environ["TMPDIR"]) / ".X11-unix" / "X1"
try:
    directory = endpoint.parent.lstat()
    if (directory.st_uid != os.getuid() or not stat.S_ISDIR(directory.st_mode)
            or stat.S_IMODE(directory.st_mode) != 0o1777):
        sys.exit("phone_x11: unexpected local display directory identity")
    try:
        existing = endpoint.lstat()
    except FileNotFoundError:
        existing = None
    if existing is not None and (existing.st_uid != os.getuid()
            or not stat.S_ISSOCK(existing.st_mode) or stat.S_IMODE(existing.st_mode) != 0o777):
        sys.exit("phone_x11: unexpected local display socket identity")
except OSError:
    sys.exit("phone_x11: local display identity is unavailable")

try:
    with socket.socket(socket.AF_UNIX) as display:
        display.settimeout(1)
        display.connect(str(endpoint))
except OSError as error:
    if error.errno not in (errno.ENOENT, errno.ECONNREFUSED):
        sys.exit("phone_x11: local display state is unavailable")
else:
    sys.exit("phone_x11: existing display retained; hand over the owned server before starting services")
PY
phone_need am "Termux:X11 Android app must be installed"
# Do not inherit an unrelated desktop session from an interactive shell.
unset TERMUX_X11_XSTARTUP
if ! am start --user 0 -n com.termux.x11/com.termux.x11.MainActivity >/dev/null 2>&1; then
    echo "phone_x11: activity_start_failed" >&2
    exit 1
fi
exec termux-x11 "$DISPLAY"

#!/usr/bin/env bash
# Runs on the phone (Termux, F-51F) to start the FastAPI server for a venue
# session. Written and tested on the PC with fake adb/termux-wake-lock/ip/
# python shims; has not run on the phone.
#
# adbd must already be in TCP mode -- from a PC, after every phone reboot:
#   adb tcpip 5555
# This script then connects to the phone's own loopback adbd and forwards
# Chrome's DevTools socket so app/solvers/cdp.py can reach it.
# Step order: the env file is checked before wake-lock/adb, so a bad env file
# is refused before anything touches adb.
set -euo pipefail

interface="${1:?usage: phone_serve.sh <wifi-interface>}"

# The default is where the phone's server env is already recorded
# (data/device-setup/apply_phone.py). Its lines are `export NAME=value`, which
# `set -a; .` below loads the same as plain NAME=value.
env_file="${ROKID_ENV_FILE:-$HOME/rokid-server/multimodal.env}"
if [[ ! -f "$env_file" ]]; then
    echo "phone_serve: env file not found: $env_file" >&2
    exit 1
fi
mode="$(stat -c '%a' "$env_file")"
if [[ "$mode" != "600" ]]; then
    echo "phone_serve: $env_file must be mode 0600 (found $mode); run: chmod 600 \"$env_file\"" >&2
    exit 1
fi
set -a
# shellcheck disable=SC1090
. "$env_file"
set +a

for tool in termux-wake-lock adb ip python; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        case "$tool" in
            # termux-wake-lock ships in termux-tools, not termux-api.
            termux-wake-lock) hint="pkg install termux-tools" ;;
            adb) hint="pkg install android-tools" ;;
            ip) hint="pkg install iproute2" ;;
            python) hint="pkg install python" ;;
        esac
        echo "phone_serve: $tool not found: $hint" >&2
        exit 1
    fi
done

termux-wake-lock

# adb commonly prints "failed to connect ..." and still exits 0, so only the
# exit code cannot be trusted. It can also print daemon-start banner lines
# before the real result on the first connect after a reboot, so judge line
# by line: success needs some line starting "connected to " / "already
# connected to " AND no line starting "failed"/"unable"/"cannot" (adb's own
# casing). Capture the output and show it either way.
connect_output="$(adb connect 127.0.0.1:5555 2>&1)" || true
echo "$connect_output"
connect_succeeded=0
connect_failed=0
while IFS= read -r line; do
    case "$line" in
        "connected to "*|"already connected to "*) connect_succeeded=1 ;;
    esac
    case "$line" in
        failed*|unable*|cannot*) connect_failed=1 ;;
    esac
done <<< "$connect_output"
if [[ "$connect_succeeded" != 1 || "$connect_failed" == 1 ]]; then
    echo "phone_serve: adb connect did not report success. Put adbd in TCP mode from a PC first, after every phone reboot:" >&2
    echo "  adb tcpip 5555" >&2
    exit 1
fi

adb -s 127.0.0.1:5555 forward tcp:9222 localabstract:chrome_devtools_remote
echo "phone_serve: keep Chrome in the foreground -- the DevTools socket disappears otherwise." >&2

address="$(ip -4 -o addr show dev "$interface" | awk '{sub(/\/.*/, "", $4); print $4; exit}')"
if [[ -z "$address" ]]; then
    echo "phone_serve: no IPv4 address found on interface $interface" >&2
    exit 1
fi

echo "phone_serve: glasses should use http://$address:8000"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
exec python -m uvicorn app.main:app --host "$address" --port 8000 --no-access-log

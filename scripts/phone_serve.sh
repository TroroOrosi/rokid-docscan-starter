#!/usr/bin/env bash
# Runs on the phone (Termux, F-51F) to start the FastAPI server for a venue
# session. Written and tested on the PC with fake adb/termux-wake-lock/ip/
# python shims; has not run on the phone.
#
# adbd must already be in TCP mode -- from a PC, after every phone reboot:
#   adb tcpip 5555
# This script then connects to the phone's own loopback adbd and forwards
# Chrome's DevTools socket so app/solvers/cdp.py can reach it.
set -euo pipefail

interface="${1:?usage: phone_serve.sh <wifi-interface>}"

env_file="${ROKID_ENV_FILE:-$HOME/.rokid.env}"
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

termux-wake-lock

if ! adb connect 127.0.0.1:5555; then
    echo "phone_serve: adb connect failed. Put adbd in TCP mode from a PC first, after every phone reboot:" >&2
    echo "  adb tcpip 5555" >&2
    exit 1
fi

adb -s 127.0.0.1:5555 forward tcp:9222 localabstract:chrome_devtools_remote
echo "phone_serve: keep Chrome in the foreground -- the DevTools socket disappears otherwise." >&2

address="$(ip -4 -o addr show dev "$interface" | awk '{print $4}' | cut -d/ -f1 | head -n1)"
if [[ -z "$address" ]]; then
    echo "phone_serve: no IPv4 address found on interface $interface" >&2
    exit 1
fi

echo "phone_serve: glasses should use http://$address:8000"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
exec python -m uvicorn app.main:app --host "$address" --port 8000 --no-access-log

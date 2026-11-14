#!/usr/bin/env bash
# Runs on Termux. Runit supervises the browser and watcher independently.
# First unlock and working tethering are required for the venue path.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/phone_env.sh"
address="${1:-0.0.0.0}"
phone_need termux-wake-lock "pkg install termux-tools"
phone_need python "pkg install python"
if [[ ! "$address" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    phone_need ip "pkg install iproute2"
    address="$(ip -4 -o addr show dev "$address" | awk '{sub(/\/.*/, "", $4); print $4; exit}')"
    if [[ -z "$address" ]]; then
        echo "phone_serve: no IPv4 address found" >&2
        exit 1
    fi
fi
termux-wake-lock
echo "phone_serve: listening on $address:8000; glasses use their Wi-Fi gateway"
# A forwarded header must never turn a phone/attacker address into the control target.
exec python -m uvicorn app.main:app --host "$address" --port 8000 --workers 1 --no-access-log --no-proxy-headers

#!/usr/bin/env bash
# Runs on Termux. Authenticated server notifications supply the glasses IP.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/phone_env.sh"
: "${ROKID_GLASSES_SERIAL:?ROKID_GLASSES_SERIAL must name the authorized glasses}"
phone_need python "pkg install python"
exec python scripts/watch_glasses.py --serial auto --expected-serial "$ROKID_GLASSES_SERIAL"

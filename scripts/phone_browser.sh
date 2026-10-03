#!/usr/bin/env bash
# Runs on Termux. First login uses an existing Termux:X11 display; the service
# uses the same private profile headless. Hardware/login acceptance is pending.
# Package/flags: termux/termux-packages x11-packages/chromium/build.sh and
# chromium-launcher.sh.in; developer.chrome.com/docs/chromium/headless.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/phone_env.sh"
mode="${1:-headless}"
flags=()
case "$mode" in
    login)
        if [[ -z "${DISPLAY:-}" ]]; then
            echo "phone_browser: login needs a visible Termux:X11 display (DISPLAY)" >&2
            exit 1
        fi
        ;;
    headless) flags+=(--headless) ;;
    *) echo "usage: phone_browser.sh [login|headless]" >&2; exit 2 ;;
esac
phone_need chromium-browser "pkg install x11-repo; pkg install chromium"
umask 077
profile="${ROKID_BROWSER_PROFILE:-${ROKID_DATA_DIR:-$repo_root/data}/chromium-profile}"
mkdir -p "$profile"
exec chromium-browser "${flags[@]}" --user-data-dir="$profile" \
    --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 \
    --no-first-run --no-default-browser-check https://chatgpt.com/

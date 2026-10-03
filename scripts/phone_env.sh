#!/usr/bin/env bash
# Shared Termux environment. No command in this file controls a device.
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${ROKID_ENV_FILE:-$HOME/rokid-server/multimodal.env}"
if [[ ! -f "$env_file" ]]; then
    echo "phone: env file not found: $env_file" >&2
    exit 1
fi
if [[ "$(stat -c '%a' "$env_file")" != "600" ]]; then
    echo "phone: env file must have mode 0600" >&2
    exit 1
fi
set -a
# shellcheck disable=SC1090
. "$env_file"
set +a
if [[ -z "${ROKID_API_KEY:-}" ]]; then
    echo "phone: authentication_failed; ROKID_API_KEY is required" >&2
    exit 1
fi
# A stale phone env must not shorten a whole-booklet reply or redirect CDP.
unset ROKID_CHATGPT_TIMEOUT_S ROKID_CHATGPT_POLL_S
export ROKID_CHATGPT_CDP="http://127.0.0.1:9222"
# Enabling services is separate from permission to submit a photographed booklet.
export ROKID_CHATGPT_SEND_ENABLED="${ROKID_CHATGPT_SEND_ENABLED:-0}"
cd "$repo_root"

phone_need() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "phone: $1 not found: $2" >&2
        exit 1
    fi
}

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
# Android boot values belong to one OS generation. A complete inherited set
# wins over a cached private env; a partial set must never be mixed with it.
phone_android_runtime_keys=(ANDROID_ART_ROOT ANDROID_I18N_ROOT ANDROID_TZDATA_ROOT
                            ANDROID_ROOT ANDROID_DATA BOOTCLASSPATH DEX2OATBOOTCLASSPATH)
phone_android_runtime_values=()
phone_android_runtime_validate() {
    local name seen=0 missing=0
    for name in "${phone_android_runtime_keys[@]}"; do
        if [[ -v "$name" ]]; then seen=1; fi
        if [[ -z "${!name-}" ]]; then missing=1; fi
    done
    if (( seen && missing )) ||
        { (( seen )) && [[ "$BOOTCLASSPATH" != "$DEX2OATBOOTCLASSPATH" &&
                           "$BOOTCLASSPATH" != "${DEX2OATBOOTCLASSPATH}:"* ]]; } ||
        { (( ! seen )) && test -x /system/bin/app_process && test -d /apex/com.android.art; }; then
        echo "phone: incomplete Android runtime environment" >&2
        exit 1
    fi
}
for phone_android_runtime_name in "${phone_android_runtime_keys[@]}"; do
    if [[ -v "$phone_android_runtime_name" ]]; then
        phone_android_runtime_values+=("${!phone_android_runtime_name}")
    fi
done
if (( ${#phone_android_runtime_values[@]} )); then phone_android_runtime_validate; fi
set -a
# shellcheck disable=SC1090
. "$env_file"
set +a
if (( ${#phone_android_runtime_values[@]} )); then
    for phone_android_runtime_index in "${!phone_android_runtime_keys[@]}"; do
        export "${phone_android_runtime_keys[$phone_android_runtime_index]}=${phone_android_runtime_values[$phone_android_runtime_index]}"
    done
fi
phone_android_runtime_validate
unset phone_android_runtime_keys phone_android_runtime_values phone_android_runtime_name phone_android_runtime_index
unset -f phone_android_runtime_validate
if [[ -z "${ROKID_API_KEY:-}" ]]; then
    echo "phone: authentication_failed; ROKID_API_KEY is required" >&2
    exit 1
fi
# A stale phone env must not shorten a whole-booklet reply or redirect CDP.
unset ROKID_CHATGPT_TIMEOUT_S ROKID_CHATGPT_POLL_S
export ROKID_CHATGPT_CDP="http://127.0.0.1:9222"
# The supervised X server and browser must use the same local display even
# when an interactive shell or an older env file selected another display.
export DISPLAY=:1
export TMPDIR="${TMPDIR:-${PREFIX:?Termux PREFIX is required}/tmp}"
# Enabling services is separate from permission to submit a photographed booklet.
export ROKID_CHATGPT_SEND_ENABLED="${ROKID_CHATGPT_SEND_ENABLED:-0}"
cd "$repo_root"

phone_need() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "phone: $1 not found: $2" >&2
        exit 1
    fi
}

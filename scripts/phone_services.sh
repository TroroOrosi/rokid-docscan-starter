#!/usr/bin/env bash
# Runs on Termux, only after approval. install writes disabled runit services;
# enable switches the three services on after visible login/CDP acceptance.
# Sources: github.com/termux/termux-boot#how-to-use and termux/termux-services.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/phone_env.sh"
: "${PREFIX:?Termux PREFIX is required}"
action="${1:-status}"
services=(rokid-browser rokid-api rokid-watch)
case "$action" in
    install)
        phone_need sv-enable "pkg install termux-services"
        : "${ROKID_GLASSES_SERIAL:?ROKID_GLASSES_SERIAL must name the authorized glasses}"
        umask 077
        for role in browser api watch; do
            name="rokid-$role"
            service="$PREFIX/var/service/$name"
            if [[ -f "$service/run" ]] && ! grep -q '^# rokid-managed$' "$service/run"; then
                echo "phone_services: refusing to replace unmanaged $name" >&2
                exit 1
            fi
            mkdir -p "$service/log" "$PREFIX/var/log/sv/$name"
            touch "$service/down"
            case "$role" in
                browser) script=phone_browser.sh; argument=headless ;;
                api) script=phone_serve.sh; argument=0.0.0.0 ;;
                watch) script=phone_watch.sh; argument="" ;;
            esac
            {
                printf '#!%s/bin/bash\n# rokid-managed\nexec 2>&1\n' "$PREFIX"
                printf 'export ROKID_ENV_FILE=%q\n' "$env_file"
                printf 'exec bash %q %q\n' "$repo_root/scripts/$script" "$argument"
            } > "$service/run"
            {
                printf '#!%s/bin/sh\n' "$PREFIX"
                printf 'exec %q -tt %q\n' "$PREFIX/bin/svlogd" "$PREFIX/var/log/sv/$name"
            } > "$service/log/run"
            chmod 700 "$service/run" "$service/log/run"
        done
        mkdir -p "$HOME/.termux/boot"
        boot="$HOME/.termux/boot/20-rokid-services"
        {
            printf '#!%s/bin/bash\ntermux-wake-lock\n' "$PREFIX"
            printf '. %q\n' "$PREFIX/etc/profile.d/start-services.sh"
        } > "$boot"
        chmod 700 "$boot"
        echo "phone_services: installed disabled services; open Termux:Boot once, login, then enable"
        ;;
    enable|disable)
        phone_need "sv-$action" "pkg install termux-services"
        . "$PREFIX/etc/profile.d/start-services.sh"
        if [[ "$action" == disable ]]; then services=(rokid-watch rokid-api rokid-browser); fi
        for service in "${services[@]}"; do "sv-$action" "$service"; done
        ;;
    status)
        phone_need sv "pkg install termux-services"
        exec sv status "${services[@]/#/$PREFIX/var/service/}"
        ;;
    *) echo "usage: phone_services.sh [install|enable|disable|status]" >&2; exit 2 ;;
esac

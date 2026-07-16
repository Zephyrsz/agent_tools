#!/usr/bin/env bash

set -euo pipefail

SCRIPT_NAME="$(basename "$0")"

usage() {
    cat <<EOF
Usage: $SCRIPT_NAME enable|disable|status

  enable   Prevent macOS from sleeping, including when the lid is closed.
  disable  Restore normal macOS sleep behavior.
  status   Show whether system sleep is currently disabled.

This setting applies on both battery and external power. Keep the MacBook
connected to power and well ventilated. Never put it in a bag while enabled.
EOF
}

require_macos() {
    if [[ "$(uname -s)" != "Darwin" ]] || ! command -v pmset >/dev/null 2>&1; then
        printf 'Error: this script must be run on macOS.\n' >&2
        exit 1
    fi
}

sleep_disabled_state() {
    ioreg -r -c IOPMrootDomain -d 1 2>/dev/null \
        | awk -F'= ' '/"SleepDisabled"/ {gsub(/[ "]/, "", $2); print $2; exit}'
}

show_status() {
    local state
    state="$(sleep_disabled_state)"

    case "$state" in
        Yes)
            printf 'System sleep: DISABLED\n'
            printf 'Lid-closed networking: expected to remain active\n'
            ;;
        No)
            printf 'System sleep: ENABLED (normal macOS behavior)\n'
            printf 'Lid-closed networking: expected to stop when the Mac sleeps\n'
            ;;
        *)
            printf 'System sleep state: unknown\n' >&2
            printf 'Run: pmset -g\n' >&2
            return 1
            ;;
    esac

    printf '\n'
    pmset -g batt | head -n 2
}

enable_lid_closed_networking() {
    printf 'Requesting administrator access...\n'
    sudo -v

    # SleepDisabled prevents lid-close sleep. While macOS remains awake,
    # existing Tailscale, SSH, and Screen Sharing services keep running.
    if ! sudo pmset -a disablesleep 1; then
        printf 'Error: this macOS version or Mac model rejected disablesleep.\n' >&2
        exit 1
    fi

    printf '\n'
    show_status
    printf '\nEnabled. Keep the MacBook powered and well ventilated.\n'
}

disable_lid_closed_networking() {
    printf 'Requesting administrator access...\n'
    sudo -v
    sudo pmset -a disablesleep 0

    printf '\n'
    show_status
    printf '\nDisabled. Normal lid-close sleep behavior has been restored.\n'
}

main() {
    require_macos

    case "${1:-status}" in
        enable)
            enable_lid_closed_networking
            ;;
        disable)
            disable_lid_closed_networking
            ;;
        status)
            show_status
            ;;
        -h|--help|help)
            usage
            ;;
        *)
            usage >&2
            exit 2
            ;;
    esac
}

main "$@"

#!/bin/sh
# Puts the card back the way install.sh found it (Clopsagotchi), keeping the trip logs.
set -eu
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
UNDO=/opt/retrogps/undo.txt
systemctl disable --now retrogps.service 2>/dev/null || true
rm -f /etc/systemd/system/retrogps.service
nmcli -t -f NAME con show | grep '^retrogps-' | while IFS= read -r name; do nmcli con delete "$name" >/dev/null; done || true
if [ -f "$UNDO" ]; then
    while read -r what arg; do
        case "$what" in
            enable) systemctl enable "$arg" >/dev/null 2>&1 || true ;;
            wifi-overlay) sed -i 's/^#retrogps#//' /boot/firmware/config.txt ;;
            nm-conf) mv "$arg.retrogps-off" "$arg" ;;
        esac
    done < "$UNDO"
fi
systemctl daemon-reload
echo "Retro GPS removed (trip logs kept in /var/lib/retrogps). Reboot."

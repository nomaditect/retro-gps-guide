#!/bin/sh
# Turns the Clopsagotchi card into Retro GPS. Every change is recorded so uninstall.sh
# can put Clopsagotchi back. Run on the Pi from a copy of this repo: sudo ./install.sh
set -eu
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
HERE=$(cd "$(dirname "$0")" && pwd)
APP=/opt/retrogps
CFG=/boot/firmware/config.txt
UNDO=$APP/undo.txt

# ---- app
if [ "$HERE" != "$APP" ]; then
    mkdir -p "$APP" && cp -r "$HERE"/. "$APP"/
fi
mkdir -p /var/lib/retrogps /etc/retrogps
[ -f "$UNDO" ] || : > "$UNDO"
python3 -m compileall -q "$APP/retrogps"   # no byte-compiling on every boot
install -m 644 "$APP/retrogps.service" /etc/systemd/system/

# ---- libraries (Pillow, smbus2, spidev and gpiozero came with the image)
python3 -c 'import qrcode' 2>/dev/null || apt-get install -y python3-qrcode iw >/dev/null 2>&1 \
    || echo "note: couldn't install python3-qrcode (offline?); the web map will show its address without a QR code"

# ---- hand the card over from Clopsagotchi
for u in clopsagotchi.service pwnagotchi.service bettercap.service; do
    if [ "$(systemctl is-enabled "$u" 2>/dev/null || true)" = enabled ]; then
        systemctl disable --now "$u" >/dev/null 2>&1 || true
        echo "enable $u" >> "$UNDO"
    fi
done

# ---- Wi-Fi back on (Clopsagotchi switched the radio off for battery); Bluetooth stays off
if grep -q '^dtoverlay=disable-wifi' "$CFG"; then
    sed -i 's/^dtoverlay=disable-wifi/#retrogps#&/' "$CFG"
    echo "wifi-overlay" >> "$UNDO"
fi
for f in /etc/NetworkManager/conf.d/*.conf; do  # pwnagotchi leaves wlan0 unmanaged
    [ -f "$f" ] && grep -q 'unmanaged-devices.*wlan0' "$f" && mv "$f" "$f.retrogps-off" \
        && echo "nm-conf $f" >> "$UNDO"
done
systemctl enable NetworkManager.service >/dev/null 2>&1 || true

# ---- secrets and Wi-Fi profiles (hidden=yes so an iPhone hotspot is found even when it's quiet)
if [ -f "$HERE/secrets.toml" ]; then
    install -m 600 "$HERE/secrets.toml" /etc/retrogps/secrets.toml
fi
if [ -f /etc/retrogps/secrets.toml ]; then
    python3 - <<'PY'
import subprocess, tomllib
nets = tomllib.load(open("/etc/retrogps/secrets.toml", "rb")).get("wifi", [])
for i, n in enumerate(nets):
    name = "retrogps-" + n["ssid"]
    subprocess.run(["nmcli", "con", "delete", name], capture_output=True)
    subprocess.run(["nmcli", "con", "add", "type", "wifi", "ifname", "wlan0", "con-name", name,
                    "ssid", n["ssid"], "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", n["password"],
                    "802-11-wireless.hidden", "yes", "connection.autoconnect", "yes",
                    "connection.autoconnect-priority", str(100 - i)], check=True, capture_output=True)
    print("Wi-Fi profile:", n["ssid"])
PY
else
    echo "note: no secrets.toml yet; copy secrets.example.toml, fill it in and run install.sh again"
fi

timedatectl set-timezone UTC 2>/dev/null || true   # the app works in each place's own zone
systemctl daemon-reload
systemctl enable retrogps.service
echo "Retro GPS installed. Reboot to start."

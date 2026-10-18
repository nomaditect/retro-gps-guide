#!/bin/sh
# clopsagotchi — one-shot USB-gadget networking fix for macOS <-> Pi Zero 2 W
#
# Problem: on the Raspberry Pi OS (Trixie) based jayofelony image, the Pi's
# usb0 gadget interface gets a RANDOM MAC each boot and, on some macOS setups,
# never gets a static IP, so `ssh pi@10.0.0.2` never comes up.
#
# How to use: the Pi's boot (FAT) partition is the only part macOS can write to.
# 1. Copy this script to the boot partition as /boot/firmware/pwnfix.sh
# 2. Save a copy of the pristine cmdline.txt as cmdline.txt.orig
# 3. Append to cmdline.txt (one line, space-separated), so it runs once:
#       systemd.run=/boot/firmware/pwnfix.sh systemd.unit=kernel-command-line.target
# 4. Boot the Pi plugged into the Mac. It configures usb0, then continues a
#    normal boot. On the Mac side:
#       networksetup -setmanual "Raspberry Pi USB Gadget" 10.0.0.1 255.255.255.0
#    then: ssh pi@10.0.0.2   (default user pi / pass raspberry on a fresh image)

set -e
B=/boot/firmware

# Restore the normal cmdline so this only runs once.
cp "$B/cmdline.txt.orig" "$B/cmdline.txt"
sync

# Static IP on usb0, matched by interface name (NOT MAC, which is random each boot).
cat > /etc/NetworkManager/system-connections/usb0-static.nmconnection <<'NM'
[connection]
id=usb0-static
type=ethernet
interface-name=usb0
autoconnect=true
autoconnect-priority=999

[ipv4]
method=manual
address1=10.0.0.2/24

[ipv6]
method=link-local
NM
chmod 600 /etc/NetworkManager/system-connections/usb0-static.nmconnection
sync

# Continue a normal boot (brings up NetworkManager, ssh, pwnagotchi).
systemctl isolate multi-user.target

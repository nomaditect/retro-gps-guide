# Connecting to the Pi over USB from macOS

Hard-won notes from getting a Pi Zero 2 W pwnagotchi talking to a Mac (macOS 26)
over the USB gadget interface.

## Cable & ports (the #1 gotcha)

- Use a **data-capable** cable (charge-only cables silently fail — test with a phone).
- Plug into the **Pi's own micro-USB port marked `USB`** (the middle one), **not** the
  Pi's `PWR` port, and **not** the PiSugar's USB-C (that's charge-only).
  Wrong port = the Mac sees no USB device at all (`ioreg` gadget count 0).
- Plug **straight into the Mac**, not through a hub/dock — the gadget often fails to
  enumerate through hubs.

## macOS side

- The Pi appears as a network service named **"Raspberry Pi USB Gadget"** (e.g. `en8`).
- If macOS enumerates the device but never creates the interface, a **Mac restart**
  clears it (an accessory-approval / driver-matching quirk). Check
  *System Settings → Privacy & Security → Allow accessories to connect*.
- Set the Mac end of the link to a static IP:

  ```sh
  networksetup -setmanual "Raspberry Pi USB Gadget" 10.0.0.1 255.255.255.0
  ```

- Then connect:

  ```sh
  ssh pi@10.0.0.2          # default pass on a fresh image: raspberry
  ```

## Quick checks

```sh
# Is the Pi enumerated on USB?
ioreg -l -w0 | grep -c 'Raspberry Pi USB Gadget@'     # expect 1

# Which interface / is the link up?
networksetup -listallhardwareports | grep -A2 -i raspberry
ifconfig en8 | grep -E 'status|inet'                  # status: active

# Is SSH reachable?
nc -z -G 2 10.0.0.2 22 && echo open
```

## PiSugar 3 notes

- The PiSugar talks over **I2C bus 1 at 0x57** (its RTC at 0x68). Confirm with a scan.
- Its blue LED can light from the Pi's 5V even with **no battery** — but the I2C chip
  needs the **battery connected** to respond. "LED on" ≠ "detected".
- If I2C shows nothing, **reseat the board** so the pogo pins press firmly and evenly
  against the underside of the GPIO header.

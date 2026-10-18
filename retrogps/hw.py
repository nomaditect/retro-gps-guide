"""PiSugar 3 (button, RTC, wake alarm, power) and the Waveshare 2.13" V4 e-ink, plus stand-ins
for trying it all out on a Mac. The PiSugar code is shared with Clopsagotchi.

PiSugar 3 register map is from PiSugar's own driver:
https://github.com/PiSugar/pisugar-power-manager-rs/blob/master/pisugar-core/src/pisugar3.rs
"""
import time
from datetime import datetime, timezone

ADDR = 0x57
CTR1, CTR2, TAP, POWEROFF_DELAY, WRITE_ENABLE, PERCENT = 0x02, 0x03, 0x08, 0x09, 0x0B, 0x2A
VOLT_H, VOLT_L, CURR_H, CURR_L = 0x22, 0x23, 0x26, 0x27
RTC = 0x31            # yy mm dd wd hh mn ss (BCD), 0x31..0x37
ALM_CTR, ALM_WD, ALM_HH, ALM_MN, ALM_SS = 0x40, 0x44, 0x45, 0x46, 0x47
TAPS = {1: "single", 2: "double", 3: "long"}


def bcd(v):
    return ((v // 10) << 4) | (v % 10)


def unbcd(b):
    return (b >> 4) * 10 + (b & 0x0F)


class PiSugar:
    def __init__(self, bus=1):
        from smbus2 import SMBus
        self.bus = SMBus(bus)

    def read(self, reg):
        return self.bus.read_byte_data(ADDR, reg)

    def write(self, reg, val):
        self.bus.write_byte_data(ADDR, WRITE_ENABLE, 0x29)
        try:
            self.bus.write_byte_data(ADDR, reg, val & 0xFF)
        finally:
            self.bus.write_byte_data(ADDR, WRITE_ENABLE, 0x00)

    # ---- battery
    def battery(self):
        return self.read(PERCENT)

    def plugged(self):
        return bool(self.read(CTR1) & 0x80)

    def millivolts(self):
        return (self.read(VOLT_H) << 8) | self.read(VOLT_L)

    def milliamps(self):
        """Current the PiSugar is feeding the Pi (only meaningful on battery)."""
        return (self.read(CURR_H) << 8) | self.read(CURR_L)

    # ---- button
    def tap(self):
        """'single' / 'double' / 'long' / None, clearing the event once read."""
        t = self.read(TAP) & 0x03
        if t:
            self.write(TAP, self.read(TAP) & 0xFC)
        return TAPS.get(t)

    def enable_soft_poweroff(self):
        """Hold-to-power-off becomes a request we handle, instead of an instant power cut."""
        self.write(CTR2, (self.read(CTR2) & 0xE0) | 0x10)

    def soft_poweroff_requested(self):
        c = self.read(CTR2)
        if c & 0x18 == 0x18:
            self.write(CTR2, c & 0xF7)
            return True
        return False

    # ---- clock (kept in UTC)
    def rtc(self):
        b = [unbcd(self.read(RTC + i)) for i in range(7)]
        yy, mm, dd, _wd, hh, mn, ss = b
        try:
            return datetime(2000 + yy, mm, dd, hh, mn, ss, tzinfo=timezone.utc)
        except ValueError:
            return None

    def set_rtc(self, dt):
        dt = dt.astimezone(timezone.utc)
        for i, v in enumerate((dt.year - 2000, dt.month, dt.day, dt.isoweekday() % 7,
                               dt.hour, dt.minute, dt.second)):
            self.write(RTC + i, bcd(v))

    def set_alarm(self, dt):
        """Wake at this UTC time of day (repeats daily; we re-arm on every shutdown)."""
        dt = dt.astimezone(timezone.utc)
        self.write(ALM_HH, bcd(dt.hour))
        self.write(ALM_MN, bcd(dt.minute))
        self.write(ALM_SS, bcd(dt.second))
        self.write(ALM_WD, 0x7F)
        self.write(ALM_CTR, self.read(ALM_CTR) | 0x80)

    def disable_alarm(self):
        self.write(ALM_CTR, self.read(ALM_CTR) & 0x7F)

    # ---- power
    def cut_power_in(self, seconds):
        """Turn the 5V output off after `seconds` (give Linux time to halt first)."""
        self.write(POWEROFF_DELAY, seconds)
        self.write(CTR1, self.read(CTR1) & 0xDF)


class Display:
    """The 2.13" V4 panel is natively portrait (122x250), so frames go straight in."""

    def __init__(self, rotate=0):
        from .epd import epd2in13_V4
        self.epd = epd2in13_V4.EPD()
        self.rotate = rotate
        self.base_set = False
        self.partials = 0

    def _buf(self, img):
        return self.epd.getbuffer(img.rotate(self.rotate) if self.rotate else img)

    def full(self, img):
        self.epd.init()
        self.epd.displayPartBaseImage(self._buf(img))  # full refresh + base for partials
        self.base_set = True
        self.partials = 0

    def show(self, img, partials_before_full=20):
        """Quick partial refresh, with a full one now and then to clear ghosting."""
        if not self.base_set or self.partials >= partials_before_full:
            return self.full(img)
        self.epd.displayPartial(self._buf(img))
        self.partials += 1

    def sleep(self):
        self.epd.sleep()  # e-ink keeps the picture with zero power


class SimSugar:
    """Stand-in PiSugar for trying the UI on a Mac: type s / d / l (+ Enter) for tap, double, hold."""

    def __init__(self):
        import queue
        import threading
        self.q = queue.Queue()

        def reader():
            try:
                while True:
                    g = {"s": "single", "d": "double", "l": "long"}.get(input().strip()[:1])
                    if g:
                        self.q.put(g)
            except EOFError:
                pass
        threading.Thread(target=reader, daemon=True).start()

    def tap(self):
        try:
            return self.q.get_nowait()
        except Exception:
            return None

    def battery(self):
        return 74

    def plugged(self):
        return False

    def millivolts(self):
        return 3900

    def milliamps(self):
        return 0

    def soft_poweroff_requested(self):
        return False

    def __getattr__(self, name):  # alarms, RTC and power: nothing to do on a Mac
        return lambda *a, **k: None


class SimDisplay:
    def __init__(self, path, rotate=0):
        self.path = path

    def full(self, img):
        img.resize((img.width * 3, img.height * 3)).save(self.path)

    def show(self, img, partials_before_full=20):
        self.full(img)

    def sleep(self):
        pass


def wait_for_rtc_sane(ps, tries=3):
    for _ in range(tries):
        t = ps.rtc()
        if t and t.year >= 2026:
            return t
        time.sleep(0.2)
    return None

"""Retro GPS: wake, do whatever's due, let you browse, power off.

One PiSugar button, mapped onto the eTrex's keys:
  tap   PAGE   next page                 (in a menu: move down)
  2x    ENTER  this page's option        (in a menu: select)
  hold  MARK   update now, new waypoint  (in a menu: back)

The Pi is fully off between visits. The PiSugar's RTC alarm wakes it for the four daily
updates and the hourly breadcrumb scans; a press of the button wakes it to look around.
"""
import argparse
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

from . import config as C
from . import guide, net, screens
from .guide import KINDS
from .screens import MENU_ITEMS, PAGES, SETUP_ITEMS, ZOOMS


def log(*a):
    print(*a, flush=True)


def usb_tethered():
    """Plugged into the Mac over the data port (or the escape-hatch file exists): stay awake."""
    if os.path.exists("/boot/firmware/retrogps-stay"):
        return True
    try:
        with open("/sys/class/net/usb0/carrier") as f:
            return f.read().strip() == "1"
    except OSError:
        return False


class App:
    def __init__(self, ps, disp, store, secrets, stay=False):
        self.ps, self.disp, self.store, self.secrets = ps, disp, store, secrets
        self.s = store.s
        self.stay = stay
        page = self.s["ui"].get("page", 0)
        self.page = page if isinstance(page, int) and 0 <= page < len(PAGES) else 0
        self.menu = {"where": None, "hi": 0}
        self.busy = None
        self.message, self.message_until = None, 0
        self.worker = None
        self.web = None          # (server, url) while the web map is on
        self.web_until = 0
        self.dirty = True
        self.quit = False
        self.wpts = store.read(store.wpts)

    # ---------- drawing ----------
    def ctx(self):
        try:
            bat, plug = self.ps.battery(), self.ps.plugged()
        except OSError:
            bat, plug = None, False
        return {"page": PAGES[self.page], "battery": bat, "plugged": plug, "busy": self.busy,
                "message": self.message, "menu": self.menu, "wpts": self.wpts,
                "url": self.web[1] if self.web else None}

    def draw(self, full=False):
        with self.store.lock:
            img = screens.render(self.s, self.ctx())
        if full:
            self.disp.full(img)
        else:
            self.disp.show(img, C.PARTIALS_BEFORE_FULL)
        self.dirty = False

    def say(self, msg, seconds=3):
        self.message, self.message_until = msg, time.monotonic() + seconds
        self.dirty = True

    # ---------- background work ----------
    def working(self):
        return self.worker is not None and self.worker.is_alive()

    def start_sync(self, watched=True):
        if self.working():
            return
        if watched:
            self.page = PAGES.index("sky")  # watch it find us, eTrex style

        def progress(msg):
            self.busy = msg
            self.dirty = watched

        def run():
            try:
                ok, msg = guide.do_update(self.store, self.secrets, progress)
            except Exception as e:  # keep the UI alive whatever the network does
                log("update crashed:", repr(e))
                ok, msg = False, "UPDATE FAILED"
            self.busy = None
            self.wpts = self.store.read(self.store.wpts)
            if ok:
                self.page = 0
                self.say(msg + " MARKED" if watched else msg, 4)
            else:
                self.say(msg, 4) if watched else None
            self.dirty = True

        self.busy = "STARTING"
        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def start_track(self):
        def run():
            try:
                guide.do_track(self.store, self.secrets)
            except Exception as e:
                log("track crashed:", repr(e))
        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def start_webmap(self):
        self.menu = {"where": "webmap", "hi": 0}
        self.web_until = time.monotonic() + C.WEBMAP_MINUTES * 60

        def run():
            self.busy = "WI-FI..."
            self.dirty = True
            aps = net.scan()
            if net.connect(self.secrets["wifi"], {s for _m, s, _r in aps}):
                from . import webmap
                try:
                    srv = webmap.serve(self.store)
                    self.web = (srv, f"http://{net.local_ip()}/")
                except OSError as e:
                    log("web map failed:", e)
            self.busy = None
            self.dirty = True
        threading.Thread(target=run, daemon=True).start()

    def stop_webmap(self):
        if self.web:
            self.web[0].shutdown()
            self.web = None
        self.menu = {"where": None, "hi": 0}
        self.dirty = True

    # ---------- the button ----------
    def handle(self, gesture):
        where = self.menu["where"]
        if where == "webmap":
            if gesture == "long":
                self.stop_webmap()
            return
        if where:
            self.handle_menu(gesture)
        elif gesture == "single":
            self.page = (self.page + 1) % len(PAGES)
        elif gesture == "long":
            self.start_sync()
        else:
            self.page_option()
        self.dirty = True

    def page_option(self):
        """ENTER on a main page."""
        name, ui = PAGES[self.page], self.s["ui"]
        g = self.s.get("guide") or {}
        with self.store.lock:
            if name in ("mark", "sky", "weather"):
                self.start_sync()
            elif name == "map":
                ui["zoom"] = (ui.get("zoom", 0) + 1) % len(ZOOMS)
                z = ZOOMS[ui["zoom"]]
                self.say("AUTO ZOOM" if z is None else f"ZOOM {screens.geo.fmt_dist(z)}", 1.5)
            elif name == "waypoint":
                self.menu = {"where": "waypoints", "hi": 0}
            elif name == "pointer":
                self.next_destination(None)
            elif name == "trip":
                ui["fields"] = ui.get("fields", 0) + 1
            elif name in KINDS:
                self.next_destination(name)
            elif name == "eh":
                guide.pick_saying(self.s)
            elif name == "menu":
                self.menu = {"where": "menu", "hi": 0}

    def next_destination(self, kind):
        """GOTO the next place: within one Nearest list, or (from the Pointer) across all of them."""
        g = self.s.get("guide") or {}
        places = g.get("places") or {}
        options = [dict(p, kind=k) for k in ([kind] if kind else KINDS) for p in places.get(k, [])]
        if not options:
            return self.say("NOTHING NEARBY", 2)
        cur = self.s["ui"].get("dest") or {}
        idx = next((i for i, p in enumerate(options) if p["name"] == cur.get("name")
                    and p["kind"] == cur.get("kind")), -1)
        self.s["ui"]["dest"] = options[(idx + 1) % len(options)]

    def handle_menu(self, gesture):
        where, hi = self.menu["where"], self.menu["hi"]
        n = {"menu": len(MENU_ITEMS), "setup": len(SETUP_ITEMS), "confirm": 2,
             "waypoints": max(1, len(self.wpts))}[where]
        if gesture == "single":
            self.menu["hi"] = (hi + 1) % n
        elif gesture == "long":
            self.menu = {"where": "setup", "hi": 2} if where == "confirm" else \
                        {"where": "menu", "hi": 0} if where in ("setup", "waypoints") else {"where": None, "hi": 0}
        elif where == "menu":
            item = MENU_ITEMS[hi]
            self.menu = {"where": None, "hi": 0}
            if item == "MARK":
                self.start_sync()
            elif item == "WAYPOINTS":
                self.menu = {"where": "waypoints", "hi": 0}
            elif item == "WEB MAP":
                self.start_webmap()
            elif item == "SETUP":
                self.menu = {"where": "setup", "hi": 0}
        elif where == "waypoints":
            if self.wpts:
                w = list(reversed(self.wpts))[hi]
                self.s["ui"]["dest"] = {"name": f"WPT {w['num']:03d} {w.get('area', '')}", "lat": w["lat"],
                                        "lon": w["lon"], "kind": "wpt"}
                self.menu = {"where": None, "hi": 0}
                self.page = PAGES.index("pointer")
        elif where == "setup":
            item = SETUP_ITEMS[hi]
            if item == "SYNC NOW":
                self.menu = {"where": None, "hi": 0}
                self.start_sync()
            elif item == "ROTATE SCREEN":
                rot = 180 if (self.s["ui"].get("rotation") or C.ROTATION) == 0 else 0
                self.s["ui"]["rotation"] = rot
                self.disp.rotate = rot
                self.store.save()
                self.draw(full=True)
            elif item == "NEW TRIP":
                self.menu = {"where": "confirm", "hi": 0}
            elif item == "SLEEP NOW":
                self.quit = True
        elif where == "confirm":
            if hi == 1:
                self.store.new_trip()
                self.s = self.store.s
                self.wpts = []
                self.say("NEW TRIP STARTED", 3)
            self.menu = {"where": "setup", "hi": 0}

    # ---------- the session ----------
    def run(self, alarm_wake):
        due_update, due_track = guide.update_due(self.s), guide.track_due(self.s)
        watched = not alarm_wake
        if watched:
            self.draw(full=True)
            stale = not self.s.get("guide") or \
                time.time() - self.s["guide"]["updated_at"] > C.STALE_AFTER_H * 3600
            if due_update or stale:
                self.start_sync(watched=False)
                self.dirty = True
            deadline = time.monotonic() + C.IDLE_FIRST_S
        else:
            log("alarm wake:", "update" if due_update else "breadcrumb" if due_track else "nothing due")
            if due_update:
                self.start_sync(watched=False)
            elif due_track:
                self.start_track()
            deadline = time.monotonic()  # power off as soon as the work's done
        last_minute = time.monotonic()
        samples, last_sample = [], 0

        while not self.quit:
            now = time.monotonic()
            try:
                gesture = self.ps.tap()
                if self.ps.soft_poweroff_requested():
                    log("button asked for power off")
                    break
            except OSError as e:
                log("PiSugar read failed:", e)
                gesture = None
            if gesture:
                log("button:", gesture)
                if not watched:  # someone picked it up during a scheduled wake
                    watched = True
                    self.dirty = True
                deadline = now + C.IDLE_AFTER_PRESS_S
                self.handle(gesture)
            if self.message and now > self.message_until:
                self.message = None
                self.dirty = True
            if self.web and now > self.web_until:
                self.stop_webmap()
            if watched and now - last_minute > 60 and PAGES[self.page] in ("menu", "trip", "weather"):
                last_minute = now
                self.dirty = True  # keep the clock moving
            if self.dirty and watched:
                self.draw()
            if now - last_sample > 2:
                last_sample = now
                try:
                    samples.append(self.ps.milliamps())
                except OSError:
                    pass
            if now >= deadline and not self.working() and not self.web and not self.message:
                if not (self.stay or usb_tethered()):
                    break
                deadline = now + 30
            time.sleep(0.1)
        self.goodnight(samples)

    def goodnight(self, samples):
        if self.web:
            self.stop_webmap()
        self.menu = {"where": None, "hi": 0}
        self.message = None
        try:
            low = self.ps.battery() <= C.LOW_BATTERY and not self.ps.plugged()
        except OSError:
            low = False
        if low:
            self.message = "BATTERY LOW! CHARGE ME"
        self.s["ui"]["page"] = self.page
        self.draw(full=True)  # a clean full refresh: this picture stays while the Pi is off
        self.disp.sleep()
        wake = guide.next_wake(self.s)
        self.s["sched"]["alarm_at"] = int(wake.timestamp())
        self.store.save()
        log_power(self.ps, samples)
        if low:
            self.ps.disable_alarm()  # only the button wakes us
            log("battery low: alarm disabled")
        else:
            self.ps.set_alarm(wake)
        log("sleeping until", wake.isoformat())


def log_power(ps, samples):
    """One CSV row per wake, so real battery life can be worked out later."""
    path = os.path.join(C.DATA_DIR, "power.csv")
    try:
        up = float(open("/proc/uptime").read().split()[0])
        new = not os.path.exists(path)
        with open(path, "a") as f:
            if new:
                f.write("utc,uptime_s,avg_ma,max_ma,battery_pct,mv,plugged\n")
            avg = sum(samples) / len(samples) if samples else 0
            f.write(f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%S},{up:.0f},{avg:.0f},"
                    f"{max(samples, default=0)},{ps.battery()},{ps.millivolts()},{int(ps.plugged())}\n")
    except OSError as e:
        log("power log failed:", e)


def sync_clock_from_rtc(ps):
    from .hw import wait_for_rtc_sane
    t = wait_for_rtc_sane(ps)
    if t is None:
        log("RTC not set; trusting the system clock", datetime.now(timezone.utc))
        return
    subprocess.run(["date", "-u", "-s", "@%d" % int(t.timestamp())], check=False, stdout=subprocess.DEVNULL)
    log("clock from RTC:", t.isoformat())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stay", action="store_true", help="never power off")
    ap.add_argument("--sim", metavar="PNG", help="run on a Mac: frames go to this PNG, type s/d/l + Enter")
    args = ap.parse_args()

    store = guide.Store()
    secrets = C.secrets()
    rotation = store.s["ui"].get("rotation")
    rotation = C.ROTATION if rotation is None else rotation
    if args.sim:
        from .hw import SimDisplay, SimSugar
        ps, disp = SimSugar(), SimDisplay(args.sim, rotation)
        alarm = False
    else:
        from .hw import Display, PiSugar
        ps = PiSugar()
        try:
            ps.enable_soft_poweroff()
        except OSError as e:
            log("soft power-off not enabled:", e)
        sync_clock_from_rtc(ps)
        guide.clock_hook = ps.set_rtc
        disp = Display(rotation)
        alarm_at = store.s["sched"].get("alarm_at") or 0
        alarm = abs(time.time() - alarm_at) < 240
    app = App(ps, disp, store, secrets, stay=args.stay or bool(args.sim))
    app.run(alarm)
    if not args.sim and not args.stay:
        ps.cut_power_in(C.POWER_CUT_DELAY_S)
        subprocess.run(["systemctl", "poweroff"], check=False)


if __name__ == "__main__":
    sys.exit(main())

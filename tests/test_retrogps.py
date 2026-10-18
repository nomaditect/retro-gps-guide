"""Run with: python3 -m unittest discover tests   (needs Pillow)."""
import os
import sys
import tempfile
import time
import unittest
import unittest.mock
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))

from retrogps import geo, guide, net, screens  # noqa: E402
from retrogps.main import App  # noqa: E402

IW = """BSS 10:20:30:40:50:60(on wlan0)
\tlast seen: 120 ms ago
\tsignal: -71.00 dBm
\tSSID: Cafe
BSS 12:20:30:40:50:61(on wlan0) -- associated
\tsignal: -40.00 dBm
\tSSID: Simon Builds
BSS a0:20:30:40:50:62(on wlan0)
\tsignal: -55.00 dBm
\tSSID: Library_nomap
BSS b0:20:30:40:50:63(on wlan0)
\tsignal: -60.00 dBm
\tSSID: Museum
"""


class Geo(unittest.TestCase):
    def test_distance_and_bearing(self):
        self.assertAlmostEqual(geo.distance_m(51.0, -114.0, 51.01, -114.0), 1112, delta=2)
        self.assertEqual(geo.bearing_deg(51.0, -114.0, 51.01, -114.0), 0)
        self.assertEqual(geo.bearing_deg(51.0, -114.0, 51.0, -113.99), 90)

    def test_garmin_coords(self):
        self.assertEqual(geo.fmt_coord(51.1784, True), "N 51°10.704'")
        self.assertEqual(geo.fmt_coord(-115.5708, False), "W115°34.248'")
        self.assertEqual(geo.fmt_coord(-0.99999999, True), "S 01°00.000'")

    def test_travel_time(self):
        self.assertEqual(geo.travel(400, 80, 600, 3000), "5min")
        self.assertEqual(geo.travel(4500, 80, 600, 3000), "8min drive")
        self.assertEqual(geo.travel(60000, 80, 600, 3000), "1h40 drive")

    def test_compass(self):
        self.assertEqual([geo.compass(d) for d in (0, 44, 90, 200, 350)], ["N", "NE", "E", "S", "N"])


class Net(unittest.TestCase):
    def test_parse_iw_sorted_and_filtered(self):
        aps = net.parse_iw(IW)
        self.assertEqual([a[2] for a in aps], [-40, -55, -60, -71])
        macs = [a["macAddress"] for a in net.for_location(aps)]
        # the hotspot (locally administered MAC) and the _nomap network are left out
        self.assertEqual(macs, ["b0:20:30:40:50:63", "10:20:30:40:50:60"])

    def test_parse_nmcli(self):
        aps = net.parse_nmcli("AA\\:BB\\:CC\\:DD\\:EE\\:FF:Home:80\n")
        self.assertEqual(aps, [("aa:bb:cc:dd:ee:ff", "Home", -60)])


class Schedule(unittest.TestCase):
    def test_next_slot_moves_through_the_day(self):
        z = ZoneInfo("America/Vancouver")
        self.assertEqual(guide.next_slot(datetime(2026, 10, 18, 7, 0, tzinfo=z)).hour, 10)
        nxt = guide.next_slot(datetime(2026, 10, 18, 21, 0, tzinfo=z))
        self.assertEqual((nxt.day, nxt.hour), (19, 6))

    def test_retries_then_gives_up(self):
        with tempfile.TemporaryDirectory() as d:
            st = guide.Store(d)
            for _ in range(3):
                guide.reschedule(st, False, "NO WI-FI")
                self.assertTrue(st.s["sched"]["retry_at"])
            guide.reschedule(st, False, "NO WI-FI")
            self.assertEqual(st.s["sched"]["retry_at"], 0)
            self.assertIn("RETRY", st.s["sched"]["status"])

    def test_no_breadcrumb_wakes_at_night(self):
        s = guide.new_state()
        s["guide"] = {"tz": "UTC", "updated_at": 0}
        night = datetime(2026, 10, 18, 23, 30, tzinfo=ZoneInfo("UTC")).timestamp()
        s["sched"].update(next_update=night + 6.5 * 3600, next_track=night + 1800)
        self.assertEqual(guide.next_wake(s, night).hour, 6)


class Trip(unittest.TestCase):
    def test_jitter_is_ignored_and_real_moves_count(self):
        with tempfile.TemporaryDirectory() as d:
            st = guide.Store(d)
            guide.log_fix(st, 1, 51.0, -114.0, 20, 1)
            guide.log_fix(st, 2, 51.0002, -114.0, 20, 0)   # 22 m: inside the error circles
            self.assertEqual(st.s["trip"]["km"], 0)
            guide.log_fix(st, 3, 51.1, -114.0, 20, 2)
            self.assertAlmostEqual(st.s["trip"]["km"], 11.1, delta=0.1)
            guide.log_fix(st, 4, 49.0, -123.0, 25000, 0)    # an IP guess: logged, not counted
            self.assertAlmostEqual(st.s["trip"]["km"], 11.1, delta=0.1)
            self.assertEqual(len(st.read(st.fixes)), 4)

    def test_candidates_rank_local_over_chains(self):
        c = guide.Candidates(51.0, -114.0)
        c.add("coffee", "Tim Hortons", 51.0005, -114.0, "", 300)
        c.add("coffee", "Tiny Local", 51.0010, -114.0, "", 0)
        c.add("coffee", "Tiny Local", 51.0010, -114.0, "", 0)   # duplicate
        c.add("coffee", "Far Away", 51.05, -114.0, "", 0)       # beyond walking distance
        self.assertEqual([p["name"] for p in c.best()["coffee"]], ["Tiny Local", "Tim Hortons"])

    def test_craft_breweries_beat_pubs_and_chains(self):
        c = guide.Candidates(51.0, -114.0)
        for name, tags, cats, chain in (
                ("The Canadian Brewhouse", {"amenity": "pub"}, [], True),
                ("Rose and Crown", {"amenity": "pub"}, [], False),
                ("Cocktail Lounge", {"amenity": "bar"}, [], False),          # left out
                ("Steamworks", {"amenity": "pub", "microbrewery": "yes"}, [], False),
                ("Banff Ave Brewing Company", {"amenity": "pub"}, [], False)):
            ranked = guide.beer_rank(tags, cats, name, chain)
            if ranked:
                c.add("beer", name, 51.001, -114.0, *ranked)
        self.assertEqual([p["name"] for p in c.best()["beer"]],
                         ["Steamworks", "Banff Ave Brewing Company", "Rose and Crown", "The Canadian Brewhouse"])

    def test_crossfit_first_then_gyms_no_studios(self):
        c = guide.Candidates(51.0, -114.0)
        for name, tags, chain in (("World Gym", {}, True), ("Hot Yoga Loft", {}, False),
                                  ("Iron Barbell Club", {}, False), ("Dynasty Gym/Palace", {"sport": "crossfit;fitness"}, False),
                                  ("Cross Fit Pyro", {}, False)):
            ranked = guide.gym_rank(tags, name, chain)
            if ranked:
                c.add("gym", name, 51.02, -114.0, *ranked)
        self.assertEqual([p["name"] for p in c.best()["gym"]],
                         ["Dynasty Gym/Palace", "Cross Fit Pyro", "Iron Barbell Club", "World Gym"])

    def test_exports(self):
        with tempfile.TemporaryDirectory() as d:
            st = guide.Store(d)
            guide.log_fix(st, 1, 51.0, -114.0, 20, 1)
            guide.log_fix(st, 9000, 51.1, -114.0, 20, 2)
            st.append(st.wpts, {"num": 1, "t": 1, "lat": 51.0, "lon": -114.0, "area": "A & B",
                                "places": {"coffee": [{"name": "Café", "dist": 50}]}})
            gj = guide.geojson(st)
            self.assertEqual([f["geometry"]["type"] for f in gj["features"]], ["LineString", "Point"])
            self.assertIn("A &amp; B", guide.gpx(st))


class FakeSugar:
    def __init__(self, gestures=()):
        self.gestures = list(gestures)

    def tap(self):
        return self.gestures.pop(0) if self.gestures else None

    def battery(self):
        return 80

    def plugged(self):
        return False

    def soft_poweroff_requested(self):
        return False

    def milliamps(self):
        return 100

    def millivolts(self):
        return 3900

    def __getattr__(self, name):
        return lambda *a, **k: None


class FakeDisplay:
    rotate = 0

    def __init__(self):
        self.frames = 0

    def full(self, img):
        self.frames += 1

    def show(self, img, n=20):
        self.frames += 1

    def sleep(self):
        pass


class UI(unittest.TestCase):
    def setUp(self):
        import preview
        self.tmp = tempfile.TemporaryDirectory()
        self.store = guide.Store(self.tmp.name)
        self.store.s.update(preview.sample_state())
        self.app = App(FakeSugar(), FakeDisplay(), self.store, {"wifi": [], "keys": {}, "github": {}})
        self.app.start_sync = lambda watched=True: setattr(self, "synced", True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_page_and_menu_renders(self):
        for p in screens.PAGES:
            self.assertEqual(screens.render(self.store.s, {"page": p}).size, (122, 250))
            self.assertEqual(screens.render(guide.new_state(), {"page": p}).size, (122, 250))
        for where in ("menu", "waypoints", "setup", "confirm", "webmap"):
            screens.render(self.store.s, {"page": "menu", "menu": {"where": where, "hi": 1}})

    def test_tap_cycles_pages(self):
        self.app.page = 0
        for _ in screens.PAGES:
            self.app.handle("single")
        self.assertEqual(self.app.page, 0)

    def test_hold_marks(self):
        self.app.handle("long")
        self.assertTrue(getattr(self, "synced", False))

    def test_nearest_double_tap_sets_goto(self):
        self.app.page = screens.PAGES.index("food")
        self.app.handle("double")
        self.assertEqual(self.store.s["ui"]["dest"]["kind"], "food")
        first = self.store.s["ui"]["dest"]["name"]
        self.app.handle("double")
        self.assertNotEqual(self.store.s["ui"]["dest"]["name"], first)

    def test_menu_navigation(self):
        self.app.page = screens.PAGES.index("menu")
        self.app.handle("double")                      # open the menu
        self.assertEqual(self.app.menu["where"], "menu")
        self.app.handle("single")
        self.app.handle("single")
        self.app.handle("single")                      # down to SETUP
        self.app.handle("double")
        self.assertEqual(self.app.menu["where"], "setup")
        self.app.handle("long")                        # back
        self.assertEqual(self.app.menu["where"], "menu")
        self.app.handle("long")
        self.assertIsNone(self.app.menu["where"])

    def test_new_trip_needs_confirming(self):
        self.store.append(self.store.wpts, {"num": 1, "t": 1, "lat": 1, "lon": 1})
        self.app.menu = {"where": "setup", "hi": 2}
        self.app.handle("double")                      # NEW TRIP -> confirm, NO highlighted
        self.app.handle("double")
        self.assertEqual(self.store.s["wpt_num"], 12)
        self.app.menu = {"where": "confirm", "hi": 1}  # YES
        self.app.handle("double")
        self.assertEqual(self.store.s["wpt_num"], 0)
        self.assertEqual(self.store.read(self.store.wpts), [])

    def test_waypoint_goto(self):
        self.store.append(self.store.wpts, {"num": 3, "t": 1, "lat": 50.0, "lon": -119.0, "area": "Kelowna"})
        self.app.wpts = self.store.read(self.store.wpts)
        self.app.menu = {"where": "waypoints", "hi": 0}
        self.app.handle("double")
        self.assertEqual(screens.PAGES[self.app.page], "pointer")
        self.assertEqual(self.store.s["ui"]["dest"]["kind"], "wpt")

    def test_scheduled_wake_powers_off_by_itself(self):
        self.store.s["sched"].update(next_update=time.time() + 3600, next_track=time.time() + 3600)
        start = time.monotonic()
        with unittest.mock.patch("retrogps.main.usb_tethered", return_value=False):  # even on a plugged-in Pi
            self.app.run(alarm_wake=True)
        self.assertLess(time.monotonic() - start, 2)
        self.assertIn("alarm_at", self.store.s["sched"])


if __name__ == "__main__":
    unittest.main()

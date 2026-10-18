"""Draws every page with made-up data (a stop in Banff), so the layout can be checked on a Mac.
Usage: python3 tools/preview.py [out.png]   (needs Pillow; qrcode optional)"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from PIL import Image  # noqa: E402

from retrogps import guide, screens  # noqa: E402

NOW = int(time.time())


def sample_state():
    s = guide.new_state()
    lat, lon = 51.1784, -115.5708

    def p(name, info, dlat, dlon):
        la, lo = lat + dlat, lon + dlon
        from retrogps import geo
        return {"name": name, "info": info, "lat": la, "lon": lo,
                "dist": round(geo.distance_m(lat, lon, la, lo)), "bearing": geo.bearing_deg(lat, lon, la, lo)}

    s["guide"] = {
        "lat": lat, "lon": lon, "accuracy": 18, "updated_at": NOW - 1800, "tz": "America/Edmonton",
        "area": "Banff Avenue", "city": "Banff", "province": "AB", "country": "CA",
        "temp": -3.4, "code": 73, "is_day": True, "hi": 1, "lo": -8, "elevation": 1383,
        "sunrise": "07:58", "sunset": "18:31",
        "forecast": [{"date": "2026-10-19", "code": 2, "hi": 4, "lo": -6},
                     {"date": "2026-10-20", "code": 0, "hi": 7, "lo": -4},
                     {"date": "2026-10-21", "code": 61, "hi": 6, "lo": 0}],
        "places": {
            "coffee": [p("Whitebark Café", "", 0.0012, 0.0010), p("Wild Flour Bakery", "", -0.0016, 0.0021),
                       p("Evelyn's Coffee Bar", "", 0.0030, -0.0005), p("Tim Hortons", "", -0.004, -0.003)],
            "food": [p("The Bison Restaurant & Terrace", "regional", 0.0008, -0.0015),
                     p("Park Distillery", "canadian", 0.0021, 0.0002),
                     p("Block Kitchen + Bar", "tapas", -0.0011, 0.0030),
                     p("Nourish Bistro", "vegetarian", 0.0036, 0.0019)],
            "beer": [p("Banff Ave Brewing Company", "brewery", 0.0009, 0.0006),
                     p("Three Bears Brewery", "brewery", -0.0014, 0.0011),
                     p("Waldhaus Pub & Biergarten", "pub", -0.0072, 0.0050),
                     p("The Canadian Brewhouse", "chain", 0.0004, -0.0008)],
            "gym": [p("Bow Valley CrossFit", "crossfit", 0.0310, 0.0420),
                    p("Banff Fitness Studio", "gym", 0.0021, -0.0012)],
            "todo": [p("Cave and Basin National Historic Site", "museum", -0.006, -0.012),
                     p("Bow Falls", "viewpoint", -0.008, 0.006), p("Banff Park Museum", "museum", -0.003, 0.001),
                     p("Central Park", "park", -0.002, -0.003)],
        },
    }
    s["wpt_num"] = 12
    s["trip"].update(km=1342.6, start=NOW - 9 * 86400, provinces=["BC", "AB"], max_elev=2088, min_elev=4)
    s["pts"] = [[49.28, -123.12], [49.70, -123.15], [50.12, -122.95], [50.67, -120.33], [51.0, -118.2],
                [51.29, -116.9], [51.18, -115.57]]
    s["last_scan"] = {"t": NOW - 1800, "rssi": [-48, -55, -61, -67, -72, -79, -84, -90], "count": 14}
    s["sched"].update(next_update=NOW + 4 * 3600)
    s["ui"]["dest"] = dict(s["guide"]["places"]["coffee"][0], kind="coffee")
    s["ui"]["saying"] = 20
    return s


def frames():
    s = sample_state()
    wpts = [{"num": 11, "lat": 51.29, "lon": -116.9, "area": "Field", "when": "Fri 16 Oct 16:00"},
            {"num": 12, "lat": 51.1784, "lon": -115.5708, "area": "Banff Avenue", "when": "Sat 17 Oct 10:00"}]
    ctx = {"battery": 74, "plugged": False, "wpts": wpts}
    out = [(pg, screens.render(s, dict(ctx, page=pg))) for pg in screens.PAGES]
    s2 = sample_state()
    s2["ui"]["fields"] = 1
    out.append(("trip 2", screens.render(s2, dict(ctx, page="trip"))))
    s2["ui"]["zoom"] = 7
    out.append(("map 100km", screens.render(s2, dict(ctx, page="map"))))
    out.append(("menu open", screens.render(s, dict(ctx, page="menu", menu={"where": "menu", "hi": 1}))))
    out.append(("waypoints", screens.render(s, dict(ctx, menu={"where": "waypoints", "hi": 0}))))
    out.append(("web map", screens.render(s, dict(ctx, menu={"where": "webmap"}, url="http://172.20.10.4/"))))
    out.append(("syncing", screens.render(s, dict(ctx, page="sky", busy="LOCATING"))))
    out.append(("marked", screens.render(s, dict(ctx, page="mark", message="WAYPOINT 012 MARKED"))))
    empty = guide.new_state()
    out.append(("first boot", screens.render(empty, dict(ctx, page="sky"))))
    return out


def sheet(frames, scale=2, cols=6):
    w, h = screens.W * scale, screens.H * scale
    rows = (len(frames) + cols - 1) // cols
    img = Image.new("RGB", (cols * (w + 16) + 16, rows * (h + 16) + 16), (90, 90, 90))
    for i, (_name, f) in enumerate(frames):
        x, y = 16 + (i % cols) * (w + 16), 16 + (i // cols) * (h + 16)
        lcd = f.convert("RGB").resize((w, h), Image.NEAREST)
        img.paste(lcd, (x, y))
    return img


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "preview.png"
    sheet(frames()).save(out)
    print("wrote", out)

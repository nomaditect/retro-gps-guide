"""Every page, drawn at 122x250 in the style of the Garmin eTrex H: boxed fields, grey bars
(dithered here, since e-ink is pure black and white) and a chunky pixel font."""
import math
import os
import time
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

from . import art, geo
from . import config as C
from . import guide
from .sayings import SAYINGS

W, H = C.W, C.H
PAGES = ("mark", "sky", "map", "waypoint", "pointer", "trip", "weather", "coffee", "food", "beer", "todo", "gym", "eh", "menu")
MENU_ITEMS = ("MARK", "WAYPOINTS", "WEB MAP", "SETUP")
SETUP_ITEMS = ("SYNC NOW", "ROTATE SCREEN", "NEW TRIP", "SLEEP NOW")
ZOOMS = (None, 200, 500, 1000, 2000, 5000, 20000, 100000, 500000)  # metres per 100 px; None = auto
TITLES = {"coffee": "COFFEE", "food": "FOOD", "beer": "BEER", "todo": "TO DO", "gym": "CROSSFIT"}

_fonts = {}


def font(size):
    if size not in _fonts:
        _fonts[size] = ImageFont.truetype(os.path.join(C.ASSETS, "VT323-Regular.ttf"), size)
    return _fonts[size]


def clean(s):
    """Our pixel font covers Latin-1: straighten curly quotes, drop emoji and the like."""
    s = str(s or "").translate({0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"', 0x2013: "-", 0x2014: "-"})
    return "".join(ch for ch in s if ord(ch) < 0x100 and ch.isprintable())


class Canvas:
    def __init__(self):
        self.img = Image.new("1", (W, H), 1)
        self.d = ImageDraw.Draw(self.img)
        self.d.fontmode = "1"  # no anti-aliasing: crisp pixels on e-ink

    # ---- text (y is the baseline)
    def tw(self, s, size):
        return round(self.d.textlength(clean(s), font=font(size)))

    def text(self, x, y, s, size, fill=0, bold=False):
        s = clean(s)
        self.d.text((x, y), s, font=font(size), fill=fill, anchor="ls")
        if bold:
            self.d.text((x + 1, y), s, font=font(size), fill=fill, anchor="ls")

    def center(self, y, s, size, fill=0, bold=False, x0=0, x1=W):
        self.text(x0 + (x1 - x0 - self.tw(s, size) - bold) // 2, y, s, size, fill, bold)

    def fit(self, s, size, max_w):
        s = clean(s)
        if self.tw(s, size) <= max_w:
            return s
        while len(s) > 1 and self.tw(s + ".", size) > max_w:
            s = s[:-1]
        return s.rstrip() + "."

    def wrap(self, s, size, max_w, max_lines=99):
        lines, line = [], ""
        for word in clean(s).split():
            trial = (line + " " + word).strip()
            if self.tw(trial, size) <= max_w or not line:
                line = trial
            else:
                lines.append(line)
                line = word
        if line:
            lines.append(line)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = self.fit(lines[-1] + "...", size, max_w)
        return [self.fit(l, size, max_w) for l in lines]

    # ---- shapes
    def rect(self, x0, y0, x1, y1, fill=None, outline=0, width=1):
        self.d.rectangle((x0, y0, x1, y1), fill=fill, outline=outline, width=width)

    def grey(self, x0, y0, x1, y1, light=True):
        """Dithered grey: 25% (light) or 50%. Used where the eTrex LCD had grey."""
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                if (x % 2 == 0 and y % 2 == 0) if light else ((x + y) % 2 == 0):
                    self.img.putpixel((x, y), 0)

    def dots(self, x0, y, x1, step=3):
        for x in range(x0, x1, step):
            self.img.putpixel((x, y), 0)

    def dotted_line(self, x0, y0, x1, y1, step=4):
        n = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
        for i in range(n + 1):
            x, y = round(x0 + (x1 - x0) * i / n), round(y0 + (y1 - y0) * i / n)
            if 0 <= x < W and 0 <= y < H:
                self.d.rectangle((x, y, x + 1, y + 1), fill=0)

    def blit(self, rows, x, y, scale=1, color=0):
        art.blit(self.d, rows, x, y, scale, color)

    def poly_rotated(self, pts, cx, cy, deg, fill=0, outline=None):
        a = math.radians(deg)
        s, c = math.sin(a), math.cos(a)
        self.d.polygon([(cx + x * c - y * s, cy + x * s + y * c) for x, y in pts], fill=fill, outline=outline)


# ---------- shared pieces ----------

def header(c, title, symbol=None):
    """eTrex grey title bar."""
    c.grey(0, 0, W - 1, 16)
    c.rect(0, 0, W - 1, 16)
    tw = c.tw(title, 20) + (13 if symbol else 0)
    x = (W - tw) // 2
    c.rect(x - 3, 2, x + tw + 2, 14, fill=1, outline=None)
    if symbol:
        c.blit(symbol, x, 4)
        x += 13
    c.text(x, 14, title, 20)


def small_arrow(c, cx, cy, deg):
    c.poly_rotated([(0, -6), (-4, 5), (4, 5)], cx, cy, deg)
    c.poly_rotated([(-4, 5), (4, 5), (0, 2)], cx, cy, deg, fill=1)


def battery_icon(c, x, y, pct, plugged):
    c.rect(x + 2, y, x + 6, y + 1, fill=0)
    c.rect(x, y + 2, x + 8, y + 17)
    if pct is not None:
        h = round(13 * max(0, min(100, pct)) / 100)
        if h:
            c.rect(x + 2, y + 16 - h, x + 6, y + 15, fill=0)
    if plugged:  # a little lightning bolt
        c.d.polygon([(x + 5, y + 4), (x + 2, y + 10), (x + 4, y + 10), (x + 3, y + 15), (x + 7, y + 8),
                     (x + 5, y + 8)], fill=1, outline=0)


def message_box(c, msg):
    """eTrex on-screen message: a framed box in the middle of the page."""
    lines = c.wrap(msg, 20, W - 24)
    h = 16 * len(lines) + 14
    y0 = (H - h) // 2
    c.rect(6, y0, W - 7, y0 + h, fill=1, width=3)
    c.rect(10, y0 + 4, W - 11, y0 + h - 4)
    for i, l in enumerate(lines):
        c.center(y0 + 21 + 16 * i, l, 20)


def busy_badge(c, text):
    tw = c.tw(text, 16)
    c.rect(W - tw - 7, 0, W - 1, 13, fill=0)
    c.text(W - tw - 4, 11, text, 16, fill=1)


def no_data(c, y):
    c.center(y, "NO DATA YET", 20)
    c.center(y + 22, "Turn on your", 16)
    c.center(y + 36, "hotspot, then", 16)
    c.center(y + 50, "HOLD to mark", 16)


def local(state, ts, fmt):
    return datetime.fromtimestamp(ts, guide.tz(state)).strftime(fmt)


# ---------- pages ----------

def page_mark(c, s, ctx):
    """The eTrex "mark waypoint" man, planting this stop's flag."""
    a = art.mark_art()
    x0, y0 = (W - a.width) // 2, 14
    c.img.paste(a, (x0, y0))
    num = f"{s['wpt_num']:03d}" if s.get("guide") else "---"
    fx, fy = art.MARK_FLAG_TEXT
    c.text(x0 + fx - c.tw(num, 20) // 2, y0 + fy, num, 20)
    g = s.get("guide")
    if g:
        c.center(214, c.fit(g.get("area", ""), 20, W - 6), 20)
        c.center(230, local(s, g["updated_at"], "%a %d %b %H:%M").upper(), 16)
    else:
        c.center(218, "HOLD TO MARK", 20)


SAT_POS = ((10, 74), (40, 66), (71, 66), (101, 74), (4, 104), (31, 98), (80, 98), (107, 104))


def page_sky(c, s, ctx):
    """SkyView, with the Wi-Fi networks we can hear standing in for satellites."""
    g, sc, scan = s.get("guide"), s["sched"], s["last_scan"]
    c.rect(0, 0, W - 1, 58, width=2)
    if ctx.get("busy"):
        lines = ("WAIT...", ctx["busy"], "", "")
    elif sc.get("status") and not sc["status"].startswith("ROUGH"):
        a, _, b = sc["status"].partition(", ")
        lines = (a, b, "", "")
    elif not g:
        lines = ("NO FIX YET", "HOLD TO", "MARK", "")
    else:
        acc = g["accuracy"]
        lines = ("READY" if acc <= C.ROUGH_FIX_M else "ROUGH FIX", "TO NAVIGATE" if acc <= C.ROUGH_FIX_M
                 else "MOVE ON", "ACCURACY:", "±" + geo.fmt_dist(acc))
    for i, l in enumerate(lines):
        c.center(15 + 13 * i, l, 16)

    rssi = scan.get("rssi") or []
    ready = bool(g) and not ctx.get("busy")
    mx, my = 58, 166
    for i, (x, y) in enumerate(SAT_POS[:len(rssi)]):
        if ready and rssi[i] > -82:
            c.dotted_line(x + 5, y + 7, mx + 3, my - 2, 5)
        c.blit(art.SATELLITE, x, y)
    # the man on his hill
    c.d.pieslice((22, 176, 100, 230), 180, 360, fill=1, outline=0)
    c.grey(23, 178, 99, 202)
    c.d.arc((22, 176, 100, 230), 180, 360, fill=0)
    c.blit(art.MAN, mx, my, 1)
    c.rect(0, 203, W - 1, 249, fill=1, outline=None)
    c.grey(0, 204, W - 1, 218)
    c.rect(2, 206, 46, 217, fill=1, outline=None)
    c.text(4, 216, "SIGNAL", 16)
    c.rect(0, 220, W - 1, 249, width=2)
    if rssi:
        top = sorted(rssi, reverse=True)[:4]
        strength = max(0.0, min(1.0, (sum(top) / len(top) + 95) / 50))
        fill = 1.0 if ready and g["accuracy"] <= 100 else strength
        if fill > 0.02:
            c.rect(4, 224, 4 + round((W - 9) * fill), 245, fill=0, outline=None)
    label = f"{scan.get('count', 0)} WI-FI" if scan.get("t") else "NO SCAN"
    tw = c.tw(label, 16)
    c.rect(W - tw - 6, 206, W - 3, 217, fill=1, outline=None)
    c.text(W - tw - 4, 216, label, 16)


def page_map(c, s, ctx):
    """Map page: you in the middle, the trail behind, waypoints and nearby places, north up."""
    g = s.get("guide")
    c.rect(0, 0, W - 1, H - 1)
    if not g:
        no_data(c, 110)
        return
    lat0, lon0 = g["lat"], g["lon"]
    places = g.get("places") or {}
    dest = s["ui"].get("dest")
    zoom = ZOOMS[s["ui"].get("zoom", 0) % len(ZOOMS)]
    if zoom is None:  # auto: fit nearby places and the destination
        far = [p["dist"] for k in guide.KINDS for p in places.get(k, []) if p["dist"] <= C.ACTIVITY_RADIUS_M]
        if dest:
            far.append(geo.distance_m(lat0, lon0, dest["lat"], dest["lon"]))
        span = max(far + [300]) * 2.3
        m_per_px = span / 110
    else:
        m_per_px = zoom / 100
    cx, cy = W // 2, 132

    def xy(lat, lon):
        e, n = geo.offset_m(lat0, lon0, lat, lon)
        return round(cx + e / m_per_px), round(cy - n / m_per_px)

    # trail (track log): a thick dotted line, like the eTrex's grey one
    pts = [xy(a, b) for a, b in s.get("pts", [])]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        c.dotted_line(x0, y0, x1, y1, 2)
    taken = [(cx - 8, cy - 8, cx + 8, cy + 12)]

    def label(x, y, text):
        tw = c.tw(text, 16)
        lx = min(max(x - tw // 2, 2), W - tw - 2)
        box = (lx - 1, y - 11, lx + tw + 1, y + 1)
        if any(not (box[2] < t[0] or box[0] > t[2] or box[3] < t[1] or box[1] > t[3]) for t in taken):
            return
        taken.append(box)
        c.rect(*box, fill=1, outline=None)
        c.text(lx, y, text, 16)

    if dest:  # path to destination
        dx, dy = xy(dest["lat"], dest["lon"])
        c.d.line((cx, cy, dx, dy), fill=0, width=1)
    for w in ctx.get("wpts", [])[-40:]:
        x, y = xy(w["lat"], w["lon"])
        if 4 <= x < W - 10 and 30 <= y < H - 26 and (x, y) != (cx, cy):
            c.blit(art.FLAG, x, y - 8)
            label(x + 3, y - 10, f"{w['num']:03d}")
    shown = []
    for k in guide.KINDS:
        for p in places.get(k, []):
            x, y = xy(p["lat"], p["lon"])
            if 5 <= x < W - 5 and 32 <= y < H - 28:
                c.rect(x - 5, y - 5, x + 5, y + 5, fill=1, outline=None)
                c.blit(art.SYMBOLS[k], x - 4, y - 4)
                taken.append((x - 5, y - 5, x + 5, y + 5))
                shown.append((p, x, y))
    # label the nearest first, wherever there's room (symbols are placed first so labels avoid them)
    for p, x, y in sorted(shown, key=lambda t: t[0]["dist"]):
        words = clean(p["name"]).split()
        if words:
            label(x, y - 7, words[0][:7].upper())
    c.blit(art.MAN, cx - 3, cy - 5)
    # north pointer
    c.d.polygon([(13, 3), (3, 27), (13, 22), (23, 27)], fill=1, outline=0)
    c.text(10, 21, "N", 16)
    if zoom is None:
        c.text(W - c.tw("AUTO", 16) - 3, 12, "AUTO", 16)
    # scale bar
    nice = (20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000)
    m = next((v for v in reversed(nice) if v / m_per_px <= 60), nice[0])
    n = max(4, round(m / m_per_px))
    c.d.line((4, H - 6, 4 + n, H - 6), fill=0, width=2)
    c.d.line((4, H - 11, 4, H - 5), fill=0)
    c.d.line((4 + n, H - 11, 4 + n, H - 5), fill=0)
    c.text(8, H - 9, geo.fmt_dist(m), 16)


def track_plot(c, s, x0, y0, w, h):
    """The breadcrumb plot from the Retro Canada Guide: recent fixes, equal scale both ways."""
    c.rect(x0, y0, x0 + w - 1, y0 + h - 1)
    pts = s.get("pts") or []
    if not pts:
        return
    lats, lons = [p[0] for p in pts], [p[1] for p in pts]
    k = math.cos(math.radians((min(lats) + max(lats)) / 2))
    span = max((max(lats) - min(lats)) * 111320, (max(lons) - min(lons)) * 111320 * k, 400) * 1.15
    m_per_px = span / min(w - 8, h - 8)
    clat, clon = (min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2
    xy = [(x0 + w // 2 + round((lo - clon) * 111320 * k / m_per_px),
           y0 + h // 2 - round((la - clat) * 111320 / m_per_px)) for la, lo in pts]
    if len(xy) > 1:
        c.d.line(xy, fill=0)
    for x, y in xy:
        c.rect(x - 1, y - 1, x + 1, y + 1, fill=0, outline=None)
    x, y = xy[-1]  # you are here
    c.rect(x - 4, y - 4, x + 4, y + 4)
    nice = (50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000, 1000000)
    m = next((v for v in reversed(nice) if v / m_per_px <= 40), nice[0])
    n = max(4, round(m / m_per_px))
    bx, by = x0 + w - 6 - n, y0 + h - 5
    c.d.line((bx, by, bx + n, by), fill=0)
    c.d.line((bx, by - 3, bx, by), fill=0)
    c.d.line((bx + n, by - 3, bx + n, by), fill=0)
    lbl = geo.fmt_dist(m)
    c.text(bx + n - c.tw(lbl, 16), by - 3, lbl, 16)


def page_waypoint(c, s, ctx):
    """This stop in Garmin coordinates, plus the route so far."""
    g = s.get("guide")
    header(c, f"WPT {s['wpt_num']:03d}" if g else "WAYPOINT")
    if not g:
        no_data(c, 100)
        return
    c.text(4, 34, c.fit(g.get("area", ""), 20, W - 8), 20)
    for i, v in enumerate((geo.fmt_coord(g["lat"], True), geo.fmt_coord(g["lon"], False))):
        size = 24 if c.tw(v, 24) <= W - 4 else 20
        c.text(2, 58 + 22 * i, v, size, bold=size == 20)
    c.text(4, 100, f"ELEV {g['elevation']}m" if "elevation" in g else "ELEV ---", 16)
    acc = "±" + geo.fmt_dist(g["accuracy"])
    c.text(W - c.tw(acc, 16) - 4, 100, acc, 16)
    c.text(4, 114, "UPD " + local(s, g["updated_at"], "%d %b %H:%M").upper(), 16)
    track_plot(c, s, 0, 120, W, H - 120)
    t = s["trip"]["km"]
    c.text(5, 135, f"TRIP {t:,.0f}km", 16, bold=True)


def page_pointer(c, s, ctx):
    """Pointer page: a compass ring with a big arrow to the destination. The Pi has no compass,
    so the ring is north-up: turn until the N on the ring matches real north."""
    g, dest = s.get("guide"), s["ui"].get("dest")
    c.rect(0, 0, W - 1, 56, width=2)
    if not g or not dest:
        c.center(16, "NO DESTINATION", 16)
        c.center(32, "2x TAP on a", 16)
        c.center(46, "NEAREST page", 16)
        bearing, dist = None, None
    else:
        dist = geo.distance_m(g["lat"], g["lon"], dest["lat"], dest["lon"])
        bearing = geo.bearing_deg(g["lat"], g["lon"], dest["lat"], dest["lon"])
        name = dest.get("name") or "WAYPOINT"
        c.center(14, c.fit(name.upper(), 16, W - 8), 16)
        c.center(40, geo.fmt_dist(dist), 32, bold=True)
        togo = geo.travel(dist, C.WALK_M_PER_MIN, C.DRIVE_M_PER_MIN, C.DRIVE_OVER_M).upper()
        c.center(53, togo.replace(" DRIVE", " BY CAR") if "DRIVE" in togo else togo + " TO GO", 16)
    # ring
    c.grey(0, 58, W - 1, 192, light=True)
    cx, cy, r = W // 2, 125, 54
    c.d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=1, outline=0, width=2)
    for deg in range(0, 360, 30):
        a = math.radians(deg)
        inner = r - (7 if deg % 90 else 4)
        c.d.line((cx + inner * math.sin(a), cy - inner * math.cos(a), cx + (r - 1) * math.sin(a),
                  cy - (r - 1) * math.cos(a)), fill=0, width=2)
    for deg, ch in ((0, "N"), (90, "E"), (180, "S"), (270, "W")):
        a = math.radians(deg)
        x, y = cx + (r - 13) * math.sin(a), cy - (r - 13) * math.cos(a)
        c.text(round(x - c.tw(ch, 20) / 2), round(y + 6), ch, 20, bold=True)
    if bearing is not None:
        c.poly_rotated([(0, -36), (15, -8), (5, -11), (5, 28), (-5, 28), (-5, -11), (-15, -8)], cx, cy,
                       bearing)
        sym = art.SYMBOLS.get(dest.get("kind"), art.FLAG)
        a = math.radians(bearing)
        sx, sy = cx + (r + 1) * math.sin(a), cy - (r + 1) * math.cos(a)
        c.rect(round(sx) - 6, round(sy) - 6, round(sx) + 6, round(sy) + 6, fill=1)
        c.blit(sym, round(sx) - 4, round(sy) - 4)
    # selectable trip data box
    c.rect(0, 194, W - 1, H - 1, width=2)
    c.center(208, "BEARING", 16)
    c.center(240, f"{geo.compass(bearing)} {bearing:03d}°" if bearing is not None else "---", 32, bold=True)


def trip_fields(s, ctx):
    g, t = s.get("guide") or {}, s["trip"]
    if s["ui"].get("fields", 0) % 2 == 0:
        days = (int((time.time() - t["start"]) // 86400) + 1) if t.get("start") else 0
        provs = t.get("provinces") or []
        ptxt = " ".join(provs) if len(" ".join(provs)) <= 8 else str(len(provs))
        return (("TRIP ODOM", f"{t['km']:,.0f}km" if t["km"] >= 10 else f"{t['km']:.1f}km"),
                ("WAYPOINTS", f"{s['wpt_num']:03d}"),
                ("DAYS OUT", str(days)),
                ("ELEVATION", f"{g['elevation']}m" if "elevation" in g else "---"),
                ("PROVINCES", ptxt or "---"))
    sc = s["sched"]
    nxt = min(x for x in (sc["next_update"], sc["retry_at"] or 1e12) if x) if sc["next_update"] else None
    bat = ctx.get("battery")
    return (("SUNRISE", g.get("sunrise", "---")), ("SUNSET", g.get("sunset", "---")),
            ("NEXT MARK", local(s, nxt, "%H:%M") if nxt else "---"),
            ("BATTERY", f"{bat}%" if bat is not None else "---"),
            ("TIME", guide.local_now(s).strftime("%H:%M")))


def page_trip(c, s, ctx):
    """Trip Computer: five boxed fields. 2x tap swaps to the second set."""
    for i, (label, value) in enumerate(trip_fields(s, ctx)):
        y = i * 50
        c.rect(0, y, W - 1, y + 49, width=2)
        c.grey(2, y + 2, W - 3, y + 15)
        tw = c.tw(label, 16)
        c.rect((W - tw) // 2 - 3, y + 3, (W + tw) // 2 + 2, y + 14, fill=1, outline=None)
        c.center(y + 14, label, 16)
        size = 32 if c.tw(value, 32) <= W - 8 else 24
        c.center(y + 42, value, size, bold=True)


def page_weather(c, s, ctx):
    header(c, "WEATHER")
    g = s.get("guide")
    now = guide.local_now(s)
    c.text(4, 30, f"{geo.time_of_day(now.hour)} {now:%H:%M}", 16)
    if not g:
        no_data(c, 100)
        return
    area = g.get("area", "")
    c.text(4, 50, c.fit(area, 24 if c.tw(area, 24) <= W - 8 else 20, W - 8), 24 if c.tw(area, 24) <= W - 8 else 20)
    c.text(4, 64, c.fit(", ".join(x for x in (g.get("city"), g.get("province")) if x), 16, W - 8), 16)
    if "temp" in g:
        c.blit(art.weather_icon(g["code"]), 4, 72, 3)
        c.text(58, 112, f"{round(g['temp'])}°", 40, bold=True)
        c.text(4, 138, c.fit(geo.weather_text(g["code"]), 20, W - 8), 20)
        c.text(4, 154, f"HI {round(g['hi'])}°  LO {round(g['lo'])}°", 16)
        if g.get("sunrise"):
            c.text(4, 168, f"SUN {g['sunrise']} - {g['sunset']}", 16)
        c.d.line((0, 174, W - 1, 174), fill=0)
        for i, f in enumerate((g.get("forecast") or [])[:3]):
            x0 = i * 41
            if i:
                c.d.line((x0 - 1, 175, x0 - 1, 228), fill=0)
            day = datetime.strptime(f["date"], "%Y-%m-%d").strftime("%a").upper()
            c.center(188, day, 16, x0=x0, x1=x0 + 40)
            c.blit(art.weather_icon(f["code"]), x0 + 12, 192)
            c.center(224, f"{round(f['hi'])}/{round(f['lo'])}", 16, x0=x0, x1=x0 + 40)
    c.d.line((0, 230, W - 1, 230), fill=0)
    c.text(4, 245, "UPD " + local(s, g["updated_at"], "%a %H:%M").upper(), 16)


def page_places(c, s, ctx, kind):
    """Nearest: the closest few, with distance, walking time and an arrow pointing the way.
    2x tap picks the next one as the Pointer's destination."""
    header(c, TITLES[kind], art.SYMBOLS[kind])
    g = s.get("guide")
    if not g:
        no_data(c, 100)
        return
    if g["accuracy"] > C.ROUGH_FIX_M:
        for i, l in enumerate(("Not sure exactly", "where we are.", "", "HOLD to try", "again")):
            c.center(90 + 16 * i, l, 16)
        return
    places = (g.get("places") or {}).get(kind, [])
    if not places:
        far = guide.RADIUS[kind] > C.WALK_RADIUS_M
        for i, l in enumerate(("Nothing within" if not far else "Nothing listed",
                               "walking distance." if not far else "nearby.", "", "HOLD to update")):
            c.center(90 + 16 * i, l, 16)
        return
    dest = s["ui"].get("dest") or {}
    y = 20
    for i, p in enumerate(places):
        lines = c.wrap(p["name"], 20, W - 8, 2)
        h = 16 * len(lines) + 18
        if y + h > H:
            break
        chosen = dest.get("kind") == kind and dest.get("name") == p["name"]
        if chosen:
            c.rect(0, y, W - 1, y + 16 * len(lines) + 1, fill=0, outline=None)
        for j, l in enumerate(lines):
            c.text(4, y + 14 + 16 * j, l, 20, fill=1 if chosen else 0)
        yy = y + 16 * len(lines) + 15
        small_arrow(c, 8, yy - 5, p["bearing"])
        d = f"{geo.fmt_dist(p['dist'])} " + geo.travel(p["dist"], C.WALK_M_PER_MIN, C.DRIVE_M_PER_MIN,
                                                          C.DRIVE_OVER_M)
        c.text(17, yy, d, 16)
        if p.get("info"):
            x = 17 + c.tw(d, 16) + 6
            c.text(x, yy, c.fit(p["info"], 16, W - x - 2), 16)
        y += h
        if i < len(places) - 1:
            c.dots(4, y - 1, W - 4)
        y += 3


def page_eh(c, s, ctx):
    header(c, "EH?")
    if s["ui"].get("saying", -1) < 0:
        guide.pick_saying(s)
    say, means, _w, _t = SAYINGS[s["ui"]["saying"] % len(SAYINGS)]
    c.blit(art.LEAF, (W - 48) // 2, 24, 2)
    y = 96
    for l in c.wrap(say, 24, W - 6):
        c.center(y, l, 24, bold=True)
        y += 21
    c.dots(30, y - 8, W - 30, 4)
    y += 10
    for l in c.wrap(means, 16, W - 8):
        c.center(y, l, 16)
        y += 14


def menu_icon(c, item, x, y):
    if item == "MARK":
        c.blit(art.MAN, x, y + 4)
        c.blit(art.FLAG, x + 8, y + 2)
    elif item == "WAYPOINTS":
        c.blit(art.FLAG, x + 3, y + 3, 1)
        c.blit(art.FLAG, x + 9, y + 1)
    elif item == "WEB MAP":
        c.d.ellipse((x, y, x + 14, y + 14), outline=0)
        c.d.ellipse((x + 4, y, x + 10, y + 14), outline=0)
        c.d.line((x, y + 7, x + 14, y + 7), fill=0)
    else:  # SETUP: a spanner
        c.d.line((x + 3, y + 13, x + 10, y + 5), fill=0, width=3)
        c.d.ellipse((x + 7, y, x + 15, y + 8), fill=0)
        c.d.rectangle((x + 10, y, x + 12, y + 4), fill=1)


def page_menu(c, s, ctx):
    """Main Menu, eTrex style, with a reminder of what the one button does."""
    header(c, "MENU")
    m = ctx.get("menu") or {}
    active = m.get("where") == "menu"
    hi = m.get("hi", 0) if active else -1
    for i, item in enumerate(MENU_ITEMS):
        y = 18 + i * 30
        c.rect(0, y, W - 1, y + 29)
        if i == hi:
            c.rect(26, y + 5, W - 4, y + 24, fill=0, outline=None)
        menu_icon(c, item, 6, y + 7)
        c.text(30, y + 21, item, 20, fill=1 if i == hi else 0)
    keys = (("TAP", "DOWN"), ("2x", "ENTER"), ("HOLD", "BACK")) if active else \
           (("TAP", "NEXT PAGE"), ("2x", "OPEN MENU"), ("HOLD", "MARK"))
    for i, (k, v) in enumerate(keys):
        c.text(6, 156 + 15 * i, k, 16, bold=True)
        c.text(42, 156 + 15 * i, v, 16)
    c.grey(0, 204, W - 1, H - 1)
    c.rect(0, 204, W - 1, H - 1)
    c.rect(2, 206, W - 3, H - 3, fill=1, outline=None)
    battery_icon(c, 6, 214, ctx.get("battery"), ctx.get("plugged"))
    now = guide.local_now(s)
    c.text(22, 227, now.strftime("%H:%M"), 24, bold=True)
    c.text(22, 242, now.strftime("%d-%b-%y").upper(), 16)
    if ctx.get("battery") is not None:
        c.text(W - c.tw(f"{ctx['battery']}%", 16) - 5, 242, f"{ctx['battery']}%", 16)


def list_page(c, title, rows, hi, footer=None):
    """A scrolling eTrex list (waypoints, setup, confirm), highlight inverted."""
    header(c, title)
    per = 8 if not footer else 7
    first = max(0, min(hi - per // 2, len(rows) - per))
    for n, i in enumerate(range(first, min(len(rows), first + per))):
        y = 18 + n * 26
        if i == hi:
            c.rect(0, y, W - 1, y + 24, fill=0, outline=None)
        main, sub = rows[i] if isinstance(rows[i], tuple) else (rows[i], None)
        col = 1 if i == hi else 0
        if sub:
            c.text(4, y + 12, c.fit(main, 16, W - 8), 16, fill=col, bold=True)
            c.text(4, y + 23, c.fit(sub, 16, W - 8), 16, fill=col)
        else:
            c.text(4, y + 18, c.fit(main, 20, W - 8), 20, fill=col)
    if first > 0:
        c.d.polygon([(W - 9, 22), (W - 5, 17), (W - 1, 22)], fill=0)
    if first + per < len(rows):
        c.d.polygon([(W - 9, 222), (W - 5, 227), (W - 1, 222)], fill=0)
    if footer:
        for i, l in enumerate(footer):
            c.center(214 + 15 * i, l, 16)


def page_webmap(c, s, ctx):
    header(c, "WEB MAP")
    url = ctx.get("url")
    if not url:
        c.center(80, ctx.get("busy") or "NO WI-FI", 20)
        c.center(110, "Turn on your", 16)
        c.center(124, "hotspot", 16)
        c.center(240, "HOLD TO STOP", 16)
        return
    c.center(32, "On your phone,", 16)
    c.center(45, "same Wi-Fi:", 16)
    try:
        import qrcode
        q = qrcode.QRCode(border=0, error_correction=qrcode.constants.ERROR_CORRECT_L)
        q.add_data(url)
        q.make(fit=True)
        mtx = q.get_matrix()
        scale = max(1, min(4, 104 // len(mtx)))
        size = len(mtx) * scale
        x0, y0 = (W - size) // 2, 54 + (110 - size) // 2
        for j, row in enumerate(mtx):
            for i, v in enumerate(row):
                if v:
                    c.rect(x0 + i * scale, y0 + j * scale, x0 + i * scale + scale - 1,
                           y0 + j * scale + scale - 1, fill=0, outline=None)
    except ImportError:
        c.center(110, "(no QR library)", 16)
    c.center(184, url.replace("http://", ""), 20 if c.tw(url[7:], 20) <= W - 4 else 16)
    c.center(206, "Map + GPX download", 16)
    c.center(240, "HOLD TO STOP", 16)


# ---------- entry point ----------

def render(s, ctx):
    """One frame. ctx: page, battery, plugged, busy, message, menu, wpts, url."""
    c = Canvas()
    m = ctx.get("menu") or {}
    where = m.get("where")
    if where == "waypoints":
        wpts = ctx.get("wpts") or []
        rows = [(f"{w['num']:03d} {w.get('area', '')}", w.get("when", "")) for w in reversed(wpts)]
        list_page(c, "WAYPOINTS", rows or [("NONE YET", "HOLD to mark one")], m.get("hi", 0))
    elif where == "setup":
        list_page(c, "SETUP", list(SETUP_ITEMS), m.get("hi", 0))
    elif where == "confirm":
        list_page(c, "NEW TRIP?", ["NO", "YES"], m.get("hi", 0),
                  footer=("Starts a fresh", "log. The old one", "is kept on the SD."))
    elif where == "webmap":
        page_webmap(c, s, ctx)
    else:
        page = ctx.get("page", "mark")
        fn = {"mark": page_mark, "sky": page_sky, "map": page_map, "waypoint": page_waypoint, "pointer": page_pointer,
              "trip": page_trip, "weather": page_weather, "eh": page_eh, "menu": page_menu}.get(page)
        if fn:
            fn(c, s, ctx)
        else:
            page_places(c, s, ctx, page)
    if ctx.get("busy") and where != "webmap":
        busy_badge(c, "SYNC")
    if ctx.get("message"):
        message_box(c, ctx["message"])
    return c.img

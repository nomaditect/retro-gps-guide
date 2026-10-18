"""The trip: where we are, what's nearby, the log of every fix and waypoint, and the schedule.

Everything lives in one JSON state file plus two append-only logs (fixes and waypoints), so a
flat battery or a yanked SD card loses at most the update in progress."""
import base64
import json
import os
import random
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

from . import geo, net
from . import config as C
from .sayings import SAYINGS

KINDS = ("coffee", "food", "todo")
MAX_PTS, MAX_PENDING = 64, 48


def log(*a):
    print(*a, flush=True)


# ---------- state ----------

def new_state():
    return {
        "guide": None,
        "wpt_num": 0,
        "trip": {"km": 0.0, "last": None, "start": None, "provinces": [], "max_elev": None,
                 "min_elev": None},
        "pts": [],
        "pending": [],
        "sched": {"next_update": 0, "retry_at": 0, "retries": 0, "next_track": 0, "status": ""},
        "last_scan": {"t": 0, "rssi": [], "count": 0},
        "ui": {"page": 0, "dest": None, "zoom": 0, "fields": 0, "saying": -1, "rotation": None},
        "gh_sha": "",
    }


class Store:
    """The state plus a lock, because updates run in a background thread while you browse."""

    def __init__(self, data_dir=C.DATA_DIR):
        self.dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.path = os.path.join(data_dir, "state.json")
        self.fixes = os.path.join(data_dir, "fixes.jsonl")
        self.wpts = os.path.join(data_dir, "wpts.jsonl")
        self.lock = threading.RLock()
        self.s = new_state()
        try:
            with open(self.path) as f:
                loaded = json.load(f)
            for k, v in loaded.items():
                if isinstance(v, dict) and isinstance(self.s.get(k), dict):
                    self.s[k].update(v)
                else:
                    self.s[k] = v
        except (OSError, ValueError):
            pass

    def save(self):
        with self.lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.s, f)
            os.replace(tmp, self.path)

    def append(self, path, rec):
        with open(path, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def read(self, path):
        try:
            with open(path) as f:
                return [json.loads(l) for l in f if l.strip()]
        except OSError:
            return []

    def new_trip(self):
        with self.lock:
            for p in (self.fixes, self.wpts):
                if os.path.exists(p):
                    os.replace(p, p + time.strftime(".%Y%m%d-%H%M%S"))
            keep_ui = self.s["ui"]
            self.s = new_state()
            self.s["ui"].update(rotation=keep_ui.get("rotation"))
            self.save()


def tz(state):
    g = state.get("guide") or {}
    try:
        return ZoneInfo(g.get("tz") or C.DEFAULT_TZ)
    except Exception:
        return ZoneInfo(C.DEFAULT_TZ)


def local_now(state):
    return datetime.now(tz(state))


# ---------- the trip log ----------

def log_fix(store, t, lat, lon, acc, wpt):
    s = store.s
    store.append(store.fixes, {"t": int(t), "lat": round(lat, 6), "lon": round(lon, 6), "acc": acc,
                               "wpt": wpt})
    if acc > 2000:
        return  # IP-based guesses are too rough for the trip distance and the map
    trip = s["trip"]
    if trip["last"]:
        la, lo, la_acc = trip["last"]
        d = geo.distance_m(la, lo, lat, lon)
        if d > acc + la_acc:  # ignore jitter
            trip["km"] += d / 1000
    trip["last"] = [lat, lon, max(acc, 1)]
    s["pts"] = (s["pts"] + [[round(lat, 6), round(lon, 6)]])[-MAX_PTS:]


def queue_scan(store, aps):
    if len(aps) >= 2:
        s = store.s
        s["pending"] = (s["pending"] + [{"t": int(time.time()), "aps": aps}])[-MAX_PENDING:]


# ---------- web services ----------

def geolocate(keys, aps, allow_ip):
    """Position from nearby Wi-Fi (Google if there's a key, else BeaconDB). Old scans must not
    fall back to our IP address: that's where we are now, not where we were."""
    if len(aps) < 2 and not allow_ip:
        return None
    body = {"considerIp": allow_ip, "wifiAccessPoints": aps}
    url = ("https://www.googleapis.com/geolocation/v1/geolocate?key=" + keys["google_geo"]
           if keys.get("google_geo") else "https://api.beacondb.net/v1/geolocate")
    r = net.http_json(url, body)
    if not r or "location" not in r:
        return None
    return r["location"]["lat"], r["location"]["lng"], round(r.get("accuracy", 99999))


def reverse_geocode(g):
    r = net.http_json("https://nominatim.openstreetmap.org/reverse?format=jsonv2&zoom=16"
                      f"&addressdetails=1&lat={g['lat']:.5f}&lon={g['lon']:.5f}")
    if not r:
        return
    a = r.get("address", {})
    area = next((a[k] for k in ("neighbourhood", "suburb", "quarter", "hamlet", "village", "town",
                                "city", "municipality", "county") if a.get(k)), None)
    city = next((a[k] for k in ("city", "town", "village", "municipality", "county", "state")
                 if a.get(k) and a[k] != area), "")
    g["area"] = area or r.get("name") or "Somewhere"
    g["city"] = city
    iso = a.get("ISO3166-2-lvl4", "")  # "CA-AB"
    g["province"] = iso.split("-", 1)[1] if "-" in iso else ""
    g["country"] = a.get("country_code", "").upper()


def fetch_weather(g):
    r = net.http_json(
        "https://api.open-meteo.com/v1/forecast?"
        f"latitude={g['lat']:.4f}&longitude={g['lon']:.4f}"
        "&current=temperature_2m,weather_code,is_day,wind_speed_10m"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset"
        "&timezone=auto&forecast_days=4")
    if not r:
        return False
    cur, d = r["current"], r["daily"]
    g.update(temp=cur["temperature_2m"], code=cur["weather_code"], is_day=cur["is_day"] == 1,
             wind=cur.get("wind_speed_10m"), hi=d["temperature_2m_max"][0],
             lo=d["temperature_2m_min"][0], elevation=round(r.get("elevation") or 0),
             tz=r.get("timezone") or g.get("tz"), sunrise=d["sunrise"][0][-5:],
             sunset=d["sunset"][0][-5:],
             forecast=[{"date": d["time"][i], "code": d["weather_code"][i],
                        "hi": d["temperature_2m_max"][i], "lo": d["temperature_2m_min"][i]}
                       for i in range(1, len(d["time"]))])
    return True


def _activity_kind(tourism, leisure, historic):
    if tourism:
        return "" if tourism == "attraction" else tourism
    return leisure or ("historic" if historic else "")


class Candidates:
    def __init__(self, lat, lon):
        self.lat, self.lon = lat, lon
        self.lists = {k: [] for k in KINDS}

    def add(self, kind, name, lat, lon, info, bonus):
        if not name or lat is None:
            return
        dist = round(geo.distance_m(self.lat, self.lon, lat, lon))
        if dist > (C.ACTIVITY_RADIUS_M if kind == "todo" else C.WALK_RADIUS_M):
            return
        lst = self.lists[kind]
        key = "".join(ch for ch in name.lower() if ch.isalnum())[:12]
        if any(c["key"] == key for c in lst):
            return  # same place listed twice ("Park Distillery Restaurant and Bar" / "... + Bar")
        info = (info or "").replace("_", " ").split(";")[0]  # "pizza;italian" -> "pizza"
        lst.append({"name": name, "info": info, "lat": lat, "lon": lon, "dist": dist,
                    "bearing": geo.bearing_deg(self.lat, self.lon, lat, lon), "score": dist + bonus, "key": key})

    def best(self):
        return {k: [{x: c[x] for x in c if x not in ("score", "key")}
                    for c in sorted(v, key=lambda c: c["score"])[:C.PLACES_PER_LIST]]
                for k, v in self.lists.items()}


def geoapify(cands, key, kind, categories, radius):
    r = net.http_json(f"https://api.geoapify.com/v2/places?categories={categories}"
                      f"&filter=circle:{cands.lon:.5f},{cands.lat:.5f},{radius}"
                      f"&bias=proximity:{cands.lon:.5f},{cands.lat:.5f}&limit=30&apiKey={key}")
    for f in (r or {}).get("features", []):
        p = f.get("properties", {})
        raw = p.get("datasource", {}).get("raw", {})
        chain = bool(raw.get("brand"))
        famous = bool(raw.get("wikidata") or raw.get("wikipedia"))
        info = ""
        if kind == "food":
            info = raw.get("cuisine") or next(
                (c[20:] for c in p.get("categories", []) if c.startswith("catering.restaurant.")), "")
        elif kind == "todo":
            info = _activity_kind(raw.get("tourism"), raw.get("leisure"), raw.get("historic"))
        # local spots beat chains; for things to do, places famous enough for Wikipedia come first
        bonus = (-1500 if famous else 0) if kind == "todo" else ((600 if kind == "food" else 300) if chain else 0)
        cands.add(kind, p.get("name"), p.get("lat"), p.get("lon"), info, bonus)


def overpass(cands):
    w, a, la, lo = C.WALK_RADIUS_M, C.ACTIVITY_RADIUS_M, cands.lat, cands.lon
    q = ("[out:json][timeout:20];("
         f'nwr(around:{w},{la:.5f},{lo:.5f})[amenity~"^(cafe|restaurant)$"][name];'
         f"nwr(around:{w},{la:.5f},{lo:.5f})[shop=coffee][name];"
         f'nwr(around:{a},{la:.5f},{lo:.5f})[tourism~"^(attraction|museum|viewpoint|gallery|zoo|aquarium|theme_park)$"][name];'
         f'nwr(around:{a},{la:.5f},{lo:.5f})[leisure~"^(park|nature_reserve|garden)$"][name][wikidata];'
         ");out center tags;")
    for server in ("https://overpass-api.de/api/interpreter",
                   "https://overpass.private.coffee/api/interpreter",
                   "https://maps.mail.ru/osm/tools/overpass/api/interpreter"):
        r = net.http_json(server, "data=" + quote(q), form=True, timeout=25)
        if r:
            break
    else:
        return
    for el in r.get("elements", []):
        t = el.get("tags", {})
        at = el.get("center", el)
        chain, famous = bool(t.get("brand")), bool(t.get("wikidata") or t.get("wikipedia"))
        if t.get("amenity") == "cafe" or t.get("shop") == "coffee":
            cands.add("coffee", t.get("name"), at.get("lat"), at.get("lon"), "", 300 if chain else 0)
        elif t.get("amenity") == "restaurant":
            cands.add("food", t.get("name"), at.get("lat"), at.get("lon"), t.get("cuisine"), 600 if chain else 0)
        else:
            cands.add("todo", t.get("name"), at.get("lat"), at.get("lon"),
                      _activity_kind(t.get("tourism"), t.get("leisure"), None), -1500 if famous else 0)


def fetch_places(g, keys):
    cands = Candidates(g["lat"], g["lon"])
    key = keys.get("geoapify")
    if key:
        geoapify(cands, key, "coffee", "catering.cafe", C.WALK_RADIUS_M)
        geoapify(cands, key, "food", "catering.restaurant", C.WALK_RADIUS_M)
        geoapify(cands, key, "todo", "tourism.attraction,tourism.sights,entertainment.museum,leisure.park",
                 C.ACTIVITY_RADIUS_M)
    else:
        overpass(cands)
    best = cands.best()
    return best if any(best.values()) else None  # keep the old lists rather than blank them


# ---------- the trip map: GeoJSON (GitHub draws it as a map) and GPX ----------

def geojson(store):
    feats = []
    coords = [[f["lon"], f["lat"]] for f in store.read(store.fixes) if f["acc"] <= 2000]
    if len(coords) >= 2:
        feats.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords},
                      "properties": {"title": "Our route", "stroke": "#d52b1e", "stroke-width": 3}})
    for w in store.read(store.wpts):
        props = {"title": f"WPT {w['num']:03d} {w.get('area', '')}", "marker-color": "#d52b1e",
                 "when": w.get("when", ""),
                 "place": ", ".join(x for x in (w.get("area"), w.get("city"), w.get("province")) if x),
                 "weather": f"{round(w.get('temp', 0))}°C {geo.weather_text(w.get('code', -1))}",
                 "elevation": f"{w.get('elevation', 0)} m"}
        for k, label in (("coffee", "coffee"), ("food", "food"), ("todo", "to do")):
            props[label] = ", ".join(f"{p['name']} ({p['dist']}m)" for p in w.get("places", {}).get(k, []))
        feats.append({"type": "Feature", "properties": props,
                      "geometry": {"type": "Point", "coordinates": [w["lon"], w["lat"]]}})
    return {"type": "FeatureCollection", "features": feats}


def _xml(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def gpx(store):
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<gpx version="1.1" creator="Retro GPS" xmlns="http://www.topografix.com/GPX/1/1">']
    for w in store.read(store.wpts):
        desc = " | ".join(f"{k}: " + ", ".join(p["name"] for p in w.get("places", {}).get(k, []))
                          for k in KINDS)
        out.append(f'<wpt lat="{w["lat"]}" lon="{w["lon"]}"><ele>{w.get("elevation", 0)}</ele>'
                   f'<time>{_iso(w["t"])}</time><name>{_xml("WPT %03d %s" % (w["num"], w.get("area", "")))}'
                   f'</name><desc>{_xml(desc)}</desc></wpt>')
    out.append("<trk><name>Trip</name><trkseg>")
    for f in store.read(store.fixes):
        if f["acc"] <= 2000:
            out.append(f'<trkpt lat="{f["lat"]}" lon="{f["lon"]}"><time>{_iso(f["t"])}</time></trkpt>')
    out += ["</trkseg></trk>", "</gpx>"]
    return "\n".join(out) + "\n"


def push_github(store, gh):
    """Upload trip.geojson so the map can be seen from anywhere (optional)."""
    token, repo = gh.get("token"), gh.get("repo")
    if not token or not repo:
        return
    url = f"https://api.github.com/repos/{repo}/contents/trip.geojson"
    hdr = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"}
    content = base64.b64encode(json.dumps(geojson(store)).encode()).decode()
    sha = store.s.get("gh_sha", "")
    for _ in range(2):
        body = {"message": f"WPT {store.s['wpt_num']:03d}", "content": content}
        if sha:
            body["sha"] = sha
        r = net.http_json(url, body, method="PUT", headers=hdr, timeout=30)
        if r and "content" in r:
            store.s["gh_sha"] = r["content"]["sha"]
            return
        r = net.http_json(url, headers=hdr)  # our idea of the file is out of date (or it's new)
        sha = (r or {}).get("sha", "")


# ---------- updates ----------

def resolve_pending(store, keys):
    """Place the breadcrumbs we couldn't look up while offline."""
    pending, store.s["pending"] = store.s["pending"], []
    for p in pending:
        fix = geolocate(keys, p["aps"], False)
        if fix:
            log_fix(store, p["t"], *fix, 0)


def remember_scan(store, aps):
    store.s["last_scan"] = {"t": int(time.time()), "rssi": [r for _m, _s, r in aps[:12]],
                            "count": len(aps)}


def do_update(store, secrets, progress=lambda msg: None):
    """The full update: where are we, what's the weather, what's nearby. Returns (ok, message)."""
    keys = secrets["keys"]
    progress("SCANNING")
    aps = net.scan()
    with store.lock:
        remember_scan(store, aps)
    usable = net.for_location(aps)
    progress("WI-FI")
    ok_net = net.connect(secrets["wifi"], {s for _m, s, _r in aps})
    if not ok_net:
        with store.lock:
            queue_scan(store, usable)
            reschedule(store, False, "NO WI-FI")
            store.save()
        return False, "NO WI-FI"
    set_clock_from_network()
    progress("LOCATING")
    with store.lock:
        resolve_pending(store, keys)
    fix = geolocate(keys, usable, True)
    if not fix:
        with store.lock:
            reschedule(store, False, "NO FIX")
            store.save()
        return False, "NO FIX"
    lat, lon, acc = fix
    old = store.s.get("guide") or {}
    g = {k: old[k] for k in ("tz",) if k in old}
    g.update(lat=lat, lon=lon, accuracy=acc, updated_at=int(time.time()))
    progress("WEATHER")
    if not fetch_weather(g):
        for k in ("temp", "code", "hi", "lo", "elevation", "sunrise", "sunset", "forecast"):
            if k in old:
                g[k] = old[k]
    reverse_geocode(g)
    g.setdefault("area", "Somewhere")
    progress("NEARBY")
    places = fetch_places(g, keys) if acc <= C.ROUGH_FIX_M else None
    if places is None:
        # last stop's cafés would be wrong if we've moved (or don't know where we are)
        near = old.get("lat") is not None and geo.distance_m(old["lat"], old["lon"], lat, lon) < 300
        places = old.get("places") if near and acc <= C.ROUGH_FIX_M else {k: [] for k in KINDS}
    g["places"] = places
    with store.lock:
        s = store.s
        s["wpt_num"] += 1
        s["guide"] = g
        trip = s["trip"]
        trip["start"] = trip["start"] or g["updated_at"]
        if g.get("province") and g["province"] not in trip["provinces"]:
            trip["provinces"].append(g["province"])
        if "elevation" in g:
            trip["max_elev"] = max(trip["max_elev"] if trip["max_elev"] is not None else -9999, g["elevation"])
            trip["min_elev"] = min(trip["min_elev"] if trip["min_elev"] is not None else 99999, g["elevation"])
        log_fix(store, g["updated_at"], lat, lon, acc, s["wpt_num"])
        when = datetime.fromtimestamp(g["updated_at"], tz(s)).strftime("%a %d %b %H:%M")
        store.append(store.wpts, {"num": s["wpt_num"], "t": g["updated_at"], "when": when,
                                  **{k: g.get(k) for k in ("lat", "lon", "accuracy", "elevation", "area",
                                                           "city", "province", "temp", "code", "places")}})
        s["ui"]["saying"] = -1
        dest = s["ui"].get("dest")
        if not dest or dest.get("kind") in KINDS:  # point at the nearest coffee by default
            first = next((places[k][0] for k in KINDS if places.get(k)), None)
            s["ui"]["dest"] = dict(first, kind=next(k for k in KINDS if places.get(k))) if first else None
        rough = f"ROUGH FIX ±{round(acc / 1000)}km" if acc > C.ROUGH_FIX_M else ""
        reschedule(store, True, rough)
        store.save()
    progress("UPLOAD")
    try:
        push_github(store, secrets["github"])
        store.save()
    except Exception as e:  # never let an upload problem lose the waypoint
        log("github upload failed:", e)
    return True, f"WAYPOINT {store.s['wpt_num']:03d}"


def do_track(store, secrets):
    """Hourly breadcrumb: a quick scan, looked up at once if one of our networks is about."""
    aps = net.scan()
    known = {n["ssid"] for n in secrets["wifi"]}
    with store.lock:
        remember_scan(store, aps)
        queue_scan(store, net.for_location(aps))
    if known & {s for _m, s, _r in aps} and net.connect(secrets["wifi"], {s for _m, s, _r in aps}, 15):
        set_clock_from_network()
        with store.lock:
            resolve_pending(store, secrets["keys"])
        try:
            push_github(store, secrets["github"])
        except Exception as e:
            log("github upload failed:", e)
    with store.lock:
        store.s["sched"]["next_track"] = int(time.time()) + C.TRACK_EVERY_MIN * 60
        store.save()


# ---------- clock and schedule ----------

clock_hook = None  # main sets this to also write the PiSugar's RTC


def set_clock_from_network():
    t = net.network_time()
    if not t:
        return
    drift = abs(t.timestamp() - time.time())
    if drift > 2:
        log(f"clock off by {drift:.0f}s; setting it")
        net.run(["date", "-u", "-s", "@%d" % int(t.timestamp())], 5)
    if clock_hook:
        clock_hook(t)


def next_slot(now_local):
    for day in range(3):
        for h in C.UPDATE_HOURS:
            at = (now_local + timedelta(days=day)).replace(hour=h, minute=0, second=0, microsecond=0)
            if at.timestamp() > now_local.timestamp() + 60:
                return at
    return now_local + timedelta(hours=6)


def reschedule(store, ok, status):
    s, now = store.s, time.time()
    sc = s["sched"]
    nowl = local_now(s)
    if ok:
        sc.update(retries=0, retry_at=0, status=status, next_update=int(next_slot(nowl).timestamp()))
    else:
        if sc["next_update"] <= now:
            sc["next_update"] = int(next_slot(nowl).timestamp())
        if sc["retries"] < C.RETRIES:
            sc["retries"] += 1
            sc["retry_at"] = int(now + C.RETRY_EVERY_MIN * 60)
        else:
            sc.update(retries=0, retry_at=0, next_update=int(next_slot(nowl).timestamp()))
        at = datetime.fromtimestamp(sc["retry_at"] or sc["next_update"], tz(s)).strftime("%H:%M")
        sc["status"] = f"{status}, RETRY {at}"
    sc["next_track"] = int(now + C.TRACK_EVERY_MIN * 60)


def update_due(s, now=None, slack=120):
    now = now or time.time()
    sc = s["sched"]
    return (not s.get("guide") or now >= sc["next_update"] - slack
            or (sc["retry_at"] and now >= sc["retry_at"] - slack))


def track_due(s, now=None, slack=120):
    now = now or time.time()
    return now >= s["sched"]["next_track"] - slack


def next_wake(s, now=None):
    """When the PiSugar should wake us: the next update, retry or (daytime) breadcrumb."""
    now = now or time.time()
    zone = tz(s)
    sc = s["sched"]
    cands = [sc["next_update"] or now + 6 * 3600]
    if sc["retry_at"]:
        cands.append(sc["retry_at"])
    t = max(sc["next_track"], now + 300)
    lt = datetime.fromtimestamp(t, zone)
    if C.TRACK_HOURS[0] <= lt.hour < C.TRACK_HOURS[1]:
        cands.append(t)
    wake = max(min(cands), now + 120)
    return datetime.fromtimestamp(wake, zone)


# ---------- sayings ----------

def saying_fits(s, saying):
    _say, _means, where, when = saying
    g = s.get("guide") or {}
    if where and not (g.get("province") and g["province"] in where.split()):
        return False
    if not when:
        return True
    hour = local_now(s).hour
    temp, code = g.get("temp"), g.get("code", -1)
    return {"cold": temp is not None and temp <= 2, "hot": temp is not None and temp >= 24,
            "snow": geo.is_snow(code), "rain": geo.is_rain(code), "morning": 5 <= hour < 11,
            "evening": 17 <= hour < 22, "night": hour >= 21 or hour < 3}.get(when, False)


def pick_saying(s):
    """Sayings that suit this place, weather or time are three times as likely."""
    cur = s["ui"].get("saying", -1)
    w = [0 if i == cur or not saying_fits(s, x) else (3 if x[2] or x[3] else 1)
         for i, x in enumerate(SAYINGS)]
    if not sum(w):
        w = [1] * len(SAYINGS)
    s["ui"]["saying"] = random.choices(range(len(SAYINGS)), weights=w)[0]

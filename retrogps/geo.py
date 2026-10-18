"""Distances, bearings and the Garmin-style ways of writing them."""
import math

R_EARTH = 6371000.0


def distance_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R_EARTH * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bearing_deg(lat1, lon1, lat2, lon2):
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return round(math.degrees(math.atan2(y, x))) % 360


def offset_m(lat0, lon0, lat, lon):
    """(east, north) metres from (lat0, lon0); fine at city-to-province scale."""
    k = math.cos(math.radians(lat0))
    return (lon - lon0) * 111320.0 * k, (lat - lat0) * 111320.0


def compass(deg):
    return ("N", "NE", "E", "SE", "S", "SW", "W", "NW")[((deg + 22) % 360) // 45]


def fmt_coord(v, lat):
    """Garmin style: N 51°10.704' / W114°03.920'."""
    hemi = ("N" if v >= 0 else "S") if lat else ("E" if v >= 0 else "W")
    a = abs(v)
    deg = int(a)
    mins = (a - deg) * 60
    if mins >= 59.9995:
        deg, mins = deg + 1, 0.0
    return f"{hemi} {deg:02d}°{mins:06.3f}'" if lat else f"{hemi}{deg:03d}°{mins:06.3f}'"


def fmt_dist(m):
    if m >= 100000:
        return f"{m / 1000:.0f}km"
    if m >= 1000:
        return f"{m / 1000:.1f}km"
    return f"{round(m)}m"


def walk_min(m, per_min):
    return max(1, round(m / per_min))


def time_of_day(hour):
    if 5 <= hour < 12:
        return "MORNING"
    if 12 <= hour < 17:
        return "AFTERNOON"
    if 17 <= hour < 21:
        return "EVENING"
    return "NIGHT"


WEATHER = {0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Cloudy", 45: "Foggy", 48: "Foggy",
           51: "Drizzle", 53: "Drizzle", 55: "Drizzle", 56: "Icy drizzle", 57: "Icy drizzle",
           61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Icy rain", 67: "Icy rain",
           71: "Snow", 73: "Snow", 75: "Snow", 77: "Snow", 80: "Showers", 81: "Showers",
           82: "Downpour", 85: "Snow showers", 86: "Snow showers", 95: "Thunder", 96: "Hail storm",
           99: "Hail storm"}


def weather_text(code):
    return WEATHER.get(code, "Weather?")


def is_snow(code):
    return 71 <= code <= 77 or code in (85, 86)


def is_rain(code):
    return 51 <= code <= 67 or 80 <= code <= 82

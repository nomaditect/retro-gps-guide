"""Settings. Keys and Wi-Fi passwords live in secrets.toml (gitignored), not here."""
import os
import tomllib

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(APP_DIR, "assets")
DATA_DIR = os.environ.get("RETROGPS_DATA", "/var/lib/retrogps")
SECRETS = os.environ.get("RETROGPS_SECRETS", "/etc/retrogps/secrets.toml")

W, H = 122, 250                # portrait, like the eTrex
ROTATION = 0                   # 0 or 180, if the screen comes out upside down in the case
PARTIALS_BEFORE_FULL = 20      # a full refresh now and then clears e-ink ghosting

UPDATE_HOURS = (6, 10, 16, 20) # local time, wherever you are
TRACK_EVERY_MIN = 60           # breadcrumb Wi-Fi scan between updates...
TRACK_HOURS = (7, 22)          # ...but only between these hours, to save battery overnight
RETRY_EVERY_MIN, RETRIES = 20, 3
STALE_AFTER_H = 3              # waking by hand with older data than this syncs straight away

WALK_RADIUS_M = 800            # about 10 minutes on foot
ACTIVITY_RADIUS_M = 2000
WALK_M_PER_MIN = 80
ROUGH_FIX_M = 3000             # worse than this (an IP address guess): skip nearby places
PLACES_PER_LIST = 4

IDLE_FIRST_S = 45              # awake after a button wake if nobody presses anything
IDLE_AFTER_PRESS_S = 90
POWER_CUT_DELAY_S = 15         # between `poweroff` and the PiSugar cutting 5V
LOW_BATTERY = 10               # %: below this, stop alarm wake-ups (the button still works)
WEBMAP_MINUTES = 10

USER_AGENT = "RetroGPS/1.0 (+https://github.com/nomaditect)"
DEFAULT_TZ = "Europe/London"


def secrets():
    """Wi-Fi networks and API keys. Missing file = no networks, keyless services."""
    try:
        with open(SECRETS, "rb") as f:
            s = tomllib.load(f)
    except FileNotFoundError:
        s = {}
    s.setdefault("wifi", [])
    s.setdefault("keys", {})
    s.setdefault("github", {})
    return s

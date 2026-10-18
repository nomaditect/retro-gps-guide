"""Wi-Fi (scan with `iw`, join with NetworkManager), HTTP and setting the clock from the network."""
import email.utils
import json
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request

from .config import USER_AGENT

IFACE = "wlan0"


def log(*a):
    print(*a, flush=True)


def run(cmd, timeout=30):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        log("command failed:", cmd[0], e)
        return ""


# ---------- scanning ----------

def _usable(mac, ssid):
    # phone hotspots use locally administered MACs and move around; "_nomap" opts out of mapping
    return not (int(mac[:2], 16) & 0x02) and not ssid.endswith("_nomap")


def parse_iw(text):
    """`iw dev wlan0 scan` output -> [(mac, ssid, dBm)], strongest first."""
    aps, cur = [], None
    for line in text.splitlines():
        m = re.match(r"^BSS ([0-9a-f:]{17})", line)
        if m:
            cur = {"mac": m.group(1), "ssid": "", "rssi": -100}
            aps.append(cur)
        elif cur is not None:
            s = line.strip()
            if s.startswith("signal:"):
                cur["rssi"] = round(float(s.split()[1]))
            elif s.startswith("SSID:"):
                cur["ssid"] = s[5:].strip()
    aps.sort(key=lambda a: -a["rssi"])
    return [(a["mac"], a["ssid"], a["rssi"]) for a in aps]


def parse_nmcli(text):
    """nmcli -t BSSID,SSID,SIGNAL fallback; signal is a percentage, roughly -100..-50 dBm."""
    aps = []
    for line in text.splitlines():
        parts = re.split(r"(?<!\\):", line)
        if len(parts) < 3:
            continue
        mac = parts[0].replace("\\", "").lower()
        try:
            aps.append((mac, parts[1].replace("\\:", ":"), int(parts[2]) // 2 - 100))
        except ValueError:
            pass
    aps.sort(key=lambda a: -a[2])
    return aps


def scan():
    """Every network in range, strongest first: [(mac, ssid, dBm)]."""
    run(["ip", "link", "set", IFACE, "up"], 5)
    for _ in range(3):
        out = run(["iw", "dev", IFACE, "scan"], 20)
        if "BSS " in out:
            return parse_iw(out)
        time.sleep(1.5)  # "device busy": NetworkManager is scanning too
    return parse_nmcli(run(["nmcli", "-t", "-f", "BSSID,SSID,SIGNAL", "dev", "wifi", "list",
                            "--rescan", "yes"], 25))


def for_location(aps, limit=12):
    return [{"macAddress": m, "signalStrength": r} for m, s, r in aps if _usable(m, s)][:limit]


# ---------- joining ----------

def connected():
    """Really online. The USB cable to the Mac shows as "connected (local only)", which isn't."""
    return run(["nmcli", "-t", "-f", "STATE", "general"], 5).strip() == "connected"


def connect(networks, seen_ssids, wait_s=20):
    """NetworkManager joins known networks by itself; give it a moment, then push it,
    trying the networks we can see first (an iPhone hotspot can hide from scans)."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < wait_s:
        if connected():
            return True
        time.sleep(1)
    names = [n["ssid"] for n in networks]
    for name in sorted(names, key=lambda n: n not in seen_ssids):
        log("trying", name)
        run(["nmcli", "--wait", "20", "con", "up", "id", "retrogps-" + name], 25)
        if connected():
            return True
    return False


def local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("1.1.1.1", 53))
            return s.getsockname()[0]
    except OSError:
        return None


# ---------- HTTP ----------

def http_json(url, body=None, method=None, headers=None, form=False, timeout=15):
    data = None
    h = {"User-Agent": USER_AGENT}
    h.update(headers or {})
    if body is not None:
        if form:
            data = body.encode()
            h["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    short = url.split("?")[0][:60]
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read().decode("utf-8"))
            log(method or ("POST" if data else "GET"), short, "->", r.status)
            return out
    except urllib.error.HTTPError as e:
        log(short, "->", e.code)
    except (urllib.error.URLError, OSError, ValueError) as e:
        log(short, "failed:", e)
    return None


def network_time():
    """UTC from a plain-HTTP Date header (works even when the clock is too wrong for TLS)."""
    for url in ("http://connectivitycheck.gstatic.com/generate_204", "http://detectportal.firefox.com/"):
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=6) as r:
                d = r.headers.get("Date")
        except (urllib.error.URLError, OSError) as e:
            log("time from", url, "failed:", e)
            continue
        if d:
            return email.utils.parsedate_to_datetime(d)
    return None

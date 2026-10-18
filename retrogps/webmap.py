"""Web map: a little page with the whole trip on a map, plus GeoJSON and GPX downloads."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import guide

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Retro GPS trip</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body,#m{height:100%;margin:0}#b{position:absolute;z-index:999;top:10px;right:10px;background:#fff;
padding:6px 10px;font:15px monospace;border:2px solid #000}</style></head><body><div id="m"></div>
<div id="b"><a href="/trip.gpx">GPX</a> | <a href="/trip.geojson">GeoJSON</a></div><script>
const m=L.map('m');L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'&copy; OpenStreetMap'}).addTo(m);
const e=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
fetch('/trip.geojson').then(r=>r.json()).then(g=>{const l=L.geoJSON(g,{style:{color:'#d52b1e',weight:4},
onEachFeature:(f,x)=>{const p=f.properties;if(f.geometry.type=='Point')x.bindPopup('<b>'+e(p.title)+'</b><br>'+
[p.when,p.place,p.weather,'Coffee: '+p.coffee,'Food: '+p.food,'To do: '+p['to do']].map(e).join('<br>'))}}).addTo(m);
m.fitBounds(l.getBounds(),{maxZoom:15})}).catch(()=>m.setView([56,-96],3));
</script></body></html>"""


def serve(store, port=80):
    """Start serving in the background; returns the server (call .shutdown() to stop)."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/":
                body, ctype, extra = PAGE.encode(), "text/html; charset=utf-8", {}
            elif path == "/trip.geojson":
                body, ctype, extra = json.dumps(guide.geojson(store)).encode(), "application/geo+json", {}
            elif path == "/trip.gpx":
                body, ctype = guide.gpx(store).encode(), "application/gpx+xml"
                extra = {"Content-Disposition": "attachment; filename=trip.gpx"}
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in extra.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv

#!/usr/bin/env python3
"""
locate.py
  1. Zapytuje radiocells.org API o pozycje GPS każdej stacji bazowej (LAC/CID)
  2. Wykonuje trilaterację algorytmem Nelder-Mead (z trilateration.py)
  3. Generuje map.html z interaktywną mapą Mapbox GL JS
"""

import json
import math
import sys
import os
import time

import requests
from scipy.optimize import minimize

# ─── CONFIG ──────────────────────────────────────────────────────────────────
MAPBOX_TOKEN    = "pk.0579a0e92cd8fe938db5e5256ab892df"

# Twoje przybliżone/znane współrzędne (punkt odniesienia)
REF_LAT =  52.225681
REF_LON =  16.529484

# ─── CELLS ───────────────────────────────────────────────────────────────────
CELLS = [
    {"mcc": 260, "mnc":  1, "lac": 31101, "cid": 203296926, "note": "Plus LTE"},
    {"mcc": 260, "mnc":  2, "lac": 57144, "cid":  69398801, "note": "T-Mobile LTE"},
    {"mcc": 260, "mnc":  3, "lac": 57144, "cid":  43764761, "note": "Orange LTE"},
    {"mcc": 260, "mnc":  3, "lac": 57144, "cid":  43764791, "note": "Orange LTE 2"},
    {"mcc": 260, "mnc":  1, "lac": 31961, "cid": 222879381, "note": "WCDMA"},
    {"mcc":   0, "mnc":  0, "lac": 57140, "cid":     24756, "note": "2G/3G"},
    {"mcc":   0, "mnc":  0, "lac": 57140, "cid":  46591280, "note": "LTE unknown"},
]


# ─── MYLNIKOV.ORG (darmowe, bez klucza) ──────────────────────────────────────
_CACHE_FILE = os.path.join(os.path.dirname(__file__), ".mylnikov_cache.json")


def _load_cache():
    if os.path.exists(_CACHE_FILE):
        with open(_CACHE_FILE, "r") as f:
            return json.load(f)
    return {}


def _save_cache(cache):
    with open(_CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def lookup_cell(mcc, mnc, lac, cid):
    """Zwraca (lat, lon) z api.mylnikov.org lub (None, None) gdy brak danych.
    Bez klucza API, z cache .mylnikov_cache.json."""
    cache = _load_cache()
    key = f"{mcc}_{mnc}_{lac}_{cid}"

    if key in cache:
        entry = cache[key]
        if entry is None:
            print("  (cache) brak w mylnikov.org")
            return None, None
        print(f"  (cache) {entry['lat']:.6f}, {entry['lon']:.6f}")
        return entry["lat"], entry["lon"]

    url = "https://api.mylnikov.org/geolocation/cell"
    params = {
        "v":      "1.1",
        "data":   "open",
        "mcc":    mcc,
        "mnc":    mnc,
        "lac":    lac,
        "cellid": cid,
    }
    headers = {"User-Agent": "trilateration-py/1.0"}

    try:
        time.sleep(0.3)
        r = requests.get(url, params=params, headers=headers, timeout=15)
        data = r.json()

        if data.get("result") == 200 and "data" in data:
            lat = float(data["data"]["lat"])
            lon = float(data["data"]["lon"])
            rng = data["data"].get("range", "?")
            cache[key] = {"lat": lat, "lon": lon, "range": rng}
            _save_cache(cache)
            return lat, lon

        print(f"  mylnikov.org: result={data.get('result')} – komórka nieznana")
        cache[key] = None
        _save_cache(cache)

    except requests.RequestException as exc:
        print(f"  [!] Błąd połączenia: {exc}")

    return None, None


# ─── GEOMETRY ────────────────────────────────────────────────────────────────
def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def trilaterate(towers):
    """
    Nelder-Mead – ten sam algorytm co trilateration.py.
    towers: lista dict {"lat", "lon", "dist_km"}
    """
    earthRe = 6378.1   # km – równikowy
    earthRp = 6356.8   # km – polarny

    def cost(point):
        x, y, z = point
        total = 0.0
        for t in towers:
            lr = math.radians(t["lat"])
            lo = math.radians(t["lon"])
            ex = earthRe * math.cos(lr) * math.cos(lo)
            ey = earthRe * math.cos(lr) * math.sin(lo)
            ez = earthRp * math.sin(lr)
            d = math.sqrt((ex - x) ** 2 + (ey - y) ** 2 + (ez - z) ** 2)
            total += (d - t["dist_km"]) ** 2
        return total

    res = minimize(cost, [0.0, 0.0, 0.0], method="Nelder-Mead",
                   options={"maxiter": 100_000, "xatol": 1e-7, "fatol": 1e-7})
    x, y, z = res.x
    lat = math.degrees(math.asin(z / earthRp))
    lon = math.degrees(math.atan2(y, x))
    return lat, lon


# ─── MAP ─────────────────────────────────────────────────────────────────────
_COLORS = {
    "Plus LTE":    "#e74c3c",
    "T-Mobile LTE":"#e67e22",
    "Orange LTE":  "#f39c12",
    "Orange LTE 2":"#d35400",
    "WCDMA":       "#9b59b6",
    "2G/3G":       "#7f8c8d",
    "LTE unknown": "#95a5a6",
}


def generate_map(found_towers, estimated_pos=None):
    features = []

    for t in found_towers:
        cid = t["cid"]
        enodeb = cid >> 8 if cid > 65535 else "-"
        sector = cid & 0xFF if cid > 65535 else "-"
        popup = (
            f"{t['note']}\n"
            f"LAC: {t['lac']}  CID: {cid}\n"
            f"eNodeB: {enodeb}  sek: {sector}\n"
            f"Pos: {t['lat']:.5f}, {t['lon']:.5f}\n"
            f"~{t['dist_km']:.2f} km od ref."
        )
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [t["lon"], t["lat"]]},
            "properties": {
                "title": popup,
                "color": _COLORS.get(t["note"], "#34495e"),
                "r": 14,
            },
        })

    # Punkt referencyjny
    features.append({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [REF_LON, REF_LAT]},
        "properties": {
            "title": f"Punkt referencyjny\n({REF_LAT}, {REF_LON})",
            "color": "#2980b9",
            "r": 18,
        },
    })

    # Wynik trilateracji
    if estimated_pos:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [estimated_pos[1], estimated_pos[0]]},
            "properties": {
                "title": (
                    f"Wynik trilateracji\n"
                    f"({estimated_pos[0]:.5f}, {estimated_pos[1]:.5f})"
                ),
                "color": "#27ae60",
                "r": 20,
            },
        })

    geojson = json.dumps({"type": "FeatureCollection", "features": features},
                         ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="pl">
<head>
  <meta charset="utf-8">
  <title>Trilateration – mylnikov.org + Mapbox</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <script src="https://api.mapbox.com/mapbox-gl-js/v3.2.0/mapbox-gl.js"></script>
  <link href="https://api.mapbox.com/mapbox-gl-js/v3.2.0/mapbox-gl.css" rel="stylesheet">
  <style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ font-family:sans-serif; }}
    #map {{ width:100vw; height:100vh; }}
    #legend {{
      position:absolute; top:12px; left:12px; z-index:1;
      background:rgba(255,255,255,.92); border-radius:8px;
      padding:10px 14px; font-size:12px; line-height:1.9;
      box-shadow:0 2px 10px rgba(0,0,0,.3); max-width:210px;
    }}
    #legend h3 {{ font-size:13px; margin-bottom:5px; }}
    .dot {{ display:inline-block; width:11px; height:11px; border-radius:50%; margin-right:5px; vertical-align:middle; }}
  </style>
</head>
<body>
<div id="map"></div>
<div id="legend">
  <h3>Trilateration Map</h3>
  <span class="dot" style="background:#2980b9"></span>Punkt ref.<br>
  <span class="dot" style="background:#27ae60"></span>Trilateracja<br>
  <span class="dot" style="background:#e74c3c"></span>Plus LTE<br>
  <span class="dot" style="background:#e67e22"></span>T-Mobile LTE<br>
  <span class="dot" style="background:#f39c12"></span>Orange LTE<br>
  <span class="dot" style="background:#9b59b6"></span>WCDMA<br>
  <span class="dot" style="background:#7f8c8d"></span>2G/3G / unknown
</div>
<script>
mapboxgl.accessToken = '{MAPBOX_TOKEN}';
const map = new mapboxgl.Map({{
  container: 'map',
  style: 'mapbox://styles/mapbox/streets-v12',
  center: [{REF_LON}, {REF_LAT}],
  zoom: 12
}});
map.addControl(new mapboxgl.NavigationControl(), 'bottom-right');

const gj = {geojson};

map.on('load', () => {{
  gj.features.forEach(f => {{
    const p = f.properties;
    const el = document.createElement('div');
    const r = p.r || 14;
    el.style.cssText = [
      `width:${{r}}px`, `height:${{r}}px`, 'border-radius:50%',
      `background:${{p.color}}`, 'border:2.5px solid #fff',
      'cursor:pointer', 'box-shadow:0 0 6px rgba(0,0,0,.45)'
    ].join(';');
    new mapboxgl.Marker(el)
      .setLngLat(f.geometry.coordinates)
      .setPopup(new mapboxgl.Popup({{ offset:12 }}).setText(p.title))
      .addTo(map);
  }});
}});
</script>
</body>
</html>"""

    out = "/workspaces/trilateration-using-python/map.html"
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"\n  Mapa zapisana → {out}")
    return out


# ─── MAIN ────────────────────────────────────────────────────────────────────
def main():
    sep = "=" * 64
    print(sep)
    print("  mylnikov.org Cell Lookup  +  Nelder-Mead Trilateration  +  Mapbox")
    print(sep)

    found = []
    seen_cid: set = set()

    for cell in CELLS:
        mcc, mnc, lac, cid = cell["mcc"], cell["mnc"], cell["lac"], cell["cid"]
        note = cell["note"]

        if cid in seen_cid:
            print(f"\n[=] {note:16s}  CID={cid}  (duplikat – pomijam)")
            continue
        seen_cid.add(cid)

        enodeb = (cid >> 8) if cid > 65535 else "—"
        sector = (cid & 0xFF) if cid > 65535 else "—"
        print(f"\n[?] {note:16s}  MCC={mcc} MNC={mnc}  "
              f"LAC={lac}  CID={cid}  eNodeB={enodeb} sek={sector}")

        lat, lon = lookup_cell(mcc, mnc, lac, cid)
        if lat is not None:
            dist = haversine_km(REF_LAT, REF_LON, lat, lon)
            print(f"    ✓ OpenCelliD → {lat:.6f}, {lon:.6f}  |  ~{dist:.2f} km od ref.")
            found.append({**cell, "lat": lat, "lon": lon, "dist_km": dist})
        else:
            print(f"    ✗ Brak współrzędnych w OpenCelliD")

    print(f"\n{sep}")
    print(f"  Stacje z pozycją: {len(found)} / {len(seen_cid)}")
    print(sep)

    estimated = None

    if len(found) >= 3:
        print("\n  Trilateracja (Nelder-Mead)…")
        elat, elon = trilaterate(found)
        estimated = (elat, elon)
        err_km = haversine_km(REF_LAT, REF_LON, elat, elon)
        print(f"  Wynik:  lat={elat:.6f}  lon={elon:.6f}")
        print(f"  Błąd vs. punkt ref.: {err_km:.3f} km  ({err_km * 1000:.0f} m)")

    elif found:
        elat = sum(t["lat"] for t in found) / len(found)
        elon = sum(t["lon"] for t in found) / len(found)
        estimated = (elat, elon)
        print(f"\n  Za mało stacji (< 3) – centroid jako przybliżenie:")
        print(f"  lat={elat:.6f}  lon={elon:.6f}")

    else:
        print("\n  Brak pozycji stacji – mapa tylko z punktem referencyjnym.")

    generate_map(found, estimated)
    print(sep)


if __name__ == "__main__":
    main()

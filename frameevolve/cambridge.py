"""Real houses: the envelopes of Cambridge, MA's one- to three-family houses, from the city's open data.

Two sources, joined by place. The assessor's Property Database says what each house is (class, style, storeys,
wall and roof type, year, living area). The city's 3D building models (LoD2: one small mesh a building, flat
walls and roof planes, in feet) give its shape. `python -m frameevolve.cambridge` downloads both and keeps, in
data/cambridge (not in git), one OBJ per house and houses.json, the list of them with the assessor's record.
"""
from __future__ import annotations

import csv
import io
import json
import math
import ssl
import urllib.parse
import urllib.request
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import truststore   # the system's certificates: this Python brings none

OUT = Path(__file__).resolve().parents[1] / "data" / "cambridge"
ASSESSOR = "https://data.cambridgema.gov/resource/waa7-ibdu.json"     # Cambridge Property Database, FY2026
TILES = ("https://services1.arcgis.com/WnzC35krSYGuYov4/arcgis/rest/services/Metro3d_Tilegrid_Poly_Cambridge_shp/"
         "FeatureServer/0/query?where=1%3D1&outFields=grid_col,grid_row&returnGeometry=false&f=json")
MODELS = "https://cambmagisdata.blob.core.windows.net/camb3d/Camb3D_{tile}_2023_Bulding_Models_OBJ.zip"   # the city's spelling
CLASSES = ("SNGL-FAM-RES", "TWO-FAM-RES", "THREE-FM-RES", "SINGLE FAM W/AUXILIARY APT")
FIELDS = ("pid", "map_lot", "bldgnum", "address", "latitude", "longitude", "propertyclass", "exterior_style",
          "exterior_numstories", "exterior_walltype", "exterior_wallheight", "exterior_rooftype",
          "interior_livingarea", "interior_totalrooms", "interior_bedrooms", "interior_numunits", "condition_yearbuilt")
STOREYS = 3.0      # the most storeys a house may have
NEAR = 20.0        # a house's model is the nearest one within this of the assessor's point, metres
LOW = 12.0         # a model lower than this is a garage or a shed, feet


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "frameevolve"})
    return urllib.request.urlopen(request, context=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)).read()


def assessed() -> list[dict]:
    """The assessor's one- to three-family houses of at most three storeys that have a place."""
    classes = ",".join(f"'{c}'" for c in CLASSES)
    query = f"select {','.join(FIELDS)} where propertyclass in ({classes}) limit 50000"
    rows = json.loads(fetch(ASSESSOR + "?" + urllib.parse.urlencode({"$query": query})))
    return [r for r in rows if r.get("latitude") and r.get("exterior_numstories")
            and float(r["exterior_numstories"]) <= STOREYS]


def tile(name: str) -> zipfile.ZipFile:
    """A tile of building models, downloaded once into data/cambridge/raw."""
    path = OUT / "raw" / f"{name}.zip"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fetch(MODELS.format(tile=name)))
    return zipfile.ZipFile(path)


def catalog(z: zipfile.ZipFile) -> list[dict]:
    """A tile's models that stand tall enough to be a house, with where each is."""
    name = next(n for n in z.namelist() if n.endswith("catalog.csv"))
    rows = csv.DictReader(io.TextIOWrapper(z.open(name), encoding="utf-8-sig"))
    return [r for r in rows if r["Center_Lat"] and r["Height_Ft"] and float(r["Height_Ft"]) >= LOW]


def metres(lat: float, lon: float, lat0: float, lon0: float) -> float:
    return math.hypot((lat - lat0) * 110950, (lon - lon0) * 111320 * math.cos(math.radians(lat0)))


def download() -> list[dict]:
    """Download the assessor's houses and every tile, give each house the model nearest its point, and save the
    houses whose model is theirs alone: a model several houses share is a row of townhouses."""
    houses = assessed()
    names = [f"{a['grid_col']}-{a['grid_row']}" for a in (f["attributes"] for f in json.loads(fetch(TILES))["features"])]
    zips = {n: tile(n) for n in names}
    models = [{**r, "tile": n} for n, z in zips.items() for r in catalog(z)]
    cells = defaultdict(list)          # models by a grid of about 100 m, to find the near ones fast
    for m in models:
        m["lat"], m["lon"] = float(m["Center_Lat"]), float(m["Center_Long"])
        cells[(round(m["lat"], 3), round(m["lon"], 3))].append(m)
    by_model = defaultdict(list)
    for h in houses:
        lat, lon = float(h["latitude"]), float(h["longitude"])
        near = [m for i in (-1, 0, 1) for j in (-1, 0, 1) for m in cells[(round(lat + i / 1000, 3), round(lon + j / 1000, 3))]]
        best = min(near, key=lambda m: metres(m["lat"], m["lon"], lat, lon), default=None)
        if best and metres(best["lat"], best["lon"], lat, lon) <= NEAR:
            by_model[best["Model_ID"]].append((h, best))
    (OUT / "models").mkdir(parents=True, exist_ok=True)
    kept = []
    for mid, pairs in sorted(by_model.items()):
        if len(pairs) > 1:
            continue
        h, m = pairs[0]
        z = zips[m["tile"]]
        obj = next(n for n in z.namelist() if n.endswith(f"{mid}_OBJ.obj"))
        (OUT / "models" / f"{mid}.obj").write_bytes(z.read(obj))
        kept.append({"model": mid, "tile": m["tile"], "height_ft": round(float(m["Height_Ft"]), 2),
                     "ground_ft": round(float(m["Ground_Elev_Ft"]), 2), "model_date": m["Model_Date"],
                     "off_m": round(metres(m["lat"], m["lon"], float(h["latitude"]), float(h["longitude"])), 1), **h})
    (OUT / "houses.json").write_text(json.dumps(kept, indent=1))
    shared = sum(len(p) for p in by_model.values() if len(p) > 1)
    print(f"{len(houses)} assessed houses, {len(models)} models in {len(names)} tiles; "
          f"{len(houses) - sum(map(len, by_model.values()))} with no model within {NEAR:.0f} m, {shared} sharing a model; "
          f"{len(kept)} kept in {OUT}")
    return kept


if __name__ == "__main__":
    kept = download()
    for key in ("propertyclass", "exterior_rooftype", "exterior_style", "exterior_numstories", "exterior_walltype"):
        print(key, dict(Counter(h.get(key, "") for h in kept).most_common(12)))

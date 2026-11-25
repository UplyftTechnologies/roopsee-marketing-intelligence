"""Build the place data the Map page uses (mi/geo_data/): state outlines, pincode centroids and place-name centroids.

    .venv\\Scripts\\python tools\\build_geo_data.py [cache-folder]

Downloads (once, into the cache folder) three public files, reads them as DATA ONLY (nothing from them is ever run) and writes small files:
  GeoNames postal codes for India   https://download.geonames.org/export/zip/IN.zip            (CC BY 4.0, geonames.org)
  GeoNames cities of 15000+         https://download.geonames.org/export/dump/cities15000.zip  (CC BY 4.0, geonames.org)
  Indian state outlines (GeoJSON)   https://gist.github.com/jbrobst/56c13bbbf9d97d187fea01ca62ea5112   (36 states and union territories)
The state outlines are simplified to about 70 KB. Outlines are drawn for orientation only, not as a legal map.
"""
import csv
import gzip
import json
import math
import re
import sys
import unicodedata
import urllib.request
import zipfile
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "mi" / "geo_data"
CACHE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "data" / "geo_cache"
SOURCES = {
    "IN.zip": "https://download.geonames.org/export/zip/IN.zip",
    "cities15000.zip": "https://download.geonames.org/export/dump/cities15000.zip",
    "states.json": "https://gist.githubusercontent.com/jbrobst/56c13bbbf9d97d187fea01ca62ea5112/raw/e388c4cae20aa53cb5090210a42ebb9b765c0a36/india_states.geojson",
}
TOL = 0.03  # degrees (about 3 km) kept when simplifying the outlines


def fetch(name: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / name
    if not p.exists():
        print("downloading", SOURCES[name])
        urllib.request.urlretrieve(SOURCES[name], p)
    return p


def key(s) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower().replace("&", " and ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", s)).strip()


# ------------------------------------------------------------------ outlines
def _perp(p, a, b):
    (x, y), (x1, y1), (x2, y2) = p, a, b
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(x - x1, y - y1)
    t = max(0, min(1, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))


def _dp(pts, tol):
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        best, k = 0, None
        for m in range(i + 1, j):
            d = _perp(pts[m], pts[i], pts[j])
            if d > best:
                best, k = d, m
        if k is not None and best > tol:
            keep[k] = True
            stack += [(i, k), (k, j)]
    return [p for p, kp in zip(pts, keep) if kp]


def _area(r):
    return abs(sum(r[i][0] * r[(i + 1) % len(r)][1] - r[(i + 1) % len(r)][0] * r[i][1] for i in range(len(r)))) / 2


def states() -> None:
    d = json.load(open(fetch("states.json"), encoding="utf-8"))
    feats = []
    for f in d["features"]:
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        out = []
        for poly in polys:
            if _area(poly[0]) < 0.01:  # specks
                continue
            ring = _dp([tuple(p[:2]) for p in poly[0]], TOL)
            if len(ring) >= 4:
                out.append([[[round(x, 2), round(y, 2)] for x, y in ring]])
        if out:
            feats.append({"type": "Feature", "properties": {"name": f["properties"]["ST_NM"]}, "geometry": {"type": "MultiPolygon", "coordinates": out}})
    (OUT / "states.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")), encoding="utf-8")
    print("states.geojson:", len(feats), "states")


# ------------------------------------------------------------------ pincodes and place names
def places() -> None:
    postal = zipfile.ZipFile(fetch("IN.zip")).read("IN.txt").decode("utf-8").splitlines()
    pins: dict[str, list] = {}     # pincode -> [lat, lon, state, n]
    names: dict[tuple, list] = {}  # (place key, state) -> [lat, lon, n]
    for line in postal:
        f = line.split("\t")
        if len(f) < 11 or not f[9] or not re.fullmatch(r"\d{6}", f[1]):
            continue
        lat, lon, st = float(f[9]), float(f[10]), f[3]
        p = pins.setdefault(f[1], [0.0, 0.0, st, 0])
        p[0] += lat; p[1] += lon; p[3] += 1
        for n in {key(f[2]), key(f[5])} - {""}:
            q = names.setdefault((n, st), [0.0, 0.0, 0])
            q[0] += lat; q[1] += lon; q[2] += 1
    with gzip.open(OUT / "pincodes.csv.gz", "wt", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        for pin, (la, lo, st, n) in sorted(pins.items()):
            w.writerow([pin, round(la / n, 3), round(lo / n, 3), st])
    # cities (with alternate spellings) outrank postal place names of the same spelling
    cities: dict[tuple, list] = {}
    for line in zipfile.ZipFile(fetch("cities15000.zip")).read("cities15000.txt").decode("utf-8").splitlines():
        f = line.split("\t")
        if f[8] != "IN":
            continue
        pop = int(f[14] or 0)
        # state name from the nearest postal point is not needed: GeoNames admin1 codes differ, so the state is taken from the postal data below
        for n in {key(f[1]), key(f[2]), *[key(x) for x in f[3].split(",")]} - {""}:
            cities[n] = max(cities.get(n, [0, 0, -1]), [float(f[4]), float(f[5]), pop], key=lambda r: r[2])
    nearest_state = {}
    pts = [(v[0] / v[3], v[1] / v[3], v[2]) for v in pins.values()]
    grid: dict[tuple, list] = {}
    for la, lo, st in pts:
        grid.setdefault((round(la), round(lo)), []).append((la, lo, st))

    def state_at(la, lo):
        best = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for pla, plo, st in grid.get((round(la) + dx, round(lo) + dy), ()):
                    d = (pla - la) ** 2 + (plo - lo) ** 2
                    if best is None or d < best[0]:
                        best = (d, st)
        return best[1] if best else ""

    rows = {}
    for (n, st), (la, lo, c) in names.items():
        rows[(n, st)] = [n, round(la / c, 3), round(lo / c, 3), st, 0]
    for n, (la, lo, pop) in cities.items():
        st = state_at(la, lo)
        rows[(n, st)] = [n, round(la, 3), round(lo, 3), st, pop]
    with gzip.open(OUT / "places.csv.gz", "wt", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        for r in sorted(rows.values()):
            w.writerow(r)
    print("pincodes.csv.gz:", len(pins), "pincodes | places.csv.gz:", len(rows), "place names")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    states()
    places()
    for f in sorted(OUT.iterdir()):
        print(f"  {f.name}: {f.stat().st_size / 1024:.0f} KB")

"""Map: visits, checkouts started and orders by area (state, city, pincode).

Two ways to place things, always labelled in the answer:
  visitor    where the visitor was browsing from (their IP): visits, checkouts and orders of the same visits, so the rates are fair
  delivery   where the order is delivered: every valid order by its delivery address (like the Orders page); visits and checkouts only for the
             few visitors who gave an address or a pincode

Places are put on the map with small public data files in mi/geo_data (see tools/build_geo_data.py): state outlines, pincode centres and place-name centres.
Whatever cannot be placed is returned as `unplaced`, so area totals plus `unplaced` always equal the totals of the whole range.
"""
import csv
import gzip
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse

from .core import app, one, q, ratio, sess_where
from .orders import _orders_where
from .sessions import FLAG_ORDER

DATA = Path(__file__).parent / "geo_data"
LEVELS = ("state", "city", "pincode")
BASES = ("visitor", "delivery")
INDIA = (6.0, 38.0, 67.0, 98.5)  # lat min / max, lon min / max: anything outside is not a point in India

ALIASES = {
    "andaman and nicobar islands": "Andaman & Nicobar", "jammu and kashmir": "Jammu & Kashmir", "orissa": "Odisha", "uttaranchal": "Uttarakhand", "pondicherry": "Puducherry",
    "dadra and nagar haveli": "Dadra and Nagar Haveli and Daman and Diu", "daman and diu": "Dadra and Nagar Haveli and Daman and Diu",
    "nct of delhi": "Delhi", "chattisgarh": "Chhattisgarh",
}


def key(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower().replace("&", " and ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", s)).strip()


def _centroid(ring) -> tuple[float, float, float]:
    a = cx = cy = 0.0
    for i in range(len(ring) - 1):
        (x1, y1), (x2, y2) = ring[i], ring[i + 1]
        c = x1 * y2 - x2 * y1
        a += c; cx += (x1 + x2) * c; cy += (y1 + y2) * c
    if not a:
        return ring[0][1], ring[0][0], 0.0
    return cy / (3 * a), cx / (3 * a), abs(a) / 2  # lat, lon, area


@lru_cache(maxsize=1)
def _data() -> dict:
    gj = json.loads((DATA / "states.geojson").read_text(encoding="utf-8"))
    names, centres = {}, {}
    for f in gj["features"]:
        n = f["properties"]["name"]
        names[key(n)] = n
        best = max((_centroid(p[0]) for p in f["geometry"]["coordinates"]), key=lambda c: c[2])
        centres[n] = (round(best[0], 3), round(best[1], 3))
    pins, places = {}, {}
    with gzip.open(DATA / "pincodes.csv.gz", "rt", encoding="utf-8") as fh:
        for pin, la, lo, st in csv.reader(fh):
            pins[pin] = (float(la), float(lo), st)
    with gzip.open(DATA / "places.csv.gz", "rt", encoding="utf-8") as fh:
        for k, la, lo, st, pop in csv.reader(fh):
            places.setdefault(k, []).append((float(la), float(lo), st, int(pop)))
    return {"names": names, "centres": centres, "pins": pins, "places": places}


def canon_state(name) -> str | None:
    """The state name as the outlines spell it (or None when it is not an Indian state / territory)."""
    k = key(name)
    for p in ("union territory of ", "national capital territory of ", "state of "):
        if k.startswith(p):
            k = k[len(p):]
    names = _data()["names"]
    if k in names:
        return names[k]
    if k in ALIASES:
        return ALIASES[k]
    return None


def _in_india(la, lo) -> bool:
    return INDIA[0] <= la <= INDIA[1] and INDIA[2] <= lo <= INDIA[3]


def locate_city(city, state=None):
    """(lat, lon) of a city name, preferring the one in the given state, else the biggest."""
    places = _data()["places"]
    base = key(re.sub(r"\(.*?\)", " ", str(city or "")))
    for k in (key(city), base):
        c = places.get(k) if k else None
        if not c:
            continue
        in_state = [x for x in c if state and canon_state(x[2]) == state]
        pick = max(in_state or c, key=lambda x: x[3])
        if _in_india(pick[0], pick[1]):
            return pick[0], pick[1]
    return None


def locate_pin(pin):
    p = _data()["pins"].get(str(pin or ""))
    return (p[0], p[1]) if p and _in_india(p[0], p[1]) else None


@app.get("/api/geo/states")
def geo_states():
    """State outlines for the map (simplified, for orientation only)."""
    return FileResponse(DATA / "states.geojson", media_type="application/geo+json", headers={"Cache-Control": "max-age=86400"})


def _fill(r: dict) -> dict:
    r["checkout_rate"] = ratio(r["checkouts"], r["visits"])
    r["order_rate"] = ratio(r["orders"], r["visits"])
    r["revenue_per_visit"] = round(r["revenue"] / r["visits"], 2) if r["visits"] else 0
    return r


def _blank() -> dict:
    return {"visits": 0, "carts": 0, "checkouts": 0, "orders": 0, "revenue": 0.0}


def _add(into: dict, r: dict) -> None:
    for k in ("visits", "carts", "checkouts", "orders"):
        into[k] += int(r.get(k) or 0)
    into["revenue"] += float(r.get("revenue") or 0)


@app.get("/api/geo/areas")
def geo_areas(level: str = "state", basis: str = "visitor", date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, limit: int = 1500):
    """One row per area with visits, carts, checkouts started, orders and revenue, and where to draw it. See the module note for `basis`."""
    if level not in LEVELS:
        raise HTTPException(400, f"level must be one of {list(LEVELS)}")
    if basis not in BASES:
        raise HTTPException(400, f"basis must be one of {list(BASES)}")
    if level == "pincode":
        basis = "delivery"  # a pincode is where something is delivered
    w, a = sess_where(date_from, date_to, include_excluded)
    base_sql = "FROM sessions s LEFT JOIN session_orders o ON o.session_id = s.session_id"
    agg = (f"count(*) AS visits, count(*) FILTER (WHERE s.f_cart) AS carts, count(*) FILTER (WHERE s.f_checkout) AS checkouts, "
           f"count(*) FILTER (WHERE {FLAG_ORDER}) AS orders, coalesce(sum(o.order_value), 0) AS revenue")
    total = _fill({**_blank(), **one(f"SELECT {agg} {base_sql} WHERE {w}", a)})
    total["revenue"] = float(total["revenue"])

    # --- raw rows: (state raw, city raw, pincode, numbers)
    if basis == "visitor":
        cols = {"state": "s.region AS st", "city": "s.city AS city, s.region AS st"}[level]
        rows = q(f"SELECT {cols}, {agg} {base_sql} WHERE {w} GROUP BY ALL", a)
        for r in rows:
            r.setdefault("city", None)
            r["pin"] = None
    else:
        sess_cols = {"state": "s.delivery_state AS st", "city": "s.delivery_city AS city, s.delivery_state AS st", "pincode": "s.pincode AS pin"}[level]
        sess_where_extra = {"state": "s.delivery_state IS NOT NULL", "city": "s.delivery_city IS NOT NULL", "pincode": "s.pincode IS NOT NULL"}[level]
        rows = q(f"SELECT {sess_cols}, {agg} {base_sql} WHERE {w} AND {sess_where_extra} GROUP BY ALL", a)
        for r in rows:
            r.setdefault("city", None); r.setdefault("pin", None); r.setdefault("st", None)
        ow, oa = _orders_where(date_from, date_to, include_excluded, "sales", None, None, None, None)
        ocols = {"state": "o.state AS st", "city": "o.city AS city, o.state AS st", "pincode": "o.pincode AS pin"}[level]
        orders = q(f"SELECT {ocols}, count(*) AS o_orders, coalesce(sum(o.total), 0) AS o_revenue FROM orders_clean o WHERE {ow} GROUP BY ALL", oa)
        # in this view the orders and revenue are the delivered orders (all of them), not the orders of the counted visits
        for r in rows:
            r["orders"], r["revenue"] = 0, 0.0
        index = {(r.get("st"), r.get("city"), r.get("pin")): r for r in rows}
        for o in orders:
            k = (o.get("st"), o.get("city"), o.get("pin"))
            r = index.get(k)
            if r is None:
                r = {"st": o.get("st"), "city": o.get("city"), "pin": o.get("pin"), "visits": 0, "carts": 0, "checkouts": 0, "orders": 0, "revenue": 0.0}
                rows.append(r); index[k] = r
            r["orders"] += o["o_orders"]; r["revenue"] += float(o["o_revenue"] or 0)
        # totals of this view
        total = _fill({**total, "orders": sum(o["o_orders"] for o in orders), "revenue": float(sum(o["o_revenue"] or 0 for o in orders))})
        total["visits_with_place"] = sum(r["visits"] for r in rows)

    # --- group onto areas and give each a place on the map
    centres = _data()["centres"]
    areas: dict = {}
    unplaced = _blank()
    unplaced_rows: list = []
    for r in rows:
        st = canon_state(r.get("st"))
        if level == "state":
            ident, name, pt, flt = st, (st or r.get("st")), centres.get(st) if st else None, ({"region": r.get("st")} if basis == "visitor" else {"delivery_state": r.get("st")})
        elif level == "city":
            city = r.get("city")
            pt = locate_city(city, st) if city else None
            ident = f"{key(city)}|{st or ''}" if city else None
            name = (f"{city}" + (f", {st}" if st else "")) if city else None
            flt = ({"city": city, "region": r.get("st")} if basis == "visitor" else {"delivery_city": city, "delivery_state": r.get("st")})
        else:
            pin = r.get("pin")
            pt = locate_pin(pin) if pin and re.fullmatch(r"\d{6}", str(pin)) else None
            ident, name, flt = (pin if pt else None), str(pin or ""), {"pincode": pin}
            if pt and not st:
                st = canon_state(_data()["pins"][str(pin)][2])
        if not ident or not pt:
            _add(unplaced, r)
            if r["visits"] or r["orders"]:
                unplaced_rows.append({"name": name or "No location", "visits": r["visits"], "checkouts": r["checkouts"], "orders": r["orders"], "revenue": float(r["revenue"] or 0)})
            continue
        ar = areas.setdefault(ident, {"key": ident, "name": name, "state": st, "lat": pt[0], "lon": pt[1], "filters": [], **_blank()})
        _add(ar, r)
        ar["filters"].append(flt)
    out = sorted((_fill(x) for x in areas.values()), key=lambda x: (-x["visits"], -x["orders"], x["name"]))
    for x in out:
        x["revenue"] = round(x["revenue"], 2)
    unplaced_rows.sort(key=lambda x: (-x["visits"], -x["orders"]))
    unplaced["revenue"] = round(unplaced["revenue"], 2)
    return {"level": level, "basis": basis, "areas": out[:max(1, min(int(limit), 5000))], "area_count": len(out), "totals": total, "unplaced": _fill(dict(unplaced)),
            "unplaced_rows": unplaced_rows[:15]}

"""Search Meta's targeting options by name (places, interests, languages) and list the account's saved audiences, so nobody has to look up ids."""
from __future__ import annotations

import json
import time

from fastapi import APIRouter, HTTPException

from src.common import Settings
from src.meta_api import Meta, MetaError

router = APIRouter()
_CACHE: dict = {}
GEO_TYPES = ["country", "region", "city", "zip", "neighborhood", "subcity", "medium_geo_area", "geo_market"]


def _cached(key, ttl, fn):
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _CACHE[key] = (time.time(), val)
    return val


def _meta():
    s = Settings()
    if s.missing():
        raise HTTPException(400, "Missing in .env: " + ", ".join(s.missing()))
    return s, Meta(s)


def _fail(s, e):
    if "code 17" in str(e) or "too many calls" in str(e).lower():
        return HTTPException(429, "Meta is limiting how often it can be asked. Wait a minute and try again.")
    return HTTPException(502, f"Meta said: {s.redact(e)[:300]}")


@router.get("/api/targeting/search")
def search(kind: str, q: str, country: str = ""):
    """kind = geo | interest | locale. Returns a short, clean list."""
    q = q.strip()
    if len(q) < 2:
        return {"results": []}
    if kind not in ("geo", "interest", "locale"):
        raise HTTPException(400, "kind must be geo, interest or locale")
    s, m = _meta()

    def go():
        if kind == "geo":
            params = {"type": "adgeolocation", "q": q, "limit": 12, "location_types": json.dumps(GEO_TYPES)}
            if country:
                params["country_code"] = country.upper()[:2]
            rows = m.get("search", **params).get("data", [])
            return [{"key": r.get("key"), "name": r.get("name"), "type": r.get("type"), "country": r.get("country_code"), "region": r.get("region"),
                     "region_id": r.get("region_id")} for r in rows if r.get("key")]
        if kind == "interest":
            rows = m.get("search", type="adinterest", q=q, limit=12).get("data", [])
            return [{"id": r.get("id"), "name": r.get("name"), "size": r.get("audience_size_upper_bound") or r.get("audience_size"), "path": " > ".join(r.get("path") or [])}
                    for r in rows if r.get("id")]
        rows = m.get("search", type="adlocale", q=q, limit=12).get("data", [])
        return [{"key": r.get("key"), "name": r.get("name")} for r in rows if r.get("key") is not None]

    try:
        return {"results": _cached((s.env, kind, q.lower(), country), 600, go)}
    except MetaError as e:
        raise _fail(s, e)


@router.get("/api/targeting/audiences")
def audiences(refresh: bool = False):
    s, m = _meta()
    key = (s.env, s.account, "audiences")
    if refresh:
        _CACHE.pop(key, None)

    def go():
        rows = m.pages(f"{s.account}/customaudiences", fields="id,name,subtype,approximate_count_lower_bound", limit=100)
        return [{"id": r["id"], "name": r.get("name"), "subtype": (r.get("subtype") or "").lower(), "size": r.get("approximate_count_lower_bound")} for r in rows]

    try:
        return {"audiences": _cached(key, 120, go)}
    except MetaError as e:
        raise _fail(s, e)

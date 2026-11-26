"""Events: every tracked event, from the catalogue of event names down to single rows and their payload fields.

High level  -> /api/events/summary   one row per event name
Slice       -> /api/events/groupby   counts by a payload field or a dimension (day, page, city, ...)
Low level   -> /api/events/rows      one row per event, with optional payload columns
Helpers     -> /api/events/fields, /api/events/values (what can be filtered on), /api/event/{id} (one event in full)

Payload fields are read from the stored extra_data the same way the pipeline does it: top level first, then `rawBody`.
Hidden traffic (excluded) and repeated events (is_dup) are left out unless asked for, like everywhere else.
"""
import json
import re
from collections import Counter

from fastapi import HTTPException, Query

from .core import _csv, app, one, q
from .payload import NOISE, event_params, flat_payload, match_score
from .scores import borrow, scored_events
from .sessions import _event_details

FIELD_RE = re.compile(r"^[A-Za-z0-9_\-]{1,60}$")

# dimensions usable in group-by (and the SQL expression for each); a payload field is `payload:<name>`
DIMS = {
    "day": "e.ts_ist::DATE::VARCHAR",
    "hour": "lpad(extract(hour FROM e.ts_ist)::INT::VARCHAR, 2, '0')",
    "event_name": "e.event_name",
    "event_key": "coalesce(e.event_key, '(not a key event)')",
    "page_type": "coalesce(e.page_type, 'other')",
    "path": "coalesce(e.path, '(none)')",
    "product": "coalesce(e.product_name, '(none)')",
    "search_term": "coalesce(lower(e.search_term), '(none)')",
    "city": "coalesce(e.city_n, 'Unknown')",
    "device": "coalesce(CASE WHEN e.is_app THEN 'Android app' ELSE e.device_n END, 'Unknown')",
    "channel": "coalesce(s.channel, 'Unknown')",
    "campaign": "coalesce(s.campaign, 'Unknown')",
}
SESSION_DIMS = {"channel", "campaign"}

ROW_SORTS = {"ts": "e.ts", "event_name": "e.event_name", "session_id": "e.session_id", "page": "e.path", "product": "e.product_name",
             "search_term": "e.search_term", "city": "e.city_n", "who": "lower(coalesce(e.account_name, e.user_name, ''))"}


def _field(name: str) -> str:
    if not FIELD_RE.match(name or ""):
        raise HTTPException(400, f"bad field name: {name!r}")
    return name


def pf(name: str) -> str:
    """SQL for one payload field of the raw row `r` (top level, else rawBody; empty counts as missing)."""
    k = _field(name)
    return (f"coalesce(nullif(json_extract_string(r.extra_data, '$.\"{k}\"'), ''), "
            f"nullif(json_extract_string(r.extra_data, '$.rawBody.\"{k}\"'), ''))")


def _parse_payload_filters(items: list[str]) -> list[tuple[str, str, str | None]]:
    """'field=value' (equals, any case) | 'field~value' (contains) | 'field' (has a value)."""
    out = []
    for it in items:
        m = re.match(r"^([A-Za-z0-9_\-]{1,60})(?:([=~])(.*))?$", it.strip(), re.S)
        if not m:
            raise HTTPException(400, f"bad payload filter: {it!r}")
        out.append((m.group(1), m.group(2) or "?", m.group(3)))
    return out


def _where(date_from, date_to, include_excluded, include_dup, event=None, key=None, search=None, payload=(), session=None, person=None,
           channel=None, extra_sess=False):
    """WHERE clause + args + which joins are needed ('raw' = the stored payload, 'sess' = the session row)."""
    w = ["e.ts_ist::DATE BETWEEN ? AND ?"]
    a = [date_from or "2000-01-01", date_to or "2999-12-31"]
    need = {"raw": False, "sess": extra_sess}
    if not include_excluded:
        w.append("NOT e.is_excluded")
    if not include_dup:
        w.append("NOT e.is_dup")
    names = _csv(event)
    if names:
        w.append("e.event_name IN (" + ",".join("?" * len(names)) + ")")
        a += names
    if key:
        w.append("coalesce(e.event_key, '(not a key event)') = ?")
        a.append(key)
    if session:
        w.append("e.session_id = ?")
        a.append(session)
    if person:
        w.append("e.person_key = ?")
        a.append(person)
    if channel:
        need["sess"] = True
        w.append("s.channel = ?")
        a.append(channel)
    for name, op, val in _parse_payload_filters(list(payload)):
        need["raw"] = True
        if op == "=":
            w.append(f"lower({pf(name)}) = lower(?)")
            a.append(val)
        elif op == "~":
            w.append(f"lower({pf(name)}) LIKE ?")
            a.append(f"%{(val or '').lower()}%")
        else:
            w.append(f"{pf(name)} IS NOT NULL")
    if search:
        need["raw"] = True
        like = f"%{search.lower()}%"
        w.append("""(lower(e.event_name) LIKE ? OR lower(e.session_id) LIKE ? OR lower(coalesce(e.path, '')) LIKE ? OR lower(coalesce(e.product_name, '')) LIKE ?
                    OR lower(coalesce(e.search_term, '')) LIKE ? OR lower(coalesce(e.account_name, e.user_name, '')) LIKE ? OR coalesce(e.phone10, '') LIKE ?
                    OR lower(coalesce(e.order_id, '')) LIKE ? OR lower(coalesce(r.extra_data::VARCHAR, '')) LIKE ?)""")
        a += [like] * 9
    return " AND ".join(w), a, need


def _from(need: dict) -> str:
    return ("FROM events_clean e" + (" JOIN raw_event_log r ON r.id = e.id" if need["raw"] else "")
            + (" LEFT JOIN sessions s ON s.session_id = e.session_id" if need["sess"] else ""))


# ------------------------------------------------------------------ high level
@app.get("/api/events/summary")
def events_summary(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, include_dup: bool = False,
                   search: str | None = None, key: str | None = None):
    """One row per event name: how often, in how many sessions, by how many people, and the trend by day."""
    w, a, need = _where(date_from, date_to, include_excluded, include_dup, key=key)
    sq, sa = "", []
    if search:
        sq, sa = " AND lower(e.event_name) LIKE ?", [f"%{search.lower().replace(' ', '_')}%"]
    rows = q(f"""SELECT e.event_name, coalesce(max(e.event_key), '(not a key event)') AS event_key, count(*) AS events, count(DISTINCT e.session_id) AS sessions,
                 count(DISTINCT e.person_key) AS people, min(e.ts_ist) AS first_seen, max(e.ts_ist) AS last_seen
                 FROM events_clean e WHERE {w}{sq} GROUP BY 1 ORDER BY events DESC, 1 LIMIT 500""", [*a, *sa])
    keep = [r["event_name"] for r in rows[:150]]
    spark = {}
    if keep:
        for r in q(f"""SELECT e.event_name, e.ts_ist::DATE AS d, count(*) AS n FROM events_clean e
                       WHERE {w} AND e.event_name IN ({','.join('?' * len(keep))}) GROUP BY 1, 2 ORDER BY 2""", [*a, *keep]):
            spark.setdefault(r["event_name"], []).append([str(r["d"]), r["n"]])
    tot = one(f"SELECT count(*) AS events, count(DISTINCT e.event_name) AS names, count(DISTINCT e.session_id) AS sessions, count(DISTINCT e.person_key) AS people FROM events_clean e WHERE {w}", a)
    keys = q(f"SELECT coalesce(e.event_key, '(not a key event)') AS k, count(*) AS n FROM events_clean e WHERE {w} GROUP BY 1 ORDER BY 2 DESC", a)
    daily = q(f"SELECT e.ts_ist::DATE AS d, count(*) AS events FROM events_clean e WHERE {w} GROUP BY 1 ORDER BY 1", a)
    for r in rows:
        r["trend"] = spark.get(r["event_name"], [])
    return {"totals": tot, "rows": rows, "keys": keys, "daily": daily}


# ------------------------------------------------------------------ what can be filtered on
@app.get("/api/events/fields")
def events_fields(event: str | None = None, date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, sample: int = 4000):
    """Payload fields present on an event (or on all events), most common first. Based on the latest `sample` matching events."""
    w, a, _ = _where(date_from, date_to, include_excluded, False, event=event)
    rows = q(f"SELECT r.extra_data::VARCHAR AS x FROM events_clean e JOIN raw_event_log r ON r.id = e.id WHERE {w} ORDER BY e.ts DESC LIMIT ?", [*a, max(100, min(int(sample), 20000))])
    c, ex = Counter(), {}
    for r in rows:
        try:
            d = json.loads(r["x"]) if r["x"] else {}
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        flat = {**{k: v for k, v in d.items() if k != "rawBody"}, **(d.get("rawBody") if isinstance(d.get("rawBody"), dict) else {})}
        for k, v in flat.items():
            if k in NOISE or v in (None, "", [], {}) or not FIELD_RE.match(k):
                continue
            c[k] += 1
            ex.setdefault(k, str(v)[:60])
    n = len(rows)
    return {"sampled": n, "fields": [{"field": k, "events": v, "share": round(v / n, 4) if n else 0, "example": ex[k]} for k, v in c.most_common(80)]}


@app.get("/api/events/values")
def events_values(field: str, event: str | None = None, date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False,
                  search: str | None = None, limit: int = 50):
    """The most common values of one payload field (feeds the value dropdown of the filter builder)."""
    w, a, _ = _where(date_from, date_to, include_excluded, False, event=event)
    expr = pf(field)
    sq, sa = ("", [])
    if search:
        sq, sa = f" AND lower({expr}) LIKE ?", [f"%{search.lower()}%"]
    rows = q(f"""SELECT {expr} AS value, count(*) AS events, count(DISTINCT e.session_id) AS sessions FROM events_clean e JOIN raw_event_log r ON r.id = e.id
                 WHERE {w} AND {expr} IS NOT NULL{sq} GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT ?""", [*a, *sa, max(1, min(int(limit), 200))])
    return {"field": field, "rows": rows}


@app.get("/api/events/params")
def events_params_by_name(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, include_dup: bool = False,
                          key: str | None = None, sample: int = 60):
    """For every event name: which parameters it carries and whether it has a value, from its latest `sample` events in the dates."""
    w, a, _ = _where(date_from, date_to, include_excluded, include_dup, key=key)
    picked = q(f"""SELECT id, event_name FROM (SELECT e.id, e.event_name, row_number() OVER (PARTITION BY e.event_name ORDER BY e.ts DESC) AS rn
                   FROM events_clean e WHERE {w}) WHERE rn <= ?""", [*a, max(5, min(int(sample), 300))])
    names = {r["id"]: r["event_name"] for r in picked}
    stored = q("SELECT id, value, extra_data::VARCHAR AS x FROM raw_event_log WHERE id IN (SELECT unnest(?::VARCHAR[]))", [list(names)]) if names else []
    seen: dict = {}
    for r in stored:
        d = seen.setdefault(names[r["id"]], {"n": 0, "keys": Counter(), "examples": {}, "values": 0, "value_example": None, "scores": 0})
        flat = flat_payload(r["x"], r["value"])
        d["n"] += 1
        for p in event_params(flat, skip=("value",)):
            d["keys"][p["k"]] += 1
            d["examples"].setdefault(p["k"], p["v"][:60])
        v = flat.get("value")
        if v not in (None, "", [], {}):
            d["values"] += 1
            d["value_example"] = d["value_example"] or str(v)[:60]
        d["scores"] += 1 if match_score(flat) != (None, None) else 0
    return {name: {"sampled": d["n"], "params": [{"k": k, "share": round(c / d["n"], 4), "example": d["examples"][k]} for k, c in sorted(d["keys"].items(), key=lambda kv: (-kv[1], kv[0]))[:12]],
                   "value_share": round(d["values"] / d["n"], 4), "value_example": d["value_example"], "score_share": round(d["scores"] / d["n"], 4)} for name, d in seen.items()}


# ------------------------------------------------------------------ slice and dice
@app.get("/api/events/groupby")
def events_groupby(by: str = "event_name", date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, include_dup: bool = False,
                   event: str | None = None, key: str | None = None, search: str | None = None, payload: list[str] = Query([]), session: str | None = None,
                   person: str | None = None, channel: str | None = None, limit: int = 100):
    """Counts by a dimension (day, hour, page, city, channel, ...) or by a payload field (by=payload:quiz_option)."""
    if by.startswith("payload:"):
        expr, kind = f"coalesce({pf(by[8:])}, '(not set)')", "raw"
    elif by in DIMS:
        expr, kind = DIMS[by], "sess" if by in SESSION_DIMS else None
    else:
        raise HTTPException(400, f"by must be one of {list(DIMS)} or payload:<field>")
    w, a, need = _where(date_from, date_to, include_excluded, include_dup, event, key, search, payload, session, person, channel, extra_sess=(kind == "sess"))
    if kind == "raw":
        need["raw"] = True
    order = "value" if by in ("day", "hour") else "events DESC, value"
    rows = q(f"""SELECT {expr} AS value, count(*) AS events, count(DISTINCT e.session_id) AS sessions, count(DISTINCT e.person_key) AS people
                 {_from(need)} WHERE {w} GROUP BY 1 ORDER BY {order} LIMIT ?""", [*a, max(1, min(int(limit), 1000))])
    total = one(f"SELECT count(*) AS events, count(DISTINCT e.session_id) AS sessions, count(DISTINCT e.person_key) AS people {_from(need)} WHERE {w}", a)
    return {"by": by, "rows": rows, "totals": total}


# ------------------------------------------------------------------ low level
@app.get("/api/events/rows")
def events_rows(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, include_dup: bool = False,
                event: str | None = None, key: str | None = None, search: str | None = None, payload: list[str] = Query([]), session: str | None = None,
                person: str | None = None, channel: str | None = None, cols: str | None = None, sort: str = "ts", direction: str = "desc",
                limit: int = 50, offset: int = 0):
    """One row per event. `payload` = repeated field=value / field~value / field filters; `cols` = payload fields to return as columns (max 8)."""
    fields = _csv(cols)[:8]
    for f in fields:
        _field(f)
    w, a, need = _where(date_from, date_to, include_excluded, include_dup, event, key, search, payload, session, person, channel, extra_sess=True)
    if fields:
        need["raw"] = True
    order = ROW_SORTS.get(sort, "e.ts")
    if sort == "score":  # the product match score lives in the stored payload
        need["raw"] = True
        order = f"try_cast({pf('product_match_score')} AS DOUBLE)"
    d = "ASC" if direction.lower() == "asc" else "DESC"
    frm = _from(need)
    total = one(f"SELECT count(*) AS n {frm} WHERE {w}", a)["n"]
    sel = "".join(f", {pf(f)} AS pf_{i}" for i, f in enumerate(fields))
    rows = q(f"""SELECT e.id, e.ts_ist AS at, e.event_name, e.event_key, e.session_id, e.person_key, coalesce(e.account_name, e.user_name) AS who, e.phone10,
                 e.path, e.page_type, e.product_name, e.search_term, e.order_id, e.city_n AS city, e.is_app, e.device_n AS device, e.is_dup, e.is_excluded,
                 s.channel, s.campaign{sel} {frm} WHERE {w} ORDER BY {order} {d} NULLS LAST, e.ts DESC, e.id LIMIT ? OFFSET ?""",
             [*a, max(1, min(int(limit), 5000)), max(0, offset)])
    stored = {}
    if rows:  # parameters are read for the rows on this page only
        ids = [r["id"] for r in rows]
        stored = {x["id"]: x for x in q(f"SELECT id, value, extra_data::VARCHAR AS x FROM raw_event_log WHERE id IN ({','.join('?' * len(ids))})", ids)}
    for r in rows:
        r["payload"] = {f: r.pop(f"pf_{i}", None) for i, f in enumerate(fields)}
        st = stored.get(r["id"])
        flat = flat_payload(st["x"], st["value"]) if st else {}
        r["score"], r["score_note"] = match_score(flat)
        v = flat.get("value")
        r["value"] = None if v in (None, "", [], {}) else str(v)[:200]
        r["params"] = event_params(flat, skip=("search_term", "value"))
        r["score_from"] = None
    missing = [r["session_id"] for r in rows if r["score"] is None and not r["score_note"]]
    borrow(rows, scored_events(missing))
    return {"total": total, "rows": rows, "cols": fields}


@app.get("/api/event/{eid}")
def event_detail(eid: str):
    """One event in full: its columns and every readable payload field."""
    r = one("""SELECT e.id, e.ts_ist AS at, e.event_name, e.event_key, e.session_id, e.person_key, coalesce(e.account_name, e.user_name) AS who, e.phone10, e.path,
               e.page_link, e.page_type, e.product_name, e.search_term, e.order_id, e.city_n AS city, e.device_n AS device, e.is_app, e.is_dup, e.is_excluded
               FROM events_clean e WHERE e.id = ?""", [eid])
    if not r:
        raise HTTPException(404, "event not found")
    raw = one("SELECT value, extra_data::VARCHAR AS x FROM raw_event_log WHERE id = ?", [eid])
    r["details"] = _event_details(raw.get("value"), raw.get("x"), True)
    r["raw"] = raw.get("x")
    return r

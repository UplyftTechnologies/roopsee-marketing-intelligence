"""Journey presets: saved lists of user actions ("searched, then added to cart, did not order"), and the visits that match them.

A preset is a name and up to 8 steps. Each step is an action and Did / Did not:
  key:<key action>   one of the key actions (event_key in mi/transform.py: add_to_cart, checkout_view, search ...)
  event:<name>       any tracked event name, exactly (payment_failed, clicked_apply_coupon ...)
  flag:order         placed a real order in the visit (not payment cancelled / pending), as on the Sessions page

"In this order" makes the Did steps happen one after the other (any time later, or directly after: the next key action or named event,
ignoring page views, clicks and scrolls). Did not steps and "placed a real order" always look at the whole visit.

Presets are user data like the exclusion rules: kept in the `journey_presets` table, never dropped by a rebuild. A few useful ones are
built in once (tracked in etl_meta, so deleting one is never undone). Visits follow the global filters: dates, hidden traffic and device.
"""
import json
import re
from datetime import datetime

from fastapi import HTTPException, Response
from pydantic import BaseModel

from . import core
from .core import app, one, q, ratio, sess_where
from .db import DB_LOCK
from .journeys import STAGE_NAME
from .sessions import FLAG_ORDER

MAX_STEPS = 8
EVENT_RE = re.compile(r"^[A-Za-z0-9_\-:.]{1,80}$")
KEY_ACTIONS = {  # the key actions (event_key), in journey order, with the label shown in the editor
    "product_view": "Viewed a product", "add_to_cart": "Added to cart", "view_cart": "Opened the cart", "wishlist": "Added to wishlist",
    "checkout_view": "Reached checkout", "address": "Entered an address", "pay_started": "Started paying", "order_placed": "Order-placed event",
    "quiz_started": "Started the quiz", "quiz_completed": "Finished the quiz", "login": "Logged in", "search": "Searched",
    "assistant": "Used Roop (chat)", "app_open": "Opened the app",
}
FLAGS = {"order": "Placed a real order"}
STAGE = f"CASE WHEN {FLAG_ORDER} THEN 5 ELSE s.stage END"
VSORTS = {"started_at": "s.started_at", "duration": "s.duration_s", "events": "s.events", "order_value": "coalesce(o.order_value, 0)",
          "channel": "s.channel", "city": "nullif(lower(s.city), '')"}
PSORTS = {"last_seen": "max(s.started_at)", "first_seen": "min(s.started_at)", "visits": "count(*)", "orders": "coalesce(any_value(u.orders), 0)",
          "revenue": "coalesce(any_value(u.revenue), 0)"}

BUILT_IN = [
    ("Searched, added to cart, did not order", "Wanted something and found it, but did not buy: worth a reminder.",
     {"ordered": True, "gap": "eventually", "steps": [{"action": "key:search", "did": True}, {"action": "key:add_to_cart", "did": True}, {"action": "flag:order", "did": False}]}),
    ("Finished the quiz, did not add to cart", "Got their routine from the quiz but took nothing from it.",
     {"ordered": False, "gap": "eventually", "steps": [{"action": "key:quiz_completed", "did": True}, {"action": "key:add_to_cart", "did": False}]}),
    ("Reached checkout, then payment failed", "Wanted to pay and the payment did not go through.",
     {"ordered": True, "gap": "eventually", "steps": [{"action": "key:checkout_view", "did": True}, {"action": "event:payment_failed", "did": True}]}),
    ("Added to cart, then checkout straight away", "Went from the cart to checkout with no other key action in between.",
     {"ordered": True, "gap": "next", "steps": [{"action": "key:add_to_cart", "did": True}, {"action": "key:checkout_view", "did": True}]}),
    ("Asked Roop, then added to cart", "The chat assistant led to a cart.",
     {"ordered": True, "gap": "eventually", "steps": [{"action": "key:assistant", "did": True}, {"action": "key:add_to_cart", "did": True}]}),
]

DDL = """
CREATE SEQUENCE IF NOT EXISTS journey_presets_seq;
CREATE TABLE IF NOT EXISTS journey_presets (
  id BIGINT PRIMARY KEY DEFAULT nextval('journey_presets_seq'), name VARCHAR NOT NULL, note VARCHAR, definition JSON NOT NULL,
  source VARCHAR DEFAULT 'manual', created_at TIMESTAMP DEFAULT now(), updated_at TIMESTAMP DEFAULT now());
CREATE TABLE IF NOT EXISTS etl_meta (k VARCHAR PRIMARY KEY, v VARCHAR);
"""


def init(con) -> None:
    """Create the table and add each built-in preset once (called when the API starts)."""
    con.execute(DDL)
    for name, note, d in BUILT_IN:
        key = f"seed:preset:{name}"
        if con.execute("SELECT 1 FROM etl_meta WHERE k = ?", [key]).fetchall():
            continue
        if not con.execute("SELECT 1 FROM journey_presets WHERE lower(name) = lower(?)", [name]).fetchall():
            con.execute("INSERT INTO journey_presets (name, note, definition, source) VALUES (?, ?, ?, 'built-in')", [name, note, json.dumps(d)])
        con.execute("INSERT INTO etl_meta VALUES (?, '1')", [key])


# ---------------------------------------------------------------- definitions
class Step(BaseModel):
    action: str
    did: bool = True


class Definition(BaseModel):
    steps: list[Step]
    ordered: bool = False
    gap: str = "eventually"  # eventually | next


class PresetIn(BaseModel):
    name: str
    note: str | None = None
    definition: Definition


def _check(d: Definition) -> Definition:
    if not d.steps:
        raise HTTPException(400, "add at least one step")
    if len(d.steps) > MAX_STEPS:
        raise HTTPException(400, f"use {MAX_STEPS} steps or fewer")
    if d.gap not in ("eventually", "next"):
        raise HTTPException(400, "gap must be eventually or next")
    for s in d.steps:
        kind, _, v = s.action.partition(":")
        ok = (kind == "key" and v in KEY_ACTIONS) or (kind == "flag" and v in FLAGS) or (kind == "event" and bool(EVENT_RE.match(v)))
        if not ok:
            raise HTTPException(400, f"unknown action '{s.action}': use key:<{'|'.join(KEY_ACTIONS)}>, flag:order or event:<event name>")
    return d


def _label(action: str) -> str:
    kind, _, v = action.partition(":")
    return KEY_ACTIONS.get(v) if kind == "key" else FLAGS.get(v) if kind == "flag" else v


def _exists(action: str) -> tuple[str, list]:
    """SQL (and args): the visit `s` did this action at least once."""
    kind, _, v = action.partition(":")
    if kind == "flag":
        return FLAG_ORDER, []
    if kind == "key":  # same rule as the session flags (any event of that key action, repeats included)
        return "s.session_id IN (SELECT session_id FROM events_base WHERE event_key = ?)", [v]
    return "s.session_id IN (SELECT session_id FROM session_events WHERE event_name = ?)", [v]


def _in_order(d: Definition) -> list[str]:
    """The Did steps that must happen one after the other (a real order is a whole-visit fact, never a step in a sequence)."""
    if not d.ordered:
        return []
    seq = [s.action for s in d.steps if s.did and not s.action.startswith("flag:")]
    return seq if len(seq) >= 2 else []


def _match_sql(d: Definition, d_from, d_to, include_excluded, upto: int | None = None) -> tuple[str, list]:
    """SQL returning the session_id of every visit in the dates that matches the first `upto` steps (all steps by default)."""
    d = _check(d)
    steps = d.steps[:upto] if upto else d.steps
    sub = Definition(steps=steps, ordered=d.ordered, gap=d.gap)
    seq = _in_order(sub)
    w, a = sess_where(d_from, d_to, include_excluded)
    for s in steps:
        if s.did and s.action in seq:
            continue  # checked by the sequence below
        cond, ca = _exists(s.action)
        w += f" AND {'' if s.did else 'NOT '}coalesce({cond}, false)"
        a += ca
    base = f"SELECT s.session_id FROM sessions s LEFT JOIN session_orders o ON o.session_id = s.session_id WHERE {w}"
    if not seq:
        return base, a
    # the visit's key actions and named events in time order; repeats of the same action in a row count as one position
    names = sorted({x.partition(":")[2] for x in seq if x.startswith("event:")})
    named = f" OR e.event_name IN ({', '.join('?' for _ in names)})" if names else ""
    sql = f"""WITH base AS ({base}),
      ev0 AS (SELECT e.session_id, e.ts, e.id, e.event_key, e.event_name, coalesce(e.event_key, e.event_name) AS tok
              FROM events_base e JOIN base USING (session_id) WHERE NOT e.is_dup AND (e.event_key IS NOT NULL{named})),
      ev1 AS (SELECT *, CASE WHEN lag(tok) OVER w IS DISTINCT FROM tok THEN 1 ELSE 0 END AS chg FROM ev0 WINDOW w AS (PARTITION BY session_id ORDER BY ts, id)),
      ev2 AS (SELECT *, sum(chg) OVER (PARTITION BY session_id ORDER BY ts, id) AS pos FROM ev1),
      d AS (SELECT session_id, pos, any_value(event_key) AS k, list(DISTINCT event_name) AS names FROM ev2 GROUP BY 1, 2)"""
    args = [*a, *names]
    for i, act in enumerate(seq, 1):
        kind, _, v = act.partition(":")
        hit = "d.k = ?" if kind == "key" else "list_contains(d.names, ?)"
        if i == 1:
            sql += f",\n      m1 AS (SELECT d.session_id, min(d.pos) AS p FROM d WHERE {hit} GROUP BY 1)"
        else:
            after = f"d.pos = m{i - 1}.p + 1" if d.gap == "next" else f"d.pos > m{i - 1}.p"
            sql += f",\n      m{i} AS (SELECT d.session_id, min(d.pos) AS p FROM d JOIN m{i - 1} ON m{i - 1}.session_id = d.session_id WHERE {hit} AND {after} GROUP BY 1)"
        args.append(v)
    return f"{sql}\n SELECT session_id FROM m{len(seq)}", args


def _summary(match: str, args: list) -> dict:
    r = one(f"""SELECT count(*) AS visits, count(DISTINCT coalesce(s.user_id, s.visitor_key)) AS people, count(*) FILTER (WHERE {FLAG_ORDER}) AS ordered,
                coalesce(sum(o.order_value), 0) AS revenue
                FROM sessions s LEFT JOIN session_orders o ON o.session_id = s.session_id WHERE s.session_id IN ({match})""", args)
    r["revenue"] = round(float(r["revenue"] or 0), 2)
    return r


# ---------------------------------------------------------------- saved presets
def _row(r: dict) -> dict:
    d = r["definition"]
    r["definition"] = json.loads(d) if isinstance(d, str) else d
    return r


@app.get("/api/journey-presets")
def list_presets():
    rows = [_row(r) for r in q("SELECT id, name, note, definition, source, created_at, updated_at FROM journey_presets ORDER BY source = 'built-in', lower(name)")]
    actions = [{"action": f"key:{k}", "label": v, "group": "Key actions"} for k, v in KEY_ACTIONS.items()] + \
              [{"action": f"flag:{k}", "label": v, "group": "Outcome"} for k, v in FLAGS.items()]
    return {"presets": rows, "actions": actions, "max_steps": MAX_STEPS}


def _save(body: PresetIn, pid: int | None = None) -> int:
    name = body.name.strip()
    if not 1 <= len(name) <= 80:
        raise HTTPException(400, "give the preset a name (up to 80 characters)")
    d = _check(body.definition)
    with DB_LOCK:
        clash = core.CON.execute("SELECT id FROM journey_presets WHERE lower(name) = lower(?) AND id IS DISTINCT FROM ?", [name, pid]).fetchone()
        if clash:
            raise HTTPException(409, f"a preset called '{name}' already exists")
        if pid is None:
            return core.CON.execute("INSERT INTO journey_presets (name, note, definition) VALUES (?, ?, ?) RETURNING id",
                                    [name, (body.note or "").strip() or None, d.model_dump_json()]).fetchone()[0]
        if not core.CON.execute("SELECT 1 FROM journey_presets WHERE id = ?", [pid]).fetchone():
            raise HTTPException(404, "preset not found")
        core.CON.execute("UPDATE journey_presets SET name = ?, note = ?, definition = ?, updated_at = now() WHERE id = ?",
                         [name, (body.note or "").strip() or None, d.model_dump_json(), pid])
        return pid


@app.post("/api/journey-presets")
def add_preset(body: PresetIn):
    return {"id": _save(body)}


@app.put("/api/journey-presets/{pid}")
def update_preset(pid: int, body: PresetIn):
    return {"id": _save(body, pid)}


@app.delete("/api/journey-presets/{pid}")
def delete_preset(pid: int):
    with DB_LOCK:
        core.CON.execute("DELETE FROM journey_presets WHERE id = ?", [pid])
    return {"ok": True}


@app.get("/api/journey-presets/export")
def export_presets():
    rows = [{"name": r["name"], "note": r["note"], "definition": r["definition"]} for r in list_presets()["presets"]]
    body = json.dumps({"format": "roopsee-journey-presets", "version": 1, "exported": datetime.now().isoformat(timespec="seconds"), "presets": rows}, indent=2)
    return Response(body, media_type="application/json", headers={"Content-Disposition": "attachment; filename=journey-presets.json"})


class ImportIn(BaseModel):
    presets: list[PresetIn]


@app.post("/api/journey-presets/import")
def import_presets(body: ImportIn):
    """Adds the presets whose name is not taken yet; existing ones are left as they are."""
    if len(body.presets) > 200:
        raise HTTPException(400, "200 presets at most")
    have = {r["name"].lower() for r in q("SELECT name FROM journey_presets")}
    added, skipped = 0, 0
    for p in body.presets:
        if p.name.strip().lower() in have:
            skipped += 1
            continue
        _save(p)
        have.add(p.name.strip().lower())
        added += 1
    return {"added": added, "skipped": skipped}


# ---------------------------------------------------------------- matching
@app.get("/api/journey-presets/counts")
def preset_counts(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False):
    """Visits, people, orders and revenue for every saved preset in the dates (for the preset cards)."""
    tw, ta = sess_where(date_from, date_to, include_excluded)
    tot = one(f"SELECT count(*) AS n FROM sessions s WHERE {tw}", ta)["n"]
    out = {}
    for p in list_presets()["presets"]:
        try:
            m, a = _match_sql(Definition(**p["definition"]), date_from, date_to, include_excluded)
            r = _summary(m, a)
            r["of_all"] = ratio(r["visits"], tot)
        except HTTPException as e:  # a preset saved by an older version that no longer validates
            r = {"error": str(e.detail)}
        out[p["id"]] = r
    return {"total_visits": tot, "counts": out}


@app.post("/api/journey-presets/match")
def preset_match(body: Definition, date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, mode: str = "visits",
                 sort: str = "started_at", direction: str = "desc", limit: int = 50, offset: int = 0):
    """The visits (or people) matching a preset, saved or not, with a count after each step."""
    if mode not in ("visits", "people"):
        raise HTTPException(400, "mode must be visits or people")
    d = _check(body)
    m, a = _match_sql(d, date_from, date_to, include_excluded)
    summary = _summary(m, a)
    tw, ta = sess_where(date_from, date_to, include_excluded)
    summary["of_all"] = ratio(summary["visits"], one(f"SELECT count(*) AS n FROM sessions s WHERE {tw}", ta)["n"])
    steps = []
    for i in range(1, len(d.steps) + 1):
        mi, ai = _match_sql(d, date_from, date_to, include_excluded, upto=i) if i < len(d.steps) else (m, a)
        n = one(f"SELECT count(*) AS n FROM ({mi})", ai)["n"]
        s = d.steps[i - 1]
        steps.append({"action": s.action, "did": s.did, "label": ("" if s.did else "did not: ") + (_label(s.action) or s.action), "visits": n})
    dd = "ASC" if direction.lower() == "asc" else "DESC"
    lim, off = max(1, min(int(limit), 2000)), max(0, int(offset))
    frm = (f"FROM sessions s LEFT JOIN session_orders o ON o.session_id = s.session_id "
           f"LEFT JOIN users_360 u ON u.person_key = coalesce(s.user_id, s.visitor_key) WHERE s.session_id IN ({m})")
    if mode == "visits":
        rows = q(f"""SELECT s.session_id, s.started_at, s.duration_s, s.events, s.channel, s.campaign, s.city, s.device, s.is_app, s.key_events,
                     ({STAGE}) AS stage, o.order_value, coalesce(s.user_id, s.visitor_key) AS person_key, u.name, u.phone10, s.is_excluded
                     {frm} ORDER BY {VSORTS.get(sort, VSORTS['started_at'])} {dd} NULLS LAST, s.started_at DESC, s.session_id LIMIT ? OFFSET ?""", [*a, lim, off])
        total = summary["visits"]
    else:
        rows = q(f"""SELECT coalesce(s.user_id, s.visitor_key) AS person_key, count(*) AS visits, min(s.started_at) AS first_seen, max(s.started_at) AS last_seen,
                     max({STAGE}) AS stage, list(s.session_id ORDER BY s.started_at DESC) AS sessions, any_value(u.name) AS name, any_value(u.phone10) AS phone10,
                     any_value(u.city) AS city, any_value(u.first_channel) AS first_channel, coalesce(any_value(u.orders), 0) AS orders, coalesce(any_value(u.revenue), 0) AS revenue
                     {frm} GROUP BY 1 ORDER BY {PSORTS.get(sort, PSORTS['last_seen'])} {dd} NULLS LAST, 1 LIMIT ? OFFSET ?""", [*a, lim, off])
        for r in rows:
            r["latest_session"] = r.pop("sessions")[0]
        total = summary["people"]
    for r in rows:
        r["stage_name"] = STAGE_NAME[r["stage"]]
    return {"mode": mode, "total": total, "summary": summary, "steps": steps, "rows": rows}

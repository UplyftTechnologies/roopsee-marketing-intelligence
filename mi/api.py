"""FastAPI service: read-only analytics endpoints + editable exclusions + background refresh.

Run:  .venv\\Scripts\\python -m uvicorn mi.api:app --port 8000
The API process owns the DuckDB file (single writer). All access goes through DB_LOCK.
"""
import threading
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import extract, transform
from .config import ROOT
from .db import DB_LOCK, connect
from .transform import EXCLUSION_KINDS, EXCL_JOINS, RULE_SQL

CON = None
JOB = {"running": False, "name": None, "started": None, "finished": None, "message": "", "error": None}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global CON
    CON = connect()
    with DB_LOCK:
        transform.seed_exclusions(CON)
    yield
    CON.close()


app = FastAPI(title="Roopsee Marketing Intelligence", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


# ------------------------------------------------------------------ db helpers
def q(sql: str, args: list | tuple = ()) -> list[dict]:
    with DB_LOCK:
        cur = CON.cursor()
        try:
            cur.execute("SET TimeZone='Asia/Kolkata'")
            cur.execute(sql, list(args))
            if cur.description is None:
                return []
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
        finally:
            cur.close()


def one(sql: str, args=()) -> dict:
    r = q(sql, args)
    return r[0] if r else {}


def has_tables() -> bool:
    return bool(q("SELECT 1 FROM information_schema.tables WHERE table_name='sessions'"))


def sess_where(d_from, d_to, include_excluded, a="s") -> tuple[str, list]:
    w = [f"{a}.date_ist BETWEEN ? AND ?"]
    args = [d_from or "2000-01-01", d_to or "2999-12-31"]
    if not include_excluded:
        w.append(f"NOT {a}.is_excluded")
    return " AND ".join(w), args


def ratio(a, b):
    return round(a / b, 4) if b else 0


# ------------------------------------------------------------------ meta / jobs
@app.get("/api/meta")
def meta():
    out = {"job": JOB, "kinds": EXCLUSION_KINDS, "ready": False}
    out["raw_events"] = one("SELECT count(*) AS n, min(created_at) AS first, max(created_at) AS last FROM raw_event_log")
    if has_tables():
        out["ready"] = True
        out["counts"] = one("""SELECT (SELECT count(*) FROM events_clean) events, (SELECT count(*) FROM events_clean WHERE is_excluded) events_excluded,
            (SELECT count(*) FROM sessions) sessions, (SELECT count(*) FROM sessions WHERE is_excluded) sessions_excluded,
            (SELECT count(*) FROM users_360) people, (SELECT count(*) FROM users_360 WHERE is_excluded) people_excluded,
            (SELECT count(*) FROM orders_clean WHERE is_valid) orders, (SELECT count(*) FROM orders_clean WHERE is_valid AND is_excluded) orders_excluded""")
        out["range"] = one("SELECT min(date_ist) AS first, max(date_ist) AS last FROM sessions")
        out["last_transform"] = one("SELECT v FROM etl_meta WHERE k='last_transform'").get("v")
        tc = _tracking_change()
        out["tracking_change"] = str(tc) if tc else None
    return out


def _run_job(name: str, fn):
    def target():
        JOB.update(running=True, name=name, started=datetime.now().isoformat(timespec="seconds"), finished=None, message="", error=None)
        try:
            fn()
            JOB["message"] = "done"
        except Exception as e:  # surfaced in the UI
            JOB["error"] = f"{type(e).__name__}: {e}"
        finally:
            JOB.update(running=False, finished=datetime.now().isoformat(timespec="seconds"))
    if JOB["running"]:
        raise HTTPException(409, f"A job is already running: {JOB['name']}")
    threading.Thread(target=target, daemon=True).start()


@app.post("/api/refresh")
def refresh(mode: str = "full"):
    """full = pull new data from Supabase (read-only) then rebuild; transform = rebuild only."""
    def fn():
        if mode == "full":
            JOB["message"] = "extracting from Supabase"
            extract.run(CON.cursor())
        JOB["message"] = "transforming"
        transform.run(CON.cursor())
    _run_job(f"refresh:{mode}", fn)
    return JOB


@app.get("/api/jobs")
def jobs():
    return JOB


def _tracking_change():
    """Date the current tracker went live (first session_started event). Session ids, bounce and duration before it are not comparable."""
    return one("SELECT min(ts_ist)::DATE AS d FROM events_clean WHERE event_name = 'session_started'").get("d")


# ------------------------------------------------------------------ overview
def _kpis(d_from, d_to, include_excluded) -> dict:
    w, a = sess_where(d_from, d_to, include_excluded)
    k = one(f"""SELECT count(*) sessions, count(DISTINCT visitor_key) visitors, count(DISTINCT coalesce(user_id, visitor_key)) people,
        coalesce(sum(pageviews),0) pageviews, count(*) FILTER (WHERE f_product) product_sessions,
        count(*) FILTER (WHERE f_cart) cart_sessions, count(*) FILTER (WHERE f_checkout) checkout_sessions,
        count(*) FILTER (WHERE f_quiz_done) quiz_done, count(*) FILTER (WHERE f_quiz_start) quiz_started,
        count(*) FILTER (WHERE is_bounce) bounced, count(*) FILTER (WHERE is_app) app_sessions,
        coalesce(avg(duration_s) FILTER (WHERE duration_s > 0),0) avg_duration_s
        FROM sessions s WHERE {w}""", a)
    ow = "date_ist BETWEEN ? AND ? AND is_valid" + ("" if include_excluded else " AND NOT is_excluded")
    o = one(f"SELECT count(*) orders, coalesce(sum(revenue),0) revenue FROM orders_clean WHERE {ow}", a)
    k.update(orders=o["orders"], revenue=o["revenue"], aov=ratio(o["revenue"], o["orders"]),
             order_cvr=ratio(o["orders"], k["sessions"]), cart_rate=ratio(k["cart_sessions"], k["sessions"]),
             bounce_rate=ratio(k["bounced"], k["sessions"]))
    return k


def prev_range(d_from, d_to):
    """The equally long period right before [d_from, d_to]; None for an open-ended range ("All time")."""
    if not d_from or not d_to:
        return None
    a, b = date.fromisoformat(d_from), date.fromisoformat(d_to)
    n = (b - a).days + 1
    pt = a - timedelta(days=1)
    return (pt - timedelta(days=n - 1)).isoformat(), pt.isoformat()


@app.get("/api/overview")
def overview(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False):
    w, a = sess_where(date_from, date_to, include_excluded)
    ow = "date_ist BETWEEN ? AND ? AND is_valid" + ("" if include_excluded else " AND NOT is_excluded")
    k = _kpis(date_from, date_to, include_excluded)
    pr = prev_range(date_from, date_to)
    prev = _kpis(pr[0], pr[1], include_excluded) if pr else None
    daily = q(f"""SELECT s.date_ist AS date, count(*) sessions, count(DISTINCT visitor_key) visitors,
        count(*) FILTER (WHERE f_cart) carts, count(*) FILTER (WHERE f_checkout) checkouts FROM sessions s WHERE {w} GROUP BY 1 ORDER BY 1""", a)
    od = {r["date"]: r for r in q(f"SELECT date_ist AS date, count(*) orders, sum(revenue) revenue FROM orders_clean WHERE {ow} GROUP BY 1", a)}
    for r in daily:
        r["orders"] = od.get(r["date"], {}).get("orders", 0)
        r["revenue"] = od.get(r["date"], {}).get("revenue", 0) or 0
    channels = q(f"""SELECT channel, count(*) sessions, count(*) FILTER (WHERE f_cart) carts, count(*) FILTER (WHERE f_order) orders
        FROM sessions s WHERE {w} GROUP BY 1 ORDER BY 2 DESC""", a)
    devices = q(f"SELECT coalesce(CASE WHEN is_app THEN 'Android app' ELSE device END,'Unknown') device, count(*) sessions FROM sessions s WHERE {w} GROUP BY 1 ORDER BY 2 DESC", a)
    hours = q(f"""SELECT extract(dow FROM timezone('Asia/Kolkata', started_at))::INT AS dow, extract(hour FROM timezone('Asia/Kolkata', started_at))::INT AS hour,
        count(*) sessions FROM sessions s WHERE {w} GROUP BY 1,2""", a)
    landing = q(f"SELECT landing_type, count(*) sessions, count(*) FILTER (WHERE f_cart) carts FROM sessions s WHERE {w} GROUP BY 1 ORDER BY 2 DESC LIMIT 8", a)
    staff = one("SELECT count(*) orders, coalesce(sum(total),0) revenue FROM orders_clean WHERE date_ist BETWEEN ? AND ? AND is_valid AND is_staff_order", a)
    rule_on = bool(q("SELECT 1 FROM exclusions WHERE kind='rule' AND value='staff_orders' AND active"))
    return {"kpis": k, "prev": prev, "prev_range": pr, "staff_orders": {**staff, "excluded": rule_on}, "daily": daily, "channels": channels, "devices": devices, "hours": hours, "landing": landing}


# ------------------------------------------------------------------ funnel / checkout
@app.get("/api/funnel")
def funnel(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, channel: str | None = None):
    w, a = sess_where(date_from, date_to, include_excluded)
    if channel:
        w += " AND s.channel = ?"; a.append(channel)
    r = one(f"""SELECT count(*) visit, count(*) FILTER (WHERE f_product) product, count(*) FILTER (WHERE f_cart) cart,
        count(*) FILTER (WHERE f_checkout) checkout, count(*) FILTER (WHERE f_pay) pay, count(*) FILTER (WHERE f_order) ordered,
        count(*) FILTER (WHERE f_quiz_start) quiz_start, count(*) FILTER (WHERE f_quiz_done) quiz_done,
        count(*) FILTER (WHERE f_quiz_done AND f_cart) quiz_to_cart, count(*) FILTER (WHERE f_login) login
        FROM sessions s WHERE {w}""", a)
    steps = [("Sessions", r["visit"]), ("Viewed a product", r["product"]), ("Added to cart", r["cart"]),
             ("Reached checkout", r["checkout"]), ("Started payment", r["pay"]), ("Order placed", r["ordered"])]
    stages = [{"stage": n, "sessions": v, "of_first": ratio(v, r["visit"]), "of_prev": ratio(v, steps[i - 1][1]) if i else 1}
              for i, (n, v) in enumerate(steps)]
    cw = "s.date_ist BETWEEN ? AND ?" + ("" if include_excluded else " AND NOT s.is_excluded")
    ca = [date_from or "2000-01-01", date_to or "2999-12-31"]
    outcomes = q(f"""SELECT outcome, count(*) sessions, coalesce(avg(cart_value),0) avg_cart_value, coalesce(sum(cart_value),0) cart_value
        FROM checkout c JOIN sessions s USING (session_id) WHERE {cw} GROUP BY 1 ORDER BY 2 DESC""", ca)
    methods = q(f"SELECT coalesce(payment_method,'unknown') method, outcome, count(*) n FROM checkout c JOIN sessions s USING (session_id) WHERE {cw} GROUP BY 1,2 ORDER BY 3 DESC", ca)
    abandoned = q(f"""SELECT c.session_id, c.checkout_at, c.outcome, c.cart_value, c.payment_method, c.channel, c.campaign, c.city, c.device,
        c.phone10, c.user_id, u.name FROM checkout c JOIN sessions s USING (session_id)
        LEFT JOIN users_360 u ON u.person_key = coalesce(s.user_id, s.visitor_key)
        WHERE {cw} AND c.outcome IN ('payment_abandoned','checkout_abandoned') ORDER BY c.checkout_at DESC LIMIT 40""", ca)
    products = q(f"""SELECT product_name, brand, count(*) adds, count(DISTINCT session_id) sessions FROM events_clean e
        WHERE event_key = 'add_to_cart' AND product_name IS NOT NULL AND product_name <> ''
        AND (? OR NOT is_excluded) AND timezone('Asia/Kolkata', ts)::DATE BETWEEN ? AND ?
        GROUP BY 1,2 ORDER BY 3 DESC LIMIT 15""", [include_excluded, *ca])
    actual = one("SELECT count(*) n FROM orders_clean WHERE date_ist BETWEEN ? AND ? AND is_valid" + ("" if include_excluded else " AND NOT is_excluded"),
                 [date_from or "2000-01-01", date_to or "2999-12-31"])["n"]
    return {"actual_orders": actual, "stages": stages, "quiz": {k: r[k] for k in ("quiz_start", "quiz_done", "quiz_to_cart", "login")},
            "checkout_outcomes": outcomes, "payment_methods": methods, "abandoned": abandoned, "top_products": products}


# ------------------------------------------------------------------ campaigns
@app.get("/api/campaigns")
def campaigns(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, min_sessions: int = 1):
    w = "date_ist BETWEEN ? AND ?" + ("" if include_excluded else " AND NOT is_excluded")
    rows = q(f"""SELECT channel, source, medium, campaign, sum(sessions) sessions, sum(visitors) visitors, sum(engaged_sessions) engaged,
        sum(quiz_done) quiz_done, sum(carts) carts, sum(checkouts) checkouts, sum(orders) orders, sum(revenue) revenue,
        sum(ft_orders) ft_orders, sum(ft_revenue) ft_revenue,
        min(date_ist) first_day, max(date_ist) last_day
        FROM campaign_performance WHERE {w} GROUP BY 1,2,3,4 HAVING sum(sessions) >= ? ORDER BY greatest(sum(orders), sum(ft_orders)) DESC, carts DESC, sessions DESC""",
             [date_from or "2000-01-01", date_to or "2999-12-31", min_sessions])
    tot_s = sum(r["sessions"] for r in rows); tot_c = sum(r["carts"] for r in rows)
    base_cart = ratio(tot_c, tot_s)
    for r in rows:
        r.update(engaged_rate=ratio(r["engaged"], r["sessions"]), quiz_rate=ratio(r["quiz_done"], r["sessions"]),
                 cart_rate=ratio(r["carts"], r["sessions"]), checkout_rate=ratio(r["checkouts"], r["sessions"]),
                 order_cvr=ratio(r["orders"], r["sessions"]), rev_per_session=round(r["revenue"] / r["sessions"], 2) if r["sessions"] else 0)
        r["best_orders"] = max(r["orders"], r["ft_orders"])
        r["best_revenue"] = max(r["revenue"], r["ft_revenue"])
        if r["best_orders"] >= 2 and r["cart_rate"] >= base_cart:
            r["verdict"] = "Winning"
        elif r["best_orders"] > 0:
            r["verdict"] = "Converting"
        elif r["sessions"] >= 30 and r["cart_rate"] >= base_cart:
            r["verdict"] = "Promising"
        elif r["sessions"] >= 100 and r["carts"] == 0:
            r["verdict"] = "No carts - review"
        else:
            r["verdict"] = "Too early"
    return {"rows": rows, "baseline_cart_rate": base_cart}


# ------------------------------------------------------------------ cohorts / geography
COHORT_DIMS = {"state": "state", "city": "city", "age": "age_bucket", "gender": "gender", "channel": "first_channel",
               "campaign": "first_campaign", "device": "device", "segment": "segment", "skin_type": "skin_type", "landing": "first_landing"}


@app.get("/api/cohorts")
def cohorts(dim: str = "state", date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, limit: int = 40):
    if dim not in COHORT_DIMS:
        raise HTTPException(400, f"dim must be one of {list(COHORT_DIMS)}")
    col = COHORT_DIMS[dim]
    w = "timezone('Asia/Kolkata', first_seen)::DATE BETWEEN ? AND ?" + ("" if include_excluded else " AND NOT is_excluded")
    rows = q(f"""SELECT coalesce({col}::VARCHAR, 'Unknown') AS value, count(*) people, sum(sessions) sessions,
        count(*) FILTER (WHERE cart_sessions > 0) carted, count(*) FILTER (WHERE checkout_sessions > 0) checked_out,
        count(*) FILTER (WHERE orders > 0) buyers, count(*) FILTER (WHERE orders > 1) repeat_buyers, coalesce(sum(revenue),0) revenue,
        count(*) FILTER (WHERE quiz_sessions > 0) quiz_done
        FROM users_360 WHERE {w} GROUP BY 1 ORDER BY people DESC LIMIT ?""", [date_from or "2000-01-01", date_to or "2999-12-31", limit])
    for r in rows:
        r.update(cart_rate=ratio(r["carted"], r["people"]), buyer_rate=ratio(r["buyers"], r["people"]),
                 avg_sessions=round(r["sessions"] / r["people"], 2) if r["people"] else 0)
    return {"dim": dim, "rows": rows}


@app.get("/api/retention")
def retention(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, weeks: int = 8):
    w = "timezone('Asia/Kolkata', u.first_seen)::DATE BETWEEN ? AND ?" + ("" if include_excluded else " AND NOT u.is_excluded")
    rows = q(f"""WITH c AS (SELECT person_key, date_trunc('week', timezone('Asia/Kolkata', first_seen))::DATE AS cw, (orders > 0) AS bought
                  FROM users_360 u WHERE {w}),
        r AS (SELECT c.cw, ((pw.week - c.cw) / 7)::INT AS n, count(DISTINCT c.person_key) active
              FROM c JOIN person_weeks pw USING (person_key) WHERE pw.week >= c.cw AND ((pw.week - c.cw) / 7) <= ? GROUP BY 1,2),
        s AS (SELECT cw, count(*) size, count(*) FILTER (WHERE bought) buyers FROM c GROUP BY 1)
        SELECT s.cw AS cohort_week, s.size, s.buyers, r.n, r.active FROM s JOIN r USING (cw) ORDER BY 1, 4""",
             [date_from or "2000-01-01", date_to or "2999-12-31", weeks])
    out = {}
    for r in rows:
        c = out.setdefault(str(r["cohort_week"]), {"cohort_week": r["cohort_week"], "size": r["size"], "buyers": r["buyers"], "weeks": {}})
        c["weeks"][r["n"]] = ratio(r["active"], r["size"])
    return {"weeks": weeks, "cohorts": list(out.values())}


# ------------------------------------------------------------------ sessions / users / events
@app.get("/api/sessions")
def sessions(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, search: str | None = None,
             min_stage: int = 0, channel: str | None = None, only_excluded: bool = False, limit: int = 50, offset: int = 0):
    w, a = sess_where(date_from, date_to, include_excluded)
    if only_excluded:
        w += " AND s.is_excluded"
    if min_stage:
        w += " AND s.stage >= ?"; a.append(min_stage)
    if channel:
        w += " AND s.channel = ?"; a.append(channel)
    if search:
        like = f"%{search.lower()}%"
        w += """ AND (lower(s.session_id) LIKE ? OR lower(s.visitor_key) LIKE ? OR lower(coalesce(s.user_id,'')) LIKE ? OR coalesce(s.ip,'') LIKE ?
                 OR coalesce(s.phone10,'') LIKE ? OR lower(coalesce(s.city,'')) LIKE ? OR lower(coalesce(u.name,'')) LIKE ? OR lower(s.campaign) LIKE ?)"""
        a += [like] * 8
    base = f"FROM sessions s LEFT JOIN users_360 u ON u.person_key = coalesce(s.user_id, s.visitor_key) WHERE {w}"
    total = one(f"SELECT count(*) n {base}", a)["n"]
    rows = q(f"""SELECT s.session_id, s.started_at, s.duration_s, s.events, s.pageviews, s.channel, s.source, s.medium, s.campaign, s.landing_path,
        s.city, s.region, s.country, s.device, s.platform, s.is_app, s.user_id, u.name, s.phone10, s.ip, s.visitor_key, s.key_events, s.stage,
        s.is_excluded, s.excl_reason {base} ORDER BY s.started_at DESC LIMIT ? OFFSET ?""", [*a, limit, offset])
    return {"total": total, "rows": rows}


@app.get("/api/sessions/{session_id}")
def session_detail(session_id: str):
    s = q("SELECT * FROM sessions WHERE session_id = ?", [session_id])
    if not s:
        raise HTTPException(404, "session not found")
    ev = q("""SELECT timezone('Asia/Kolkata', ts) AS at, event_name, event_key, page_type, path, product_name, brand, amount, search_term, city_n, ip
              FROM events_clean WHERE session_id = ? ORDER BY ts, id LIMIT 600""", [session_id])
    return {"session": s[0], "events": ev}


@app.get("/api/users")
def users(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, search: str | None = None,
          segment: str | None = None, sort: str = "last_seen", limit: int = 50, offset: int = 0):
    w = "timezone('Asia/Kolkata', last_seen)::DATE >= ? AND timezone('Asia/Kolkata', first_seen)::DATE <= ?" + ("" if include_excluded else " AND NOT is_excluded")
    a = [date_from or "2000-01-01", date_to or "2999-12-31"]
    if segment:
        w += " AND segment = ?"; a.append(segment)
    if search:
        like = f"%{search.lower()}%"
        w += " AND (lower(coalesce(name,'')) LIKE ? OR coalesce(phone10,'') LIKE ? OR lower(coalesce(email,'')) LIKE ? OR lower(person_key) LIKE ? OR lower(coalesce(city,'')) LIKE ?)"
        a += [like] * 5
    order = {"last_seen": "last_seen DESC", "revenue": "revenue DESC, last_seen DESC", "sessions": "sessions DESC",
             "first_seen": "first_seen DESC"}.get(sort, "last_seen DESC")
    total = one(f"SELECT count(*) n FROM users_360 WHERE {w}", a)["n"]
    rows = q(f"""SELECT person_key, user_id, name, phone10, email, is_registered, first_seen, last_seen, sessions, first_channel, first_campaign,
        city, state, device, uses_app, cart_sessions, checkout_sessions, orders, revenue, gender, skin_type, age_bucket, segment, is_excluded
        FROM users_360 WHERE {w} ORDER BY {order} LIMIT ? OFFSET ?""", [*a, limit, offset])
    segs = q(f"SELECT segment, count(*) n FROM users_360 WHERE {'TRUE' if include_excluded else 'NOT is_excluded'} GROUP BY 1 ORDER BY 2 DESC")
    return {"total": total, "rows": rows, "segments": segs}


@app.get("/api/events/catalogue")
def catalogue(include_excluded: bool = False):
    return q("""SELECT event_name, coalesce(event_key,'(not a key event)') AS event_key, count(*) events, count(DISTINCT session_id) sessions,
        min(ts) AS first_seen, max(ts) AS last_seen FROM events_clean WHERE (? OR NOT is_excluded) GROUP BY 1,2 ORDER BY 3 DESC LIMIT 300""", [include_excluded])


# ------------------------------------------------------------------ exclusions (user-editable)
class ExclIn(BaseModel):
    kind: str
    value: str
    note: str | None = None
    active: bool = True


class ExclPatch(BaseModel):
    kind: str | None = None
    value: str | None = None
    note: str | None = None
    active: bool | None = None


def _check_kind(kind: str):
    if kind not in EXCLUSION_KINDS:
        raise HTTPException(400, f"kind must be one of {list(EXCLUSION_KINDS)}")


def _reapply():
    _run_job("apply-exclusions", lambda: transform.run(CON.cursor()))


@app.get("/api/exclusions")
def list_exclusions():
    return {"kinds": EXCLUSION_KINDS, "rows": q("SELECT * FROM exclusions ORDER BY active DESC, id DESC")}


@app.post("/api/exclusions")
def add_exclusions(body: ExclIn, apply: bool = True):
    """`value` may hold several entries separated by newlines or commas."""
    _check_kind(body.kind)
    vals = [v.strip() for v in body.value.replace(",", "\n").splitlines() if v.strip()]
    if not vals:
        raise HTTPException(400, "value is empty")
    ids = []
    with DB_LOCK:
        for v in vals:
            if CON.execute("SELECT 1 FROM exclusions WHERE kind=? AND lower(value)=lower(?)", [body.kind, v]).fetchone():
                continue
            ids.append(CON.execute("INSERT INTO exclusions (kind, value, note, active) VALUES (?,?,?,?) RETURNING id",
                                   [body.kind, v, body.note, body.active]).fetchone()[0])
    if apply and ids and not JOB["running"]:
        _reapply()
    return {"added": len(ids), "ids": ids, "job": JOB}


@app.put("/api/exclusions/{eid}")
def update_exclusion(eid: int, body: ExclPatch, apply: bool = True):
    if body.kind:
        _check_kind(body.kind)
    sets, args = [], []
    for f in ("kind", "value", "note", "active"):
        v = getattr(body, f)
        if v is not None:
            sets.append(f"{f} = ?"); args.append(v.strip() if isinstance(v, str) else v)
    if not sets:
        raise HTTPException(400, "nothing to update")
    with DB_LOCK:
        if not CON.execute("SELECT 1 FROM exclusions WHERE id=?", [eid]).fetchone():
            raise HTTPException(404, "not found")
        CON.execute(f"UPDATE exclusions SET {', '.join(sets)}, updated_at = now() WHERE id = ?", [*args, eid])
    if apply and not JOB["running"]:
        _reapply()
    return {"ok": True, "job": JOB}


@app.delete("/api/exclusions/{eid}")
def delete_exclusion(eid: int, apply: bool = True):
    with DB_LOCK:
        CON.execute("DELETE FROM exclusions WHERE id=?", [eid])
    if apply and not JOB["running"]:
        _reapply()
    return {"ok": True, "job": JOB}


@app.post("/api/exclusions/apply")
def apply_exclusions():
    _reapply()
    return JOB


@app.get("/api/exclusions/preview")
def preview_exclusion(kind: str, value: str):
    """How much traffic would this exclusion remove? Evaluated against the current clean tables."""
    _check_kind(kind)
    v = value.strip()
    if kind in ("source", "campaign", "channel"):
        col = {"source": "source", "campaign": "campaign", "channel": "channel"}[kind]
        r = one(f"SELECT count(*) sessions, coalesce(sum(events),0) events FROM sessions WHERE lower({col}) = lower(?)", [v])
        return {"sessions": r["sessions"], "events": r["events"], "people": None}
    if kind == "rule":
        cond = next((c for n, c, _ in RULE_SQL if n == v), None)
        if not cond:
            raise HTTPException(400, f"unknown rule; use one of {[n for n, _, _ in RULE_SQL]}")
    else:
        cond = next(c for k, c, _ in EXCL_JOINS if k == kind)
    sql = f"""SELECT count(*) events, count(DISTINCT e.session_id) sessions, count(DISTINCT e.person_key) people
              FROM events_clean e, (SELECT lower(trim(?)) AS v) x WHERE {cond if kind != 'rule' else cond}"""
    return one(sql, [v])


@app.get("/api/lookup")
def lookup(q_: str = Query(..., alias="q", min_length=2), limit: int = 12):
    """Find identifiers (names, IPs, phones, ids...) so they can be excluded with one click."""
    like = f"%{q_.lower()}%"
    cols = [("name", "coalesce(nullif(account_name,''), nullif(user_name,''))"), ("ip", "ip"), ("phone", "phone10"),
            ("email", "email_l"), ("session_id", "session_id"), ("visitor_id", "visitor_key"), ("user_id", "user_id"),
            ("city", "city_n"), ("host", "host")]
    out = []
    for kind, expr in cols:
        for r in q(f"""SELECT '{kind}' AS kind, {expr} AS value, count(*) events, count(DISTINCT session_id) sessions, max(ts) AS last_seen,
                       bool_and(is_excluded) AS excluded FROM events_clean WHERE lower({expr}) LIKE ? AND {expr} IS NOT NULL
                       AND {expr} NOT IN ('Guest') GROUP BY 2 ORDER BY 3 DESC LIMIT ?""", [like, limit]):
            out.append(r)
    return out



# ------------------------------------------------------------------ insights (plain-language findings)
def _chg(cur, prev):
    return None if not prev else (cur - prev) / prev


@app.get("/api/insights")
def insights(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False):
    """Rule-based findings for the selected range. Each has a tone (good / warn / bad / info) and a drill-down target."""
    k = _kpis(date_from, date_to, include_excluded)
    pr = prev_range(date_from, date_to)
    prev = _kpis(pr[0], pr[1], include_excluded) if pr else None
    out = []

    def add(tone, title, detail, tab=None, filters=None):
        out.append({"tone": tone, "title": title, "detail": detail, "tab": tab, "filters": filters or {}})

    # 1. trend vs the previous period
    thin = False
    if prev:
        n_days = (date.fromisoformat(date_to) - date.fromisoformat(date_from)).days + 1
        covered = one("SELECT count(*) n FROM (SELECT date_ist FROM sessions WHERE date_ist BETWEEN ? AND ?" + ("" if include_excluded else " AND NOT is_excluded") + " GROUP BY 1 HAVING count(*) >= 30)", list(pr))["n"]
        tc = _tracking_change()
        prev_old = bool(tc and pr[0] < str(tc))
        thin = covered < 0.7 * n_days or prev_old
    if prev and prev["sessions"] >= 50:
        c = _chg(k["sessions"], prev["sessions"])
        word = "up" if c >= 0 else "down"
        note = ""
        if prev_old:
            note = f" Tracking was upgraded on {tc}, so session counts before that date are not directly comparable."
        elif thin:
            note = f" Only {covered} of {n_days} days in that earlier period have meaningful tracking data, so this comparison overstates the change."
        add("info" if thin else "good" if c >= 0.1 else "bad" if c <= -0.1 else "info", f"Traffic is {word} {abs(c) * 100:.0f}% on the previous period",
            f"{k['sessions']:,} sessions vs {prev['sessions']:,} in {pr[0]} to {pr[1]}." + note, "performance")
    if prev and (k["orders"] or prev["orders"]):
        c = _chg(k["orders"], prev["orders"])
        add("good" if (c or 0) >= 0.1 else "bad" if (c or 0) <= -0.1 else "info",
            f"{k['orders']} orders (₹{k['revenue']:,.0f})" + (f", {'up' if c >= 0 else 'down'} {abs(c) * 100:.0f}% on before" if c is not None else ""),
            f"Previous period: {prev['orders']} orders (₹{prev['revenue']:,.0f}). Average order value ₹{k['aov']:,.0f}.", "performance")

    # 2. biggest leak in the purchase funnel
    f = funnel(date_from, date_to, include_excluded, None)
    st = f["stages"]
    leaks = [(st[i]["of_prev"], i) for i in range(2, 6) if st[i - 1]["sessions"] >= 20]
    if leaks:
        rate, i = min(leaks)
        add("warn", f"Biggest leak: {st[i - 1]['stage']} → {st[i]['stage']}",
            f"Only {rate * 100:.0f}% continue; {st[i - 1]['sessions'] - st[i]['sessions']:,} sessions stop here.", "funnel")

    # 3. abandoned checkouts that can still be recovered (phone known, no later order)
    end = date_to or one("SELECT max(date_ist) AS d FROM sessions")["d"]
    start7 = (date.fromisoformat(str(end)) - timedelta(days=6)).isoformat()
    ab = one(f"""SELECT count(DISTINCT c.phone10) people, coalesce(sum(c.cart_value),0) value FROM checkout c JOIN sessions s USING (session_id)
        WHERE s.date_ist BETWEEN ? AND ? {'' if include_excluded else 'AND NOT s.is_excluded'} AND c.outcome IN ('checkout_abandoned','payment_abandoned')
        AND c.phone10 IS NOT NULL AND c.phone10 NOT IN (SELECT phone10 FROM orders_clean WHERE is_valid AND phone10 IS NOT NULL)""", [start7, str(end)])
    if ab["people"]:
        add("warn", f"{ab['people']} people with a known phone left checkout in the last 7 days",
            f"They haven't ordered since. Cart value where recorded: ₹{ab['value']:,.0f}. A reminder message here is the quickest win.", "funnel")

    # 4. campaigns: best performer and wasted traffic
    camps = campaigns(date_from, date_to, include_excluded, 1)["rows"]
    won = [c for c in camps if c["best_orders"] >= 1]
    if won:
        c = max(won, key=lambda r: (r["best_orders"], r["best_revenue"]))
        label = f"{c['channel']} traffic with no campaign tag" if c["campaign"] == "(not set)" else f"{c['campaign']} ({c['channel']})"
        add("good", f"Best converting source: {label}",
            f"{c['best_orders']} orders, ₹{c['best_revenue']:,.0f}, from {c['sessions']:,} sessions ({c['cart_rate'] * 100:.1f}% added to cart).", "campaigns")
    waste = sorted([c for c in camps if c["sessions"] >= 200 and c["carts"] == 0], key=lambda r: -r["sessions"])[:3]
    if waste:
        add("bad", f"{len(waste)} campaign{'s' if len(waste) > 1 else ''} with 200+ sessions and zero add-to-carts",
            "; ".join(f"{c['campaign']} ({c['channel']}, {c['sessions']:,} sessions)" for c in waste) + ". Worth reviewing the targeting or landing page.", "campaigns")

    # 5. channel that adds to cart best vs worst
    w, a = sess_where(date_from, date_to, include_excluded)
    ch = [r for r in q(f"SELECT channel, count(*) sessions, count(*) FILTER (WHERE f_cart) carts FROM sessions s WHERE {w} GROUP BY 1 HAVING count(*) >= 200", a)]
    if len(ch) >= 2:
        for r in ch:
            r["rate"] = r["carts"] / r["sessions"]
        hi, lo = max(ch, key=lambda r: r["rate"]), min(ch, key=lambda r: r["rate"])
        if hi["rate"] >= 1.5 * max(lo["rate"], 1e-9):
            add("info", f"{hi['channel']} visitors add to cart most ({hi['rate'] * 100:.1f}%)",
                f"Compare {lo['channel']}: {lo['rate'] * 100:.1f}% on {lo['sessions']:,} sessions.", "sessions", {"channel": hi["channel"]})

    # 6. mobile vs desktop
    dv = {r["device"]: r for r in q(f"SELECT device, count(*) sessions, count(*) FILTER (WHERE f_cart) carts FROM sessions s WHERE {w} AND device IN ('Mobile','Desktop') AND NOT is_app GROUP BY 1", a)}
    if len(dv) == 2 and min(v["sessions"] for v in dv.values()) >= 200:
        m, d = dv["Mobile"], dv["Desktop"]
        mr, dr = m["carts"] / m["sessions"], d["carts"] / d["sessions"]
        if dr >= 1.5 * mr or mr >= 1.5 * dr:
            add("warn" if dr > mr and m["sessions"] > d["sessions"] else "info", f"{'Desktop' if dr > mr else 'Mobile'} adds to cart {max(dr, mr) / max(min(dr, mr), 1e-9):.1f}× as often",
                f"Mobile {mr * 100:.1f}% of {m['sessions']:,} sessions, desktop {dr * 100:.1f}% of {d['sessions']:,}.", "cohorts")

    # 7. peak hour
    hr = one(f"SELECT extract(hour FROM timezone('Asia/Kolkata', started_at))::INT AS h, count(*) n FROM sessions s WHERE {w} GROUP BY 1 ORDER BY 2 DESC LIMIT 1", a)
    if hr:
        h = hr["h"]
        add("info", f"Most visits start between {h % 12 or 12}{'am' if h < 12 else 'pm'} and {(h + 1) % 12 or 12}{'am' if (h + 1) % 24 < 12 else 'pm'} IST",
            f"{hr['n']:,} sessions began in that hour. Useful for timing posts, ads and messages.", "performance")

    # 8. bounce
    if k["sessions"] >= 200 and k["bounce_rate"] > 0.4:
        add("warn", f"{k['bounce_rate'] * 100:.0f}% of sessions leave without doing anything",
            "One page view or fewer, no clicks, scrolls or searches. Check landing pages and ad-to-page match.", "campaigns")

    # 9. staff orders (so the number is never silently hidden)
    so = one("SELECT count(*) n, coalesce(sum(total),0) v FROM orders_clean WHERE date_ist BETWEEN ? AND ? AND is_valid AND is_staff_order", [date_from or "2000-01-01", date_to or "2999-12-31"])
    if so["n"]:
        on = bool(q("SELECT 1 FROM exclusions WHERE kind='rule' AND value='staff_orders' AND active"))
        add("info", f"{so['n']} orders (₹{so['v']:,.0f}) came from admin / staff accounts",
            ("They are excluded from every number here." if on else "They are counted as real customer orders.") + " Change this in Exclusions.", "exclusions")
    return {"kpis": k, "prev": prev, "prev_range": pr, "insights": out}


# ------------------------------------------------------------------ static dashboard (after `npm run build`)
DIST = ROOT / "dashboard" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=str(DIST), html=True), name="dashboard")

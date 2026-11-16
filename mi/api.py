"""FastAPI service: read-only analytics endpoints + editable exclusions + background refresh.

Run:  .venv\\Scripts\\python -m uvicorn mi.api:app --port 8000
The API process owns the DuckDB file (single writer). All access goes through DB_LOCK.
"""
import threading
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

import csv
import io
import json

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import extract, transform
from . import meta as meta_mod
from .config import ROOT
from .db import DB_LOCK, connect
from .transform import EXCLUSION_KINDS, EXCL_JOINS, RULE_SQL

CON = None
PENDING = {"reapply": False}
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
            if PENDING["reapply"]:
                PENDING["reapply"] = False
                try:
                    _reapply()
                except Exception:  # never let a follow-up failure mask the first job's result
                    pass
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
            if meta_mod.configured():
                JOB["message"] = "pulling Meta Ads"
                try:
                    meta_mod.sync(CON.cursor())
                except Exception as e:  # keep the refresh going; the error is shown on the Meta Ads page
                    meta_mod.record_error(CON.cursor(), e)
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
# what a session "did" (used by the multi-select filters and the abandoner presets)
FLAG_ORDER = "(s.f_order OR coalesce(o.n_orders, 0) > 0)"
FLAG_LOGIN = "(s.f_login OR s.user_id IS NOT NULL)"
SESSION_FLAGS = {"product": "s.f_product", "cart": "s.f_cart", "checkout": "s.f_checkout", "pay": "s.f_pay", "order": FLAG_ORDER,
                 "login": FLAG_LOGIN, "quiz": "s.f_quiz_done", "search": "s.f_search"}
EMAIL = "coalesce(nullif(lower(u.email), ''), o.order_email)"
SESSION_SORTS = {"started_at": "s.started_at", "events": "s.events", "duration_s": "s.duration_s", "order_value": "coalesce(o.order_value, 0)",
                 "channel": "s.channel", "campaign": "s.campaign", "city": "nullif(lower(s.city), '')", "name": "nullif(lower(u.name), '')", "email": EMAIL,
                 "stage": "s.stage", "device": "s.device"}
ORD_CTE = """WITH o AS (SELECT session_id, count(*) FILTER (WHERE NOT is_test) AS n_orders,
    sum(total) FILTER (WHERE is_valid AND NOT is_test) AS order_value, sum(total) FILTER (WHERE NOT is_valid AND NOT is_test) AS other_value,
    string_agg(DISTINCT status, ', ') FILTER (WHERE NOT is_test) AS statuses, any_value(email_l) FILTER (WHERE email_l IS NOT NULL) AS order_email
    FROM orders_clean WHERE session_id IS NOT NULL GROUP BY 1)"""
SESS_FROM = " FROM sessions s LEFT JOIN o ON o.session_id = s.session_id LEFT JOIN users_360 u ON u.person_key = coalesce(s.user_id, s.visitor_key)"


def _csv(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def _sessions_where(d_from, d_to, include_excluded, search=None, channel=None, only_excluded=False, min_stage=0, has=None, lacks=None, match="any"):
    w, a = sess_where(d_from, d_to, include_excluded)
    if only_excluded:
        w += " AND s.is_excluded"
    if min_stage:
        w += " AND s.stage >= ?"
        a.append(min_stage)
    if channel:
        w += " AND s.channel = ?"
        a.append(channel)
    hs = [SESSION_FLAGS[k] for k in _csv(has) if k in SESSION_FLAGS]
    if hs:
        w += " AND (" + (" AND " if match == "all" else " OR ").join(hs) + ")"
    for k in _csv(lacks):
        if k in SESSION_FLAGS:
            w += f" AND NOT {SESSION_FLAGS[k]}"
    if search:
        like = f"%{search.lower()}%"
        w += f""" AND (lower(s.session_id) LIKE ? OR lower(s.visitor_key) LIKE ? OR lower(coalesce(s.user_id,'')) LIKE ? OR coalesce(s.ip,'') LIKE ?
                 OR coalesce(s.phone10,'') LIKE ? OR lower(coalesce(s.city,'')) LIKE ? OR lower(coalesce(u.name,'')) LIKE ? OR lower(s.campaign) LIKE ?
                 OR lower(coalesce({EMAIL}, '')) LIKE ?)"""
        a += [like] * 9
    return w, a


@app.get("/api/sessions")
def sessions(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, search: str | None = None,
             min_stage: int = 0, channel: str | None = None, only_excluded: bool = False, has: str | None = None, lacks: str | None = None,
             match: str = "any", sort: str = "started_at", direction: str = "desc", limit: int = 50, offset: int = 0):
    """has / lacks = comma lists of: product, cart, checkout, pay, order, login, quiz, search. match=any|all applies to `has`."""
    w, a = _sessions_where(date_from, date_to, include_excluded, search, channel, only_excluded, min_stage, has, lacks, match)
    order = SESSION_SORTS.get(sort, SESSION_SORTS["started_at"])
    d = "ASC" if direction.lower() == "asc" else "DESC"
    total = one(f"{ORD_CTE} SELECT count(*) n {SESS_FROM} WHERE {w}", a)["n"]
    rows = q(f"""{ORD_CTE} SELECT s.session_id, s.started_at, s.duration_s, s.events, s.pageviews, s.channel, s.source, s.medium, s.campaign, s.landing_path,
        s.city, s.region, s.country, s.device, s.platform, s.is_app, s.user_id, u.name, {EMAIL} AS email, s.phone10, s.ip, s.visitor_key, s.key_events, s.stage,
        s.is_excluded, s.excl_reason, coalesce(o.n_orders, 0) AS order_count, o.order_value, o.other_value AS order_other_value, o.statuses AS order_statuses
        {SESS_FROM} WHERE {w} ORDER BY {order} {d} NULLS LAST, s.started_at DESC LIMIT ? OFFSET ?""", [*a, max(1, min(int(limit), 500)), max(0, offset)])
    return {"total": total, "rows": rows}


@app.get("/api/sessions/counts")
def session_counts(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False):
    """Sizes of the one-click presets on the Sessions tab."""
    w, a = sess_where(date_from, date_to, include_excluded)
    r = one(f"""{ORD_CTE} SELECT count(*) AS total,
        count(*) FILTER (WHERE s.f_cart AND NOT {FLAG_ORDER}) AS cart_abandoners, count(*) FILTER (WHERE s.f_checkout AND NOT {FLAG_ORDER}) AS checkout_abandoners,
        count(*) FILTER (WHERE {FLAG_LOGIN}) AS logged_in, count(*) FILTER (WHERE {FLAG_ORDER}) AS ordered
        {SESS_FROM} WHERE {w}""", a)
    return r


@app.get("/api/sessions/{session_id}")
def session_detail(session_id: str):
    """Everything about one session: attribution, device, the ordered event timeline, pages, orders, and the person it belongs to."""
    rows = q("SELECT * FROM sessions WHERE session_id = ?", [session_id])
    if not rows:
        raise HTTPException(404, "session not found")
    s = rows[0]
    events = q("""SELECT timezone('Asia/Kolkata', ts) AS at, event_name, event_key, page_type, path, product_name, brand, amount, search_term, city_n, ip
                  FROM events_clean WHERE session_id = ? ORDER BY ts, id LIMIT 3000""", [session_id])
    pages = q("""SELECT path, any_value(page_type) AS page_type, min(timezone('Asia/Kolkata', ts)) AS first_at, count(*) AS events,
                 count(*) FILTER (WHERE is_pageview) AS views FROM events_clean WHERE session_id = ? GROUP BY path ORDER BY first_at""", [session_id])
    types = q("""SELECT event_name, any_value(event_key) AS event_key, count(*) AS n FROM events_clean WHERE session_id = ?
                 GROUP BY event_name ORDER BY n DESC LIMIT 25""", [session_id])
    extra = one("""SELECT any_value(browser_n) AS browser,
                   first(utm_content ORDER BY ts) FILTER (WHERE utm_content IS NOT NULL) AS utm_content,
                   first(utm_term ORDER BY ts) FILTER (WHERE utm_term IS NOT NULL) AS utm_term,
                   first(referrer_host ORDER BY ts) FILTER (WHERE referrer_host IS NOT NULL) AS referrer
                   FROM events_clean WHERE session_id = ?""", [session_id])
    orders = q("""SELECT o.order_id, o.ts, o.total, o.status, o.payment_method, o.coupon_code, o.items_count, o.is_valid, o.is_test,
                  (SELECT string_agg(l.product_name, ' | ') FROM order_lines l WHERE l.order_id = o.order_id) AS items
                  FROM orders_clean o WHERE o.session_id = ? ORDER BY o.ts""", [session_id])
    pkey = s["user_id"] or s["visitor_key"]
    person = one("SELECT person_key, name, phone10, email, segment, sessions, is_registered FROM users_360 WHERE person_key = ?", [pkey])
    prev_s = one("SELECT session_id, started_at FROM sessions WHERE coalesce(user_id, visitor_key) = ? AND started_at < ? ORDER BY started_at DESC LIMIT 1", [pkey, s["started_at"]])
    next_s = one("SELECT session_id, started_at FROM sessions WHERE coalesce(user_id, visitor_key) = ? AND started_at > ? ORDER BY started_at ASC LIMIT 1", [pkey, s["started_at"]])
    return {"session": s, "events": events, "pages": pages, "event_types": types, "extra": extra, "orders": orders,
            "person": {**person, "person_key": pkey} if person else {"person_key": pkey}, "prev": prev_s or None, "next": next_s or None}


# ------------------------------------------------------------------ person profile (all sessions, browsers, times, orders of one person)
@app.get("/api/person")
def person_profile(key: str):
    """`key` is a person key: the account id for logged-in people, or the browser id for anonymous visitors."""
    sess = q("""WITH s0 AS (SELECT * FROM sessions WHERE coalesce(user_id, visitor_key) = ?),
                b AS (SELECT session_id, any_value(browser_n) AS browser FROM events_clean WHERE session_id IN (SELECT session_id FROM s0) GROUP BY 1)
                SELECT s0.session_id, s0.started_at, s0.ended_at, s0.duration_s, s0.events, s0.pageviews, s0.visitor_key, s0.device, s0.platform, s0.is_app,
                       s0.channel, s0.source, s0.medium, s0.campaign, s0.landing_path, s0.city, s0.region, s0.ip, s0.key_events, s0.stage,
                       s0.is_excluded, s0.excl_reason, b.browser
                FROM s0 LEFT JOIN b USING (session_id) ORDER BY s0.started_at DESC""", [key])
    profile = one("SELECT * FROM users_360 WHERE person_key = ?", [key])
    if not sess and not profile:
        raise HTTPException(404, "person not found")
    browsers = {}
    for r in sess:
        b = browsers.setdefault(r["visitor_key"], {"visitor_key": r["visitor_key"], "sessions": 0, "events": 0, "first_seen": r["started_at"], "last_seen": r["started_at"],
                                                   "device": r["device"], "platform": r["platform"], "browser": r["browser"], "is_app": r["is_app"]})
        b["sessions"] += 1
        b["events"] += r["events"]
        b["first_seen"] = min(b["first_seen"], r["started_at"])
        b["last_seen"] = max(b["last_seen"], r["started_at"])
    ips = q("""SELECT ip, count(*) AS events, count(DISTINCT session_id) AS sessions, min(ts) AS first_seen, max(ts) AS last_seen, any_value(city_n) AS city
               FROM events_clean WHERE ip IS NOT NULL AND session_id IN (SELECT session_id FROM sessions WHERE coalesce(user_id, visitor_key) = ?)
               GROUP BY 1 ORDER BY events DESC LIMIT 15""", [key])
    orders = q("""SELECT o.order_id, o.ts, o.total, o.status, o.payment_method, o.coupon_code, o.items_count, o.is_valid, o.is_test, o.is_excluded, o.session_id,
                  (SELECT string_agg(l.product_name, ' | ') FROM order_lines l WHERE l.order_id = o.order_id) AS items
                  FROM orders_clean o WHERE o.user_id = ? ORDER BY o.ts DESC""", [key])
    daily = q("SELECT date_ist AS d, count(*) AS sessions, sum(events) AS events FROM sessions WHERE coalesce(user_id, visitor_key) = ? GROUP BY 1 ORDER BY 1", [key])
    totals = {"sessions": len(sess), "events": sum(r["events"] for r in sess), "pageviews": sum(r["pageviews"] for r in sess),
              "seconds": sum(r["duration_s"] or 0 for r in sess), "browsers": len(browsers), "ips": len(ips),
              "devices": len({(r["device"], r["platform"], r["is_app"]) for r in sess})}
    return {"person_key": key, "profile": profile or None, "totals": totals, "sessions": sess, "browsers": sorted(browsers.values(), key=lambda b: b["last_seen"], reverse=True),
            "ips": ips, "orders": orders, "daily": daily}


USER_SORTS = {"last_seen": "last_seen", "first_seen": "first_seen", "name": "nullif(lower(name), '')", "city": "nullif(lower(city), '')", "sessions": "sessions", "orders": "orders",
              "revenue": "revenue", "cart_sessions": "cart_sessions", "segment": "segment", "first_channel": "first_channel", "email": "nullif(lower(email), '')"}
USER_PRESETS = {"cart_abandoners": "cart_sessions > 0 AND orders = 0", "checkout_abandoners": "checkout_sessions > 0 AND orders = 0",
                "logged_in": "is_registered", "buyers": "orders > 0", "reachable": "nullif(phone10, '') IS NOT NULL"}


def _users_where(d_from, d_to, include_excluded, search=None, segment=None, preset=None):
    w = "timezone('Asia/Kolkata', last_seen)::DATE >= ? AND timezone('Asia/Kolkata', first_seen)::DATE <= ?" + ("" if include_excluded else " AND NOT is_excluded")
    a = [d_from or "2000-01-01", d_to or "2999-12-31"]
    if segment:
        w += " AND segment = ?"
        a.append(segment)
    for k in _csv(preset):
        if k in USER_PRESETS:
            w += f" AND ({USER_PRESETS[k]})"
    if search:
        like = f"%{search.lower()}%"
        w += " AND (lower(coalesce(name,'')) LIKE ? OR coalesce(phone10,'') LIKE ? OR lower(coalesce(email,'')) LIKE ? OR lower(person_key) LIKE ? OR lower(coalesce(city,'')) LIKE ?)"
        a += [like] * 5
    return w, a


@app.get("/api/users")
def users(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, search: str | None = None,
          segment: str | None = None, preset: str | None = None, sort: str = "last_seen", direction: str = "desc", limit: int = 50, offset: int = 0):
    w, a = _users_where(date_from, date_to, include_excluded, search, segment, preset)
    order = USER_SORTS.get(sort, "last_seen")
    d = "ASC" if direction.lower() == "asc" else "DESC"
    total = one(f"SELECT count(*) n FROM users_360 WHERE {w}", a)["n"]
    rows = q(f"""SELECT person_key, user_id, name, phone10, email, is_registered, first_seen, last_seen, sessions, first_channel, first_campaign,
        city, state, device, uses_app, cart_sessions, checkout_sessions, orders, revenue, gender, skin_type, age_bucket, segment, is_excluded
        FROM users_360 WHERE {w} ORDER BY {order} {d} NULLS LAST, last_seen DESC LIMIT ? OFFSET ?""", [*a, max(1, min(int(limit), 500)), max(0, offset)])
    segs = q(f"SELECT segment, count(*) n FROM users_360 WHERE {'TRUE' if include_excluded else 'NOT is_excluded'} GROUP BY 1 ORDER BY 2 DESC")
    return {"total": total, "rows": rows, "segments": segs}


@app.get("/api/users/counts")
def user_counts(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False):
    """Sizes of the one-click presets on the Users tab (person level: someone who later ordered is not an abandoner)."""
    w, a = _users_where(date_from, date_to, include_excluded)
    cols = ", ".join(f"count(*) FILTER (WHERE {c}) AS {k}" for k, c in USER_PRESETS.items())
    return one(f"SELECT count(*) AS total, {cols} FROM users_360 WHERE {w}", a)


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
    """Exclusion edits only need the flagging steps (about 3 s instead of 15 s). Edits made mid-job are queued."""
    if JOB["running"]:
        PENDING["reapply"] = True
        return
    _run_job("apply-exclusions", lambda: transform.run(CON.cursor(), flags_only=True))


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
    if apply and ids:
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
    if apply:
        _reapply()
    return {"ok": True, "job": JOB}


@app.delete("/api/exclusions/{eid}")
def delete_exclusion(eid: int, apply: bool = True):
    with DB_LOCK:
        CON.execute("DELETE FROM exclusions WHERE id=?", [eid])
    if apply:
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
    # 10. basket size, returning customers, reachable quiz audience
    bk = basket(date_from, date_to, include_excluded, 499)["kpis"]
    if bk["single_item_orders"] >= 10 and bk["aov_single"] and bk["aov_multi"] > 1.2 * bk["aov_single"]:
        add("info", f"Orders with 2+ items are worth {(bk['aov_multi'] / bk['aov_single'] - 1) * 100:.0f}% more",
            f"{bk['single_item_orders']} of {bk['orders']} orders ({bk['single_item_orders'] / bk['orders'] * 100:.0f}%) have a single item: ₹{bk['aov_single']:,.0f} vs ₹{bk['aov_multi']:,.0f} for bigger baskets. Bundles and add-ons are the AOV lever.", "basket")
    lt = loyalty(include_excluded)["kpis"]
    if lt["customers"] >= 20:
        add("info", f"{lt['repeat_customers']} of {lt['customers']} customers ({lt['repeat_rate'] * 100:.0f}%) have come back on another day",
            f"They account for {lt['repeat_revenue_share'] * 100:.0f}% of revenue. Orders placed several times on the same day are not counted as repeat.", "loyalty")
    au = {a["id"]: a for a in audiences(include_excluded)["audiences"]}
    qa = au.get("quiz_no_buy")
    if qa and qa["reachable"] >= 20:
        add("warn", f"{qa['reachable']} people finished the quiz, left a phone number, and never bought",
            f"{qa['people']} quiz finishers in the last 60 days have no order; these {qa['reachable']} can be contacted. Quiz users convert far better than other visitors.", "audiences")
    # 11. online payments that never complete (a direct revenue leak)
    ex = "" if include_excluded else " AND NOT is_excluded"
    pay = one(f"""SELECT count(*) AS attempts, count(*) FILTER (WHERE is_valid) AS ok FROM orders_clean WHERE date_ist BETWEEN ? AND ? AND NOT is_test{ex}
                  AND payment_method IS NOT NULL AND payment_method NOT ILIKE 'COD%'""", [date_from or "2000-01-01", date_to or "2999-12-31"])
    if pay["attempts"] >= 10 and pay["ok"] / pay["attempts"] < 0.6:
        reason = one(f"""SELECT payment_failed_reason AS r, count(*) AS n FROM orders_clean WHERE date_ist BETWEEN ? AND ? AND NOT is_test{ex} AND NOT is_placed
                         AND payment_failed_reason IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 1""", [date_from or "2000-01-01", date_to or "2999-12-31"])
        lost = pay["attempts"] - pay["ok"]
        add("bad", f"Only {pay['ok'] / pay['attempts'] * 100:.0f}% of online payments complete",
            f"{lost} of {pay['attempts']} online orders were cancelled or abandoned at payment" + (f"; most common reason: “{reason['r']}”" if reason else "") + ". Cash on delivery orders almost always complete.",
            "orders", {"tab": "analytics"})
    # 12. Meta Ads: what the spend bought
    if one("SELECT count(*) AS n FROM raw_meta_insights")["n"]:
        mt = _meta_rows(date_from, date_to, include_excluded)
        tot = _meta_totals(mt)
        if tot["spend"] >= 500:
            wasted = [r for r in mt if r["verdict"] == "Wasting spend"]
            bl = _meta_blended(date_from, date_to, include_excluded, tot["spend"])
            roas = f"{bl['roas']:.2f}" if bl["roas"] is not None else "n/a"
            add("warn" if (bl["orders"] == 0 or (bl["roas"] or 0) < 1) else "good",
                f"Meta Ads spent ₹{tot['spend']:,.0f}, bringing {bl['orders']} tracked order{'s' if bl['orders'] != 1 else ''} (₹{bl['revenue']:,.0f})",
                f"Return on ad spend {roas}× across all Paid Meta traffic; {tot['carts']} carts from {tot['sessions']:,} sessions matched to campaigns."
                + (f" {len(wasted)} campaign{'s' if len(wasted) != 1 else ''} spent ₹{sum(r['spend'] for r in wasted):,.0f} with no add-to-carts." if wasted else ""), "meta")
    return {"kpis": k, "prev": prev, "prev_range": pr, "insights": out}



# ------------------------------------------------------------------ basket & AOV lab
def _order_filter(d_from, d_to, include_excluded, a="c", dated=True):
    w = [f"{a}.is_valid"]
    args = []
    if dated:
        w.append(f"{a}.date_ist BETWEEN ? AND ?")
        args += [d_from or "2000-01-01", d_to or "2999-12-31"]
    if not include_excluded:
        w.append(f"NOT {a}.is_excluded")
    return " AND ".join(w), args


@app.get("/api/basket")
def basket(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, threshold: int = 499):
    ow, oa = _order_filter(date_from, date_to, include_excluded, "c")
    lw, la = _order_filter(date_from, date_to, include_excluded, "l")
    k = one(f"""SELECT count(*) orders, coalesce(avg(total),0) aov, coalesce(median(total),0) median_aov, coalesce(avg(items_count),0) items_per_order,
        count(*) FILTER (WHERE items_count = 1) single_item_orders, coalesce(sum(revenue),0) revenue,
        coalesce(avg(total) FILTER (WHERE items_count = 1),0) aov_single, coalesce(avg(total) FILTER (WHERE items_count >= 2),0) aov_multi
        FROM orders_clean c WHERE {ow}""", oa)
    by_size = q(f"""SELECT CASE WHEN items_count >= 4 THEN '4+' ELSE items_count::VARCHAR END AS items, count(*) orders, avg(total) aov, sum(revenue) revenue
        FROM orders_clean c WHERE {ow} GROUP BY 1 ORDER BY 1""", oa)
    bands = q(f"""SELECT CASE WHEN products_total < 300 THEN '1. under 300' WHEN products_total < 500 THEN '2. 300-499' WHEN products_total < 800 THEN '3. 500-799'
        WHEN products_total < 1200 THEN '4. 800-1199' ELSE '5. 1200+' END AS band, count(*) orders, coalesce(sum(revenue),0) revenue
        FROM orders_clean c WHERE {ow} GROUP BY 1 ORDER BY 1""", oa)
    products = q(f"""SELECT product_name, any_value(brand) brand, any_value(product_type) product_type, sum(qty) units, count(DISTINCT order_id) orders, sum(line_total) revenue
        FROM order_lines l WHERE {lw} GROUP BY product_name ORDER BY revenue DESC LIMIT 12""", la)
    brands = q(f"""SELECT any_value(brand) brand, sum(qty) units, count(DISTINCT order_id) orders, sum(line_total) revenue
        FROM order_lines l WHERE {lw} GROUP BY lower(brand) ORDER BY revenue DESC LIMIT 10""", la)
    types = q(f"""SELECT product_type, any_value(category) category, sum(qty) units, count(DISTINCT order_id) orders, sum(line_total) revenue
        FROM order_lines l WHERE {lw} GROUP BY product_type ORDER BY revenue DESC LIMIT 12""", la)
    cover = one(f"SELECT coalesce(100.0 * sum(line_total) FILTER (WHERE brand <> 'Unknown') / nullif(sum(line_total),0), 0) brand_known_pct, coalesce(100.0 * sum(line_total) FILTER (WHERE NOT type_inferred) / nullif(sum(line_total),0), 0) catalog_type_pct FROM order_lines l WHERE {lw}", la)
    pairs = q(f"""WITH t AS (SELECT DISTINCT order_id, product_type FROM order_lines l WHERE {lw} AND product_type NOT IN ('Other','Unknown'))
        SELECT a.product_type AS a, b.product_type AS b, count(*) orders FROM t a JOIN t b ON a.order_id = b.order_id AND a.product_type < b.product_type
        GROUP BY 1,2 HAVING count(*) >= 2 ORDER BY 3 DESC, 1 LIMIT 10""", la)
    coupons = q(f"""SELECT coalesce(split_part(c.coupon_code, ',', 1), '(no coupon)') coupon, count(*) orders, avg(c.total) aov, avg(c.products_total) avg_basket,
        avg(try_cast(o.coupon_discount AS DOUBLE)) avg_discount FROM orders_clean c JOIN raw_orders o ON lower(o.id) = c.order_id
        WHERE {ow} GROUP BY 1 ORDER BY 2 DESC LIMIT 10""", oa)
    t = int(threshold)
    sim = one(f"""SELECT count(*) orders, count(*) FILTER (WHERE products_total >= ?) at_or_above,
        count(*) FILTER (WHERE products_total < ? AND products_total >= ? * 0.7) near,
        coalesce(sum(? - products_total) FILTER (WHERE products_total < ? AND products_total >= ? * 0.7), 0) gap_value
        FROM orders_clean c WHERE {ow}""", [t, t, t, t, t, t, *oa])
    cw = "s.date_ist BETWEEN ? AND ?" + ("" if include_excluded else " AND NOT s.is_excluded")
    ab = one(f"""SELECT count(*) FILTER (WHERE cart_value >= ?) at_or_above, count(*) FILTER (WHERE cart_value < ? AND cart_value >= ? * 0.7) near,
        count(*) FILTER (WHERE cart_value IS NULL) unknown FROM checkout ck JOIN sessions s USING (session_id)
        WHERE {cw} AND ck.outcome IN ('checkout_abandoned','payment_abandoned')""", [t, t, t, date_from or "2000-01-01", date_to or "2999-12-31"])
    return {"kpis": k, "by_size": by_size, "bands": bands, "products": products, "brands": brands, "types": types, "coverage": cover,
            "pairs": pairs, "coupons": coupons, "threshold": {"value": t, "orders": sim, "abandoned": ab}}


# ------------------------------------------------------------------ retention & lifetime value (all-time; date range does not apply)
@app.get("/api/loyalty")
def loyalty(include_excluded: bool = False):
    ow, _ = _order_filter(None, None, include_excluded, "c", dated=False)
    base = f"SELECT c.user_id, c.ts, c.revenue, c.order_id FROM orders_clean c WHERE {ow}"
    cust = f"SELECT user_id, count(*) n, count(DISTINCT timezone('Asia/Kolkata', ts)::DATE) AS ndays, sum(revenue) rev, min(ts) first_at, max(ts) last_at FROM ({base}) GROUP BY 1"
    k = one(f"""SELECT count(*) customers, count(*) FILTER (WHERE ndays >= 2) repeat_customers, count(*) FILTER (WHERE n >= 2 AND ndays = 1) same_day_multi,
        count(*) FILTER (WHERE n >= 2) multi_order_customers, coalesce(sum(rev),0) revenue,
        coalesce(sum(rev) FILTER (WHERE ndays >= 2),0) repeat_revenue, coalesce(avg(n),0) orders_per_customer, coalesce(avg(rev),0) ltv FROM ({cust})""")
    k["repeat_rate"] = ratio(k["repeat_customers"], k["customers"])
    k["repeat_revenue_share"] = ratio(k["repeat_revenue"], k["revenue"])
    dist = q(f"SELECT CASE WHEN n >= 4 THEN '4+' ELSE n::VARCHAR END AS orders, count(*) customers, sum(rev) revenue FROM ({cust}) GROUP BY 1 ORDER BY 1")
    gaps = q(f"""WITH g AS (SELECT date_diff('hour', lag(ts) OVER (PARTITION BY user_id ORDER BY ts), ts) / 24.0 AS d FROM ({base}))
        SELECT CASE WHEN d < 1 THEN '1. same day' WHEN d <= 7 THEN '2. within a week' WHEN d <= 30 THEN '3. 8-30 days' WHEN d <= 60 THEN '4. 31-60 days' ELSE '5. 60+ days' END AS gap,
        count(*) orders FROM g WHERE d IS NOT NULL GROUP BY 1 ORDER BY 1""")
    median_gap = one(f"SELECT median(d) AS d FROM (SELECT date_diff('hour', lag(ts) OVER (PARTITION BY user_id ORDER BY ts), ts) / 24.0 AS d FROM ({base})) WHERE d IS NOT NULL").get("d")
    by_channel = q(f"""SELECT coalesce(u.first_channel, 'Unknown') channel, count(*) customers, sum(c.n) orders, sum(c.rev) revenue, avg(c.rev) ltv,
        count(*) FILTER (WHERE c.ndays >= 2) repeaters FROM ({cust}) c LEFT JOIN users_360 u ON u.user_id = c.user_id GROUP BY 1 ORDER BY revenue DESC""")
    cohorts = q(f"""WITH o AS (SELECT user_id, ts, revenue, date_trunc('month', timezone('Asia/Kolkata', min(ts) OVER (PARTITION BY user_id)))::DATE AS cohort,
                        date_diff('month', date_trunc('month', timezone('Asia/Kolkata', min(ts) OVER (PARTITION BY user_id))), date_trunc('month', timezone('Asia/Kolkata', ts))) AS m FROM ({base}))
        SELECT cohort, count(DISTINCT user_id) customers, m, sum(revenue) revenue FROM o GROUP BY 1,3 ORDER BY 1,3""")
    coh = {}
    for r in cohorts:
        c = coh.setdefault(str(r["cohort"]), {"cohort": r["cohort"], "customers": r["customers"], "months": {}})
        c["customers"] = max(c["customers"], r["customers"])
        c["months"][r["m"]] = r["revenue"]
    for c in coh.values():
        run, out = 0.0, {}
        for m in sorted(c["months"]):
            run += c["months"][m]
            out[m] = round(run / c["customers"], 1)
        c["months"] = out
    as_of = one("SELECT max(date_ist) AS d FROM sessions")["d"]
    recency = q(f"""SELECT CASE WHEN dd <= 30 THEN '1. bought in last 30 days' WHEN dd <= 60 THEN '2. 31-60 days ago' WHEN dd <= 90 THEN '3. 61-90 days ago' ELSE '4. over 90 days ago' END AS bucket,
        count(*) customers, count(*) FILTER (WHERE ndays >= 2) repeaters, sum(rev) revenue
        FROM (SELECT n, ndays, rev, date_diff('day', timezone('Asia/Kolkata', last_at)::DATE, ?::DATE) dd FROM ({cust})) GROUP BY 1 ORDER BY 1""", [str(as_of)])
    lw, _ = _order_filter(None, None, include_excluded, "l", dated=False)
    reordered = q(f"""SELECT product_name, any_value(brand) brand, count(*) repeat_customers, sum(orders) orders FROM (
        SELECT user_id, product_name, any_value(brand) AS brand, count(DISTINCT order_id) orders FROM order_lines l WHERE {lw} GROUP BY 1,2 HAVING count(DISTINCT order_id) >= 2) GROUP BY product_name ORDER BY 3 DESC, 4 DESC LIMIT 8""")
    return {"as_of": as_of, "kpis": k, "dist": dist, "gaps": gaps, "median_gap_days": median_gap, "by_channel": by_channel,
            "cohorts": list(coh.values()), "recency": recency, "reordered": reordered}


# ------------------------------------------------------------------ audiences (who can we reach, and with what)
AUDIENCES = [
    ("abandoned_checkout", "Left checkout, never ordered", "Opened checkout in the last 30 days but did not buy.",
     "Send a reminder with the exact cart; offer help with payment or delivery questions.", "p.segment = 'Abandoned checkout' AND p.days_seen <= 30"),
    ("cart_no_checkout", "Added to cart, never reached checkout", "Added something to the cart in the last 30 days but never opened checkout.",
     "Remind them what is in the cart; highlight free delivery or a first-order offer.", "p.segment = 'Cart, no checkout' AND p.days_seen <= 30"),
    ("quiz_no_buy", "Finished the skin quiz, never bought", "Completed the quiz in the last 60 days with no order.",
     "Send their routine from the quiz as a bundle; this group is warmer than average.", "p.quiz_sessions > 0 AND p.orders = 0 AND p.days_seen <= 60"),
    ("signed_up_no_order", "Signed up, never ordered", "Registered at least a day ago and has never placed an order.",
     "Welcome offer or a simple 'start with this' pick for their skin type.", "p.is_registered AND p.orders = 0 AND p.days_since_signup >= 1"),
    ("recent_buyers", "Bought in the last 14 days", "Fresh customers: best moment for a referral ask or a complementary product.",
     "Ask for a referral; cross-sell a product that goes with what they bought.", "p.orders >= 1 AND p.days_order <= 14"),
    ("second_order_due", "First-timers due a second order", "Exactly one order, placed 25-75 days ago.",
     "Reorder reminder for what they bought, plus a routine add-on.", "p.orders = 1 AND p.days_order BETWEEN 25 AND 75"),
    ("lapsed_repeat", "Repeat buyers gone quiet", "Two or more orders, but nothing in the last 45 days.",
     "Win-back with a personal note; they are your most valuable customers.", "p.orders >= 2 AND p.days_order > 45"),
    ("top_spenders", "Top spenders", "Customers in the top quarter by lifetime spend.",
     "VIP treatment: early access, free gift, referral reward.", "p.orders >= 1 AND p.revenue >= (SELECT quantile_cont(revenue, 0.75) FROM users_360 WHERE orders >= 1 AND NOT is_excluded)"),
]


def _audience_base(include_excluded: bool) -> str:
    return f"""
    WITH as_of AS (SELECT max(date_ist) AS d FROM sessions),
    ab AS (SELECT coalesce(s.user_id, s.visitor_key) AS person_key, max(c.checkout_at) AS last_checkout_at, arg_max(c.cart_value, c.checkout_at) AS last_cart_value
           FROM checkout c JOIN sessions s USING (session_id) WHERE c.outcome IN ('checkout_abandoned','payment_abandoned') GROUP BY 1)
    SELECT u.person_key, u.user_id, u.name, nullif(u.phone10, '') AS phone10, u.email, u.is_registered, u.segment, u.city, u.state, u.first_channel,
           u.orders, u.revenue, u.quiz_sessions, u.cart_sessions, u.skin_type, u.age_bucket, u.first_seen, u.last_seen, u.last_order_at, u.signed_up_at,
           ab.last_checkout_at, ab.last_cart_value,
           date_diff('day', timezone('Asia/Kolkata', u.last_seen)::DATE, (SELECT d FROM as_of)) AS days_seen,
           date_diff('day', timezone('Asia/Kolkata', u.last_order_at)::DATE, (SELECT d FROM as_of)) AS days_order,
           date_diff('day', timezone('Asia/Kolkata', u.signed_up_at)::DATE, (SELECT d FROM as_of)) AS days_since_signup
    FROM users_360 u LEFT JOIN ab ON ab.person_key = u.person_key
    WHERE u.role IS NULL OR u.role NOT IN ('admin','rider','doctor')""" + ("" if include_excluded else " AND NOT u.is_excluded")


@app.get("/api/audiences")
def audiences(include_excluded: bool = False):
    base = _audience_base(include_excluded)
    out = []
    for aid, title, desc, action, cond in AUDIENCES:
        r = one(f"SELECT count(*) people, count(p.phone10) reachable, coalesce(sum(p.last_cart_value),0) cart_value, coalesce(sum(p.revenue),0) revenue FROM ({base}) p WHERE {cond}")
        out.append({"id": aid, "title": title, "description": desc, "action": action, **r})
    totals = one(f"SELECT count(*) people, count(p.phone10) reachable, count(*) FILTER (WHERE p.is_registered) registered FROM ({base}) p")
    return {"audiences": out, "totals": totals, "as_of": one("SELECT max(date_ist) AS d FROM sessions")["d"]}


@app.get("/api/audiences/{aid}/people")
def audience_people(aid: str, include_excluded: bool = False, only_reachable: bool = False, sort: str = "reach", direction: str = "desc", limit: int = 50, offset: int = 0):
    spec = next((a for a in AUDIENCES if a[0] == aid), None)
    if not spec:
        raise HTTPException(404, "unknown audience")
    base = _audience_base(include_excluded)
    cond = spec[4] + (" AND p.phone10 IS NOT NULL" if only_reachable else "")
    sorts = {"last_seen": "p.last_seen", "name": "lower(p.name)", "city": "lower(p.city)", "orders": "p.orders", "revenue": "p.revenue",
             "last_cart_value": "p.last_cart_value", "first_channel": "p.first_channel", "days_seen": "p.days_seen"}
    dd = "ASC" if direction.lower() == "asc" else "DESC"
    order = f"{sorts[sort]} {dd}" if sort in sorts else "(p.phone10 IS NULL)"
    total = one(f"SELECT count(*) n FROM ({base}) p WHERE {cond}")["n"]
    rows = q(f"""SELECT p.person_key, p.name, p.phone10, p.email, p.city, p.state, p.segment, p.first_channel, p.orders, p.revenue, p.skin_type, p.age_bucket,
        p.last_seen, p.last_order_at, p.last_checkout_at, p.last_cart_value, p.days_seen, p.days_order
        FROM ({base}) p WHERE {cond} ORDER BY {order} NULLS LAST, p.last_seen DESC LIMIT ? OFFSET ?""", [limit, offset])
    return {"id": aid, "title": spec[1], "description": spec[2], "action": spec[3], "total": total, "rows": rows}



# ------------------------------------------------------------------ time series (sparklines + current vs previous period)
def _series(lo: str, hi: str, include_excluded: bool) -> dict:
    """Daily metrics for [lo, hi] on a gap-free date spine (days without data are zeros, so periods align by position)."""
    w, a = sess_where(lo, hi, include_excluded)
    ow = "date_ist BETWEEN ? AND ? AND is_valid" + ("" if include_excluded else " AND NOT is_excluded")
    srows = {str(r["d"]): r for r in q(f"""SELECT date_ist AS d, count(*) sessions, count(DISTINCT coalesce(user_id, visitor_key)) people,
        count(*) FILTER (WHERE f_cart) carts, count(*) FILTER (WHERE f_checkout) checkouts, count(*) FILTER (WHERE is_bounce) bounced
        FROM sessions s WHERE {w} GROUP BY 1""", a)}
    orows = {str(r["d"]): r for r in q(f"SELECT date_ist AS d, count(*) orders, coalesce(sum(revenue),0) revenue FROM orders_clean WHERE {ow} GROUP BY 1", a)}
    d0, d1 = date.fromisoformat(lo), date.fromisoformat(hi)
    dates, m = [], {k: [] for k in ("sessions", "people", "carts", "checkouts", "orders", "revenue", "cart_rate", "aov", "bounce_rate")}
    d = d0
    while d <= d1:
        k = d.isoformat()
        sr, orr = srows.get(k, {}), orows.get(k, {})
        ses, car, orders, rev = sr.get("sessions", 0), sr.get("carts", 0), orr.get("orders", 0), float(orr.get("revenue", 0) or 0)
        dates.append(k)
        m["sessions"].append(ses)
        m["people"].append(sr.get("people", 0))
        m["carts"].append(car)
        m["checkouts"].append(sr.get("checkouts", 0))
        m["orders"].append(orders)
        m["revenue"].append(round(rev, 2))
        m["cart_rate"].append(round(car / ses, 4) if ses else 0)
        m["aov"].append(round(rev / orders, 2) if orders else 0)
        m["bounce_rate"].append(round(sr.get("bounced", 0) / ses, 4) if ses else 0)
        d += timedelta(days=1)
    return {"dates": dates, "m": m}


@app.get("/api/timeseries")
def timeseries(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False):
    lo = date_from or str(one("SELECT min(date_ist) AS d FROM sessions")["d"])
    hi = date_to or str(one("SELECT max(date_ist) AS d FROM sessions")["d"])
    cur = _series(lo, hi, include_excluded)
    pr = prev_range(date_from, date_to)
    prev = _series(pr[0], pr[1], include_excluded) if pr else None
    return {"dates": cur["dates"], "current": cur["m"], "prev_dates": prev["dates"] if prev else None, "previous": prev["m"] if prev else None}


# ------------------------------------------------------------------ generic report table (sort / search / totals)
REPORT_DIMS = {
    "channel": "s.channel",
    "source_medium": "s.source || ' / ' || s.medium",
    "campaign": "s.campaign",
    "device": "coalesce(CASE WHEN s.is_app THEN 'Android app' ELSE s.device END, 'Unknown')",
    "landing": "s.landing_type",
    "state": "coalesce(s.region, 'Unknown')",
    "city": "coalesce(s.city, 'Unknown')",
    "country": "coalesce(s.country, 'Unknown')",
}
REPORT_SORTS = {"dim": "dim", "sessions": "sessions", "people": "people", "carts": "carts", "checkouts": "checkouts", "orders": "orders",
                "revenue": "revenue", "avg_duration": "avg_duration", "cart_rate": "carts::DOUBLE / sessions", "bounce_rate": "bounced::DOUBLE / sessions"}
REPORT_METRICS = """count(*) AS sessions, count(DISTINCT coalesce(s.user_id, s.visitor_key)) AS people, count(*) FILTER (WHERE s.f_cart) AS carts,
    count(*) FILTER (WHERE s.f_checkout) AS checkouts, count(*) FILTER (WHERE s.is_bounce) AS bounced,
    coalesce(avg(s.duration_s) FILTER (WHERE s.duration_s > 0), 0) AS avg_duration, coalesce(sum(o.orders), 0) AS orders, coalesce(sum(o.revenue), 0) AS revenue"""


def _derive(r: dict) -> dict:
    r["cart_rate"] = ratio(r["carts"], r["sessions"])
    r["bounce_rate"] = ratio(r["bounced"], r["sessions"])
    return r


@app.get("/api/report")
def report(dimension: str = "channel", date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False,
           sort: str = "sessions", direction: str = "desc", search: str | None = None, limit: int = 10, offset: int = 0, min_sessions: int = 1):
    """One row per value of the chosen dimension, with a totals row. Orders are credited to the session they were placed in."""
    if dimension not in REPORT_DIMS:
        raise HTTPException(400, f"dimension must be one of {list(REPORT_DIMS)}")
    order_by = REPORT_SORTS.get(sort, "sessions")
    direction = "ASC" if direction.lower() == "asc" else "DESC"
    expr = REPORT_DIMS[dimension]
    w, a = sess_where(date_from, date_to, include_excluded)
    ords = f"(SELECT session_id, count(*) AS orders, sum(revenue) AS revenue FROM orders_clean WHERE is_valid {'' if include_excluded else 'AND NOT is_excluded'} GROUP BY 1)"
    base = f"FROM sessions s LEFT JOIN {ords} o ON o.session_id = s.session_id WHERE {w}"
    sq, sa = "", []
    if search:
        sq, sa = f" AND ({expr}) ILIKE ?", [f"%{search}%"]
    limit = max(1, min(int(limit), 200))
    ms = max(1, int(min_sessions))
    rows = q(f"SELECT {expr} AS dim, {REPORT_METRICS} {base}{sq} GROUP BY 1 HAVING count(*) >= ? ORDER BY {order_by} {direction} NULLS LAST, dim LIMIT ? OFFSET ?", [*a, *sa, ms, limit, max(0, offset)])
    groups = one(f"SELECT count(*) AS n FROM (SELECT {expr} AS g {base}{sq} GROUP BY 1 HAVING count(*) >= ?)", [*a, *sa, ms])["n"]
    totals = one(f"SELECT {REPORT_METRICS} {base}{sq}", [*a, *sa])
    return {"dimension": dimension, "rows": [_derive(r) for r in rows], "totals": _derive(totals) if totals else None, "groups": groups}



# ------------------------------------------------------------------ exclusions: bulk add, share (export / import), inventory
class BulkItem(BaseModel):
    kind: str
    value: str
    note: str | None = None
    active: bool = True


class BulkIn(BaseModel):
    items: list[BulkItem]
    apply: bool = True


class ImportIn(BaseModel):
    exclusions: list[BulkItem]
    dry_run: bool = True


def _classify(items: list[BulkItem]) -> tuple[list[BulkItem], int, list[dict]]:
    """Split into (new, duplicate count, invalid rows) against what is already in the list."""
    with DB_LOCK:
        have = {(k, str(v).lower()) for k, v in CON.execute("SELECT kind, value FROM exclusions").fetchall()}
    new, dup, invalid, seen = [], 0, [], set()
    for it in items:
        kind, value = it.kind.strip(), it.value.strip()
        if kind not in EXCLUSION_KINDS:
            invalid.append({"kind": it.kind, "value": it.value, "why": "unknown type"})
        elif not value or len(value) > 300:
            invalid.append({"kind": kind, "value": value[:40], "why": "empty or too long"})
        elif (kind, value.lower()) in have or (kind, value.lower()) in seen:
            dup += 1
        else:
            seen.add((kind, value.lower()))
            new.append(BulkItem(kind=kind, value=value, note=it.note, active=it.active))
    return new, dup, invalid


def _insert_exclusions(items: list[BulkItem], note_suffix: str = "") -> int:
    with DB_LOCK:
        for it in items:
            CON.execute("INSERT INTO exclusions (kind, value, note, active, source) VALUES (?,?,?,?, 'manual')",
                        [it.kind, it.value, ((it.note or "") + note_suffix).strip() or None, it.active]).fetchall()
    return len(items)


@app.post("/api/exclusions/bulk")
def bulk_exclusions(body: BulkIn):
    """Add many exclusions at once (one rebuild, not one per row)."""
    if len(body.items) > 5000:
        raise HTTPException(400, "too many items (max 5000)")
    new, dup, invalid = _classify(body.items)
    added = _insert_exclusions(new)
    if body.apply and added:
        _reapply()
    return {"added": added, "skipped": dup, "invalid": invalid[:20], "job": JOB}


@app.get("/api/exclusions/export")
def export_exclusions(format: str = "json", include_builtin: bool = False):
    """Download the exclusion list as a file that another dashboard can import."""
    rows = q("SELECT kind, value, note, active, source FROM exclusions ORDER BY kind, lower(value)")
    if not include_builtin:
        rows = [r for r in rows if r["source"] != "default"]
    stamp = date.today().isoformat()
    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["kind", "value", "note", "active"])
        for r in rows:
            w.writerow([r["kind"], r["value"], r["note"] or "", "true" if r["active"] else "false"])
        return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="roopsee-exclusions-{stamp}.csv"'})
    payload = {"format": "roopsee-exclusions", "version": 1, "exported_at": datetime.now().isoformat(timespec="seconds"), "count": len(rows),
               "exclusions": [{"kind": r["kind"], "value": r["value"], "note": r["note"], "active": bool(r["active"])} for r in rows]}
    return Response(json.dumps(payload, indent=2, ensure_ascii=False), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="roopsee-exclusions-{stamp}.json"'})


@app.post("/api/exclusions/import")
def import_exclusions(body: ImportIn):
    """dry_run=true previews (new / already present / invalid); dry_run=false merges the new ones and rebuilds once."""
    if len(body.exclusions) > 5000:
        raise HTTPException(400, "too many items (max 5000)")
    new, dup, invalid = _classify(body.exclusions)
    if not body.dry_run and new:
        _insert_exclusions(new, " [imported]")
        _reapply()
    return {"applied": not body.dry_run, "new": len(new), "duplicates": dup, "invalid": invalid[:20], "invalid_count": len(invalid),
            "preview": [{"kind": n.kind, "value": n.value, "note": n.note} for n in new[:50]]}


@app.get("/api/exclusions/inventory")
def exclusion_inventory():
    """Every identifier we have reason to think is internal / automated, with how much of it is still counted in the numbers."""
    items: dict = {}

    def add(kind, value, label, reason, total=0, counted=0, last=None, shared=None):
        if value is None or str(value).strip() == "":
            return
        k = (kind, str(value).lower())
        it = items.setdefault(k, {"kind": kind, "value": str(value), "label": label, "reasons": [], "sessions": 0, "counted": 0, "last_seen": None, "shared": None})
        if reason not in it["reasons"]:
            it["reasons"].append(reason)
        it["label"] = it["label"] or label
        it["sessions"] = max(it["sessions"], total or 0)
        it["counted"] = max(it["counted"], counted or 0)
        if last and (not it["last_seen"] or last > it["last_seen"]):
            it["last_seen"] = last
        if shared is not None:
            it["shared"] = shared

    # 1. staff accounts (admin / rider / doctor) and their contact details
    ustat = {r["user_id"]: r for r in q("SELECT user_id, count(*) n, count(*) FILTER (WHERE NOT is_excluded) c, max(started_at) last FROM sessions WHERE user_id IS NOT NULL GROUP BY 1")}
    for r in q("""SELECT lower(id) uid, name, role, nullif(lower(email), '') email,
                  nullif(right(regexp_replace(coalesce(phone_no, ''), '[^0-9]', '', 'g'), 10), '') phone FROM raw_users WHERE role IN ('admin','rider','doctor')"""):
        st = ustat.get(r["uid"], {})
        why = f"staff account ({r['role']})"
        n, c, last = st.get("n", 0), st.get("c", 0), st.get("last")
        add("user_id", r["uid"], r["name"], why, n, c, last)
        add("email", r["email"], r["name"], why + " email", n, c, last)
        add("phone", r["phone"], r["name"], why + " phone", n, c, last)
        if r["name"] and len(r["name"].strip()) > 2:
            add("name", r["name"].strip(), r["name"], why + " name", n, c, last)

    # 2. company-domain emails (from the active @domain exclusions)
    doms = [r["value"].lower() for r in q("SELECT value FROM exclusions WHERE active AND kind = 'email' AND value LIKE '@%'")]
    for d in doms:
        for r in q("SELECT lower(id) uid, name, lower(email) email FROM raw_users WHERE lower(email) LIKE ?", [f"%{d}"]):
            st = ustat.get(r["uid"], {})
            add("email", r["email"], r["name"], f"company email ({d})", st.get("n", 0), st.get("c", 0), st.get("last"))

    # 3. anything seen inside /admin: browsers, IPs, phones
    for r in q("""WITH adm AS (SELECT visitor_key, count(DISTINCT session_id) internal FROM events_clean WHERE page_type = 'admin' GROUP BY 1)
                  SELECT a.visitor_key, a.internal, count(s.session_id) n, count(s.session_id) FILTER (WHERE NOT s.is_excluded) c, max(s.started_at) last
                  FROM adm a LEFT JOIN sessions s ON s.visitor_key = a.visitor_key GROUP BY a.visitor_key, a.internal"""):
        add("visitor_id", r["visitor_key"], None, f"opened /admin ({r['internal']} sessions)", r["n"], r["c"], r["last"])
    for r in q("""WITH adm AS (SELECT ip, count(DISTINCT session_id) internal FROM events_clean WHERE page_type = 'admin' AND ip IS NOT NULL GROUP BY 1)
                  SELECT a.ip, a.internal, count(s.session_id) n, count(s.session_id) FILTER (WHERE NOT s.is_excluded) c, count(DISTINCT s.visitor_key) browsers, max(s.started_at) last
                  FROM adm a LEFT JOIN sessions s ON s.ip = a.ip GROUP BY a.ip, a.internal"""):
        add("ip", r["ip"], None, f"used inside /admin ({r['internal']} sessions)", r["n"], r["c"], r["last"], r["browsers"])
    for r in q("""WITH adm AS (SELECT phone10, count(DISTINCT session_id) internal FROM events_clean WHERE page_type = 'admin' AND phone10 IS NOT NULL GROUP BY 1)
                  SELECT a.phone10, a.internal, count(s.session_id) n, count(s.session_id) FILTER (WHERE NOT s.is_excluded) c, max(s.started_at) last
                  FROM adm a LEFT JOIN sessions s ON s.phone10 = a.phone10 GROUP BY a.phone10, a.internal"""):
        add("phone", r["phone10"], None, f"used inside /admin ({r['internal']} sessions)", r["n"], r["c"], r["last"])

    # 4. bot-like anonymous browsers: many very short sessions
    for r in q("""SELECT visitor_key, count(*) n, count(*) FILTER (WHERE NOT is_excluded) c, avg(duration_s) avg_s, max(started_at) last, mode(ip) top_ip
                  FROM sessions WHERE user_id IS NULL GROUP BY 1 HAVING count(*) >= 30 AND avg(duration_s) < 5"""):
        why = f"bot-like: {r['n']} sessions averaging {r['avg_s']:.1f}s"
        add("visitor_id", r["visitor_key"], None, why, r["n"], r["c"], r["last"])
        if r["top_ip"]:
            ipst = one("SELECT count(*) n, count(*) FILTER (WHERE NOT is_excluded) c, count(DISTINCT visitor_key) b FROM sessions WHERE ip = ?", [r["top_ip"]])
            add("ip", r["top_ip"], None, why, ipst["n"], ipst["c"], r["last"], ipst["b"])

    listed = {(r["kind"], str(r["value"]).lower()) for r in q("SELECT kind, value FROM exclusions WHERE active")}
    rows = []
    for it in items.values():
        it["reason"] = " · ".join(it["reasons"])
        it["in_list"] = (it["kind"], it["value"].lower()) in listed
        it["risky"] = it["kind"] == "ip" and (it["shared"] or 0) >= 4  # shared IP (carrier / office): may belong to many customers
        rows.append(it)
    rows.sort(key=lambda r: (-r["counted"], -r["sessions"], r["kind"]))
    by_kind: dict = {}
    for r in rows:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    return {"rows": rows, "summary": {"total": len(rows), "in_list": sum(r["in_list"] for r in rows), "still_counted": sum(1 for r in rows if r["counted"] > 0 and not r["in_list"]), "by_kind": by_kind}}



# ------------------------------------------------------------------ orders: list, analytics, detail
ORDER_SORTS = {"ts": "o.ts", "total": "o.total", "products_total": "o.products_total", "status": "o.status", "payment_method": "o.payment_method",
               "city": "nullif(lower(o.city), '')", "customer_name": "nullif(lower(o.customer_name), '')", "coupon_code": "o.coupon_code",
               "items_count": "o.items_count", "nth_order": "o.nth_order", "delivery_fee": "o.delivery_fee"}
ORDER_SCOPES = {"sales": "o.is_valid", "all": "NOT o.is_test", "unpaid": "(NOT o.is_placed AND NOT o.is_test)", "internal": "o.is_excluded"}
ORDER_ITEMS = "(SELECT string_agg(l.product_name || CASE WHEN l.qty > 1 THEN ' x' || l.qty ELSE '' END, ' | ') FROM order_lines l WHERE l.order_id = o.order_id)"


def _in(col: str, values: list[str]) -> tuple[str, list]:
    return f"{col} IN ({', '.join('?' for _ in values)})", list(values)


def _orders_where(d_from, d_to, include_excluded, scope="sales", status=None, payment=None, coupon=None, search=None):
    w = ["o.date_ist BETWEEN ? AND ?", ORDER_SCOPES.get(scope, ORDER_SCOPES["sales"])]
    a = [d_from or "2000-01-01", d_to or "2999-12-31"]
    if scope != "internal" and not include_excluded:
        w.append("NOT o.is_excluded")
    if _csv(status):
        c, v = _in("o.status", _csv(status))
        w.append(c)
        a += v
    if _csv(payment):
        c, v = _in("coalesce(o.payment_method, '(not recorded)')", _csv(payment))
        w.append(c)
        a += v
    if coupon:
        w.append("coalesce(split_part(o.coupon_code, ',', 1), '(no coupon)') = ?")
        a.append(coupon)
    if search:
        like = f"%{search.lower()}%"
        w.append("""(lower(o.order_id) LIKE ? OR coalesce(o.phone10, '') LIKE ? OR lower(coalesce(o.customer_name, '')) LIKE ? OR lower(coalesce(o.email_l, '')) LIKE ?
                    OR lower(coalesce(o.city, '')) LIKE ? OR coalesce(o.pincode, '') LIKE ? OR lower(coalesce(o.coupon_code, '')) LIKE ?)""")
        a += [like] * 7
    return " AND ".join(w), a


@app.get("/api/orders")
def orders_list(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, scope: str = "sales", status: str | None = None,
                payment: str | None = None, coupon: str | None = None, search: str | None = None, sort: str = "ts", direction: str = "desc", limit: int = 50, offset: int = 0):
    """scope: sales (valid orders) | all (every real order incl. unpaid) | unpaid (cancelled / payment pending) | internal (test, staff, manually excluded)."""
    w, a = _orders_where(date_from, date_to, include_excluded, scope, status, payment, coupon, search)
    order = ORDER_SORTS.get(sort, "o.ts")
    d = "ASC" if direction.lower() == "asc" else "DESC"
    summ = one(f"SELECT count(*) AS orders, coalesce(sum(o.total), 0) AS gmv, coalesce(avg(o.total), 0) AS aov FROM orders_clean o WHERE {w}", a)
    rows = q(f"""SELECT o.order_id, o.ts, o.customer_name, o.phone10, o.email_l AS email, o.city, o.state, o.pincode, o.items_count, {ORDER_ITEMS} AS items,
        o.total, o.products_total, o.coupon_code, o.coupon_discount, o.delivery_fee, o.wallet_amount_used, o.payment_method, o.payment_status, o.status,
        o.payment_failed_reason, o.nth_order, o.session_id, o.channel, o.campaign, o.device, o.rider_name, o.delivered_at, o.user_id,
        o.is_valid, o.is_test, o.is_staff_order, o.is_excluded
        FROM orders_clean o WHERE {w} ORDER BY {order} {d} NULLS LAST, o.ts DESC LIMIT ? OFFSET ?""", [*a, max(1, min(int(limit), 500)), max(0, offset)])
    opts = {"statuses": [r["status"] for r in q("SELECT status, count(*) n FROM orders_clean WHERE NOT is_test GROUP BY 1 ORDER BY 2 DESC")],
            "payment_methods": [r["m"] for r in q("SELECT coalesce(payment_method, '(not recorded)') AS m, count(*) n FROM orders_clean WHERE NOT is_test GROUP BY 1 ORDER BY 2 DESC")],
            "coupons": [r["c"] for r in q("SELECT coalesce(split_part(coupon_code, ',', 1), '(no coupon)') AS c, count(*) n FROM orders_clean WHERE NOT is_test GROUP BY 1 ORDER BY 2 DESC LIMIT 30")]}
    return {"total": summ["orders"], "summary": summ, "rows": rows, "options": opts}


def _order_kpis(d_from, d_to, include_excluded) -> dict:
    ex = "" if include_excluded else " AND NOT o.is_excluded"
    k = one(f"""SELECT count(*) AS attempts, count(*) FILTER (WHERE o.is_valid) AS orders, coalesce(sum(o.total) FILTER (WHERE o.is_valid), 0) AS gmv,
        count(*) FILTER (WHERE o.status = 'payment_cancelled') AS cancelled, count(*) FILTER (WHERE o.status = 'payment_pending') AS pending,
        count(*) FILTER (WHERE o.is_valid AND o.payment_method ILIKE 'COD%') AS cod_orders,
        count(*) FILTER (WHERE o.is_valid AND coalesce(o.payment_method, '') NOT ILIKE 'COD%') AS online_orders,
        coalesce(sum(o.coupon_discount) FILTER (WHERE o.is_valid), 0) AS coupon_discount, coalesce(sum(o.products_total) FILTER (WHERE o.is_valid), 0) AS products_total,
        coalesce(sum(o.delivery_fee) FILTER (WHERE o.is_valid), 0) AS delivery_fees, coalesce(sum(o.wallet_amount_used) FILTER (WHERE o.is_valid), 0) AS wallet_used,
        count(*) FILTER (WHERE o.is_valid AND o.nth_order = 1) AS first_orders, count(*) FILTER (WHERE o.is_valid AND o.nth_order > 1) AS repeat_orders,
        count(*) FILTER (WHERE o.is_valid AND o.delivered_at IS NOT NULL) AS delivered,
        median(date_diff('minute', o.ts, o.delivered_at)) FILTER (WHERE o.is_valid AND o.delivered_at IS NOT NULL) / 60.0 AS median_delivery_h
        FROM orders_clean o WHERE o.date_ist BETWEEN ? AND ? AND NOT o.is_test{ex}""", [d_from or "2000-01-01", d_to or "2999-12-31"])
    k["aov"] = ratio(k["gmv"], k["orders"]) if False else (round(k["gmv"] / k["orders"], 2) if k["orders"] else 0)
    k["cancel_rate"] = ratio(k["cancelled"], k["attempts"])
    k["cod_share"] = ratio(k["cod_orders"], k["orders"])
    k["repeat_share"] = ratio(k["repeat_orders"], k["orders"])
    k["discount_pct"] = ratio(k["coupon_discount"], k["products_total"])
    return k


def _order_series(lo: str, hi: str, include_excluded: bool) -> dict:
    ex = "" if include_excluded else " AND NOT o.is_excluded"
    rows = {str(r["d"]): r for r in q(f"""SELECT o.date_ist AS d, count(*) AS attempts, count(*) FILTER (WHERE o.is_valid) AS orders,
        coalesce(sum(o.total) FILTER (WHERE o.is_valid), 0) AS gmv, count(*) FILTER (WHERE o.status = 'payment_cancelled') AS cancelled
        FROM orders_clean o WHERE o.date_ist BETWEEN ? AND ? AND NOT o.is_test{ex} GROUP BY 1""", [lo, hi])}
    dates, m = [], {k: [] for k in ("orders", "gmv", "aov", "cancelled", "attempts")}
    d, end = date.fromisoformat(lo), date.fromisoformat(hi)
    while d <= end:
        k = d.isoformat()
        r = rows.get(k, {})
        o, g = r.get("orders", 0), float(r.get("gmv", 0) or 0)
        dates.append(k)
        m["orders"].append(o)
        m["gmv"].append(round(g, 2))
        m["aov"].append(round(g / o, 2) if o else 0)
        m["cancelled"].append(r.get("cancelled", 0))
        m["attempts"].append(r.get("attempts", 0))
        d += timedelta(days=1)
    return {"dates": dates, "m": m}


@app.get("/api/orders/analytics")
def orders_analytics(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False):
    lo = date_from or str(one("SELECT min(date_ist) AS d FROM orders_clean")["d"])
    hi = date_to or str(one("SELECT max(date_ist) AS d FROM orders_clean")["d"])
    pr = prev_range(date_from, date_to)
    kpis = _order_kpis(date_from, date_to, include_excluded)
    prev = _order_kpis(pr[0], pr[1], include_excluded) if pr else None
    cur = _order_series(lo, hi, include_excluded)
    pser = _order_series(pr[0], pr[1], include_excluded) if pr else None
    w = "o.date_ist BETWEEN ? AND ? AND NOT o.is_test" + ("" if include_excluded else " AND NOT o.is_excluded")
    a = [date_from or "2000-01-01", date_to or "2999-12-31"]
    status = q(f"SELECT o.status, count(*) AS n, coalesce(sum(o.total), 0) AS gmv FROM orders_clean o WHERE {w} GROUP BY 1 ORDER BY n DESC", a)
    payment = q(f"""SELECT coalesce(o.payment_method, '(not recorded)') AS method, count(*) AS attempts, count(*) FILTER (WHERE o.is_valid) AS orders,
        coalesce(sum(o.total) FILTER (WHERE o.is_valid), 0) AS gmv, coalesce(avg(o.total) FILTER (WHERE o.is_valid), 0) AS aov,
        count(*) FILTER (WHERE o.status = 'payment_cancelled') AS cancelled FROM orders_clean o WHERE {w} GROUP BY 1 ORDER BY attempts DESC""", a)
    failures = q(f"SELECT coalesce(o.payment_failed_reason, '(no reason recorded)') AS reason, count(*) AS n FROM orders_clean o WHERE {w} AND NOT o.is_placed GROUP BY 1 ORDER BY n DESC LIMIT 8", a)
    coupons = q(f"""SELECT coalesce(split_part(o.coupon_code, ',', 1), '(no coupon)') AS coupon, count(*) AS orders, coalesce(sum(o.total), 0) AS gmv, avg(o.total) AS aov,
        avg(o.coupon_discount) AS avg_discount FROM orders_clean o WHERE {w} AND o.is_valid GROUP BY 1 ORDER BY orders DESC LIMIT 10""", a)
    cities = q(f"SELECT coalesce(o.city, 'Unknown') AS city, count(*) AS orders, coalesce(sum(o.total), 0) AS gmv, avg(o.total) AS aov FROM orders_clean o WHERE {w} AND o.is_valid GROUP BY 1 ORDER BY orders DESC LIMIT 10", a)
    pins = q(f"SELECT coalesce(o.pincode, 'Unknown') AS pincode, any_value(o.city) AS city, count(*) AS orders, coalesce(sum(o.total), 0) AS gmv FROM orders_clean o WHERE {w} AND o.is_valid GROUP BY 1 ORDER BY orders DESC LIMIT 10", a)
    hours = q(f"""SELECT extract(dow FROM o.ts_ist)::INT AS dow, extract(hour FROM o.ts_ist)::INT AS hour, count(*) AS orders FROM orders_clean o WHERE {w} AND o.is_valid GROUP BY 1, 2""", a)
    customers = q(f"""SELECT CASE WHEN o.nth_order = 1 THEN 'First order' ELSE 'Repeat order' END AS kind, count(*) AS orders, coalesce(sum(o.total), 0) AS gmv, avg(o.total) AS aov
        FROM orders_clean o WHERE {w} AND o.is_valid GROUP BY 1 ORDER BY 1""", a)
    channels = q(f"SELECT coalesce(o.channel, 'Unattributed') AS channel, count(*) AS orders, coalesce(sum(o.total), 0) AS gmv, avg(o.total) AS aov FROM orders_clean o WHERE {w} AND o.is_valid GROUP BY 1 ORDER BY orders DESC", a)
    buckets = q(f"""SELECT CASE WHEN o.total < 300 THEN '1. under 300' WHEN o.total < 500 THEN '2. 300-499' WHEN o.total < 800 THEN '3. 500-799' WHEN o.total < 1200 THEN '4. 800-1199'
        ELSE '5. 1200+' END AS band, count(*) AS orders FROM orders_clean o WHERE {w} AND o.is_valid GROUP BY 1 ORDER BY 1""", a)
    delivery = one(f"""SELECT count(*) FILTER (WHERE o.delivered_at IS NOT NULL) AS delivered,
        count(*) FILTER (WHERE o.delivered_at IS NOT NULL AND date_diff('hour', o.ts, o.delivered_at) <= 24) AS within_24h,
        count(*) FILTER (WHERE o.delivered_at IS NOT NULL AND date_diff('hour', o.ts, o.delivered_at) <= 48) AS within_48h,
        median(date_diff('minute', o.ts, o.delivered_at)) FILTER (WHERE o.delivered_at IS NOT NULL) / 60.0 AS median_h,
        median(date_diff('minute', o.ts, o.picked_up_at)) FILTER (WHERE o.picked_up_at IS NOT NULL) / 60.0 AS median_pickup_h
        FROM orders_clean o WHERE {w} AND o.is_valid""", a)
    riders = q(f"""SELECT coalesce(o.rider_name, 'Unassigned') AS rider, count(*) AS orders, count(*) FILTER (WHERE o.delivered_at IS NOT NULL) AS delivered,
        median(date_diff('minute', o.ts, o.delivered_at)) FILTER (WHERE o.delivered_at IS NOT NULL) / 60.0 AS median_h
        FROM orders_clean o WHERE {w} AND o.is_valid GROUP BY 1 ORDER BY orders DESC LIMIT 8""", a)
    return {"kpis": kpis, "prev": prev, "prev_range": pr, "dates": cur["dates"], "current": cur["m"], "prev_dates": pser["dates"] if pser else None, "previous": pser["m"] if pser else None,
            "status": status, "payment": payment, "failures": failures, "coupons": coupons, "cities": cities, "pincodes": pins, "hours": hours,
            "customers": customers, "channels": channels, "buckets": buckets, "delivery": delivery, "riders": riders}


@app.get("/api/orders/{order_id}")
def order_detail(order_id: str):
    rows = q("SELECT * FROM orders_clean WHERE order_id = ?", [order_id.lower()])
    if not rows:
        raise HTTPException(404, "order not found")
    o = rows[0]
    items = q("SELECT product_id, product_name, brand, product_type, qty, price, line_total FROM order_lines WHERE order_id = ? ORDER BY line_total DESC", [o["order_id"]])
    steps = [("Order placed", o["ts"]), ("Payment received", o["paid_at"]), ("Picked up", o["picked_up_at"]), ("Out for delivery", o["delivery_started_at"]),
             ("Delivered", o["delivered_at"]), ("Cash collected", o["cod_collected_at"])]
    timeline = sorted(({"label": l, "at": t} for l, t in steps if t), key=lambda x: x["at"])
    customer = one("SELECT person_key, name, phone10, email, segment, sessions, orders, revenue, first_channel FROM users_360 WHERE user_id = ?", [o["user_id"]]) if o["user_id"] else {}
    others = q("SELECT order_id, ts, total, status, nth_order FROM orders_clean WHERE user_id = ? AND order_id <> ? AND NOT is_test ORDER BY ts DESC LIMIT 20", [o["user_id"], o["order_id"]]) if o["user_id"] else []
    session = one("SELECT session_id, started_at, channel, source, medium, campaign, landing_path, device, city FROM sessions WHERE session_id = ?", [o["session_id"]]) if o["session_id"] else {}
    return {"order": o, "items": items, "timeline": timeline, "customer": customer or None, "other_orders": others, "session": session or None}



# ------------------------------------------------------------------ Meta Ads (spend from Meta joined to our own sessions and orders)
def _meta_rows(d_from, d_to, include_excluded) -> list[dict]:
    lo, hi = d_from or "2000-01-01", d_to or "2999-12-31"
    mrows = q("""SELECT campaign_id, any_value(campaign_name) AS name, sum(spend) AS spend, sum(impressions) AS impressions, sum(clicks) AS clicks, sum(link_clicks) AS link_clicks,
                 sum(purchases) AS meta_purchases, sum(purchase_value) AS meta_value, sum(add_to_cart) AS meta_atc, sum(initiate_checkout) AS meta_checkout,
                 min(date) AS first_day, max(date) AS last_day FROM raw_meta_insights WHERE date BETWEEN ? AND ? GROUP BY campaign_id""", [lo, hi])
    ex = "" if include_excluded else " AND NOT s.is_excluded"
    ours = {r["cid"]: r for r in q(f"""SELECT sm.meta_campaign_id AS cid, count(*) AS sessions, count(DISTINCT s.visitor_key) AS visitors, count(*) FILTER (WHERE s.f_cart) AS carts,
        count(*) FILTER (WHERE s.f_checkout) AS checkouts, count(*) FILTER (WHERE s.f_quiz_done) AS quiz FROM sessions s JOIN session_meta sm USING (session_id)
        WHERE s.date_ist BETWEEN ? AND ?{ex} GROUP BY 1""", [lo, hi])}
    oex = "" if include_excluded else " AND NOT o.is_excluded"
    ords = {r["cid"]: r for r in q(f"""SELECT sm.meta_campaign_id AS cid, count(*) AS orders, coalesce(sum(o.total), 0) AS revenue FROM orders_clean o
        JOIN session_meta sm ON sm.session_id = o.session_id WHERE o.is_valid AND o.date_ist BETWEEN ? AND ?{oex} GROUP BY 1""", [lo, hi])}
    ents = {r["entity_id"]: r for r in q("SELECT entity_id, effective_status, objective, daily_budget FROM raw_meta_entities WHERE entity_type = 'campaign'")}
    out = []
    for m in mrows:
        o, w, e = ours.get(m["campaign_id"], {}), ords.get(m["campaign_id"], {}), ents.get(m["campaign_id"], {})
        r = {**m, "sessions": o.get("sessions", 0), "visitors": o.get("visitors", 0), "carts": o.get("carts", 0), "checkouts": o.get("checkouts", 0), "quiz": o.get("quiz", 0),
             "orders": w.get("orders", 0), "revenue": float(w.get("revenue", 0) or 0), "status": e.get("effective_status"), "objective": e.get("objective"), "daily_budget": e.get("daily_budget")}
        out.append(_meta_derive(r))
    return out


def _meta_derive(r: dict) -> dict:
    sp = float(r["spend"] or 0)
    r["spend"] = sp
    r["ctr"] = ratio(r["clicks"], r["impressions"])
    r["cpc"] = round(sp / r["clicks"], 2) if r["clicks"] else None
    r["cpm"] = round(sp / r["impressions"] * 1000, 2) if r["impressions"] else None
    r["meta_roas"] = round((r["meta_value"] or 0) / sp, 2) if sp else None
    r["our_roas"] = round(r["revenue"] / sp, 2) if sp else None
    r["cost_per_session"] = round(sp / r["sessions"], 2) if r["sessions"] else None
    r["cost_per_cart"] = round(sp / r["carts"], 2) if r["carts"] else None
    r["cost_per_order"] = round(sp / r["orders"], 2) if r["orders"] else None
    r["cart_rate"] = ratio(r["carts"], r["sessions"])
    r["click_to_session"] = ratio(r["sessions"], r["link_clicks"]) if r["link_clicks"] else None
    if r["orders"] and r["our_roas"] and r["our_roas"] >= 1:
        r["verdict"] = "Paying back"
    elif r["orders"]:
        r["verdict"] = "Converting"
    elif sp >= 300 and r["carts"] == 0:
        r["verdict"] = "Wasting spend"
    elif r["carts"]:
        r["verdict"] = "Promising"
    else:
        r["verdict"] = "Too early"
    return r


def _meta_totals(rows: list[dict]) -> dict:
    keys = ("spend", "impressions", "clicks", "link_clicks", "meta_purchases", "meta_value", "meta_atc", "sessions", "visitors", "carts", "checkouts", "quiz", "orders", "revenue")
    t = {k: sum((r[k] or 0) for r in rows) for k in keys}
    return _meta_derive({**t, "meta_checkout": 0})


def _meta_blended(d_from, d_to, include_excluded, spend: float) -> dict:
    """Orders from ALL Paid Meta traffic, even sessions whose campaign tag cannot be matched to a Meta campaign (so ROAS is not understated)."""
    oex = "" if include_excluded else " AND NOT o.is_excluded"
    r = one(f"""SELECT count(*) AS orders, coalesce(sum(o.total), 0) AS revenue FROM orders_clean o JOIN sessions s ON s.session_id = o.session_id
                WHERE s.channel = 'Paid Meta' AND o.is_valid AND o.date_ist BETWEEN ? AND ?{oex}""", [d_from or "2000-01-01", d_to or "2999-12-31"])
    rev = float(r["revenue"] or 0)
    return {"spend": spend, "orders": r["orders"], "revenue": rev, "roas": round(rev / spend, 2) if spend else None,
            "cost_per_order": round(spend / r["orders"], 2) if r["orders"] else None}


def _meta_series(lo: str, hi: str, include_excluded: bool) -> dict:
    ex = "" if include_excluded else " AND NOT s.is_excluded"
    oex = "" if include_excluded else " AND NOT o.is_excluded"
    md = {str(r["d"]): r for r in q("SELECT date AS d, sum(spend) AS spend, sum(impressions) AS impressions, sum(clicks) AS clicks, sum(link_clicks) AS link_clicks FROM raw_meta_insights WHERE date BETWEEN ? AND ? GROUP BY 1", [lo, hi])}
    sd = {str(r["d"]): r for r in q(f"""SELECT s.date_ist AS d, count(*) AS sessions, count(*) FILTER (WHERE s.f_cart) AS carts FROM sessions s JOIN session_meta sm USING (session_id)
                                      WHERE s.date_ist BETWEEN ? AND ?{ex} GROUP BY 1""", [lo, hi])}
    od = {str(r["d"]): r for r in q(f"""SELECT o.date_ist AS d, count(*) AS orders, coalesce(sum(o.total), 0) AS revenue FROM orders_clean o JOIN session_meta sm ON sm.session_id = o.session_id
                                      WHERE o.is_valid AND o.date_ist BETWEEN ? AND ?{oex} GROUP BY 1""", [lo, hi])}
    dates, m = [], {k: [] for k in ("spend", "impressions", "clicks", "link_clicks", "sessions", "carts", "orders", "revenue")}
    d, end = date.fromisoformat(lo), date.fromisoformat(hi)
    while d <= end:
        k = d.isoformat()
        dates.append(k)
        for key, src in (("spend", md), ("impressions", md), ("clicks", md), ("link_clicks", md), ("sessions", sd), ("carts", sd), ("orders", od), ("revenue", od)):
            v = src.get(k, {}).get(key, 0) or 0
            m[key].append(round(float(v), 2) if key in ("spend", "revenue") else int(v))
        d += timedelta(days=1)
    return {"dates": dates, "m": m}


@app.get("/api/meta/status")
def meta_status(check: bool = False):
    """Connection state. `check=true` also asks Meta about the token (validity / expiry); the token itself is never returned."""
    out = {"configured": meta_mod.configured()}
    kv = {r["k"]: r["v"] for r in q("SELECT k, v FROM etl_meta WHERE k LIKE 'meta_%'")}
    out["last_sync"] = kv.get("meta_last_sync")
    out["last_error"] = kv.get("meta_last_error")
    out["accounts"] = json.loads(kv["meta_accounts"]) if kv.get("meta_accounts") else []
    st = one("SELECT count(*) AS rows, min(date) AS first_day, max(date) AS last_day, coalesce(sum(spend), 0) AS spend, count(DISTINCT campaign_id) AS campaigns FROM raw_meta_insights")
    out.update(st)
    if check and out["configured"]:
        try:
            c = meta_mod.MetaClient()
            out["token"] = c.token_info()
            out["user"] = c.me().get("name")
        except Exception as e:
            out["token"] = {"valid": False, "error": meta_mod.redact(e)}
    return out


@app.post("/api/meta/sync")
def meta_sync(full: bool = False):
    if not meta_mod.configured():
        raise HTTPException(400, "META_ACCESS_TOKEN is not set in .env")

    def fn():
        JOB["message"] = "pulling Meta Ads"
        try:
            meta_mod.sync(CON.cursor(), full=full)
        except Exception as e:
            meta_mod.record_error(CON.cursor(), e)
            raise
        JOB["message"] = "linking campaigns to your sessions"
        transform.run(CON.cursor(), flags_only=True)
    _run_job("meta-sync", fn)
    return JOB


@app.get("/api/meta/overview")
def meta_overview(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False):
    if not one("SELECT count(*) AS n FROM raw_meta_insights")["n"]:
        return {"connected": False}
    rows = _meta_rows(date_from, date_to, include_excluded)
    rows.sort(key=lambda r: -r["spend"])
    tot = _meta_totals(rows)
    pr = prev_range(date_from, date_to)
    prev = _meta_totals(_meta_rows(pr[0], pr[1], include_excluded)) if pr else None
    lo = date_from or str(one("SELECT min(date) AS d FROM raw_meta_insights")["d"])
    hi = date_to or str(one("SELECT max(date) AS d FROM raw_meta_insights")["d"])
    cur = _meta_series(lo, hi, include_excluded)
    pser = _meta_series(pr[0], pr[1], include_excluded) if pr else None
    ex = "" if include_excluded else " AND NOT s.is_excluded"
    cov = one(f"""SELECT count(*) AS paid_meta_sessions, count(sm.session_id) AS matched FROM sessions s LEFT JOIN session_meta sm USING (session_id)
                  WHERE s.channel = 'Paid Meta' AND s.date_ist BETWEEN ? AND ?{ex}""", [date_from or "2000-01-01", date_to or "2999-12-31"])
    unmatched = q(f"""SELECT s.campaign, count(*) AS sessions FROM sessions s LEFT JOIN session_meta sm USING (session_id)
                      WHERE s.channel = 'Paid Meta' AND sm.session_id IS NULL AND s.date_ist BETWEEN ? AND ?{ex} GROUP BY 1 ORDER BY 2 DESC LIMIT 6""", [date_from or "2000-01-01", date_to or "2999-12-31"])
    blended = _meta_blended(date_from, date_to, include_excluded, tot["spend"])
    pblended = _meta_blended(pr[0], pr[1], include_excluded, prev["spend"]) if (pr and prev) else None
    return {"connected": True, "blended": blended, "prev_blended": pblended, "totals": tot, "prev": prev, "prev_range": pr, "campaigns": rows, "dates": cur["dates"], "current": cur["m"],
            "prev_dates": pser["dates"] if pser else None, "previous": pser["m"] if pser else None,
            "coverage": {**cov, "unmatched": unmatched}, "wasted": [r for r in rows if r["verdict"] == "Wasting spend"]}


@app.get("/api/meta/breakdown")
def meta_breakdown(level: str = "adset", campaign_id: str | None = None, date_from: str | None = None, date_to: str | None = None):
    """Ad sets or ads, with Meta's own numbers (our sessions can only be matched to campaigns reliably)."""
    if level not in ("adset", "ad"):
        raise HTTPException(400, "level must be adset or ad")
    idc, namec = ("adset_id", "adset_name") if level == "adset" else ("ad_id", "ad_name")
    w, a = "date BETWEEN ? AND ?", [date_from or "2000-01-01", date_to or "2999-12-31"]
    if campaign_id:
        w += " AND campaign_id = ?"
        a.append(campaign_id)
    rows = q(f"""SELECT {idc} AS id, any_value({namec}) AS name, any_value(campaign_name) AS campaign, sum(spend) AS spend, sum(impressions) AS impressions, sum(clicks) AS clicks,
                 sum(link_clicks) AS link_clicks, sum(purchases) AS meta_purchases, sum(purchase_value) AS meta_value, sum(add_to_cart) AS meta_atc, sum(initiate_checkout) AS meta_checkout
                 FROM raw_meta_insights WHERE {w} GROUP BY 1 ORDER BY spend DESC LIMIT 200""", a)
    thumbs = {r["entity_id"]: r for r in q("SELECT entity_id, thumbnail_url, effective_status FROM raw_meta_entities WHERE entity_type = ?", [level])}
    for r in rows:
        t = thumbs.get(r["id"], {})
        r["thumbnail_url"], r["status"] = t.get("thumbnail_url"), t.get("effective_status")
        r["ctr"] = ratio(r["clicks"], r["impressions"])
        r["cpc"] = round(r["spend"] / r["clicks"], 2) if r["clicks"] else None
        r["meta_roas"] = round((r["meta_value"] or 0) / r["spend"], 2) if r["spend"] else None
    return {"level": level, "rows": rows}


# ------------------------------------------------------------------ static dashboard (after `npm run build`)
DIST = ROOT / "dashboard" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=str(DIST), html=True), name="dashboard")

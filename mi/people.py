"""People: profiles, users, cohorts, retention, lifetime value and audiences."""
import re
from fastapi import HTTPException

from .core import _csv, app, one, q, ratio
from .orders import _order_filter
from .sessions import _addresses


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
        FROM users_360 WHERE {w} GROUP BY 1 ORDER BY people DESC, 1 LIMIT ?""", [date_from or "2000-01-01", date_to or "2999-12-31", limit])
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


@app.get("/api/person")
def person_profile(key: str):
    """`key` is a person key: the account id for logged-in people, or the browser id for anonymous visitors."""
    sess = q("""WITH s0 AS (SELECT * FROM sessions WHERE coalesce(user_id, visitor_key) = ?),
                b AS (SELECT session_id, max(browser_n) AS browser FROM events_clean WHERE session_id IN (SELECT session_id FROM s0) GROUP BY 1)
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
    ips = q("""SELECT ip, count(*) AS events, count(DISTINCT session_id) AS sessions, min(ts) AS first_seen, max(ts) AS last_seen, max(city_n) AS city
               FROM events_clean WHERE ip IS NOT NULL AND session_id IN (SELECT session_id FROM sessions WHERE coalesce(user_id, visitor_key) = ?)
               GROUP BY 1 ORDER BY events DESC, 1 LIMIT 15""", [key])
    orders = q("""SELECT o.order_id, o.ts, o.total, o.status, o.payment_method, o.coupon_code, o.items_count, o.is_valid, o.is_test, o.is_excluded, o.session_id,
                  (SELECT string_agg(l.product_name, ' | ' ORDER BY l.product_name) FROM order_lines l WHERE l.order_id = o.order_id) AS items
                  FROM orders_clean o WHERE o.user_id = ? ORDER BY o.ts DESC""", [key])
    daily = q("SELECT date_ist AS d, count(*) AS sessions, sum(events) AS events FROM sessions WHERE coalesce(user_id, visitor_key) = ? GROUP BY 1 ORDER BY 1", [key])
    totals = {"sessions": len(sess), "events": sum(r["events"] for r in sess), "pageviews": sum(r["pageviews"] for r in sess),
              "seconds": sum(r["duration_s"] or 0 for r in sess), "browsers": len(browsers), "ips": len(ips),
              "devices": len({(r["device"], r["platform"], r["is_app"]) for r in sess})}
    uid = key if re.fullmatch(r"[0-9a-fA-F-]{36}", key or "") else None
    return {"person_key": key, "addresses": _addresses(uid), "profile": profile or None, "totals": totals, "sessions": sess, "browsers": sorted(browsers.values(), key=lambda b: b["last_seen"], reverse=True),
            "ips": ips, "orders": orders, "daily": daily}


USER_SORTS = {"last_seen": "last_seen", "first_seen": "first_seen", "name": "nullif(lower(name), '')", "city": "nullif(lower(city), '')", "sessions": "sessions", "orders": "orders",
              "revenue": "revenue", "cart_sessions": "cart_sessions", "segment": "segment", "first_channel": "first_channel", "email": "nullif(lower(email), '')"}


USER_PRESETS = {"cart_abandoners": "cart_sessions > 0 AND orders = 0", "checkout_abandoners": "checkout_sessions > 0 AND orders = 0",
                "logged_in": "is_registered", "buyers": "orders > 0", "reachable": "nullif(phone10, '') IS NOT NULL",
                "has_pincode": "delivery_pincode IS NOT NULL", "saved_address": "has_saved_address"}


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
        city, state, device, uses_app, cart_sessions, checkout_sessions, orders, revenue, gender, skin_type, age_bucket, segment, is_excluded,
        delivery_pincode, has_saved_address, ip_city
        FROM users_360 WHERE {w} ORDER BY {order} {d} NULLS LAST, last_seen DESC, person_key LIMIT ? OFFSET ?""", [*a, max(1, min(int(limit), 5000)), max(0, offset)])
    segs = q(f"SELECT segment, count(*) n FROM users_360 WHERE {'TRUE' if include_excluded else 'NOT is_excluded'} GROUP BY 1 ORDER BY 2 DESC")
    return {"total": total, "rows": rows, "segments": segs}


@app.get("/api/users/counts")
def user_counts(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False):
    """Sizes of the one-click presets on the Users tab (person level: someone who later ordered is not an abandoner)."""
    w, a = _users_where(date_from, date_to, include_excluded)
    cols = ", ".join(f"count(*) FILTER (WHERE {c}) AS {k}" for k, c in USER_PRESETS.items())
    return one(f"SELECT count(*) AS total, {cols} FROM users_360 WHERE {w}", a)


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
    reordered = q(f"""SELECT product_name, coalesce(max(brand) FILTER (WHERE brand <> 'Unknown'), 'Unknown') brand, count(*) repeat_customers, sum(orders) orders FROM (
        SELECT user_id, product_name, coalesce(max(brand) FILTER (WHERE brand <> 'Unknown'), 'Unknown') AS brand, count(DISTINCT order_id) orders FROM order_lines l WHERE {lw} GROUP BY 1,2 HAVING count(DISTINCT order_id) >= 2) GROUP BY product_name ORDER BY 3 DESC, 4 DESC, 1 LIMIT 8""")
    return {"as_of": as_of, "kpis": k, "dist": dist, "gaps": gaps, "median_gap_days": median_gap, "by_channel": by_channel,
            "cohorts": list(coh.values()), "recency": recency, "reordered": reordered}


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
        FROM ({base}) p WHERE {cond} ORDER BY {order} NULLS LAST, p.last_seen DESC, p.person_key LIMIT ? OFFSET ?""", [limit, offset])
    return {"id": aid, "title": spec[1], "description": spec[2], "action": spec[3], "total": total, "rows": rows}

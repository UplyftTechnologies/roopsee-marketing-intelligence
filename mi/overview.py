"""Overview, time series, funnel, report table and the plain-language insights."""
from datetime import date, timedelta
from fastapi import HTTPException

from .acquisition import campaigns
from .core import app, one, prev_range, q, ratio, sess_where
from .meta_ads import _meta_blended, _meta_rows, _meta_totals
from .orders import basket
from .people import audiences, loyalty
from .sessions import FLAG_ORDER
from .system import _tracking_change


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
    landing = q(f"SELECT landing_type, count(*) sessions, count(*) FILTER (WHERE f_cart) carts FROM sessions s WHERE {w} GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 8", a)
    staff = one("SELECT count(*) orders, coalesce(sum(total),0) revenue FROM orders_clean WHERE date_ist BETWEEN ? AND ? AND is_valid AND is_staff_order", a)
    rule_on = bool(q("SELECT 1 FROM exclusions WHERE kind='rule' AND value='staff_orders' AND active"))
    return {"kpis": k, "prev": prev, "prev_range": pr, "staff_orders": {**staff, "excluded": rule_on}, "daily": daily, "channels": channels, "devices": devices, "hours": hours, "landing": landing}


@app.get("/api/funnel")
def funnel(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, channel: str | None = None):
    w, a = sess_where(date_from, date_to, include_excluded)
    if channel:
        w += " AND s.channel = ?"; a.append(channel)
    r = one(f"""SELECT count(*) visit, count(*) FILTER (WHERE f_product) product, count(*) FILTER (WHERE f_cart) cart,
        count(*) FILTER (WHERE f_checkout) checkout, count(*) FILTER (WHERE f_pay) pay, count(*) FILTER (WHERE {FLAG_ORDER}) ordered,
        count(*) FILTER (WHERE f_quiz_start) quiz_start, count(*) FILTER (WHERE f_quiz_done) quiz_done,
        count(*) FILTER (WHERE f_quiz_done AND f_cart) quiz_to_cart, count(*) FILTER (WHERE f_login) login
        FROM sessions s LEFT JOIN session_orders o ON o.session_id = s.session_id WHERE {w}""", a)
    steps = [("Sessions", r["visit"]), ("Viewed a product", r["product"]), ("Added to cart", r["cart"]),
             ("Reached checkout", r["checkout"]), ("Started payment", r["pay"]), ("Placed an order", r["ordered"])]
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
        WHERE event_key = 'add_to_cart' AND NOT is_dup AND product_name IS NOT NULL AND product_name <> ''
        AND (? OR NOT is_excluded) AND timezone('Asia/Kolkata', ts)::DATE BETWEEN ? AND ?
        GROUP BY 1,2 ORDER BY 3 DESC, 1 LIMIT 15""", [include_excluded, *ca])
    actual = one("SELECT count(*) n FROM orders_clean WHERE date_ist BETWEEN ? AND ? AND is_valid" + ("" if include_excluded else " AND NOT is_excluded"),
                 [date_from or "2000-01-01", date_to or "2999-12-31"])["n"]
    return {"actual_orders": actual, "stages": stages, "quiz": {k: r[k] for k in ("quiz_start", "quiz_done", "quiz_to_cart", "login")},
            "checkout_outcomes": outcomes, "payment_methods": methods, "abandoned": abandoned, "top_products": products}


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
    hr = one(f"SELECT extract(hour FROM timezone('Asia/Kolkata', started_at))::INT AS h, count(*) n FROM sessions s WHERE {w} GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 1", a)
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
                         AND payment_failed_reason IS NOT NULL GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 1""", [date_from or "2000-01-01", date_to or "2999-12-31"])
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


REPORT_DIMS = {
    "channel": "s.channel",
    "source_medium": "s.source || ' / ' || s.medium",
    "campaign": "s.campaign",
    "device": "coalesce(CASE WHEN s.is_app THEN 'Android app' ELSE s.device END, 'Unknown')",
    "landing": "s.landing_type",
    "state": "coalesce(s.region, 'Unknown')",
    "city": "coalesce(s.city, 'Unknown')",
    "country": "coalesce(s.country, 'Unknown')",
    "channel_split": "s.channel_split",
    "delivery_state": "coalesce(s.delivery_state, 'No address given')",
    "delivery_city": "coalesce(s.delivery_city, 'No address given')",
    "pincode": "coalesce(s.pincode, 'No pincode given')",
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
    """One row per value of the chosen dimension, with a totals row. Orders are counted by order date (like the Overview and Orders pages)
    and credited to the session they were placed in. `reconcile` says how many orders of the period are not in the table (their visit started
    before the period, or the order predates tracking), so the numbers always add up to the Overview total."""
    if dimension not in REPORT_DIMS:
        raise HTTPException(400, f"dimension must be one of {list(REPORT_DIMS)}")
    order_by = REPORT_SORTS.get(sort, "sessions")
    direction = "ASC" if direction.lower() == "asc" else "DESC"
    expr = REPORT_DIMS[dimension]
    w, a = sess_where(date_from, date_to, include_excluded)
    oa = [date_from or "2000-01-01", date_to or "2999-12-31"]
    ords = f"(SELECT session_id, count(*) AS orders, sum(revenue) AS revenue FROM orders_clean WHERE is_valid AND date_ist BETWEEN ? AND ? {'' if include_excluded else 'AND NOT is_excluded'} GROUP BY 1)"
    base = f"FROM sessions s LEFT JOIN {ords} o ON o.session_id = s.session_id WHERE {w}"
    sq, sa = "", []
    if search:
        sq, sa = f" AND ({expr}) ILIKE ?", [f"%{search}%"]
    limit = max(1, min(int(limit), 5000))
    ms = max(1, int(min_sessions))
    rows = q(f"SELECT {expr} AS dim, {REPORT_METRICS} {base}{sq} GROUP BY 1 HAVING count(*) >= ? ORDER BY {order_by} {direction} NULLS LAST, dim LIMIT ? OFFSET ?", [*oa, *a, *sa, ms, limit, max(0, offset)])
    groups = one(f"SELECT count(*) AS n FROM (SELECT {expr} AS g {base}{sq} GROUP BY 1 HAVING count(*) >= ?)", [*oa, *a, *sa, ms])["n"]
    totals = one(f"SELECT {REPORT_METRICS} {base}{sq}", [*oa, *a, *sa])
    all_orders = one("SELECT count(*) AS n, coalesce(sum(revenue), 0) AS revenue FROM orders_clean WHERE is_valid AND date_ist BETWEEN ? AND ?" + ("" if include_excluded else " AND NOT is_excluded"), oa)
    in_table = (totals or {}).get("orders", 0)
    rec = {"orders_total": all_orders["n"], "orders_in_table": in_table, "orders_other": max(0, all_orders["n"] - in_table),
           "revenue_other": max(0.0, round(all_orders["revenue"] - ((totals or {}).get("revenue") or 0), 2))}
    return {"dimension": dimension, "rows": [_derive(r) for r in rows], "totals": _derive(totals) if totals else None, "groups": groups, "reconcile": rec}

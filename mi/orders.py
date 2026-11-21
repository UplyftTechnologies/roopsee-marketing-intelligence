"""Orders: list, analytics, one order in detail, and the basket / order value lab."""
from datetime import date, timedelta
from fastapi import HTTPException

from .core import _csv, _in, app, one, prev_range, q, ratio


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
    products = q(f"""SELECT product_name, coalesce(max(brand) FILTER (WHERE brand <> 'Unknown'), 'Unknown') brand, max(product_type) product_type, sum(qty) units, count(DISTINCT order_id) orders, sum(line_total) revenue
        FROM order_lines l WHERE {lw} GROUP BY product_name ORDER BY round(revenue, 2) DESC, 1 LIMIT 12""", la)
    brands = q(f"""SELECT coalesce(max(brand) FILTER (WHERE brand <> 'Unknown'), 'Unknown') brand, sum(qty) units, count(DISTINCT order_id) orders, sum(line_total) revenue
        FROM order_lines l WHERE {lw} GROUP BY lower(brand) ORDER BY round(revenue, 2) DESC, 1 LIMIT 10""", la)
    types = q(f"""SELECT product_type, max(category) category, sum(qty) units, count(DISTINCT order_id) orders, sum(line_total) revenue
        FROM order_lines l WHERE {lw} GROUP BY product_type ORDER BY round(revenue, 2) DESC, 1 LIMIT 12""", la)
    cover = one(f"SELECT coalesce(100.0 * sum(line_total) FILTER (WHERE brand <> 'Unknown') / nullif(sum(line_total),0), 0) brand_known_pct, coalesce(100.0 * sum(line_total) FILTER (WHERE NOT type_inferred) / nullif(sum(line_total),0), 0) catalog_type_pct FROM order_lines l WHERE {lw}", la)
    pairs = q(f"""WITH t AS (SELECT DISTINCT order_id, product_type FROM order_lines l WHERE {lw} AND product_type NOT IN ('Other','Unknown'))
        SELECT a.product_type AS a, b.product_type AS b, count(*) orders FROM t a JOIN t b ON a.order_id = b.order_id AND a.product_type < b.product_type
        GROUP BY 1,2 HAVING count(*) >= 2 ORDER BY 3 DESC, 1 LIMIT 10""", la)
    coupons = q(f"""SELECT coalesce(split_part(c.coupon_code, ',', 1), '(no coupon)') coupon, count(*) orders, avg(c.total) aov, avg(c.products_total) avg_basket,
        avg(try_cast(o.coupon_discount AS DOUBLE)) avg_discount FROM orders_clean c JOIN raw_orders o ON lower(o.id) = c.order_id
        WHERE {ow} GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 10""", oa)
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


ORDER_SORTS = {"ts": "o.ts", "total": "o.total", "products_total": "o.products_total", "status": "o.status", "payment_method": "o.payment_method",
               "city": "nullif(lower(o.city), '')", "customer_name": "nullif(lower(o.customer_name), '')", "coupon_code": "o.coupon_code",
               "items_count": "o.items_count", "nth_order": "o.nth_order", "delivery_fee": "o.delivery_fee"}


ORDER_SCOPES = {"sales": "o.is_valid", "all": "NOT o.is_test", "unpaid": "(NOT o.is_placed AND NOT o.is_test)", "internal": "o.is_excluded"}


ORDER_ITEMS = "(SELECT string_agg(l.product_name || CASE WHEN l.qty > 1 THEN ' x' || l.qty ELSE '' END, ' | ' ORDER BY l.product_name) FROM order_lines l WHERE l.order_id = o.order_id)"


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
        o.is_valid, o.is_test, o.is_staff_order, o.is_excluded, o.payment_state, o.credit_channel
        FROM orders_clean o WHERE {w} ORDER BY {order} {d} NULLS LAST, o.ts DESC, o.order_id LIMIT ? OFFSET ?""", [*a, max(1, min(int(limit), 5000)), max(0, offset)])
    opts = {"statuses": [r["status"] for r in q("SELECT status, count(*) n FROM orders_clean WHERE NOT is_test GROUP BY 1 ORDER BY 2 DESC")],
            "payment_methods": [r["m"] for r in q("SELECT coalesce(payment_method, '(not recorded)') AS m, count(*) n FROM orders_clean WHERE NOT is_test GROUP BY 1 ORDER BY 2 DESC")],
            "coupons": [r["c"] for r in q("SELECT coalesce(split_part(coupon_code, ',', 1), '(no coupon)') AS c, count(*) n FROM orders_clean WHERE NOT is_test GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 30")]}
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
        median(date_diff('minute', o.ts, o.delivered_at)) FILTER (WHERE o.is_valid AND o.delivered_at IS NOT NULL) / 60.0 AS median_delivery_h,
        count(*) FILTER (WHERE o.is_valid AND o.payment_state IN ('unconfirmed', 'conflicting')) AS at_risk_orders,
        coalesce(sum(o.total) FILTER (WHERE o.is_valid AND o.payment_state IN ('unconfirmed', 'conflicting')), 0) AS at_risk_value,
        count(*) FILTER (WHERE o.is_valid AND o.payment_state = 'cod_pending') AS cod_pending_orders,
        coalesce(sum(o.total) FILTER (WHERE o.is_valid AND o.payment_state = 'cod_pending'), 0) AS cod_pending_value
        FROM orders_clean o WHERE o.date_ist BETWEEN ? AND ? AND NOT o.is_test{ex}""", [d_from or "2000-01-01", d_to or "2999-12-31"])
    k["aov"] = round(k["gmv"] / k["orders"], 2) if k["orders"] else 0
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
    failures = q(f"SELECT coalesce(o.payment_failed_reason, '(no reason recorded)') AS reason, count(*) AS n FROM orders_clean o WHERE {w} AND NOT o.is_placed GROUP BY 1 ORDER BY n DESC, 1 LIMIT 8", a)
    coupons = q(f"""SELECT coalesce(split_part(o.coupon_code, ',', 1), '(no coupon)') AS coupon, count(*) AS orders, coalesce(sum(o.total), 0) AS gmv, avg(o.total) AS aov,
        avg(o.coupon_discount) AS avg_discount FROM orders_clean o WHERE {w} AND o.is_valid GROUP BY 1 ORDER BY orders DESC, 1 LIMIT 10""", a)
    cities = q(f"SELECT coalesce(o.city, 'Unknown') AS city, count(*) AS orders, coalesce(sum(o.total), 0) AS gmv, avg(o.total) AS aov FROM orders_clean o WHERE {w} AND o.is_valid GROUP BY 1 ORDER BY orders DESC, 1 LIMIT 10", a)
    pins = q(f"SELECT coalesce(o.pincode, 'Unknown') AS pincode, max(o.city) AS city, count(*) AS orders, coalesce(sum(o.total), 0) AS gmv FROM orders_clean o WHERE {w} AND o.is_valid GROUP BY 1 ORDER BY orders DESC, 1 LIMIT 10", a)
    hours = q(f"""SELECT extract(dow FROM o.ts_ist)::INT AS dow, extract(hour FROM o.ts_ist)::INT AS hour, count(*) AS orders FROM orders_clean o WHERE {w} AND o.is_valid GROUP BY 1, 2""", a)
    customers = q(f"""SELECT CASE WHEN o.nth_order = 1 THEN 'First order' ELSE 'Repeat order' END AS kind, count(*) AS orders, coalesce(sum(o.total), 0) AS gmv, avg(o.total) AS aov
        FROM orders_clean o WHERE {w} AND o.is_valid GROUP BY 1 ORDER BY 1""", a)
    channels = q(f"SELECT coalesce(o.channel, 'Unattributed') AS channel, count(*) AS orders, coalesce(sum(o.total), 0) AS gmv, avg(o.total) AS aov FROM orders_clean o WHERE {w} AND o.is_valid GROUP BY 1 ORDER BY orders DESC", a)
    credited = q(f"SELECT coalesce(o.credit_channel, 'Unattributed') AS channel, count(*) AS orders, coalesce(sum(o.total), 0) AS gmv, avg(o.total) AS aov FROM orders_clean o WHERE {w} AND o.is_valid GROUP BY 1 ORDER BY orders DESC", a)
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
        FROM orders_clean o WHERE {w} AND o.is_valid GROUP BY 1 ORDER BY orders DESC, 1 LIMIT 8""", a)
    return {"kpis": kpis, "prev": prev, "prev_range": pr, "dates": cur["dates"], "current": cur["m"], "prev_dates": pser["dates"] if pser else None, "previous": pser["m"] if pser else None,
            "status": status, "payment": payment, "failures": failures, "coupons": coupons, "cities": cities, "pincodes": pins, "hours": hours,
            "customers": customers, "channels": channels, "credited_channels": credited, "buckets": buckets, "delivery": delivery, "riders": riders}


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

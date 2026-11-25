"""Alerts and the weekly summary: what changed that you would want to know about, in plain language. Nothing is sent anywhere; it is shown on Home."""
from datetime import datetime, time, timedelta, timezone

from .core import app, one, q, ratio
from .overview import _kpis

IST = timezone(timedelta(hours=5, minutes=30))
LEVEL_ORDER = {"bad": 0, "warn": 1, "info": 2}


def _windows():
    """This week and the week before, ending on the latest complete day (today is still filling up)."""
    last = one("SELECT max(date_ist) AS d FROM sessions").get("d")
    if last is None:
        return None
    newest = one("SELECT max(created_at) AS t FROM raw_event_log").get("t")
    # the last day counts only when it is over: it is not today, and the data runs to late evening (a stale refresh leaves it half-filled)
    complete = last < datetime.now(IST).date() and newest is not None and newest.astimezone(IST) >= datetime.combine(last, time(22, 0), IST)
    end = last if complete else last - timedelta(days=1)
    cur = ((end - timedelta(days=6)).isoformat(), end.isoformat())
    prev = ((end - timedelta(days=13)).isoformat(), (end - timedelta(days=7)).isoformat())
    return cur, prev


def _money(x) -> str:
    return f"₹{x:,.0f}"


def _change(cur, prev, pct=True):
    if prev in (None, 0):
        return ""
    if pct:
        d = (cur - prev) / prev * 100
        return f" ({d:+.0f}%)"
    return f" ({cur - prev:+d})"


def _alert(level, title, detail, tab, **prefill):
    return {"level": level, "title": title, "detail": detail, "tab": tab, "prefill": prefill}


@app.get("/api/alerts")
def alerts():
    """Things that changed this week and need a look, worst first. Based on the last 7 complete days against the 7 before."""
    win = _windows()
    if not win:
        return {"alerts": [], "range": None}
    (c0, c1), (p0, p1) = win
    k, p = _kpis(c0, c1, False), _kpis(p0, p1, False)
    out = []

    # tracking quiet: a day far below a normal day usually means tracking broke, not that people disappeared
    typical = one("""SELECT median(n) AS med FROM (SELECT count(*) AS n FROM sessions WHERE NOT is_excluded AND date_ist BETWEEN ?::DATE - 28 AND ?::DATE - 1 GROUP BY date_ist)""", [c0, c0])
    med = (typical or {}).get("med") or 0
    if med >= 50:
        for r in q("SELECT date_ist AS d, count(*) AS n FROM sessions WHERE NOT is_excluded AND date_ist BETWEEN ? AND ? GROUP BY 1 ORDER BY 1 DESC", [c0, c1]):
            if r["n"] < 0.25 * med:
                out.append(_alert("bad", f"Tracking may have stopped on {r['d']:%d %b}", f"Only {r['n']} visits were recorded, against about {med:.0f} on a normal day. "
                                  "If the site was up, tracking broke and that day's numbers are too low.", "data"))
                break

    # fewer orders
    if p["orders"] >= 5 and k["orders"] <= 0.5 * p["orders"]:
        out.append(_alert("bad", "Orders fell sharply", f"{k['orders']} orders this week against {p['orders']} the week before{_change(k['revenue'], p['revenue'])} in revenue.", "orders"))

    # lower add-to-cart rate
    if k["sessions"] >= 300 and p["sessions"] >= 300 and p["cart_rate"] and k["cart_rate"] < 0.7 * p["cart_rate"]:
        out.append(_alert("warn", "Fewer visitors are adding to cart", f"Add-to-cart rate is {k['cart_rate'] * 100:.1f}% this week, down from {p['cart_rate'] * 100:.1f}%.", "funnel"))

    # failed online payments
    pay = one("""SELECT count(*) FILTER (WHERE upper(coalesce(payment_method, '')) NOT LIKE 'COD%') AS online,
                 count(*) FILTER (WHERE upper(coalesce(payment_method, '')) NOT LIKE 'COD%' AND status = 'payment_cancelled') AS cancelled
                 FROM orders_clean WHERE NOT is_test AND NOT is_excluded AND date_ist BETWEEN ? AND ?""", [c0, c1])
    if pay["online"] >= 6 and pay["cancelled"] / pay["online"] >= 0.5:
        out.append(_alert("warn", "Many online payments are failing", f"{pay['cancelled']} of {pay['online']} online payment attempts were cancelled this week ({pay['cancelled'] / pay['online'] * 100:.0f}%). "
                          "Check the payment page and the failure reasons.", "orders"))

    # sales without confirmed payment
    risk = one("""SELECT count(*) AS n, coalesce(sum(total), 0) AS v FROM orders_clean WHERE is_valid AND NOT is_excluded
                  AND payment_state IN ('unconfirmed', 'conflicting') AND date_ist >= ?::DATE - 30""", [c1])
    if risk["n"]:
        out.append(_alert("warn", f"{risk['n']} recent sale{'s' if risk['n'] != 1 else ''} without a confirmed payment", f"Worth {_money(risk['v'])} in the last 30 days. They are counted as sales; check them before trusting revenue.", "orders"))

    # Meta spend against what came back
    spend = one("SELECT coalesce(sum(spend), 0) AS s FROM raw_meta_insights WHERE date BETWEEN ? AND ?", [c0, c1]).get("s") or 0
    if spend >= 500:
        mo = one("SELECT count(*) AS n, coalesce(sum(revenue), 0) AS r FROM orders_clean WHERE is_valid AND NOT is_excluded AND credit_channel = 'Paid Meta' AND date_ist BETWEEN ? AND ?", [c0, c1])
        if mo["n"] == 0:
            out.append(_alert("bad", "Meta spend with no orders", f"{_money(spend)} was spent on Meta ads this week and no order is credited to Paid Meta.", "meta"))
        elif mo["r"] / spend < 0.5:
            out.append(_alert("warn", "Meta ads are not paying back yet", f"{_money(spend)} spent this week; {mo['n']} order{'s' if mo['n'] != 1 else ''} worth {_money(mo['r'])} credited to Paid Meta, "
                              f"about ₹{mo['r'] / spend:.2f} back for every ₹1 spent.", "meta"))

    # ad links that cannot be told apart
    u = one("""SELECT count(*) FILTER (WHERE channel = 'Paid Meta') AS meta,
               count(*) FILTER (WHERE channel = 'Paid Meta' AND session_id NOT IN (SELECT session_id FROM session_meta)) AS unmatched,
               count(*) FILTER (WHERE (channel IN ('Paid Google', 'Paid Meta', 'Paid Partner') OR has_gclid OR has_fbclid) AND campaign = '(not set)') AS untagged,
               count(*) FILTER (WHERE channel IN ('Paid Google', 'Paid Meta', 'Paid Partner') OR has_gclid OR has_fbclid) AS paid
               FROM sessions WHERE NOT is_excluded AND date_ist BETWEEN ? AND ?""", [c0, c1])
    if u["meta"] >= 100 and u["unmatched"] / u["meta"] > 0.25:
        out.append(_alert("warn", "Many Meta visits cannot be matched to a campaign", f"{u['unmatched'] / u['meta'] * 100:.0f}% of this week's Paid Meta visits use a campaign name Meta does not recognise, so their spend and orders cannot be joined.", "campaigns"))
    elif u["paid"] >= 100 and u["untagged"] / u["paid"] > 0.3:
        out.append(_alert("warn", "Many paid visits have no campaign name", f"{u['untagged'] / u['paid'] * 100:.0f}% of this week's paid visits carry no campaign tag.", "campaigns"))

    # people you can still reach (opportunity, not a problem)
    wait = one("""SELECT count(DISTINCT person_key) AS n FROM (SELECT coalesce(s.user_id, s.visitor_key) AS person_key, c.phone10 FROM checkout c JOIN sessions s USING (session_id)
                  WHERE NOT s.is_excluded AND c.outcome IN ('checkout_abandoned', 'payment_abandoned') AND c.phone10 IS NOT NULL AND c.checkout_at >= (SELECT max(created_at) FROM raw_event_log) - INTERVAL 48 HOUR)
                  WHERE person_key NOT IN (SELECT user_id FROM orders_clean WHERE is_valid AND user_id IS NOT NULL)""")
    if wait["n"]:
        out.append(_alert("info", f"{wait['n']} people reached checkout in the last 2 days and did not buy", "They left a phone number, so you can follow up while the interest is fresh.", "audiences"))

    # a competitor cut the price of one of our sellers (between its last two price readings), and is now cheaper than us
    try:
        from .prices import _changes, price_catalogue
        sold = {r["product_id"] for r in q("""SELECT DISTINCT product_id FROM order_lines WHERE is_valid AND NOT is_excluded AND date_ist >= ?::DATE - 30""", [c1])} \
            if q("SELECT 1 FROM information_schema.tables WHERE table_name = 'order_lines'") else set()
        cuts = [c for c in _changes(200) if c["change"] is not None and c["change"] <= -0.05 and c["product_id"] in sold and c["our_price"] and c["now_price"] < c["our_price"]]
        if cuts and price_catalogue():
            top = cuts[0]
            out.append(_alert("warn", f"{top['site_label']} cut the price of {top['name']}" + (f" and {len(cuts) - 1} more of our sellers" if len(cuts) > 1 else ""),
                              f"Now {_money(top['now_price'])} (was {_money(top['before_price'])}, {top['change'] * 100:.0f}%), against our {_money(top['our_price'])}.", "prices"))
    except Exception:  # price tables not built yet, or the sheet still has the old columns: no price alert
        pass
    out.sort(key=lambda a: LEVEL_ORDER[a["level"]])
    return {"alerts": out, "range": {"from": c0, "to": c1}, "previous": {"from": p0, "to": p1}}


@app.get("/api/digest")
def digest():
    """The week at a glance: this week against the week before, as numbers and as text you can paste into a message."""
    win = _windows()
    if not win:
        return {"lines": [], "text": ""}
    (c0, c1), (p0, p1) = win
    k, p = _kpis(c0, c1, False), _kpis(p0, p1, False)
    rows = q("""SELECT channel, count(*) AS sessions FROM sessions WHERE NOT is_excluded AND date_ist BETWEEN ? AND ? GROUP BY 1 ORDER BY 2 DESC, 1""", [c0, c1])
    by_order = q("""SELECT coalesce(credit_channel, 'Unknown') AS channel, count(*) AS orders, coalesce(sum(revenue), 0) AS revenue FROM orders_clean
                    WHERE is_valid AND NOT is_excluded AND date_ist BETWEEN ? AND ? GROUP BY 1 ORDER BY 2 DESC, 1""", [c0, c1])
    fmt = lambda s: datetime.fromisoformat(s).strftime("%d %b")
    lines = [
        f"Visits {k['sessions']:,}{_change(k['sessions'], p['sessions'])}",
        f"Added to cart {k['cart_rate'] * 100:.1f}% of visits (before: {p['cart_rate'] * 100:.1f}%)",
        f"Orders {k['orders']}{_change(k['orders'], p['orders'], pct=False)} worth {_money(k['revenue'])}{_change(k['revenue'], p['revenue'])}",
    ]
    if k["orders"]:
        lines.append(f"Average order {_money(k['aov'])}" + (f" (before: {_money(p['aov'])})" if p["orders"] else ""))
    if rows:
        lines.append(f"Most visits came from {rows[0]['channel']} ({rows[0]['sessions']:,})")
    if by_order:
        lines.append(f"Most orders came from {by_order[0]['channel']} ({by_order[0]['orders']})")
    spend = one("SELECT coalesce(sum(spend), 0) AS s FROM raw_meta_insights WHERE date BETWEEN ? AND ?", [c0, c1]).get("s") or 0
    if spend:
        mo = next((r for r in by_order if r["channel"] == "Paid Meta"), {"orders": 0, "revenue": 0})
        lines.append(f"Meta ads: {_money(spend)} spent, {mo['orders']} order{'s' if mo['orders'] != 1 else ''} credited ({_money(mo['revenue'])})")
    for a in alerts()["alerts"][:3]:
        lines.append(("Watch out: " if a["level"] != "info" else "Opportunity: ") + a["title"])
    head = f"Week {fmt(c0)} to {fmt(c1)} compared with {fmt(p0)} to {fmt(p1)}"
    return {"range": {"from": c0, "to": c1}, "previous": {"from": p0, "to": p1}, "head": head, "lines": lines,
            "text": head + "\n" + "\n".join("• " + line for line in lines),
            "kpis": {"sessions": k["sessions"], "orders": k["orders"], "revenue": k["revenue"], "cart_rate": k["cart_rate"]},
            "previous_kpis": {"sessions": p["sessions"], "orders": p["orders"], "revenue": p["revenue"], "cart_rate": p["cart_rate"]}}

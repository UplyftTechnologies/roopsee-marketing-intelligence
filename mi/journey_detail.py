"""Journeys › "More detail" under a journey: the facts that are not a funnel step, moved here from the old Deeper analysis tab.

purchase   what led up to each customer's first order (visits, days, first channel and landing page)
search     the search terms, searches per day, where people searched, filters and sorting, and searchers against other browsers
quiz       where the quiz loses people (by question), the result / concern / skin type they got, and the time from the quiz to an order
checkout   how long it takes from tapping pay to a confirmed order

The funnels themselves are on the journey (mi/journeys.py); nothing here repeats them. Visits follow the global filters like every page.
The per-visit tables used here (discovery_events, quiz_sessions, quiz_steps, pay_sessions, session_concerns) are built by mi/deeper_sql.py.
"""
from statistics import median

from fastapi import HTTPException

from .core import app, one, q, ratio, sess_where
from .sessions import FLAG_ORDER

SESS = "FROM sessions s LEFT JOIN session_orders o ON o.session_id = s.session_id"
DETAIL = ("purchase", "search", "quiz", "checkout")


def _have(*tables) -> bool:
    got = {r["table_name"] for r in q("SELECT table_name FROM information_schema.tables")}
    return all(t in got for t in tables)


def _med(vals):
    vals = [v for v in vals if v is not None]
    return round(median(vals), 1) if vals else None


def _bucket(x, edges):
    return next((lbl for lim, lbl in edges if x <= lim), edges[-1][1])


# ---------------------------------------------------------------- purchase
def first_orders(d_from, d_to, include_excluded) -> dict:
    """Every customer's first valid order in the dates, and the visits before it."""
    ex = "" if include_excluded else " AND NOT is_excluded"
    ob = q(f"""WITH o AS (SELECT order_id, user_id, ts FROM orders_clean WHERE is_valid{ex} AND nth_order = 1 AND user_id IS NOT NULL AND date_ist BETWEEN ? AND ?)
               SELECT o.order_id, count(*) AS visits, epoch(o.ts - min(s.started_at)) / 86400.0 AS days, arg_min(s.channel, s.started_at) AS first_channel,
                      arg_min(s.landing_type, s.started_at) AS first_landing, count(DISTINCT s.channel) AS channels
               FROM o JOIN sessions s ON s.user_id = o.user_id AND s.started_at <= o.ts GROUP BY o.order_id, o.ts""", [d_from or "2000-01-01", d_to or "2999-12-31"])
    vb = {"1 visit": 0, "2 visits": 0, "3 visits": 0, "4+ visits": 0}
    db = {"Same day": 0, "1 to 3 days": 0, "4 to 7 days": 0, "8 to 30 days": 0, "Over 30 days": 0}
    ch: dict = {}
    land: dict = {}
    for r in ob:
        vb[_bucket(r["visits"], [(1, "1 visit"), (2, "2 visits"), (3, "3 visits"), (10 ** 9, "4+ visits")])] += 1
        db[_bucket(r["days"], [(1, "Same day"), (3, "1 to 3 days"), (7, "4 to 7 days"), (30, "8 to 30 days"), (10 ** 9, "Over 30 days")])] += 1
        c = ch.setdefault(r["first_channel"] or "Unknown", {"name": r["first_channel"] or "Unknown", "orders": 0, "visits": []})
        c["orders"] += 1
        c["visits"].append(r["visits"])
        land[r["first_landing"] or "other"] = land.get(r["first_landing"] or "other", 0) + 1
    return {"orders": len(ob), "median_visits": _med([r["visits"] for r in ob]), "median_days": _med([r["days"] for r in ob]),
            "multi_channel": sum(1 for r in ob if r["channels"] > 1),
            "visits": [{"name": k, "count": v} for k, v in vb.items()], "days": [{"name": k, "count": v} for k, v in db.items()],
            "first_channel": sorted([{"name": c["name"], "orders": c["orders"], "median_visits": _med(c["visits"])} for c in ch.values()], key=lambda x: -x["orders"]),
            "first_landing": sorted([{"name": k, "count": v} for k, v in land.items()], key=lambda x: -x["count"])}


# ---------------------------------------------------------------- search
def search_detail(d_from, d_to, include_excluded) -> dict:
    w, a = sess_where(d_from, d_to, include_excluded)
    d = f"FROM discovery_events d JOIN sessions s ON s.session_id = d.session_id WHERE {w}"
    k = one(f"""SELECT count(*) FILTER (WHERE d.kind = 'search') AS searches, count(*) FILTER (WHERE d.kind = 'search' AND d.results = 0) AS zero_searches,
                count(*) FILTER (WHERE d.kind = 'no_results') AS no_result_events, count(DISTINCT d.session_id) FILTER (WHERE d.kind = 'result_click') AS click_sessions,
                count(DISTINCT d.session_id) FILTER (WHERE d.kind = 'search_abandon') AS abandon_sessions,
                count(DISTINCT d.session_id) FILTER (WHERE d.kind IN ('filter', 'sort', 'apply_filters')) AS filter_sessions {d}""", a)
    searched = "s.session_id IN (SELECT session_id FROM discovery_events WHERE kind = 'search')"
    cmp = one(f"""SELECT count(*) FILTER (WHERE {searched}) AS searchers, count(*) FILTER (WHERE {searched} AND {FLAG_ORDER}) AS searchers_ordered,
                  count(*) FILTER (WHERE {searched} AND s.f_cart) AS searchers_carted, count(*) FILTER (WHERE NOT {searched} AND s.f_product) AS others,
                  count(*) FILTER (WHERE NOT {searched} AND s.f_product AND {FLAG_ORDER}) AS others_ordered, count(*) FILTER (WHERE NOT {searched} AND s.f_product AND s.f_cart) AS others_carted
                  {SESS} WHERE {w}""", a)
    terms = q(f"""WITH t AS (SELECT d.term, d.session_id, d.kind, d.results {d} AND d.term IS NOT NULL AND d.term <> ''),
                  ord AS (SELECT s.session_id, ({FLAG_ORDER}) AS ordered {SESS} WHERE {w})
                  SELECT t.term, count(*) FILTER (WHERE t.kind = 'search') AS searches, count(DISTINCT t.session_id) AS sessions,
                         avg(t.results) FILTER (WHERE t.kind = 'search') AS avg_results, count(*) FILTER (WHERE t.kind = 'search' AND t.results = 0) AS zero,
                         count(*) FILTER (WHERE t.kind = 'no_results') AS no_result_events, count(*) FILTER (WHERE t.kind = 'result_click') AS clicks,
                         count(DISTINCT t.session_id) FILTER (WHERE ord.ordered) AS ordered_sessions
                  FROM t LEFT JOIN ord ON ord.session_id = t.session_id GROUP BY 1 HAVING count(*) FILTER (WHERE t.kind IN ('search', 'no_results')) > 0
                  ORDER BY searches DESC, no_result_events DESC, 1 LIMIT 60""", [*a, *a])
    for r in terms:
        n = r["searches"] + r["no_result_events"]
        r["zero_share"] = ratio(r["zero"] + r["no_result_events"], n) if n else 0
        r["avg_results"] = round(r["avg_results"], 1) if r["avg_results"] is not None else None
    by_source = q(f"""SELECT coalesce(d.source, '(not recorded)') AS source, count(*) FILTER (WHERE d.kind = 'search') AS searches, count(*) FILTER (WHERE d.kind = 'search' AND d.results = 0) AS zero,
                      count(*) FILTER (WHERE d.kind = 'no_results') AS no_result_events {d} AND d.kind IN ('search', 'no_results') GROUP BY 1 ORDER BY 2 DESC, 1""", a)
    filters = q(f"""SELECT d.kind, coalesce(d.value, '(none)') AS value, count(*) AS uses, count(DISTINCT d.session_id) AS sessions {d} AND d.kind IN ('filter', 'sort', 'apply_filters')
                    GROUP BY 1, 2 ORDER BY uses DESC, 1, 2 LIMIT 40""", a)
    daily = q(f"""SELECT s.date_ist AS day, count(*) FILTER (WHERE d.kind = 'search') AS searches, count(*) FILTER (WHERE d.kind = 'no_results') AS no_results {d} AND d.kind IN ('search', 'no_results')
                  GROUP BY 1 ORDER BY 1""", a)
    return {"kpis": {**k, "searcher_cart_rate": ratio(cmp["searchers_carted"], cmp["searchers"]), "searcher_order_rate": ratio(cmp["searchers_ordered"], cmp["searchers"]),
                     "other_cart_rate": ratio(cmp["others_carted"], cmp["others"]), "other_order_rate": ratio(cmp["others_ordered"], cmp["others"])},
            "terms": terms, "by_source": by_source, "filters": filters, "daily": daily}


# ---------------------------------------------------------------- quiz
def quiz_detail(d_from, d_to, include_excluded) -> dict:
    w, a = sess_where(d_from, d_to, include_excluded)
    qs = f"FROM quiz_sessions z JOIN sessions s ON s.session_id = z.session_id LEFT JOIN session_orders o ON o.session_id = s.session_id WHERE {w}"
    steps = q(f"""SELECT st.step, max(st.question) AS question, count(DISTINCT st.session_id) AS sessions FROM quiz_steps st JOIN sessions s ON s.session_id = st.session_id WHERE {w}
                  GROUP BY 1 ORDER BY 1""", a)
    drops = q(f"SELECT z.drop_step AS step, count(*) AS sessions {qs} AND z.drop_step IS NOT NULL AND NOT z.completed GROUP BY 1 ORDER BY 1", a)
    prog = q(f"""SELECT coalesce(z.program, '(none picked)') AS name, count(*) AS sessions, count(*) FILTER (WHERE s.f_cart) AS carted, count(*) FILTER (WHERE {FLAG_ORDER}) AS ordered
                 {qs} AND z.completed GROUP BY 1 ORDER BY 2 DESC LIMIT 12""", a)
    skin = q(f"SELECT coalesce(z.skin_type, '(not given)') AS name, count(*) AS sessions, count(*) FILTER (WHERE {FLAG_ORDER}) AS ordered {qs} AND z.completed GROUP BY 1 ORDER BY 2 DESC LIMIT 8", a)
    conc = q(f"""SELECT c.concern AS name, count(DISTINCT c.session_id) AS sessions, count(DISTINCT c.session_id) FILTER (WHERE s.f_cart) AS carted,
                 count(DISTINCT c.session_id) FILTER (WHERE {FLAG_ORDER}) AS ordered
                 FROM session_concerns c JOIN sessions s ON s.session_id = c.session_id LEFT JOIN session_orders o ON o.session_id = s.session_id WHERE {w} AND c.source = 'quiz'
                 GROUP BY 1 ORDER BY 2 DESC LIMIT 10""", a)
    lag = q("""WITH z AS (SELECT sp.person_key, min(zz.done_ts) AS done_ts FROM quiz_sessions zz JOIN sessions s ON s.session_id = zz.session_id JOIN sessions_person sp ON sp.session_id = s.session_id
                          WHERE zz.completed AND s.date_ist BETWEEN ? AND ? AND (? OR NOT s.is_excluded) GROUP BY 1)
               SELECT z.person_key, epoch(min(o.ts) - z.done_ts) / 3600.0 AS hours FROM z JOIN orders_clean o ON o.user_id = z.person_key AND o.is_valid AND o.ts >= z.done_ts GROUP BY 1, z.done_ts""",
            [d_from or "2000-01-01", d_to or "2999-12-31", include_excluded])
    hrs = [r["hours"] for r in lag]
    edges = [(1, "Within an hour"), (24, "Within a day"), (168, "Within a week"), (10 ** 9, "Later")]
    lagb = {n: 0 for _, n in edges}
    for h in hrs:
        lagb[_bucket(h, edges)] += 1
    return {"steps": steps, "drops": drops, "programs": prog, "skin_types": skin, "concerns": conc,
            "quiz_to_order": {"people": len(hrs), "median_hours": _med(hrs), "buckets": [{"name": k, "count": v} for k, v in lagb.items()]}}


# ---------------------------------------------------------------- checkout
def pay_timing(d_from, d_to, include_excluded) -> dict:
    """How long it takes from tapping pay to a confirmed order (the pay steps themselves are on the Checkout journey)."""
    w, a = sess_where(d_from, d_to, include_excluded)
    ps = f"FROM pay_sessions p JOIN sessions s ON s.session_id = p.session_id WHERE {w}"
    secs = q(f"""SELECT epoch(p.t_order - p.t_pay) AS secs, p.popup_s,
                 CASE WHEN coalesce(p.payment_method, '') IN ('cod', '') AND p.t_window IS NULL THEN 'Cash on delivery' ELSE 'Online' END AS method
                 {ps} AND p.t_pay IS NOT NULL AND p.t_order IS NOT NULL AND p.t_order >= p.t_pay""", a)
    sb = {"Under 10 s": 0, "10 to 30 s": 0, "30 s to 1 min": 0, "1 to 3 min": 0, "Over 3 min": 0}
    by_method: dict = {}
    for r in secs:
        x = r["secs"]
        sb["Under 10 s" if x < 10 else "10 to 30 s" if x < 30 else "30 s to 1 min" if x < 60 else "1 to 3 min" if x < 180 else "Over 3 min"] += 1
        by_method.setdefault(r["method"], []).append(x)
    conf = one("""SELECT count(*) FILTER (WHERE payment_state = 'confirmed') AS confirmed, count(*) AS orders, median(epoch(paid_at - ts)) FILTER (WHERE paid_at IS NOT NULL) AS median_paid_s,
                  quantile_cont(epoch(paid_at - ts), 0.9) FILTER (WHERE paid_at IS NOT NULL) AS p90_paid_s, count(*) FILTER (WHERE paid_at IS NOT NULL) AS online_paid
                  FROM orders_clean WHERE is_valid AND date_ist BETWEEN ? AND ? AND (? OR NOT is_excluded)""", [d_from or "2000-01-01", d_to or "2999-12-31", include_excluded])
    return {"timed": len(secs), "median_seconds": _med([r["secs"] for r in secs]), "popup_median_s": _med([r["popup_s"] for r in secs]),
            "buckets": [{"name": k, "count": v} for k, v in sb.items()],
            "by_method": [{"name": k, "orders": len(v), "median_seconds": _med(v)} for k, v in by_method.items()], "orders": conf}


NEEDS = {"purchase": (), "search": ("discovery_events",), "quiz": ("quiz_sessions", "quiz_steps", "session_concerns", "sessions_person"), "checkout": ("pay_sessions",)}
BUILD = {"purchase": first_orders, "search": search_detail, "quiz": quiz_detail, "checkout": pay_timing}


@app.get("/api/journeys/detail")
def journeys_detail(journey: str, date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False):
    """The "More detail" section of a journey (see the module docstring for what each holds)."""
    if journey not in DETAIL:
        raise HTTPException(400, f"journey must be one of {list(DETAIL)}")
    if not _have(*NEEDS[journey]):
        return {"ready": False, "journey": journey}
    return {"ready": True, "journey": journey, **{journey: BUILD[journey](date_from, date_to, include_excluded)}}

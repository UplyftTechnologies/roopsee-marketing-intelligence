"""Deeper analysis: postmortems that go below the headline numbers.

journeys   the paths people take before an order, and a visual postmortem of the ads and landing products that brought visits
discovery  search, searches with no result, filters and sorting
quiz       skin quiz to purchase, and pay tap to order confirmation
flow       ad -> skin concern -> products
chain      the journey builder: pick an event, then the events that follow, event after event
segments   people labels (quiz users, makeup users, price range, discount checkers ...)

Visits, events and orders follow the global date range, "hide internal traffic" and the device filter like every other page.
The per-visit facts these use are tables built by the rebuild (mi/deeper_sql.py); the label and concern definitions are in mi/deeper_defs.py.
"""
import re
from datetime import date
from statistics import median

from fastapi import HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse

from . import deeper_defs as D
from .config import DATA_DIR
from .core import app, one, q, ratio, sess_where, untracked_sales
from .people import _users_where
from .sessions import FLAG_ORDER

AD_DIR = DATA_DIR / "ad_images"
SESS = "FROM sessions s LEFT JOIN session_orders o ON o.session_id = s.session_id"


def _uw(d_from, d_to, include_excluded):
    """The Users-tab date / hidden-traffic condition, written for users_360 aliased as u."""
    w, a = _users_where(d_from, d_to, include_excluded)
    return w.replace("first_seen", "u.first_seen").replace("last_seen", "u.last_seen").replace("is_excluded", "u.is_excluded"), a


def _have(table: str) -> bool:
    return bool(q("SELECT 1 FROM information_schema.tables WHERE table_name = ?", [table]))


def _ready(*tables) -> bool:
    return all(_have(t) for t in tables)


def _med(vals):
    vals = [v for v in vals if v is not None]
    return round(median(vals), 1) if vals else None


def _image_of(images):
    """The first image address in a product's image list (stored as JSON)."""
    import json
    try:
        v = json.loads(images) if isinstance(images, str) else images
    except Exception:
        return None
    return v[0] if isinstance(v, list) and v else None


def ad_image_url(ad_id: str):
    return f"/api/ad-image/{ad_id}" if (AD_DIR / f"{ad_id}.jpg").exists() else None


@app.get("/api/ad-image/{ad_id}")
def ad_image(ad_id: str):
    """The picture of a Meta ad: the copy saved on this computer, else Meta's own thumbnail link."""
    if not re.fullmatch(r"\d{5,30}", ad_id):
        raise HTTPException(400, "bad ad id")
    f = AD_DIR / f"{ad_id}.jpg"
    if f.exists():
        return FileResponse(f, headers={"Cache-Control": "max-age=86400"})
    e = one("SELECT coalesce(image_url, thumbnail_url) AS u FROM raw_meta_entities WHERE entity_type = 'ad' AND entity_id = ?", [ad_id])
    if e.get("u"):
        return RedirectResponse(e["u"])
    raise HTTPException(404, "no image for this ad")


# ================================================================== 1. pre-order journeys + ad / product postmortem
def _card_stats(r: dict, base: dict) -> dict:
    s = r["sessions"] or 0
    out = {**r, "bounce_rate": ratio(r["bounced"], s), "product_rate": ratio(r["product"], s), "cart_rate": ratio(r["carts"], s), "checkout_rate": ratio(r["checkouts"], s),
           "order_rate": ratio(r["orders"], s), "pain_rate": ratio(r["pain"], s), "avg_duration": round(r["avg_duration"] or 0, 1)}
    notes = []
    if s >= 30:
        if out["bounce_rate"] >= base["bounce_rate"] + 0.12:
            notes.append(f"{out['bounce_rate'] * 100:.0f}% left without doing anything, against {base['bounce_rate'] * 100:.0f}% for comparable visits.")
        if r["carts"] == 0 and s >= 50:
            notes.append(f"Nobody added to the cart from {s:,} visits.")
        elif r["carts"] and out["checkout_rate"] < 0.3 * out["cart_rate"]:
            notes.append("People add to the cart but few reach checkout.")
        if out["pain_rate"] >= 0.3:
            notes.append(f"{out['pain_rate'] * 100:.0f}% of visits hit a slow or broken moment.")
        if base["cart_rate"] and out["cart_rate"] >= 1.5 * base["cart_rate"] and r["carts"] >= 3:
            notes.append(f"Adds to cart {out['cart_rate'] / base['cart_rate']:.1f}x more often than comparable visits: worth more budget.")
        if r["orders"]:
            notes.append(f"{r['orders']} order{'s' if r['orders'] != 1 else ''} worth ₹{r['revenue']:,.0f}.")
    out["notes"] = notes
    out["verdict"] = ("Ordering" if r["orders"] else "No carts" if (r["carts"] == 0 and s >= 100) else "High bounce" if (s >= 50 and out["bounce_rate"] >= base["bounce_rate"] + 0.15)
                      else "Promising" if r["carts"] else "Too early")
    return out


@app.get("/api/deeper/journeys")
def deeper_journeys(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False):
    if not _ready("session_attrib", "session_landing_product", "pain_sessions"):
        return {"ready": False}
    w, a = sess_where(date_from, date_to, include_excluded)
    # 1. the most common paths (the key actions of each visit, in order)
    paths = q(f"""SELECT s.key_events AS path, count(*) AS sessions, count(*) FILTER (WHERE {FLAG_ORDER}) AS ordered {SESS} WHERE {w} AND s.key_events IS NOT NULL
                  GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 25""", a)
    tot = one(f"SELECT count(*) AS sessions, count(*) FILTER (WHERE s.key_events IS NULL) AS browse_only, count(*) FILTER (WHERE {FLAG_ORDER}) AS ordered {SESS} WHERE {w}", a)
    # 2. what led up to the first order: visits, days, first channel and landing
    ob = q("""WITH o AS (SELECT order_id, user_id, ts, total FROM orders_clean WHERE is_valid AND NOT is_excluded AND nth_order = 1 AND user_id IS NOT NULL AND date_ist BETWEEN ? AND ?),
              v AS (SELECT o.order_id, count(*) AS visits, epoch(o.ts - min(s.started_at)) / 86400.0 AS days, arg_min(s.channel, s.started_at) AS first_channel,
                           arg_min(s.landing_type, s.started_at) AS first_landing, count(DISTINCT s.channel) AS channels
                    FROM o JOIN sessions s ON s.user_id = o.user_id AND s.started_at <= o.ts GROUP BY o.order_id, o.ts)
              SELECT * FROM v""", [date_from or "2000-01-01", date_to or "2999-12-31"])
    n = len(ob)
    bucket = lambda x, edges: next((lbl for lim, lbl in edges if x <= lim), edges[-1][1])  # noqa: E731
    vb = {"1 visit": 0, "2 visits": 0, "3 visits": 0, "4+ visits": 0}
    db = {"Same day": 0, "1 to 3 days": 0, "4 to 7 days": 0, "8 to 30 days": 0, "Over 30 days": 0}
    ch: dict = {}
    land: dict = {}
    for r in ob:
        vb[bucket(r["visits"], [(1, "1 visit"), (2, "2 visits"), (3, "3 visits"), (10 ** 9, "4+ visits")])] += 1
        db[bucket(r["days"], [(1, "Same day"), (3, "1 to 3 days"), (7, "4 to 7 days"), (30, "8 to 30 days"), (10 ** 9, "Over 30 days")])] += 1
        c = ch.setdefault(r["first_channel"] or "Unknown", {"name": r["first_channel"] or "Unknown", "orders": 0, "visits": []})
        c["orders"] += 1
        c["visits"].append(r["visits"])
        land[r["first_landing"] or "other"] = land.get(r["first_landing"] or "other", 0) + 1
    before = {"orders": n, "median_visits": _med([r["visits"] for r in ob]), "median_days": _med([r["days"] for r in ob]), "multi_channel": sum(1 for r in ob if r["channels"] > 1),
              "visits": [{"name": k, "count": v} for k, v in vb.items()], "days": [{"name": k, "count": v} for k, v in db.items()],
              "first_channel": sorted([{"name": c["name"], "orders": c["orders"], "median_visits": _med(c["visits"])} for c in ch.values()], key=lambda x: -x["orders"]),
              "first_landing": sorted([{"name": k, "count": v} for k, v in land.items()], key=lambda x: -x["count"])}
    # 3. ads: a card per Meta ad (the ad id in the link)
    agg = ("count(*) AS sessions, count(*) FILTER (WHERE s.is_bounce) AS bounced, count(*) FILTER (WHERE s.f_product) AS product, count(*) FILTER (WHERE s.f_cart) AS carts, "
           f"count(*) FILTER (WHERE s.f_checkout) AS checkouts, count(*) FILTER (WHERE {FLAG_ORDER}) AS orders, coalesce(sum(o.order_value), 0) AS revenue, "
           "avg(s.duration_s) FILTER (WHERE s.duration_s > 0) AS avg_duration, count(*) FILTER (WHERE ps.with_problem) AS pain")
    ps = "LEFT JOIN pain_sessions ps ON ps.session_id = s.session_id"

    def base_of(r):
        s = r["sessions"] or 1
        return {"bounce_rate": r["bounced"] / s, "cart_rate": r["carts"] / s}
    meta_base = one(f"SELECT {agg} {SESS} {ps} WHERE {w} AND s.channel = 'Paid Meta'", a)
    ads_raw = q(f"""SELECT sa.ad_id, {agg} {SESS} JOIN session_attrib sa ON sa.session_id = s.session_id {ps} WHERE {w} AND s.channel = 'Paid Meta' GROUP BY 1
                    HAVING count(*) >= 5 ORDER BY sessions DESC LIMIT 36""", a)
    ids = [r["ad_id"] for r in ads_raw]
    info = {r["entity_id"]: r for r in q("SELECT entity_id, name, effective_status, campaign_id FROM raw_meta_entities WHERE entity_type = 'ad'")}
    spend = {r["ad_id"]: r for r in q("SELECT ad_id, sum(spend) AS spend, sum(link_clicks) AS clicks, sum(impressions) AS impressions FROM raw_meta_insights WHERE date BETWEEN ? AND ? GROUP BY 1",
                                      [date_from or "2000-01-01", date_to or "2999-12-31"])}
    land_mix: dict = {}
    if ids:
        for r in q(f"""SELECT sa.ad_id, s.landing_type AS lt, count(*) AS n {SESS} JOIN session_attrib sa ON sa.session_id = s.session_id WHERE {w} AND s.channel = 'Paid Meta'
                       AND sa.ad_id IN (SELECT unnest(?::VARCHAR[])) GROUP BY 1, 2""", [*a, ids]):
            land_mix.setdefault(r["ad_id"], []).append({"name": r["lt"] or "other", "count": r["n"]})
    bm = base_of(meta_base) if meta_base["sessions"] else {"bounce_rate": 0, "cart_rate": 0}
    ads = []
    for r in ads_raw:
        c = _card_stats(r, bm)
        i, sp = info.get(r["ad_id"], {}), spend.get(r["ad_id"], {})
        mix = sorted(land_mix.get(r["ad_id"], []), key=lambda x: -x["count"])
        top = mix[0] if mix else None
        if top and top["name"] == "home" and top["count"] >= 0.7 * r["sessions"] and r["sessions"] >= 30:
            c["notes"].append(f"{top['count'] / r['sessions'] * 100:.0f}% landed on the home page, not on a product.")
        c.update(name=i.get("name"), status=i.get("effective_status"), image=ad_image_url(r["ad_id"]), in_meta=bool(i), landing=mix[:3],
                 spend=float(sp.get("spend") or 0), clicks=sp.get("clicks") or 0, cost_per_order=round(float(sp["spend"]) / r["orders"], 2) if sp.get("spend") and r["orders"] else None)
        ads.append(c)
    # 4. landing products: a card per product page that visits started on
    pb = one(f"SELECT {agg} {SESS} {ps} WHERE {w} AND s.landing_type = 'product'", a)
    pbase = base_of(pb) if pb["sessions"] else {"bounce_rate": 0, "cart_rate": 0}
    prods = []
    for r in q(f"""SELECT lp.product_id, max(lp.product_name) AS name, max(lp.brand) AS brand, any_value(lp.images) AS images, {agg} {SESS}
                   JOIN session_landing_product lp ON lp.session_id = s.session_id {ps} WHERE {w} GROUP BY 1 HAVING count(*) >= 10 ORDER BY sessions DESC LIMIT 24""", a):
        c = _card_stats(r, pbase)
        c["image"] = _image_of(r["images"])
        c.pop("images", None)
        prods.append(c)
    return {"ready": True, "totals": tot, "paths": paths, "before_order": before, "ads": ads, "meta_baseline": {**bm, "sessions": meta_base["sessions"]},
            "meta_connected": bool(info), "ads_without_image": sum(1 for x in ads if not x["image"]), "products": prods, "product_baseline": {**pbase, "sessions": pb["sessions"]}}


# ================================================================== 2. product discovery
@app.get("/api/deeper/discovery")
def deeper_discovery(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False):
    if not _ready("discovery_events"):
        return {"ready": False}
    w, a = sess_where(date_from, date_to, include_excluded)
    d = f"FROM discovery_events d JOIN sessions s ON s.session_id = d.session_id WHERE {w}"
    k = one(f"""SELECT count(*) FILTER (WHERE d.kind = 'search') AS searches, count(DISTINCT d.session_id) FILTER (WHERE d.kind = 'search') AS searching_sessions,
                count(*) FILTER (WHERE d.kind = 'search' AND d.results = 0) AS zero_searches, count(*) FILTER (WHERE d.kind = 'no_results') AS no_result_events,
                count(DISTINCT d.session_id) FILTER (WHERE d.kind = 'no_results') AS no_result_sessions, count(DISTINCT d.session_id) FILTER (WHERE d.kind = 'result_click') AS click_sessions,
                count(DISTINCT d.session_id) FILTER (WHERE d.kind = 'search_abandon') AS abandon_sessions,
                count(DISTINCT d.session_id) FILTER (WHERE d.kind IN ('filter', 'sort', 'apply_filters')) AS filter_sessions {d}""", a)
    tot = one(f"SELECT count(*) AS sessions, count(*) FILTER (WHERE {FLAG_ORDER}) AS ordered {SESS} WHERE {w}", a)
    cmp = one(f"""SELECT count(*) FILTER (WHERE s.session_id IN (SELECT session_id FROM discovery_events WHERE kind = 'search')) AS searchers,
                  count(*) FILTER (WHERE s.session_id IN (SELECT session_id FROM discovery_events WHERE kind = 'search') AND {FLAG_ORDER}) AS searchers_ordered,
                  count(*) FILTER (WHERE s.session_id IN (SELECT session_id FROM discovery_events WHERE kind = 'search') AND s.f_cart) AS searchers_carted,
                  count(*) FILTER (WHERE s.session_id NOT IN (SELECT session_id FROM discovery_events WHERE kind = 'search') AND s.f_product) AS other_browsers,
                  count(*) FILTER (WHERE s.session_id NOT IN (SELECT session_id FROM discovery_events WHERE kind = 'search') AND s.f_product AND {FLAG_ORDER}) AS other_ordered,
                  count(*) FILTER (WHERE s.session_id NOT IN (SELECT session_id FROM discovery_events WHERE kind = 'search') AND s.f_product AND s.f_cart) AS other_carted
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
        r["zero_share"] = ratio(r["zero"] + r["no_result_events"], r["searches"] + r["no_result_events"]) if (r["searches"] + r["no_result_events"]) else 0
        r["click_rate"] = ratio(r["clicks"], r["searches"])
        r["avg_results"] = round(r["avg_results"], 1) if r["avg_results"] is not None else None
    missing = q(f"""SELECT d.term, count(*) AS events, count(DISTINCT d.session_id) AS sessions, max(d.ts) AS last_seen
              {d} AND d.kind = 'no_results' AND d.term IS NOT NULL AND d.term <> '' GROUP BY 1 ORDER BY events DESC, 1 LIMIT 40""", a)
    by_source = q(f"""SELECT coalesce(d.source, '(not recorded)') AS source, count(*) FILTER (WHERE d.kind = 'search') AS searches, count(*) FILTER (WHERE d.kind = 'search' AND d.results = 0) AS zero,
                      count(*) FILTER (WHERE d.kind = 'no_results') AS no_result_events {d} AND d.kind IN ('search', 'no_results') GROUP BY 1 ORDER BY 2 DESC, 1""", a)
    filters = q(f"""SELECT d.kind, coalesce(d.value, '(none)') AS value, count(*) AS uses, count(DISTINCT d.session_id) AS sessions {d} AND d.kind IN ('filter', 'sort', 'apply_filters')
                    GROUP BY 1, 2 ORDER BY uses DESC, 1, 2 LIMIT 40""", a)
    daily = q(f"""SELECT s.date_ist AS day, count(*) FILTER (WHERE d.kind = 'search') AS searches, count(*) FILTER (WHERE d.kind = 'no_results') AS no_results {d} AND d.kind IN ('search', 'no_results')
                  GROUP BY 1 ORDER BY 1""", a)
    funnel = [("Visits that searched", k["searching_sessions"]), ("Clicked a search result", k["click_sessions"]), ("Searched and added to cart", cmp["searchers_carted"]), ("Searched and ordered", cmp["searchers_ordered"])]
    return {"ready": True, "kpis": {**k, "sessions": tot["sessions"], "searcher_order_rate": ratio(cmp["searchers_ordered"], cmp["searchers"]),
                                    "other_order_rate": ratio(cmp["other_ordered"], cmp["other_browsers"]), "searcher_cart_rate": ratio(cmp["searchers_carted"], cmp["searchers"]),
                                    "other_cart_rate": ratio(cmp["other_carted"], cmp["other_browsers"])},
            "funnel": [{"name": n, "count": v} for n, v in funnel], "terms": terms, "missing": missing, "by_source": by_source, "filters": filters, "daily": daily}


# ================================================================== 3. quiz -> purchase, and pay -> confirmation
@app.get("/api/deeper/quiz")
def deeper_quiz(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False):
    if not _ready("quiz_sessions", "quiz_steps", "pay_sessions", "session_concerns"):
        return {"ready": False}
    w, a = sess_where(date_from, date_to, include_excluded)
    qs = f"FROM quiz_sessions z JOIN sessions s ON s.session_id = z.session_id LEFT JOIN session_orders o ON o.session_id = s.session_id WHERE {w}"
    f = one(f"""SELECT count(*) AS engaged, count(*) FILTER (WHERE z.completed) AS completed, count(*) FILTER (WHERE z.abandoned AND NOT z.completed) AS abandoned,
                count(*) FILTER (WHERE z.completed AND s.f_cart) AS completed_carted, count(*) FILTER (WHERE z.completed AND s.f_checkout) AS completed_checkout,
                count(*) FILTER (WHERE z.completed AND {FLAG_ORDER}) AS completed_ordered, count(*) FILTER (WHERE NOT z.completed AND s.f_cart) AS other_carted,
                count(*) FILTER (WHERE NOT z.completed AND {FLAG_ORDER}) AS other_ordered {qs}""", a)
    base = one(f"""SELECT count(*) AS sessions, count(*) FILTER (WHERE s.f_cart) AS carted, count(*) FILTER (WHERE {FLAG_ORDER}) AS ordered {SESS}
                   WHERE {w} AND s.session_id NOT IN (SELECT session_id FROM quiz_sessions)""", a)
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
    # time from finishing the quiz to the first order that followed
    lag = q("""WITH z AS (SELECT sp.person_key, min(zz.done_ts) AS done_ts FROM quiz_sessions zz JOIN sessions s ON s.session_id = zz.session_id JOIN sessions_person sp ON sp.session_id = s.session_id
                          WHERE zz.completed AND s.date_ist BETWEEN ? AND ? AND (? OR NOT s.is_excluded) GROUP BY 1)
               SELECT z.person_key, epoch(min(o.ts) - z.done_ts) / 3600.0 AS hours FROM z JOIN orders_clean o ON o.user_id = z.person_key AND o.is_valid AND o.ts >= z.done_ts GROUP BY 1, z.done_ts""",
              [date_from or "2000-01-01", date_to or "2999-12-31", include_excluded])
    hrs = [r["hours"] for r in lag]
    edges = [(1, "Within an hour"), (24, "Within a day"), (168, "Within a week"), (10 ** 9, "Later")]
    lagb = {n: 0 for _, n in edges}
    for h in hrs:
        lagb[next(n for lim, n in edges if h <= lim)] += 1
    # pay tap -> confirmed
    ps = f"FROM pay_sessions p JOIN sessions s ON s.session_id = p.session_id WHERE {w}"
    pf = one(f"""SELECT count(p.t_pay) AS tapped, count(p.t_started) AS started, count(p.t_window) AS window, count(p.t_paid) AS paid, count(p.t_order) AS confirmed,
                 count(*) FILTER (WHERE p.t_pay IS NOT NULL AND p.t_order IS NULL) AS dropped {ps}""", a)
    secs = q(f"SELECT epoch(p.t_order - p.t_pay) AS secs, p.popup_s, CASE WHEN coalesce(p.payment_method, '') IN ('cod', '') AND p.t_window IS NULL THEN 'Cash on delivery' ELSE 'Online' END AS method {ps} AND p.t_pay IS NOT NULL AND p.t_order IS NOT NULL AND p.t_order >= p.t_pay", a)
    sb = {"Under 10 s": 0, "10 to 30 s": 0, "30 s to 1 min": 0, "1 to 3 min": 0, "Over 3 min": 0}
    for r in secs:
        x = r["secs"]
        sb["Under 10 s" if x < 10 else "10 to 30 s" if x < 30 else "30 s to 1 min" if x < 60 else "1 to 3 min" if x < 180 else "Over 3 min"] += 1
    by_method = {}
    for r in secs:
        by_method.setdefault(r["method"], []).append(r["secs"])
    conf = one("""SELECT count(*) FILTER (WHERE payment_state = 'confirmed') AS confirmed, count(*) AS orders, median(epoch(paid_at - ts)) FILTER (WHERE paid_at IS NOT NULL) AS median_paid_s,
                  quantile_cont(epoch(paid_at - ts), 0.9) FILTER (WHERE paid_at IS NOT NULL) AS p90_paid_s, count(*) FILTER (WHERE paid_at IS NOT NULL) AS online_paid
                  FROM orders_clean WHERE is_valid AND date_ist BETWEEN ? AND ? AND (? OR NOT is_excluded)""", [date_from or "2000-01-01", date_to or "2999-12-31", include_excluded])
    return {"ready": True, "funnel": f, "baseline": base, "steps": steps, "drops": drops, "programs": prog, "skin_types": skin, "concerns": conc,
            "quiz_to_order": {"people": len(hrs), "median_hours": _med(hrs), "buckets": [{"name": k, "count": v} for k, v in lagb.items()]},
            "pay": {"funnel": pf, "median_seconds": _med([r["secs"] for r in secs]), "popup_median_s": _med([r["popup_s"] for r in secs]), "buckets": [{"name": k, "count": v} for k, v in sb.items()],
                    "by_method": [{"name": k, "orders": len(v), "median_seconds": _med(v)} for k, v in by_method.items()], "orders": conf}}


# ================================================================== 4. ad -> concern -> products
@app.get("/api/deeper/flow")
def deeper_flow(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False):
    if not _ready("session_attrib", "session_concerns", "session_products"):
        return {"ready": False}
    w, a = sess_where(date_from, date_to, include_excluded)
    base = f"""WITH b AS (SELECT s.session_id, sa.ad_id, ({FLAG_ORDER}) AS ordered {SESS} JOIN session_attrib sa ON sa.session_id = s.session_id WHERE {w} AND s.channel = 'Paid Meta'),
               qc AS (SELECT session_id, concern, 'quiz' AS source FROM session_concerns WHERE source = 'quiz' GROUP BY 1, 2),
               ic AS (SELECT session_id, concern, 'inferred' AS source FROM session_concerns WHERE source = 'inferred' AND session_id NOT IN (SELECT session_id FROM qc) GROUP BY 1, 2),
               c AS (SELECT * FROM qc UNION ALL SELECT * FROM ic)"""
    ads = q(f"""{base} SELECT b.ad_id, count(*) AS sessions, count(*) FILTER (WHERE b.session_id IN (SELECT session_id FROM c)) AS with_concern, count(*) FILTER (WHERE b.ordered) AS orders
                FROM b GROUP BY 1 HAVING count(*) >= 5 ORDER BY 2 DESC LIMIT 12""", a)
    ids = [r["ad_id"] for r in ads]
    if not ids:
        return {"ready": True, "ads": [], "concerns": [], "edges": [], "products": []}
    info = {r["entity_id"]: r["name"] for r in q("SELECT entity_id, name FROM raw_meta_entities WHERE entity_type = 'ad'")}
    for r in ads:
        r["name"], r["image"] = info.get(r["ad_id"]), ad_image_url(r["ad_id"])
    ad_c = q(f"""{base} SELECT b.ad_id, c.concern, c.source, count(DISTINCT b.session_id) AS sessions, count(DISTINCT b.session_id) FILTER (WHERE b.ordered) AS orders
                 FROM b JOIN c ON c.session_id = b.session_id WHERE b.ad_id IN (SELECT unnest(?::VARCHAR[])) GROUP BY 1, 2, 3""", [*a, ids])
    c_p = q(f"""{base} SELECT b.ad_id, c.concern, p.product_name, count(DISTINCT b.session_id) AS sessions, count(DISTINCT b.session_id) FILTER (WHERE p.carted) AS carted,
                count(DISTINCT b.session_id) FILTER (WHERE p.ordered) AS ordered
                FROM b JOIN c ON c.session_id = b.session_id JOIN session_products p ON p.session_id = b.session_id
                WHERE b.ad_id IN (SELECT unnest(?::VARCHAR[])) AND (p.viewed OR p.carted OR p.ordered) GROUP BY 1, 2, 3""", [*a, ids])
    img = {r["n"]: _image_of(r["images"]) for r in q("SELECT lower(product_name) AS n, any_value(images) AS images FROM dim_products WHERE images IS NOT NULL GROUP BY 1")}
    for r in c_p:
        r["image"] = img.get((r["product_name"] or "").lower())
    return {"ready": True, "ads": ads, "ad_concern": ad_c, "concern_product": c_p}


# ================================================================== 5. journey builder
UNIT = {"key": "e.event_key", "name": "e.event_name", "page": "CASE WHEN e.is_pageview THEN e.page_type END"}


@app.get("/api/deeper/chain")
def deeper_chain(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, step: list[str] = Query([]), unit: str = "key", mode: str = "eventually",
                 only_ordered: bool = False, limit: int = 30):
    """The visits that did event 1, then event 2 ..., and the event that most often came next. unit: key (key actions) | name (every event name) | page (page types).
    mode: eventually (each step any time after the one before) | next (each step right after the one before)."""
    if unit not in UNIT:
        raise HTTPException(400, f"unit must be one of {list(UNIT)}")
    if mode not in ("eventually", "next"):
        raise HTTPException(400, "mode must be eventually or next")
    steps = [s for s in step if s][:8]
    expr = UNIT[unit]
    where = "NOT e.is_dup AND e.ts_ist::DATE BETWEEN ? AND ? AND " + expr + " IS NOT NULL" + ("" if include_excluded else " AND NOT e.is_excluded")
    args = [date_from or "2000-01-01", date_to or "2999-12-31"]
    if only_ordered:
        where += " AND e.session_id IN (SELECT session_id FROM pain_ordered WHERE ordered)"
    head = f"""WITH ev AS (SELECT e.session_id, {expr} AS ev, e.ts, e.id FROM events_clean e WHERE {where}),
               d0 AS (SELECT *, lag(ev) OVER (PARTITION BY session_id ORDER BY ts, id) AS prev FROM ev),
               d AS (SELECT session_id, ev, row_number() OVER (PARTITION BY session_id ORDER BY ts, id) AS pos FROM d0 WHERE prev IS DISTINCT FROM ev)"""
    if not steps:
        starts = q(f"{head} SELECT ev, count(DISTINCT session_id) AS sessions FROM d GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 80", args)
        tot = one(f"{head} SELECT count(DISTINCT session_id) AS n FROM d", args)["n"]
        return {"steps": [], "next": starts, "total": tot, "ended": 0}
    ctes, params = [], []
    for i, ev in enumerate(steps, 1):
        if i == 1:
            ctes.append(f"m1 AS (SELECT session_id, min(pos) AS p FROM d WHERE ev = ? GROUP BY 1)")
        else:
            cond = f"d.pos = m{i - 1}.p + 1" if mode == "next" else f"d.pos > m{i - 1}.p"
            ctes.append(f"m{i} AS (SELECT d.session_id, min(d.pos) AS p FROM d JOIN m{i - 1} ON m{i - 1}.session_id = d.session_id WHERE d.ev = ? AND {cond} GROUP BY 1)")
        params.append(ev)
    n = len(steps)
    counts = " UNION ALL ".join(f"SELECT {i} AS k, count(*) AS n, count(*) FILTER (WHERE session_id IN (SELECT session_id FROM pain_ordered WHERE ordered)) AS ordered FROM m{i}" for i in range(1, n + 1))
    sql = head + ",\n" + ",\n".join(ctes)
    res = q(f"{sql} {counts} ORDER BY 1", [*args, *params])
    nxt = q(f"""{sql} SELECT d.ev, count(DISTINCT d.session_id) AS sessions,
                count(DISTINCT d.session_id) FILTER (WHERE d.session_id IN (SELECT session_id FROM pain_ordered WHERE ordered)) AS ordered
                FROM d JOIN m{n} ON m{n}.session_id = d.session_id WHERE d.pos = m{n}.p + 1 GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT ?""", [*args, *params, max(1, min(limit, 100))])
    total_all = one(f"{head} SELECT count(DISTINCT session_id) AS n FROM d", args)["n"]
    last = res[-1]["n"] if res else 0
    ended = one(f"""{sql} SELECT count(*) AS n FROM m{n} WHERE NOT EXISTS (SELECT 1 FROM d WHERE d.session_id = m{n}.session_id AND d.pos = m{n}.p + 1)""", [*args, *params])["n"]
    out_steps, prev_n = [], total_all
    for ev, r in zip(steps, res):
        out_steps.append({"event": ev, "sessions": r["n"], "ordered": r["ordered"], "of_all": ratio(r["n"], total_all), "of_prev": ratio(r["n"], prev_n)})
        prev_n = r["n"]
    return {"steps": out_steps, "next": nxt, "total": total_all, "ended": ended, "last": last}


# ================================================================== 6. segments
def _label_meta() -> dict:
    meta = {key: {"group": g, "title": t, "description": desc} for g, key, t, desc, _ in D.LABELS}
    for r in q("SELECT DISTINCT label_key FROM user_labels WHERE label_key LIKE 'stage:%' OR label_key LIKE 'concern:%'"):
        k = r["label_key"]
        name = k.split(":", 1)[1]
        if k.startswith("stage:"):
            meta[k] = {"group": "Journey stage", "title": name.replace("_", " ").replace(",", "").capitalize(), "description": "Where the person is in the journey (Users tab segment)."}
        else:
            meta[k] = {"group": "Skin concern (quiz)", "title": name, "description": "Named this concern in the skin quiz."}
    return meta


@app.get("/api/deeper/segments")
def deeper_segments(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, label: str | None = None):
    if not _ready("user_labels"):
        return {"ready": False}
    uw, ua = _uw(date_from, date_to, include_excluded)
    meta = _label_meta()
    total = one(f"SELECT count(*) AS people, count(*) FILTER (WHERE u.orders > 0) AS buyers FROM users_360 u WHERE {uw}", ua)
    rows = q(f"""SELECT l.label_key, count(*) AS people, count(*) FILTER (WHERE u.orders > 0) AS buyers, count(*) FILTER (WHERE u.orders > 1) AS repeat_buyers, coalesce(sum(u.revenue), 0) AS revenue,
                 count(*) FILTER (WHERE nullif(u.phone10, '') IS NOT NULL) AS reachable, avg(u.sessions) AS avg_sessions
                 FROM user_labels l JOIN users_360 u ON u.person_key = l.person_key WHERE {uw}
                 GROUP BY 1 ORDER BY 2 DESC""", ua)
    out = []
    for r in rows:
        m = meta.get(r["label_key"], {"group": "Other", "title": r["label_key"], "description": ""})
        out.append({**r, **m, "key": r["label_key"], "buyer_rate": ratio(r["buyers"], r["people"]), "aov": round(r["revenue"] / r["buyers"], 0) if r["buyers"] else None,
                    "share": ratio(r["people"], total["people"]), "avg_sessions": round(r["avg_sessions"] or 0, 1)})
    co = []
    if label:
        co = q(f"""SELECT l2.label_key AS key, count(*) AS people FROM user_labels l1 JOIN user_labels l2 ON l2.person_key = l1.person_key AND l2.label_key <> l1.label_key
                   JOIN users_360 u ON u.person_key = l1.person_key WHERE l1.label_key = ? AND {uw}
                   GROUP BY 1 ORDER BY 2 DESC LIMIT 12""", [label, *ua])
        for r in co:
            r["title"] = meta.get(r["key"], {}).get("title", r["key"])
    return {"ready": True, "untracked": untracked_sales(include_excluded), "totals": total, "labels": out, "co": co, "base": {"buyer_rate": ratio(total["buyers"], total["people"])}}


@app.get("/api/deeper/segments/people")
def deeper_segment_people(label: str, date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, only_reachable: bool = False,
                          sort: str = "last_seen", limit: int = 50, offset: int = 0):
    if not _ready("user_labels"):
        return {"total": 0, "rows": []}
    uw, ua = _uw(date_from, date_to, include_excluded)
    if only_reachable:
        uw += " AND nullif(u.phone10, '') IS NOT NULL"
    order = {"last_seen": "u.last_seen DESC", "revenue": "u.revenue DESC", "sessions": "u.sessions DESC", "evidence": "l.n DESC"}.get(sort, "u.last_seen DESC")
    total = one(f"SELECT count(*) AS n FROM user_labels l JOIN users_360 u ON u.person_key = l.person_key WHERE l.label_key = ? AND {uw}", [label, *ua])["n"]
    rows = q(f"""SELECT u.person_key, u.name, u.phone10, u.email, u.city, u.state, u.segment, u.first_channel, u.orders, u.revenue, u.sessions, u.last_seen, l.n AS evidence
                 FROM user_labels l JOIN users_360 u ON u.person_key = l.person_key WHERE l.label_key = ? AND {uw} ORDER BY {order} NULLS LAST, u.person_key LIMIT ? OFFSET ?""",
             [label, *ua, max(1, min(int(limit), 2000)), max(0, offset)])
    meta = _label_meta()
    if rows:
        by: dict = {}
        for r in q("SELECT person_key, label_key FROM user_labels WHERE person_key IN (SELECT unnest(?::VARCHAR[])) AND label_key NOT LIKE 'stage:%'", [[r["person_key"] for r in rows]]):
            by.setdefault(r["person_key"], []).append(meta.get(r["label_key"], {}).get("title", r["label_key"]))
        for r in rows:
            r["labels"] = by.get(r["person_key"], [])
    return {"label": label, "title": meta.get(label, {}).get("title", label), "total": total, "rows": rows}

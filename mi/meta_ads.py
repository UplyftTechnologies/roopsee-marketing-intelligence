"""Meta Ads: spend joined to your own sessions and orders."""
import json
from datetime import date, timedelta
from fastapi import HTTPException

from . import core, meta as meta_mod, transform
from .core import JOB, _run_job, app, one, prev_range, q, ratio


def _meta_rows(d_from, d_to, include_excluded) -> list[dict]:
    lo, hi = d_from or "2000-01-01", d_to or "2999-12-31"
    mrows = q("""SELECT campaign_id, max(campaign_name) AS name, sum(spend) AS spend, sum(impressions) AS impressions, sum(clicks) AS clicks, sum(link_clicks) AS link_clicks,
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
            meta_mod.sync(core.CON.cursor(), full=full)
        except Exception as e:
            meta_mod.record_error(core.CON.cursor(), e)
            raise
        JOB["message"] = "linking campaigns to your sessions"
        transform.run(core.CON.cursor(), flags_only=True)
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
                      WHERE s.channel = 'Paid Meta' AND sm.session_id IS NULL AND s.date_ist BETWEEN ? AND ?{ex} GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 6""", [date_from or "2000-01-01", date_to or "2999-12-31"])
    blended = _meta_blended(date_from, date_to, include_excluded, tot["spend"])
    pblended = _meta_blended(pr[0], pr[1], include_excluded, prev["spend"]) if (pr and prev) else None
    return {"connected": True, "blended": blended, "prev_blended": pblended, "totals": tot, "prev": prev, "prev_range": pr, "campaigns": rows, "dates": cur["dates"], "current": cur["m"],
            "prev_dates": pser["dates"] if pser else None, "previous": pser["m"] if pser else None,
            "coverage": {**cov, "unmatched": unmatched}, "wasted": [r for r in rows if r["verdict"] == "Wasting spend"]}


@app.get("/api/meta/reconcile")
def meta_reconcile(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False):
    """Meta's own numbers next to what your site recorded for Paid Meta traffic, day by day, with the likely reasons for any gap."""
    if not one("SELECT count(*) AS n FROM raw_meta_insights")["n"]:
        return {"connected": False}
    lo, hi = date_from or "2000-01-01", date_to or "2999-12-31"
    ex = "" if include_excluded else " AND NOT is_excluded"
    meta = {r["d"]: r for r in q("""SELECT date AS d, sum(spend) AS spend, sum(link_clicks) AS clicks, sum(purchases) AS purchases, sum(purchase_value) AS value
                                   FROM raw_meta_insights WHERE date BETWEEN ? AND ? GROUP BY 1""", [lo, hi])}
    orders = {r["d"]: r for r in q(f"""SELECT date_ist AS d, count(*) AS orders, coalesce(sum(revenue), 0) AS revenue FROM orders_clean
                                      WHERE is_valid AND credit_channel = 'Paid Meta' AND date_ist BETWEEN ? AND ?{ex} GROUP BY 1""", [lo, hi])}
    visits = {r["d"]: r["n"] for r in q(f"SELECT date_ist AS d, count(*) AS n FROM sessions WHERE channel = 'Paid Meta' AND date_ist BETWEEN ? AND ?{ex} GROUP BY 1", [lo, hi])}
    days = sorted(set(meta) | set(orders) | set(visits))
    rows = []
    for d in days:
        m, o = meta.get(d, {}), orders.get(d, {})
        rows.append({"date": d, "spend": m.get("spend") or 0, "meta_clicks": m.get("clicks") or 0, "meta_purchases": m.get("purchases") or 0, "meta_value": m.get("value") or 0,
                     "site_visits": visits.get(d, 0), "site_orders": o.get("orders", 0), "site_revenue": o.get("revenue", 0)})
    tot = {k: sum(r[k] for r in rows) for k in ("spend", "meta_clicks", "meta_purchases", "meta_value", "site_visits", "site_orders", "site_revenue")}
    notes = []
    if tot["meta_clicks"] >= 100:
        ratio_v = tot["site_visits"] / tot["meta_clicks"]
        if ratio_v < 0.6:
            notes.append(f"Only {ratio_v * 100:.0f}% of Meta link clicks arrived as a visit on your site ({tot['site_visits']:,} visits for {tot['meta_clicks']:,.0f} clicks). The rest is usually people leaving before the page loads, "
                         "or tracking blocked in the in-app browser. A faster landing page and the Meta pixel on the site help.")
        elif ratio_v > 1.2:
            notes.append(f"Your site counted more Paid Meta visits ({tot['site_visits']:,}) than Meta counted link clicks ({tot['meta_clicks']:,.0f}): some of those visits are returning visitors or shared links carrying Meta tags.")
    gap = tot["meta_purchases"] - tot["site_orders"]
    if gap > 0:
        notes.append(f"Meta reports {gap:,.0f} more purchase{'s' if gap != 1 else ''} than your site credited to Paid Meta ({tot['meta_purchases']:,.0f} against {tot['site_orders']}). "
                     "Meta counts a purchase when someone saw or clicked an ad within its attribution window and bought later, even through another channel. "
                     "Your site only credits an order to Meta when it came from a Meta-tagged visit (or a Direct order within 7 days of one).")
    elif gap < 0:
        notes.append(f"Your site credits {-gap:,.0f} more order{'s' if -gap != 1 else ''} to Paid Meta than Meta reports. The Meta pixel or Conversions API may not be sending every purchase, which also weakens Meta's ad optimisation.")
    if tot["meta_purchases"] and tot["site_orders"] and tot["meta_value"] and abs(tot["meta_value"] - tot["site_revenue"]) / max(tot["meta_value"], 1) > 0.5:
        notes.append(f"Purchase value also differs: Meta says {tot['meta_value']:,.0f}, your site recorded {tot['site_revenue']:,.0f}. Check that the pixel sends the order total and currency.")
    return {"connected": True, "totals": tot, "rows": rows, "notes": notes}


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
    rows = q(f"""SELECT {idc} AS id, max({namec}) AS name, max(campaign_name) AS campaign, sum(spend) AS spend, sum(impressions) AS impressions, sum(clicks) AS clicks,
                 sum(link_clicks) AS link_clicks, sum(purchases) AS meta_purchases, sum(purchase_value) AS meta_value, sum(add_to_cart) AS meta_atc, sum(initiate_checkout) AS meta_checkout
                 FROM raw_meta_insights WHERE {w} GROUP BY 1 ORDER BY round(sum(spend), 2) DESC, 1 LIMIT 200""", a)
    thumbs = {r["entity_id"]: r for r in q("SELECT entity_id, thumbnail_url, effective_status FROM raw_meta_entities WHERE entity_type = ?", [level])}
    for r in rows:
        t = thumbs.get(r["id"], {})
        r["thumbnail_url"], r["status"] = t.get("thumbnail_url"), t.get("effective_status")
        r["ctr"] = ratio(r["clicks"], r["impressions"])
        r["cpc"] = round(r["spend"] / r["clicks"], 2) if r["clicks"] else None
        r["meta_roas"] = round((r["meta_value"] or 0) / r["spend"], 2) if r["spend"] else None
    return {"level": level, "rows": rows}


def _meta_lite(r: dict) -> dict:
    """Meta's own numbers for one ad set / ad (our sessions can only be matched to campaigns reliably)."""
    sp = float(r["spend"] or 0)
    r["spend"] = sp
    r["ctr"] = ratio(r["clicks"], r["impressions"])
    r["cpc"] = round(sp / r["clicks"], 2) if r["clicks"] else None
    r["meta_roas"] = round((r["meta_value"] or 0) / sp, 2) if sp else None
    return r


_SUM = ("spend", "impressions", "clicks", "link_clicks", "meta_purchases", "meta_value", "meta_atc")


@app.get("/api/meta/hierarchy")
def meta_hierarchy(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, include_idle: bool = False):
    """Campaign -> ad set -> ad tree with spend and results at every level.
    Campaign rows also carry our own sessions / orders / ROAS. `include_idle` adds items that had no spend in the range."""
    if not one("SELECT count(*) AS n FROM raw_meta_insights")["n"]:
        return {"connected": False, "campaigns": []}
    lo, hi = date_from or "2000-01-01", date_to or "2999-12-31"
    rows = q("""SELECT campaign_id, max(campaign_name) AS campaign_name, adset_id, max(adset_name) AS adset_name, ad_id, max(ad_name) AS ad_name,
                sum(spend) AS spend, sum(impressions) AS impressions, sum(clicks) AS clicks, sum(link_clicks) AS link_clicks,
                sum(purchases) AS meta_purchases, sum(purchase_value) AS meta_value, sum(add_to_cart) AS meta_atc
                FROM raw_meta_insights WHERE date BETWEEN ? AND ? GROUP BY campaign_id, adset_id, ad_id ORDER BY campaign_id, adset_id, ad_id""", [lo, hi])
    ents = {}
    for e in q("SELECT entity_type, entity_id, name, campaign_id, adset_id, effective_status, daily_budget, thumbnail_url FROM raw_meta_entities"):
        ents[(e["entity_type"], e["entity_id"])] = e
    ours = {r["campaign_id"]: r for r in _meta_rows(date_from, date_to, include_excluded)}
    zero = {k: 0 for k in _SUM}

    camps: dict[str, dict] = {}

    def camp(cid, name=None):
        if cid not in camps:
            e = ents.get(("campaign", cid), {})
            camps[cid] = {"id": cid, "level": "campaign", "name": name or e.get("name") or cid, "status": e.get("effective_status"),
                          "daily_budget": e.get("daily_budget"), "objective": (ours.get(cid) or {}).get("objective"), "adsets": {}}
        return camps[cid]

    def adset(c, aid, name=None):
        if aid not in c["adsets"]:
            e = ents.get(("adset", aid), {})
            c["adsets"][aid] = {"id": aid, "level": "adset", "name": name or e.get("name") or aid, "status": e.get("effective_status"),
                                "daily_budget": e.get("daily_budget"), "ads": {}}
        return c["adsets"][aid]

    for r in rows:
        c = camp(r["campaign_id"], r["campaign_name"])
        a = adset(c, r["adset_id"], r["adset_name"])
        e = ents.get(("ad", r["ad_id"]), {})
        a["ads"][r["ad_id"]] = _meta_lite({"id": r["ad_id"], "level": "ad", "name": r["ad_name"] or e.get("name") or r["ad_id"], "status": e.get("effective_status"),
                                           "thumbnail_url": e.get("thumbnail_url"), **{k: r[k] or 0 for k in _SUM}})
    if include_idle:  # things that exist in Meta but had no spend in this range
        for (kind, eid), e in ents.items():
            if kind == "campaign":
                camp(eid)
            elif kind == "adset" and e.get("campaign_id"):
                adset(camp(e["campaign_id"]), eid)
            elif kind == "ad" and e.get("campaign_id") and e.get("adset_id"):
                a = adset(camp(e["campaign_id"]), e["adset_id"])
                a["ads"].setdefault(eid, _meta_lite({"id": eid, "level": "ad", "name": e.get("name") or eid, "status": e.get("effective_status"),
                                                     "thumbnail_url": e.get("thumbnail_url"), **zero}))
    out = []
    for c in camps.values():
        sets = []
        for a in c["adsets"].values():
            ads = sorted(a.pop("ads").values(), key=lambda x: -x["spend"])
            node = _meta_lite({**a, **{k: sum(x[k] or 0 for x in ads) for k in _SUM}})
            node["children"] = ads
            sets.append(node)
        sets.sort(key=lambda x: -x["spend"])
        c.pop("adsets")
        base = ours.get(c["id"])
        if base:
            node = {**base, **{k: c[k] for k in ("id", "level", "daily_budget") if c.get(k) is not None}, "name": base["name"] or c["name"], "status": c["status"] or base.get("status")}
        else:
            node = _meta_derive({**c, **{k: sum(x[k] or 0 for x in sets) for k in _SUM}, "meta_checkout": 0, "sessions": 0, "visitors": 0, "carts": 0, "checkouts": 0, "quiz": 0, "orders": 0, "revenue": 0.0})
        node["id"], node["level"] = c["id"], "campaign"
        node["children"] = sets
        out.append(node)
    out.sort(key=lambda x: -x["spend"])
    return {"connected": True, "campaigns": out,
            "counts": {"campaigns": len(out), "adsets": sum(len(c["children"]) for c in out), "ads": sum(len(a["children"]) for c in out for a in c["children"])}}

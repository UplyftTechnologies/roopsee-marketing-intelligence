"""Ads & landing pages (the former Deeper analysis tab, without the parts that repeated other pages).

ads    a postmortem card per Meta ad and per landing product page: what the visits it brought did, against comparable visits
flow   ad -> skin concern -> products

Moved out: the pre-order paths (Journeys › Every journey and the presets), first-order lead-up, search, quiz and payment timing
(Journeys › More detail, mi/journey_detail.py), the journey builder (Journeys › My presets, mi/presets.py) and segments (Audiences, mi/segments.py).
Visits follow the global date range, hidden traffic and the device filter like every other page. Tables: mi/deeper_sql.py.
"""
import re
from statistics import median

from fastapi import HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from .config import DATA_DIR
from .core import app, one, q, ratio, sess_where
from .sessions import FLAG_ORDER

AD_DIR = DATA_DIR / "ad_images"
SESS = "FROM sessions s LEFT JOIN session_orders o ON o.session_id = s.session_id"

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


# ================================================================== 1. ad / landing product postmortem cards
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


@app.get("/api/deeper/ads")
def deeper_ads(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False):
    if not _ready("session_attrib", "session_landing_product", "pain_sessions"):
        return {"ready": False}
    w, a = sess_where(date_from, date_to, include_excluded)
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
    return {"ready": True, "ads": ads, "meta_baseline": {**bm, "sessions": meta_base["sessions"]},
            "meta_connected": bool(info), "ads_without_image": sum(1 for x in ads if not x["image"]), "products": prods, "product_baseline": {**pbase, "sessions": pb["sessions"]}}


# ================================================================== 2. ad -> concern -> products
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

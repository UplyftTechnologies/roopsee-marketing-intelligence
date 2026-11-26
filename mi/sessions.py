"""Sessions: the list, filters, one session in detail and the event catalogue."""
import json
import re
from fastapi import HTTPException

from .core import _csv, app, one, q, sess_where


# what a session "did" (used by the multi-select filters and the abandoner presets)
FLAG_ORDER = "(coalesce(s.f_order, false) OR coalesce(o.n_placed, 0) > 0)"  # a real order: payment-cancelled / pending ones do not count


FLAG_LOGIN = "(coalesce(s.f_login, false) OR s.user_id IS NOT NULL)"


# every flag is wrapped so a missing value counts as "did not" (NOT NULL would otherwise silently drop the session from "did not" filters)
SESSION_FLAGS = {k: f"coalesce({v}, false)" for k, v in {
    "product": "s.f_product", "cart": "s.f_cart", "checkout": "s.f_checkout", "pay": "s.f_pay", "order": FLAG_ORDER,
    "login": FLAG_LOGIN, "login_now": "s.f_login", "quiz": "s.f_quiz_done", "search": "s.f_search", "address": "s.f_address", "location": "s.f_location",
    "roop": "jy.chat_opened", "roop_asked": "jy.chat_asked"}.items()}


EMAIL = "coalesce(nullif(lower(u.email), ''), o.order_email)"


SESSION_SORTS = {"started_at": "s.started_at", "events": "s.events", "duration_s": "s.duration_s", "order_value": "coalesce(o.order_value, 0)",
                 "channel": "s.channel", "campaign": "s.campaign", "city": "nullif(lower(s.city), '')", "name": "nullif(lower(u.name), '')", "email": EMAIL,
                 "stage": f"CASE WHEN {FLAG_ORDER} THEN 5 ELSE s.stage END", "device": "s.device", "pincode": "s.pincode"}


ORD_CTE = "WITH o AS (SELECT * FROM session_orders)"  # built once by the transform


SESS_FROM = (" FROM sessions s LEFT JOIN o ON o.session_id = s.session_id LEFT JOIN users_360 u ON u.person_key = coalesce(s.user_id, s.visitor_key)"
             " LEFT JOIN journey_sessions jy ON jy.session_id = s.session_id LEFT JOIN session_attrib sa ON sa.session_id = s.session_id"
             " LEFT JOIN meta_ad_dim ae ON ae.ad_id = sa.ad_id LEFT JOIN session_meta sm ON sm.session_id = s.session_id"
             " LEFT JOIN session_landing_product lp ON lp.session_id = s.session_id")


def _sessions_where(d_from, d_to, include_excluded, search=None, channel=None, only_excluded=False, min_stage=0, has=None, lacks=None, match="any", pincode=None, event=None,
                    ad=None, adset=None, campaign_id=None, landing_product=None, ad_match=None, region=None, city=None, delivery_state=None, delivery_city=None):
    w, a = sess_where(d_from, d_to, include_excluded or only_excluded)  # "only hidden" must not be combined with "hide hidden"
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
    for col, val in (("sa.ad_id", ad), ("sa.adset_id", adset), ("lp.product_id", landing_product)):  # the ad / ad set / product page a visit came from
        if val:
            w += f" AND {col} = ?"
            a.append(val)
    if campaign_id:  # the campaign tag in the link, or the campaign the visit was tied to through its tag or its ad
        w += " AND (s.campaign = ? OR sm.meta_campaign_id = ?)"
        a += [campaign_id, campaign_id]
    for col, val in (("s.region", region), ("s.city", city), ("s.delivery_state", delivery_state), ("s.delivery_city", delivery_city)):  # where the visit came from / where it is delivered (exact names, comma list)
        names = _csv(val)
        if names:
            w += f" AND {col} IN ({','.join('?' * len(names))})"
            a += names
    if ad_match:
        kinds = [k for k in _csv(ad_match) if k in ("id", "name", "probable", "unmatched", "none")]
        if kinds:
            w += " AND (" + " OR ".join(["sa.session_id IS NULL" if k == "none" else "sa.ad_match = ?" for k in kinds]) + ")"
            a += [k for k in kinds if k != "none"]
    pins = _csv(pincode)
    if pins:
        w += " AND s.pincode IN (" + ",".join("?" * len(pins)) + ")"
        a += pins
    evs = [e.lower().replace(" ", "_") for e in _csv(event)]
    if evs:  # sessions that contain the event (name or part of a name); several names = any of them
        w += " AND s.session_id IN (SELECT session_id FROM session_events WHERE " + " OR ".join(["event_name LIKE ?"] * len(evs)) + ")"
        a += [f"%{e}%" for e in evs]
    if search:
        like = f"%{search.lower()}%"
        ev_term = search.strip().lower().replace(" ", "_")
        # something like add_to_cart or checked_delivery_pincode is an event name: also return the sessions that contain it
        ev_or = " OR s.session_id IN (SELECT session_id FROM session_events WHERE event_name LIKE ?)" if "_" in ev_term else ""
        w += f""" AND (lower(s.session_id) LIKE ? OR lower(s.visitor_key) LIKE ? OR lower(coalesce(s.user_id,'')) LIKE ? OR coalesce(s.ip,'') LIKE ?
                 OR coalesce(s.phone10,'') LIKE ? OR lower(coalesce(s.city,'')) LIKE ? OR lower(coalesce(u.name,'')) LIKE ? OR lower(s.campaign) LIKE ?
                 OR lower(coalesce({EMAIL}, '')) LIKE ? OR coalesce(s.pincode, '') LIKE ?
                 OR s.session_id IN (SELECT session_id FROM orders_clean WHERE session_id IS NOT NULL AND lower(order_id) LIKE ?)
                 OR lower(coalesce(sa.ad_id, '')) LIKE ? OR lower(coalesce(ae.name, '')) LIKE ?{ev_or})"""
        a += [like] * 13 + ([f"%{ev_term}%"] if ev_or else [])
    return w, a


@app.get("/api/sessions")
def sessions(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, search: str | None = None,
             min_stage: int = 0, channel: str | None = None, only_excluded: bool = False, has: str | None = None, lacks: str | None = None,
             match: str = "any", pincode: str | None = None, event: str | None = None, ad: str | None = None, adset: str | None = None, campaign_id: str | None = None,
             landing_product: str | None = None, ad_match: str | None = None, region: str | None = None, city: str | None = None,
             delivery_state: str | None = None, delivery_city: str | None = None, sort: str = "started_at", direction: str = "desc", limit: int = 50, offset: int = 0):
    """ad / adset / campaign_id / landing_product = only visits that came from that Meta ad, ad set, campaign (exact id or name) or started on that product page.
    has / lacks = comma lists of: product, cart, checkout, pay, order, login (known user), login_now (logged in during the session), quiz, search, roop (opened the Roop assistant), roop_asked (asked it a question), address (saved a proper address), location (only picked a pincode / location). pincode = comma list of 6-digit pincodes given in the session. match=any|all applies to `has`."""
    w, a = _sessions_where(date_from, date_to, include_excluded, search, channel, only_excluded, min_stage, has, lacks, match, pincode, event, ad, adset, campaign_id, landing_product, ad_match, region, city, delivery_state, delivery_city)
    order = SESSION_SORTS.get(sort, SESSION_SORTS["started_at"])
    d = "ASC" if direction.lower() == "asc" else "DESC"
    total = one(f"{ORD_CTE} SELECT count(*) n {SESS_FROM} WHERE {w}", a)["n"]
    rows = q(f"""{ORD_CTE} SELECT s.session_id, s.started_at, s.duration_s, s.events, s.pageviews, s.channel, s.source, s.medium, s.campaign, s.landing_path,
        s.city, s.region, s.country, s.device, s.platform, s.is_app, s.user_id, u.name, {EMAIL} AS email, s.phone10, s.pincode, s.ip, s.visitor_key, s.key_events, CASE WHEN {FLAG_ORDER} THEN 5 ELSE s.stage END AS stage,
        s.is_excluded, s.excl_reason, sa.ad_id, ae.name AS ad_name, sa.adset_id, sa.ad_match, sa.ad_raw, coalesce(jy.chat_opened, false) AS roop_opened, coalesce(jy.chat_asked, false) AS roop_asked, coalesce(o.n_orders, 0) AS order_count, o.order_value, o.other_value AS order_other_value, o.statuses AS order_statuses
        {SESS_FROM} WHERE {w} ORDER BY {order} {d} NULLS LAST, s.started_at DESC, s.session_id LIMIT ? OFFSET ?""", [*a, max(1, min(int(limit), 5000)), max(0, offset)])
    return {"total": total, "rows": rows}


@app.get("/api/sessions/ads")
def session_ads(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, limit: int = 80):
    """The Meta ads that brought visits in these dates (for the Ad filter of the Sessions tab), with their names where Meta is synced."""
    w, a = sess_where(date_from, date_to, include_excluded)
    return q(f"""SELECT sa.ad_id, ae.name, count(*) AS sessions, count(*) FILTER (WHERE jy.chat_opened) AS roop FROM sessions s JOIN session_attrib sa ON sa.session_id = s.session_id
                 LEFT JOIN meta_ad_dim ae ON ae.ad_id = sa.ad_id
                 LEFT JOIN journey_sessions jy ON jy.session_id = s.session_id WHERE {w} AND s.channel = 'Paid Meta' GROUP BY 1, 2 ORDER BY sessions DESC, 1 LIMIT ?""", [*a, max(1, min(int(limit), 300))])


@app.get("/api/sessions/counts")
def session_counts(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False):
    """Sizes of the one-click presets on the Sessions tab."""
    w, a = sess_where(date_from, date_to, include_excluded)
    r = one(f"""{ORD_CTE} SELECT count(*) AS total,
        count(*) FILTER (WHERE coalesce(s.f_cart, false) AND NOT {FLAG_ORDER}) AS cart_abandoners, count(*) FILTER (WHERE coalesce(s.f_checkout, false) AND NOT {FLAG_ORDER}) AS checkout_abandoners,
        count(*) FILTER (WHERE {FLAG_LOGIN}) AS logged_in, count(*) FILTER (WHERE {FLAG_ORDER}) AS ordered
        {SESS_FROM} WHERE {w}""", a)
    r["channels"] = [x["channel"] for x in q(f"SELECT s.channel, count(*) AS n FROM sessions s WHERE {w} GROUP BY 1 ORDER BY n DESC", a)]
    return r


# event payload keys that are plumbing, not "what happened" (device, tracking ids, location of the visitor, ...)
from .payload import NOISE as _NOISE, event_params, flat_payload, match_score # hidden in the "Data" view: plumbing, not "what happened"


# the most telling keys first; the timeline shows the first few inline and the rest when the row is opened
_FIRST = ["element_text", "element", "search_term", "scroll_pct", "results_count", "totalResults", "visibleBefore", "grand_total", "payment_method", "cart_value",
          "cart_items", "items_count", "order_id", "locationText", "addressPincode", "pincode", "selected_program", "skin_type", "quiz_name", "current_step"]


_LABEL = {"element_text": "Clicked", "element": "Element", "scroll_pct": "Scrolled to %", "results_count": "Results", "totalResults": "Total results",
          "visibleBefore": "Showing before", "grand_total": "Order total ₹", "cart_value": "Cart value ₹", "cart_items": "Items in cart", "items_count": "Items",
          "locationText": "Location", "addressPincode": "Pincode", "selected_program": "Program", "current_step": "Quiz step", "load_ms": "Load time ms",
          "search_source": "Search from", "payment_method": "Payment"}


def _event_details(value, extra, cart_step=False) -> list[dict]:
    """Readable key / value pairs from one event's payload (nested rawBody flattened, plumbing and empty values dropped)."""
    try:
        d = json.loads(extra) if isinstance(extra, str) else (extra or {})
    except Exception:
        d = {}
    if not isinstance(d, dict):
        d = {}
    flat = {**{k: v for k, v in d.items() if k != "rawBody"}, **(d.get("rawBody") if isinstance(d.get("rawBody"), dict) else {})}
    if value not in (None, "") and "value" not in flat:
        flat["value"] = value
    out = {}
    for k, v in flat.items():
        if k in _NOISE or v is None or v == "" or v == [] or v == {}:
            continue
        if k in ("cart_value", "cart_items") and str(v) in ("0", "0.0"):
            continue
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        v = str(v)
        out[k] = v if len(v) <= 160 else v[:157] + "…"
    first = [k for k in _FIRST if k in out and (cart_step or k not in ("cart_value", "cart_items"))]  # the running cart total repeats on every event: lead with it only on cart steps
    rest = [k for k in out if k not in first]
    keys = first + [k for k in rest if k not in ("cart_value", "cart_items")] + [k for k in rest if k in ("cart_value", "cart_items")]
    nice = lambda k: _LABEL.get(k) or re.sub(r"[_\s]+", " ", re.sub(r"(?<=[a-z])(?=[A-Z])", " ", k)).strip().capitalize()
    return [{"k": nice(k), "v": out[k]} for k in keys]


def _raw_record(r: dict) -> dict:
    """The event exactly as stored in event_log (every column, extra_data as real JSON), for the 'raw data' view."""
    out = {k: v for k, v in r.items() if k != "x"}
    try:
        out["extra_data"] = json.loads(r["x"]) if r.get("x") else None
    except Exception:
        out["extra_data"] = r.get("x")
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in out.items() if v is not None}


def _addresses(user_id, session_id=None):
    """Addresses saved on the account (customer_address) plus, for a session, the pincodes / places typed during it."""
    saved = q("""SELECT id, full_name, phone, email, delivery_address, nearby_landmark, formatted_address, city, state, pincode, is_default, location_source,
                        created_at, updated_at, latitude, longitude FROM raw_customer_address
                 WHERE lower(user_id) = ? ORDER BY is_default DESC NULLS LAST, created_at DESC""", [str(user_id).lower()]) if user_id else []
    entered = []
    if session_id:
        entered = q("""SELECT pincode_ev AS pincode, event_name, min(timezone('Asia/Kolkata', ts)) AS first_at, count(*) AS n
                       FROM events_base WHERE session_id = ? AND pincode_ev IS NOT NULL GROUP BY 1, 2 ORDER BY first_at""", [session_id])
    return {"saved": saved, "entered": entered}


@app.get("/api/sessions/{session_id}")
def session_detail(session_id: str):
    """Everything about one session: attribution, device, the ordered event timeline, pages, orders, and the person it belongs to."""
    rows = q("SELECT * FROM sessions WHERE session_id = ?", [session_id])
    if not rows:
        raise HTTPException(404, "session not found")
    s = rows[0]
    events = q("""SELECT id, timezone('Asia/Kolkata', ts) AS at, event_name, event_key, page_type, path, product_name, brand, amount, search_term, city_n, ip
                  FROM events_clean WHERE session_id = ? AND NOT is_dup ORDER BY ts, id LIMIT 3000""", [session_id])
    hidden = one("SELECT count(*) FILTER (WHERE is_dup) AS n FROM events_clean WHERE session_id = ?", [session_id])["n"]
    raw = {r["id"]: r for r in q("SELECT *, extra_data::VARCHAR AS x FROM raw_event_log WHERE id IN (SELECT id FROM events_clean WHERE session_id = ? AND NOT is_dup)", [session_id])}
    for e in events:
        r = raw.pop(e.pop("id"), None)
        e["details"] = _event_details(r["value"], r["x"], e.get("event_key") in ("add_to_cart", "view_cart", "checkout_view", "pay_started", "order_placed")) if r else []
        e["raw"] = _raw_record(r) if r else None
        fl = flat_payload(r["x"], r["value"]) if r else {}
        e["score"], e["score_note"] = match_score(fl)
        e["params"] = event_params(fl)
    from .scores import borrow
    borrow(events, events)  # an add to cart sent without a score takes it from the earlier view / click of the same product in this visit
    from .chats import session_chats  # local import: chats.py imports nothing from here, but api.py loads both
    chats = session_chats(session_id)
    for c in chats:  # Roop chat messages are part of what the visitor did: show them in the timeline, in time order
        events.append({"at": c["at"], "event_name": "assistant_chat", "event_key": "roop_chat", "page_type": None, "path": "Roop chat", "product_name": None, "brand": None, "amount": None,
                       "search_term": str(c["question"] or "")[:100], "city_n": None, "ip": None, "score": None, "score_note": None, "score_from": None, "params": [], "raw": {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in c.items() if v is not None},
                       "details": [{"k": "Asked", "v": c["question"]}, {"k": "Roop replied" if not c["error"] else "No answer", "v": c["reply"] if not c["error"] else c["error"]}]
                       + ([{"k": "Rated", "v": "helpful" if c["rating"] == 1 else "not helpful"}] if c["rating"] else [])})
    if chats:
        events.sort(key=lambda e: e["at"])
    pages = q("""SELECT path, max(page_type) AS page_type, min(timezone('Asia/Kolkata', ts)) AS first_at, count(*) AS events,
                 count(*) FILTER (WHERE is_pageview) AS views FROM events_clean WHERE session_id = ? AND NOT is_dup GROUP BY path ORDER BY first_at""", [session_id])
    types = q("""SELECT event_name, max(event_key) AS event_key, count(*) AS n FROM events_clean WHERE session_id = ? AND NOT is_dup
                 GROUP BY event_name ORDER BY n DESC, 1 LIMIT 25""", [session_id])
    extra = one("""SELECT max(browser_n) AS browser,
                   first(utm_content ORDER BY ts) FILTER (WHERE utm_content IS NOT NULL) AS utm_content,
                   first(utm_term ORDER BY ts) FILTER (WHERE utm_term IS NOT NULL) AS utm_term,
                   first(referrer_host ORDER BY ts) FILTER (WHERE referrer_host IS NOT NULL) AS referrer
                   FROM events_clean WHERE session_id = ?""", [session_id])
    orders = q("""SELECT o.order_id, o.ts, o.total, o.status, o.payment_method, o.coupon_code, o.items_count, o.is_valid, o.is_test,
                  (SELECT string_agg(l.product_name, ' | ' ORDER BY l.product_name) FROM order_lines l WHERE l.order_id = o.order_id) AS items
                  FROM orders_clean o WHERE o.session_id = ? ORDER BY o.ts""", [session_id])
    if any(o["is_valid"] and not o["is_test"] for o in orders) or s.get("f_order"):
        s["stage"] = 5  # same rule as the Ordered filter
    pkey = s["user_id"] or s["visitor_key"]
    person = one("SELECT person_key, name, phone10, email, segment, sessions, is_registered FROM users_360 WHERE person_key = ?", [pkey])
    addresses = _addresses(s["user_id"], session_id)
    prev_s = one("SELECT session_id, started_at FROM sessions WHERE coalesce(user_id, visitor_key) = ? AND started_at < ? ORDER BY started_at DESC LIMIT 1", [pkey, s["started_at"]])
    next_s = one("SELECT session_id, started_at FROM sessions WHERE coalesce(user_id, visitor_key) = ? AND started_at > ? ORDER BY started_at ASC LIMIT 1", [pkey, s["started_at"]])
    ad = one("""SELECT sa.ad_id, sa.adset_id, sa.ad_match, sa.ad_raw, ae.name, ae.status, ae.campaign_id FROM session_attrib sa
                LEFT JOIN meta_ad_dim ae ON ae.ad_id = sa.ad_id WHERE sa.session_id = ?""", [session_id])
    if ad:
        from .deeper import ad_image_url
        sp = one("SELECT coalesce(sum(spend), 0) AS spend, coalesce(sum(link_clicks), 0) AS clicks FROM raw_meta_insights WHERE ad_id = ?", [ad["ad_id"]])
        ad = {**ad, "image": ad_image_url(ad["ad_id"]), "spend": float(sp["spend"] or 0), "clicks": sp["clicks"] or 0,
              "visits": one("SELECT count(*) AS n FROM session_attrib WHERE ad_id = ?", [ad["ad_id"]])["n"]}
    return {"session": s, "ad": ad or None, "events": events, "pages": pages, "event_types": types, "extra": extra, "orders": orders, "addresses": addresses, "duplicates_hidden": hidden, "chats": chats,
            "person": {**person, "person_key": pkey} if person else {"person_key": pkey}, "prev": prev_s or None, "next": next_s or None}


@app.get("/api/events/names")
def event_names():
    """Every event name with the number of sessions that contain it (for the Sessions event filter)."""
    return q("SELECT event_name, count(*) AS sessions FROM session_events GROUP BY 1 ORDER BY 2 DESC")


@app.get("/api/events/catalogue")
def catalogue(include_excluded: bool = False):
    return q("""SELECT event_name, coalesce(event_key,'(not a key event)') AS event_key, count(*) events, count(DISTINCT session_id) sessions,
        min(ts) AS first_seen, max(ts) AS last_seen FROM events_clean WHERE (? OR NOT is_excluded) GROUP BY 1,2 ORDER BY 3 DESC, 1 LIMIT 300""", [include_excluded])

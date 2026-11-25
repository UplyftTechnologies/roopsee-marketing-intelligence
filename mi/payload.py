"""What is kept from the extra data (payload) the tracker sends with every event.

About half of every stored payload is plumbing: copies of fields that already have their own column (page, url, user agent, time ...),
and tracker context the dashboard never shows. `slim` drops it before an event is stored, which makes the database smaller and the
rebuild faster. Nothing is lost for good: the source of truth stays in Supabase and a normal pull can restore any field.

`READ_BY_PIPELINE` lists the payload fields mi/transform.py reads (through j(...) / jj(...)). They are never dropped.
tests/test_invariants.py checks that this list matches the transform, so a new field cannot be dropped by mistake.
"""

# fields hidden in the dashboard's "Data" view because they are plumbing, not "what happened"
NOISE = {"environment", "analytics_event_id", "analytics_collector", "user_agent", "browser", "platform", "device", "language", "referrer", "page", "url",
         "time", "time_ist", "timezone", "timestamp", "ip", "city", "region", "country", "userName", "user_name", "phone", "visitorId", "sessionId", "userId",
         "session_id", "visitor_id", "eventName", "current_page", "latitude", "longitude", "screen_resolution", "is_first_visit", "traffic_source",
         "traffic_channel", "landing_page", "landing_path", "funnel_stage", "last_action", "step_in_session", "pages_viewed", "seconds_in_session",
         "seconds_on_page", "location_source", "previous_page", "first_touch_date", "has_gclid", "has_fbclid", "client_surface", "connection",
         "downlink_mbps", "rtt_ms", "dom_ready_ms", "page_link", "guest_session_id", "rawBody", "brand", "price", "section", "cartItems", "cartTotal",
         "productId", "productName", "referrer_host", "entry_type", "hidden", "hiddenCount"}

# fields the pipeline reads from the payload (keep in step with j(...) / jj(...) in mi/transform.py)
READ_BY_PIPELINE = {"addressCity", "addressPincode", "addressState", "brand", "cartTotal", "city", "cityName", "country", "device", "dom_ready_ms",
                    "grand_total", "ip", "item_brand", "item_name", "loadMs", "load_ms", "order_id", "paymentMethod", "phone", "pincode", "productName",
                    "referrer", "region", "search_term", "sessionId", "stateName", "userId", "visitorId"}

# fields that are safe to drop: hidden in the UI and never read by the pipeline
REMOVE = NOISE - READ_BY_PIPELINE - {"rawBody"}


def slim(obj):
    """The payload without the removable fields, at the top level and inside its `rawBody` copy."""
    if not isinstance(obj, dict):
        return obj
    out = {k: v for k, v in obj.items() if k not in REMOVE}
    raw = out.get("rawBody")
    if isinstance(raw, dict):
        out["rawBody"] = {k: v for k, v in raw.items() if k not in REMOVE}
    return out


import json as _json

SCORE_KEYS = ("product_match_score", "matchScore")


def flat_payload(extra, value=None) -> dict:
    """One event's stored payload as a flat dict: top level plus the `rawBody` copy, with the event's `value` added when it has one."""
    try:
        d = _json.loads(extra) if isinstance(extra, str) else (extra or {})
    except Exception:
        d = {}
    if not isinstance(d, dict):
        d = {}
    flat = {**{k: v for k, v in d.items() if k != "rawBody"}, **(d.get("rawBody") if isinstance(d.get("rawBody"), dict) else {})}
    if value not in (None, "") and "value" not in flat:
        flat["value"] = value
    return flat


def match_score(flat: dict):
    """(score, note): the product match score (0-100) when the event carries one; `note` explains a non-number such as 'not_scorable'."""
    for k in SCORE_KEYS:
        v = flat.get(k)
        if v in (None, ""):
            continue
        try:
            return round(float(v), 2), None
        except (TypeError, ValueError):
            return None, str(v).replace("_", " ")
    return None, None


def event_params(flat: dict, skip=()) -> list[dict]:
    """The readable name / value pairs of a payload, in stored order: plumbing, empty values and the score (it has its own column) left out."""
    out = []
    for k, v in flat.items():
        if k in NOISE or k in SCORE_KEYS or k in skip or v is None or v == "" or v == [] or v == {}:
            continue
        if isinstance(v, (dict, list)):
            v = _json.dumps(v, ensure_ascii=False)
        v = str(v)
        out.append({"k": k, "v": v if len(v) <= 160 else v[:157] + "…"})
    return out

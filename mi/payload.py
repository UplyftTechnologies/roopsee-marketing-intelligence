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

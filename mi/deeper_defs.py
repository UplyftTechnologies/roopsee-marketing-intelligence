"""Definitions for Ads & landing pages (concerns) and the Audiences › Interest & behaviour groups (labels): which skin concern a product is about, and how people are labelled (segments).

Everything a person might want to change lives here: add a label or a concern keyword and rebuild (Refresh), no page code to touch.
A label's `sql` returns (person_key, n): the people who have it and a count of the evidence (events, products, orders ...).
"""

# product name keywords -> the skin concern the product is about (used for the "inferred" concern when a visitor never took the quiz)
CONCERN_KEYWORDS = {
    "Acne & blemishes": ["acne", "salicylic", "bha", "blemish", "trouble", "pimple", "tea tree", "cica", "centella", "bija"],
    "Pigmentation & glow": ["dark spot", "pigment", "brighten", "bright", "vitamin c", "niacinamide", "glow", "tranexamic", "arbutin", "whitening", "even tone", "radiance"],
    "Sun protection": ["sunscreen", "sun screen", "spf", "sunblock", "sun stick"],
    "Dryness & hydration": ["hydrat", "moistur", "ceramide", "hyaluron", "barrier", "dry skin", "water cream", "aqua", "snail"],
    "Anti-ageing": ["retinol", "anti-aging", "anti aging", "anti-ageing", "collagen", "peptide", "wrinkle", "firming", "bakuchiol"],
    "Oil control & pores": ["oil control", "oil-control", "mattif", "pore", "clay", "sebum", "oily"],
    "Lips & makeup": ["lipstick", "lip tint", "lip balm", "lip gloss", "kajal", "eyeliner", "mascara", "blush", "foundation", "concealer", "compact", "tint", "makeup"],
}

# price bands in rupees, by the median selling price of the products a person looked at, carted or bought
BUDGET_MAX = 300
MID_MAX = 800

# how a person's quiz answers name a concern -> shown as is (the quiz stores e.g. ['acne', 'pigmentation'])

# group, key, title, description, sql returning (person_key, n)
_EVENT_PERSON = "SELECT person_key, count(*) AS n FROM events_base WHERE NOT is_dup AND {cond} GROUP BY 1"
_PRODUCT_EVENT = "NOT is_dup AND event_key IN ('product_view', 'add_to_cart') AND product_name IS NOT NULL"

LABELS = [
    ("Interest", "quiz_taker", "Quiz users", "Finished the skin quiz.", _EVENT_PERSON.format(cond="event_key = 'quiz_completed'")),
    ("Interest", "quiz_dropped", "Started the quiz, never finished", "Answered quiz questions but never completed it.",
     "SELECT person_key, count(*) AS n FROM events_base WHERE NOT is_dup AND event_name IN ('quiz_started', 'quiz_answer_filled', 'clicked_quiz_option') "
     "AND person_key NOT IN (SELECT person_key FROM events_base WHERE event_key = 'quiz_completed') GROUP BY 1"),
    ("Interest", "makeup_user", "Makeup users", "Looked at or added makeup, lip or eye products, or browsed the makeup pages.",
     "SELECT person_key, count(*) AS n FROM events_base WHERE NOT is_dup AND (page_type = 'makeup' OR (event_key IN ('product_view', 'add_to_cart') AND product_kind(product_name) IN ('Makeup', 'Lip'))) GROUP BY 1"),
    ("Interest", "skincare_user", "Skincare users", "Looked at or added face skincare: cleansers, serums, moisturisers, sunscreens, toners or masks.",
     "SELECT person_key, count(*) AS n FROM events_base WHERE " + _PRODUCT_EVENT + " AND kind_category(product_kind(product_name)) = 'Face' GROUP BY 1"),
    ("Interest", "hair_body_user", "Hair & body users", "Looked at or added hair or body products.",
     "SELECT person_key, count(*) AS n FROM events_base WHERE " + _PRODUCT_EVENT + " AND product_kind(product_name) IN ('Hair', 'Body') GROUP BY 1"),
    ("Price range", "price_budget", "Budget shoppers", f"The median price of the products they looked at or added is under ₹{BUDGET_MAX}.", "SELECT person_key, n FROM person_price WHERE median_price < {b}"),
    ("Price range", "price_mid", "Mid-range shoppers", f"Median price ₹{BUDGET_MAX} to ₹{MID_MAX}.", "SELECT person_key, n FROM person_price WHERE median_price >= {b} AND median_price <= {m}"),
    ("Price range", "price_premium", "Premium shoppers", f"Median price over ₹{MID_MAX}.", "SELECT person_key, n FROM person_price WHERE median_price > {m}"),
    ("Discounts", "discount_checker", "Discount checkers", "Opened coupons, offers or the wallet.",
     _EVENT_PERSON.format(cond="event_name IN ('clicked_view_all_coupons', 'page_viewed_coupons', 'clicked_view_offers', 'clicked_view_more_offers', 'cod_online_offer_viewed', 'closed_offers', "
                               "'clicked_wallet_icon', 'wallet_toggle_on', 'clicked_wallet_toggle', 'clicked_apply_coupon')")),
    ("Discounts", "coupon_user", "Coupon users", "Placed an order with a coupon code.",
     "SELECT coalesce(user_id, 'x') AS person_key, count(*) AS n FROM orders_clean WHERE is_valid AND coupon_code IS NOT NULL AND coupon_code <> '' AND user_id IS NOT NULL GROUP BY 1"),
    ("Discovery", "searcher", "Searchers", "Searched three or more times.",
     "SELECT s.person_key, count(*) AS n FROM discovery_events d JOIN sessions_person s ON s.session_id = d.session_id WHERE d.kind = 'search' GROUP BY 1 HAVING count(*) >= 3"),
    ("Discovery", "no_results", "Hit a search with no results", "Searched for something we could not find.",
     "SELECT s.person_key, count(*) AS n FROM discovery_events d JOIN sessions_person s ON s.session_id = d.session_id WHERE d.kind = 'no_results' GROUP BY 1"),
    ("Discovery", "filterer", "Filter & sort users", "Used the shop filters or sorting.",
     "SELECT s.person_key, count(*) AS n FROM discovery_events d JOIN sessions_person s ON s.session_id = d.session_id WHERE d.kind IN ('filter', 'sort', 'apply_filters') GROUP BY 1"),
    ("Device", "app_user", "App users", "Used the Android app.", "SELECT coalesce(user_id, visitor_key) AS person_key, count(*) AS n FROM sessions WHERE is_app GROUP BY 1"),
]
# journey stage labels come from users_360.segment (Buyer, Repeat buyer, Abandoned checkout, ...) and quiz concerns from session_concerns:
# both are added by deeper_sql() so they appear alongside the labels above.

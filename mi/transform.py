"""Transform: raw_* -> clean analytics tables, entirely in DuckDB SQL.

Layers (rebuilt from raw on every run; `exclusions` is user data and is never dropped):
  identity_map -> events_base -> exclusion hits -> sessions -> events_clean
  -> checkout / orders_clean -> users_360 -> person_weeks / campaign_performance

Excluded traffic is FLAGGED (is_excluded + excl_reason), never deleted, so the dashboard can toggle it
and exclusions can be edited and re-applied at any time.
"""
import time
from datetime import datetime

from .db import TRANSFORM_LOCK, log_run

# ---------------------------------------------------------------- exclusions (editable user data)
EXCLUSION_KINDS = {
    "name": "Person name (event user_name or account name)",
    "ip": "IP address (end with * for a prefix, e.g. 45.119.*)",
    "session_id": "Session ID",
    "user_id": "User ID (account uuid)",
    "visitor_id": "Browser / visitor ID",
    "phone": "Phone number (last 10 digits)",
    "email": "Email, or @domain.com for a whole domain",
    "host": "Website host (e.g. localhost:5173)",
    "country": "Country",
    "region": "State / region",
    "city": "City",
    "device": "Device (Mobile / Desktop / Tablet)",
    "browser": "Browser",
    "source": "Traffic source (e.g. google, instagram)",
    "campaign": "Campaign name",
    "channel": "Channel (e.g. Paid Google)",
    "any_text": "Anything - matches name, ids, ip, phone, email, page URL, referrer, city",
    "rule": "Built-in rule: staff_roles, admin_pages, dev_hosts, non_india, crawler_ua",
}
DEFAULT_RULES = [
    ("rule", "staff_roles", "Accounts with role admin / rider / doctor, and everything their browsers did"),
    ("rule", "admin_pages", "Any visitor who opened a /admin page is internal staff"),
    ("rule", "dev_hosts", "Vercel preview builds and localhost:<port> dev servers"),
    ("rule", "non_india", "Traffic geolocated outside India (mostly datacenter bots: Mountain View, Ashburn...)"),
    ("rule", "crawler_ua", "Crawlers, headless browsers and link-preview bots (user agent says bot / crawler / headless / externalads ...)"),
    ("rule", "staff_orders", "Orders placed from admin/rider/doctor accounts (team-placed or test orders). Disable if these are real customer orders"),
    ("email", "@roopsee.com", "Company email domain"),
    ("email", "@joinuplyft.com", "Agency / team email domain"),
    ("source", "qa_bot", "QA automation traffic"),
]

DDL_EXCL = """
CREATE SEQUENCE IF NOT EXISTS exclusions_seq;
CREATE TABLE IF NOT EXISTS exclusions (
  id BIGINT PRIMARY KEY DEFAULT nextval('exclusions_seq'), kind VARCHAR NOT NULL, value VARCHAR NOT NULL,
  note VARCHAR, active BOOLEAN DEFAULT TRUE, source VARCHAR DEFAULT 'manual',
  created_at TIMESTAMP DEFAULT now(), updated_at TIMESTAMP DEFAULT now());
CREATE TABLE IF NOT EXISTS etl_meta (k VARCHAR PRIMARY KEY, v VARCHAR);
"""


def seed_exclusions(con) -> None:
    """Insert each built-in default once (tracked in etl_meta) so deleting/disabling one is never undone."""
    con.execute(DDL_EXCL)
    for kind, value, note in DEFAULT_RULES:
        key = f"seed:{kind}:{value}"
        if con.execute("SELECT 1 FROM etl_meta WHERE k=?", [key]).fetchall():
            continue
        if not con.execute("SELECT 1 FROM exclusions WHERE kind=? AND lower(value)=lower(?)", [kind, value]).fetchall():
            con.execute("INSERT INTO exclusions (kind, value, note, source) VALUES (?,?,?, 'default')", [kind, value, note])
        con.execute("INSERT INTO etl_meta VALUES (?, '1')", [key])


# ---------------------------------------------------------------- SQL helpers
def j(path: str) -> str:
    return f"json_extract_string(extra_data, '$.{path}')"


def jj(key: str) -> str:
    """Payload keys live either at top level or under rawBody depending on tracking generation."""
    return f"coalesce(nullif({j(key)},''), nullif({j('rawBody.' + key)},''))"


UUID_RE = "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"

MACROS = r"""
CREATE OR REPLACE MACRO initcap(s) AS array_to_string(list_transform(string_split(lower(s), ' '), lambda x: upper(x[1]) || x[2:]), ' ');
CREATE OR REPLACE MACRO product_kind(n) AS CASE
  WHEN lower(n) LIKE '%sunscreen%' OR lower(n) LIKE '%spf%' THEN 'Sunscreen'
  WHEN lower(n) LIKE '%cleans%' OR lower(n) LIKE '%face wash%' OR lower(n) LIKE '%facewash%' THEN 'Cleanser'
  WHEN lower(n) LIKE '%serum%' OR lower(n) LIKE '%ampoule%' OR lower(n) LIKE '%booster%' OR lower(n) LIKE '%essence%' THEN 'Serum'
  WHEN lower(n) LIKE '%moisturi%' OR lower(n) LIKE '%cream%' OR lower(n) LIKE '%lotion%' THEN 'Moisturiser'
  WHEN lower(n) LIKE '%toner%' OR lower(n) LIKE '%mist%' THEN 'Toner'
  WHEN lower(n) LIKE '%mask%' THEN 'Mask'
  WHEN lower(n) LIKE '%lip%' OR lower(n) LIKE '%tint%' THEN 'Lip'
  WHEN lower(n) LIKE '%shampoo%' OR lower(n) LIKE '%conditioner%' OR lower(n) LIKE '%hair%' THEN 'Hair'
  WHEN lower(n) LIKE '%body%' THEN 'Body'
  WHEN lower(n) LIKE '%kajal%' OR lower(n) LIKE '%eyeliner%' OR lower(n) LIKE '%mascara%' OR lower(n) LIKE '%blush%'
       OR lower(n) LIKE '%foundation%' OR lower(n) LIKE '%concealer%' OR lower(n) LIKE '%compact%' THEN 'Makeup'
  ELSE 'Other' END;
CREATE OR REPLACE MACRO kind_category(k) AS CASE
  WHEN k IN ('Sunscreen','Cleanser','Serum','Moisturiser','Toner','Mask') THEN 'Face'
  WHEN k IN ('Lip','Hair','Body','Makeup') THEN k ELSE 'Other' END;
CREATE OR REPLACE MACRO qs(link, key) AS nullif(url_decode(replace(regexp_extract(link, '[?&]' || key || '=([^&#]*)', 1), '+', ' ')), '');
CREATE OR REPLACE MACRO age_bucket(a) AS CASE
  WHEN a IS NULL OR trim(a) = '' THEN NULL
  WHEN lower(a) LIKE 'under%' OR lower(a) = 'teen' THEN 'Under 18'
  WHEN a LIKE '45%' THEN '45+'
  WHEN a LIKE '35%' THEN '35-44'
  WHEN a LIKE '25%' THEN '25-34'
  WHEN a LIKE '16%' OR a LIKE '18%' OR a = '20' THEN '16-24'
  WHEN lower(a) = 'adult' THEN 'Adult (no range)'
  ELSE 'Other' END;
CREATE OR REPLACE MACRO event_key(e) AS CASE
  WHEN e IN ('order_placed','page_viewed_checkout_success') THEN 'order_placed'
  WHEN e IN ('clicked_pay_now','payment_started','payment_success') THEN 'pay_started'
  WHEN e IN ('page_viewed_checkout','page_view_checkout','clicked_checkout','clicked_checkout_cart_drawer','clicked_my_cart_login_to_checkout') THEN 'checkout_view'
  WHEN e IN ('address_field_filled','clicked_save_address','delivery_location_set') THEN 'address'
  WHEN e = 'checked_delivery_pincode' THEN 'checked_delivery_pincode'
  WHEN e = 'clicked_address_modal_open' THEN 'clicked_address_modal_open'
  WHEN e = 'address_saved' THEN 'address_saved'
  WHEN e IN ('payment_cancelled','payment_failed') THEN 'payment_failed'
  WHEN e = 'login_prompt_shown' THEN 'login_prompt'
  WHEN e = 'add_to_cart' OR e LIKE 'clicked\_add\_to\_cart%' ESCAPE '\' OR e IN ('clicked_buy_now_product_detail','clicked_buy_bundle') THEN 'add_to_cart'
  WHEN e IN ('view_cart','clicked_open_cart','clicked_open_cart_navbar','clicked_view_cart') THEN 'view_cart'
  WHEN e = 'added_to_wishlist' THEN 'wishlist'
  WHEN e IN ('page_viewed_product_detail','page_view_product_detail','product_viewed') OR e LIKE 'page\_view\_products\_%' ESCAPE '\' THEN 'product_view'
  WHEN e IN ('quiz_completed','quiz_submited') THEN 'quiz_completed'
  WHEN e = 'quiz_started' THEN 'quiz_started'
  WHEN e IN ('login_successful','otp_verified','existing_user_login') THEN 'login'
  WHEN e = 'search_performed' THEN 'search'
  WHEN e IN ('assistant_opened','assistant_message_sent') THEN 'assistant'
  WHEN e = 'app_opened' THEN 'app_open'
  ELSE NULL END;
"""

# ---------------------------------------------------------------- pipeline steps
STEP_IDENTITY = f"""
CREATE OR REPLACE TABLE identity_map AS
WITH ev AS (
  SELECT coalesce(nullif(visitor_id,''), {jj('visitorId')}) AS visitor_id,
         coalesce(CASE WHEN regexp_matches(user_id, '{UUID_RE}') THEN lower(user_id) END,
                  CASE WHEN regexp_matches({jj('userId')}, '{UUID_RE}') THEN lower({jj('userId')}) END) AS user_id,
         created_at AS ts
  FROM raw_event_log),
c AS (
  SELECT visitor_id, user_id, count(*) n, max(ts) AS last_ts FROM ev WHERE visitor_id IS NOT NULL AND user_id IS NOT NULL GROUP BY 1,2
  UNION ALL
  SELECT visitor_id, lower(user_id), 0, linked_at FROM raw_visitor_links WHERE visitor_id IS NOT NULL AND user_id IS NOT NULL),
r AS (SELECT visitor_id, user_id, row_number() OVER (PARTITION BY visitor_id ORDER BY n DESC, last_ts DESC NULLS LAST) rn FROM c)
SELECT visitor_id AS visitor_key, user_id FROM r WHERE rn = 1;
"""

STEP_EVENTS_BASE = f"""
CREATE OR REPLACE TABLE events_base AS
WITH p AS (
  SELECT e.id, e.created_at AS ts, e.event_name, e.page_link, e.user_name, e.extra_data, e.value,
    coalesce(nullif(e.session_id,''), {jj('sessionId')}, 'unknown') AS session_id,
    coalesce(nullif(e.visitor_id,''), {jj('visitorId')}) AS visitor_id,
    coalesce(CASE WHEN regexp_matches(e.user_id, '{UUID_RE}') THEN lower(e.user_id) END,
             CASE WHEN regexp_matches({jj('userId')}, '{UUID_RE}') THEN lower({jj('userId')}) END) AS user_id_raw,
    nullif(right(regexp_replace(coalesce(nullif(e.phone_no,''), {jj('phone')}, ''), '[^0-9]', '', 'g'), 10), '') AS phone_raw,
    coalesce(nullif(e.ip_address,''), {jj('ip')}) AS ip,
    CASE upper(coalesce(nullif(e.country,''), {jj('country')}, ''))
      WHEN '' THEN NULL WHEN 'IN' THEN 'India' WHEN 'US' THEN 'United States' WHEN 'SG' THEN 'Singapore'
      WHEN 'CN' THEN 'China' WHEN 'GB' THEN 'United Kingdom' WHEN 'JP' THEN 'Japan'
      ELSE initcap(lower(coalesce(nullif(e.country,''), {jj('country')}))) END AS country_n,
    initcap(lower(coalesce(nullif(trim(e.region),''), {jj('region')}))) AS region_n,
    coalesce(nullif(trim(e.city),''), {jj('city')}) AS city_n,
    coalesce(nullif(e.device,''), {jj('device')}) AS device_n,
    nullif(nullif(e.platform,''), 'Unknown Platform') AS platform_n,
    CASE WHEN e.browser LIKE 'Mozilla/%' THEN CASE WHEN e.browser LIKE '%; wv)%' THEN 'Android WebView' WHEN e.browser LIKE '%Chrome%' THEN 'Chrome' ELSE 'Other' END
         WHEN e.browser = 'Unknown Browser' THEN NULL ELSE nullif(e.browser,'') END AS browser_n,
    coalesce(nullif(e.referrer,''), {jj('referrer')}) AS referrer_raw,
    regexp_matches(lower(coalesce(e.browser, '')), '\\bbot\\b|bot/|crawler|spider|headless|externalads|facebookexternalhit|lighthouse|pagespeed|pingdom') AS is_bot_ua
  FROM raw_event_log e),
q AS (
  SELECT p.*,
    coalesce(p.visitor_id, 'S:' || p.session_id) AS visitor_key,
    coalesce(p.user_id_raw, m.user_id) AS user_id_res,
    CASE WHEN p.page_link LIKE 'Android app:%' THEN 'app.roopsee'
         ELSE lower(regexp_extract(p.page_link, '^https?://([^/?#]+)', 1)) END AS host,
    CASE WHEN p.page_link LIKE 'Android app:%' THEN coalesce(nullif(regexp_replace(trim(substr(p.page_link, 13)), '[?#].*$', ''), ''), '/')
         ELSE coalesce(nullif(regexp_extract(p.page_link, '^https?://[^/?#]+(/[^?#]*)?', 1), ''), '/') END AS path
  FROM p LEFT JOIN identity_map m ON m.visitor_key = p.visitor_id)
,
b0 AS (
SELECT q.id, q.ts, timezone('Asia/Kolkata', q.ts) AS ts_ist, q.event_name, event_key(q.event_name) AS event_key,
  (q.event_name IN ('page_viewed','page_view') OR q.event_name LIKE 'page\\_view\\_%' ESCAPE '\\') AS is_pageview,
  q.session_id, q.visitor_id, q.visitor_key, q.user_id_res AS user_id,
  coalesce(q.user_id_res, q.visitor_key) AS person_key,
  coalesce(q.phone_raw, nullif(right(regexp_replace(coalesce(u.phone_no,''), '[^0-9]', '', 'g'), 10), '')) AS phone10,
  q.ip, q.country_n, q.region_n, q.city_n, q.device_n, q.platform_n, q.browser_n,
  q.user_name, u.name AS account_name, lower(u.email) AS email_l, u.role,
  q.host, q.path,
  (q.page_link LIKE 'Android app:%' OR q.host = 'localhost' OR q.event_name LIKE 'app\\_%' ESCAPE '\\') AS is_app,
  (q.host LIKE '%.vercel.app' OR q.host LIKE 'localhost:%' OR q.host LIKE '127.%') AS is_dev,
  CASE WHEN q.path LIKE '/admin%' THEN 'admin' WHEN q.path = '/' THEN 'home'
       WHEN q.path LIKE '/products/%' THEN 'product' WHEN q.path LIKE '/products%' OR q.path LIKE '/shop-products%' THEN 'shop'
       WHEN q.path LIKE '/skin-quiz%' THEN 'quiz' WHEN q.path LIKE '/checkout%' THEN 'checkout'
       WHEN q.path LIKE '/order-confirm%' THEN 'order_confirm' WHEN q.path LIKE '/login%' THEN 'login'
       WHEN q.path LIKE '/quickfix%' THEN 'quickfix' WHEN q.path LIKE '/festive%' THEN 'festive'
       WHEN q.path LIKE '/makeup%' THEN 'makeup' WHEN q.path LIKE '/tracking%' THEN 'tracking'
       WHEN q.path LIKE '/my-looks%' THEN 'my_looks' ELSE 'other' END AS page_type,
  lower(qs(q.page_link,'utm_source')) AS utm_source, lower(qs(q.page_link,'utm_medium')) AS utm_medium,
  qs(q.page_link,'utm_campaign') AS utm_campaign, qs(q.page_link,'utm_content') AS utm_content,
  qs(q.page_link,'utm_term') AS utm_term, qs(q.page_link,'gad_campaignid') AS gad_campaign,
  regexp_matches(coalesce(q.page_link,''), '[?&]gclid=') AS has_gclid, regexp_matches(coalesce(q.page_link,''), '[?&]fbclid=') AS has_fbclid,
  CASE WHEN q.referrer_raw IS NULL OR lower(q.referrer_raw) = 'direct' THEN NULL
       ELSE regexp_replace(lower(regexp_extract(q.referrer_raw, '^(?:https?://)?([^/?#]+)', 1)), '^www\\.', '') END AS referrer_host,
  q.page_link, {j('order_id')} AS order_id,
  coalesce(nullif({j('productName')},''), {j('items[0].item_name')}) AS product_name,
  coalesce(nullif({j('brand')},''), {j('items[0].item_brand')}) AS brand,
  {j('search_term')} AS search_term, {j('paymentMethod')} AS payment_method,
  coalesce(try_cast({j('grand_total')} AS DOUBLE), try_cast({j('cartTotal')} AS DOUBLE)) AS amount,
  CASE WHEN regexp_matches(trim(coalesce({jj('pincode')}, {jj('addressPincode')}, '')), '^[0-9]{{6}}$')
       THEN trim(coalesce({jj('pincode')}, {jj('addressPincode')})) END AS pincode_ev,
  nullif(trim(coalesce({jj('addressCity')}, {jj('cityName')})), '') AS addr_city_ev,
  nullif(trim(coalesce({jj('addressState')}, {jj('stateName')})), '') AS addr_state_ev,
  try_cast(coalesce({jj('load_ms')}, {jj('loadMs')}) AS DOUBLE) AS load_ms,
  try_cast({jj('dom_ready_ms')} AS DOUBLE) AS dom_ready_ms,
  q.is_bot_ua
FROM q LEFT JOIN raw_users u ON lower(u.id) = q.user_id_res)
-- the tracker often fires one action several times (and one action under several event names): flag every repeat of the
-- same thing in the same session within 2 seconds (1 second for untracked events such as clicks and scrolls). Nothing is deleted; counts use NOT is_dup.
SELECT * EXCLUDE (prev_ts, ev_id),
  (prev_ts IS NOT NULL AND ts - prev_ts <= CASE WHEN event_key IS NOT NULL OR is_pageview THEN INTERVAL 2 SECOND ELSE INTERVAL 1 SECOND END) AS is_dup
FROM (SELECT b0.*, b0.id AS ev_id,
        lag(b0.ts) OVER (PARTITION BY b0.session_id, CASE WHEN b0.is_pageview THEN 'pageview' ELSE coalesce(b0.event_key, b0.event_name) END,
                                      coalesce(b0.product_name, ''), coalesce(b0.order_id, ''), coalesce(b0.path, '')
                         ORDER BY b0.ts, b0.id) AS prev_ts
      FROM b0);
"""

# (kind, join condition on e = events_base row / x = exclusion row, propagate to the whole visitor?)
EXCL_JOINS = [
    ("name", "lower(trim(e.user_name)) = x.v OR lower(trim(e.account_name)) = x.v", True),
    ("ip", "e.ip = x.v OR (x.v LIKE '%*' AND e.ip LIKE replace(x.v, '*', '%'))", False),
    ("session_id", "lower(e.session_id) = x.v", False),
    ("user_id", "e.user_id = x.v", True),
    ("visitor_id", "lower(e.visitor_key) = x.v", True),
    ("phone", "e.phone10 = right(regexp_replace(x.v, '[^0-9]', '', 'g'), 10)", True),
    ("email", "e.email_l = x.v OR (x.v LIKE '@%' AND e.email_l LIKE '%' || x.v)", True),
    ("host", "e.host = x.v", False),
    ("country", "lower(e.country_n) = x.v", False),
    ("region", "lower(e.region_n) = x.v", False),
    ("city", "lower(e.city_n) = x.v", False),
    ("device", "lower(e.device_n) = x.v", False),
    ("browser", "lower(e.browser_n) = x.v", False),
    ("any_text", "strpos(lower(concat_ws('|', e.user_name, e.account_name, e.ip, e.session_id, e.visitor_key, e.user_id, "
                 "e.phone10, e.email_l, e.page_link, e.referrer_host, e.city_n)), x.v) > 0", True),
]
RULE_SQL = [
    ("staff_roles", "e.role IN ('admin','rider','doctor')", True),
    ("admin_pages", "e.page_type = 'admin'", True),
    ("dev_hosts", "e.is_dev", False),
    ("non_india", "e.country_n IS NOT NULL AND e.country_n <> 'India'", False),
    ("crawler_ua", "e.is_bot_ua", False),
]


def step_hits(con) -> None:
    con.execute("CREATE OR REPLACE TEMP TABLE excl AS SELECT kind, lower(trim(value)) AS v FROM exclusions "
                "WHERE active AND trim(value) <> ''")
    con.execute("CREATE OR REPLACE TEMP TABLE hits (id VARCHAR, session_id VARCHAR, visitor_key VARCHAR, "
                "user_id VARCHAR, why VARCHAR, by_visitor BOOLEAN)")
    for kind, cond, byv in EXCL_JOINS:
        if con.execute("SELECT 1 FROM excl WHERE kind=? LIMIT 1", [kind]).fetchone():
            con.execute(f"INSERT INTO hits SELECT e.id, e.session_id, e.visitor_key, e.user_id, '{kind}:' || x.v, "
                        f"{str(byv).upper()} FROM events_base e JOIN excl x ON x.kind = '{kind}' AND ({cond})")
    for rule, cond, byv in RULE_SQL:
        if con.execute("SELECT 1 FROM excl WHERE kind='rule' AND v=?", [rule]).fetchone():
            con.execute(f"INSERT INTO hits SELECT e.id, e.session_id, e.visitor_key, e.user_id, 'rule:{rule}', "
                        f"{str(byv).upper()} FROM events_base e WHERE {cond}")
    con.execute("""
      CREATE OR REPLACE TABLE excluded_sessions AS
        SELECT session_id, string_agg(DISTINCT why, ', ' ORDER BY why) AS reason FROM hits GROUP BY 1;
      CREATE OR REPLACE TABLE excluded_visitors AS
        SELECT visitor_key, string_agg(DISTINCT why, ', ' ORDER BY why) AS reason FROM hits WHERE by_visitor GROUP BY 1;
      CREATE OR REPLACE TABLE manual_sessions AS SELECT DISTINCT session_id FROM hits WHERE why NOT LIKE 'rule:%';
      CREATE OR REPLACE TABLE manual_users AS
        SELECT DISTINCT user_id FROM hits WHERE by_visitor AND user_id IS NOT NULL AND why NOT LIKE 'rule:%';
      CREATE OR REPLACE TABLE excluded_users AS
        SELECT user_id, string_agg(DISTINCT why, ', ' ORDER BY why) AS reason FROM hits
        WHERE by_visitor AND user_id IS NOT NULL GROUP BY 1;""")


STEP_SESSIONS = """
-- pincode -> place, learned from saved addresses and orders
CREATE OR REPLACE TABLE dim_pincode AS
WITH u AS (
  SELECT pincode, initcap(lower(trim(city))) AS city, initcap(lower(trim(state))) AS state FROM (
    SELECT pincode, city, state FROM raw_customer_address WHERE regexp_matches(coalesce(pincode, ''), '^[0-9]{6}$')
    UNION ALL SELECT pincode, city, state FROM raw_orders WHERE regexp_matches(coalesce(pincode, ''), '^[0-9]{6}$'))),
cc AS (SELECT pincode, city, count(*) AS c FROM u WHERE city IS NOT NULL GROUP BY 1, 2),
ss AS (SELECT pincode, state, count(*) AS c FROM u WHERE state IS NOT NULL GROUP BY 1, 2)
SELECT p.pincode, (SELECT first(cc.city ORDER BY cc.c DESC, cc.city) FROM cc WHERE cc.pincode = p.pincode) AS city,
       (SELECT first(ss.state ORDER BY ss.c DESC, ss.state) FROM ss WHERE ss.pincode = p.pincode) AS state
FROM (SELECT DISTINCT pincode FROM u) p;

CREATE OR REPLACE TABLE sessions_pre AS
WITH k AS (
  SELECT session_id, event_key, ts, row_number() OVER (PARTITION BY session_id, event_key ORDER BY ts) rn
  FROM events_base WHERE event_key IS NOT NULL),
keys AS (SELECT session_id, string_agg(event_key, ' > ' ORDER BY ts) AS key_events FROM k WHERE rn = 1 GROUP BY 1),
-- time actually spent: gaps between consecutive events, ignoring idle gaps over 30 minutes (a session id can live for weeks)
gp AS (
  SELECT session_id, coalesce(sum(CASE WHEN g <= 1800 THEN g ELSE 0 END), 0) AS active_s FROM (
    SELECT session_id, epoch(ts) - epoch(lag(ts) OVER (PARTITION BY session_id ORDER BY ts, id)) AS g FROM events_base WHERE NOT is_dup)
  GROUP BY 1),
a AS (
  SELECT session_id, min(ts) AS started_at, max(ts) AS ended_at, count(*) FILTER (WHERE NOT is_dup) AS events, count(*) AS events_raw,
    count(*) FILTER (WHERE is_pageview AND NOT is_dup) AS pageviews,
    arg_min(visitor_key, ts) AS visitor_key, max(user_id) AS user_id,
    arg_min(path, ts) AS landing_path, arg_min(page_type, ts) AS landing_type,
    first(utm_source ORDER BY ts) FILTER (WHERE utm_source IS NOT NULL) AS utm_source,
    first(utm_medium ORDER BY ts) FILTER (WHERE utm_medium IS NOT NULL) AS utm_medium,
    first(utm_campaign ORDER BY ts) FILTER (WHERE utm_campaign IS NOT NULL) AS utm_campaign,
    first(gad_campaign ORDER BY ts) FILTER (WHERE gad_campaign IS NOT NULL) AS gad_campaign,
    first(referrer_host ORDER BY ts) FILTER (WHERE referrer_host IS NOT NULL
        AND referrer_host NOT IN ('roopsee.com','localhost','shop.roopsee.com')) AS referrer_host,
    bool_or(has_gclid) AS has_gclid, bool_or(has_fbclid) AS has_fbclid,
    first(country_n ORDER BY ts) FILTER (WHERE country_n IS NOT NULL) AS country,
    first(region_n ORDER BY ts) FILTER (WHERE region_n IS NOT NULL) AS region,
    first(city_n ORDER BY ts) FILTER (WHERE city_n IS NOT NULL) AS city,
    first(device_n ORDER BY ts) FILTER (WHERE device_n IS NOT NULL) AS device,
    first(platform_n ORDER BY ts) FILTER (WHERE platform_n IS NOT NULL) AS platform,
    first(ip ORDER BY ts) FILTER (WHERE ip IS NOT NULL) AS ip,
    first(phone10 ORDER BY ts) FILTER (WHERE phone10 IS NOT NULL) AS phone10,
    bool_or(is_app) AS is_app, bool_or(is_dev) AS is_dev,
    coalesce(bool_or(event_key = 'product_view'), false) AS f_product, coalesce(bool_or(event_key = 'add_to_cart'), false) AS f_cart,
    coalesce(bool_or(event_key = 'checkout_view'), false) AS f_checkout, coalesce(bool_or(event_key = 'pay_started'), false) AS f_pay,
    coalesce(bool_or(event_key = 'order_placed'), false) AS f_order, coalesce(bool_or(event_key = 'quiz_started'), false) AS f_quiz_start,
    coalesce(bool_or(event_key = 'quiz_completed'), false) AS f_quiz_done, coalesce(bool_or(event_key = 'login'), false) AS f_login,
    coalesce(bool_or(event_key = 'search'), false) AS f_search,
    -- an address was really saved: a save event that carries a valid 6-digit pincode
    coalesce(bool_or(event_name IN ('address_saved', 'clicked_save_address', 'clicked_update_address_button') AND pincode_ev IS NOT NULL), false) AS f_address,
    -- only picked a delivery pincode / location (typed it, searched a place, used current location, chose a saved one)
    coalesce(bool_or(pincode_ev IS NOT NULL OR event_name IN ('delivery_location_set', 'location_search_selected', 'location_search_suggestion_picked',
                                                              'checked_delivery_pincode', 'clicked_use_current_location', 'selected_saved_address')), false) AS f_location,
    last(pincode_ev ORDER BY ts) FILTER (WHERE pincode_ev IS NOT NULL) AS pincode,
    last(addr_city_ev ORDER BY ts) FILTER (WHERE addr_city_ev IS NOT NULL) AS addr_city,
    last(addr_state_ev ORDER BY ts) FILTER (WHERE addr_state_ev IS NOT NULL) AS addr_state,
    bool_or(event_name LIKE 'clicked\\_%' ESCAPE '\\' OR event_name IN ('ui_clicked','page_scrolled','scroll_depth','searchbar_typed','add_to_cart')
            OR event_key IN ('add_to_cart','view_cart','checkout_view','pay_started','order_placed','quiz_started','quiz_completed',
                             'login','search','wishlist','assistant','address')) AS f_interact
  FROM events_base GROUP BY 1),
b AS (
  SELECT a.*, keys.key_events, coalesce(gp.active_s, 0) AS active_s,
    CASE lower(utm_source) WHEN 'ig' THEN 'instagram' WHEN 'fb' THEN 'facebook' WHEN 'wa' THEN 'whatsapp'
         WHEN 'th' THEN 'threads' ELSE lower(utm_source) END AS src_utm,
    CASE WHEN referrer_host LIKE '%instagram.com' THEN 'instagram' WHEN referrer_host LIKE '%facebook.com' THEN 'facebook'
         WHEN referrer_host LIKE '%google.%' OR referrer_host LIKE '%googlequicksearchbox%'
              OR referrer_host LIKE '%doubleclick%' OR referrer_host LIKE '%googlesyndication%' THEN 'google'
         WHEN referrer_host LIKE '%youtube.com' THEN 'youtube' ELSE referrer_host END AS src_ref
  FROM a LEFT JOIN keys USING (session_id) LEFT JOIN gp USING (session_id)),
c AS (
  SELECT b.*,
    coalesce(src_utm, CASE WHEN has_gclid THEN 'google' WHEN has_fbclid THEN 'facebook' END, src_ref, 'direct') AS source,
    coalesce(utm_medium, CASE WHEN has_gclid THEN 'cpc' WHEN has_fbclid THEN 'paid_social'
                              WHEN src_ref IN ('instagram','facebook','youtube') THEN 'social'
                              WHEN src_ref = 'google' THEN 'organic' WHEN src_ref IS NOT NULL THEN 'referral'
                              ELSE 'none' END) AS medium,
    coalesce(utm_campaign, 'gads_' || gad_campaign, '(not set)') AS campaign
  FROM b)
SELECT x.*, CASE WHEN x.channel = 'Direct' THEN CASE WHEN x.is_returning THEN 'Direct (returning)' ELSE 'Direct (new)' END ELSE x.channel END AS channel_split
FROM (
SELECT c.*, min(c.started_at) OVER (PARTITION BY c.visitor_key) < c.started_at AS is_returning,
  coalesce(pc.city, initcap(lower(c.addr_city))) AS delivery_city, coalesce(pc.state, initcap(lower(c.addr_state))) AS delivery_state,
  timezone('Asia/Kolkata', started_at)::DATE AS date_ist,
  CASE WHEN source = 'mygate' THEN 'MyGate Partner'
       WHEN source = 'google' AND (has_gclid OR medium IN ('cpc','ppc','paid')) THEN 'Paid Google'
       WHEN source IN ('instagram','facebook') AND (has_fbclid OR medium LIKE 'paid%' OR medium = 'cpc') THEN 'Paid Meta'
       WHEN medium = 'paid_partner' THEN 'Paid Partner'
       WHEN source IN ('instagram','facebook','youtube','threads','whatsapp') THEN 'Organic Social'
       WHEN source = 'google' THEN 'Organic Search'
       WHEN source = 'direct' THEN 'Direct'
       ELSE 'Referral' END AS channel,
  active_s AS duration_s, epoch(ended_at) - epoch(started_at) AS span_s,
  (pageviews <= 1 AND NOT f_interact) AS is_bounce,
  CASE WHEN f_order THEN 5 WHEN f_pay THEN 4 WHEN f_checkout THEN 3 WHEN f_cart THEN 2 WHEN f_product THEN 1 ELSE 0 END AS stage
FROM c LEFT JOIN dim_pincode pc ON pc.pincode = c.pincode) x;

-- source / campaign / channel exclusions are matched on session attribution
INSERT INTO excluded_sessions
SELECT s.session_id, 'source:' || x.v FROM sessions_pre s JOIN excl x ON x.kind = 'source' AND lower(s.source) = x.v
UNION ALL SELECT s.session_id, 'campaign:' || x.v FROM sessions_pre s JOIN excl x ON x.kind = 'campaign' AND lower(s.campaign) = x.v
UNION ALL SELECT s.session_id, 'channel:' || x.v FROM sessions_pre s JOIN excl x ON x.kind = 'channel' AND lower(s.channel) = x.v;

CREATE OR REPLACE TABLE excluded_sessions AS
SELECT session_id, string_agg(DISTINCT reason, ', ' ORDER BY reason) AS reason FROM excluded_sessions GROUP BY 1;

CREATE OR REPLACE TABLE sessions AS
SELECT s.*,
  (es.session_id IS NOT NULL OR ev.visitor_key IS NOT NULL OR eu.user_id IS NOT NULL) AS is_excluded,
  nullif(concat_ws(' | ', es.reason, ev.reason, eu.reason), '') AS excl_reason
FROM sessions_pre s
LEFT JOIN excluded_sessions es ON es.session_id = s.session_id
LEFT JOIN excluded_visitors ev ON ev.visitor_key = s.visitor_key
LEFT JOIN excluded_users eu ON eu.user_id = s.user_id;
DROP TABLE sessions_pre;
"""

STEP_EVENTS_CLEAN = """
-- a view, not a second copy of every event: it adds the hidden-traffic flag to events_base when read
CREATE VIEW events_clean AS
SELECT e.*,
  (es.session_id IS NOT NULL OR ev.visitor_key IS NOT NULL OR eu.user_id IS NOT NULL) AS is_excluded
FROM events_base e
LEFT JOIN excluded_sessions es ON es.session_id = e.session_id
LEFT JOIN excluded_visitors ev ON ev.visitor_key = e.visitor_key
LEFT JOIN excluded_users eu ON eu.user_id = e.user_id;
"""

STEP_ORDERS = """
CREATE OR REPLACE TABLE orders_clean AS
WITH om AS (  -- order -> session via the order_placed event when the order row has no session_id
  SELECT order_id, arg_min(session_id, ts) AS session_id FROM events_base
  WHERE order_id IS NOT NULL AND event_key = 'order_placed' GROUP BY 1),
o AS (
  SELECT lower(o.id) AS order_id, lower(o.user_id) AS user_id, o.created_at AS ts, timezone('Asia/Kolkata', o.created_at) AS ts_ist,
    timezone('Asia/Kolkata', o.created_at)::DATE AS date_ist,
    o.total, try_cast(o.products_total AS DOUBLE) AS products_total, o.status, o.payment_status, o.payment_method,
    o.coupon_code, initcap(lower(trim(o.city))) AS city, initcap(lower(trim(o.state))) AS state, o.pincode,
    right(regexp_replace(coalesce(o.phone,''), '[^0-9]', '', 'g'), 10) AS phone10, lower(o.email) AS email_l,
    coalesce(nullif(o.session_id,''), om.session_id) AS session_id, o.visitor_id,
    CASE WHEN o.items IS NULL THEN 0 ELSE json_array_length(o.items) END AS items_count,
    (coalesce(o.items::VARCHAR,'') ILIKE '%test product%' OR coalesce(o.total, 0) <= 1) AS is_test,
    (o.status NOT IN ('payment_cancelled','payment_pending')) AS is_placed,
    o.name AS customer_name, try_cast(o.delivery_fee AS DOUBLE) AS delivery_fee, try_cast(o.handling_fee AS DOUBLE) AS handling_fee,
    try_cast(o.coupon_discount AS DOUBLE) AS coupon_discount, o.discount AS discount, o.savings AS savings, o.wallet_amount_used,
    o.cashback_amount, o.cashback_percent, o.payment_failed_reason, o.paid_at, o.delivered_at,
    try_cast(json_extract_string(o.metadata, '$.picked_up_at') AS TIMESTAMPTZ) AS picked_up_at,
    try_cast(json_extract_string(o.metadata, '$.delivery_started_at') AS TIMESTAMPTZ) AS delivery_started_at,
    try_cast(json_extract_string(o.metadata, '$.cod_collected_at') AS TIMESTAMPTZ) AS cod_collected_at,
    o.rider_id, o.courier_partner, o.tracking_id
  FROM raw_orders o LEFT JOIN om ON om.order_id = lower(o.id))
SELECT o.*, (o.is_placed AND NOT o.is_test) AS is_valid,
  CASE WHEN NOT o.is_placed THEN 'not_placed'
       WHEN o.payment_status = 'success' OR o.paid_at IS NOT NULL OR o.cod_collected_at IS NOT NULL THEN 'confirmed'
       WHEN upper(coalesce(o.payment_method, '')) = 'COD' AND o.payment_status = 'pending' THEN 'cod_pending'
       WHEN o.payment_status = 'cancelled' THEN 'conflicting'
       ELSE 'unconfirmed' END AS payment_state,
  CASE WHEN coalesce(s.channel, 'Direct') = 'Direct' AND nd.started_at >= o.ts - INTERVAL 7 DAY THEN nd.session_id ELSE o.session_id END AS credit_session_id,
  CASE WHEN coalesce(s.channel, 'Direct') = 'Direct' AND nd.started_at >= o.ts - INTERVAL 7 DAY THEN nd.channel ELSE s.channel END AS credit_channel,
  CASE WHEN coalesce(s.channel, 'Direct') = 'Direct' AND nd.started_at >= o.ts - INTERVAL 7 DAY THEN nd.campaign ELSE s.campaign END AS credit_campaign,
  CASE WHEN o.is_placed AND NOT o.is_test THEN o.total ELSE 0 END AS revenue,
  s.channel, s.source, s.medium, s.campaign, s.device, s.is_app, rd.name AS rider_name,
  CASE WHEN o.is_placed AND NOT o.is_test
       THEN count(*) FILTER (WHERE o.is_placed AND NOT o.is_test) OVER (PARTITION BY o.user_id ORDER BY o.ts) END AS nth_order,
  (o.user_id IN (SELECT lower(id) FROM raw_users WHERE role IN ('admin','rider','doctor'))) AS is_staff_order,
  coalesce(o.is_test
   OR (o.user_id IN (SELECT lower(id) FROM raw_users WHERE role IN ('admin','rider','doctor')) AND EXISTS (SELECT 1 FROM excl WHERE kind = 'rule' AND v = 'staff_orders'))
   OR o.user_id IN (SELECT user_id FROM manual_users)
   OR o.session_id IN (SELECT session_id FROM manual_sessions)
   OR o.phone10 IN (SELECT right(regexp_replace(v, '[^0-9]', '', 'g'), 10) FROM excl WHERE kind = 'phone')
   OR EXISTS (SELECT 1 FROM excl x WHERE x.kind = 'email' AND (o.email_l = x.v OR (x.v LIKE '@%' AND o.email_l LIKE '%' || x.v))),
   FALSE) AS is_excluded
FROM o LEFT JOIN sessions s ON s.session_id = o.session_id LEFT JOIN raw_users rd ON lower(rd.id) = lower(o.rider_id)
ASOF LEFT JOIN (SELECT coalesce(user_id, visitor_key) AS person_key, started_at, session_id, channel, campaign FROM sessions
                WHERE channel <> 'Direct' AND NOT is_excluded) nd
  ON nd.person_key = coalesce(o.user_id, s.visitor_key) AND o.ts >= nd.started_at;

-- per-session order totals, computed once here instead of on every Sessions request
CREATE OR REPLACE TABLE session_orders AS
SELECT session_id, count(*) FILTER (WHERE NOT is_test) AS n_orders, count(*) FILTER (WHERE is_valid) AS n_placed,
  sum(total) FILTER (WHERE is_valid AND NOT is_test) AS order_value, sum(total) FILTER (WHERE NOT is_valid AND NOT is_test) AS other_value,
  string_agg(DISTINCT status, ', ' ORDER BY status) FILTER (WHERE NOT is_test) AS statuses, max(email_l) FILTER (WHERE email_l IS NOT NULL) AS order_email
FROM orders_clean WHERE session_id IS NOT NULL GROUP BY 1;

-- which event names each session contains (powers the "had event" filter and event-name search on Sessions)
CREATE OR REPLACE TABLE session_events AS SELECT DISTINCT session_id, event_name FROM events_base;

-- page speed samples (the tracker reports load time on each page load)
CREATE OR REPLACE TABLE perf_samples AS
SELECT timezone('Asia/Kolkata', ts)::DATE AS date_ist, page_type, CASE WHEN is_app THEN 'Android app' ELSE coalesce(device_n, 'Unknown') END AS device,
       load_ms, dom_ready_ms, is_excluded
FROM events_clean WHERE event_name = 'page_load_sample' AND load_ms IS NOT NULL AND load_ms >= 0 AND load_ms < 120000;
"""

STEP_PRODUCTS = """
CREATE OR REPLACE TABLE dim_products AS
SELECT product_uid AS product_id, product_name, brand, category_l1, product_type_l2 AS product_type, mrp, selling_price
FROM raw_catalog_roopsee WHERE product_uid IS NOT NULL
UNION ALL
SELECT product_id, product_name, brand, category_l1, category_l2, mrp, selling_price
FROM raw_catalog_master WHERE product_id IS NOT NULL AND product_id NOT IN (SELECT product_uid FROM raw_catalog_roopsee WHERE product_uid IS NOT NULL);

-- one row per product line on every order (order flags copied from orders_clean so the same filters apply).
-- Order lines use several product-id schemes; brand / kind fall back to the name stored on the line.
CREATE OR REPLACE TABLE order_lines AS
WITH l AS (SELECT lower(o.id) AS order_id, unnest(from_json(o.items, '["JSON"]')) AS j FROM raw_orders o WHERE o.items IS NOT NULL),
brands AS (  -- one spelling per brand (the alphabetically first), so "AXIS-Y" and "Axis-Y" never flip between rebuilds
  SELECT b, min(brand) AS brand FROM (
    SELECT DISTINCT lower(trim(brand)) AS b, trim(brand) AS brand FROM dim_products WHERE brand IS NOT NULL AND length(trim(brand)) > 2
    UNION
    SELECT DISTINCT lower(trim(json_extract_string(j, '$.brand_name'))), trim(json_extract_string(j, '$.brand_name')) FROM l
    WHERE length(trim(coalesce(json_extract_string(j, '$.brand_name'), ''))) > 2) GROUP BY b),
x AS (
  SELECT c.order_id, c.user_id, c.ts, c.date_ist, c.is_valid, c.is_excluded, c.is_staff_order, c.total AS order_total, c.items_count,
    json_extract_string(l.j, '$.id') AS product_id,
    coalesce(nullif(json_extract_string(l.j, '$.name'), ''), d.product_name, 'Unknown product') AS product_name,
    nullif(json_extract_string(l.j, '$.brand_name'), '') AS brand_raw,
    d.brand AS brand_cat, d.category_l1 AS cat_cat, d.product_type AS type_cat,
    coalesce(try_cast(json_extract_string(l.j, '$.qty') AS INTEGER), 1) AS qty,
    coalesce(try_cast(json_extract_string(l.j, '$.price') AS DOUBLE), 0) AS price,
    (d.product_id IS NOT NULL) AS in_catalog
  FROM l JOIN orders_clean c ON c.order_id = l.order_id
  LEFT JOIN dim_products d ON d.product_id = json_extract_string(l.j, '$.id'))
SELECT x.order_id, x.user_id, x.ts, x.date_ist, x.is_valid, x.is_excluded, x.is_staff_order, x.order_total, x.items_count,
  x.product_id, x.product_name,
  coalesce(x.brand_raw, x.brand_cat, (SELECT bl.brand FROM brands bl WHERE lower(x.product_name) LIKE bl.b || '%' ORDER BY length(bl.b) DESC LIMIT 1), 'Unknown') AS brand,
  coalesce(x.cat_cat, kind_category(product_kind(x.product_name))) AS category,
  replace(initcap(coalesce(x.type_cat, product_kind(x.product_name))), 'Moisturizer', 'Moisturiser') AS product_type,
  (x.cat_cat IS NULL) AS type_inferred,
  x.qty, x.price, x.price * x.qty AS line_total, x.in_catalog
FROM x;
"""

STEP_META = """
-- every id / name Meta knows for a campaign -> that campaign (ambiguous keys are dropped, never guessed)
CREATE OR REPLACE TABLE meta_ids AS
SELECT key, max(campaign_id) AS campaign_id FROM (
  SELECT campaign_id AS key, campaign_id FROM raw_meta_insights
  UNION ALL SELECT adset_id, campaign_id FROM raw_meta_insights
  UNION ALL SELECT ad_id, campaign_id FROM raw_meta_insights
  UNION ALL SELECT lower(trim(campaign_name)), campaign_id FROM raw_meta_insights WHERE campaign_name IS NOT NULL
  UNION ALL SELECT entity_id, coalesce(campaign_id, entity_id) FROM raw_meta_entities
  UNION ALL SELECT lower(trim(name)), entity_id FROM raw_meta_entities WHERE entity_type = 'campaign' AND name IS NOT NULL)
WHERE key IS NOT NULL GROUP BY key HAVING count(DISTINCT campaign_id) = 1;

-- our sessions that came from a Meta campaign we can identify (utm_campaign holds the campaign id, name, or an ad-set / ad id)
CREATE OR REPLACE TABLE session_meta AS
SELECT s.session_id, max(m.campaign_id) AS meta_campaign_id
FROM sessions s JOIN meta_ids m ON m.key = s.campaign OR m.key = lower(trim(s.campaign))
WHERE s.source IN ('facebook', 'instagram') GROUP BY s.session_id;
"""

STEP_CHECKOUT = """
CREATE OR REPLACE TABLE checkout AS
WITH e AS (
  SELECT session_id,
    min(ts) FILTER (WHERE event_key = 'checkout_view') AS checkout_at,
    min(ts) FILTER (WHERE event_key = 'pay_started') AS pay_at,
    min(ts) FILTER (WHERE event_key = 'order_placed') AS order_at,
    max(amount) FILTER (WHERE event_key IN ('checkout_view','pay_started','order_placed')) AS cart_value,
    max(payment_method) FILTER (WHERE payment_method IS NOT NULL) AS payment_method,
    max(order_id) AS order_id, bool_or(event_key = 'address') AS address_entered
  FROM events_base WHERE event_key IN ('checkout_view','pay_started','order_placed','address') GROUP BY 1)
SELECT s.session_id, s.person_key_dummy AS person_key, s.user_id, s.phone10, s.channel, s.campaign, s.device, s.city,
  e.checkout_at, e.pay_at, e.order_at, e.cart_value, e.payment_method, e.address_entered, e.order_id,
  CASE WHEN e.order_at IS NOT NULL THEN 'ordered' WHEN e.pay_at IS NOT NULL THEN 'payment_abandoned'
       WHEN e.checkout_at IS NOT NULL THEN 'checkout_abandoned' ELSE 'address_only' END AS outcome,
  o.status AS order_status, o.revenue, s.is_excluded
FROM (SELECT *, coalesce(user_id, visitor_key) AS person_key_dummy FROM sessions) s
JOIN e USING (session_id)
LEFT JOIN orders_clean o ON o.order_id = lower(e.order_id) OR o.session_id = s.session_id;
"""

STEP_USERS = """
CREATE OR REPLACE TABLE users_360 AS
SELECT u0.*, CASE WHEN u0.phone10 IS NOT NULL THEN min(u0.person_key) OVER (PARTITION BY u0.phone10) END AS phone_group FROM (
WITH sp AS (SELECT *, coalesce(user_id, visitor_key) AS person_key FROM sessions),
dl AS (  -- where they want delivery: saved address first, else the latest order, else a pincode typed in a session
  SELECT p.person_key, coalesce(sa.pincode, lo.pincode, ls.pincode) AS pincode, (sa.pincode IS NOT NULL) AS has_saved_address,
         coalesce(sa.city, lo.city, ls.city) AS city, coalesce(sa.state, lo.state, ls.state) AS state
  FROM (SELECT DISTINCT person_key, user_id FROM sp) p
  LEFT JOIN (SELECT lower(user_id) AS user_id, pincode, city, state, row_number() OVER (PARTITION BY lower(user_id) ORDER BY is_default DESC NULLS LAST, created_at DESC) rn
             FROM raw_customer_address WHERE regexp_matches(coalesce(pincode, ''), '^[0-9]{6}$')) sa ON sa.user_id = p.user_id AND sa.rn = 1
  LEFT JOIN (SELECT user_id, pincode, city, state, row_number() OVER (PARTITION BY user_id ORDER BY ts DESC) rn FROM orders_clean
             WHERE regexp_matches(coalesce(pincode, ''), '^[0-9]{6}$')) lo ON lo.user_id = p.user_id AND lo.rn = 1
  LEFT JOIN (SELECT person_key, pincode, delivery_city AS city, delivery_state AS state, row_number() OVER (PARTITION BY person_key ORDER BY started_at DESC) rn
             FROM sp WHERE pincode IS NOT NULL) ls ON ls.person_key = p.person_key AND ls.rn = 1),
agg AS (
  SELECT person_key, max(user_id) AS user_id, min(started_at) AS first_seen, max(ended_at) AS last_seen,
    count(*) AS sessions, sum(events) AS events, sum(pageviews) AS pageviews,
    arg_min(channel, started_at) AS first_channel, arg_min(campaign, started_at) AS first_campaign,
    arg_min(source, started_at) AS first_source, arg_min(medium, started_at) AS first_medium, min(date_ist) AS first_date,
    arg_min(landing_type, started_at) AS first_landing,
    max(phone10) FILTER (WHERE phone10 IS NOT NULL) AS phone10, bool_or(is_app) AS uses_app,
    count(*) FILTER (WHERE f_product) AS product_sessions, count(*) FILTER (WHERE f_cart) AS cart_sessions,
    count(*) FILTER (WHERE f_checkout) AS checkout_sessions, count(*) FILTER (WHERE f_quiz_done) AS quiz_sessions,
    bool_or(f_cart) AS ever_cart, bool_or(f_checkout) AS ever_checkout, bool_or(f_quiz_done) AS ever_quiz,
    bool_or(f_login) AS ever_login, bool_and(is_excluded) AS all_excluded, max(visitor_key) AS visitor_key
  FROM sp GROUP BY 1),
mv AS (  -- most common value of each attribute per person; ties go to the alphabetically first value, so a rebuild never changes the answer
  SELECT person_key, k, v, count(*) AS c FROM (
    SELECT person_key, 'city' AS k, city AS v FROM sp UNION ALL SELECT person_key, 'state', region FROM sp UNION ALL SELECT person_key, 'country', country FROM sp
    UNION ALL SELECT person_key, 'device', device FROM sp UNION ALL SELECT person_key, 'platform', platform FROM sp) WHERE v IS NOT NULL GROUP BY 1, 2, 3),
mvt AS (
  SELECT person_key, first(v ORDER BY c DESC, v) FILTER (WHERE k = 'city') AS city, first(v ORDER BY c DESC, v) FILTER (WHERE k = 'state') AS state,
         first(v ORDER BY c DESC, v) FILTER (WHERE k = 'country') AS country, first(v ORDER BY c DESC, v) FILTER (WHERE k = 'device') AS device,
         first(v ORDER BY c DESC, v) FILTER (WHERE k = 'platform') AS platform FROM mv GROUP BY 1),
agg2 AS (SELECT agg.*, mvt.city, mvt.state, mvt.country, mvt.device, mvt.platform FROM agg LEFT JOIN mvt USING (person_key)),
ord AS (
  SELECT coalesce(o.user_id, s.person_key) AS person_key, count(*) FILTER (WHERE o.is_valid) AS orders,
    sum(o.revenue) AS revenue, max(o.ts) FILTER (WHERE o.is_valid) AS last_order_at,
    arg_max(o.state, o.ts) AS order_state, arg_max(o.city, o.ts) AS order_city  -- where they last ordered
  FROM orders_clean o LEFT JOIN (SELECT DISTINCT session_id, person_key FROM sp) s ON s.session_id = o.session_id
  WHERE NOT o.is_test GROUP BY 1),
q AS (
  SELECT person_key, gender, skin_type, age_bucket FROM (
    SELECT sp.person_key, q.gender, q.skin_type, age_bucket(q.age) AS age_bucket,
      row_number() OVER (PARTITION BY sp.person_key ORDER BY coalesce(q.created_at, q.completed_at) DESC NULLS LAST) rn
    FROM raw_quiz_results q
    JOIN (SELECT DISTINCT person_key, user_id, session_id FROM sp) sp
      ON (q.user_id IS NOT NULL AND lower(q.user_id) = sp.user_id) OR (q.guest_session_id IS NOT NULL AND q.guest_session_id = sp.session_id))
  WHERE rn = 1)
SELECT a.person_key, a.user_id, u.name, nullif(coalesce(a.phone10, right(regexp_replace(coalesce(u.phone_no,''), '[^0-9]', '', 'g'), 10)), '') AS phone10,
  u.email, u.role, u.created_at AS signed_up_at, (a.user_id IS NOT NULL) AS is_registered,
  a.first_seen, a.last_seen, a.sessions, a.events, a.pageviews,
  a.first_channel, a.first_campaign, a.first_source, a.first_medium, a.first_date, a.first_landing,
  coalesce(initcap(lower(dl.city)), a.city, od.order_city) AS city, coalesce(initcap(lower(dl.state)), a.state, od.order_state) AS state, a.city AS ip_city, a.country,
  dl.pincode AS delivery_pincode, coalesce(dl.has_saved_address, FALSE) AS has_saved_address, a.device, a.platform, a.uses_app,
  a.product_sessions, a.cart_sessions, a.checkout_sessions, a.quiz_sessions,
  coalesce(od.orders, 0) AS orders, coalesce(od.revenue, 0) AS revenue, od.last_order_at,
  CASE WHEN coalesce(od.orders, 0) > 0 THEN od.revenue / od.orders END AS aov,
  coalesce(q.gender, nullif(lower(u.gender),'')) AS gender, coalesce(q.skin_type, u.skin_type) AS skin_type, q.age_bucket,
  CASE WHEN coalesce(od.orders, 0) >= 2 THEN 'Repeat buyer'
       WHEN coalesce(od.orders, 0) = 1 THEN 'Buyer'
       WHEN a.ever_checkout THEN 'Abandoned checkout'
       WHEN a.ever_cart THEN 'Cart, no checkout'
       WHEN a.ever_quiz THEN 'Quiz done, no cart'
       WHEN a.product_sessions > 0 THEN 'Engaged browser'
       ELSE 'Visitor' END AS segment,
  coalesce(a.all_excluded OR a.user_id IN (SELECT user_id FROM excluded_users) OR a.visitor_key IN (SELECT visitor_key FROM excluded_visitors), FALSE) AS is_excluded
FROM agg2 a
LEFT JOIN raw_users u ON lower(u.id) = a.user_id
LEFT JOIN ord od ON od.person_key = a.person_key
LEFT JOIN q ON q.person_key = a.person_key
LEFT JOIN dl ON dl.person_key = a.person_key) u0;

CREATE OR REPLACE TABLE person_weeks AS
SELECT DISTINCT coalesce(user_id, visitor_key) AS person_key, date_trunc('week', timezone('Asia/Kolkata', started_at))::DATE AS week
FROM sessions;

CREATE OR REPLACE TABLE campaign_performance AS
WITH so AS (  -- orders credited to the session they happened in (last touch)
  SELECT s2.date_ist, s2.channel, s2.source, s2.medium, s2.campaign, count(*) AS orders, sum(oc.revenue) AS revenue
  FROM orders_clean oc JOIN sessions s2 ON s2.session_id = oc.session_id
  WHERE oc.is_valid AND NOT oc.is_excluded GROUP BY ALL),
ft AS (  -- orders credited to the buyer's FIRST session (first touch): who actually brought the customer
  SELECT u.first_date AS date_ist, u.first_channel AS channel, u.first_source AS source, u.first_medium AS medium,
         u.first_campaign AS campaign, count(*) AS orders, sum(oc.revenue) AS revenue
  FROM orders_clean oc JOIN users_360 u ON u.user_id = oc.user_id
  WHERE oc.is_valid AND NOT oc.is_excluded GROUP BY ALL)
,
lnd AS (  -- orders credited to the last non-Direct visit in the 7 days before the order
  SELECT cs.date_ist, cs.channel, cs.source, cs.medium, cs.campaign, count(*) AS orders, sum(oc.revenue) AS revenue
  FROM orders_clean oc JOIN sessions cs ON cs.session_id = oc.credit_session_id
  WHERE oc.is_valid AND NOT oc.is_excluded GROUP BY ALL)
SELECT s.date_ist, s.channel, s.source, s.medium, s.campaign, s.is_excluded,
  count(*) AS sessions, count(DISTINCT s.visitor_key) AS visitors,
  count(*) FILTER (WHERE s.events >= 5 OR s.f_product) AS engaged_sessions,
  count(*) FILTER (WHERE s.f_quiz_done) AS quiz_done, count(*) FILTER (WHERE s.f_cart) AS carts,
  count(*) FILTER (WHERE s.f_checkout) AS checkouts,
  coalesce(max(so.orders), 0) AS orders, coalesce(max(so.revenue), 0) AS revenue,
  coalesce(max(ft.orders), 0) AS ft_orders, coalesce(max(ft.revenue), 0) AS ft_revenue,
  coalesce(max(lnd.orders), 0) AS lnd_orders, coalesce(max(lnd.revenue), 0) AS lnd_revenue
FROM sessions s
LEFT JOIN so ON so.date_ist = s.date_ist AND so.channel = s.channel AND so.source = s.source AND so.medium = s.medium AND so.campaign = s.campaign
LEFT JOIN ft ON ft.date_ist = s.date_ist AND ft.channel = s.channel AND ft.source = s.source AND ft.medium = s.medium AND ft.campaign = s.campaign
LEFT JOIN lnd ON lnd.date_ist = s.date_ist AND lnd.channel = s.channel AND lnd.source = s.source AND lnd.medium = s.medium AND lnd.campaign = s.campaign
GROUP BY ALL;
"""


def _log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def run(con, flags_only: bool = False, progress=None) -> dict:
    """Rebuild every derived table from raw.

    The whole rebuild is ONE transaction: dashboard queries keep reading the previous tables (consistent snapshot) and switch
    to the new ones the instant it commits, so a refresh never freezes the dashboard. `progress(message)` reports the current step."""
    note = progress or (lambda m: None)
    with TRANSFORM_LOCK:
        t0 = time.time()
        con.execute("BEGIN TRANSACTION")
        try:
            return _run_steps(con, flags_only, note, t0)
        except BaseException:
            con.execute("ROLLBACK")
            raise


def _drop_any(con, name: str) -> None:
    """Drop `name` whether it currently exists as a table or as a view."""
    if con.execute("SELECT 1 FROM duckdb_tables() WHERE table_name = ?", [name]).fetchall():
        con.execute(f"DROP TABLE {name}")
    if con.execute("SELECT 1 FROM duckdb_views() WHERE view_name = ? AND NOT internal", [name]).fetchall():
        con.execute(f"DROP VIEW {name}")


def _run_steps(con, flags_only, note, t0) -> dict:
    seed_exclusions(con)
    con.execute(MACROS)
    # exclusions never change events_base / identity_map, so an exclusion edit can skip the two slowest steps
    have_base = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'events_base'").fetchall()[0][0] > 0
    steps = [] if (flags_only and have_base) else [("identity_map", STEP_IDENTITY), ("events_base", STEP_EVENTS_BASE)]
    for name, sql in steps:
        t = time.time()
        note(f"rebuilding: {name}")
        con.execute(sql)
        _log(f"{name}: {time.time() - t:.1f}s")
    t = time.time(); note("rebuilding: exclusion hits"); step_hits(con); _log(f"exclusion hits: {time.time() - t:.1f}s")
    for name, sql in [("sessions", STEP_SESSIONS), ("events_clean", STEP_EVENTS_CLEAN), ("orders_clean", STEP_ORDERS), ("products / order lines", STEP_PRODUCTS), ("meta links", STEP_META),
                      ("checkout", STEP_CHECKOUT), ("users_360 / cohorts / campaigns", STEP_USERS)]:
        t = time.time()
        note(f"rebuilding: {name}")
        if name == "events_clean":
            _drop_any(con, "events_clean")  # older builds stored it as a table
        con.execute(sql)
        _log(f"{name}: {time.time() - t:.1f}s")
    con.execute("DROP TABLE IF EXISTS events_base_x")
    stats = {
        "events": con.execute("SELECT count(*) FROM events_clean").fetchone()[0],
        "events_excluded": con.execute("SELECT count(*) FROM events_clean WHERE is_excluded").fetchone()[0],
        "sessions": con.execute("SELECT count(*) FROM sessions").fetchone()[0],
        "sessions_excluded": con.execute("SELECT count(*) FROM sessions WHERE is_excluded").fetchone()[0],
        "people": con.execute("SELECT count(*) FROM users_360").fetchone()[0],
        "seconds": round(time.time() - t0, 1),
    }
    con.execute("INSERT OR REPLACE INTO etl_meta VALUES ('last_transform', ?)", [datetime.now().isoformat(timespec="seconds")])
    note("publishing the new tables")
    con.execute("COMMIT")
    _log(f"transform done {stats}")
    log_run(con, "transform", datetime.fromtimestamp(t0), stats["events"], f"{stats['sessions']} sessions, {stats['people']} people, {stats['seconds']}s")
    return stats

"""SQL for the tables behind Ads & landing pages, Journeys › More detail and the Audiences groups (built by the rebuild, mi/transform.py).

Which ad / landing product a visit came from, its concerns and products, discovery (search / filter) events, quiz progress, the pay-to-confirmation
steps, and the people labels (segments). The definitions to edit are in mi/deeper_defs.py.
"""
from . import deeper_defs as D
from .transform import _q, jj


def _kw(words) -> str:
    return "|".join(w.replace("'", "''") for w in words)


QUIZ_EXTRA = {"Dryness & hydration": ["dry", "dehydrat"], "Pigmentation & glow": ["tan", "dull", "dark circle", "dark-spot", "dark_spot"], "Anti-ageing": ["aging", "ageing", "fine line"],
              "Oil control & pores": ["oil", "pore"], "Acne & blemishes": ["acne", "breakout", "blemish"], "Sun protection": ["sun"]}


def deeper_sql() -> str:
    quiz_case = "CASE " + " ".join(f"WHEN regexp_matches(lower(c), {_q(_kw(D.CONCERN_KEYWORDS[k] + QUIZ_EXTRA.get(k, [])))}) THEN {_q(k)}" for k in D.CONCERN_KEYWORDS) \
        + " ELSE initcap(replace(c, '_', ' ')) END"
    inferred = "\nUNION ALL\n".join(
        f"SELECT session_id, {_q(k)} AS concern, 'inferred' AS source, count(*) AS n FROM session_products "
        f"WHERE (viewed OR carted OR ordered) AND regexp_matches(lower(product_name), {_q(_kw(w))}) GROUP BY 1"
        for k, w in D.CONCERN_KEYWORDS.items())
    labels = "\nUNION ALL\n".join(
        f"SELECT x.person_key, {_q(key)} AS label_key, x.n::BIGINT AS n FROM ({sql.replace('{b}', str(D.BUDGET_MAX)).replace('{m}', str(D.MID_MAX))}) x"
        for _g, key, _t, _d, sql in D.LABELS)
    return f"""
CREATE OR REPLACE TABLE sessions_person AS SELECT session_id, coalesce(user_id, visitor_key) AS person_key FROM sessions;

-- the ad (Meta ad id in utm_content, ad set in utm_term) a visit came from
CREATE OR REPLACE TABLE session_attrib AS
SELECT session_id, first(utm_content ORDER BY ts) FILTER (WHERE utm_content IS NOT NULL) AS ad_id, first(utm_term ORDER BY ts) FILTER (WHERE utm_term IS NOT NULL) AS adset_id
FROM events_base GROUP BY 1 HAVING count(utm_content) > 0;

-- the product page a visit landed on (the path holds the product id, or a slug that ends with it)
CREATE OR REPLACE TABLE session_landing_product AS
WITH k AS (SELECT session_id, url_decode(regexp_extract(landing_path, '/products/([^/?#]+)', 1)) AS slug FROM sessions WHERE landing_type = 'product'),
m AS (SELECT session_id, slug, nullif(upper(replace(regexp_extract(slug, '--(.*)$', 1), '-', '/')), '') AS alt FROM k WHERE slug <> '')
SELECT * EXCLUDE (rn) FROM (
  SELECT m.session_id, d.product_id, d.product_name, d.brand, d.images, row_number() OVER (PARTITION BY m.session_id ORDER BY (d.product_id = m.slug) DESC, d.product_id) AS rn
  FROM m JOIN dim_products d ON d.product_id = m.slug OR d.product_id = m.alt) WHERE rn = 1;

-- products a visit looked at, added to the cart and bought
CREATE OR REPLACE TABLE session_products AS
WITH ev AS (SELECT session_id, min(product_name) AS product_name, bool_or(event_key = 'product_view') AS viewed, bool_or(event_key = 'add_to_cart') AS carted
            FROM events_base WHERE NOT is_dup AND event_key IN ('product_view', 'add_to_cart') AND coalesce(product_name, '') <> '' GROUP BY session_id, lower(product_name)),
od AS (SELECT o.session_id, min(l.product_name) AS product_name FROM order_lines l JOIN orders_clean o ON o.order_id = l.order_id
       WHERE l.is_valid AND o.session_id IS NOT NULL GROUP BY o.session_id, lower(l.product_name))
SELECT coalesce(ev.session_id, od.session_id) AS session_id, coalesce(ev.product_name, od.product_name) AS product_name,
  coalesce(ev.viewed, false) AS viewed, coalesce(ev.carted, false) AS carted, od.session_id IS NOT NULL AS ordered
FROM ev FULL JOIN od ON ev.session_id = od.session_id AND lower(ev.product_name) = lower(od.product_name);

-- the skin concern of a visit: from the quiz answers when the visitor took the quiz, otherwise inferred from the products they looked at
CREATE OR REPLACE TABLE session_concerns AS
WITH q AS (SELECT e.session_id, unnest(regexp_extract_all(coalesce({jj('skin_concerns')}, ''), '["'']([^"'']+)["'']')) AS c
           FROM events_base e JOIN raw_event_log r ON r.id = e.id WHERE e.event_name IN ('quiz_completed', 'quiz_updated', 'quiz_submited')),
q2 AS (SELECT session_id, lower(trim(replace(replace(c, '"', ''), '''', ''))) AS c FROM q)
SELECT session_id, {quiz_case} AS concern, 'quiz' AS source, count(*) AS n FROM q2 WHERE c NOT IN ('', 'none') GROUP BY 1, 2
UNION ALL
{inferred};

-- searches, searches with no result, result clicks, filters and sorting
CREATE OR REPLACE TABLE discovery_events AS
SELECT e.session_id, e.ts,
  CASE e.event_name WHEN 'search_performed' THEN 'search' WHEN 'search_no_results_found' THEN 'no_results' WHEN 'shop_no_results_found' THEN 'no_results'
    WHEN 'clicked_search_result_product' THEN 'result_click' WHEN 'search_abandoned' THEN 'search_abandon' WHEN 'search_suggestion_selected' THEN 'suggestion'
    WHEN 'clicked_sort_applied' THEN 'sort' WHEN 'clicked_apply_filters' THEN 'apply_filters' ELSE 'filter' END AS kind,
  regexp_replace(lower(trim(coalesce(nullif({jj('search_term')}, ''), nullif({jj('search')}, ''), nullif({jj('last_search_term')}, '')))), '\\s+', ' ', 'g') AS term,
  coalesce(nullif({jj('sortBy')}, ''), nullif({jj('filterValue')}, ''), nullif({jj('appliedFilters')}, ''), nullif({jj('value')}, '')) AS value,
  {jj('filterType')} AS filter_type, try_cast({jj('results_count')} AS INTEGER) AS results, {jj('search_source')} AS source, e.product_name
FROM events_base e JOIN raw_event_log r ON r.id = e.id
WHERE NOT e.is_dup AND e.event_name IN ('search_performed', 'search_no_results_found', 'shop_no_results_found', 'clicked_search_result_product', 'search_abandoned', 'search_suggestion_selected',
  'clicked_filter_option', 'clicked_sort_applied', 'clicked_apply_filters', 'clicked_product_filter_brand', 'product_filter_brand_clicked', 'clicked_skin_type_filter', 'clicked_product_filter_product_type');

-- how far each visit got in the skin quiz
CREATE OR REPLACE TABLE quiz_sessions AS
SELECT e.session_id, min(e.ts) AS first_ts, max(e.ts) AS last_ts, bool_or(e.event_key = 'quiz_completed') AS completed,
  bool_or(e.event_name IN ('quiz_abandoned', 'dropping_from_quiz_page')) AS abandoned,
  max(try_cast({jj('step')} AS INTEGER)) FILTER (WHERE e.event_name = 'clicked_quiz_option') AS max_step,
  max(try_cast({jj('drop_step')} AS INTEGER)) FILTER (WHERE e.event_name IN ('quiz_abandoned', 'dropping_from_quiz_page')) AS drop_step,
  min(e.ts) FILTER (WHERE e.event_key = 'quiz_completed') AS done_ts,
  max(nullif({jj('selected_program')}, '')) FILTER (WHERE e.event_key = 'quiz_completed') AS program,
  max(nullif({jj('skin_type')}, '')) AS skin_type, max(nullif({jj('life_stage')}, '')) AS life_stage
FROM events_base e JOIN raw_event_log r ON r.id = e.id
WHERE NOT e.is_dup AND (e.event_name IN ('quiz_started', 'quiz_answer_filled', 'clicked_quiz_option', 'quiz_abandoned', 'dropping_from_quiz_page', 'quiz_updated') OR e.event_key = 'quiz_completed')
GROUP BY 1;

CREATE OR REPLACE TABLE quiz_steps AS
SELECT e.session_id, try_cast({jj('step')} AS INTEGER) AS step, max({jj('question')}) AS question
FROM events_base e JOIN raw_event_log r ON r.id = e.id WHERE NOT e.is_dup AND e.event_name = 'clicked_quiz_option' AND try_cast({jj('step')} AS INTEGER) IS NOT NULL GROUP BY 1, 2;

-- pay tap -> payment started -> payment window -> paid -> order confirmed
CREATE OR REPLACE TABLE pay_sessions AS
SELECT e.session_id,
  min(e.ts) FILTER (WHERE e.event_name = 'clicked_pay_now') AS t_pay, min(e.ts) FILTER (WHERE e.event_name = 'payment_started') AS t_started,
  min(e.ts) FILTER (WHERE e.event_name = 'razorpay_opened') AS t_window, min(e.ts) FILTER (WHERE e.event_name = 'payment_completed') AS t_paid,
  min(e.ts) FILTER (WHERE e.event_key = 'order_placed') AS t_order,
  max(try_cast({jj('secondsInPopup')} AS DOUBLE)) FILTER (WHERE e.event_name = 'payment_completed') AS popup_s,
  max(lower({jj('paymentMethod')})) AS payment_method
FROM events_base e JOIN raw_event_log r ON r.id = e.id
WHERE NOT e.is_dup AND e.event_name IN ('clicked_pay_now', 'payment_started', 'razorpay_opened', 'payment_completed', 'order_placed', 'page_viewed_checkout_success') GROUP BY 1;

-- the typical price of what a person looks at (catalogue price of the products they viewed or added)
CREATE OR REPLACE TABLE person_price AS
SELECT e.person_key, median(d.selling_price) AS median_price, count(*) AS n
FROM events_base e JOIN (SELECT lower(product_name) AS nm, max(selling_price) AS selling_price FROM dim_products WHERE selling_price > 0 GROUP BY 1) d ON d.nm = lower(e.product_name)
WHERE NOT e.is_dup AND e.event_key IN ('product_view', 'add_to_cart') GROUP BY 1;

-- the people labels (segments)
CREATE OR REPLACE TABLE user_labels AS
SELECT person_key, label_key, n FROM (
{labels}
UNION ALL SELECT person_key, 'stage:' || lower(replace(segment, ' ', '_')), 1 FROM users_360
UNION ALL SELECT sp.person_key, 'concern:' || c.concern, sum(c.n) FROM session_concerns c JOIN sessions_person sp ON sp.session_id = c.session_id WHERE c.source = 'quiz' GROUP BY 1, 2
) WHERE person_key IN (SELECT person_key FROM users_360);  -- a few events carry an id the sessions do not: those people are not listed
"""

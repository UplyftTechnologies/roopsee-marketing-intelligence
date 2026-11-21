"""SQL for the journey_sessions table: one row per visit with a yes/no for every step of every journey (definitions: mi/journey_defs.py).

Built by the rebuild after the pain-point, login, chat and deeper-analysis tables, which it reuses (pain_sessions, pain_ordered, logins, quiz_sessions,
discovery_events, chat_messages).
"""
from .transform import _q

LOGIN_ASK = ["login_prompt_shown", "login_popup_shown", "page_viewed_login", "clicked_login", "clicked_checkout_login", "clicked_my_cart_login_to_checkout"]
QUIZ_OPEN = ["page_viewed_skin_quiz", "page_view_skin_quiz", "clicked_skin_quiz_cta", "clicked_nav_skin_quiz", "clicked_on_skin_quiz"]
ADDRESS_READY = ["address_saved", "selected_saved_address"]


def _in(names) -> str:
    return ", ".join(_q(n) for n in names)


def journey_sql() -> str:
    return f"""
CREATE OR REPLACE TABLE journey_sessions AS
WITH e AS (
  SELECT session_id,
    bool_or(event_key = 'product_view') AS view_item, bool_or(event_key = 'add_to_cart') AS add_to_cart, bool_or(event_key = 'view_cart') AS view_cart,
    bool_or(event_name IN ({_in(ADDRESS_READY)})) AS address_ready, bool_or(event_name = 'clicked_payment_method') AS chose_pay, bool_or(event_name = 'clicked_pay_now') AS tapped_pay,
    bool_or(event_name IN ({_in(LOGIN_ASK)})) AS login_ask, bool_or(event_name IN ({_in(QUIZ_OPEN)})) AS quiz_open,
    bool_or(event_name = 'assistant_opened') AS chat_open, bool_or(event_name = 'assistant_message_sent') AS chat_ask, bool_or(event_name = 'assistant_product_clicked') AS chat_click
  FROM events_base WHERE NOT is_dup GROUP BY 1),
d AS (
  SELECT session_id, bool_or(kind = 'search') AS searched, bool_or(kind = 'search' AND coalesce(results, 0) > 0) AS had_results, bool_or(kind = 'result_click') AS clicked
  FROM discovery_events GROUP BY 1),
c AS (SELECT session_id, count(*) AS n, bool_or(error IS NULL) AS answered FROM chat_messages WHERE session_id IS NOT NULL GROUP BY 1)
SELECT s.session_id, sp.person_key,
  -- purchase
  true AS purchase_visited, (coalesce(e.view_item, false) OR s.f_product) AS purchase_view_item, (coalesce(e.add_to_cart, false) OR s.f_cart) AS purchase_add_to_cart,
  coalesce(e.view_cart, false) AS purchase_view_cart, s.f_checkout AS purchase_checkout, s.f_pay AS purchase_pay_started, po.ordered AS purchase_purchase,
  -- checkout (only visits that got to checkout: a login or an address elsewhere on the site is not a checkout step)
  (s.f_checkout OR s.f_pay OR po.ordered) AS checkout_opened, ((s.f_checkout OR s.f_pay OR po.ordered) AND (s.user_id IS NOT NULL OR s.f_login)) AS checkout_logged_in,
  ((s.f_checkout OR s.f_pay OR po.ordered) AND (coalesce(e.address_ready, false) OR s.f_address)) AS checkout_address,
  ((s.f_checkout OR s.f_pay OR po.ordered) AND coalesce(e.chose_pay, false)) AS checkout_chose_pay, ((s.f_checkout OR s.f_pay OR po.ordered) AND (coalesce(e.tapped_pay, false) OR s.f_pay)) AS checkout_tapped_pay,
  ((s.f_checkout OR s.f_pay OR po.ordered) AND po.ordered) AS checkout_ordered,
  -- login & sign-up
  (coalesce(ps.lp_opened, false) OR coalesce(ps.lp_sent, false) OR coalesce(e.login_ask, false) OR coalesce(ps.g_click, false)) AS login_asked,
  (coalesce(ps.lp_sent, false) OR coalesce(ps.g_click, false)) AS login_otp_sent, (coalesce(ps.lp_entered, false) OR coalesce(ps.g_click, false)) AS login_otp_entered,
  (coalesce(ps.lp_phone_done, false) OR coalesce(ps.g_done, false) OR lg.session_id IS NOT NULL) AS login_logged_in, coalesce(lg.is_new, false) AS login_new_account,
  -- skin quiz
  (coalesce(e.quiz_open, false) OR qz.session_id IS NOT NULL) AS quiz_opened, qz.session_id IS NOT NULL AS quiz_started, coalesce(qz.completed, false) AS quiz_finished,
  (coalesce(qz.completed, false) AND (s.user_id IS NOT NULL OR s.f_login)) AS quiz_saved, (coalesce(qz.completed, false) AND s.f_cart) AS quiz_add_to_cart,
  (coalesce(qz.completed, false) AND po.ordered) AS quiz_ordered,
  -- search & discovery
  coalesce(d.searched, false) AS search_searched, coalesce(d.had_results, false) AS search_results, coalesce(d.clicked, false) AS search_clicked,
  (coalesce(d.searched, false) AND s.f_cart) AS search_add_to_cart, (coalesce(d.searched, false) AND po.ordered) AS search_ordered,
  -- Roop chat
  (coalesce(e.chat_open, false) OR coalesce(c.n, 0) > 0) AS chat_opened, (coalesce(e.chat_ask, false) OR coalesce(c.n, 0) > 0) AS chat_asked, coalesce(c.answered, false) AS chat_answered,
  coalesce(e.chat_click, false) AS chat_clicked, ((coalesce(e.chat_ask, false) OR coalesce(c.n, 0) > 0) AND s.f_cart) AS chat_add_to_cart,
  ((coalesce(e.chat_ask, false) OR coalesce(c.n, 0) > 0) AND po.ordered) AS chat_ordered
FROM sessions s JOIN sessions_person sp ON sp.session_id = s.session_id JOIN pain_ordered po ON po.session_id = s.session_id
LEFT JOIN pain_sessions ps ON ps.session_id = s.session_id LEFT JOIN e ON e.session_id = s.session_id LEFT JOIN d ON d.session_id = s.session_id
LEFT JOIN quiz_sessions qz ON qz.session_id = s.session_id LEFT JOIN c ON c.session_id = s.session_id LEFT JOIN logins lg ON lg.session_id = s.session_id;
"""

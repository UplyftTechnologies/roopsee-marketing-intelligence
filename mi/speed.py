"""Page speed: every visit that ran into a slow or broken moment.

  slow_page_load  a page took over 3 s to show (the tracker's slow_page_load event, or a load sample over 3 s)
  slow_api        a request to our server took over 5 s
  api_failed      a request to our server failed
  app_error       something on the page broke
"""
from fastapi import HTTPException

from .core import app, one, q, sess_where
from .sessions import FLAG_ORDER

PROBLEMS = {"slow_page_load": "Slow page (over 3 s)", "slow_api": "Slow request (over 5 s)", "api_failed": "Request failed", "app_error": "Page error"}
SLOW_MS = 3000

_CTE = f"""WITH p AS (
  SELECT session_id, problem_key AS k, path, ms, detail FROM pain_events WHERE stage = 'speed'
  UNION ALL
  SELECT session_id, 'slow_page_load', path, load_ms, NULL FROM events_clean WHERE event_name = 'page_load_sample' AND load_ms > {SLOW_MS} AND load_ms < 120000 AND NOT is_dup),
g AS (
  SELECT session_id, list_sort(list(DISTINCT k)) AS problems,
    count(DISTINCT path) AS pages_hit, (list_sort(list(DISTINCT path) FILTER (WHERE path IS NOT NULL)))[1:5] AS pages,
    count(DISTINCT path) FILTER (WHERE k = 'slow_page_load') AS slow_pages, max(ms) FILTER (WHERE k = 'slow_page_load') AS worst_load_ms,
    count(*) FILTER (WHERE k = 'slow_api') AS slow_requests, max(ms) FILTER (WHERE k = 'slow_api') AS worst_request_ms,
    count(*) FILTER (WHERE k = 'api_failed') AS failed_requests, count(*) FILTER (WHERE k = 'app_error') AS errors,
    (list_sort(list(DISTINCT detail) FILTER (WHERE detail IS NOT NULL)))[1:3] AS details
  FROM p GROUP BY 1)"""
_FROM = """ FROM sessions s JOIN g ON g.session_id = s.session_id
  LEFT JOIN session_orders o ON o.session_id = s.session_id LEFT JOIN users_360 u ON u.person_key = coalesce(s.user_id, s.visitor_key)"""


@app.get("/api/speed/sessions")
def speed_sessions(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, problem: str | None = None, limit: int = 5000):
    """The affected visits, newest first, and how many visits had each kind of problem. `problem` narrows the list to one kind."""
    if problem and problem not in PROBLEMS:
        raise HTTPException(400, f"problem must be one of {list(PROBLEMS)}")
    if not q("SELECT 1 FROM information_schema.tables WHERE table_name = 'pain_events'"):
        return {"ready": False}
    w, a = sess_where(date_from, date_to, include_excluded)
    counts = ", ".join(f"count(*) FILTER (WHERE list_contains(g.problems, '{k}')) AS {k}" for k in PROBLEMS)
    summary = one(f"{_CTE} SELECT count(*) AS affected, {counts}, count(*) FILTER (WHERE {FLAG_ORDER}) AS ordered {_FROM} WHERE {w}", a)
    all_visits = one(f"SELECT count(*) AS n, count(*) FILTER (WHERE {FLAG_ORDER}) AS ordered FROM sessions s LEFT JOIN session_orders o ON o.session_id = s.session_id WHERE {w}", a)
    pw, pa = (" AND list_contains(g.problems, ?)", [problem]) if problem else ("", [])
    total = one(f"{_CTE} SELECT count(*) AS n {_FROM} WHERE {w}{pw}", [*a, *pa])["n"]
    rows = q(f"""{_CTE} SELECT s.session_id, s.started_at, s.duration_s, u.name, s.phone10, s.city, CASE WHEN s.is_app THEN 'App' ELSE s.device END AS device, s.channel, s.landing_path,
                 g.problems, g.pages_hit, g.pages, g.slow_pages, g.worst_load_ms, g.slow_requests, g.worst_request_ms, g.failed_requests, g.errors, g.details,
                 ({FLAG_ORDER}) AS ordered {_FROM} WHERE {w}{pw} ORDER BY s.started_at DESC, s.session_id LIMIT ?""", [*a, *pa, max(1, min(int(limit), 5000))])
    clean = all_visits["n"] - summary["affected"]
    return {"ready": True, "labels": PROBLEMS, "summary": {**summary, "visits": all_visits["n"],
                                                           "order_rate_hit": summary["ordered"] / summary["affected"] if summary["affected"] else None,
                                                           "order_rate_clean": (all_visits["ordered"] - summary["ordered"]) / clean if clean else None},
            "total": total, "rows": rows}

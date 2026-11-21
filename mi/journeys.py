"""Journeys: every journey a shopper can take, as a funnel, with what went wrong and who stopped, plus a browser of individual journeys.

Mirrors the Shopper journeys tab of the admin analytics on roopsee.com and adds Search, Roop chat and After the order. The steps are in mi/journey_defs.py;
the yes/no per step and visit is the journey_sessions table (mi/journey_sql.py). A person (or visit) reached a step when they did it or any LATER step.
Visits, hidden traffic and the device filter follow the global filters like every other page.
"""
from statistics import median

from fastapi import HTTPException

from . import journey_defs as D
from .core import app, one, prev_range, q, ratio, sess_where
from .sessions import FLAG_ORDER

STAGE_NAME = ["Browsed", "Looked at a product", "Added to cart", "Reached checkout", "Started paying", "Ordered"]
ENTRY_LABEL = {"quiz": "took the quiz", "login": "asked to log in", "search": "searched", "chat": "used Roop", "checkout": "reached checkout", "purchase": "visited"}
UNITS = ("people", "sessions")
CART_STEP = {"purchase": 2, "checkout": 0, "quiz": 4, "search": 3, "chat": 4}


def _ready() -> bool:
    return bool(q("SELECT 1 FROM information_schema.tables WHERE table_name = 'journey_sessions'"))


def _spec(journey: str) -> dict:
    if journey not in D.JOURNEYS:
        raise HTTPException(400, f"journey must be one of {D.JOURNEY_KEYS}")
    return D.JOURNEYS[journey]


def _reach(journey: str, i: int) -> str:
    """SQL: the visit reached step i, or any later step of the journey."""
    steps = _spec(journey)["steps"]
    return "(" + " OR ".join(f"j.{D.column(journey, k)}" for k, _ in steps[i:]) + ")"


def _where(d_from, d_to, include_excluded, channel=None):
    w, a = sess_where(d_from, d_to, include_excluded)
    if channel:
        w += " AND s.channel = ?"
        a.append(channel)
    return w, a


FROM = "FROM journey_sessions j JOIN sessions s ON s.session_id = j.session_id LEFT JOIN pain_sessions ps ON ps.session_id = j.session_id"


def _funnel_counts(journey: str, w: str, a: list, by: str) -> dict:
    """Per step: reached, and stopped here (reached it, not the next step, never bought). People or visits."""
    steps = _spec(journey)["steps"]
    n = len(steps)
    r = [_reach(journey, i) for i in range(n)]
    bought = "j.purchase_purchase"
    cart_step = CART_STEP.get(journey)  # the step from which an abandoned cart is worth following up (none for login)
    if by == "people":
        sel = ", ".join(f"bool_or({r[i]}) AS r{i}" for i in range(n))
        row = one(f"""WITH p AS (SELECT j.person_key, {sel}, bool_or({bought}) AS bought, max(coalesce(ps.cart_value, 0)) AS cart {FROM} WHERE {w} GROUP BY 1)
                      SELECT {', '.join(f'count(*) FILTER (WHERE r{i}) AS c{i}' for i in range(n))},
                             {', '.join(f'count(*) FILTER (WHERE r{i} AND NOT r{i + 1} AND NOT bought) AS x{i}' for i in range(n - 1))},
                             {f"coalesce(sum(cart) FILTER (WHERE r{cart_step} AND NOT bought), 0)" if cart_step is not None else "0"} AS cart_risk FROM p""", a)
    else:
        row = one(f"""SELECT {', '.join(f'count(*) FILTER (WHERE {r[i]}) AS c{i}' for i in range(n))},
                             {', '.join(f'count(*) FILTER (WHERE {r[i]} AND NOT {r[i + 1]} AND NOT {bought}) AS x{i}' for i in range(n - 1))},
                             {f"coalesce(sum(ps.cart_value) FILTER (WHERE {r[cart_step]} AND NOT {bought}), 0)" if cart_step is not None else "0"} AS cart_risk {FROM} WHERE {w}""", a)
    return {"reached": [row[f"c{i}"] or 0 for i in range(n)], "stopped": [row[f"x{i}"] or 0 for i in range(n - 1)] + [0], "cart_risk": float(row["cart_risk"] or 0)}


def _wrong(journey: str, w: str, a: list) -> dict:
    """What went wrong for visits of this journey that did not get through."""
    steps = _spec(journey)["steps"]
    entry = _reach(journey, 0)
    if journey in ("purchase", "checkout", "login"):
        stages = {"purchase": "('login', 'address', 'order', 'payment', 'speed')", "checkout": "('login', 'address', 'order', 'payment')", "login": "('login')"}[journey]
        gone = f"NOT j.{D.column(journey, steps[-1][0])}" if journey != "login" else f"NOT j.{D.column('login', 'logged_in')}"
        rows = q(f"""SELECT pe.label AS name, pe.label, count(DISTINCT pe.session_id) AS count FROM pain_events pe JOIN journey_sessions j ON j.session_id = pe.session_id
                     JOIN sessions s ON s.session_id = pe.session_id WHERE {w} AND pe.is_hard AND pe.stage IN {stages} AND {entry} AND {gone} GROUP BY 1, 2 ORDER BY 3 DESC, 1 LIMIT 10""", a)
        return {"title": "What went wrong", "sub": "problems recorded in visits of this journey that did not get through (a visit can have several)", "items": rows}
    if journey == "quiz":
        rows = q(f"""SELECT 'step ' || z.drop_step AS name, 'Left on step ' || z.drop_step || coalesce(': ' || max(st.question), '') AS label, count(DISTINCT z.session_id) AS count
                     FROM quiz_sessions z JOIN sessions s ON s.session_id = z.session_id LEFT JOIN quiz_steps st ON st.session_id = z.session_id AND st.step = z.drop_step
                     WHERE {w} AND z.drop_step IS NOT NULL AND NOT z.completed GROUP BY z.drop_step ORDER BY z.drop_step""", a)
        nl = one(f"SELECT count(*) AS n {FROM} WHERE {w} AND j.quiz_finished AND NOT j.quiz_saved", a)["n"]
        if nl:
            rows.append({"name": "unsaved", "label": "Finished but never logged in (the result is not saved to an account)", "count": nl})
        return {"title": "Where the quiz lost people", "sub": "the step people left on, and finishers whose result was never saved", "items": rows}
    if journey == "search":
        rows = q(f"""SELECT d.term AS name, d.term AS label, count(*) AS count FROM discovery_events d JOIN sessions s ON s.session_id = d.session_id
                     WHERE {w} AND d.kind = 'no_results' AND coalesce(d.term, '') <> '' GROUP BY 1 ORDER BY 3 DESC, 1 LIMIT 10""", a)
        return {"title": "Searched for, not found", "sub": "the words that returned nothing", "items": rows}
    rows = q(f"""SELECT c.failure AS name, c.failure AS label, count(*) AS count FROM chat_messages c JOIN sessions s ON s.session_id = c.session_id
                 WHERE {w} AND c.error IS NOT NULL GROUP BY 1 ORDER BY 2 DESC""", a)
    cna = one(f"SELECT count(*) AS n FROM chat_messages c JOIN sessions s ON s.session_id = c.session_id WHERE {w} AND c.could_not_answer", a)["n"]
    if cna:
        rows.append({"name": "cna", "label": "Roop could not fully answer", "count": cna})
    return {"title": "Where Roop fell short", "sub": "messages that failed, and answers that said Roop could not help", "items": rows}


def _funnel_out(journey: str, counts: dict) -> list:
    steps = _spec(journey)["steps"]
    reached, stopped = counts["reached"], counts["stopped"]
    return [{"key": k, "label": lb, "count": reached[i], "of_first": ratio(reached[i], reached[0]), "of_prev": ratio(reached[i], reached[i - 1]) if i else 1,
             "stopped": stopped[i]} for i, (k, lb) in enumerate(steps)]


@app.get("/api/journeys/meta")
def journeys_meta():
    """The journeys and their steps (for the tab headings and the how-it-is-counted boxes)."""
    out = [{"key": k, "label": d["label"], "blurb": d["blurb"], "steps": [{"key": s, "label": lb} for s, lb in d["steps"]], "how": d["how"]} for k, d in D.JOURNEYS.items()]
    out.append({"key": "after_order", "label": D.AFTER_ORDER["label"], "blurb": D.AFTER_ORDER["blurb"], "steps": [{"key": s, "label": lb} for s, lb in D.AFTER_ORDER["steps"]], "how": D.AFTER_ORDER["how"]})
    return {"journeys": out, "ready": _ready()}


@app.get("/api/journeys/funnel")
def journeys_funnel(journey: str = "purchase", date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, by: str = "people",
                    channel: str | None = None, compare: bool = False):
    """One journey: the funnel (people or visits), the biggest drop, what stopped people, and the same funnel for the period before."""
    if not _ready():
        return {"ready": False}
    spec = _spec(journey)
    if by not in UNITS:
        raise HTTPException(400, f"by must be one of {list(UNITS)}")
    w, a = _where(date_from, date_to, include_excluded, channel)
    counts = _funnel_counts(journey, w, a, by)
    funnel = _funnel_out(journey, counts)
    drops = [(f["of_prev"], i) for i, f in enumerate(funnel) if i and funnel[i - 1]["count"] >= 20]
    big = None
    if drops:
        rate, i = min(drops)
        big = {"from": funnel[i - 1]["label"], "to": funnel[i]["label"], "rate": rate, "lost": funnel[i - 1]["count"] - funnel[i]["count"]}
    out = {"ready": True, "journey": journey, "label": spec["label"], "by": by, "funnel": funnel, "biggest_drop": big, "cart_at_risk": counts["cart_risk"],
           "entry": funnel[0]["count"], "final": funnel[-1]["count"], "conversion": ratio(funnel[-1]["count"], funnel[0]["count"]),
           "stopped_total": sum(counts["stopped"]), "wrong": _wrong(journey, w, a)}
    pr = prev_range(date_from, date_to) if compare else None
    if pr:
        pw, pa = _where(pr[0], pr[1], include_excluded, channel)
        pc = _funnel_counts(journey, pw, pa, by)
        out["prev"] = {"range": pr, "reached": pc["reached"], "cart_at_risk": pc["cart_risk"]}
    return out


@app.get("/api/journeys/people")
def journeys_people(journey: str, step: str, date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, channel: str | None = None,
                    only_reachable: bool = False, limit: int = 100):
    """People who got to `step` of a journey but no further and never bought in these dates: newest first, with how to reach them."""
    if not _ready():
        return {"total": 0, "people": []}
    steps = _spec(journey)["steps"]
    keys = [k for k, _ in steps]
    if step not in keys or step == keys[-1]:
        raise HTTPException(400, f"step must be one of {keys[:-1]}")
    i = keys.index(step)
    w, a = _where(date_from, date_to, include_excluded, channel)
    reach = " AND nullif(u.phone10, '') IS NOT NULL" if only_reachable else ""
    rows = q(f"""WITH p AS (SELECT j.person_key, bool_or({_reach(journey, i)}) AS r, bool_or({_reach(journey, i + 1)}) AS r1, bool_or(j.purchase_purchase) AS bought, max(s.ended_at) AS last_seen,
                             max(coalesce(ps.cart_value, 0)) AS cart, count(*) AS visits, arg_max(s.session_id, s.started_at) AS session_id {FROM} WHERE {w} GROUP BY 1)
                 SELECT p.person_key, p.last_seen, p.cart, p.visits, p.session_id, u.name, u.phone10, u.city, u.segment, u.is_registered
                 FROM p LEFT JOIN users_360 u ON u.person_key = p.person_key WHERE p.r AND NOT p.r1 AND NOT p.bought{reach}
                 ORDER BY p.last_seen DESC""", a)
    return {"journey": journey, "step": step, "step_label": steps[i][1], "total": len(rows), "people": rows[:max(1, min(int(limit), 1000))]}


# ------------------------------------------------------------------ after the order
@app.get("/api/journeys/after_order")
def journeys_after_order(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, compare: bool = False):
    """Order placed -> picked up -> out for delivery -> delivered, with typical times and the orders that are stuck."""
    def one_range(lo, hi):
        ex = "" if include_excluded else " AND NOT o.is_excluded"
        rows = q(f"""SELECT o.order_id, o.ts, o.customer_name, o.phone10, o.status, o.payment_state, o.payment_method, o.total, o.city, o.picked_up_at, o.delivery_started_at, o.delivered_at, o.paid_at, o.cod_collected_at
                     FROM orders_clean o WHERE o.is_valid AND o.date_ist BETWEEN ? AND ?{ex} ORDER BY o.ts""", [lo or "2000-01-01", hi or "2999-12-31"])
        return rows
    rows = one_range(date_from, date_to)
    latest = one("SELECT max(created_at) AS t FROM raw_event_log").get("t")
    hrs = lambda a, b: (b - a).total_seconds() / 3600 if a and b else None  # noqa: E731
    reach = [lambda r: True, lambda r: bool(r["picked_up_at"] or r["delivery_started_at"] or r["delivered_at"]), lambda r: bool(r["delivery_started_at"] or r["delivered_at"]), lambda r: bool(r["delivered_at"])]
    steps = D.AFTER_ORDER["steps"]
    counts = [sum(1 for r in rows if f(r)) for f in reach]
    med = lambda xs: round(median(xs), 1) if xs else None  # noqa: E731
    times = {"placed_to_picked_up": med([h for r in rows if (h := hrs(r["ts"], r["picked_up_at"])) is not None and h >= 0]),
             "picked_up_to_out": med([h for r in rows if (h := hrs(r["picked_up_at"], r["delivery_started_at"])) is not None and h >= 0]),
             "out_to_delivered": med([h for r in rows if (h := hrs(r["delivery_started_at"], r["delivered_at"])) is not None and h >= 0]),
             "placed_to_delivered": med([h for r in rows if (h := hrs(r["ts"], r["delivered_at"])) is not None and h >= 0])}
    buckets = {"Within a day": 0, "1 to 2 days": 0, "2 to 3 days": 0, "Over 3 days": 0}
    for r in rows:
        h = hrs(r["ts"], r["delivered_at"])
        if h is not None and h >= 0:
            buckets["Within a day" if h <= 24 else "1 to 2 days" if h <= 48 else "2 to 3 days" if h <= 72 else "Over 3 days"] += 1
    stuck = []
    for r in rows:
        age = hrs(r["ts"], latest) if latest else None
        if not r["delivered_at"] and age is not None and age > 48 and r["status"] not in ("completed",):
            stuck.append({"order_id": r["order_id"], "ts": r["ts"], "customer_name": r["customer_name"], "phone10": r["phone10"], "status": r["status"], "payment_state": r["payment_state"],
                          "total": r["total"], "city": r["city"], "age_hours": round(age, 0)})
    stuck.sort(key=lambda x: -x["age_hours"])
    by_pay = {}
    for r in rows:
        k = "Cash on delivery" if str(r["payment_method"] or "").upper().startswith("COD") else "Online"
        d = by_pay.setdefault(k, {"name": k, "orders": 0, "delivered": 0, "hours": []})
        d["orders"] += 1
        h = hrs(r["ts"], r["delivered_at"])
        if h is not None and h >= 0:
            d["delivered"] += 1
            d["hours"].append(h)
    funnel = [{"key": k, "label": lb, "count": counts[i], "of_first": ratio(counts[i], counts[0]), "of_prev": ratio(counts[i], counts[i - 1]) if i else 1, "stopped": (counts[i] - counts[i + 1]) if i + 1 < len(counts) else 0}
              for i, (k, lb) in enumerate(steps)]
    out = {"ready": True, "funnel": funnel, "times": times, "buckets": [{"name": k, "count": v} for k, v in buckets.items()], "stuck": stuck[:100], "stuck_total": len(stuck),
           "payment": [{"name": d["name"], "orders": d["orders"], "delivered": d["delivered"], "median_hours": med(d["hours"])} for d in by_pay.values()],
           "confirmed": sum(1 for r in rows if r["payment_state"] == "confirmed"), "orders": len(rows), "by_status": sorted([{"name": k, "count": sum(1 for r in rows if r["status"] == k)} for k in {r["status"] for r in rows}], key=lambda x: -x["count"])}
    pr = prev_range(date_from, date_to) if compare else None
    if pr:
        prow = one_range(pr[0], pr[1])
        out["prev"] = {"range": pr, "reached": [sum(1 for r in prow if f(r)) for f in reach]}
    return out


# ------------------------------------------------------------------ every journey
OUTCOME_STAGE = {"ordered": 5, "paying": 4, "checkout": 3, "cart": 2, "product": 1, "browsed": 0}
SORTS = {"started_at": "s.started_at", "duration": "s.duration_s", "events": "s.events", "order_value": "coalesce(o.order_value, 0)", "channel": "s.channel", "city": "nullif(lower(s.city), '')"}
PSORTS = {"last_seen": "max(s.started_at)", "first_seen": "min(s.started_at)", "visits": "count(*)", "revenue": "coalesce(any_value(u.revenue), 0)", "orders": "coalesce(any_value(u.orders), 0)"}
STAGE_EXPR = f"CASE WHEN {FLAG_ORDER} THEN 5 ELSE s.stage END"
ENTERED = [("login", "login_asked", "Login"), ("quiz", "quiz_opened", "Quiz"), ("search", "search_searched", "Search"), ("chat", "chat_asked", "Roop")]


@app.get("/api/journeys/explore")
def journeys_explore(mode: str = "visits", date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, outcome: str | None = None,
                     journey: str | None = None, reached: str | None = None, stuck: bool = False, channel: str | None = None, search: str | None = None,
                     sort: str = "started_at", direction: str = "desc", limit: int = 50, offset: int = 0):
    """Individual journeys. mode=visits: one row per visit with its path of key actions and outcome. mode=people: one row per person with their visits in order.
    Filters: outcome (browsed / product / cart / checkout / paying / ordered), journey + reached (visits that reached a step), stuck (reached it, went no further, never bought)."""
    if not _ready():
        return {"ready": False, "total": 0, "rows": []}
    if mode not in ("visits", "people"):
        raise HTTPException(400, "mode must be visits or people")
    w, a = _where(date_from, date_to, include_excluded, channel)
    if outcome:
        if outcome not in OUTCOME_STAGE:
            raise HTTPException(400, f"outcome must be one of {list(OUTCOME_STAGE)}")
        w += f" AND ({STAGE_EXPR}) = {OUTCOME_STAGE[outcome]}"
    if journey and reached:
        keys = [k for k, _ in _spec(journey)["steps"]]
        if reached not in keys:
            raise HTTPException(400, f"reached must be one of {keys}")
        i = keys.index(reached)
        w += f" AND {_reach(journey, i)}"
        if stuck and i + 1 < len(keys):
            w += f" AND NOT {_reach(journey, i + 1)} AND NOT j.purchase_purchase"
    if search:
        like = f"%{search.lower()}%"
        w += (" AND (lower(s.session_id) LIKE ? OR lower(coalesce(s.city, '')) LIKE ? OR lower(coalesce(u.name, '')) LIKE ? OR coalesce(u.phone10, '') LIKE ? OR lower(s.campaign) LIKE ?"
              " OR lower(coalesce(s.key_events, '')) LIKE ?)")
        a += [like] * 6
    d = "ASC" if direction.lower() == "asc" else "DESC"
    base = (f"FROM sessions s JOIN journey_sessions j ON j.session_id = s.session_id LEFT JOIN session_orders o ON o.session_id = s.session_id "
            f"LEFT JOIN pain_sessions ps ON ps.session_id = s.session_id LEFT JOIN users_360 u ON u.person_key = j.person_key")
    lim, off = max(1, min(int(limit), 2000)), max(0, offset)
    if mode == "visits":
        total = one(f"SELECT count(*) AS n {base} WHERE {w}", a)["n"]
        flags = ", ".join(f"j.{c} AS f_{k}" for k, c, _ in ENTERED)
        rows = q(f"""SELECT s.session_id, s.started_at, s.duration_s, s.events, s.channel, s.source, s.campaign, s.city, s.device, s.is_app, s.key_events, ({STAGE_EXPR}) AS stage, o.order_value,
                     j.person_key, u.name, u.phone10, coalesce(ps.with_problem, false) AS had_problem, s.is_excluded, {flags}
                     {base} WHERE {w} ORDER BY {SORTS.get(sort, SORTS['started_at'])} {d} NULLS LAST, s.started_at DESC, s.session_id LIMIT ? OFFSET ?""", [*a, lim, off])
        for r in rows:
            r["entered"] = [lb for k, _c, lb in ENTERED if r.pop(f"f_{k}")]
            r["stage_name"] = STAGE_NAME[r["stage"]]
        return {"ready": True, "mode": mode, "total": total, "rows": rows}
    ob = PSORTS.get(sort, PSORTS['last_seen'])
    total = one(f"SELECT count(*) AS n FROM (SELECT j.person_key {base} WHERE {w} GROUP BY 1)", a)["n"]
    rows = q(f"""SELECT j.person_key, count(*) AS visits, min(s.started_at) AS first_seen, max(s.started_at) AS last_seen, max({STAGE_EXPR}) AS stage,
                 list(({STAGE_EXPR}) ORDER BY s.started_at) AS stages, list(s.channel ORDER BY s.started_at) AS channels, list(s.session_id ORDER BY s.started_at) AS sessions,
                 any_value(u.name) AS name, any_value(u.phone10) AS phone10, any_value(u.city) AS city, any_value(u.first_channel) AS first_channel, any_value(u.segment) AS segment,
                 coalesce(any_value(u.orders), 0) AS orders, coalesce(any_value(u.revenue), 0) AS revenue, any_value(u.is_registered) AS is_registered
                 {base} WHERE {w} GROUP BY j.person_key ORDER BY {ob} {d} NULLS LAST, j.person_key LIMIT ? OFFSET ?""",
             [*a, lim, off])
    for r in rows:
        r["stage_name"] = STAGE_NAME[r["stage"]]
        r["days"] = round((r["last_seen"] - r["first_seen"]).total_seconds() / 86400, 1) if r["visits"] > 1 else 0
        r["sessions"] = r["sessions"][-8:]
        r["stages"] = r["stages"][-8:]
        r["channels"] = r["channels"][-8:]
    return {"ready": True, "mode": mode, "total": total, "rows": rows}

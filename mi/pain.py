"""Pain points: what went wrong for shoppers from login to payment, and what stopped them buying.

Mirrors the Pain points tab of the admin analytics on roopsee.com. The rules are in mi/pain_defs.py; the per-visit tables (pain_events, pain_visits,
pain_sessions, ...) are built by the rebuild (mi/transform.py `pain_sql`). This file only reads them for a date range.

A visit is "stuck" at a stage when it tried it and never got through, or its last word there was a problem. An order settles every stage.
"""
import re
from datetime import date, datetime, timedelta
from statistics import median

from fastapi import HTTPException

from . import pain_defs as P
from .core import app, one, prev_range, q

MAX_LIST = 100


def _where(d_from, d_to, include_excluded, channel):
    w = ["s.date_ist BETWEEN ? AND ?"]
    a = [d_from or "2000-01-01", d_to or "2999-12-31"]
    if not include_excluded:
        w.append("NOT s.is_excluded")
    if channel:
        w.append("s.channel = ?")
        a.append(channel)
    return " AND ".join(w), a


def _clean(v) -> str:
    return re.sub(r"\s+", " ", str(v or "").replace("_", " ")).strip()[:80]


def _top(counter: dict, n: int):
    return [{"name": k, "count": v} for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))[:n]]


def _med(vals):
    vals = [v for v in vals if v is not None]
    return int(round(median(vals))) if vals else None


def _have() -> bool:
    return bool(q("SELECT 1 FROM information_schema.tables WHERE table_name = 'pain_sessions'"))


def _load(w, a):
    """Stuck visits without an order (all stages) and what each of those people did in the other visits of the range."""
    rows = q(f"""SELECT pv.stage, pv.session_id, coalesce(s.user_id, s.visitor_key) AS person_key, s.started_at, s.ended_at, pv.hit, pv.tries, ps.cart_value,
                 greatest(0, epoch(s.ended_at) - epoch(pv.start_ts)) AS secs
                 FROM pain_visits pv JOIN sessions s ON s.session_id = pv.session_id JOIN pain_sessions ps ON ps.session_id = pv.session_id
                 WHERE pv.stuck AND NOT ps.ordered AND {w}""", a)
    people = sorted({r["person_key"] for r in rows})
    later: dict = {}
    if people:
        for r in q(f"""SELECT coalesce(s.user_id, s.visitor_key) AS person_key, s.started_at, ps.ordered FROM sessions s JOIN pain_sessions ps ON ps.session_id = s.session_id
                       WHERE {w} AND coalesce(s.user_id, s.visitor_key) IN (SELECT unnest(?::VARCHAR[]))""", [*a, people]):
            later.setdefault(r["person_key"], []).append((r["started_at"], r["ordered"]))
    buyers = {p for p, v in later.items() if any(o for _, o in v)}
    return rows, later, buyers


def _after(rows, later):
    """People stuck here: did they come back and buy, come back without buying, or not come back? Lost value = carts of those who did not buy."""
    first: dict = {}
    cart: dict = {}
    for r in rows:
        p = r["person_key"]
        if p not in first or r["started_at"] < first[p]["started_at"]:
            first[p] = r
        cart[p] = max(cart.get(p, 0), r["cart_value"] or 0)
    out = {"people": len(first), "bought_after": 0, "returned_no_order": 0, "never_returned": 0, "lost_value": 0}
    for p, v in first.items():
        after = [x for x in later.get(p, []) if x[0] > v["ended_at"]]
        if any(o for _, o in after):
            out["bought_after"] += 1
            continue
        out["returned_no_order" if after else "never_returned"] += 1
        out["lost_value"] += cart[p]
    out["lost_value"] = round(out["lost_value"])
    return out


def _pain(d_from, d_to, include_excluded, channel):
    w, a = _where(d_from, d_to, include_excluded, channel)
    base = f"FROM sessions s JOIN pain_sessions ps ON ps.session_id = s.session_id WHERE {w}"
    t = one(f"""SELECT count(*) AS visits, count(*) FILTER (WHERE ps.ordered) AS ordered, count(*) FILTER (WHERE ps.with_problem) AS with_problem,
                count(*) FILTER (WHERE ps.left_with_problem) AS left_with_problem, count(*) FILTER (WHERE NOT ps.ordered AND NOT ps.has_open) AS left_no_problem,
                coalesce(sum(ps.cart_value) FILTER (WHERE ps.left_with_problem), 0) AS cart_value_left {base}""", a)
    t["cart_value_left"] = round(t["cart_value_left"] or 0)
    vjoin = f"FROM pain_visits pv JOIN sessions s ON s.session_id = pv.session_id JOIN pain_sessions ps ON ps.session_id = pv.session_id WHERE {w}"
    counts = {r["stage"]: r for r in q(f"""SELECT pv.stage, count(*) AS tried, count(*) FILTER (WHERE pv.hit) AS hit, count(*) FILTER (WHERE pv.stuck) AS stuck,
        count(*) FILTER (WHERE pv.hit AND NOT pv.stuck) AS recovered, count(*) FILTER (WHERE pv.stuck AND NOT ps.ordered) AS stuck_no_order,
        count(*) FILTER (WHERE pv.stuck AND NOT pv.hit) AS no_signal,
        coalesce(sum(ps.cart_value) FILTER (WHERE pv.stuck AND NOT ps.ordered), 0) AS cart_value {vjoin} GROUP BY 1""", a)}
    reasons: dict = {}
    for r in q(f"""SELECT pe.stage, pe.problem_key, pe.label, pe.soft, count(DISTINCT pe.session_id) AS visits
                   FROM pain_events pe JOIN pain_visits pv ON pv.session_id = pe.session_id AND pv.stage = pe.stage AND pv.stuck
                   JOIN sessions s ON s.session_id = pe.session_id JOIN pain_sessions ps ON ps.session_id = pe.session_id
                   WHERE {w} GROUP BY 1, 2, 3, 4 ORDER BY 5 DESC, 2""", a):
        reasons.setdefault(r["stage"], {})[r["problem_key"]] = {"key": r["problem_key"], "label": r["label"], "soft": r["soft"], "visits": r["visits"], "details": [], **P.PROBLEM_EVENT[r["problem_key"]]}
    for r in q(f"""SELECT pe.stage, pe.problem_key, pe.detail, count(DISTINCT pe.session_id) AS n
                   FROM pain_events pe JOIN pain_visits pv ON pv.session_id = pe.session_id AND pv.stage = pe.stage AND pv.stuck
                   JOIN sessions s ON s.session_id = pe.session_id JOIN pain_sessions ps ON ps.session_id = pe.session_id
                   WHERE {w} AND pe.detail IS NOT NULL GROUP BY 1, 2, 3""", a):
        reasons[r["stage"]][r["problem_key"]].setdefault("_d", {})[r["detail"]] = r["n"]
    for st in reasons.values():
        for rr in st.values():
            rr["details"] = _top(rr.pop("_d", {}), 5)

    rows, later, buyers = _load(w, a)
    stages = []
    for key, label, stuck_label in P.STAGES:
        c = counts.get(key, {})
        mine = [r for r in rows if r["stage"] == key]
        listed = {r["person_key"] for r in mine} - buyers
        effort = None
        if key in P.RETRY and mine:
            tries = [r["tries"] for r in mine]
            effort = {"median_sec": _med([r["secs"] for r in mine]), "median_tries": _med(tries), "tries_label": P.RETRY_LABEL[key], "three_plus": sum(1 for x in tries if x >= 3)}
        row = {"key": key, "label": label, "stuck_label": stuck_label, "tried": t["visits"] if key == "speed" else c.get("tried", 0), "hit": c.get("hit", 0),
               "stuck": c.get("stuck", 0), "recovered": c.get("recovered", 0), "stuck_no_order": c.get("stuck_no_order", 0), "no_signal": c.get("no_signal", 0),
               "cart_value": round(c.get("cart_value", 0) or 0), "reasons": sorted(reasons.get(key, {}).values(), key=lambda r: -r["visits"]),
               "list_total": len(listed), "after": _after(mine, later), "effort": effort}
        if key == "speed":
            sp = one(f"""SELECT count(*) FILTER (WHERE NOT hit_s) AS clean_n, count(*) FILTER (WHERE NOT hit_s AND ordered) AS clean_ord,
                         count(*) FILTER (WHERE hit_s) AS hit_n, count(*) FILTER (WHERE hit_s AND ordered) AS hit_ord, count(*) FILTER (WHERE hit_s AND quick) AS quick_hit FROM (
                         SELECT ps.ordered, (s.session_id IN (SELECT session_id FROM pain_visits WHERE stage = 'speed')) AS hit_s, (s.duration_s < 10) AS quick
                         FROM sessions s JOIN pain_sessions ps ON ps.session_id = s.session_id WHERE {w})""", a)
            row["order_rate_hit"] = sp["hit_ord"] / sp["hit_n"] if sp["hit_n"] else None
            row["order_rate_clean"] = sp["clean_ord"] / sp["clean_n"] if sp["clean_n"] else None
            row["quick_exit_hit"] = sp["quick_hit"]
        stages.append(row)

    last = q(f"""SELECT ps.last_key AS key, count(*) AS visits {base} AND NOT ps.ordered AND ps.last_key IS NOT NULL GROUP BY 1 ORDER BY 2 DESC, 1""", a)
    ld: dict = {}
    for r in q(f"SELECT ps.last_key AS key, ps.last_detail AS d, count(*) AS n {base} AND NOT ps.ordered AND ps.last_detail IS NOT NULL GROUP BY 1, 2", a):
        ld.setdefault(r["key"], {})[r["d"]] = r["n"]
    last_before = [{"key": r["key"], "label": P.PROBLEM_LABEL[r["key"]], "stage": P.PROBLEM_STAGE[r["key"]], "visits": r["visits"], "details": _top(ld.get(r["key"], {}), 3)} for r in last]

    lp = one(f"""SELECT count(*) FILTER (WHERE lp_opened OR lp_sent OR lp_entered OR lp_phone_done) AS p0, count(*) FILTER (WHERE lp_sent OR lp_entered OR lp_phone_done) AS p1,
                 count(*) FILTER (WHERE lp_entered OR lp_phone_done) AS p2, count(*) FILTER (WHERE lp_phone_done) AS p3,
                 count(*) FILTER (WHERE g_click OR g_done) AS g0, count(*) FILTER (WHERE g_done) AS g1 {base}""", a)
    login_paths = [
        {"key": "phone", "label": "Phone OTP", "steps": [{"key": k, "label": lb, "visits": lp[f"p{i}"]} for i, (k, lb) in enumerate(
            [("opened", "Opened login"), ("otp_sent", "Sent the OTP"), ("otp_entered", "Entered the OTP"), ("logged_in", "Logged in")])]},
        {"key": "google", "label": "Google", "steps": [{"key": "clicked", "label": "Clicked “Continue with Google”", "visits": lp["g0"]}, {"key": "logged_in", "label": "Logged in with Google", "visits": lp["g1"]}]},
    ]

    # trend by day
    days = {str(r["d"]): {"day": str(r["d"]), "visits": r["visits"], "with_problem": r["with_problem"], "left_with_problem": r["left_with_problem"], **{k: 0 for k, _, _ in P.STAGES}}
            for r in q(f"""SELECT s.date_ist AS d, count(*) AS visits, count(*) FILTER (WHERE ps.with_problem) AS with_problem, count(*) FILTER (WHERE ps.left_with_problem) AS left_with_problem
                           {base} GROUP BY 1 ORDER BY 1""", a)}
    for r in q(f"SELECT s.date_ist AS d, pv.stage, count(*) AS n {vjoin} AND pv.stuck GROUP BY 1, 2", a):
        days[str(r["d"])][r["stage"]] = r["n"]
    daily = []
    if days:
        d, end = date.fromisoformat(min(days)), date.fromisoformat(max(days))
        while d <= end:
            daily.append(days.get(d.isoformat(), {"day": d.isoformat(), "visits": 0, "with_problem": 0, "left_with_problem": 0, **{k: 0 for k, _, _ in P.STAGES}}))
            d += timedelta(days=1)

    return {"stages": stages, "login_paths": login_paths, "last_before_leaving": last_before, "daily": daily, "spikes": _spikes(w, a, daily),
            "payment": _payment(w, a), "not_served": _not_served(w, a), "out_of_stock": _stock(w, a), "slow_pages": _slow(w, a), "totals": t}


def _spikes(w, a, daily):
    """Hours when one problem suddenly hit many more visits than usual (often an outage)."""
    if not daily:
        return []
    hours = len(daily) * 24
    if hours < 6:
        return []
    per = q(f"""SELECT pe.problem_key AS key, date_trunc('hour', pe.ts) AS hr, count(DISTINCT pe.session_id) AS n FROM pain_events pe JOIN sessions s ON s.session_id = pe.session_id
                WHERE pe.is_hard AND {w} GROUP BY 1, 2""", a)
    total: dict = {}
    for r in per:
        total[r["key"]] = total.get(r["key"], 0) + r["n"]
    out = []
    for r in per:
        usual = (total[r["key"]] - r["n"]) / (hours - 1)
        if r["n"] < 5 or r["n"] < 4 * max(usual, 0.5):
            continue
        det = {x["detail"]: x["n"] for x in q(f"""SELECT pe.detail, count(DISTINCT pe.session_id) AS n FROM pain_events pe JOIN sessions s ON s.session_id = pe.session_id
                WHERE pe.problem_key = ? AND date_trunc('hour', pe.ts) = ? AND pe.detail IS NOT NULL AND {w} GROUP BY 1""", [r["key"], r["hr"], *a])}
        out.append({"key": r["key"], "label": P.PROBLEM_LABEL[r["key"]], "stage": P.PROBLEM_STAGE[r["key"]], "from": r["hr"], "visits": r["n"], "usual": round(usual, 1), "details": _top(det, 3)})
    out.sort(key=lambda x: -x["visits"] / max(x["usual"], 0.5))
    return out[:6]


def _payment(w, a):
    names = {"": "Not recorded", "cod": "Cash on delivery"}
    methods: dict = {}
    for r in q(f"""SELECT coalesce(pv.pay_method, '') AS m, count(*) AS tried, count(*) FILTER (WHERE pv.stuck) AS stuck FROM pain_visits pv JOIN sessions s ON s.session_id = pv.session_id
                   WHERE pv.stage = 'payment' AND {w} GROUP BY 1""", a):
        n = names.get(r["m"], "Online (Razorpay)")
        m = methods.setdefault(n, {"name": n, "tried": 0, "stuck": 0})
        m["tried"] += r["tried"]
        m["stuck"] += r["stuck"]
    cnt = {k: {} for k in ("reasons", "sources", "steps", "codes")}
    failed = 0
    for r in q(f"""SELECT pe.reason, pe.source, pe.step, pe.code FROM pain_events pe JOIN sessions s ON s.session_id = pe.session_id WHERE pe.problem_key = 'payment_failed' AND {w}""", a):
        failed += 1
        for k, f in (("reasons", "reason"), ("sources", "source"), ("steps", "step"), ("codes", "code")):
            if r[f]:
                c = _clean(r[f])
                cnt[k][c] = cnt[k].get(c, 0) + 1
    return {"methods": sorted(methods.values(), key=lambda m: -m["tried"]), "failed_attempts": failed, **{k: _top(v, 8) for k, v in cnt.items()}}


def _not_served(w, a):
    j = f"FROM pain_notserved n JOIN sessions s ON s.session_id = n.session_id JOIN pain_sessions ps ON ps.session_id = n.session_id LEFT JOIN dim_pincode dp ON dp.pincode = n.pincode WHERE n.pincode IS NOT NULL AND {w}"
    tot = one(f"SELECT count(DISTINCT n.session_id) AS visits, count(DISTINCT n.pincode) AS pins {j}", a)
    rows = q(f"""SELECT n.pincode, coalesce(max(dp.city), mode(n.city)) AS city, count(DISTINCT n.session_id) AS visits,
                 count(DISTINCT n.session_id) FILTER (WHERE n.at_checkout) AS at_checkout, count(DISTINCT n.session_id) FILTER (WHERE NOT ps.ordered) AS "left"
                 {j} GROUP BY 1 ORDER BY at_checkout DESC, visits DESC, 1 LIMIT 20""", a)
    return {"visits": tot["visits"], "total_pincodes": tot["pins"], "pincodes": rows}


def _stock(w, a):
    return q(f"""SELECT n.name, coalesce(max(n.brand), '') AS brand, count(DISTINCT n.session_id) AS visits,
                 count(DISTINCT n.session_id) FILTER (WHERE n.event_name = 'out_of_stock_viewed') AS viewed,
                 count(DISTINCT n.session_id) FILTER (WHERE n.event_name = 'out_of_stock_add_attempt') AS tried_add,
                 count(DISTINCT n.session_id) FILTER (WHERE NOT ps.ordered) AS "left"
                 FROM pain_stock n JOIN sessions s ON s.session_id = n.session_id JOIN pain_sessions ps ON ps.session_id = n.session_id
                 WHERE n.name IS NOT NULL AND n.name <> 'Product' AND {w} GROUP BY 1 ORDER BY tried_add DESC, visits DESC, 1 LIMIT 20""", a)


def _slow(w, a):
    return q(f"""SELECT CASE WHEN pe.page_type = 'product' THEN '/products/(a product page)' ELSE coalesce(pe.path, 'unknown') END AS page, count(DISTINCT pe.session_id) AS visits,
                 median(pe.ms) FILTER (WHERE pe.ms > 0) AS median_ms, count(DISTINCT pe.session_id) FILTER (WHERE NOT ps.ordered) AS "left"
                 FROM pain_events pe JOIN sessions s ON s.session_id = pe.session_id JOIN pain_sessions ps ON ps.session_id = pe.session_id
                 WHERE pe.problem_key = 'slow_page_load' AND {w} GROUP BY 1 ORDER BY visits DESC, 1 LIMIT 12""", a)


@app.get("/api/pain")
def pain(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, channel: str | None = None, compare: bool = False):
    """The whole Pain points tab for a date range (and, with compare=true, the same numbers for the period before)."""
    if not _have():
        return {"ready": False}
    out = _pain(date_from, date_to, include_excluded, channel)
    pr = prev_range(date_from, date_to) if compare else None
    if pr:
        p = _pain(pr[0], pr[1], include_excluded, channel)
        out["prev"] = {"range": pr, "totals": p["totals"], "stages": {s["key"]: {k: s[k] for k in ("tried", "hit", "stuck")} for s in p["stages"]},
                       "lost": sum(s["after"]["lost_value"] for s in p["stages"] if s["key"] != "speed")}
    seen = {r["event_name"] for r in q("SELECT DISTINCT event_name FROM pain_events")}
    out["silent"] = [e for e in P.PROBLEM_EVENTS if e not in seen]  # problem events the tracker has never sent (so a zero here may not be a real zero)
    out["channels"] = [r["channel"] for r in q("SELECT channel, count(*) n FROM sessions GROUP BY 1 ORDER BY n DESC")]
    out["ready"] = True
    return out


@app.get("/api/pain/people")
def pain_people(stage: str, date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, channel: str | None = None, limit: int = MAX_LIST):
    """Who got stuck at a stage in a visit without an order (and never ordered in the range): newest first, with what went wrong."""
    if stage not in P.STAGE_LABEL:
        raise HTTPException(400, f"stage must be one of {list(P.STAGE_LABEL)}")
    if not _have():
        return {"total": 0, "people": []}
    w, a = _where(date_from, date_to, include_excluded, channel)
    rows, _later, buyers = _load(w, a)
    by: dict = {}
    for r in rows:
        if r["stage"] != stage or r["person_key"] in buyers:
            continue
        by.setdefault(r["person_key"], []).append(r)
    people = []
    for pk, vs in by.items():
        vs.sort(key=lambda r: r["started_at"], reverse=True)
        people.append({"person_key": pk, "visits": len(vs), "last_seen": vs[0]["ended_at"], "session_id": vs[0]["session_id"], "cart_value": round(max(v["cart_value"] or 0 for v in vs))})
    people.sort(key=lambda p: p["last_seen"], reverse=True)
    total = len(people)
    people = people[:max(1, min(int(limit), 2000))]
    if people:
        info = {r["person_key"]: r for r in q("SELECT person_key, name, phone10, city, is_registered FROM users_360 WHERE person_key IN (SELECT unnest(?::VARCHAR[]))", [[p["person_key"] for p in people]])}
        why: dict = {}
        for r in q("SELECT session_id, label, detail FROM pain_events WHERE stage = ? AND session_id IN (SELECT unnest(?::VARCHAR[])) ORDER BY ts", [stage, [p["session_id"] for p in people]]):
            why.setdefault(r["session_id"], []).append(f"{r['label']}{' (' + r['detail'] + ')' if r['detail'] else ''}")
        for p in people:
            i = info.get(p["person_key"], {})
            p.update(name=i.get("name"), phone10=i.get("phone10"), city=i.get("city"), is_registered=i.get("is_registered", False))
            reasons = list(dict.fromkeys(why.get(p["session_id"], [])))
            p["why"] = " · ".join(reasons[:4]) if reasons else "No error recorded: they just stopped"
    return {"stage": stage, "total": total, "people": people}

"""Logins: every visit in which someone logged in, for the Home page and the Logins page.

The `logins` table (built by the rebuild, mi/transform.py `logins_sql`) has one row per visit with a login: the several events of one login
(otp_verified, login_successful, ...) count once. A login is "new" when the account was created within an hour of it.
Hidden internal traffic is left out unless asked for (the table is joined to sessions when read).
"""
from datetime import date, timedelta

from fastapi import HTTPException

from .core import app, one, prev_range, q

SORTS = {"at": "l.ts", "name": "nullif(lower(u.name), '')", "method": "l.method", "city": "nullif(lower(s.city), '')", "channel": "s.channel", "device": "s.device"}
KINDS = {"new": "l.is_new", "returning": "NOT l.is_new"}
METHODS = ("Google", "Phone OTP", "Not recorded")


def has_logins() -> bool:
    return bool(q("SELECT 1 FROM information_schema.tables WHERE table_name = 'logins'"))


def _where(d_from, d_to, include_excluded, method=None, kind=None, search=None):
    w = ["l.ts_ist::DATE BETWEEN ? AND ?"]
    a = [d_from or "2000-01-01", d_to or "2999-12-31"]
    if not include_excluded:
        w.append("NOT s.is_excluded")
    if method:
        if method not in METHODS:
            raise HTTPException(400, f"method must be one of {list(METHODS)}")
        w.append("l.method = ?")
        a.append(method)
    if kind:
        if kind not in KINDS:
            raise HTTPException(400, f"kind must be one of {list(KINDS)}")
        w.append(KINDS[kind])
    if search:
        like = f"%{search.lower()}%"
        w.append("""(lower(coalesce(l.name, '')) LIKE ? OR coalesce(l.phone10, '') LIKE ? OR lower(coalesce(l.email, '')) LIKE ? OR lower(l.session_id) LIKE ?
                    OR lower(coalesce(s.city, '')) LIKE ? OR lower(l.person_key) LIKE ?)""")
        a += [like] * 6
    return " AND ".join(w), a


FROM = "FROM logins l JOIN sessions s ON s.session_id = l.session_id LEFT JOIN users_360 u ON u.person_key = l.person_key"


def login_kpis(d_from, d_to, include_excluded) -> dict:
    """logins (one per visit), people who logged in, how many were new accounts. Zeros before the first rebuild that has the table."""
    if not has_logins():
        return {"logins": 0, "login_people": 0, "login_new": 0}
    w, a = _where(d_from, d_to, include_excluded)
    r = one(f"SELECT count(*) AS logins, count(DISTINCT l.person_key) AS login_people, count(*) FILTER (WHERE l.is_new) AS login_new {FROM} WHERE {w}", a)
    return {k: r[k] or 0 for k in ("logins", "login_people", "login_new")}


def login_series(lo: str, hi: str, include_excluded: bool) -> dict:
    """Logins per day on a gap-free date spine (days without logins are zeros)."""
    if not has_logins():
        return {}
    w, a = _where(lo, hi, include_excluded)
    rows = {str(r["d"]): r for r in q(f"SELECT l.ts_ist::DATE AS d, count(*) AS logins, count(*) FILTER (WHERE l.is_new) AS login_new {FROM} WHERE {w} GROUP BY 1", a)}
    out = {"logins": [], "login_new": []}
    d, end = date.fromisoformat(lo), date.fromisoformat(hi)
    while d <= end:
        r = rows.get(d.isoformat(), {})
        out["logins"].append(r.get("logins", 0))
        out["login_new"].append(r.get("login_new", 0))
        d += timedelta(days=1)
    return out


@app.get("/api/logins")
def logins(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, method: str | None = None, kind: str | None = None,
           search: str | None = None, sort: str = "at", direction: str = "desc", limit: int = 50, offset: int = 0, summary: bool = True, compare: bool = False):
    """Every login in the range, newest first, with totals, a daily trend and the split by method and hour. `summary=false` returns only the rows."""
    if not has_logins():
        return {"ready": False, "total": 0, "rows": []}
    w, a = _where(date_from, date_to, include_excluded, method, kind, search)
    order = SORTS.get(sort, SORTS["at"])
    d = "ASC" if direction.lower() == "asc" else "DESC"
    total = one(f"SELECT count(*) AS n {FROM} WHERE {w}", a)["n"]
    rows = q(f"""SELECT l.session_id, l.ts_ist AS at, l.person_key, l.user_id, coalesce(l.name, u.name) AS name, l.phone10, l.email, l.method, l.is_new, s.city, s.region, s.device, s.is_app,
                 s.platform, s.channel, s.campaign, coalesce(po.ordered, false) AS ordered, s.is_excluded
                 {FROM} LEFT JOIN pain_ordered po ON po.session_id = l.session_id WHERE {w} ORDER BY {order} {d} NULLS LAST, l.ts DESC, l.session_id LIMIT ? OFFSET ?""",
             [*a, max(1, min(int(limit), 5000)), max(0, offset)])
    out = {"ready": True, "total": total, "rows": rows}
    if not summary:
        return out
    # the totals and charts ignore the method / kind / search filters only for the split they describe, so the split always adds up to the range total
    wa, aa = _where(date_from, date_to, include_excluded)
    out["totals"] = login_kpis(date_from, date_to, include_excluded)
    out["by_method"] = q(f"SELECT l.method AS name, count(*) AS logins, count(*) FILTER (WHERE l.is_new) AS new_accounts {FROM} WHERE {wa} GROUP BY 1 ORDER BY 2 DESC, 1", aa)
    out["by_hour"] = q(f"SELECT extract(hour FROM l.ts_ist)::INT AS hour, count(*) AS logins {FROM} WHERE {wa} GROUP BY 1 ORDER BY 1", aa)
    out["by_channel"] = q(f"SELECT coalesce(s.channel, 'Unknown') AS name, count(*) AS logins {FROM} WHERE {wa} GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 8", aa)
    out["after"] = one(f"""SELECT count(*) FILTER (WHERE po.ordered) AS ordered_same_visit FROM logins l JOIN sessions s ON s.session_id = l.session_id
                           LEFT JOIN pain_ordered po ON po.session_id = l.session_id WHERE {wa}""", aa) if _has("pain_ordered") else {}
    lo = date_from or str(one("SELECT min(ts_ist)::DATE AS d FROM logins")["d"])
    hi = date_to or str(one("SELECT max(ts_ist)::DATE AS d FROM logins")["d"])
    out["dates"] = [(date.fromisoformat(lo) + timedelta(days=i)).isoformat() for i in range((date.fromisoformat(hi) - date.fromisoformat(lo)).days + 1)]
    out["current"] = login_series(lo, hi, include_excluded)
    pr = prev_range(date_from, date_to) if compare else None
    if pr:
        out["prev_range"] = pr
        out["prev"] = login_kpis(pr[0], pr[1], include_excluded)
        out["prev_dates"] = [(date.fromisoformat(pr[0]) + timedelta(days=i)).isoformat() for i in range((date.fromisoformat(pr[1]) - date.fromisoformat(pr[0])).days + 1)]
        out["previous"] = login_series(pr[0], pr[1], include_excluded)
    return out


def _has(table: str) -> bool:
    return bool(q("SELECT 1 FROM information_schema.tables WHERE table_name = ?", [table]))

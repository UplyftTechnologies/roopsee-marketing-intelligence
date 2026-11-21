"""Segments: people labels (quiz users, makeup users, price range, discount checkers, journey stage, quiz concern ...), shown on the Audiences tab.

The labels are defined in mi/deeper_defs.py and stored per person in the user_labels table by the rebuild (mi/deeper_sql.py).
Moved here from the old Deeper analysis tab; the Audiences tab shows them for all time (no date range), like its other lists.
"""
from statistics import median  # noqa: F401  (used by _med)

from . import deeper_defs as D
from .core import app, one, q, ratio, untracked_sales
from .people import _users_where


def _uw(d_from, d_to, include_excluded):
    """The Users-tab date / hidden-traffic condition, written for users_360 aliased as u."""
    w, a = _users_where(d_from, d_to, include_excluded)
    return w.replace("first_seen", "u.first_seen").replace("last_seen", "u.last_seen").replace("is_excluded", "u.is_excluded"), a


def _have(table: str) -> bool:
    return bool(q("SELECT 1 FROM information_schema.tables WHERE table_name = ?", [table]))


def _ready(*tables) -> bool:
    return all(_have(t) for t in tables)


def _med(vals):
    vals = [v for v in vals if v is not None]
    return round(median(vals), 1) if vals else None



def _label_meta() -> dict:
    meta = {key: {"group": g, "title": t, "description": desc} for g, key, t, desc, _ in D.LABELS}
    for r in q("SELECT DISTINCT label_key FROM user_labels WHERE label_key LIKE 'stage:%' OR label_key LIKE 'concern:%'"):
        k = r["label_key"]
        name = k.split(":", 1)[1]
        if k.startswith("stage:"):
            meta[k] = {"group": "Journey stage", "title": name.replace("_", " ").replace(",", "").capitalize(), "description": "Where the person is in the journey (Users tab segment)."}
        else:
            meta[k] = {"group": "Skin concern (quiz)", "title": name, "description": "Named this concern in the skin quiz."}
    return meta


@app.get("/api/segments")
def segment_labels(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, label: str | None = None):
    if not _ready("user_labels"):
        return {"ready": False}
    uw, ua = _uw(date_from, date_to, include_excluded)
    meta = _label_meta()
    total = one(f"SELECT count(*) AS people, count(*) FILTER (WHERE u.orders > 0) AS buyers FROM users_360 u WHERE {uw}", ua)
    rows = q(f"""SELECT l.label_key, count(*) AS people, count(*) FILTER (WHERE u.orders > 0) AS buyers, count(*) FILTER (WHERE u.orders > 1) AS repeat_buyers, coalesce(sum(u.revenue), 0) AS revenue,
                 count(*) FILTER (WHERE nullif(u.phone10, '') IS NOT NULL) AS reachable, avg(u.sessions) AS avg_sessions
                 FROM user_labels l JOIN users_360 u ON u.person_key = l.person_key WHERE {uw}
                 GROUP BY 1 ORDER BY 2 DESC""", ua)
    out = []
    for r in rows:
        m = meta.get(r["label_key"], {"group": "Other", "title": r["label_key"], "description": ""})
        out.append({**r, **m, "key": r["label_key"], "buyer_rate": ratio(r["buyers"], r["people"]), "aov": round(r["revenue"] / r["buyers"], 0) if r["buyers"] else None,
                    "share": ratio(r["people"], total["people"]), "avg_sessions": round(r["avg_sessions"] or 0, 1)})
    co = []
    if label:
        co = q(f"""SELECT l2.label_key AS key, count(*) AS people FROM user_labels l1 JOIN user_labels l2 ON l2.person_key = l1.person_key AND l2.label_key <> l1.label_key
                   JOIN users_360 u ON u.person_key = l1.person_key WHERE l1.label_key = ? AND {uw}
                   GROUP BY 1 ORDER BY 2 DESC LIMIT 12""", [label, *ua])
        for r in co:
            r["title"] = meta.get(r["key"], {}).get("title", r["key"])
    return {"ready": True, "untracked": untracked_sales(include_excluded), "totals": total, "labels": out, "co": co, "base": {"buyer_rate": ratio(total["buyers"], total["people"])}}


@app.get("/api/segments/people")
def segment_people(label: str, date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, only_reachable: bool = False,
                          sort: str = "last_seen", limit: int = 50, offset: int = 0):
    if not _ready("user_labels"):
        return {"total": 0, "rows": []}
    uw, ua = _uw(date_from, date_to, include_excluded)
    if only_reachable:
        uw += " AND nullif(u.phone10, '') IS NOT NULL"
    order = {"last_seen": "u.last_seen DESC", "revenue": "u.revenue DESC", "sessions": "u.sessions DESC", "evidence": "l.n DESC"}.get(sort, "u.last_seen DESC")
    total = one(f"SELECT count(*) AS n FROM user_labels l JOIN users_360 u ON u.person_key = l.person_key WHERE l.label_key = ? AND {uw}", [label, *ua])["n"]
    rows = q(f"""SELECT u.person_key, u.name, u.phone10, u.email, u.city, u.state, u.segment, u.first_channel, u.orders, u.revenue, u.sessions, u.last_seen, l.n AS evidence
                 FROM user_labels l JOIN users_360 u ON u.person_key = l.person_key WHERE l.label_key = ? AND {uw} ORDER BY {order} NULLS LAST, u.person_key LIMIT ? OFFSET ?""",
             [label, *ua, max(1, min(int(limit), 2000)), max(0, offset)])
    meta = _label_meta()
    if rows:
        by: dict = {}
        for r in q("SELECT person_key, label_key FROM user_labels WHERE person_key IN (SELECT unnest(?::VARCHAR[])) AND label_key NOT LIKE 'stage:%'", [[r["person_key"] for r in rows]]):
            by.setdefault(r["person_key"], []).append(meta.get(r["label_key"], {}).get("title", r["label_key"]))
        for r in rows:
            r["labels"] = by.get(r["person_key"], [])
    return {"label": label, "title": meta.get(label, {}).get("title", label), "total": total, "rows": rows}

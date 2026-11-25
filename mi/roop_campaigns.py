"""Roop (the assistant) by campaign, ad set, ad and channel: which traffic opens the assistant, asks it something, and what happens next.

Built on the per-visit Roop steps of the Journeys tab (journey_sessions), the ad of each visit (session_attrib) and the chat messages, so a row here is
exactly the visits the Sessions tab lists when you click it (has=roop / roop_asked). The campaign is the visit's own first-touch campaign, not the (shortened)
name carried on the assistant event. Visits, hidden traffic and the device filter follow the global filters.
"""
from fastapi import HTTPException

from .core import app, q, ratio, sess_where

LEVELS = {
    "campaign": "s.campaign",
    "adset": "coalesce(sa.adset_id, '(no ad set)')",
    "ad": "coalesce(sa.ad_id, '(no ad)')",
    "channel": "s.channel",
}
ENTITY = {"campaign": "campaign", "adset": "adset", "ad": "ad"}


def _have() -> bool:
    return bool(q("SELECT 1 FROM information_schema.tables WHERE table_name = 'journey_sessions'"))


@app.get("/api/roop/usage")
def roop_usage(level: str = "campaign", date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, min_sessions: int = 1, only_used: bool = True,
               limit: int = 200):
    """One row per campaign / ad set / ad / channel: visits, opened Roop, asked, got an answer, clicked a product, and what those visits did, against the visits that did not use Roop."""
    if level not in LEVELS:
        raise HTTPException(400, f"level must be one of {list(LEVELS)}")
    if not _have():
        return {"ready": False}
    key = LEVELS[level]
    w, a = sess_where(date_from, date_to, include_excluded)
    base = ("FROM sessions s JOIN journey_sessions j ON j.session_id = s.session_id LEFT JOIN session_attrib sa ON sa.session_id = s.session_id "
            f"WHERE {w}")
    rows = q(f"""SELECT {key} AS key, max(s.channel) AS channel, count(*) AS sessions, count(*) FILTER (WHERE j.chat_opened) AS opened, count(*) FILTER (WHERE j.chat_asked) AS asked,
                 count(*) FILTER (WHERE j.chat_answered) AS answered, count(*) FILTER (WHERE j.chat_clicked) AS clicked,
                 count(*) FILTER (WHERE j.chat_opened AND j.purchase_add_to_cart) AS roop_carted, count(*) FILTER (WHERE j.chat_opened AND j.purchase_purchase) AS roop_ordered,
                 count(*) FILTER (WHERE NOT j.chat_opened) AS other_sessions, count(*) FILTER (WHERE NOT j.chat_opened AND j.purchase_add_to_cart) AS other_carted,
                 count(*) FILTER (WHERE NOT j.chat_opened AND j.purchase_purchase) AS other_ordered
                 {base} GROUP BY 1 HAVING count(*) >= ? {'AND count(*) FILTER (WHERE j.chat_opened) > 0' if only_used else ''} ORDER BY opened DESC, sessions DESC, 1 LIMIT ?""",
             [*a, max(1, int(min_sessions)), max(1, min(int(limit), 1000))])
    names = {}
    if level in ENTITY:
        names = {r["entity_id"]: r["name"] for r in q("SELECT entity_id, any_value(name) AS name FROM raw_meta_entities WHERE entity_type = ? GROUP BY 1", [ENTITY[level]])}
    topics: dict = {}
    keys = [r["key"] for r in rows]
    if keys and q("SELECT 1 FROM information_schema.tables WHERE table_name = 'chat_messages'"):
        for r in q(f"""SELECT {key} AS key, c.topic, count(*) AS n FROM chat_messages c JOIN sessions s ON s.session_id = c.session_id
                       LEFT JOIN session_attrib sa ON sa.session_id = c.session_id WHERE {w} AND {key} IN (SELECT unnest(?::VARCHAR[])) GROUP BY 1, 2 ORDER BY 3 DESC""", [*a, keys]):
            topics.setdefault(r["key"], []).append({"name": r["topic"], "count": r["n"]})
    for r in rows:
        r["name"] = names.get(r["key"]) or r["key"]
        r["named"] = r["key"] in names
        r["use_rate"] = ratio(r["opened"], r["sessions"])
        r["ask_rate"] = ratio(r["asked"], r["opened"])
        r["roop_order_rate"] = ratio(r["roop_ordered"], r["opened"])
        r["other_order_rate"] = ratio(r["other_ordered"], r["other_sessions"])
        r["roop_cart_rate"] = ratio(r["roop_carted"], r["opened"])
        r["other_cart_rate"] = ratio(r["other_carted"], r["other_sessions"])
        r["topics"] = topics.get(r["key"], [])[:3]
    tot = {k: sum(r[k] for r in rows) for k in ("sessions", "opened", "asked", "answered", "clicked", "roop_carted", "roop_ordered", "other_sessions", "other_carted", "other_ordered")}
    allv = q(f"SELECT count(*) AS sessions, count(*) FILTER (WHERE j.chat_opened) AS opened, count(*) FILTER (WHERE j.chat_asked) AS asked, count(*) FILTER (WHERE j.chat_opened AND j.purchase_purchase) AS roop_ordered, "
             f"count(*) FILTER (WHERE NOT j.chat_opened AND j.purchase_purchase) AS other_ordered, count(*) FILTER (WHERE NOT j.chat_opened) AS other_sessions {base}", a)[0]
    return {"ready": True, "level": level, "rows": rows, "totals": {**tot, "use_rate": ratio(allv["opened"], allv["sessions"]), "roop_order_rate": ratio(allv["roop_ordered"], allv["opened"]),
                                                                       "other_order_rate": ratio(allv["other_ordered"], allv["other_sessions"])},
            "all": allv}

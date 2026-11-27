"""Roop chats: what shoppers ask Roop, the skin-care assistant, and what Roop answers. Mirrors the "Roop chats" tab of the admin analytics on roopsee.com.

The `chat_messages` table (mi/transform.py `chats_sql`) has one row per message with its topic, failure reason, cost and the visit it was sent in.
Every chat is tied to its visit(s), so the chat list and a conversation show the session data (place, IP, browser, device, channel, length, what the visit did).
Hidden internal traffic is left out like everywhere else; a conversation with any hidden message is left out whole.
"""
import json
import re
from collections import Counter
from statistics import median

from fastapi import HTTPException

from .core import DEVICE, app, one, prev_range, q

INR_PER_USD = 88
CONVERSATIONS_SHOWN = 300
SESSION_COLS = ("session_id, started_at, ended_at, duration_s, events, pageviews, channel, source, medium, campaign, city, region, country, device, platform, is_app, ip, "
                "visitor_key, user_id, stage, f_order, is_excluded")


def has_chats() -> bool:
    return bool(q("SELECT 1 FROM information_schema.tables WHERE table_name = 'chat_messages'"))


def _rows(d_from, d_to, include_excluded, conversation=None, session=None):
    """Messages in the range, oldest first. A conversation with any hidden message (hidden visit or hidden person) is left out whole."""
    hide = "" if include_excluded else """ AND x.conversation NOT IN (SELECT conversation FROM x WHERE h)"""
    if DEVICE.get() and not conversation and not session:  # a device filter keeps only messages whose visit is on that device
        hide += " AND x.session_id IN (SELECT session_id FROM sessions)"
    w, a = "x.date_ist BETWEEN ? AND ?", [d_from or "2000-01-01", d_to or "2999-12-31"]
    if conversation:
        w, a = "x.conversation = ?", [conversation]
    if session:
        w, a = "x.session_id = ?", [session]
    return q(f"""WITH x AS (SELECT c.*, (coalesce(s.is_excluded, false) OR c.user_id IN (SELECT user_id FROM excluded_users)) AS h
                           FROM chat_messages c LEFT JOIN sessions s ON s.session_id = c.session_id)
                 SELECT x.* FROM x WHERE {w}{hide} ORDER BY x.ts, x.id""", a)


def _names() -> dict:
    return {str(r["product_id"]).strip().upper(): r["product_name"] for r in q("SELECT product_id, product_name FROM dim_products WHERE product_name IS NOT NULL")}


def _name(pid, names):
    return names.get(str(pid).strip().upper(), pid)


def readable(reply, names) -> str:
    """A saved reply as text: [[product id]] -> the product's name."""
    return re.sub(r"\[\[([^\]]+)\]\]", lambda m: str(_name(m.group(1), names)), str(reply or ""))


def _ids(v):
    try:
        out = json.loads(v) if isinstance(v, str) else (v or [])
    except Exception:
        out = []
    return [str(x) for x in out] if isinstance(out, list) else []


def _top(counter, n):
    return [{"name": k, "count": v} for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))[:n]]


OUTCOMES = {
    "quiz_started": "Quiz started",
    "quiz_resumed": "Quiz resumed",
    "awaiting_product_clarification": "Awaiting product clarification",
    "assortment_gap": "Product answered / assortment gap",
    "out_of_stock": "Product answered / out of stock",
    "stock_alert_registered": "Stock alert registered",
    "product_information_gap": "Product information gap",
    "availability_unknown": "Availability unconfirmed",
    "product_answered": "Product answered",
}


def _assortment_demand(rows):
    products = {}
    for row in rows:
        if row.get("outcome") != "assortment_gap":
            continue
        product = row.get("product_reference") or {}
        if isinstance(product, str):
            product = json.loads(product) or {}
        if not product.get("name"):
            continue
        key = product.get("source_url") or f"{product.get('brand') or ''} {product['name']}".lower()
        entry = products.setdefault(key, {"name": key, "label": product["name"], "chats": set()})
        entry["chats"].add(row["conversation"])
    demand = [{"name": p["name"], "label": p["label"], "count": len(p["chats"])} for p in products.values()]
    return sorted(demand, key=lambda p: (-p["count"], p["label"]))[:30]


def _pct(part, whole) -> int:
    return round(part / whole * 100) if whole else 0


def _med(vals):
    vals = [v for v in vals if v is not None]
    return int(round(median(vals))) if vals else 0


def _sessions(ids):
    ids = sorted({i for i in ids if i})
    if not ids:
        return {}
    return {r["session_id"]: r for r in q(f"SELECT {SESSION_COLS} FROM sessions WHERE session_id IN (SELECT unnest(?::VARCHAR[]))", [ids])}


def _group_shoppers(convs: list[dict], sess: dict) -> list[dict]:
    """Chats of returning shoppers (two or more chats), one entry per shopper: the account when logged in, else the browser (visitor id). A guest chat
    joins the account when exactly one account ever logged in on that browser. Marks every chat with `shopper_key` and `returning`."""
    visitors = {}
    for c in convs:
        visitors[c["key"]] = next((sess[s]["visitor_key"] for s in c["sessions"] if s in sess and sess[s].get("visitor_key")), None)
    known = sorted({v for v in visitors.values() if v})
    accounts: dict = {}
    if known:
        for r in q("""SELECT visitor_key, count(DISTINCT user_id) AS n, max(user_id) AS user_id FROM sessions
                      WHERE user_id IS NOT NULL AND visitor_key IN (SELECT unnest(?::VARCHAR[])) GROUP BY 1""", [known]):
            if r["n"] == 1:
                accounts[r["visitor_key"]] = r["user_id"]
    groups: dict = {}
    for c in convs:
        v = visitors[c["key"]]
        user = c["user_id"] or accounts.get(v)
        kind, ident = ("account", user) if user else ("browser", v) if v else ("guest", c["guest_session_id"]) if c["guest_session_id"] else ("chat", c["key"])
        c["shopper_key"] = f"{kind}:{ident}"
        g = groups.setdefault(c["shopper_key"], {"key": c["shopper_key"], "kind": kind, "user_id": user, "visitor_id": None, "chats": []})
        g["visitor_id"] = g["visitor_id"] or v
        g["chats"].append(c)
    out = []
    for g in groups.values():
        many = len(g["chats"]) > 1
        for c in g["chats"]:
            c["returning"] = many
        if not many:
            continue
        g["chats"].sort(key=lambda c: str(c["updated_at"]), reverse=True)
        out.append({**g, "n_chats": len(g["chats"]), "first_at": min(c["started_at"] for c in g["chats"]), "last_at": g["chats"][0]["updated_at"],
                    **{k: sum(c[k] for c in g["chats"]) for k in ("messages", "failed", "thumbs_up", "thumbs_down")}})
    users = sorted({g["user_id"] for g in out if g["user_id"]})
    who = {r["user_id"]: r for r in q("SELECT user_id, any_value(name) AS name, any_value(phone10) AS phone10 FROM users_360 WHERE user_id IN (SELECT unnest(?::VARCHAR[])) GROUP BY 1", [users])} if users else {}
    for g in out:
        w = who.get(g["user_id"]) or {}
        g["name"], g["phone10"] = w.get("name"), w.get("phone10")
    return sorted(out, key=lambda g: str(g["last_at"]), reverse=True)


def _totals(rows) -> dict:
    answered = [r for r in rows if not r["error"]]
    shoppers: dict = {}
    convs = set()
    for r in rows:
        k = f"u:{r['user_id']}" if r["user_id"] else f"g:{r['guest_session_id']}" if r["guest_session_id"] else f"c:{r['conversation']}"
        s = shoppers.setdefault(k, {"in": False, "quiz": False})
        s["in"] = s["in"] or bool(r["user_id"])
        s["quiz"] = s["quiz"] or bool(r["has_profile"])
        convs.add(r["conversation"])
    counted = [r for r in answered if r["has_tokens"]]
    toks = sum((r["prompt_tokens"] or 0) + (r["completion_tokens"] or 0) for r in counted)
    cost = sum(r["cost_usd"] or 0 for r in counted)
    return {"messages": len(rows), "answered": len(answered), "failed": len(rows) - len(answered), "chats": len(convs), "shoppers": len(shoppers),
            "logged_in_shoppers": sum(1 for s in shoppers.values() if s["in"]), "shoppers_with_quiz": sum(1 for s in shoppers.values() if s["quiz"]),
            "messages_per_chat": round(len(rows) / len(convs), 1) if convs else 0, "median_latency_ms": _med([r["latency_ms"] for r in answered]),
            "thumbs_up": sum(1 for r in rows if r["rating"] == 1), "thumbs_down": sum(1 for r in rows if r["rating"] == -1),
            "could_not_answer": sum(1 for r in answered if r["could_not_answer"]), "tokens_per_message": round(toks / len(counted)) if counted else 0,
            "cost_usd": cost, "cost_inr": cost * INR_PER_USD, "cost_inr_per_message": (cost * INR_PER_USD / len(counted)) if counted else 0}


def _plural(n, one_, many=None):
    return f"{n:,} {one_ if n == 1 else (many or one_ + 's')}"


def _insights(d) -> list[dict]:
    t = d["totals"]
    out = []
    if not t["messages"]:
        return [{"tone": "info", "text": "Nobody chatted with Roop in this period."}]
    out.append({"tone": "info", "text": f"{_plural(t['shoppers'], 'shopper')} sent {_plural(t['messages'], 'message')} in {_plural(t['chats'], 'chat')}, about {t['messages_per_chat']} per chat. "
                                        f"{_pct(t['logged_in_shoppers'], t['shoppers'])}% were logged in and {_pct(t['shoppers_with_quiz'], t['shoppers'])}% had a finished skin quiz."})
    if t["failed"]:
        r = d["failures"][0]
        share = _pct(t["failed"], t["messages"])
        out.append({"tone": "warn" if share >= 5 else "info", "text": f"{_plural(t['failed'], 'message')} ({share}%) got no answer, mostly: {r['name']} ({r['count']})."})
    else:
        out.append({"tone": "good", "text": "Every message got an answer."})
    topics = [x for x in d["topics"] if x["name"] != "Other"][:3]
    if topics:
        out.append({"tone": "info", "text": f"Most asked about: {', '.join(x['name'].lower() for x in topics)}."})
    rated = t["thumbs_up"] + t["thumbs_down"]
    if rated:
        liked = _pct(t["thumbs_up"], rated)
        out.append({"tone": "good" if liked >= 70 else "warn", "text": f"Shoppers rated {_plural(rated, 'answer')}: {liked}% helpful ({t['thumbs_up']} up, {t['thumbs_down']} down)."})
    else:
        out.append({"tone": "info", "text": "No answers were rated yet."})
    if t["could_not_answer"]:
        share = _pct(t["could_not_answer"], t["answered"])
        out.append({"tone": "warn" if share >= 15 else "info", "text": f"Roop couldn't fully answer {_plural(t['could_not_answer'], 'question')} ({share}%). They're listed below."})
    if t["median_latency_ms"] > 5000:
        out.append({"tone": "warn", "text": f"Answers are slow: usually {t['median_latency_ms'] / 1000:.1f} seconds."})
    return out


@app.get("/api/chats")
def chats(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, compare: bool = False):
    """The whole Roop chats tab for a date range: totals, topics, questions, products, failures, rated answers, conversations (with their visits)."""
    if not has_chats():
        return {"ready": False}
    rows = _rows(date_from, date_to, include_excluded)
    names = _names()
    topics, questions, asked, rec, fails, models = Counter(), Counter(), Counter(), Counter(), Counter(), Counter()
    daily: dict = {}
    convs: dict = {}
    for r in rows:
        d = daily.setdefault(str(r["date_ist"]), {"day": str(r["date_ist"]), "messages": 0, "failed": 0})
        d["messages"] += 1
        d["failed"] += 1 if r["error"] else 0
        topics[r["topic"]] += 1
        questions[re.sub(r"\s+", " ", str(r["question"] or "").strip().lower())] += 1
        if r["product_id"]:
            asked[r["product_id"]] += 1
        if r["error"]:
            fails[r["failure"]] += 1
        if r["model"]:
            models[r["model"]] += 1
        for pid in _ids(r["product_ids"]):
            if pid != r["product_id"]:
                rec[pid] += 1
        c = convs.setdefault(r["conversation"], {"key": r["conversation"], "user_id": None, "guest_session_id": None, "product_id": None, "started_at": r["ts_ist"], "updated_at": r["ts_ist"],
                                                 "messages": 0, "failed": 0, "thumbs_up": 0, "thumbs_down": 0, "questions": [], "sessions": []})
        c["user_id"] = c["user_id"] or r["user_id"]
        c["guest_session_id"] = c["guest_session_id"] or r["guest_session_id"]
        c["product_id"] = c["product_id"] or r["product_id"]
        c["updated_at"] = r["ts_ist"]
        c["messages"] += 1
        c["failed"] += 1 if r["error"] else 0
        c["thumbs_up"] += 1 if r["rating"] == 1 else 0
        c["thumbs_down"] += 1 if r["rating"] == -1 else 0
        c["questions"].append(str(r["question"] or "")[:160])
        if r["session_id"] and r["session_id"] not in c["sessions"]:
            c["sessions"].append(r["session_id"])
    days = daily
    if date_from and date_to:  # a gap-free spine
        from datetime import date, timedelta
        d, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
        days = {}
        while d <= end:
            days[d.isoformat()] = daily.get(d.isoformat(), {"day": d.isoformat(), "messages": 0, "failed": 0})
            d += timedelta(days=1)

    answered = [r for r in rows if not r["error"]]
    outcomes = Counter(r["outcome"] for r in answered if r.get("outcome") in OUTCOMES)
    every = sorted(convs.values(), key=lambda c: str(c["updated_at"]), reverse=True)
    shown = every[:CONVERSATIONS_SHOWN]
    sess = _sessions([s for c in every for s in c["sessions"]])
    returning = _group_shoppers(every, sess)
    for c in every:
        first = next((sess[s] for s in c["sessions"] if s in sess), {})
        c.update(product_name=_name(c["product_id"], names) if c["product_id"] else None, city=first.get("city"), ip=first.get("ip"), visitor_id=first.get("visitor_key"),
                 channel=first.get("channel"), device=("Android app" if first.get("is_app") else first.get("device")) if first else None)

    def answer(r):
        return {"conversation": r["conversation"], "at": r["ts_ist"], "question": r["question"], "reply": readable(r["reply"], names),
                "product_name": _name(r["product_id"], names) if r["product_id"] else None, "session_id": r["session_id"]}
    named = lambda items: [{**i, "label": _name(i["name"], names)} for i in items]  # noqa: E731
    data = {"ready": True, "totals": _totals(rows), "daily": sorted(days.values(), key=lambda x: x["day"]), "topics": _top(topics, 12), "top_questions": _top(questions, 12),
            "products_asked_about": named(_top(asked, 10)), "products_recommended": named(_top(rec, 10)), "failures": _top(fails, 6), "models": _top(models, 5),
            "outcomes": [{**item, "label": OUTCOMES[item["name"]]} for item in _top(outcomes, len(OUTCOMES))],
            "assortment_demand": _assortment_demand(answered),
            "disliked": [answer(r) for r in reversed([r for r in answered if r["rating"] == -1])][:20],
            "could_not_answer": [answer(r) for r in reversed([r for r in answered if r["could_not_answer"]])][:20],
            "conversations_total": len(convs), "conversations": shown,
            "returning": returning[:CONVERSATIONS_SHOWN], "returning_total": len(returning), "returning_chats": sum(g["n_chats"] for g in returning),
            "link": {"messages": len(rows), "with_visit": sum(1 for r in rows if r["session_id"])}}
    data["insights"] = _insights(data)
    pr = prev_range(date_from, date_to) if compare else None
    if pr:
        data["prev"] = {"range": pr, "totals": _totals(_rows(pr[0], pr[1], include_excluded))}
    return data


@app.get("/api/chats/{key:path}")
def chat_conversation(key: str):
    """One conversation, turn by turn, with the visit(s) it happened in (the session data)."""
    if not has_chats():
        raise HTTPException(404, "no chats")
    rows = _rows(None, None, True, conversation=key)
    if not rows:
        raise HTTPException(404, "No chat found.")
    names = _names()
    sess = _sessions([r["session_id"] for r in rows])
    order = list(dict.fromkeys(r["session_id"] for r in rows if r["session_id"]))
    first_user = next((r["user_id"] for r in rows if r["user_id"]), None)
    person = one("SELECT person_key, name, phone10, email, segment, is_registered, orders, sessions FROM users_360 WHERE user_id = ?", [first_user]) if first_user else {}
    prod = next((r["product_id"] for r in rows if r["product_id"]), None)
    return {"key": key, "user_id": first_user, "guest_session_id": rows[0]["guest_session_id"], "has_quiz": any(r["has_profile"] for r in rows), "product_id": prod,
            "product_name": _name(prod, names) if prod else None, "person": person or None,
            "sessions": [{**sess[s], "messages": sum(1 for r in rows if r["session_id"] == s)} for s in order if s in sess],
            "turns": [{"id": r["id"], "at": r["ts_ist"], "question": r["question"], "reply": None if r["error"] else readable(r["reply"], names), "error": r["failure"] if r["error"] else None,
                       "rating": r["rating"], "latency_ms": r["latency_ms"], "tokens": (r["prompt_tokens"] or 0) + (r["completion_tokens"] or 0), "topic": r["topic"],
                       "outcome": OUTCOMES.get(r.get("outcome")),
                       "products": [_name(p, names) for p in _ids(r["product_ids"]) if p != r["product_id"]], "session_id": r["session_id"], "session_link": r["session_link"]} for r in rows]}


def session_chats(session_id: str) -> list[dict]:
    """The Roop messages sent in one visit (for the session page: shown in the timeline and as a list)."""
    if not has_chats():
        return []
    names = _names()
    return [{"id": r["id"], "at": r["ts_ist"], "question": r["question"], "reply": None if r["error"] else readable(r["reply"], names), "error": r["failure"] if r["error"] else None,
             "rating": r["rating"], "conversation": r["conversation"]} for r in _rows(None, None, True, session=session_id)]

"""The product match score for events that arrive without one.

The tracker puts `product_match_score` on product views, card clicks and some add-to-cart events, but not on all of them. Such an event takes the
score of the latest earlier event of the SAME visit about the SAME product (by name, or by the product page's address). A borrowed score keeps the name
of the event it came from in `score_from`, so the screen can mark it. An event that says "not scorable" keeps saying that.
"""
import re
from urllib.parse import unquote

from .core import q
from .payload import flat_payload, match_score

_PAGE = re.compile(r"/products/([^/?#]+)")
_WORDS = ("add_to_cart", "addtocart", "clicked_product", "clicked_on_product", "buy_now", "product_card")


def wants_score(name, key) -> bool:
    return key in ("add_to_cart", "product_view") or any(w in (name or "").lower() for w in _WORDS)


def product_of(product_name, path) -> set:
    """The ways an event names its product (empty when it names none)."""
    out = set()
    n = (product_name or "").strip().lower()
    if n and n != "product":  # the tracker's placeholder
        out.add(f"name:{n}")
    m = _PAGE.search(path or "")
    if m:
        out.add(f"page:{unquote(m.group(1)).lower()}")
    return out


def borrow(targets: list[dict], sources: list[dict]) -> None:
    """Fill `score` / `score_from` on the targets that need one. Both are dicts with at, event_name, product_name, path (and session_id when they
    come from several visits); sources also have a numeric `score`."""
    by_session: dict = {}
    for s in sources:
        if s.get("score") is not None and not s.get("score_from"):
            ids = product_of(s.get("product_name"), s.get("path"))
            if ids:
                by_session.setdefault(s.get("session_id"), []).append((s["at"], ids, s["score"], s["event_name"]))
    for lst in by_session.values():
        lst.sort(key=lambda x: x[0])
    for t in targets:
        t.setdefault("score_from", None)
        if t.get("score") is not None or t.get("score_note") or not wants_score(t.get("event_name"), t.get("event_key")):
            continue
        ids = product_of(t.get("product_name"), t.get("path"))
        for at, theirs, score, name in reversed(by_session.get(t.get("session_id"), [])):
            if at <= t["at"] and ids & theirs:
                t["score"], t["score_from"] = score, name
                break


def scored_events(session_ids: list[str]) -> list[dict]:
    """Every event of these visits that carries a numeric score."""
    if not session_ids:
        return []
    rows = q("""SELECT e.session_id, e.ts_ist AS at, e.event_name, e.product_name, e.path, r.extra_data::VARCHAR AS x
                FROM events_clean e JOIN raw_event_log r ON r.id = e.id
                WHERE e.session_id IN (SELECT unnest(?::VARCHAR[])) AND (contains(r.extra_data::VARCHAR, 'product_match_score') OR contains(r.extra_data::VARCHAR, 'matchScore'))""",
             [sorted(set(session_ids))])
    for r in rows:
        r["score"], _ = match_score(flat_payload(r.pop("x")))
    return [r for r in rows if r["score"] is not None]

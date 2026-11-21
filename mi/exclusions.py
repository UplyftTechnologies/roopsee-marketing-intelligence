"""Excluding internal, test and bot traffic: rules, bulk edit, import / export and the inventory."""
import csv
import io
import json
from datetime import date, datetime
from fastapi import HTTPException, Query, Response
from pydantic import BaseModel

from . import core
from .db import DB_LOCK
from .transform import EXCLUSION_KINDS, EXCL_JOINS, RULE_SQL
from .core import JOB, _reapply, app, one, q


class ExclIn(BaseModel):
    kind: str
    value: str
    note: str | None = None
    active: bool = True


class ExclPatch(BaseModel):
    kind: str | None = None
    value: str | None = None
    note: str | None = None
    active: bool | None = None


def _check_kind(kind: str):
    if kind not in EXCLUSION_KINDS:
        raise HTTPException(400, f"kind must be one of {list(EXCLUSION_KINDS)}")


@app.get("/api/exclusions")
def list_exclusions():
    return {"kinds": EXCLUSION_KINDS, "rows": q("SELECT * FROM exclusions ORDER BY active DESC, id DESC")}


@app.post("/api/exclusions")
def add_exclusions(body: ExclIn, apply: bool = True):
    """`value` may hold several entries separated by newlines or commas."""
    _check_kind(body.kind)
    vals = [v.strip() for v in body.value.replace(",", "\n").splitlines() if v.strip()]
    if not vals:
        raise HTTPException(400, "value is empty")
    ids = []
    with DB_LOCK:
        for v in vals:
            if core.CON.execute("SELECT 1 FROM exclusions WHERE kind=? AND lower(value)=lower(?)", [body.kind, v]).fetchone():
                continue
            ids.append(core.CON.execute("INSERT INTO exclusions (kind, value, note, active) VALUES (?,?,?,?) RETURNING id",
                                   [body.kind, v, body.note, body.active]).fetchone()[0])
    if apply and ids:
        _reapply()
    return {"added": len(ids), "ids": ids, "job": JOB}


@app.put("/api/exclusions/{eid}")
def update_exclusion(eid: int, body: ExclPatch, apply: bool = True):
    if body.kind:
        _check_kind(body.kind)
    sets, args = [], []
    for f in ("kind", "value", "note", "active"):
        v = getattr(body, f)
        if v is not None:
            sets.append(f"{f} = ?"); args.append(v.strip() if isinstance(v, str) else v)
    if not sets:
        raise HTTPException(400, "nothing to update")
    with DB_LOCK:
        if not core.CON.execute("SELECT 1 FROM exclusions WHERE id=?", [eid]).fetchone():
            raise HTTPException(404, "not found")
        core.CON.execute(f"UPDATE exclusions SET {', '.join(sets)}, updated_at = now() WHERE id = ?", [*args, eid])
    if apply:
        _reapply()
    return {"ok": True, "job": JOB}


@app.delete("/api/exclusions/{eid}")
def delete_exclusion(eid: int, apply: bool = True):
    with DB_LOCK:
        core.CON.execute("DELETE FROM exclusions WHERE id=?", [eid])
    if apply:
        _reapply()
    return {"ok": True, "job": JOB}


@app.post("/api/exclusions/apply")
def apply_exclusions():
    _reapply()
    return JOB


@app.get("/api/exclusions/preview")
def preview_exclusion(kind: str, value: str):
    """How much traffic would this exclusion remove? Evaluated against the current clean tables."""
    _check_kind(kind)
    v = value.strip()
    if kind in ("source", "campaign", "channel"):
        col = {"source": "source", "campaign": "campaign", "channel": "channel"}[kind]
        r = one(f"SELECT count(*) sessions, coalesce(sum(events),0) events FROM sessions WHERE lower({col}) = lower(?)", [v])
        return {"sessions": r["sessions"], "events": r["events"], "people": None}
    if kind == "rule":
        cond = next((c for n, c, _ in RULE_SQL if n == v), None)
        if not cond:
            raise HTTPException(400, f"unknown rule; use one of {[n for n, _, _ in RULE_SQL]}")
    else:
        cond = next(c for k, c, _ in EXCL_JOINS if k == kind)
    sql = f"""SELECT count(*) events, count(DISTINCT e.session_id) sessions, count(DISTINCT e.person_key) people
              FROM events_clean e, (SELECT lower(trim(?)) AS v) x WHERE {cond if kind != 'rule' else cond}"""
    return one(sql, [v])


@app.get("/api/lookup")
def lookup(q_: str = Query(..., alias="q", min_length=2), limit: int = 12):
    """Find identifiers (names, IPs, phones, ids...) so they can be excluded with one click."""
    like = f"%{q_.lower()}%"
    cols = [("name", "coalesce(nullif(account_name,''), nullif(user_name,''))"), ("ip", "ip"), ("phone", "phone10"),
            ("email", "email_l"), ("session_id", "session_id"), ("visitor_id", "visitor_key"), ("user_id", "user_id"),
            ("city", "city_n"), ("host", "host")]
    out = []
    for kind, expr in cols:
        for r in q(f"""SELECT '{kind}' AS kind, {expr} AS value, count(*) events, count(DISTINCT session_id) sessions, max(ts) AS last_seen,
                       bool_and(is_excluded) AS excluded FROM events_clean WHERE lower({expr}) LIKE ? AND {expr} IS NOT NULL
                       AND {expr} NOT IN ('Guest') GROUP BY 2 ORDER BY 3 DESC, 2 LIMIT ?""", [like, limit]):
            out.append(r)
    return out


class BulkItem(BaseModel):
    kind: str
    value: str
    note: str | None = None
    active: bool = True


class BulkIn(BaseModel):
    items: list[BulkItem]
    apply: bool = True


class ImportIn(BaseModel):
    exclusions: list[BulkItem]
    dry_run: bool = True


def _classify(items: list[BulkItem]) -> tuple[list[BulkItem], int, list[dict]]:
    """Split into (new, duplicate count, invalid rows) against what is already in the list."""
    with DB_LOCK:
        have = {(k, str(v).lower()) for k, v in core.CON.execute("SELECT kind, value FROM exclusions").fetchall()}
    new, dup, invalid, seen = [], 0, [], set()
    for it in items:
        kind, value = it.kind.strip(), it.value.strip()
        if kind not in EXCLUSION_KINDS:
            invalid.append({"kind": it.kind, "value": it.value, "why": "unknown type"})
        elif not value or len(value) > 300:
            invalid.append({"kind": kind, "value": value[:40], "why": "empty or too long"})
        elif (kind, value.lower()) in have or (kind, value.lower()) in seen:
            dup += 1
        else:
            seen.add((kind, value.lower()))
            new.append(BulkItem(kind=kind, value=value, note=it.note, active=it.active))
    return new, dup, invalid


def _insert_exclusions(items: list[BulkItem], note_suffix: str = "") -> int:
    with DB_LOCK:
        for it in items:
            core.CON.execute("INSERT INTO exclusions (kind, value, note, active, source) VALUES (?,?,?,?, 'manual')",
                        [it.kind, it.value, ((it.note or "") + note_suffix).strip() or None, it.active]).fetchall()
    return len(items)


@app.post("/api/exclusions/bulk")
def bulk_exclusions(body: BulkIn):
    """Add many exclusions at once (one rebuild, not one per row)."""
    if len(body.items) > 5000:
        raise HTTPException(400, "too many items (max 5000)")
    new, dup, invalid = _classify(body.items)
    added = _insert_exclusions(new)
    if body.apply and added:
        _reapply()
    return {"added": added, "skipped": dup, "invalid": invalid[:20], "job": JOB}


@app.get("/api/exclusions/export")
def export_exclusions(format: str = "json", include_builtin: bool = False):
    """Download the exclusion list as a file that another dashboard can import."""
    rows = q("SELECT kind, value, note, active, source FROM exclusions ORDER BY kind, lower(value)")
    if not include_builtin:
        rows = [r for r in rows if r["source"] != "default"]
    stamp = date.today().isoformat()
    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["kind", "value", "note", "active"])
        for r in rows:
            w.writerow([r["kind"], r["value"], r["note"] or "", "true" if r["active"] else "false"])
        return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="roopsee-exclusions-{stamp}.csv"'})
    payload = {"format": "roopsee-exclusions", "version": 1, "exported_at": datetime.now().isoformat(timespec="seconds"), "count": len(rows),
               "exclusions": [{"kind": r["kind"], "value": r["value"], "note": r["note"], "active": bool(r["active"])} for r in rows]}
    return Response(json.dumps(payload, indent=2, ensure_ascii=False), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="roopsee-exclusions-{stamp}.json"'})


@app.post("/api/exclusions/import")
def import_exclusions(body: ImportIn):
    """dry_run=true previews (new / already present / invalid); dry_run=false merges the new ones and rebuilds once."""
    if len(body.exclusions) > 5000:
        raise HTTPException(400, "too many items (max 5000)")
    new, dup, invalid = _classify(body.exclusions)
    if not body.dry_run and new:
        _insert_exclusions(new, " [imported]")
        _reapply()
    return {"applied": not body.dry_run, "new": len(new), "duplicates": dup, "invalid": invalid[:20], "invalid_count": len(invalid),
            "preview": [{"kind": n.kind, "value": n.value, "note": n.note} for n in new[:50]]}


@app.get("/api/exclusions/inventory")
def exclusion_inventory():
    """Every identifier we have reason to think is internal / automated, with how much of it is still counted in the numbers."""
    items: dict = {}

    def add(kind, value, label, reason, total=0, counted=0, last=None, shared=None):
        if value is None or str(value).strip() == "":
            return
        k = (kind, str(value).lower())
        it = items.setdefault(k, {"kind": kind, "value": str(value), "label": label, "reasons": [], "sessions": 0, "counted": 0, "last_seen": None, "shared": None})
        if reason not in it["reasons"]:
            it["reasons"].append(reason)
        it["label"] = it["label"] or label
        it["sessions"] = max(it["sessions"], total or 0)
        it["counted"] = max(it["counted"], counted or 0)
        if last and (not it["last_seen"] or last > it["last_seen"]):
            it["last_seen"] = last
        if shared is not None:
            it["shared"] = shared

    # 1. staff accounts (admin / rider / doctor) and their contact details
    ustat = {r["user_id"]: r for r in q("SELECT user_id, count(*) n, count(*) FILTER (WHERE NOT is_excluded) c, max(started_at) last FROM sessions WHERE user_id IS NOT NULL GROUP BY 1")}
    for r in q("""SELECT lower(id) uid, name, role, nullif(lower(email), '') email,
                  nullif(right(regexp_replace(coalesce(phone_no, ''), '[^0-9]', '', 'g'), 10), '') phone FROM raw_users WHERE role IN ('admin','rider','doctor')"""):
        st = ustat.get(r["uid"], {})
        why = f"staff account ({r['role']})"
        n, c, last = st.get("n", 0), st.get("c", 0), st.get("last")
        add("user_id", r["uid"], r["name"], why, n, c, last)
        add("email", r["email"], r["name"], why + " email", n, c, last)
        add("phone", r["phone"], r["name"], why + " phone", n, c, last)
        if r["name"] and len(r["name"].strip()) > 2:
            add("name", r["name"].strip(), r["name"], why + " name", n, c, last)

    # 2. company-domain emails (from the active @domain exclusions)
    doms = [r["value"].lower() for r in q("SELECT value FROM exclusions WHERE active AND kind = 'email' AND value LIKE '@%'")]
    for d in doms:
        for r in q("SELECT lower(id) uid, name, lower(email) email FROM raw_users WHERE lower(email) LIKE ?", [f"%{d}"]):
            st = ustat.get(r["uid"], {})
            add("email", r["email"], r["name"], f"company email ({d})", st.get("n", 0), st.get("c", 0), st.get("last"))

    # 3. anything seen inside /admin: browsers, IPs, phones
    for r in q("""WITH adm AS (SELECT visitor_key, count(DISTINCT session_id) internal FROM events_clean WHERE page_type = 'admin' GROUP BY 1)
                  SELECT a.visitor_key, a.internal, count(s.session_id) n, count(s.session_id) FILTER (WHERE NOT s.is_excluded) c, max(s.started_at) last
                  FROM adm a LEFT JOIN sessions s ON s.visitor_key = a.visitor_key GROUP BY a.visitor_key, a.internal"""):
        add("visitor_id", r["visitor_key"], None, f"opened /admin ({r['internal']} sessions)", r["n"], r["c"], r["last"])
    for r in q("""WITH adm AS (SELECT ip, count(DISTINCT session_id) internal FROM events_clean WHERE page_type = 'admin' AND ip IS NOT NULL GROUP BY 1)
                  SELECT a.ip, a.internal, count(s.session_id) n, count(s.session_id) FILTER (WHERE NOT s.is_excluded) c, count(DISTINCT s.visitor_key) browsers, max(s.started_at) last
                  FROM adm a LEFT JOIN sessions s ON s.ip = a.ip GROUP BY a.ip, a.internal"""):
        add("ip", r["ip"], None, f"used inside /admin ({r['internal']} sessions)", r["n"], r["c"], r["last"], r["browsers"])
    for r in q("""WITH adm AS (SELECT phone10, count(DISTINCT session_id) internal FROM events_clean WHERE page_type = 'admin' AND phone10 IS NOT NULL GROUP BY 1)
                  SELECT a.phone10, a.internal, count(s.session_id) n, count(s.session_id) FILTER (WHERE NOT s.is_excluded) c, max(s.started_at) last
                  FROM adm a LEFT JOIN sessions s ON s.phone10 = a.phone10 GROUP BY a.phone10, a.internal"""):
        add("phone", r["phone10"], None, f"used inside /admin ({r['internal']} sessions)", r["n"], r["c"], r["last"])

    # 4. bot-like anonymous browsers: many very short sessions
    for r in q("""SELECT visitor_key, count(*) n, count(*) FILTER (WHERE NOT is_excluded) c, avg(duration_s) avg_s, max(started_at) last, mode(ip) top_ip
                  FROM sessions WHERE user_id IS NULL GROUP BY 1 HAVING count(*) >= 30 AND avg(duration_s) < 5"""):
        why = f"bot-like: {r['n']} sessions averaging {r['avg_s']:.1f}s"
        add("visitor_id", r["visitor_key"], None, why, r["n"], r["c"], r["last"])
        if r["top_ip"]:
            ipst = one("SELECT count(*) n, count(*) FILTER (WHERE NOT is_excluded) c, count(DISTINCT visitor_key) b FROM sessions WHERE ip = ?", [r["top_ip"]])
            add("ip", r["top_ip"], None, why, ipst["n"], ipst["c"], r["last"], ipst["b"])

    listed = {(r["kind"], str(r["value"]).lower()) for r in q("SELECT kind, value FROM exclusions WHERE active")}
    rows = []
    for it in items.values():
        it["reason"] = " · ".join(it["reasons"])
        it["in_list"] = (it["kind"], it["value"].lower()) in listed
        it["risky"] = it["kind"] == "ip" and (it["shared"] or 0) >= 4  # shared IP (carrier / office): may belong to many customers
        rows.append(it)
    rows.sort(key=lambda r: (-r["counted"], -r["sessions"], r["kind"]))
    by_kind: dict = {}
    for r in rows:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    return {"rows": rows, "summary": {"total": len(rows), "in_list": sum(r["in_list"] for r in rows), "still_counted": sum(1 for r in rows if r["counted"] > 0 and not r["in_list"]), "by_kind": by_kind}}


@app.get("/api/staff-orders")
def staff_orders():
    """Orders placed from accounts with a staff role (admin / rider / doctor), one row per account, with the evidence of whether they are real sales.
    Marking an account "real customer" (kind real_customer) counts its orders everywhere; the account's visits stay hidden."""
    marked = {str(r["value"]).lower() for r in q("SELECT value FROM exclusions WHERE kind = 'real_customer' AND active")}
    rule_on = bool(q("SELECT 1 FROM exclusions WHERE kind = 'rule' AND value = 'staff_orders' AND active"))
    rows = q("""SELECT o.user_id, max(o.customer_name) AS name, max(u.role) AS role, max(o.phone10) AS phone10, count(*) AS orders, coalesce(sum(o.total), 0) AS revenue,
                count(*) FILTER (WHERE o.delivered_at IS NOT NULL OR o.status IN ('delivered', 'completed', 'out_for_delivery', 'picked_up')) AS shipped,
                count(*) FILTER (WHERE o.payment_state = 'confirmed') AS paid, count(*) FILTER (WHERE upper(coalesce(o.payment_method, '')) LIKE 'COD%') AS cod,
                count(DISTINCT o.phone10) AS phones, count(DISTINCT o.city) AS cities, min(o.ts) AS first_order, max(o.ts) AS last_order
                FROM orders_clean o JOIN raw_users u ON lower(u.id) = o.user_id WHERE o.is_valid AND u.role IN ('admin', 'rider', 'doctor') GROUP BY 1 ORDER BY revenue DESC""")
    for r in rows:
        r["real_customer"] = str(r["user_id"]).lower() in marked
        r["counted"] = r["real_customer"] or not rule_on
        r["looks_real"] = r["shipped"] >= max(1, r["orders"] // 2) and r["paid"] >= 1  # most orders shipped and at least one confirmed payment
    return {"rule_on": rule_on, "accounts": rows,
            "totals": {"orders": sum(r["orders"] for r in rows), "revenue": sum(r["revenue"] for r in rows),
                       "counted_orders": sum(r["orders"] for r in rows if r["counted"]), "counted_revenue": sum(r["revenue"] for r in rows if r["counted"])}}

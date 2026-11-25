"""Data status, refresh jobs and data health."""
import re
from datetime import date, datetime, timedelta, timezone

from . import adimages, core, extract, meta as meta_mod, transform
from .transform import EXCLUSION_KINDS
from .core import JOB, _run_job, app, has_tables, one, q


@app.get("/api/meta")
def meta():
    out = {"job": JOB, "kinds": EXCLUSION_KINDS, "ready": False}
    out["raw_events"] = one("SELECT count(*) AS n, min(created_at) AS first, max(created_at) AS last FROM raw_event_log")
    if has_tables():
        out["ready"] = True
        out["counts"] = one("""SELECT (SELECT count(*) FROM events_base WHERE NOT is_dup) events, (SELECT count(*) FROM events_clean WHERE is_excluded AND NOT is_dup) events_excluded,
            (SELECT count(*) FROM events_base WHERE is_dup) events_duplicate,
            (SELECT count(*) FROM sessions) sessions, (SELECT count(*) FROM sessions WHERE is_excluded) sessions_excluded,
            (SELECT count(*) FROM users_360) people, (SELECT count(*) FROM users_360 WHERE is_excluded) people_excluded,
            (SELECT count(*) FROM orders_clean WHERE is_valid) orders, (SELECT count(*) FROM orders_clean WHERE is_valid AND is_excluded) orders_excluded""")
        out["range"] = one("SELECT min(date_ist) AS first, max(date_ist) AS last FROM sessions")
        out["last_transform"] = one("SELECT v FROM etl_meta WHERE k='last_transform'").get("v")
        tc = _tracking_change()
        out["tracking_change"] = str(tc) if tc else None
    return out


@app.post("/api/refresh")
def refresh(mode: str = "full"):
    """full = pull new data from Supabase (read-only) then rebuild; transform = rebuild only."""
    def fn():
        if mode == "full":
            JOB["message"] = "pulling data from Supabase"
            extract.run(core.CON.cursor(), progress=lambda m: JOB.update(message=m))
            if meta_mod.configured():
                JOB["message"] = "pulling Meta Ads"
                try:
                    meta_mod.sync(core.CON.cursor())
                    adimages.cache(core.CON.cursor())
                except Exception as e:  # keep the refresh going; the error is shown on the Meta Ads page
                    meta_mod.record_error(core.CON.cursor(), e)
        JOB["message"] = "rebuilding the analytics tables"
        transform.run(core.CON.cursor(), progress=lambda m: JOB.update(message=m))
    _run_job(f"refresh:{mode}", fn)
    return JOB


@app.get("/api/jobs")
def jobs():
    return JOB


def _tracking_change():
    """Date the current tracker went live (first session_started event). Session ids, bounce and duration before it are not comparable."""
    return one("SELECT min(ts_ist)::DATE AS d FROM events_base WHERE event_name = 'session_started'").get("d")


@app.get("/api/health")
def data_health():
    """Is the data fresh and trustworthy? Each check is ok / warn / bad with a plain-language detail, plus the last pipeline runs."""
    checks = []

    def add(key, label, status, detail):
        checks.append({"key": key, "label": label, "status": status, "detail": detail})

    raw = one("SELECT max(created_at) AS last_event, count(*) AS n FROM raw_event_log")
    if raw.get("last_event"):
        lag = (datetime.now(timezone.utc) - raw["last_event"].astimezone(timezone.utc)).total_seconds() / 3600
        add("fresh", "Newest event", "ok" if lag <= 6 else "warn" if lag <= 24 else "bad",
            f"{lag:.0f} hour{'' if round(lag) == 1 else 's'} old (latest {raw['last_event'].astimezone(timezone(timedelta(hours=5, minutes=30))):%d %b %H:%M} IST). Press Refresh data to pull newer events.")
    else:
        add("fresh", "Newest event", "bad", "No events loaded yet")
    if not has_tables():
        return {"status": "bad", "checks": checks, "runs": []}
    last_t = one("SELECT v FROM etl_meta WHERE k='last_transform'").get("v")
    add("transform", "Analytics tables", "ok" if last_t else "bad", f"Rebuilt {last_t}" if last_t else "Never built")
    runs = q("SELECT step, finished_at, rows, note FROM etl_runs ORDER BY finished_at DESC LIMIT 12")
    ev = q("SELECT rows FROM etl_runs WHERE step = 'extract:event_log' ORDER BY finished_at DESC LIMIT 2")
    if len(ev) == 2 and ev[0]["rows"] is not None and ev[1]["rows"] is not None and ev[0]["rows"] < ev[1]["rows"]:
        add("rows", "Event count", "bad", f"Stored events went down ({ev[1]['rows']:,} to {ev[0]['rows']:,}). Something removed data.")
    skipped = [r for r in runs if (r["note"] or "").startswith("skipped")]
    if skipped:
        add("skipped", "Table pulls", "bad", f"{skipped[0]['step'].replace('extract:raw_', '')} was not updated: {skipped[0]['note']}")
    t = one("""SELECT (SELECT count(*) FROM events_base) AS ev, (SELECT count(*) FROM events_base WHERE is_dup) AS dup,
               (SELECT count(*) FROM events_base WHERE visitor_id IS NULL) AS no_vis,
               (SELECT count(*) FROM orders_clean WHERE is_valid AND date_ist >= (SELECT min(date_ist) FROM sessions)) AS orders,
               (SELECT count(*) FROM orders_clean WHERE is_valid AND session_id IS NULL AND date_ist >= (SELECT min(date_ist) FROM sessions)) AS orders_nosess,
               (SELECT count(*) FROM orders_clean WHERE is_valid AND date_ist < (SELECT min(date_ist) FROM sessions)) AS orders_pretracking,
               (SELECT count(*) FROM orders_clean WHERE is_valid AND payment_state IN ('unconfirmed', 'conflicting')) AS risk,
               (SELECT coalesce(sum(total), 0) FROM orders_clean WHERE is_valid AND payment_state IN ('unconfirmed', 'conflicting')) AS risk_v,
               (SELECT count(*) FROM sessions) AS sess, (SELECT count(*) FROM sessions WHERE city IS NULL) AS sess_nocity,
               (SELECT count(*) FROM sessions WHERE is_excluded) AS sess_ex""")
    pc = lambda a, b: (100.0 * a / b) if b else 0.0
    d = pc(t["dup"], t["ev"])
    add("dups", "Repeated events", "ok" if d <= 50 else "warn", f"{d:.0f}% of tracked events are repeats of the same action (hidden from counts, kept in the raw data).")
    v = pc(t["no_vis"], t["ev"])
    add("visitor", "Events without a browser id", "ok" if v <= 20 else "warn", f"{v:.0f}% of events carry no browser id, so they are grouped by session only.")
    o = pc(t["orders_nosess"], t["orders"])
    add("order_session", "Orders linked to a visit", "ok" if o <= 10 else "warn" if o <= 25 else "bad",
        f"{t['orders'] - t['orders_nosess']} of {t['orders']} sales since tracking began are linked to the visit that produced them."
        + (f" {t['orders_pretracking']} earlier sales predate tracking, so they have no visit to link to." if t["orders_pretracking"] else ""))
    add("payment", "Payment confirmed", "ok" if not t["risk"] else "warn",
        "Every counted sale has a confirmed or expected payment." if not t["risk"] else f"{t['risk']} counted sale(s) worth ₹{t['risk_v']:,.0f} have no confirmed payment.")
    c = pc(t["sess_nocity"], t["sess"])
    add("geo", "Sessions with a place", "ok" if c <= 20 else "warn", f"{100 - c:.0f}% of sessions have a city (from the visitor's IP address).")
    add("excluded", "Hidden internal and bot traffic", "ok", f"{pc(t['sess_ex'], t['sess']):.0f}% of sessions are hidden by the exclusion rules.")
    # days with no sessions at all, or far fewer than usual, point to tracking that was down
    days = q("""WITH d AS (SELECT unnest(generate_series(min(date_ist), max(date_ist), INTERVAL 1 DAY))::DATE AS day FROM sessions),
                n AS (SELECT date_ist AS day, count(*) AS s FROM sessions GROUP BY 1),
                m AS (SELECT median(s) AS med FROM n)
                SELECT d.day, coalesce(n.s, 0) AS sessions, (SELECT med FROM m) AS typical FROM d LEFT JOIN n USING (day)
                WHERE coalesce(n.s, 0) < 0.2 * (SELECT med FROM m) AND d.day < (SELECT max(date_ist) FROM sessions) ORDER BY d.day""")
    if days:
        recent = [x for x in days if (date.today() - x["day"]).days <= 30]
        shown = ", ".join(f"{x['day']:%d %b}" + (f" ({x['sessions']} sessions)" if x["sessions"] else "") for x in days[-6:])
        add("gaps", "Days with little or no data", "warn" if recent else "ok",
            f"{len(days)} day(s) had under 20% of a typical day's visits (typical is about {days[0]['typical']:.0f}). Most recent: {shown}. "
            + ("Some are in the last 30 days, so recent numbers may be understated." if recent else "All are older than 30 days."))
    else:
        add("gaps", "Days with little or no data", "ok", "Every day since tracking began has a normal amount of data.")
    tx = one("SELECT note FROM etl_runs WHERE step = 'transform' ORDER BY finished_at DESC LIMIT 1").get("note") or ""
    mt = re.search(r"([0-9.]+)s$", tx)
    if mt:
        secs = float(mt.group(1))
        add("rebuild", "Rebuild time", "ok" if secs <= 120 else "warn",
            f"The last rebuild took {secs:.0f} seconds." + ("" if secs <= 120 else " It is getting slow; ask for an incremental rebuild."))
    order = {"ok": 0, "warn": 1, "bad": 2}
    return {"status": max((x["status"] for x in checks), key=order.get, default="ok"), "checks": checks, "runs": runs}


@app.get("/api/performance")
def performance(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False):
    """Page load speed from the tracker's own load samples."""
    w = "date_ist BETWEEN ? AND ?" + ("" if include_excluded else " AND NOT is_excluded")
    a = [date_from or "2000-01-01", date_to or "2999-12-31"]
    agg = "count(*) AS samples, quantile_cont(load_ms, 0.5) AS p50, quantile_cont(load_ms, 0.9) AS p90, count(*) FILTER (WHERE load_ms > 3000)::DOUBLE / count(*) AS slow_share"
    overall = one(f"SELECT {agg} FROM perf_samples WHERE {w}", a)
    return {"overall": overall,
            "by_page": q(f"SELECT coalesce(page_type, 'other') AS page, {agg} FROM perf_samples WHERE {w} GROUP BY 1 HAVING count(*) >= 10 ORDER BY samples DESC, 1 LIMIT 12", a),
            "by_device": q(f"SELECT device, {agg} FROM perf_samples WHERE {w} GROUP BY 1 HAVING count(*) >= 10 ORDER BY samples DESC", a),
            "daily": q(f"SELECT date_ist AS d, {agg} FROM perf_samples WHERE {w} GROUP BY 1 ORDER BY 1", a)}

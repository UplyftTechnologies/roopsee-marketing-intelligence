"""Campaigns and ad tagging health."""

from .core import app, one, q, ratio, sess_where


@app.get("/api/utm-health")
def utm_health(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False):
    """How many paid visits arrive without usable campaign tags, and which campaign names do not match anything we can identify."""
    w, a = sess_where(date_from, date_to, include_excluded)
    paid = "(s.channel IN ('Paid Google', 'Paid Meta', 'Paid Partner') OR s.has_gclid OR s.has_fbclid)"
    k = one(f"""SELECT count(*) FILTER (WHERE {paid}) AS paid, count(*) FILTER (WHERE {paid} AND s.campaign = '(not set)') AS paid_untagged,
        count(*) FILTER (WHERE (s.has_gclid OR s.has_fbclid) AND s.utm_campaign IS NULL AND s.gad_campaign IS NULL) AS clickid_no_campaign,
        count(*) FILTER (WHERE s.channel = 'Paid Meta') AS meta, count(*) FILTER (WHERE s.channel = 'Paid Meta' AND s.session_id NOT IN (SELECT session_id FROM session_meta)) AS meta_unmatched,
        count(*) FILTER (WHERE s.campaign = '(not set)') AS all_not_set, count(*) AS sessions
        FROM sessions s WHERE {w}""", a)
    by_channel = q(f"""SELECT s.channel, count(*) AS sessions, count(*) FILTER (WHERE s.campaign = '(not set)') AS not_set,
        count(*) FILTER (WHERE s.utm_source IS NULL) AS no_source, count(*) FILTER (WHERE s.utm_medium IS NULL) AS no_medium
        FROM sessions s WHERE {w} GROUP BY 1 ORDER BY 2 DESC""", a)
    unmatched = q(f"""SELECT s.campaign, count(*) AS sessions, count(DISTINCT s.visitor_key) AS visitors, min(s.date_ist) AS first_day, max(s.date_ist) AS last_day
        FROM sessions s WHERE {w} AND s.channel = 'Paid Meta' AND s.session_id NOT IN (SELECT session_id FROM session_meta)
        GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 12""", a)
    names = q(f"""SELECT lower(trim(s.campaign)) AS key, string_agg(DISTINCT s.campaign, '  |  ' ORDER BY s.campaign) AS spellings, count(DISTINCT s.campaign) AS variants, count(*) AS sessions
        FROM sessions s WHERE {w} AND s.campaign <> '(not set)' GROUP BY 1 HAVING count(DISTINCT s.campaign) > 1 ORDER BY 4 DESC, 1 LIMIT 10""", a)
    macros = q(f"""SELECT s.campaign, count(*) AS sessions FROM sessions s WHERE {w}
        AND (s.campaign LIKE '%{{{{%' OR s.campaign LIKE '%\\%7B%' ESCAPE '\\' OR s.campaign LIKE '%}}}}%' OR s.campaign LIKE '%undefined%' OR s.campaign LIKE '%null%')
        GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 8""", a)
    pct = lambda x, y: round(100.0 * x / y, 1) if y else 0.0
    checks = [
        ("Paid visits carry a campaign name", "ok" if pct(k["paid_untagged"], k["paid"]) <= 10 else "warn" if pct(k["paid_untagged"], k["paid"]) <= 30 else "bad",
         f"{k['paid_untagged']:,} of {k['paid']:,} paid visits ({pct(k['paid_untagged'], k['paid'])}%) have no campaign name, so their results cannot be split by campaign.",
         "Add utm_campaign to every ad's URL (in Meta: URL parameters = utm_source=facebook&utm_medium=paid_social&utm_campaign={{campaign.name}})."),
        ("Ad clicks without any tag", "ok" if k["clickid_no_campaign"] == 0 else "warn",
         f"{k['clickid_no_campaign']:,} visits arrived from an ad click (click id present) but with no utm_campaign or Google campaign id.",
         "These ads need URL parameters. Without them the visit can only be counted as 'paid', not tied to a campaign."),
        ("Meta visits match a Meta campaign", "ok" if pct(k["meta_unmatched"], k["meta"]) <= 10 else "warn" if pct(k["meta_unmatched"], k["meta"]) <= 25 else "bad",
         f"{k['meta_unmatched']:,} of {k['meta']:,} Paid Meta visits ({pct(k['meta_unmatched'], k['meta'])}%) use a campaign name or id that is not a Meta campaign we can identify, so their spend and orders are not joined.",
         "Use the campaign id or the exact campaign name in utm_campaign. Duplicated ('- Copy') or renamed campaigns break the match."),
        ("One spelling per campaign", "ok" if not names else "warn",
         f"{len(names)} campaign name(s) appear with different spellings or capitalisation and are counted as separate campaigns." if names else "No campaign is split across spellings.",
         "Pick one lowercase naming pattern and keep it, for example brand_goal_audience_month."),
        ("No unfilled placeholders", "ok" if not macros else "bad",
         "No campaign name contains an unfilled placeholder." if not macros else f"{len(macros)} campaign name(s) contain an unfilled placeholder such as {{{{campaign.name}}}}, undefined or null.",
         "The ad URL has a template tag that the ad platform did not replace; check the URL parameters field."),
    ]
    return {"kpis": k, "paid_untagged_pct": pct(k["paid_untagged"], k["paid"]), "by_channel": by_channel, "unmatched_meta": unmatched, "spelling_variants": names,
            "placeholders": macros, "checks": [{"label": l, "status": s_, "detail": d, "fix": f} for l, s_, d, f in checks]}


@app.get("/api/campaigns")
def campaigns(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False, min_sessions: int = 1):
    w = "date_ist BETWEEN ? AND ?" + ("" if include_excluded else " AND NOT is_excluded")
    rows = q(f"""SELECT channel, source, medium, campaign, sum(sessions) sessions, sum(visitors) visitors, sum(engaged_sessions) engaged,
        sum(quiz_done) quiz_done, sum(carts) carts, sum(checkouts) checkouts, sum(orders) orders, sum(revenue) revenue,
        sum(ft_orders) ft_orders, sum(ft_revenue) ft_revenue, sum(lnd_orders) lnd_orders, sum(lnd_revenue) lnd_revenue,
        min(date_ist) first_day, max(date_ist) last_day
        FROM campaign_performance WHERE {w} GROUP BY 1,2,3,4 HAVING sum(sessions) >= ? ORDER BY greatest(sum(orders), sum(ft_orders), sum(lnd_orders)) DESC, carts DESC, sessions DESC""",
             [date_from or "2000-01-01", date_to or "2999-12-31", min_sessions])
    tot_s = sum(r["sessions"] for r in rows); tot_c = sum(r["carts"] for r in rows)
    base_cart = ratio(tot_c, tot_s)
    for r in rows:
        r.update(engaged_rate=ratio(r["engaged"], r["sessions"]), quiz_rate=ratio(r["quiz_done"], r["sessions"]),
                 cart_rate=ratio(r["carts"], r["sessions"]), checkout_rate=ratio(r["checkouts"], r["sessions"]),
                 order_cvr=ratio(r["orders"], r["sessions"]), rev_per_session=round(r["revenue"] / r["sessions"], 2) if r["sessions"] else 0)
        r["best_orders"] = max(r["orders"], r["ft_orders"], r["lnd_orders"])
        r["best_revenue"] = max(r["revenue"], r["ft_revenue"], r["lnd_revenue"])
        if r["best_orders"] >= 2 and r["cart_rate"] >= base_cart:
            r["verdict"] = "Winning"
        elif r["best_orders"] > 0:
            r["verdict"] = "Converting"
        elif r["sessions"] >= 30 and r["cart_rate"] >= base_cart:
            r["verdict"] = "Promising"
        elif r["sessions"] >= 100 and r["carts"] == 0:
            r["verdict"] = "No carts - review"
        else:
            r["verdict"] = "Too early"
    return {"rows": rows, "baseline_cart_rate": base_cart}

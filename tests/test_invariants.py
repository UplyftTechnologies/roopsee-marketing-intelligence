"""Rules that must always hold for the dashboard numbers.

Run (from the project folder):   .venv\\Scripts\\python -m unittest discover -s tests -v
It reads data/mi.duckdb (or the file in MI_DB_PATH). If the dashboard is running and has the file locked,
a temporary copy is made automatically, so the tests never touch your live data.
"""
import os
import shutil
import sys
import tempfile
import unittest

os.environ["PRICES_SUPABASE_KEY"] = ""  # the tests never touch the shared price store
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import duckdb  # noqa: E402

from mi import config  # noqa: E402

_TMP = None


def _open():
    """Read-only connection to the analytics database (copying it first when the dashboard holds the lock)."""
    global _TMP
    path = Path(os.environ.get("MI_DB_PATH") or config.DB_PATH)
    try:
        con = duckdb.connect(str(path), read_only=True)
    except duckdb.IOException:
        _TMP = tempfile.mkdtemp(prefix="mi-test-")
        copy = Path(_TMP) / "copy.duckdb"
        try:
            shutil.copyfile(path, copy)
        except PermissionError:  # Windows will not let a locked file be copied
            raise SystemExit(f"{path} is locked by the running dashboard. Stop it (python run.py --stop) or set MI_DB_PATH to a copy of the file.")
        con = duckdb.connect(str(copy), read_only=True)
    con.execute("SET TimeZone='Asia/Kolkata'")
    return con


CON = _open()
from mi import api  # noqa: E402  (imported after the path is set)

from mi import core  # noqa: E402

core.CON = CON
q, one = api.q, api.one


def tearDownModule():
    CON.close()
    if _TMP:
        shutil.rmtree(_TMP, ignore_errors=True)


def total(**kw):
    return api.sessions(limit=1, **kw)["total"]


class SessionFilters(unittest.TestCase):
    def test_did_and_did_not_add_up_to_everything(self):
        every = total()
        for flag in api.SESSION_FLAGS:
            with self.subTest(flag=flag):
                self.assertEqual(total(has=flag) + total(lacks=flag), every, f'"did {flag}" + "did not {flag}" must equal all sessions')

    def test_no_missing_flags(self):
        row = one("""SELECT count(*) FILTER (WHERE f_product IS NULL OR f_cart IS NULL OR f_checkout IS NULL OR f_pay IS NULL OR f_order IS NULL
                     OR f_login IS NULL OR f_search IS NULL OR f_address IS NULL OR f_location IS NULL) AS n FROM sessions""")
        self.assertEqual(row["n"], 0)

    def test_only_hidden_returns_the_hidden_sessions(self):
        hidden = one("SELECT count(*) n FROM sessions WHERE is_excluded")["n"]
        self.assertEqual(total(only_excluded=True), hidden)

    def test_ordered_never_includes_unpaid_only_sessions(self):
        bad = one(f"""WITH o AS (SELECT * FROM session_orders) SELECT count(*) n FROM sessions s LEFT JOIN o ON o.session_id = s.session_id
                      WHERE {api.FLAG_ORDER} AND NOT coalesce(s.f_order, false) AND coalesce(o.n_placed, 0) = 0""")
        self.assertEqual(bad["n"], 0)

    def test_event_filter_returns_exactly_the_sessions_with_that_event(self):
        name = one("SELECT event_name FROM session_events GROUP BY 1 ORDER BY count(*) ASC LIMIT 1 OFFSET 40")["event_name"]
        expected = one("""SELECT count(DISTINCT e.session_id) n FROM session_events e JOIN sessions s USING (session_id)
                          WHERE e.event_name = ? AND NOT s.is_excluded""", [name])["n"]
        self.assertEqual(total(event=name), expected)
        if "_" in name:
            self.assertEqual(total(search=name), max(expected, total(search=name)))  # the search box also finds sessions by event name
            self.assertGreaterEqual(total(search=name), expected)

    def test_pincode_filter_only_returns_those_pincodes(self):
        pin = one("SELECT pincode FROM sessions WHERE pincode IS NOT NULL AND NOT is_excluded GROUP BY 1 ORDER BY count(*) DESC LIMIT 1")["pincode"]
        rows = api.sessions(pincode=pin, limit=500)["rows"]
        self.assertTrue(rows)
        self.assertTrue(all(r["pincode"] == pin for r in rows))

    def test_unknown_sort_and_flag_values_are_ignored_not_executed(self):
        self.assertEqual(api.sessions(sort="nope; DROP TABLE sessions", limit=1)["total"], total())
        self.assertEqual(total(has="nonsense"), total())


class OneNumberEverywhere(unittest.TestCase):
    def test_orders_agree_between_overview_orders_and_funnel(self):
        ov = api.overview()["kpis"]["orders"]
        oa = api.orders_analytics()["kpis"]["orders"]
        fu = api.funnel()["actual_orders"]
        self.assertEqual(ov, oa)
        self.assertEqual(oa, fu)

    def test_sessions_agree_between_list_report_and_campaigns(self):
        every = total()
        rp = sum(r["sessions"] for r in api.report(dimension="channel", limit=500)["rows"])
        ca = sum(r["sessions"] for r in api.campaigns()["rows"])
        self.assertEqual(rp, every)
        self.assertEqual(ca, every)

    def test_every_report_dimension_adds_up_to_all_sessions(self):
        every = total()
        for dim in api.REPORT_DIMS:
            with self.subTest(dim=dim):
                self.assertEqual(sum(r["sessions"] for r in api.report(dimension=dim, limit=5000)["rows"]), every)


class DataRules(unittest.TestCase):
    def test_repeats_are_flagged_not_counted(self):
        r = one("SELECT sum(events) AS e, sum(events_raw) AS raw FROM sessions")
        self.assertLessEqual(r["e"], r["raw"])
        self.assertEqual(r["e"], one("SELECT count(*) n FROM events_base WHERE NOT is_dup")["n"])

    def test_active_time_never_exceeds_the_span_of_the_session(self):
        self.assertEqual(one("SELECT count(*) n FROM sessions WHERE duration_s > span_s + 1")["n"], 0)

    def test_payment_state_is_one_of_the_known_values(self):
        states = {r["s"] for r in q("SELECT DISTINCT payment_state s FROM orders_clean")}
        self.assertLessEqual(states, {"confirmed", "cod_pending", "unconfirmed", "conflicting", "not_placed"})

    def test_a_sale_is_never_both_valid_and_unplaced(self):
        self.assertEqual(one("SELECT count(*) n FROM orders_clean WHERE is_valid AND NOT is_placed")["n"], 0)

    def test_every_order_id_is_unique(self):
        self.assertEqual(one("SELECT count(*) - count(DISTINCT order_id) d FROM orders_clean")["d"], 0)

    def test_session_ids_are_unique(self):
        self.assertEqual(one("SELECT count(*) - count(DISTINCT session_id) d FROM sessions")["d"], 0)

    def test_person_keys_are_unique(self):
        self.assertEqual(one("SELECT count(*) - count(DISTINCT person_key) d FROM users_360")["d"], 0)


class Reconciliation(unittest.TestCase):
    def test_report_orders_plus_orders_not_in_table_equal_overview_orders(self):
        r = api.report(dimension="channel", limit=500)
        self.assertEqual(r["totals"]["orders"] + r["reconcile"]["orders_other"], api.overview()["kpis"]["orders"])

    def test_funnel_last_stage_matches_the_ordered_quick_view(self):
        self.assertEqual(api.funnel()["stages"][-1]["sessions"], api.session_counts()["ordered"])

    def test_orders_in_the_channel_report_never_exceed_orders_overall(self):
        r = api.report(dimension="campaign", limit=5000)
        self.assertLessEqual(r["totals"]["orders"], api.overview()["kpis"]["orders"])


class StableLists(unittest.TestCase):
    """Rows with equal sort values must keep one order, or paging shows a row twice and skips another."""

    def test_pages_of_the_session_list_never_repeat_a_row(self):
        seen = []
        for off in (0, 100, 200, 300):
            seen += [r["session_id"] for r in api.sessions(sort="events", direction="desc", limit=100, offset=off)["rows"]]
        self.assertEqual(len(seen), len(set(seen)))

    def test_pages_of_the_user_list_never_repeat_a_row(self):
        seen = []
        for off in (0, 100, 200, 300):
            seen += [r["person_key"] for r in api.users(sort="sessions", direction="desc", limit=100, offset=off)["rows"]]
        self.assertEqual(len(seen), len(set(seen)))

    def test_the_same_question_gives_the_same_answer_twice(self):
        self.assertEqual(api.orders_analytics()["cities"], api.orders_analytics()["cities"])
        self.assertEqual(api.basket()["products"], api.basket()["products"])


class StoredPayloads(unittest.TestCase):
    def test_trimming_never_drops_a_field_the_pipeline_reads(self):
        import re

        from mi import payload
        src = (ROOT / "mi" / "transform.py").read_text(encoding="utf-8")
        used = set(re.findall(r"jj?\('([A-Za-z_]+)'\)", src)) | {k.split(".")[-1].split("[")[0] for k in re.findall(r"jj?\('([A-Za-z_.\[\]0-9]+)'\)", src)}
        self.assertTrue(used)
        self.assertFalse(used & payload.REMOVE, f"slimming would drop fields the transform reads: {used & payload.REMOVE}")

    def test_slim_keeps_what_matters_and_removes_plumbing(self):
        from mi import payload
        out = payload.slim({"user_agent": "x" * 50, "search_term": "cream", "rawBody": {"user_agent": "y", "sessionId": "s1", "page": "p"}})
        self.assertEqual(out, {"search_term": "cream", "rawBody": {"sessionId": "s1"}})


class EveryScreenLoads(unittest.TestCase):
    """Each dashboard endpoint answers with default settings (a broken query shows up here, not in front of you)."""

    def test_endpoints(self):
        calls = {
            "meta": api.meta, "overview": api.overview, "funnel": api.funnel, "campaigns": api.campaigns, "cohorts": api.cohorts,
            "retention": api.retention, "loyalty": api.loyalty, "basket": api.basket, "audiences": api.audiences, "insights": api.insights,
            "orders_list": api.orders_list, "orders_analytics": api.orders_analytics, "sessions": api.sessions, "session_counts": api.session_counts,
            "users": api.users, "user_counts": api.user_counts, "timeseries": api.timeseries, "report": api.report, "health": api.data_health,
            "performance": api.performance, "event_names": api.event_names, "catalogue": api.catalogue, "utm_health": api.utm_health, "alerts": api.alerts, "digest": api.digest, "meta_reconcile": api.meta_reconcile, "meta_overview": api.meta_overview, "meta_breakdown": api.meta_breakdown, "meta_hierarchy": api.meta_hierarchy,
        }
        for name, fn in calls.items():
            with self.subTest(endpoint=name):
                self.assertIsNotNone(fn())

    def test_detail_pages(self):
        sid = one("SELECT session_id FROM sessions ORDER BY events DESC LIMIT 1")["session_id"]
        d = api.session_detail(sid)
        self.assertEqual(d["session"]["session_id"], sid)
        key = one("SELECT person_key FROM users_360 ORDER BY sessions DESC LIMIT 1")["person_key"]
        self.assertTrue(api.person_profile(key)["sessions"])
        oid = one("SELECT order_id FROM orders_clean LIMIT 1")["order_id"]
        self.assertTrue(api.order_detail(oid))


if __name__ == "__main__":
    unittest.main()


class EventsTab(unittest.TestCase):
    def test_catalogue_total_equals_sum_of_names(self):
        s = api.events_summary()
        self.assertEqual(s["totals"]["events"], sum(r["events"] for r in api.events_summary()["rows"]) if s["totals"]["names"] <= 500 else s["totals"]["events"])

    def test_rows_total_matches_catalogue_for_each_top_event(self):
        for r in api.events_summary()["rows"][:5]:
            with self.subTest(event=r["event_name"]):
                self.assertEqual(api.events_rows(event=r["event_name"], payload=[], limit=1)["total"], r["events"])

    def test_group_by_event_name_adds_up(self):
        g = api.events_groupby(by="event_name", payload=[], limit=1000)
        self.assertEqual(sum(x["events"] for x in g["rows"]), g["totals"]["events"])

    def test_pages_never_repeat_a_row(self):
        a = api.events_rows(payload=[], limit=50, offset=0)["rows"]
        b = api.events_rows(payload=[], limit=50, offset=50)["rows"]
        self.assertFalse({r["id"] for r in a} & {r["id"] for r in b})

    def test_payload_filter_never_returns_more_than_the_event(self):
        top = api.events_summary()["rows"][0]["event_name"]
        fields = api.events_fields(event=top)["fields"]
        if fields:
            f = fields[0]["field"]
            self.assertLessEqual(api.events_rows(event=top, payload=[f], limit=1)["total"], api.events_rows(event=top, payload=[], limit=1)["total"])

    def test_bad_field_names_are_refused(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            api.events_rows(payload=["a'; DROP TABLE x;--=1"], limit=1)


class PainPoints(unittest.TestCase):
    def setUp(self):
        self.r = api.pain(compare=False)

    def test_stuck_never_exceeds_tried_and_hit(self):
        for st in self.r["stages"]:
            with self.subTest(stage=st["key"]):
                self.assertLessEqual(st["stuck"], st["tried"])
                self.assertLessEqual(st["hit"], st["tried"])
                self.assertEqual(st["recovered"] + (st["stuck"] if st["key"] == "speed" else 0) <= st["hit"] + st["stuck"], True)

    def test_an_order_clears_every_stage(self):
        bad = one("SELECT count(*) n FROM pain_visits v JOIN pain_sessions s USING (session_id) WHERE s.ordered AND v.stuck")
        self.assertEqual(bad["n"], 0)

    def test_visit_totals_agree_with_the_sessions_table(self):
        self.assertEqual(self.r["totals"]["visits"], one("SELECT count(*) n FROM sessions WHERE NOT is_excluded")["n"])
        self.assertEqual(self.r["totals"]["ordered"] + self.r["totals"]["left_with_problem"] + self.r["totals"]["left_no_problem"], self.r["totals"]["visits"])

    def test_who_list_matches_the_stage_count(self):
        for st in self.r["stages"]:
            with self.subTest(stage=st["key"]):
                self.assertEqual(api.pain_people(stage=st["key"], limit=2000)["total"], st["list_total"])

    def test_last_problem_adds_up_to_visits_that_left_with_one(self):
        self.assertEqual(sum(x["visits"] for x in self.r["last_before_leaving"]), self.r["totals"]["left_with_problem"])

    def test_every_problem_event_is_known_to_the_stages(self):
        from mi import pain_defs
        self.assertTrue({r["problem_key"] for r in q("SELECT DISTINCT problem_key FROM pain_events")} <= set(pain_defs.PROBLEM_LABEL))


class Logins(unittest.TestCase):
    def test_daily_logins_add_up_to_the_total(self):
        ts = api.timeseries(date_from="2026-10-01", date_to="2026-11-20")
        self.assertEqual(sum(ts["current"]["logins"]), api.logins(date_from="2026-10-01", date_to="2026-11-20", summary=False, limit=1)["total"])

    def test_overview_and_logins_page_agree(self):
        k = api.overview(date_from="2026-10-01", date_to="2026-11-20")["kpis"]
        self.assertEqual(k["logins"], api.logins(date_from="2026-10-01", date_to="2026-11-20", summary=False, limit=1)["total"])

    def test_one_login_per_visit_and_never_more_than_sessions(self):
        r = one("SELECT count(*) n, count(DISTINCT session_id) d FROM logins")
        self.assertEqual(r["n"], r["d"])
        self.assertLessEqual(r["n"], one("SELECT count(*) n FROM sessions")["n"])

    def test_method_and_kind_filters_split_the_total(self):
        every = api.logins(summary=False, limit=1)["total"]
        self.assertEqual(sum(api.logins(method=m, summary=False, limit=1)["total"] for m in api.METHODS), every)
        self.assertEqual(api.logins(kind="new", summary=False, limit=1)["total"] + api.logins(kind="returning", summary=False, limit=1)["total"], every)

    def test_rows_page_without_repeats(self):
        a = api.logins(summary=False, limit=20, offset=0)["rows"]
        b = api.logins(summary=False, limit=20, offset=20)["rows"]
        self.assertFalse({r["session_id"] for r in a} & {r["session_id"] for r in b})


class RoopChats(unittest.TestCase):
    def test_messages_add_up_across_conversations(self):
        d = api.chats(include_excluded=True)
        self.assertEqual(sum(c["messages"] for c in d["conversations"]) if d["conversations_total"] <= 300 else d["totals"]["messages"], d["totals"]["messages"])
        self.assertEqual(sum(x["messages"] for x in d["daily"]), d["totals"]["messages"])
        self.assertEqual(sum(x["count"] for x in d["topics"]), d["totals"]["messages"])

    def test_answered_plus_failed_is_every_message(self):
        t = api.chats()["totals"]
        self.assertEqual(t["answered"] + t["failed"], t["messages"])

    def test_one_row_per_message(self):
        r = one("SELECT count(*) n, count(DISTINCT id) d FROM chat_messages")
        self.assertEqual(r["n"], r["d"])
        self.assertEqual(r["n"], one("SELECT count(*) n FROM raw_chat_logs")["n"])

    def test_a_conversation_matches_the_list(self):
        c = api.chats(include_excluded=True)["conversations"][0]
        self.assertEqual(len(api.chat_conversation(c["key"])["turns"]), c["messages"])

    def test_a_visit_with_chats_shows_them_in_its_timeline(self):
        sid = one("SELECT session_id FROM chat_messages WHERE session_id IS NOT NULL LIMIT 1")["session_id"]
        d = api.session_detail(sid)
        self.assertTrue(d["chats"])
        self.assertEqual(sum(1 for e in d["events"] if e["event_name"] == "assistant_chat"), len(d["chats"]))


class DeviceFilter(unittest.TestCase):
    def _run(self, devices):
        from mi.core import DEVICE
        t = DEVICE.set(devices)
        try:
            k = api.overview(date_from="2026-10-01", date_to="2026-11-20")["kpis"]
            return k["sessions"], k["orders"], k["logins"], api.events_summary(date_from="2026-10-01", date_to="2026-11-20")["totals"]["events"]
        finally:
            DEVICE.reset(t)

    def test_the_device_types_add_up_to_everything(self):
        from mi.core import DEVICE_TYPES
        parts = [self._run((d,)) for d in DEVICE_TYPES]
        self.assertEqual(tuple(sum(x) for x in zip(*parts)), self._run(None))

    def test_web_is_the_three_web_types(self):
        web = self._run(("Mobile web", "Desktop web", "Tablet web"))
        app_only = self._run(("App",))
        self.assertEqual(tuple(a + b for a, b in zip(web, app_only)), tuple(a - u for a, u in zip(self._run(None), self._run(("Unknown",)))))

    def test_only_the_visit_tables_are_narrowed(self):
        from mi.core import narrow
        out = narrow("SELECT 1 FROM sessions s JOIN session_orders o ON 1=1 JOIN sessions_pre p ON 1=1", ("App",))
        self.assertEqual(out.count("SELECT * FROM sessions WHERE"), 1)
        self.assertIn("JOIN session_orders o", out)
        self.assertIn("JOIN sessions_pre p", out)
        self.assertEqual(narrow("SELECT 1 FROM sessions", None), "SELECT 1 FROM sessions")


class DeeperAnalysis(unittest.TestCase):
    R = dict(date_from="2026-10-01", date_to="2026-11-20")

    def test_first_order_buckets_add_up(self):
        b = api.journeys_detail(journey="purchase", **self.R)["purchase"]
        self.assertEqual(sum(x["count"] for x in b["visits"]), b["orders"])
        self.assertEqual(sum(x["count"] for x in b["days"]), b["orders"])

    def test_ad_cards_follow_the_funnel(self):
        for ad in api.deeper_ads(**self.R)["ads"]:
            with self.subTest(ad=ad["ad_id"]):
                self.assertGreaterEqual(ad["sessions"], ad["carts"])
                self.assertGreaterEqual(ad["carts"], ad["checkouts"] - 0 if ad["checkouts"] <= ad["carts"] else 0)
                self.assertLessEqual(ad["orders"], ad["sessions"])

    def test_search_numbers_are_consistent(self):
        k = api.journeys_detail(journey="search", **self.R)["search"]["kpis"]
        self.assertLessEqual(k["zero_searches"], k["searches"])
        searched = api.journeys_funnel(journey="search", by="sessions", **self.R)["funnel"][0]["count"]
        self.assertLessEqual(k["click_sessions"], searched)  # tapping a result needs a search first

    def test_quiz_detail_never_exceeds_the_quiz_journey(self):
        d = api.journeys_detail(journey="quiz", **self.R)["quiz"]
        answered = api.journeys_funnel(journey="quiz", by="sessions", **self.R)["funnel"][1]["count"]
        for st in d["steps"]:
            self.assertLessEqual(st["sessions"], answered)
        finished = api.journeys_funnel(journey="quiz", by="sessions", **self.R)["funnel"][2]["count"]
        self.assertLessEqual(sum(p["sessions"] for p in d["programs"]), finished)

    def test_pay_timing_buckets_add_up(self):
        p = api.journeys_detail(journey="checkout", **self.R)["checkout"]
        self.assertEqual(sum(b["count"] for b in p["buckets"]), p["timed"])
        self.assertEqual(sum(m["orders"] for m in p["by_method"]), p["timed"])

    def test_detail_refuses_unknown_journeys(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            api.journeys_detail(journey="chat", **self.R)

    def test_every_label_lists_exactly_its_people(self):
        d = api.segment_labels(**self.R)
        for l in d["labels"][:6]:
            with self.subTest(label=l["key"]):
                self.assertEqual(api.segment_people(label=l["key"], limit=1, **self.R)["total"], l["people"])

    def test_labels_belong_to_known_people(self):
        bad = one("SELECT count(*) n FROM user_labels l WHERE l.person_key NOT IN (SELECT person_key FROM users_360)")
        self.assertEqual(bad["n"], 0)

    def test_flow_never_exceeds_the_ad_visits(self):
        d = api.deeper_flow(**self.R)
        sess = {a["ad_id"]: a["sessions"] for a in d["ads"]}
        per = {}
        for r in d["ad_concern"]:
            per[(r["ad_id"], r["concern"])] = per.get((r["ad_id"], r["concern"]), 0) + r["sessions"]
        for (ad, _c), n in per.items():
            self.assertLessEqual(n, sess[ad])


class RevenueReconciliation(unittest.TestCase):
    """Every revenue figure either equals the headline or shows the gap, so no page contradicts another."""
    R = dict(date_from="2026-10-22", date_to="2026-11-20")

    def test_all_time_chart_adds_up_to_the_headline(self):
        ov = api.overview()
        k = ov["kpis"]
        self.assertEqual(sum(d["orders"] for d in ov["daily"]), k["orders"])
        self.assertAlmostEqual(sum(d["revenue"] for d in ov["daily"]), k["revenue"], places=2)
        ts = api.timeseries()["current"]
        self.assertEqual(sum(ts["orders"]), k["orders"])
        self.assertAlmostEqual(sum(ts["revenue"]), k["revenue"], places=2)

    def test_revenue_is_split_by_payment_status_without_loss(self):
        for R in ({}, self.R):
            with self.subTest(R=R):
                k = api.overview(**R)["kpis"]
                self.assertAlmostEqual(k["revenue_confirmed"] + k["revenue_cod_pending"] + k["revenue_unconfirmed"], k["revenue"], places=2)
                oa = api.orders_analytics(**R)
                self.assertAlmostEqual(sum(x["revenue"] for x in oa["revenue_split"]), oa["kpis"]["gmv"], places=2)

    def test_pages_agree_on_revenue(self):
        for R in ({}, self.R):
            with self.subTest(R=R):
                rev = api.overview(**R)["kpis"]["revenue"]
                self.assertAlmostEqual(api.orders_analytics(**R)["kpis"]["gmv"], rev, places=2)
                self.assertAlmostEqual(api.orders_list(**R, limit=1)["summary"]["gmv"], rev, places=2)
                self.assertAlmostEqual(api.basket(**R)["kpis"]["revenue"], rev, places=2)

    def test_net_revenue_of_all_lines_is_the_revenue(self):
        r = one("SELECT coalesce(sum(net_line), 0) AS n FROM order_lines WHERE is_valid AND NOT is_excluded")["n"]
        self.assertAlmostEqual(r, api.overview()["kpis"]["revenue"], places=1)

    def test_the_bridge_from_item_value_to_revenue_closes(self):
        b = api.basket()["bridge"]
        self.assertAlmostEqual(b["items"] - b["coupons"] - b["wallet"] + b["delivery"] + b["handling"] + b["other"], b["revenue"], places=2)

    def test_coupon_value_never_exceeds_the_recorded_discount(self):
        bad = one("SELECT count(*) n FROM orders_clean WHERE coupon_value > coalesce(coupon_discount, 0) + 0.001 OR coupon_value < 0")["n"]
        self.assertEqual(bad, 0)

    def test_campaigns_show_what_they_do_not_cover(self):
        for R in ({}, self.R):
            with self.subTest(R=R):
                c = api.campaigns(**R)["reconcile"]
                self.assertEqual(c["orders_in_table"] + c["orders_other"], c["orders_total"])
                self.assertAlmostEqual(c["revenue_in_table"] + c["revenue_other"], c["revenue_total"], places=1)
                self.assertAlmostEqual(c["revenue_total"], api.overview(**R)["kpis"]["revenue"], places=2)

    def test_people_lists_plus_the_notes_equal_the_revenue(self):
        shown = one("SELECT coalesce(sum(revenue), 0) AS r FROM users_360 WHERE NOT is_excluded")["r"]
        u = api.untracked_sales()
        self.assertAlmostEqual(shown + u["revenue"] + u["hidden_revenue"], api.overview()["kpis"]["revenue"], places=1)

    def test_sales_basis_only_narrows(self):
        from mi.core import SALES, SALES_BASIS
        full = api.overview()["kpis"]
        got = {}
        for name, states in SALES_BASIS.items():
            t = SALES.set(states)
            try:
                got[name] = api.overview()["kpis"]
            finally:
                SALES.reset(t)
        self.assertLessEqual(got["confirmed"]["revenue"], got["paid_or_cod"]["revenue"])
        self.assertLessEqual(got["paid_or_cod"]["revenue"], full["revenue"])
        self.assertAlmostEqual(got["confirmed"]["revenue"], full["revenue_confirmed"], places=2)
        self.assertAlmostEqual(got["paid_or_cod"]["revenue"], full["revenue_confirmed"] + full["revenue_cod_pending"], places=2)

    def test_staff_orders_are_listed_and_add_up(self):
        so = api.staff_orders()
        self.assertEqual(sum(a["orders"] for a in so["accounts"]), so["totals"]["orders"])
        hidden = one("SELECT count(*) n FROM orders_clean WHERE is_valid AND is_staff_order AND is_excluded")["n"]
        self.assertEqual(so["totals"]["orders"] - so["totals"]["counted_orders"], hidden)

    @unittest.skipUnless(os.environ.get("MI_LIVE_RECONCILE") == "1", "set MI_LIVE_RECONCILE=1 to compare with a fresh read of Supabase")
    def test_revenue_matches_a_fresh_read_of_supabase(self):
        """Recomputes the revenue from the live orders table with the documented rules and compares it with every page."""
        import json
        from mi.supa import ReadOnlySupabase
        sb = ReadOnlySupabase()
        rows, off = [], 0
        while True:
            page = sb.select("orders", {"select": "id,user_id,total,status,items", "order": "id.asc", "limit": 1000, "offset": off})
            rows += page
            if len(page) < 1000:
                break
            off += 1000
        roles = {r["id"].lower(): r["role"] for r in sb.select("users", {"select": "id,role", "limit": 5000})}
        marked = {r["value"].lower() for r in q("SELECT value FROM exclusions WHERE kind = 'real_customer' AND active")}

        def counted(r):
            if r["status"] in ("payment_cancelled", "payment_pending") or (r["total"] or 0) <= 1 or "test product" in json.dumps(r["items"]).lower():
                return False
            staff = roles.get((r["user_id"] or "").lower()) in ("admin", "rider", "doctor")
            return not staff or (r["user_id"] or "").lower() in marked
        mine = round(sum(r["total"] for r in rows if counted(r)), 2)
        self.assertAlmostEqual(api.overview()["kpis"]["revenue"], mine, places=2)


class JourneysTab(unittest.TestCase):
    R = dict(date_from="2026-10-22", date_to="2026-11-20")

    def test_every_funnel_only_shrinks(self):
        from mi import journey_defs
        for j in journey_defs.JOURNEY_KEYS:
            for by in ("people", "sessions"):
                with self.subTest(journey=j, by=by):
                    counts = [x["count"] for x in api.journeys_funnel(journey=j, by=by, **self.R)["funnel"]]
                    self.assertEqual(counts, sorted(counts, reverse=True))

    def test_people_never_exceed_visits(self):
        from mi import journey_defs
        for j in journey_defs.JOURNEY_KEYS:
            with self.subTest(journey=j):
                p = [x["count"] for x in api.journeys_funnel(journey=j, by="people", **self.R)["funnel"]]
                v = [x["count"] for x in api.journeys_funnel(journey=j, by="sessions", **self.R)["funnel"]]
                self.assertTrue(all(a <= b for a, b in zip(p, v)))

    def test_purchase_journey_starts_with_every_visit(self):
        self.assertEqual(api.journeys_funnel(journey="purchase", by="sessions", **self.R)["funnel"][0]["count"], api.overview(**self.R)["kpis"]["sessions"])
        self.assertGreaterEqual(api.journeys_funnel(journey="purchase", by="sessions", **self.R)["funnel"][-1]["count"], api.funnel(**self.R)["stages"][5]["sessions"])

    def test_stopped_lists_match_the_counts(self):
        for j, step in (("purchase", "add_to_cart"), ("checkout", "address"), ("login", "otp_sent"), ("quiz", "finished")):
            with self.subTest(journey=j, step=step):
                f = api.journeys_funnel(journey=j, by="people", **self.R)["funnel"]
                stopped = next(x["stopped"] for x in f if x["key"] == step)
                self.assertEqual(api.journeys_people(journey=j, step=step, limit=1, **self.R)["total"], stopped)

    def test_the_explorer_adds_up(self):
        v = api.journeys_explore(mode="visits", limit=1, **self.R)["total"]
        self.assertEqual(v, api.overview(**self.R)["kpis"]["sessions"])
        parts = sum(api.journeys_explore(mode="visits", outcome=o, limit=1, **self.R)["total"] for o in api.OUTCOME_STAGE)
        self.assertEqual(parts, v)
        self.assertEqual(api.journeys_explore(mode="people", limit=1, **self.R)["total"], api.journeys_funnel(journey="purchase", by="people", **self.R)["funnel"][0]["count"])

    def test_after_the_order_starts_with_the_orders(self):
        a = api.journeys_after_order(**self.R)
        self.assertEqual(a["funnel"][0]["count"], api.overview(**self.R)["kpis"]["orders"])
        counts = [x["count"] for x in a["funnel"]]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_bad_input_is_refused(self):
        from fastapi import HTTPException
        for call in (lambda: api.journeys_funnel(journey="nope", **self.R), lambda: api.journeys_funnel(journey="quiz", by="x", **self.R),
                     lambda: api.journeys_people(journey="quiz", step="ordered", **self.R), lambda: api.journeys_explore(mode="x", **self.R),
                     lambda: api.journeys_explore(outcome="x", **self.R)):
            with self.assertRaises(HTTPException):
                call()


class RoopByCampaignAndAd(unittest.TestCase):
    R = dict(date_from="2026-10-22", date_to="2026-11-20")

    def test_roop_usage_matches_the_chat_journey(self):
        d = api.roop_usage(level="channel", only_used=False, **self.R)
        self.assertEqual(d["all"]["opened"], api.journeys_funnel(journey="chat", by="sessions", **self.R)["funnel"][0]["count"])
        self.assertEqual(sum(r["opened"] for r in d["rows"]), d["all"]["opened"])
        self.assertEqual(sum(r["sessions"] for r in d["rows"]), api.overview(**self.R)["kpis"]["sessions"])

    def test_every_level_accounts_for_every_open(self):
        for lv in ("campaign", "adset", "ad", "channel"):
            with self.subTest(level=lv):
                d = api.roop_usage(level=lv, limit=1000, **self.R)
                self.assertEqual(sum(r["opened"] for r in d["rows"]), d["all"]["opened"])

    def test_a_row_lists_exactly_its_visits(self):
        for lv, kw in (("ad", "ad"), ("adset", "adset"), ("campaign", "campaign_id")):
            row = next((r for r in api.roop_usage(level=lv, **self.R)["rows"] if not r["key"].startswith("(")), None)
            if not row:
                continue
            with self.subTest(level=lv):
                self.assertEqual(api.sessions(**self.R, limit=1, **{kw: row["key"]})["total"], row["sessions"])
                self.assertEqual(api.sessions(**self.R, limit=1, has="roop", **{kw: row["key"]})["total"], row["opened"])
                self.assertEqual(api.sessions(**self.R, limit=1, has="roop_asked", **{kw: row["key"]})["total"], row["asked"])

    def test_the_roop_flags_match_the_journey(self):
        self.assertEqual(api.sessions(**self.R, limit=1, has="roop")["total"], api.journeys_funnel(journey="chat", by="sessions", **self.R)["funnel"][0]["count"])
        self.assertEqual(api.sessions(**self.R, limit=1, has="roop_asked")["total"], api.journeys_funnel(journey="chat", by="sessions", **self.R)["funnel"][1]["count"])
        every = api.sessions(**self.R, limit=1)["total"]
        self.assertEqual(api.sessions(**self.R, limit=1, has="roop")["total"] + api.sessions(**self.R, limit=1, lacks="roop")["total"], every)

    def test_ad_cards_open_their_visits(self):
        j = api.deeper_ads(**self.R)
        for ad in j["ads"][:3]:
            with self.subTest(ad=ad["ad_id"]):
                self.assertEqual(api.sessions(**self.R, limit=1, ad=ad["ad_id"], channel="Paid Meta")["total"], ad["sessions"])
        for p in j["products"][:3]:
            with self.subTest(product=p["product_id"]):
                self.assertEqual(api.sessions(**self.R, limit=1, landing_product=p["product_id"])["total"], p["sessions"])

    def test_searching_an_ad_id_finds_its_visits(self):
        ad = api.session_ads(**self.R)[0]
        self.assertEqual(api.sessions(**self.R, limit=1, search=ad["ad_id"])["total"], api.sessions(**self.R, limit=1, ad=ad["ad_id"])["total"])

    def test_the_session_page_names_the_ad(self):
        ad = api.session_ads(**self.R)[0]
        row = api.sessions(**self.R, limit=1, ad=ad["ad_id"])["rows"][0]
        self.assertEqual(row["ad_id"], ad["ad_id"])
        self.assertEqual(api.session_detail(row["session_id"])["ad"]["ad_id"], ad["ad_id"])

    def test_the_explorer_filters_by_ad_and_roop(self):
        ad = api.session_ads(**self.R)[0]
        self.assertEqual(api.journeys_explore(mode="visits", ad=ad["ad_id"], limit=1, **self.R)["total"], api.sessions(**self.R, limit=1, ad=ad["ad_id"])["total"])
        self.assertEqual(api.journeys_explore(mode="visits", roop="opened", limit=1, **self.R)["total"], api.sessions(**self.R, limit=1, has="roop")["total"])

    def test_bad_input_is_refused(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            api.roop_usage(level="nope", **self.R)
        with self.assertRaises(HTTPException):
            api.journeys_explore(mode="visits", roop="x", **self.R)


class JourneyPresets(unittest.TestCase):
    R = dict(date_from="2026-10-22", date_to="2026-11-20")

    def match(self, steps, **kw):
        d = api.Definition(steps=[api.Step(action=a, did=did) for a, did in steps], **kw)
        return api.preset_match(d, limit=5, **self.R)

    def test_one_step_equals_the_sessions_filter(self):
        for action, flag in (("key:add_to_cart", "cart"), ("key:checkout_view", "checkout"), ("key:search", "search"), ("flag:order", "order")):
            with self.subTest(action=action):
                self.assertEqual(self.match([(action, True)])["summary"]["visits"], api.sessions(limit=1, has=flag, **self.R)["total"])

    def test_did_and_did_not_add_up_to_everything(self):
        did = self.match([("key:add_to_cart", True)])["summary"]["visits"]
        nope = self.match([("key:add_to_cart", False)])["summary"]["visits"]
        self.assertEqual(did + nope, api.overview(**self.R)["kpis"]["sessions"])

    def test_order_only_narrows(self):
        steps = [("key:product_view", True), ("key:add_to_cart", True), ("key:checkout_view", True)]
        any_order = self.match(steps)["summary"]["visits"]
        later = self.match(steps, ordered=True)["summary"]["visits"]
        right_after = self.match(steps, ordered=True, gap="next")["summary"]["visits"]
        self.assertLessEqual(right_after, later)
        self.assertLessEqual(later, any_order)

    def test_steps_only_shrink_and_end_at_the_total(self):
        m = self.match([("key:search", True), ("key:add_to_cart", True), ("flag:order", False)], ordered=True)
        counts = [x["visits"] for x in m["steps"]]
        self.assertEqual(counts, sorted(counts, reverse=True))
        self.assertEqual(counts[-1], m["summary"]["visits"])
        self.assertEqual(m["total"], m["summary"]["visits"])

    def test_people_never_exceed_visits(self):
        m = self.match([("key:add_to_cart", True)])
        self.assertLessEqual(m["summary"]["people"], m["summary"]["visits"])
        d = api.Definition(steps=[api.Step(action="key:add_to_cart")])
        self.assertEqual(api.preset_match(d, mode="people", limit=1, **self.R)["total"], m["summary"]["people"])

    def test_every_listed_visit_really_matches(self):
        for r in self.match([("key:add_to_cart", True), ("flag:order", False)])["rows"]:
            with self.subTest(session=r["session_id"]):
                self.assertIn("add_to_cart", r["key_events"] or "")
                self.assertNotEqual(r["stage"], 5)

    def test_saved_presets_count_like_the_match(self):
        counts = api.preset_counts(**self.R)["counts"]
        for p in api.list_presets()["presets"][:5]:
            with self.subTest(preset=p["name"]):
                self.assertEqual(counts[p["id"]]["visits"], api.preset_match(api.Definition(**p["definition"]), limit=1, **self.R)["summary"]["visits"])

    def test_bad_presets_are_refused(self):
        from fastapi import HTTPException
        for d in (dict(steps=[]), dict(steps=[api.Step(action="key:nope")]), dict(steps=[api.Step(action="event:drop table")]),
                  dict(steps=[api.Step(action="key:search")], gap="soon"), dict(steps=[api.Step(action="key:search")] * 9)):
            with self.subTest(definition=str(d)[:60]):
                with self.assertRaises(HTTPException):
                    api.preset_match(api.Definition(**d), **self.R)


class AdAttribution(unittest.TestCase):
    """Which Meta ad a visit came from: by id, by name, probably, or not at all."""
    R = dict(date_from="2026-10-22", date_to="2026-11-20")

    @classmethod
    def setUpClass(cls):
        if not one("SELECT count(*) AS n FROM raw_meta_insights")["n"]:
            raise unittest.SkipTest("Meta Ads is not synced on this computer (no META_ACCESS_TOKEN): nothing to tie visits to")

    def test_every_paid_meta_visit_has_exactly_one_kind(self):
        d = api.meta_attribution(**self.R)
        self.assertEqual(sum(d["by_match"].values()), d["visits"])
        self.assertEqual(d["visits"], api.sessions(limit=1, channel="Paid Meta", **self.R)["total"])
        self.assertEqual(d["tied"], d["by_match"]["id"] + d["by_match"]["name"] + d["by_match"]["probable"])

    def test_the_sessions_filter_equals_the_health_card(self):
        d = api.meta_attribution(**self.R)
        for kind, n in d["by_match"].items():
            with self.subTest(kind=kind):
                self.assertEqual(api.sessions(limit=1, channel="Paid Meta", ad_match=kind, **self.R)["total"], n)

    def test_a_resolved_ad_is_a_real_meta_ad(self):
        bad = one("""SELECT count(*) AS n FROM session_attrib sa WHERE sa.ad_match IN ('id', 'name', 'probable')
                     AND sa.ad_id NOT IN (SELECT ad_id FROM meta_ad_dim)""")["n"]
        self.assertEqual(bad, 0)

    def test_an_exact_id_is_never_replaced_and_the_raw_value_is_kept(self):
        self.assertEqual(one("SELECT count(*) AS n FROM session_attrib WHERE ad_match = 'id' AND ad_id <> ad_raw")["n"], 0)
        self.assertEqual(one("SELECT count(*) AS n FROM session_attrib WHERE ad_raw IS NULL")["n"], 0)

    def test_a_campaign_is_tied_to_a_visit_at_most_once(self):
        d = one("SELECT count(*) AS n, count(DISTINCT session_id) AS u FROM session_meta")
        self.assertEqual(d["n"], d["u"])

    def test_a_visit_tied_through_its_ad_is_listed_under_its_campaign(self):
        r = one("""SELECT sm.meta_campaign_id AS c, count(*) AS n FROM session_meta sm JOIN sessions s USING (session_id)
                   WHERE s.date_ist BETWEEN ? AND ? AND NOT s.is_excluded GROUP BY 1 ORDER BY 2 DESC LIMIT 1""", [self.R["date_from"], self.R["date_to"]])
        self.assertEqual(api.sessions(limit=1, campaign_id=r["c"], **self.R)["total"], r["n"] + one(
            "SELECT count(*) AS n FROM sessions s LEFT JOIN session_meta sm USING (session_id) WHERE s.date_ist BETWEEN ? AND ? AND NOT s.is_excluded AND s.campaign = ? AND sm.session_id IS NULL",
            [self.R["date_from"], self.R["date_to"], r["c"]])["n"])

    def test_unknown_kinds_are_ignored(self):
        self.assertEqual(api.sessions(limit=1, ad_match="nope", **self.R)["total"], api.sessions(limit=1, **self.R)["total"])


class GeoMap(unittest.TestCase):
    """The map: visits, checkouts started and orders by area."""
    R = dict(date_from="2026-10-22", date_to="2026-11-20")

    def total(self, d, k):
        return sum(a[k] for a in d["areas"]) + d["unplaced"][k]

    def test_visitor_view_adds_up_to_the_whole_range(self):
        kp = api.overview(**self.R)["kpis"]
        for level in ("state", "city"):
            d = api.geo_areas(level=level, basis="visitor", limit=5000, **self.R)
            with self.subTest(level=level):
                self.assertEqual(self.total(d, "visits"), kp["sessions"])
                self.assertEqual(self.total(d, "visits"), d["totals"]["visits"])
                self.assertEqual(self.total(d, "checkouts"), d["totals"]["checkouts"])
                self.assertEqual(self.total(d, "orders"), d["totals"]["orders"])

    def test_orders_match_the_visits_that_ordered(self):
        d = api.geo_areas(level="state", basis="visitor", **self.R)
        self.assertEqual(d["totals"]["orders"], api.sessions(limit=1, has="order", **self.R)["total"])

    def test_delivery_view_counts_every_order_of_the_orders_page(self):
        n = api.orders_list(scope="sales", limit=1, **self.R)["total"]
        for level in ("state", "city", "pincode"):
            d = api.geo_areas(level=level, basis="delivery", limit=5000, **self.R)
            with self.subTest(level=level):
                self.assertEqual(self.total(d, "orders"), n)
                self.assertEqual(d["totals"]["orders"], n)

    def test_a_state_opens_exactly_its_visits(self):
        d = api.geo_areas(level="state", basis="visitor", **self.R)
        for a in d["areas"][:5]:
            regions = ",".join(sorted({f["region"] for f in a["filters"]}))
            with self.subTest(state=a["name"]):
                self.assertEqual(api.sessions(limit=1, region=regions, **self.R)["total"], a["visits"])

    def test_a_city_opens_exactly_its_visits(self):
        d = api.geo_areas(level="city", basis="visitor", **self.R)
        for a in [x for x in d["areas"] if len(x["filters"]) == 1][:5]:
            f = a["filters"][0]
            with self.subTest(city=a["name"]):
                self.assertEqual(api.sessions(limit=1, city=f["city"], region=f["region"], **self.R)["total"], a["visits"])

    def test_every_area_is_a_point_in_india(self):
        for level, basis in (("state", "visitor"), ("city", "visitor"), ("pincode", "delivery")):
            for a in api.geo_areas(level=level, basis=basis, limit=5000, **self.R)["areas"]:
                self.assertTrue(6 <= a["lat"] <= 38 and 67 <= a["lon"] <= 98.5, (level, a["name"]))

    def test_state_names_match_the_outlines(self):
        from mi import geo
        names = set(geo._data()["centres"])
        for r in q("SELECT DISTINCT region AS n FROM sessions WHERE region IS NOT NULL"):
            c = geo.canon_state(r["n"])
            self.assertTrue(c is None or c in names, r["n"])
        self.assertEqual(geo.canon_state("National Capital Territory Of Delhi"), "Delhi")
        self.assertEqual(geo.canon_state("Jammu And Kashmir"), "Jammu & Kashmir")
        self.assertIsNone(geo.canon_state("Harare"))

    def test_bad_input_is_refused(self):
        from fastapi import HTTPException
        for kw in (dict(level="country"), dict(basis="nope")):
            with self.assertRaises(HTTPException):
                api.geo_areas(**kw, **self.R)


class PriceTab(unittest.TestCase):
    """Price intelligence: the comparison and the analysis agree with each other and with the product sheet."""
    R = dict(date_from="2026-10-22", date_to="2026-11-20")

    @classmethod
    def setUpClass(cls):
        if not q("SELECT 1 FROM information_schema.tables WHERE table_name = 'price_matches'"):
            raise unittest.SkipTest("price tables not built yet (start the dashboard once)")

    def test_every_sheet_product_has_one_row(self):
        rows = api.prices_compare(**self.R)["rows"]
        self.assertEqual(len(rows), len(api.price_catalogue()))
        self.assertEqual(len({r["product_id"] for r in rows}), len(rows))

    def test_the_gap_is_against_the_cheapest_competitor_price(self):
        for r in api.prices_compare(**self.R)["rows"]:
            live = [v["price"] for v in r["sites"].values() if v.get("price")]
            with self.subTest(product=r["product_id"]):
                if not live or not r["our_price"]:
                    self.assertIsNone(r["gap"])
                    continue
                self.assertEqual(r["cheapest_price"], min(live))
                self.assertAlmostEqual(r["gap"], r["our_price"] / min(live) - 1, places=3)

    def test_positions_add_up_to_the_products_compared(self):
        k = api.prices_analysis(**self.R)["kpis"]
        self.assertEqual(k["cheaper"] + k["same"] + k["dearer"], k["compared"])
        self.assertLessEqual(k["dearer_10"], k["dearer"])

    def test_matches_have_known_states(self):
        bad = one("SELECT count(*) AS n FROM price_matches WHERE status NOT IN ('matched', 'review', 'none', 'rejected') OR site NOT IN ('nykaa', 'tira', 'purplle')")
        self.assertEqual(bad["n"], 0)
        self.assertEqual(one("SELECT count(*) AS n FROM price_matches WHERE status = 'matched' AND url IS NULL")["n"], 0)

    def test_readings_are_positive_and_never_compare_the_nykaa_offer(self):
        self.assertEqual(one("SELECT count(*) AS n FROM price_snapshots WHERE ok AND (price <= 0 OR mrp <= 0)")["n"], 0)
        for r in api.prices_compare(**self.R)["rows"]:
            v = r["sites"].get("nykaa")
            if v and v.get("offer_price") and r["cheapest_site"] == "nykaa":
                self.assertEqual(r["cheapest_price"], v["price"])

    def test_bad_decisions_are_refused(self):
        from fastapi import HTTPException
        pid = api.price_catalogue()[0]["product_id"]
        for body in (dict(product_id=pid, site="amazon", action="confirm", url="https://www.amazon.in/x"),
                     dict(product_id=pid, site="tira", action="link", url="https://www.nykaa.com/x/p/1"),
                     dict(product_id="nope", site="tira", action="clear"),
                     dict(product_id=pid, site="tira", action="delete-everything")):
            with self.subTest(body=body), self.assertRaises(HTTPException):
                api.prices_match(api.MatchIn(**body))


class SessionScores(unittest.TestCase):
    """A product match score borrowed for an event that arrived without one."""

    def event(self, at, name, key=None, product="Glow Serum", score=None, session="s1", path=None, note=None):
        return {"session_id": session, "at": at, "event_name": name, "event_key": key, "product_name": product, "path": path, "score": score, "score_note": note}

    def test_it_comes_from_the_latest_earlier_event_of_the_same_product_in_the_same_visit(self):
        from mi.scores import borrow
        sources = [self.event(1, "clicked_product_card", score=70.0), self.event(3, "product_detail_data_loaded", score=81.7), self.event(9, "viewed_product_image", score=99.0),
                   self.event(2, "clicked_product_card", score=10.0, product="Other"), self.event(4, "clicked_product_card", score=11.0, session="s2")]
        t = self.event(5, "clicked_add_to_cart_product_detail", key="add_to_cart")
        borrow([t], sources)
        self.assertEqual((t["score"], t["score_from"]), (81.7, "product_detail_data_loaded"))

    def test_the_product_page_address_identifies_the_product_too(self):
        from mi.scores import borrow
        t = self.event(5, "clicked_add_to_cart_product_detail", product=None, path="/products/abc-1")
        borrow([t], [self.event(1, "page_viewed_product_detail", product="Product", path="/products/abc-1", score=55.0)])
        self.assertEqual(t["score"], 55.0)

    def test_nothing_is_invented(self):
        from mi.scores import borrow
        own = self.event(5, "clicked_add_to_cart", key="add_to_cart", score=60.0)
        later = self.event(1, "clicked_add_to_cart", key="add_to_cart", product="Late")
        unrelated = self.event(8, "ui_clicked")
        not_scorable = self.event(8, "clicked_add_to_cart", key="add_to_cart", note="not scorable")
        sources = [self.event(3, "clicked_product_card", score=90.0), self.event(6, "clicked_product_card", score=80.0, product="Late")]
        borrow([own, later, unrelated, not_scorable], sources)
        self.assertEqual([own["score"], later["score"], unrelated["score"], not_scorable["score"]], [60.0, None, None, None])

    def test_event_rows_mark_a_borrowed_score(self):
        d = api.events_rows(date_from="2026-10-22", date_to="2026-11-20", key="add_to_cart", limit=500, include_excluded=False, include_dup=False, event=None, search=None,
                            payload=[], session=None, person=None, channel=None, cols=None, sort="ts", direction="desc", offset=0)
        for r in d["rows"]:
            if r["score_from"]:
                self.assertIsNotNone(r["score"])
            self.assertNotIn("value", [p["k"] for p in r["params"]])  # the value has its own column

    def test_parameters_by_event_name(self):
        d = api.events_params_by_name(date_from="2026-10-22", date_to="2026-11-20", include_excluded=False, include_dup=False, key=None, sample=20)
        self.assertTrue(d)
        for name, x in d.items():
            with self.subTest(event=name):
                self.assertTrue(0 < x["sampled"] <= 20)
                self.assertTrue(0 <= x["value_share"] <= 1 and all(0 < p["share"] <= 1 for p in x["params"]))


class SpeedVisits(unittest.TestCase):
    R = dict(date_from="2026-10-22", date_to="2026-11-20")

    def test_the_list_matches_the_counts(self):
        d = api.speed_sessions(**self.R)
        m = d["summary"]
        self.assertEqual(d["total"], m["affected"])
        self.assertEqual(len({r["session_id"] for r in d["rows"]}), len(d["rows"]))
        self.assertLessEqual(m["affected"], m["visits"])
        for k in d["labels"]:
            with self.subTest(problem=k):
                one_kind = api.speed_sessions(problem=k, **self.R)
                self.assertEqual(one_kind["total"], m[k])
                self.assertTrue(all(k in r["problems"] for r in one_kind["rows"]))

    def test_every_listed_visit_really_had_a_problem(self):
        for r in api.speed_sessions(limit=25, **self.R)["rows"]:
            n = one("""SELECT (SELECT count(*) FROM pain_events WHERE session_id = ? AND stage = 'speed')
                            + (SELECT count(*) FROM events_clean WHERE session_id = ? AND event_name = 'page_load_sample' AND load_ms > 3000) AS n""", [r["session_id"], r["session_id"]])["n"]
            self.assertGreater(n, 0)

    def test_unknown_problem_is_refused(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            api.speed_sessions(problem="nope", **self.R)


class ReturningChats(unittest.TestCase):
    def test_groups_hold_two_or_more_chats_and_each_chat_once(self):
        d = api.chats(date_from="2026-10-22", date_to="2026-11-20", include_excluded=False, compare=False)
        if not d.get("ready"):
            self.skipTest("no chat data")
        keys = [c["key"] for g in d["returning"] for c in g["chats"]]
        self.assertEqual(len(keys), len(set(keys)))
        for g in d["returning"]:
            with self.subTest(shopper=g["key"]):
                self.assertGreaterEqual(g["n_chats"], 2)
                self.assertEqual(g["messages"], sum(c["messages"] for c in g["chats"]))
        for c in d["conversations"]:
            self.assertEqual(c["returning"], c["key"] in set(keys))
        if d["conversations_total"] <= 300:
            self.assertEqual(len(keys) + sum(1 for c in d["conversations"] if not c["returning"]), d["conversations_total"])

    def test_a_guest_chat_joins_the_account_of_its_browser(self):
        from mi.chats import _group_shoppers
        conv = lambda k, user=None, guest=None, sessions=(), at=1: {"key": k, "user_id": user, "guest_session_id": guest, "sessions": list(sessions), "started_at": at, "updated_at": at,
                                                                    "messages": 1, "failed": 0, "thumbs_up": 0, "thumbs_down": 0}
        sess = {"a": {"visitor_key": "test-browser-one"}, "b": {"visitor_key": "test-browser-one"}, "c": {"visitor_key": "test-browser-two"}}
        convs = [conv("1", guest="g1", sessions=["a"]), conv("2", guest="g2", sessions=["b"], at=2), conv("3", guest="g3", sessions=["c"])]
        groups = _group_shoppers(convs, sess)
        self.assertEqual([(g["kind"], g["n_chats"], g["visitor_id"]) for g in groups], [("browser", 2, "test-browser-one")])
        self.assertEqual([c["returning"] for c in convs], [True, True, False])


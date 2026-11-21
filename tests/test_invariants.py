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

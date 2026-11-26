"""Two (three) simulated computers sharing prices through the real SQL, via the local stand-in API. Nothing touches production or the real database."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ["PRICES_SUPABASE_KEY"] = ""  # never the real one
import duckdb
import requests
from fastapi import HTTPException

from mi import core, price_sync as S, price_sites as P, prices as R

BASE = "http://127.0.0.1:54999"
admin = lambda sql: requests.post(f"{BASE}/__sql", json={"sql": sql}).json()
down = lambda v: requests.post(f"{BASE}/__down", json={"down": v})
URL = lambda n: f"https://www.nykaa.com/product-{n}/p/{n}"
PRODUCTS = [{"product_id": f"P{n}", "name": f"Brand X Serum {n}", "brand": "Brand X", "category": "Face", "type": "Serum", "size": "30ml", "mrp": 1200.0, "price": 1000.0, "link": URL(n), "barcode": None, "image": None} for n in (1, 2, 3)]
PRICES = {1: 900.0, 2: 950.0, 3: 990.0}
R.price_catalogue = lambda: PRODUCTS
R._pull_catalogue = lambda: None
P.pause = lambda: None
hook = {"before_read": None}


def fetch(url, timeout=40):
    if hook["before_read"]:
        hook["before_read"](url)
    return url


P.fetch = fetch
P.read = lambda site, body: {"name": f"Brand X Serum {body.rsplit('/', 1)[1]}", "price": PRICES[int(body.rsplit('/', 1)[1])], "mrp": 1200.0, "offer_price": None, "in_stock": True,
                             "stock_qty": None, "size": "30ml", "discount": None, "ean": None, "variants": []}


class PC:
    def __init__(self, name, shared=True):
        self.name, self.shared = name, shared
        self.con = duckdb.connect(":memory:")
        self.con.execute("SET TimeZone='Asia/Kolkata'")
        self.state = {"last_sync": None, "error": None, "holder": None, "holder_since": None, "conflicts": 0}
        with self:
            R.price_init(self.con)

    def __enter__(self):
        os.environ["PRICES_NAME"] = self.name
        core.CON = self.con
        S.REMOTE = S.Remote(BASE, "test-key") if self.shared else None
        S.STATE.clear(); S.STATE.update(self.state)
        return self

    def __exit__(self, *a):
        self.state = dict(S.STATE)

    def sql(self, q, a=()):
        return self.con.execute(q, list(a)).fetchall()


def run(sites=("nykaa",)):
    R.start_price_run(list(sites), wait=True)
    assert R.PRICE_JOB["error"] is None, R.PRICE_JOB["error"]


def match(pid):
    return R._matches()[(pid, "nykaa")]


def decide(pid, action, version, url=None):
    return R.prices_match(R.MatchIn(product_id=pid, site="nykaa", action=action, version=version, url=url))


def raises(code, fn, text=""):
    try:
        fn()
    except HTTPException as e:
        assert e.status_code == code and text in str(e.detail), (e.status_code, e.detail)
        return str(e.detail)
    raise AssertionError(f"expected HTTP {code}")


passed = []


def ok(name):
    passed.append(name)
    print("ok  ", name)


a, b = PC("asha-pc"), PC("ravi-pc")

with a:
    assert S.check().startswith("The key works")
    run()
    assert S.waiting()["waiting"] == 0, S.waiting()
assert admin("select count(*)::int as n from mi_price_snapshots")[0]["n"] == 3
assert admin("select count(*)::int as n from mi_price_own")[0]["n"] == 3
assert admin("select count(*)::int as n from mi_price_matches")[0]["n"] == 3
assert admin("select status, host from mi_price_runs") == [{"status": "done", "host": "asha-pc"}]
assert admin("select holder from mi_price_lock")[0]["holder"] is None
ok("a run on one computer reaches the shared tables and frees the lock")

with b:
    assert S.sync()["ok"], S.STATE
    rows = R._rows()
    assert [r["sites"]["nykaa"]["price"] for r in rows] == [900.0, 950.0, 990.0], rows
    assert R.prices_runs()["runs"][0]["host"] == "asha-pc"
    assert [x["price"] for x in R.prices_history("P1")["own"]] == [1000.0]
    got = S.sync()["received"]
    assert got["readings"] == 0 and got["own"] == 0 and got["matches"] == 0, got
    assert b.sql("select count(*) from price_snapshots")[0][0] == 3
ok("the other computer receives readings, matches, runs and our price, once")

with b:
    held = S.acquire(S.new_run_id(), "nykaa")
    assert held["ok"]
with a:
    raises(409, run, "ravi-pc is refreshing")
    assert not R.PRICE_JOB["running"]
    assert R.prices_status()["sharing"]["enabled"]
with b:
    assert S.finish(held["token"], "done", {}, None)
ok("only one computer refreshes at a time, and the other is told who")

with a:
    S.sync()
    v = match("P1")["remote_version"]
with b:
    S.sync()
    assert match("P1")["remote_version"] == v
    decide("P1", "notsold", v)
    assert match("P1")["status"] == "rejected"
with a:
    msg = raises(409, lambda: decide("P1", "link", v, URL(1)), "ravi-pc changed this match")
    assert match("P1")["status"] == "rejected" and match("P1")["updated_by"] == "ravi-pc"
ok("a decision made on an old screen is refused and shows who changed it")

with a:  # the job tries to overwrite a person's decision: refused, and this computer takes the shared row
    R._save_match("P1", "nykaa", url=URL(1), status="matched", method="sheet", confidence=1.0, matched_name=None)
    res = S.push()
    assert res["conflicts"] == 1, res
    assert match("P1")["status"] == "rejected" and match("P1")["method"] == "you" and match("P1")["dirty"] is False
ok("an automatic result cannot overwrite a person's decision")

with a:
    decide("P1", "clear", match("P1")["remote_version"])
    assert (match("P1")["status"], match("P1")["method"], match("P1")["checked_at"]) == ("none", None, None)
    R._save_match("P1", "nykaa", url=URL(1), status="matched", method="name", confidence=0.9, matched_name=None)
    assert S.push()["conflicts"] == 0
    assert admin("select status, method from mi_price_matches where product_id = 'P1'") == [{"status": "matched", "method": "name"}]
ok("'Look again' hands a match back to the automatic search")

down(True)
with a:
    before = match("P2")
    raises(503, lambda: decide("P2", "notsold", before["remote_version"]), "not saved")
    assert match("P2") == before
    raises(503, run, "not started")
    assert S.sync()["ok"] is False and S.STATE["error"]
down(False)
ok("offline: no refresh and no decision, nothing changes locally")

PRICES.update({1: 800.0, 2: 810.0, 3: 820.0})
with a:
    S.sync()
    count = admin("select count(*)::int as n from mi_price_snapshots")[0]["n"]
    hook["before_read"] = lambda url: down(True)  # the internet drops as soon as reading starts
    run()
    hook["before_read"] = None
    assert S.waiting()["waiting"] == 3, S.waiting()
    assert S.STATE["error"]
    down(False)
    assert admin("select count(*)::int as n from mi_price_snapshots")[0]["n"] == count
    assert S.sync()["ok"] and S.waiting()["waiting"] == 0
    assert admin("select count(*)::int as n from mi_price_snapshots")[0]["n"] == count + 3
    a.con.execute("update price_snapshots set synced = false")
    S.push()
    assert admin("select count(*)::int as n from mi_price_snapshots")[0]["n"] == count + 3
ok("a dropped connection loses nothing, and sending again creates no duplicates")

with b:  # the first computer's lock is still held after it went offline; once it lapses the next may start
    raises(409, run, "asha-pc is refreshing")
    admin("update mi_price_lock set expires_at = now() - interval '1 second'")
    run()
    assert [r["sites"]["nykaa"]["price"] for r in R._rows()] == [800.0, 810.0, 820.0]
assert admin("select count(*)::int as n from mi_price_runs where status = 'running'")[0]["n"] == 0
ok("a lapsed lock lets the next computer in, and no run is left 'running'")

R.BEAT_SECONDS = 0.2
with a:
    def slow(url):
        admin("update mi_price_lock set token = gen_random_uuid(), holder = 'thief'")
        time.sleep(0.8)
    hook["before_read"] = slow
    R.start_price_run(["nykaa"], wait=True)
    hook["before_read"] = None
    assert R.PRICE_JOB["stop"] and "took over" in R.PRICE_JOB["error"], R.PRICE_JOB
admin("update mi_price_lock set token = null, holder = null, expires_at = null")
R.BEAT_SECONDS = 30
ok("a computer that loses the lock stops")

# first upload: a third computer collected history before sharing was on
c = PC("old-laptop", shared=False)
PRICES.update({1: 700.0, 2: 710.0, 3: 720.0})
with c:
    run(); run()
    decide("P3", "notsold", None)
    log = R.prices_runs()["runs"]
    assert log[0]["summary"]["ok"] >= 2
    assert S.waiting()["history"] == 6, S.waiting()
    assert c.sql("select count(*) from price_snapshots where synced is not null")[0][0] == 0
c.shared = True
snap0 = admin("select count(*)::int as n from mi_price_snapshots")[0]["n"]
with c:
    S.sync()  # before the upload: its own decision must survive the download
    assert match("P3")["status"] == "rejected" and match("P3")["method"] == "you", match("P3")
    assert admin("select count(*)::int as n from mi_price_snapshots")[0]["n"] == snap0, "nothing is uploaded without asking"
    out = R.prices_upload()
    assert out["runs"] == 2 and out["readings"] == 5 or out["readings"] == 6, out
    again = R.prices_upload()
    assert (again["runs"], again["readings"], again["own"]) == (0, 0, 0), again
    assert S.waiting()["history"] == 0
    kept = R.prices_runs()["runs"]
    assert [(r["summary"], r["message"], r["finished_at"]) for r in kept if r["host"] == "old-laptop"] == [(r["summary"], r["message"], r["finished_at"]) for r in log], kept
assert admin("select status, method from mi_price_matches where product_id = 'P3'") == [{"status": "rejected", "method": "you"}]
assert admin("select count(*)::int as n from mi_price_snapshots")[0]["n"] == snap0 + out["readings"]
old = admin("select extract(epoch from now() - min(fetched_at))::int as s from mi_price_snapshots s join mi_price_runs r using (run_id) where r.host = 'old-laptop'")[0]["s"]
assert 0 <= old < 120, old
with a:
    S.sync()
    assert match("P3")["status"] == "rejected" and match("P3")["updated_by"] == "old-laptop"
    assert a.sql("select count(*) from (select run_id, product_id, site from price_snapshots group by all having count(*) > 1)")[0][0] == 0
ok("history is uploaded only on request, once, with a person's decision winning")

S.REMOTE = S.Remote(BASE, "wrong-key")
try:
    S.check()
    raise AssertionError("a wrong key must fail")
except S.Refused as e:
    assert "401" in str(e)
ok("a wrong key is refused with a clear message")
print(f"\n{len(passed)} scenarios passed")

"""Price intelligence: our catalogue (master_products) against the live prices on Nykaa, Tira and Purplle, and what it means.

One "Refresh prices" run (button on the tab; python -m mi.cli prices from a terminal) does, for each site in parallel, one page at a time:
  1. find the product page of every catalogue product not matched yet (the link in the sheet when it points at that site; else the site's
     sitemap, matched by brand + name + size; Purplle pages carry the barcode, so a Purplle match is automatic only when the barcodes agree)
  2. read the price, MRP, offer price, stock and discount of every matched product page and keep it as a snapshot (history is kept)
Uncertain matches wait in the review queue on the tab (confirm, reject, or paste the right link); your decisions are never guessed again.

Tables (user data like the exclusion rules: a data rebuild never drops them):
  price_matches    (product_id, site) -> url, status (matched / review / none / rejected), method (sheet / barcode / name / you), confidence
  price_snapshots  every page read: price, mrp, offer_price, in_stock, stock_qty, discount, error
  price_runs       one row per Refresh prices run
  price_index      the product pages each site lists (its sitemap), refreshed weekly, for matching
  price_own        our own price of every product at each run
With sharing on (mi/price_sync.py, docs/price-sync.md) these are a copy of the tables in Supabase that all computers use; the sitemap list stays local.
The comparison uses the REGULAR competitor price (Nykaa's offer price for some customers is a note only) and the latest price read for each product,
whether or not it is in stock there (only the price matters). Each shop cell is one of: priced, review, not_available (not found, not sold there,
or no price ever seen), unchecked (not looked for or not read yet).
Our price = master_products "Selling Price" / "MRP". The hand-typed competitor prices in the sheet are not used.
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from fastapi import HTTPException
from pydantic import BaseModel

from . import core, price_sites as P, price_sync as S
from .core import app, one, q, ratio
from .db import DB_LOCK

INDEX_MAX_AGE = timedelta(days=7)      # sitemaps are re-read once a week
RETRY_NONE_AFTER = timedelta(days=7)   # a product not found on a site is looked for again after a week (or when you ask)
MAX_BLOCKS = 4                          # refusals in a row before a site is stopped for this run
RESUME_WITHIN = timedelta(hours=6)     # a stopped or interrupted run is continued, not repeated, within this time
BEAT_SECONDS = 30                      # while sharing: keep the lock and send what has been read, this often
LOST_AFTER = 4 * 60                    # seconds without reaching Supabase before the run stops (the lock lapses after 5 minutes)
GONE = "page no longer exists"
AUTO = 0.85                             # name score for an automatic Nykaa / Tira match (with the same size)
REVIEW = 0.55                           # lowest name score worth showing in the review queue

DDL = """
CREATE SEQUENCE IF NOT EXISTS price_runs_seq;
CREATE TABLE IF NOT EXISTS price_runs (run_id BIGINT PRIMARY KEY DEFAULT nextval('price_runs_seq'), started_at TIMESTAMP, finished_at TIMESTAMP,
  status VARCHAR, sites VARCHAR, summary JSON, message VARCHAR);
CREATE TABLE IF NOT EXISTS price_matches (product_id VARCHAR, site VARCHAR, url VARCHAR, status VARCHAR, method VARCHAR, confidence DOUBLE,
  matched_name VARCHAR, candidates JSON, rejected JSON, checked_at TIMESTAMP, updated_at TIMESTAMP, PRIMARY KEY (product_id, site));
CREATE TABLE IF NOT EXISTS price_snapshots (run_id BIGINT, product_id VARCHAR, site VARCHAR, url VARCHAR, fetched_at TIMESTAMP, ok BOOLEAN, error VARCHAR,
  price DOUBLE, mrp DOUBLE, offer_price DOUBLE, in_stock BOOLEAN, stock_qty BIGINT, discount VARCHAR, page_name VARCHAR, page_size VARCHAR);
CREATE TABLE IF NOT EXISTS price_index (site VARCHAR, url VARCHAR, words VARCHAR, fetched_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS price_own (run_id BIGINT, product_id VARCHAR, price DOUBLE, mrp DOUBLE, fetched_at TIMESTAMP, synced BOOLEAN);
CREATE TABLE IF NOT EXISTS price_sync_state (key VARCHAR PRIMARY KEY, value VARCHAR);
-- columns for sharing, added to tables of earlier versions too
ALTER TABLE price_runs ADD COLUMN IF NOT EXISTS host VARCHAR;
ALTER TABLE price_runs ADD COLUMN IF NOT EXISTS remote_id VARCHAR;
ALTER TABLE price_matches ADD COLUMN IF NOT EXISTS remote_version INTEGER;
ALTER TABLE price_matches ADD COLUMN IF NOT EXISTS dirty BOOLEAN;
ALTER TABLE price_matches ADD COLUMN IF NOT EXISTS updated_by VARCHAR;
ALTER TABLE price_snapshots ADD COLUMN IF NOT EXISTS synced BOOLEAN;
"""

PRICE_JOB = {"running": False, "run_id": None, "started": None, "finished": None, "stop": False, "sites": {}, "error": None, "message": ""}
_LOCK = threading.Lock()


def price_init(con) -> None:
    con.execute(DDL)
    # runs of this computer only: a run another computer is doing right now is shown as running until the shared list says otherwise
    con.execute("UPDATE price_runs SET status = 'stopped', message = 'the dashboard was closed during the run' WHERE status = 'running' AND (host IS NULL OR host = ?)", [S.me()])


def _x(sql: str, args=()) -> None:
    with DB_LOCK:
        core.CON.cursor().execute(sql, list(args))


def _have(table: str) -> bool:
    return bool(q("SELECT 1 FROM information_schema.tables WHERE table_name = ?", [table]))


# ---------------------------------------------------------------- the catalogue
def price_catalogue() -> list[dict]:
    """Every master_products row: our price and what matching needs."""
    if not _have("raw_catalog_master"):
        return []
    cols = {r["column_name"] for r in q("SELECT column_name FROM information_schema.columns WHERE table_name = 'raw_catalog_master'")}
    if "sku_size" not in cols:
        raise HTTPException(409, "The product sheet was pulled by an older version. Press Refresh (top right) once to pull it again.")
    return q("""SELECT product_id, any_value(product_name) AS name, any_value(brand) AS brand, any_value(category_l1) AS category, any_value(category_l2) AS type,
                any_value(sku_size) AS size, any_value(mrp) AS mrp, any_value(selling_price) AS price, any_value(product_link) AS link,
                any_value(nullif(trim(bar_code), '')) AS barcode, any_value(images) AS image
                FROM raw_catalog_master WHERE product_id IS NOT NULL GROUP BY 1 ORDER BY 2""")


def _our_sizes(p: dict) -> set:
    return P.sizes_in(p.get("size")) or P.sizes_in(p.get("name"))


# ---------------------------------------------------------------- matches
def _matches() -> dict:
    out = {}
    for r in q("SELECT * FROM price_matches"):
        for k in ("candidates", "rejected"):
            r[k] = json.loads(r[k]) if isinstance(r[k], str) else (r[k] or [])
        out[(r["product_id"], r["site"])] = r
    return out


def _save_match(pid, site, **f) -> None:
    f.setdefault("candidates", [])
    f.setdefault("rejected", [])
    for k in ("candidates", "rejected"):
        f[k] = json.dumps(f[k])
    cols = ["url", "status", "method", "confidence", "matched_name", "candidates", "rejected", "dirty"]
    f["dirty"] = S.enabled()
    vals = [f.get(c) for c in cols]
    _x(f"""INSERT INTO price_matches (product_id, site, {', '.join(cols)}, checked_at, updated_at) VALUES (?, ?, {', '.join('?' * len(cols))}, now(), now())
           ON CONFLICT (product_id, site) DO UPDATE SET {', '.join(f'{c} = excluded.{c}' for c in cols)}, checked_at = now(), updated_at = now()""", [pid, site, *vals])


def _seed_from_sheet(products: list[dict], have: dict) -> None:
    """The product link in the sheet is trusted for its own site (nykaaman.com links are read on nykaa.com)."""
    for p in products:
        u = P.canonical_url(p.get("link"))
        s = P.site_of(u) if u else None
        if s and (p["product_id"], s) not in have:
            _save_match(p["product_id"], s, url=u, status="matched", method="sheet", confidence=1.0, matched_name=None)


def _index(site: str, status, stop) -> list[dict]:
    """The site's product pages (from its sitemap), re-read when older than a week."""
    last = one("SELECT max(fetched_at) AS t FROM price_index WHERE site = ?", [site]).get("t")
    if not last or datetime.now() - last > INDEX_MAX_AGE:
        urls = P.sitemap_urls(site, progress=lambda m: status(phase=m), stop=stop)
        if urls and not stop():
            import pandas as pd
            df = pd.DataFrame({"url": urls, "words": [P.slug_text(u) for u in urls]})
            with DB_LOCK:
                cur = core.CON.cursor()
                cur.execute("DELETE FROM price_index WHERE site = ?", [site])
                cur.register("_pi", df)
                cur.execute("INSERT INTO price_index SELECT ?, url, words, now() FROM _pi", [site])
                cur.unregister("_pi")
    return one("SELECT count(*) AS n FROM price_index WHERE site = ?", [site])["n"]


def _brand_pages(site: str, brand: str, cache: dict) -> list[dict]:
    """The site's pages whose link contains the brand (looked up once per brand and run)."""
    keys = tuple(P.brand_keys(brand))
    if keys not in cache:
        cond = " OR ".join(["regexp_replace(words, '[^a-z0-9]', '', 'g') LIKE ?"] * len(keys))
        cache[keys] = q(f"SELECT url, words FROM price_index WHERE site = ? AND ({cond})", [site, *[f"%{k}%" for k in keys]]) if keys else []
    return cache[keys]


def _candidates(p: dict, pages: list[dict], rejected: list) -> list[dict]:
    """The best few pages on a site for one of our products: same brand, size not different, ranked by name score."""
    ours = _our_sizes(p)
    out = []
    for r in pages:
        if r["url"] in rejected:
            continue
        words = P.fix_sizes(r["words"], ours)
        sv = P.size_verdict(ours, P.sizes_in(words))
        if sv == "different":
            continue
        sc = P.score(p["name"], p.get("brand"), words)
        if sc >= REVIEW:
            out.append({"url": r["url"], "words": words, "score": sc, "size": sv})
    out.sort(key=lambda c: (-c["score"], c["size"] != "same", len(c["words"])))
    return out[:5]


# ---------------------------------------------------------------- one site, one run
def _snapshot(run_id, pid, site, url, got=None, err=None) -> None:
    g = got or {}
    _x("""INSERT INTO price_snapshots (run_id, product_id, site, url, fetched_at, ok, error, price, mrp, offer_price, in_stock, stock_qty, discount, page_name, page_size, synced)
          VALUES (?, ?, ?, ?, now(), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
       [run_id, pid, site, url, err is None, err, g.get("price"), g.get("mrp"), g.get("offer_price"), g.get("in_stock"),
        int(g["stock_qty"]) if str(g.get("stock_qty") or "").isdigit() else None, g.get("discount"), g.get("name"), g.get("size"), False if S.enabled() else None])


def _run_site(site: str, run_id: int, products: list[dict], only: set | None, recheck: bool = False) -> None:
    st = PRICE_JOB["sites"][site]

    def status(**k):
        st.update(k)

    stop = lambda: PRICE_JOB["stop"]  # noqa: E731
    blocks = 0
    have = _matches()

    def visit(url):
        nonlocal blocks
        P.pause()
        try:
            got = P.read(site, P.fetch(url))
            blocks = 0
            return got, None
        except P.Blocked as e:
            blocks += 1
            if blocks >= MAX_BLOCKS:
                raise
            time.sleep(60)  # back off once, then go on
            return None, f"blocked by {P.LABEL[site]} ({e})"
        except P.PageGone as e:
            return None, f"{GONE} ({e})"
        except Exception as e:  # layout changed, network ... recorded with the reason, the run goes on
            return None, str(e)[:200]

    # 1. products that still need a page on this site
    todo = [p for p in products if (only is None or p["product_id"] in only)]
    need = []
    for p in todo:
        m = have.get((p["product_id"], site))
        if (m is None or (m["status"] == "none" and (not m["checked_at"] or datetime.now() - m["checked_at"] > RETRY_NONE_AFTER))
                or (recheck and m["status"] in ("none", "review") and m["method"] != "you")):  # "search again": everything you have not decided
            need.append(p)
    if need:
        status(phase=f"loading the {P.LABEL[site]} product list")
        if not _index(site, status, stop):
            raise RuntimeError(f"could not read the {P.LABEL[site]} product list (sitemap)")
        brand_cache: dict = {}
        status(phase="finding our products", total=len(need), done=0)
        for i, p in enumerate(need, 1):
            if stop():
                return
            m = have.get((p["product_id"], site)) or {}
            cands = _candidates(p, _brand_pages(site, p.get("brand"), brand_cache), m.get("rejected") or [])
            status(done=i)
            if not cands:
                _save_match(p["product_id"], site, url=None, status="none", method=None, confidence=0, matched_name=None, rejected=m.get("rejected") or [])
                continue
            decided = None
            tries = cands[:2] if site == "purplle" and p.get("barcode") else cands[:1]
            for c in tries:  # open the best candidate(s): the page also gives the price
                got, err = visit(c["url"])
                c["page_name"], c["price"], c["in_stock"] = (got or {}).get("name"), (got or {}).get("price"), (got or {}).get("in_stock")
                if got is None:
                    continue
                same_size = P.size_verdict(_our_sizes(p), P.sizes_in(got.get("size")) or P.sizes_in(got.get("name")))
                if site == "purplle" and p.get("barcode") and got.get("ean"):
                    if got["ean"] == str(p["barcode"]).strip():
                        decided = ("matched", "barcode", 1.0, c, got)
                        break
                    c["other_barcode"] = got["ean"]  # a different barcode: certainly another product, never put to review
                    continue
                got, size_problem = P.fit_size(got, _our_sizes(p))  # the variant of OUR size (Nykaa sells every size on one page)
                c["price"], c["in_stock"] = got.get("price"), got.get("in_stock")
                if size_problem:
                    same_size = "different"
                page_score = max(c["score"], P.score(p["name"], p.get("brand"), got.get("name") or ""))
                c["page_size"] = same_size
                size_ok = "same" if "same" in (same_size, c["size"]) and same_size != "different" else same_size
                if site != "purplle" and (P.same_product(p["name"], p.get("brand"), got.get("name") or "", size_ok)
                                          or (page_score >= AUTO and size_ok == "same")):
                    decided = ("matched", "name", page_score, c, got)
                    break
                if same_size != "different":
                    decided = decided or ("review", "name", page_score, c, got)
            if decided:
                stat, method, conf, c, got = decided
                _save_match(p["product_id"], site, url=c["url"], status=stat, method=method, confidence=conf, matched_name=c.get("page_name"),
                            candidates=[{k: x.get(k) for k in ("url", "score", "size", "page_size", "page_name", "price", "in_stock")} for x in cands], rejected=m.get("rejected") or [])
                if stat == "matched":
                    _snapshot(run_id, p["product_id"], site, c["url"], got)
            elif not any(c.get("page_name") or c.get("other_barcode") for c in tries):
                continue  # none of the pages could be read (blocked, network): nothing learned, it is tried again at the next refresh
            else:  # every opened page was another product (other barcode, or a different size): not found; unopened candidates stay for review
                # a Purplle product with a barcode whose best pages all carry OTHER barcodes is not sold there: its weaker candidates are not worth your time
                barcode_says_no = site == "purplle" and p.get("barcode") and all(x.get("other_barcode") for x in tries)
                keep = [] if barcode_says_no else [x for x in cands if not x.get("other_barcode") and x not in tries]
                _save_match(p["product_id"], site, url=None, status="review" if keep else "none", method="name", confidence=cands[0]["score"], matched_name=None,
                            candidates=[{k: x.get(k) for k in ("url", "score", "size", "page_size", "page_name", "price", "in_stock")} for x in keep], rejected=m.get("rejected") or [])

    # 2. read every matched page that was not read in step 1 (or by the stopped run this one continues)
    done_now = {r["product_id"] for r in q("SELECT product_id FROM price_snapshots WHERE run_id = ? AND site = ?", [run_id, site])}
    if only is None:
        prev = one("""SELECT run_id, status, started_at FROM price_runs WHERE run_id <> ? AND started_at <= (SELECT started_at FROM price_runs WHERE run_id = ?)
                      ORDER BY started_at DESC, run_id DESC LIMIT 1""", [run_id, run_id])
        if prev.get("status") == "stopped" and prev.get("started_at") and datetime.now() - prev["started_at"] < RESUME_WITHIN:
            done_now |= {r["product_id"] for r in q("SELECT product_id FROM price_snapshots WHERE run_id = ? AND site = ? AND ok", [prev["run_id"], site])}
    byid = {p["product_id"]: p for p in products}
    pages = [(pid, m, False) for (pid, s), m in _matches().items() if s == site and m["status"] == "matched" and m["url"] and pid not in done_now
             and pid in byid and (only is None or pid in only)]
    total = len(pages)
    status(phase="reading prices", total=total, done=0)
    i = 0
    while i < len(pages):  # pages that fail once are added to the end and tried one more time
        if stop():
            return
        pid, m, again = pages[i]
        i += 1
        url = m["url"]
        got, err = visit(url)
        gone = bool(err) and err.startswith(GONE)
        if got is None and not gone and not again:
            pages.append((pid, m, True))
            continue
        if gone and m["method"] != "you":  # a dead link: forget it and look for the product again at the next refresh
            _save_match(pid, site, url=None, status="none", method=m["method"], confidence=0, matched_name=None, rejected=sorted(set(m.get("rejected") or []) | {url}))
            _x("UPDATE price_matches SET checked_at = NULL WHERE product_id = ? AND site = ?", [pid, site])
        if got is not None:
            got, size_problem = P.fit_size(got, _our_sizes(byid[pid]))  # the price of OUR size, never another size's
            if size_problem and m["method"] != "you":  # e.g. a sheet link to a page that only sells 59 / 118 ml when ours is 125 ml: ask, do not compare
                err = f"not our size ({size_problem}; ours {byid[pid].get('size')})"
                _save_match(pid, site, url=None, status="review", method=m["method"], confidence=m["confidence"], matched_name=None,
                            candidates=[{"url": url, "score": m["confidence"], "size": "different", "page_size": "different", "page_name": got.get("name"),
                                         "price": got.get("price"), "in_stock": got.get("in_stock"), "note": size_problem}], rejected=m.get("rejected") or [])
                got = None
        _snapshot(run_id, pid, site, url, got, err)
        status(done=min(st.get("done", 0) + 1, total), ok=st.get("ok", 0) + (err is None), failed=st.get("failed", 0) + (err is not None))
    failed, read = st.get("failed", 0), st.get("ok", 0) + st.get("failed", 0)
    if failed >= 10 and failed > 0.3 * read:
        status(error=f"{failed} of {read} {P.LABEL[site]} pages failed: the site may have changed its pages (see the Refresh log)")


def _record_own(run_id: int, products: list[dict]) -> None:
    """Our own price of every product at this run, so the history graph has our line too."""
    flag = False if S.enabled() else None
    with DB_LOCK:
        cur = core.CON.cursor()
        for p in products:
            if p.get("price") is not None:
                cur.execute("INSERT INTO price_own VALUES (?, ?, ?, ?, now(), ?)", [run_id, p["product_id"], p["price"], p.get("mrp"), flag])


def _pull_catalogue() -> None:
    """Every computer compares the same products: take the latest product sheet before a shared run (the copy here is used if that fails)."""
    from . import extract
    try:
        extract.extract_small(core.CON.cursor(), only={"raw_catalog_master"})
    except Exception as e:
        PRICE_JOB["message"] = f"using the product sheet already here (could not pull it: {type(e).__name__})"


def _beat(token: str, done: threading.Event) -> None:
    """While a shared run is going: keep the lock and send what has been read. Stops the run if the lock is lost."""
    reached = time.monotonic()
    while not done.wait(BEAT_SECONDS):
        try:
            if not S.renew(token):
                PRICE_JOB.update(stop=True, error="Another computer took over the refresh: this one stopped.")
                return
            reached = time.monotonic()
            S.push()
            S.STATE.update(error=None, last_sync=datetime.now().isoformat(timespec="seconds"))
        except (S.Unreachable, S.Refused) as e:
            S.STATE["error"] = str(e)
            if time.monotonic() - reached > LOST_AFTER:
                PRICE_JOB.update(stop=True, error="Supabase could not be reached for several minutes: the run stopped, so another computer does not overlap it.")
                return
        except Exception as e:  # a local problem must not end the heartbeat
            S.STATE["error"] = f"{type(e).__name__}: {e}"


def _run(run_id: int, sites: list[str], only: set | None, recheck: bool = False, token: str | None = None) -> None:
    done = threading.Event()
    beat = None
    final, summary, message = "failed", {}, None
    try:
        if token:
            beat = threading.Thread(target=_beat, args=(token, done), daemon=True)
            beat.start()
            _pull_catalogue()
        products = price_catalogue()
        _record_own(run_id, [p for p in products if only is None or p["product_id"] in only])
        _seed_from_sheet(products, _matches())

        def one_site(site):
            try:
                _run_site(site, run_id, products, only, recheck)
                PRICE_JOB["sites"][site]["phase"] = "stopped" if PRICE_JOB["stop"] else "done"
            except P.Blocked as e:
                PRICE_JOB["sites"][site].update(phase="stopped", error=f"{P.LABEL[site]} kept refusing our requests ({e}); try again later")
            except Exception as e:
                PRICE_JOB["sites"][site].update(phase="failed", error=f"{type(e).__name__}: {str(e)[:200]}")

        with ThreadPoolExecutor(len(sites)) as ex:
            list(ex.map(one_site, sites))
        counts = one("""SELECT count(*) AS pages, count(*) FILTER (WHERE ok) AS ok, count(*) FILTER (WHERE NOT ok) AS failed FROM price_snapshots WHERE run_id = ?""", [run_id])
        errs = [v["error"] for v in PRICE_JOB["sites"].values() if v.get("error")] + ([PRICE_JOB["error"]] if PRICE_JOB["error"] else [])
        final = "stopped" if PRICE_JOB["stop"] else ("done with problems" if errs else "done")
        summary, message = {**counts, "sites": PRICE_JOB["sites"]}, "; ".join(errs)[:500] or None
    except Exception as e:
        PRICE_JOB["error"] = f"{type(e).__name__}: {e}"
        message = PRICE_JOB["error"][:500]
    finally:
        done.set()
        if beat:
            beat.join(timeout=60)
        try:
            _x("UPDATE price_runs SET finished_at = now(), status = ?, summary = ?, message = ? WHERE run_id = ?", [final, json.dumps(summary, default=str) if summary else None, message, run_id])
            if token:
                _close_shared(token, final, summary, message)
        finally:
            PRICE_JOB.update(running=False, finished=datetime.now().isoformat(timespec="seconds"))


def _close_shared(token: str, final: str, summary: dict, message: str | None) -> None:
    """Send the last readings and free the lock. What cannot be sent waits here and goes with the next sync."""
    try:
        S.push()
        S.finish(token, final, summary, message)
        S.pull()
        S.read_lock()
        S.STATE.update(error=None, last_sync=datetime.now().isoformat(timespec="seconds"))
    except (S.Unreachable, S.Refused) as e:
        S.STATE["error"] = f"The run is saved here but not all of it has reached Supabase yet ({e}). Press Sync now when you are online."


def _take_turn(sites: list[str]) -> tuple[str, str]:
    """Before a shared run: get up to date and take the lock. Returns (run id in Supabase, lock token); refuses when another computer is refreshing."""
    try:
        S.push()
        S.pull()
        run = S.new_run_id()
        got = S.acquire(run, ",".join(sites))
    except S.Unreachable as e:
        raise HTTPException(503, f"{e}. A refresh is not started while the shared prices cannot be reached, so computers do not drift apart. Prices already downloaded can still be viewed.")
    except S.Refused as e:
        raise HTTPException(502, f"Supabase refused: {e}")
    if not got.get("ok"):
        since = S._in(got.get("since"))
        raise HTTPException(409, f"{got.get('holder') or 'Another computer'} is refreshing prices" + (f" (since {since:%H:%M})" if since else "") + ". Their results appear here when you sync.")
    return run, got["token"]


def start_price_run(sites=None, only: set | None = None, wait: bool = False, recheck: bool = False) -> dict:
    """Start a Refresh prices run in the background (wait=True runs it here, for the command line)."""
    sites = [s for s in (sites or P.SITES) if s in P.SITES]
    with _LOCK:
        if PRICE_JOB["running"]:
            raise HTTPException(409, "Prices are already being refreshed")
        price_catalogue()  # fails early (409) when the sheet must be pulled again
        remote_id, token = _take_turn(sites) if S.enabled() else (None, None)
        with DB_LOCK:
            cur = core.CON.cursor()
            row = cur.execute("SELECT run_id FROM price_runs WHERE remote_id = ?", [remote_id]).fetchone() if remote_id else None  # already downloaded with the list
            if row:
                run_id = row[0]
                cur.execute("UPDATE price_runs SET started_at = now(), status = 'running', sites = ?, host = ? WHERE run_id = ?", [",".join(sites), S.me(), run_id])
            else:
                run_id = cur.execute("INSERT INTO price_runs (started_at, status, sites, host, remote_id) VALUES (now(), 'running', ?, ?, ?) RETURNING run_id",
                                     [",".join(sites), S.me(), remote_id]).fetchone()[0]
        PRICE_JOB.update(running=True, run_id=run_id, started=datetime.now().isoformat(timespec="seconds"), finished=None, stop=False, error=None, message="",
                         sites={s: {"phase": "starting", "done": 0, "total": 0, "ok": 0, "failed": 0, "error": None} for s in sites})
    if wait:
        _run(run_id, sites, only, recheck, token)
    else:
        threading.Thread(target=_run, args=(run_id, sites, only, recheck, token), daemon=True).start()
    return PRICE_JOB


# ---------------------------------------------------------------- API: run control
@app.post("/api/prices/refresh")
def prices_refresh(site: str | None = None, recheck: bool = False):
    """recheck = also search again for everything not available or waiting for review (not what you decided yourself)."""
    return start_price_run([site] if site else None, recheck=recheck)


@app.post("/api/prices/stop")
def prices_stop():
    if PRICE_JOB["running"]:
        PRICE_JOB["stop"] = True
    return PRICE_JOB


@app.get("/api/prices/status")
def prices_status():
    last = one("SELECT * FROM price_runs WHERE status <> 'running' ORDER BY started_at DESC, run_id DESC LIMIT 1") if _have("price_runs") else {}
    counts = {r["site"]: r for r in q("""SELECT site, count(*) FILTER (WHERE status = 'matched') AS matched, count(*) FILTER (WHERE status = 'review') AS review,
                                         count(*) FILTER (WHERE status IN ('none', 'rejected')) AS not_found FROM price_matches GROUP BY 1""")} if _have("price_matches") else {}
    try:
        n, need_pull = len(price_catalogue()), False
    except HTTPException:
        n, need_pull = 0, True
    sharing = {"enabled": S.enabled()}
    if sharing["enabled"] and _have("price_sync_state"):
        sharing.update(S.STATE, me=S.me(), **S.waiting())
    return {"job": PRICE_JOB, "last_run": last or None, "products": n, "needs_pull": need_pull, "sharing": sharing,
            "sites": {s: {"label": P.LABEL[s], **counts.get(s, {"matched": 0, "review": 0, "not_found": 0})} for s in P.SITES}}


@app.post("/api/prices/sync")
def prices_sync():
    """With sharing on: send what waits on this computer and fetch what others added. The screen calls it when the tab opens."""
    return S.sync()


@app.post("/api/prices/upload")
def prices_upload():
    """The first upload, only when you press the button: this computer's history from before sharing was on."""
    if not S.enabled():
        raise HTTPException(409, "Sharing is not set up on this computer (see docs/price-sync.md)")
    if PRICE_JOB["running"]:
        raise HTTPException(409, "Wait for the price refresh to finish")
    try:
        return S.upload_history()
    except S.Unreachable as e:
        raise HTTPException(503, f"{e}. Press the button again later: what was sent is not sent twice.")
    except S.Refused as e:
        raise HTTPException(502, f"Supabase refused: {e}")


@app.get("/api/prices/runs")
def prices_runs(limit: int = 20):
    rows = q("SELECT run_id, started_at, finished_at, status, sites, summary, message, host FROM price_runs ORDER BY started_at DESC, run_id DESC LIMIT ?", [max(1, min(limit, 200))])
    for r in rows:
        r["summary"] = json.loads(r["summary"]) if isinstance(r["summary"], str) else r["summary"]
    errors = q("""SELECT site, error, count(*) AS n, any_value(url) AS example FROM price_snapshots WHERE NOT ok
                  AND run_id = (SELECT run_id FROM price_snapshots ORDER BY fetched_at DESC LIMIT 1)
                  GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 20""")
    return {"runs": rows, "last_errors": errors}


# ---------------------------------------------------------------- API: review queue
@app.get("/api/prices/review")
def prices_review(site: str | None = None, status: str = "review"):
    if status not in ("review", "none", "rejected", "matched"):
        raise HTTPException(400, "status must be review, none, rejected or matched")
    prods = {p["product_id"]: p for p in price_catalogue()}
    out = []
    for (pid, s), m in sorted(_matches().items(), key=lambda kv: (kv[0][1], (prods.get(kv[0][0]) or {}).get("name") or "")):
        if m["status"] != status or (site and s != site) or pid not in prods:
            continue
        p = prods[pid]
        out.append({"product_id": pid, "site": s, "site_label": P.LABEL[s], "name": p["name"], "brand": p["brand"], "size": p["size"], "our_price": p["price"],
                    "url": m["url"], "method": m["method"], "confidence": m["confidence"], "matched_name": m["matched_name"], "candidates": m["candidates"],
                    "version": m.get("remote_version") or 0, "updated_by": m.get("updated_by")})
    return {"rows": out}


class MatchIn(BaseModel):
    product_id: str
    site: str
    action: str             # confirm | reject | link | clear | notsold
    url: str | None = None  # for confirm (a candidate) or link (pasted)
    version: int | None = None  # with sharing: the version of the match the screen showed


@app.post("/api/prices/match")
def prices_match(body: MatchIn):
    """Your decision on a match; it is kept and never guessed again. A confirmed or pasted link is read at the next Refresh prices."""
    if body.site not in P.SITES:
        raise HTTPException(400, f"site must be one of {list(P.SITES)}")
    if body.product_id not in {p["product_id"] for p in price_catalogue()}:
        raise HTTPException(404, "unknown product")
    if body.action not in ("confirm", "link", "reject", "clear", "notsold"):
        raise HTTPException(400, "action must be confirm, reject, link, clear or notsold")
    if body.action in ("confirm", "link"):
        u = P.canonical_url(body.url)
        if not u or P.site_of(u) != body.site:
            raise HTTPException(400, f"paste a {P.LABEL[body.site]} product link (https://{P.HOSTS[body.site][0]}/...)")
    try:
        S.decide(body.product_id, body.site, body.version, lambda: _apply_decision(body))
    except S.Conflict as e:
        who = e.row.get("updated_by") or "Someone else"
        raise HTTPException(409, f"{who} changed this match just now, so yours was not saved. The list now shows their decision.")
    except S.Unreachable as e:
        raise HTTPException(503, f"{e}. Your decision was not saved: try again when you are online.")
    except S.Refused as e:
        raise HTTPException(502, f"Supabase refused: {e}")
    return {"ok": True}


def _apply_decision(body: MatchIn) -> None:
    """Change the local match as the person asked (read fresh: with sharing on it was just updated)."""
    m = _matches().get((body.product_id, body.site)) or {"candidates": [], "rejected": []}
    if body.action in ("confirm", "link"):
        u = P.canonical_url(body.url)
        _save_match(body.product_id, body.site, url=u, status="matched", method="you", confidence=1.0, matched_name=next((c.get("page_name") for c in m["candidates"] if c.get("url") == u), None),
                    candidates=m["candidates"], rejected=[x for x in m["rejected"] if x != u])
    elif body.action == "reject":  # this page is not our product: never propose it again
        bad = body.url or m.get("url")
        left = [c for c in m["candidates"] if c.get("url") != bad]
        still = m.get("status") == "review" and bool(left)  # other suggestions remain: the question stays open
        _save_match(body.product_id, body.site, url=None, status="review" if still else "rejected", method=m.get("method") if still else "you",
                    confidence=m.get("confidence") if still else 0, matched_name=None, candidates=left, rejected=sorted(set(m["rejected"]) | ({bad} if bad else set())))
    elif body.action == "notsold":  # the site does not sell it
        _save_match(body.product_id, body.site, url=None, status="rejected", method="you", confidence=0, matched_name=None, candidates=[],
                    rejected=sorted(set(m["rejected"]) | {c["url"] for c in m["candidates"] if c.get("url")}))
    elif S.enabled():  # clear, shared: a row cannot be removed there, so it goes back to "not found, never looked for"
        _save_match(body.product_id, body.site, url=None, status="none", method=None, confidence=0, matched_name=None)
        _x("UPDATE price_matches SET checked_at = NULL WHERE product_id = ? AND site = ?", [body.product_id, body.site])
    else:  # clear: forget the match, it is looked for again at the next refresh
        _x("DELETE FROM price_matches WHERE product_id = ? AND site = ?", [body.product_id, body.site])


# ---------------------------------------------------------------- comparison and analysis
LATEST = """
WITH m AS (SELECT * FROM price_matches WHERE status = 'matched'),
r AS (SELECT s.* FROM price_snapshots s JOIN m ON m.product_id = s.product_id AND m.site = s.site AND m.url = s.url),
p AS (SELECT * FROM r WHERE ok AND price IS NOT NULL QUALIFY row_number() OVER (PARTITION BY product_id, site ORDER BY fetched_at DESC) = 1),
t AS (SELECT product_id, site, max(fetched_at) AS last_try, max(fetched_at) FILTER (WHERE ok) AS last_ok FROM r GROUP BY 1, 2)
SELECT m.product_id, m.site, m.url, m.method, p.fetched_at, p.price, p.mrp, p.offer_price, p.discount, p.page_name, t.last_try, t.last_ok
FROM m LEFT JOIN p ON p.product_id = m.product_id AND p.site = m.site
LEFT JOIN t ON t.product_id = m.product_id AND t.site = m.site
"""


def _cell(match: dict | None, r: dict | None, ours) -> dict:
    """What one shop's column shows for one product."""
    if not match:
        return {"state": "unchecked"}
    if match["status"] == "review":
        return {"state": "review"}
    if match["status"] != "matched":
        return {"state": "not_available"}
    r = r or {}
    if r.get("price") is None:  # read fine but the page has never shown a price: nothing to sell; never read: not checked yet
        return {"state": "not_available" if r.get("last_ok") else "unchecked", "url": match["url"]}
    return {"state": "priced", "url": match["url"], "method": match["method"], "price": r["price"], "mrp": r["mrp"], "offer_price": r["offer_price"], "discount_text": r["discount"],
            "checked": r["fetched_at"], "earlier": bool(r["last_try"] and r["fetched_at"] < r["last_try"]),  # a later read gave no price: this one is older
            "discount": round(1 - r["price"] / r["mrp"], 4) if r["price"] and r["mrp"] else None,
            "gap": round(ours / r["price"] - 1, 4) if ours and r["price"] else None}


_NAME_MAP: dict = {}  # event product name -> catalogue product id (or None), remembered for the life of the server


def _product_of(name: str, prods: list[dict], exact: dict) -> str | None:
    """The catalogue product an event's product name means. The site names products differently in different events (a product page view
    may carry the long page title, an add-to-cart the short name), so: the exact name, else the same brand + a confident name match, size not different."""
    k = (name or "").strip().lower()
    if k in exact:
        return exact[k]
    if k not in _NAME_MAP:
        words, best = P.norm(name), (0.0, None)
        for p in prods:
            if not P.brand_in(p.get("brand"), words) and not P.brand_in(p.get("brand"), P.norm(p["name"])):
                continue
            if P.size_verdict(_our_sizes(p), P.sizes_in(name)) == "different":
                continue
            a, b = P.coverage(p["name"], p.get("brand"), name)
            sc = max(min(a, b), (a + b) / 2 if min(a, b) >= 0.7 else 0)
            if sc > best[0]:
                best = (sc, p["product_id"])
        _NAME_MAP[k] = best[1] if best[0] >= 0.85 else None
    return _NAME_MAP[k]


def _demand(d_from, d_to, include_excluded) -> dict:
    """Our own numbers per catalogue product in the dates: visits that viewed it (or added it straight from a list), visits that added it
    to cart, orders, units and revenue. Events are tied to the product by name (see _product_of); orders by product id, else by name."""
    if not _have("events_clean"):
        return {}
    ex = "" if include_excluded else " AND NOT is_excluded"
    lo, hi = d_from or "2000-01-01", d_to or "2999-12-31"
    prods = price_catalogue()
    exact = {(p["name"] or "").strip().lower(): p["product_id"] for p in prods}
    ev = q(f"""SELECT product_name AS name, session_id, bool_or(event_key = 'add_to_cart') AS carted
               FROM events_clean WHERE product_name IS NOT NULL AND event_key IN ('product_view', 'add_to_cart') AND ts_ist::DATE BETWEEN ? AND ?{ex}
               GROUP BY 1, 2""", [lo, hi])
    seen: dict = {}
    # product pages: the tracker often names the product just "Product", but the page path holds its id (/products/<id> or /products/<slug>--<id-with-dashes>)
    ids = {p["product_id"] for p in prods}
    for r in q(f"""SELECT DISTINCT session_id, url_decode(regexp_extract(path, '/products/([^/?#]+)', 1)) AS slug FROM events_clean
                   WHERE event_key = 'product_view' AND path LIKE '/products/%' AND ts_ist::DATE BETWEEN ? AND ?{ex}""", [lo, hi]):
        slug = r["slug"] or ""
        alt = slug.split("--", 1)[1].replace("-", "/").upper() if "--" in slug else None
        pid = slug if slug in ids else alt if alt in ids else None
        if pid:
            seen.setdefault(pid, {"views": set(), "carts": set()})["views"].add(r["session_id"])
    for r in ev:
        if (r["name"] or "").strip().lower() == "product":
            continue  # the placeholder name: these visits are counted by their page above
        pid = _product_of(r["name"], prods, exact)
        if pid:
            x = seen.setdefault(pid, {"views": set(), "carts": set()})
            x["views"].add(r["session_id"])
            if r["carted"]:
                x["carts"].add(r["session_id"])
    ol = q(f"""SELECT product_id, lower(product_name) AS k, sum(qty) AS units, count(DISTINCT order_id) AS orders, sum(line_total) AS revenue
               FROM order_lines WHERE is_valid AND date_ist BETWEEN ? AND ?{ex} GROUP BY 1, 2""", [lo, hi]) if _have("order_lines") else []
    out = {}
    for p in prods:
        k = (p["name"] or "").lower()
        x = seen.get(p["product_id"], {"views": set(), "carts": set()})
        o = [r for r in ol if r["product_id"] == p["product_id"] or r["k"] == k]
        out[p["product_id"]] = {"views": len(x["views"]), "carts": len(x["carts"]), "orders": sum(r["orders"] for r in o), "units": sum(r["units"] or 0 for r in o),
                                "revenue": float(sum(r["revenue"] or 0 for r in o))}
    return out


def _position(gap):
    if gap is None:
        return "no_data"
    return "dearer" if gap > 0.01 else "cheaper" if gap < -0.01 else "same"


def _rows(d_from=None, d_to=None, include_excluded=False) -> list[dict]:
    prods = price_catalogue()
    latest = {}
    if _have("price_snapshots"):
        for r in q(LATEST):
            latest.setdefault(r["product_id"], {})[r["site"]] = r
    dem = _demand(d_from, d_to, include_excluded)
    matches = _matches() if _have("price_matches") else {}
    out = []
    for p in prods:
        ours, mrp = p["price"], p["mrp"]
        sites = {s: _cell(matches.get((p["product_id"], s)), (latest.get(p["product_id"]) or {}).get(s), ours) for s in P.SITES}
        priced = {s: v["price"] for s, v in sites.items() if v.get("price")}
        cheapest = min(priced, key=priced.get) if priced else None
        gap = round(ours / priced[cheapest] - 1, 4) if ours and cheapest else None
        out.append({**{k: p[k] for k in ("product_id", "name", "brand", "category", "type", "size", "image")}, "our_price": ours, "our_mrp": mrp,
                    "our_discount": round(1 - ours / mrp, 4) if ours and mrp else None, "sites": sites, "cheapest_site": cheapest,
                    "cheapest_price": priced.get(cheapest) if cheapest else None, "gap": gap, "position": _position(gap),
                    "saving_needed": round(ours - priced[cheapest], 2) if cheapest and gap and gap > 0 else 0,
                    **dem.get(p["product_id"], {"views": 0, "carts": 0, "orders": 0, "units": 0, "revenue": 0.0})})
    return out


@app.get("/api/prices/compare")
def prices_compare(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False):
    """One row per catalogue product: our price, each site's latest regular price, the cheapest, our gap, and our own demand in the dates."""
    return {"rows": _rows(date_from, date_to, include_excluded), "sites": [{"key": s, "label": P.LABEL[s]} for s in P.SITES]}


def _med(v):
    v = sorted(x for x in v if x is not None)
    if not v:
        return None
    n = len(v)
    return round(v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2, 4)


@app.get("/api/prices/analysis")
def prices_analysis(date_from: str | None = None, date_to: str | None = None, include_excluded: bool = False):
    rows = _rows(date_from, date_to, include_excluded)
    compared = [r for r in rows if r["gap"] is not None]
    k = {"products": len(rows), "compared": len(compared), "cheaper": sum(r["position"] == "cheaper" for r in compared), "same": sum(r["position"] == "same" for r in compared),
         "dearer": sum(r["position"] == "dearer" for r in compared), "dearer_10": sum(1 for r in compared if r["gap"] > 0.10), "median_gap": _med([r["gap"] for r in compared])}
    k["cheapest_share"] = ratio(k["cheaper"] + k["same"], k["compared"])
    per_site = []
    for s in P.SITES:
        cells = [r["sites"][s] for r in rows]
        have = [(r, r["sites"][s]) for r in rows if r["sites"][s]["state"] == "priced"]
        gaps = [v["gap"] for _, v in have if v["gap"] is not None]
        disc = [(v["discount"], r["our_discount"]) for r, v in have if v["discount"] is not None and r["our_discount"] is not None]
        per_site.append({"site": s, "label": P.LABEL[s], "priced": len(have), "review": sum(c["state"] == "review" for c in cells),
                         "not_available": sum(c["state"] == "not_available" for c in cells), "unchecked": sum(c["state"] == "unchecked" for c in cells),
                         "median_gap": _med(gaps), "we_dearer": sum(1 for g in gaps if g > 0.01), "we_cheaper": sum(1 for g in gaps if g < -0.01),
                         "their_discount": _med([a for a, _ in disc]), "our_discount": _med([b for _, b in disc]), "with_offer": sum(1 for _, v in have if v["offer_price"])})

    def group(key):
        g = {}
        for r in compared:
            x = g.setdefault(r.get(key) or "Unknown", {"name": r.get(key) or "Unknown", "products": 0, "dearer": 0, "gaps": [], "revenue": 0.0})
            x["products"] += 1
            x["dearer"] += r["position"] == "dearer"
            x["gaps"].append(r["gap"])
            x["revenue"] += r["revenue"]
        out = [{**{k2: v for k2, v in x.items() if k2 != "gaps"}, "median_gap": _med(x["gaps"]), "index": round(100 * (1 + (_med(x["gaps"]) or 0)), 1)} for x in g.values()]
        return sorted(out, key=lambda x: (-x["products"], x["name"]))

    cart_rate = ratio(sum(r["carts"] for r in rows), sum(r["views"] for r in rows))
    at_risk = sorted([r for r in compared if r["position"] == "dearer" and (r["revenue"] or r["views"])], key=lambda r: (-r["revenue"], -r["views"]))[:25]
    sensitive = sorted([r for r in compared if r["position"] == "dearer" and r["views"] >= 20 and ratio(r["carts"], r["views"]) < cart_rate],
                       key=lambda r: -r["views"])[:25]
    return {"kpis": k, "sites": per_site, "by_brand": group("brand")[:40], "by_category": group("category"), "cart_rate": cart_rate,
            "at_risk": [_lite(r) for r in at_risk], "price_sensitive": [{**_lite(r), "cart_rate": ratio(r["carts"], r["views"])} for r in sensitive],
            "changes": _changes()}


def _lite(r: dict) -> dict:
    return {k: r[k] for k in ("product_id", "name", "brand", "size", "our_price", "cheapest_site", "cheapest_price", "gap", "saving_needed", "views", "carts", "orders",
                              "revenue", "position")}


def _changes(limit: int = 40) -> list[dict]:
    """Price changes between each product's last two prices read from its matched page on a site."""
    if not _have("price_snapshots"):
        return []
    names = {p["product_id"]: p for p in price_catalogue()}
    rows = q("""WITH s AS (SELECT s.product_id, s.site, s.fetched_at, s.price, row_number() OVER (PARTITION BY s.product_id, s.site ORDER BY s.fetched_at DESC) AS n
                           FROM price_snapshots s JOIN price_matches m ON m.product_id = s.product_id AND m.site = s.site AND m.url = s.url AND m.status = 'matched'
                           WHERE s.ok AND s.price IS NOT NULL)
                SELECT a.product_id, a.site, a.fetched_at, a.price AS now_price, b.price AS before_price, b.fetched_at AS before_at
                FROM s a JOIN s b ON b.product_id = a.product_id AND b.site = a.site AND b.n = 2 WHERE a.n = 1 AND a.price <> b.price ORDER BY a.fetched_at DESC""")
    out = []
    for r in rows:
        p = names.get(r["product_id"]) or {}
        ch = ratio((r["now_price"] or 0) - (r["before_price"] or 0), r["before_price"]) if r["now_price"] and r["before_price"] else None
        out.append({**r, "name": p.get("name"), "brand": p.get("brand"), "site_label": P.LABEL[r["site"]], "change": ch, "our_price": p.get("price")})
    out.sort(key=lambda x: -abs(x["change"] or 0))
    return out[:limit]


@app.get("/api/prices/history")
def prices_history(product_id: str):
    p = next((x for x in price_catalogue() if x["product_id"] == product_id), None)
    if not p:
        raise HTTPException(404, "unknown product")
    bad = {(s, u) for (pid, s), m in _matches().items() if pid == product_id for u in m["rejected"]}  # pages you (or a dead link) ruled out
    read = q("""SELECT s.run_id, r.started_at AS run_at, s.site, s.url, s.fetched_at, s.price FROM price_snapshots s LEFT JOIN price_runs r ON r.run_id = s.run_id
                WHERE s.product_id = ? AND s.ok AND s.price IS NOT NULL ORDER BY s.fetched_at""", [product_id])
    points = [{"run": r["run_id"], "run_at": r["run_at"] or r["fetched_at"], "site": r["site"], "day": str(r["fetched_at"])[:10], "at": r["fetched_at"], "price": r["price"]}
              for r in read if (r["site"], r["url"]) not in bad]  # one point per reading; the graph draws one step per refresh
    own = q("""SELECT o.run_id AS run, coalesce(r.started_at, o.fetched_at) AS run_at, o.fetched_at AS at, o.price FROM price_own o LEFT JOIN price_runs r ON r.run_id = o.run_id
               WHERE o.product_id = ? ORDER BY o.fetched_at""", [product_id]) if _have("price_own") else []
    return {"product": p, "points": points, "own": own}

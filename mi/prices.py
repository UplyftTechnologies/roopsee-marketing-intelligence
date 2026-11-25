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
The comparison uses the REGULAR competitor price (Nykaa's offer price for some customers is a note only) and the latest reading of each product.
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

from . import core, price_sites as P
from .core import app, one, q, ratio
from .db import DB_LOCK

INDEX_MAX_AGE = timedelta(days=7)      # sitemaps are re-read once a week
RETRY_NONE_AFTER = timedelta(days=7)   # a product not found on a site is looked for again after a week (or when you ask)
MAX_BLOCKS = 4                          # refusals in a row before a site is stopped for this run
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
"""

PRICE_JOB = {"running": False, "run_id": None, "started": None, "finished": None, "stop": False, "sites": {}, "error": None, "message": ""}
_LOCK = threading.Lock()


def price_init(con) -> None:
    con.execute(DDL)
    con.execute("UPDATE price_runs SET status = 'stopped', message = 'the dashboard was closed during the run' WHERE status = 'running'")


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
    cols = ["url", "status", "method", "confidence", "matched_name", "candidates", "rejected"]
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
    k = P.brand_key(brand)
    if k not in cache:
        cache[k] = q("SELECT url, words FROM price_index WHERE site = ? AND replace(words, ' ', '') LIKE ?", [site, f"%{k}%"]) if k else []
    return cache[k]


def _candidates(p: dict, pages: list[dict], rejected: list) -> list[dict]:
    """The best few pages on a site for one of our products: same brand, size not different, ranked by name score."""
    ours = _our_sizes(p)
    out = []
    for r in pages:
        if r["url"] in rejected:
            continue
        sv = P.size_verdict(ours, P.sizes_in(r["words"]))
        if sv == "different":
            continue
        sc = P.score(p["name"], p.get("brand"), r["words"])
        if sc >= REVIEW:
            out.append({"url": r["url"], "words": r["words"], "score": sc, "size": sv})
    out.sort(key=lambda c: (-c["score"], c["size"] != "same", len(c["words"])))
    return out[:5]


# ---------------------------------------------------------------- one site, one run
def _snapshot(run_id, pid, site, url, got=None, err=None) -> None:
    g = got or {}
    _x("""INSERT INTO price_snapshots VALUES (?, ?, ?, ?, now(), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
       [run_id, pid, site, url, err is None, err, g.get("price"), g.get("mrp"), g.get("offer_price"), g.get("in_stock"),
        int(g["stock_qty"]) if str(g.get("stock_qty") or "").isdigit() else None, g.get("discount"), g.get("name"), g.get("size")])


def _run_site(site: str, run_id: int, products: list[dict], only: set | None) -> None:
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
            return None, f"page no longer exists ({e})"
        except Exception as e:  # layout changed, network ... recorded with the reason, the run goes on
            return None, str(e)[:200]

    # 1. products that still need a page on this site
    todo = [p for p in products if (only is None or p["product_id"] in only)]
    need = []
    for p in todo:
        m = have.get((p["product_id"], site))
        if m is None or (m["status"] == "none" and (not m["checked_at"] or datetime.now() - m["checked_at"] > RETRY_NONE_AFTER)):
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

    # 2. read every matched page that was not read in step 1
    done_now = {r["product_id"] for r in q("SELECT product_id FROM price_snapshots WHERE run_id = ? AND site = ?", [run_id, site])}
    byid = {p["product_id"]: p for p in products}
    pages = [(pid, m) for (pid, s), m in _matches().items() if s == site and m["status"] == "matched" and m["url"] and pid not in done_now
             and pid in byid and (only is None or pid in only)]
    status(phase="reading prices", total=len(pages), done=0)
    for i, (pid, m) in enumerate(pages, 1):
        if stop():
            return
        url = m["url"]
        got, err = visit(url)
        if got is not None:
            got, size_problem = P.fit_size(got, _our_sizes(byid[pid]))  # the price of OUR size, never another size's
            if size_problem and m["method"] != "you":  # e.g. a sheet link to a page that only sells 59 / 118 ml when ours is 125 ml: ask, do not compare
                err = f"not our size ({size_problem}; ours {byid[pid].get('size')})"
                _save_match(pid, site, url=None, status="review", method=m["method"], confidence=m["confidence"], matched_name=None,
                            candidates=[{"url": url, "score": m["confidence"], "size": "different", "page_size": "different", "page_name": got.get("name"),
                                         "price": got.get("price"), "in_stock": got.get("in_stock"), "note": size_problem}], rejected=m.get("rejected") or [])
                got = None
        _snapshot(run_id, pid, site, url, got, err)
        status(done=i, ok=st.get("ok", 0) + (err is None), failed=st.get("failed", 0) + (err is not None))


def _run(run_id: int, sites: list[str], only: set | None) -> None:
    products = price_catalogue()
    _seed_from_sheet(products, _matches())

    def one_site(site):
        try:
            _run_site(site, run_id, products, only)
            PRICE_JOB["sites"][site]["phase"] = "stopped" if PRICE_JOB["stop"] else "done"
        except P.Blocked as e:
            PRICE_JOB["sites"][site].update(phase="stopped", error=f"{P.LABEL[site]} kept refusing our requests ({e}); try again later")
        except Exception as e:
            PRICE_JOB["sites"][site].update(phase="failed", error=f"{type(e).__name__}: {str(e)[:200]}")

    try:
        with ThreadPoolExecutor(len(sites)) as ex:
            list(ex.map(one_site, sites))
        summary = one("""SELECT count(*) AS pages, count(*) FILTER (WHERE ok) AS ok, count(*) FILTER (WHERE NOT ok) AS failed FROM price_snapshots WHERE run_id = ?""", [run_id])
        errs = [v["error"] for v in PRICE_JOB["sites"].values() if v.get("error")]
        final = "stopped" if PRICE_JOB["stop"] else ("done with problems" if errs else "done")
        _x("UPDATE price_runs SET finished_at = now(), status = ?, summary = ?, message = ? WHERE run_id = ?",
           [final, json.dumps({**summary, "sites": PRICE_JOB["sites"]}, default=str), "; ".join(errs)[:500] or None, run_id])
    except Exception as e:
        PRICE_JOB["error"] = f"{type(e).__name__}: {e}"
        _x("UPDATE price_runs SET finished_at = now(), status = 'failed', message = ? WHERE run_id = ?", [PRICE_JOB["error"][:500], run_id])
    finally:
        PRICE_JOB.update(running=False, finished=datetime.now().isoformat(timespec="seconds"))


def start_price_run(sites=None, only: set | None = None, wait: bool = False) -> dict:
    """Start a Refresh prices run in the background (wait=True runs it here, for the command line)."""
    sites = [s for s in (sites or P.SITES) if s in P.SITES]
    with _LOCK:
        if PRICE_JOB["running"]:
            raise HTTPException(409, "Prices are already being refreshed")
        price_catalogue()  # fails early (409) when the sheet must be pulled again
        with DB_LOCK:
            run_id = core.CON.cursor().execute("INSERT INTO price_runs (started_at, status, sites) VALUES (now(), 'running', ?) RETURNING run_id", [",".join(sites)]).fetchone()[0]
        PRICE_JOB.update(running=True, run_id=run_id, started=datetime.now().isoformat(timespec="seconds"), finished=None, stop=False, error=None,
                   sites={s: {"phase": "starting", "done": 0, "total": 0, "ok": 0, "failed": 0, "error": None} for s in sites})
    if wait:
        _run(run_id, sites, only)
    else:
        threading.Thread(target=_run, args=(run_id, sites, only), daemon=True).start()
    return PRICE_JOB


# ---------------------------------------------------------------- API: run control
@app.post("/api/prices/refresh")
def prices_refresh(site: str | None = None):
    return start_price_run([site] if site else None)


@app.post("/api/prices/stop")
def prices_stop():
    if PRICE_JOB["running"]:
        PRICE_JOB["stop"] = True
    return PRICE_JOB


@app.get("/api/prices/status")
def prices_status():
    last = one("SELECT * FROM price_runs WHERE status <> 'running' ORDER BY run_id DESC LIMIT 1") if _have("price_runs") else {}
    counts = {r["site"]: r for r in q("""SELECT site, count(*) FILTER (WHERE status = 'matched') AS matched, count(*) FILTER (WHERE status = 'review') AS review,
                                         count(*) FILTER (WHERE status IN ('none', 'rejected')) AS not_found FROM price_matches GROUP BY 1""")} if _have("price_matches") else {}
    try:
        n, need_pull = len(price_catalogue()), False
    except HTTPException:
        n, need_pull = 0, True
    return {"job": PRICE_JOB, "last_run": last or None, "products": n, "needs_pull": need_pull, "sites": {s: {"label": P.LABEL[s], **counts.get(s, {"matched": 0, "review": 0, "not_found": 0})} for s in P.SITES}}


@app.get("/api/prices/runs")
def prices_runs(limit: int = 20):
    rows = q("SELECT run_id, started_at, finished_at, status, sites, summary, message FROM price_runs ORDER BY run_id DESC LIMIT ?", [max(1, min(limit, 200))])
    for r in rows:
        r["summary"] = json.loads(r["summary"]) if isinstance(r["summary"], str) else r["summary"]
    errors = q("""SELECT site, error, count(*) AS n, any_value(url) AS example FROM price_snapshots WHERE NOT ok AND run_id = (SELECT max(run_id) FROM price_snapshots)
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
                    "url": m["url"], "method": m["method"], "confidence": m["confidence"], "matched_name": m["matched_name"], "candidates": m["candidates"]})
    return {"rows": out}


class MatchIn(BaseModel):
    product_id: str
    site: str
    action: str             # confirm | reject | link | clear
    url: str | None = None  # for confirm (a candidate) or link (pasted)


@app.post("/api/prices/match")
def prices_match(body: MatchIn):
    """Your decision on a match; it is kept and never guessed again. A confirmed or pasted link is read at the next Refresh prices."""
    if body.site not in P.SITES:
        raise HTTPException(400, f"site must be one of {list(P.SITES)}")
    if body.product_id not in {p["product_id"] for p in price_catalogue()}:
        raise HTTPException(404, "unknown product")
    m = _matches().get((body.product_id, body.site)) or {"candidates": [], "rejected": []}
    if body.action in ("confirm", "link"):
        u = P.canonical_url(body.url)
        if not u or P.site_of(u) != body.site:
            raise HTTPException(400, f"paste a {P.LABEL[body.site]} product link (https://{P.HOSTS[body.site][0]}/...)")
        _save_match(body.product_id, body.site, url=u, status="matched", method="you", confidence=1.0, matched_name=next((c.get("page_name") for c in m["candidates"] if c.get("url") == u), None),
                    candidates=m["candidates"], rejected=[x for x in m["rejected"] if x != u])
    elif body.action == "reject":  # this page is not our product: never propose it again
        bad = body.url or m.get("url")
        _save_match(body.product_id, body.site, url=None, status="rejected", method="you", confidence=0, matched_name=None,
                    candidates=[c for c in m["candidates"] if c.get("url") != bad], rejected=sorted(set(m["rejected"]) | ({bad} if bad else set())))
    elif body.action == "clear":  # forget the match: it is looked for again at the next refresh
        _x("DELETE FROM price_matches WHERE product_id = ? AND site = ?", [body.product_id, body.site])
    else:
        raise HTTPException(400, "action must be confirm, reject, link or clear")
    return {"ok": True}


# ---------------------------------------------------------------- comparison and analysis
LATEST = """
WITH m AS (SELECT * FROM price_matches WHERE status = 'matched'),
s AS (SELECT * FROM price_snapshots WHERE ok QUALIFY row_number() OVER (PARTITION BY product_id, site ORDER BY fetched_at DESC) = 1)
SELECT m.product_id, m.site, m.url, m.method, s.fetched_at, s.price, s.mrp, s.offer_price, s.in_stock, s.stock_qty, s.discount, s.page_name
FROM m LEFT JOIN s ON s.product_id = m.product_id AND s.site = m.site AND s.url = m.url
"""


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
    out = []
    for p in prods:
        ours, mrp = p["price"], p["mrp"]
        sites = {}
        for s in P.SITES:
            r = (latest.get(p["product_id"]) or {}).get(s)
            if not r:
                continue
            sites[s] = {"url": r["url"], "method": r["method"], "price": r["price"], "mrp": r["mrp"], "offer_price": r["offer_price"], "in_stock": r["in_stock"],
                        "stock_qty": r["stock_qty"], "discount_text": r["discount"], "checked": r["fetched_at"],
                        "discount": round(1 - r["price"] / r["mrp"], 4) if r["price"] and r["mrp"] else None,
                        "gap": round(ours / r["price"] - 1, 4) if ours and r["price"] and r["in_stock"] else None}
        live = {s: v["price"] for s, v in sites.items() if v["price"] and v["in_stock"]}
        cheapest = min(live, key=live.get) if live else None
        gap = round(ours / live[cheapest] - 1, 4) if ours and cheapest else None
        out.append({**{k: p[k] for k in ("product_id", "name", "brand", "category", "type", "size", "image")}, "our_price": ours, "our_mrp": mrp,
                    "our_discount": round(1 - ours / mrp, 4) if ours and mrp else None, "sites": sites, "cheapest_site": cheapest,
                    "cheapest_price": live.get(cheapest) if cheapest else None, "gap": gap, "position": _position(gap),
                    "saving_needed": round(ours - live[cheapest], 2) if cheapest and gap and gap > 0 else 0,
                    "out_of_stock_at": [s for s, v in sites.items() if v["in_stock"] is False], **dem.get(p["product_id"], {"views": 0, "carts": 0, "orders": 0, "units": 0, "revenue": 0.0})})
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
        have = [r for r in rows if s in r["sites"]]
        gaps = [r["sites"][s]["gap"] for r in have if r["sites"][s]["gap"] is not None]
        disc = [(r["sites"][s]["discount"], r["our_discount"]) for r in have if r["sites"][s]["discount"] is not None and r["our_discount"] is not None]
        per_site.append({"site": s, "label": P.LABEL[s], "matched": len(have), "priced": sum(1 for r in have if r["sites"][s]["price"]),
                         "in_stock": sum(1 for r in have if r["sites"][s]["in_stock"]), "out_of_stock": sum(1 for r in have if r["sites"][s]["in_stock"] is False),
                         "median_gap": _med(gaps), "we_dearer": sum(1 for g in gaps if g > 0.01), "we_cheaper": sum(1 for g in gaps if g < -0.01),
                         "their_discount": _med([a for a, _ in disc]), "our_discount": _med([b for _, b in disc]), "with_offer": sum(1 for r in have if r["sites"][s]["offer_price"])})

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
    oos = sorted([r for r in rows if r["out_of_stock_at"]], key=lambda r: (-r["revenue"], -r["views"], -len(r["out_of_stock_at"])))[:25]
    return {"kpis": k, "sites": per_site, "by_brand": group("brand")[:40], "by_category": group("category"), "cart_rate": cart_rate,
            "at_risk": [_lite(r) for r in at_risk], "price_sensitive": [{**_lite(r), "cart_rate": ratio(r["carts"], r["views"])} for r in sensitive],
            "out_of_stock_elsewhere": [_lite(r) for r in oos], "changes": _changes()}


def _lite(r: dict) -> dict:
    return {k: r[k] for k in ("product_id", "name", "brand", "size", "our_price", "cheapest_site", "cheapest_price", "gap", "saving_needed", "views", "carts", "orders",
                              "revenue", "out_of_stock_at", "position")}


def _changes(limit: int = 40) -> list[dict]:
    """Price and stock changes between each product's last two readings on a site."""
    if not _have("price_snapshots"):
        return []
    names = {p["product_id"]: p for p in price_catalogue()}
    rows = q("""WITH s AS (SELECT product_id, site, fetched_at, price, in_stock, row_number() OVER (PARTITION BY product_id, site ORDER BY fetched_at DESC) AS n
                           FROM price_snapshots WHERE ok)
                SELECT a.product_id, a.site, a.fetched_at, a.price AS now_price, b.price AS before_price, a.in_stock AS now_stock, b.in_stock AS before_stock, b.fetched_at AS before_at
                FROM s a JOIN s b ON b.product_id = a.product_id AND b.site = a.site AND b.n = 2 WHERE a.n = 1
                AND (a.price IS DISTINCT FROM b.price OR a.in_stock IS DISTINCT FROM b.in_stock) ORDER BY a.fetched_at DESC""")
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
    rows = q("""SELECT site, fetched_at::DATE AS day, max(fetched_at) AS at, arg_max(price, fetched_at) AS price, arg_max(in_stock, fetched_at) AS in_stock
                FROM price_snapshots WHERE product_id = ? AND ok GROUP BY 1, 2 ORDER BY 2""", [product_id])
    return {"product": p, "points": rows}

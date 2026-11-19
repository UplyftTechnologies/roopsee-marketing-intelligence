"""Extract: read-only REST pulls from production Supabase into local DuckDB raw_* tables.

event_log (570k+ rows) is pulled in parallel one-day windows ordered by created_at, and is incremental:
re-runs only fetch from (latest stored event - 1h). Inserts are idempotent (primary key on id).
Small tables are replaced in full on each run.
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import pandas as pd

from .db import DB_LOCK, RAW_SCHEMAS, connect, log_run
from .supa import ReadOnlySupabase

IST_TZ = timezone(timedelta(hours=5, minutes=30))
PAGE = 1000
WORKERS = 6
OVERLAP_H = 24

SMALL_TABLES = {  # raw table -> (supabase table, columns to select)
    "raw_users": ("users", None),
    "raw_orders": ("orders", None),
    "raw_quiz_results": ("quiz_results", None),
    "raw_visitor_links": ("visitor_identity_links", None),
    "raw_customer_address": ("customer_address", None),
    "raw_catalog_roopsee": ("roopsee_products", None),
    # master catalog has columns like "Product-id" / "Product Name": alias them to snake_case in the request
    "raw_catalog_master": ("master_products",
                           'product_id:"Product-id",product_name:"Product Name",brand:Brand,category_l1:"Category L1",'
                           'category_l2:"Category L2",mrp:MRP,selling_price:"Selling Price"'),
}


def _log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def _frame(rows: list[dict], schema: dict) -> pd.DataFrame:
    cols = [c for c in schema]
    df = pd.DataFrame(rows, columns=cols)
    for c, d in schema.items():
        if d.startswith("JSON"):
            df[c] = df[c].map(lambda v: None if v is None else json.dumps(v, ensure_ascii=False))
        elif d.startswith(("DOUBLE", "INTEGER", "BIGINT")):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _insert(con, table: str, df: pd.DataFrame, ignore: bool) -> None:
    if df.empty:
        return
    schema = RAW_SCHEMAS[table]
    sel = ", ".join(f"CAST({c} AS {d.split(' PRIMARY')[0]}) AS {c}" for c, d in schema.items())
    with DB_LOCK:
        con.register("_df", df)
        try:
            con.execute(f"INSERT {'OR IGNORE ' if ignore else ''}INTO {table} SELECT {sel} FROM _df").fetchall()
        finally:
            con.unregister("_df")


def _fetch_window(start: datetime, end: datetime) -> list[dict]:
    """All event_log rows with start <= created_at < end, paged by created_at (dupes removed at insert)."""
    sb = ReadOnlySupabase()
    out, cursor = [], start
    while True:
        params = {
            "select": "*",
            "and": f"(created_at.gte.{cursor.isoformat()},created_at.lt.{end.isoformat()})",
            "order": "created_at.asc,id.asc",
            "limit": PAGE,
        }
        rows = sb.select("event_log", params)
        out.extend(rows)
        if len(rows) < PAGE:
            return out
        last = datetime.fromisoformat(rows[-1]["created_at"])
        first = datetime.fromisoformat(rows[0]["created_at"])
        cursor = last if last > first else last + timedelta(microseconds=1)


def extract_events(con) -> int:
    t_start = datetime.now()
    sb = ReadOnlySupabase()
    mx = con.execute("SELECT max(created_at) FROM raw_event_log").fetchall()[0][0]
    if mx is None:
        first = sb.select("event_log", {"select": "created_at", "order": "created_at.asc", "limit": 1})
        start = datetime.fromisoformat(first[0]["created_at"]).astimezone(IST_TZ)
        _log(f"event_log backfill from {start:%Y-%m-%d}")
    else:
        start = mx.astimezone(IST_TZ) - timedelta(hours=OVERLAP_H)  # re-read the last day: inserts are idempotent, so late-arriving rows are caught
        _log(f"event_log incremental from {start:%Y-%m-%d %H:%M}")
    now = datetime.now(IST_TZ) + timedelta(hours=1)
    day0 = start.replace(hour=0, minute=0, second=0, microsecond=0)
    windows = []
    d = day0
    while d < now:
        windows.append((max(d, start), d + timedelta(days=1)))
        d += timedelta(days=1)

    total, done = 0, 0
    with ThreadPoolExecutor(WORKERS) as ex:
        futs = {ex.submit(_fetch_window, a, b): (a, b) for a, b in windows}
        for f in as_completed(futs):
            rows = f.result()
            _insert(con, "raw_event_log", _frame(rows, RAW_SCHEMAS["raw_event_log"]), ignore=True)
            total += len(rows)
            done += 1
            if done % 5 == 0 or done == len(windows):
                _log(f"  windows {done}/{len(windows)}  rows fetched {total:,}")
    n = con.execute("SELECT count(*) FROM raw_event_log").fetchall()[0][0]
    _log(f"raw_event_log now {n:,} rows")
    log_run(con, "extract:event_log", t_start, n, f"{total:,} rows fetched")
    return n


def extract_small(con) -> None:
    sb = ReadOnlySupabase()
    for raw, (src, select_override) in SMALL_TABLES.items():
        schema = RAW_SCHEMAS[raw]
        rows, off = [], 0
        while True:
            params = {"select": select_override or ",".join(schema), "limit": PAGE, "offset": off}
            if "id" in schema:  # stable paging
                params["order"] = "id.asc"
            page = sb.select(src, params)
            rows.extend(page)
            if len(page) < PAGE:
                break
            off += PAGE
        t_start = datetime.now()
        prev = con.execute(f"SELECT count(*) FROM {raw}").fetchall()[0][0]
        if prev >= 20 and len(rows) < prev * 0.5:  # a pull that suddenly returns far fewer rows is a failed pull, not a real change
            _log(f"{raw}: SKIPPED, source returned {len(rows):,} rows but {prev:,} are stored")
            log_run(con, f"extract:{raw}", t_start, prev, f"skipped: source returned {len(rows)} rows, {prev} stored")
            continue
        con.execute("BEGIN TRANSACTION")  # replace atomically: a failure half-way can never leave the table empty
        try:
            con.execute(f"DELETE FROM {raw}").fetchall()
            _insert(con, raw, _frame(rows, schema), ignore=False)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        _log(f"{raw}: {len(rows):,} rows")
        log_run(con, f"extract:{raw}", t_start, len(rows))


def run(con=None, small_only: bool = False) -> None:
    own = con is None
    con = con or connect()
    try:
        extract_small(con)
        if not small_only:
            extract_events(con)
    finally:
        if own:
            con.close()


if __name__ == "__main__":
    run(small_only="--small" in sys.argv)

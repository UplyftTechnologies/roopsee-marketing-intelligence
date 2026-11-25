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

from . import payload
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
    "raw_chat_logs": ("assistant_chat_logs", None),  # optional: a key without access to it must not stop the refresh
    # master catalog has columns like "Product-id" / "Product Name": alias them to snake_case in the request
    "raw_catalog_master": ("master_products",
                           'product_id:"Product-id",product_name:"Product Name",brand:Brand,category_l1:"Category L1",'
                           'category_l2:"Category L2",mrp:MRP,selling_price:"Selling Price",sku_size:"SKU Size",product_link:"Product Link",'
                           'bar_code,images:Images'),  # size / link / barcode feed the Price intelligence tab; the sheet's hand-typed competitor prices are not pulled
}


def _log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def _frame(rows: list[dict], schema: dict) -> pd.DataFrame:
    cols = [c for c in schema]
    df = pd.DataFrame(rows, columns=cols)
    for c, d in schema.items():
        if d.startswith("JSON"):
            keep = payload.slim if c == "extra_data" else (lambda v: v)  # event payloads are stored without their plumbing fields
            df[c] = df[c].map(lambda v: None if v is None else json.dumps(keep(v), ensure_ascii=False))
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
            con.execute(f"INSERT {'OR IGNORE ' if ignore else ''}INTO {table} ({', '.join(schema)}) SELECT {sel} FROM _df").fetchall()  # named columns: an extra column in the stored table never breaks a pull
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


def extract_events(con, progress=None) -> int:
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
            if progress:
                progress(f"pulling events: day {done} of {len(windows)}, {total:,} rows")
    n = con.execute("SELECT count(*) FROM raw_event_log").fetchall()[0][0]
    _log(f"raw_event_log now {n:,} rows")
    log_run(con, "extract:event_log", t_start, n, f"{total:,} rows fetched")
    return n


OPTIONAL = {"raw_chat_logs"}


def extract_small(con, progress=None) -> None:
    sb = ReadOnlySupabase()
    for raw, (src, select_override) in SMALL_TABLES.items():
        schema = RAW_SCHEMAS[raw]
        if progress:
            progress(f"pulling {src}")
        rows, off = [], 0
        t_start = datetime.now()
        try:
            while True:
                params = {"select": select_override or ",".join(schema), "limit": PAGE, "offset": off}
                if "id" in schema:  # stable paging
                    params["order"] = "id.asc"
                page = sb.select(src, params)
                rows.extend(page)
                if len(page) < PAGE:
                    break
                off += PAGE
        except Exception as e:
            if raw not in OPTIONAL:
                raise
            _log(f"{raw}: SKIPPED, could not read {src}: {str(e)[:120]}")
            log_run(con, f"extract:{raw}", t_start, None, f"skipped: could not read {src} ({str(e)[:100]})")
            continue
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


def slim_stored_payloads(con) -> None:
    """One-off for events stored before payloads were slimmed: drop the plumbing fields in place (the file is compacted afterwards)."""
    from . import config
    path = config.DB_PATH
    before = path.stat().st_size
    n = con.execute("SELECT count(*) FROM raw_event_log").fetchone()[0]
    top = json.dumps({k: None for k in sorted(payload.REMOVE)})
    both = json.dumps({**{k: None for k in sorted(payload.REMOVE)}, "rawBody": {k: None for k in sorted(payload.REMOVE)}})
    t = time.time()
    print(f"Trimming {n:,} stored event payloads (a null in a JSON merge patch removes the field)...")
    con.execute("""UPDATE raw_event_log SET extra_data = CASE WHEN json_exists(extra_data, '$.rawBody')
                   THEN json_merge_patch(extra_data, ?::JSON) ELSE json_merge_patch(extra_data, ?::JSON) END WHERE extra_data IS NOT NULL""", [both, top])
    con.execute("CHECKPOINT")
    print(f"  done in {time.time() - t:.0f}s. File size is still {before / 1e6:,.0f} MB until it is compacted (next step).")
    con.close()
    compact_database(path)


def compact_database(path) -> None:
    """Copy the database into a fresh file so the space freed by deleted or trimmed data is really given back."""
    import os

    import duckdb
    tmp = path.with_suffix(".compact.duckdb")
    if tmp.exists():
        tmp.unlink()
    before = path.stat().st_size
    con = duckdb.connect(str(path))
    name = con.execute("SELECT current_database()").fetchone()[0]  # the catalog is named after the file
    con.execute(f"ATTACH '{tmp.as_posix()}' AS compact")
    con.execute(f'COPY FROM DATABASE "{name}" TO compact')
    con.execute("DETACH compact")
    con.close()
    for ext in (".wal",):
        w = path.with_name(path.name + ext)
        if w.exists():
            w.unlink()
    os.replace(tmp, path)
    after = path.stat().st_size
    print(f"Compacted {path.name}: {before / 1e6:,.0f} MB -> {after / 1e6:,.0f} MB")


def purge_old_events(con, days: int, execute: bool) -> None:
    """Retention: remove raw events older than `days` days (a dry run unless execute). Rebuild afterwards (Refresh)."""
    cutoff = f"now() - INTERVAL {int(days)} DAY"
    old = con.execute(f"SELECT count(*), min(created_at), max(created_at) FROM raw_event_log WHERE created_at < {cutoff}").fetchall()[0]
    total = con.execute("SELECT count(*) FROM raw_event_log").fetchone()[0]
    print(f"{old[0]:,} of {total:,} stored events are older than {days} days" + (f" (from {old[1]:%d %b %Y} to {old[2]:%d %b %Y})." if old[0] else "."))
    if not old[0]:
        return
    if not execute:
        print("Dry run: nothing was deleted. Add --yes to delete them. The dashboard's history before that date will disappear after the next rebuild.")
        return
    con.execute(f"DELETE FROM raw_event_log WHERE created_at < {cutoff}")
    con.execute("CHECKPOINT")
    print("Deleted. Press Refresh to rebuild the tables, and run `python -m mi.cli compact` to shrink the file.")


def run(con=None, small_only: bool = False, progress=None) -> None:
    own = con is None
    con = con or connect()
    try:
        extract_small(con, progress)
        if not small_only:
            extract_events(con, progress)
    finally:
        if own:
            con.close()


if __name__ == "__main__":
    run(small_only="--small" in sys.argv)

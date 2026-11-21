"""CLI:  python -m mi.cli {extract|transform|all|serve|access|slim}

extract    pull new data from production Supabase (read-only GETs) into data/mi.duckdb
transform  rebuild all analytics tables (also re-applies the exclusion list)
all        extract + transform
serve      start the API + dashboard on http://127.0.0.1:8000  (build the UI first: cd dashboard && npm run build)
access     say which Supabase key is in use and what it can do (never prints the key, never contacts production)
slim       one-off: remove duplicated fields and tracking plumbing from stored event payloads, then shrink the file (stop the dashboard first)
compact    shrink the database file after deleting data (stop the dashboard first)
purge      python -m mi.cli purge 365 [--yes]   delete raw events older than N days (dry run unless --yes)

NOTE: DuckDB allows a single writer. Stop `serve` before running extract/transform from the CLI,
or just use the "Refresh data" button in the dashboard, which runs the same code inside the server.
"""
import base64
import json
import sys
from datetime import datetime, timezone

from . import config, extract, transform
from .db import connect


def access_report() -> int:
    """Which key is configured and what role it carries (read from the key itself; no network call)."""
    env = config.load_env()
    names = ("PRODUCT_SUPABASE_READ_KEY", "PRODUCT_SUPABASE_ANON_KEY", "PRODUCT_SUPABASE_SERVICE_KEY")
    name = next((n for n in names if env.get(n)), None)
    if not name:
        print("No production key found in .env. Add PRODUCT_SUPABASE_READ_KEY (see docs/read-only-access.md).")
        return 1
    key = env[name]
    print(f"Using {name} (set in .env; the value is not shown)")
    role = exp = None
    if key.count(".") == 2:
        try:
            body = key.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
            role, exp = claims.get("role"), claims.get("exp")
        except Exception:
            pass
    elif key.startswith("sb_secret_"):
        role = "service_role"
    elif key.startswith("sb_publishable_"):
        role = "anon"
    print(f"  role: {role or 'unknown'}")
    if exp:
        left = (datetime.fromtimestamp(exp, timezone.utc) - datetime.now(timezone.utc)).days
        print(f"  expires: in {left} days" if left >= 0 else "  expires: ALREADY EXPIRED")
    if role == "service_role":
        print("  WARNING: this is the full-access key. It can read, change and delete everything in production.")
        print("  Create a read-only key instead: docs/read-only-access.md")
        return 0
    if role == "anon":
        print("  This is the public key. It only works if Row Level Security lets anonymous users read the data tables, which also lets anyone read them.")
        return 0
    print("  Looks like a restricted key. Press Refresh in the dashboard to confirm every table can be read.")
    return 0


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "all"
    if cmd == "serve":
        import os

        import uvicorn
        uvicorn.run("mi.api:app", host="127.0.0.1", port=int(os.environ.get("MI_PORT", "8000")))
        return 0
    if cmd == "access":
        return access_report()
    if cmd == "slim":
        extract.slim_stored_payloads(connect())  # closes the connection itself, then compacts the file
        return 0
    if cmd == "compact":
        extract.compact_database(config.DB_PATH)
        return 0
    if cmd == "purge":
        days = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else None
        if days is None:
            print("Usage: python -m mi.cli purge <days> [--yes]")
            return 2
        con = connect()
        try:
            extract.purge_old_events(con, days, "--yes" in argv)
        finally:
            con.close()
        return 0
    if cmd not in ("extract", "transform", "all"):
        print(__doc__)
        return 2
    con = connect()
    try:
        if cmd in ("extract", "all"):
            extract.run(con)
        if cmd in ("transform", "all"):
            transform.run(con)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

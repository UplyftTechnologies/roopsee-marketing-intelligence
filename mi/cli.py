"""CLI:  python -m mi.cli {extract|transform|all|serve}

extract    pull new data from production Supabase (read-only GETs) into data/mi.duckdb
transform  rebuild all analytics tables (also re-applies the exclusion list)
all        extract + transform
serve      start the API + dashboard on http://127.0.0.1:8000  (build the UI first: cd dashboard && npm run build)

NOTE: DuckDB allows a single writer. Stop `serve` before running extract/transform from the CLI,
or just use the "Refresh data" button in the dashboard, which runs the same code inside the server.
"""
import sys

from . import extract, transform
from .db import connect


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "all"
    if cmd == "serve":
        import uvicorn
        uvicorn.run("mi.api:app", host="127.0.0.1", port=8000)
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

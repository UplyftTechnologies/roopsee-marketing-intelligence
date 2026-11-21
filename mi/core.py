"""Shared by every part of the API: the app, the database helpers and the small helpers every report uses."""
import contextvars
import re
import threading
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from . import transform
from .db import DB_LOCK, connect


CON = None


PENDING = {"reapply": False}


JOB = {"running": False, "name": None, "started": None, "finished": None, "message": "", "error": None}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global CON
    CON = connect()
    with DB_LOCK:
        transform.seed_exclusions(CON)
    yield
    CON.close()


app = FastAPI(title="Roopsee Marketing Intelligence", lifespan=lifespan)


app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------- device filter (Mobile web / Desktop web / Tablet web / App)
# A request can carry ?device_type=App,Mobile web ... The middleware below remembers it for the request and q() narrows the three
# visit-level tables (sessions, events_clean, orders_clean) to those devices, so every page built on them follows the filter without each
# query having to know about it. Pages built on person-level or campaign-level tables (users_360, campaign_performance) are not narrowed.
DEVICE_TYPES = ("Mobile web", "Desktop web", "Tablet web", "App", "Unknown")
DEVICE: contextvars.ContextVar = contextvars.ContextVar("device_type", default=None)
DEVICE_SKIP = ("/api/meta", "/api/health", "/api/jobs", "/api/refresh", "/api/exclusions", "/api/lookup", "/api/performance", "/api/users", "/api/cohorts",
               "/api/retention", "/api/loyalty", "/api/audiences", "/api/person", "/api/campaigns", "/api/utm-health", "/api/events/names", "/api/events/catalogue")
# the columns that say app / device in each table
_DEV_COLS = {"sessions": ("is_app", "device"), "events_clean": ("is_app", "device_n"), "orders_clean": ("is_app", "device")}
_TABLE_RE = re.compile(r"\b(FROM|JOIN)(\s+)(sessions|events_clean|orders_clean)(?![\w])", re.I)


def device_expr(app_col: str, dev_col: str) -> str:
    return (f"CASE WHEN coalesce({app_col}, false) THEN 'App' WHEN {dev_col} = 'Mobile' THEN 'Mobile web' WHEN {dev_col} = 'Desktop' THEN 'Desktop web' "
            f"WHEN {dev_col} = 'Tablet' THEN 'Tablet web' ELSE 'Unknown' END")


def parse_devices(v: str | None) -> tuple | None:
    got = tuple(x for x in (t.strip() for t in (v or "").split(",")) if x in DEVICE_TYPES)
    return got or None


def narrow(sql: str, devices: tuple | None) -> str:
    """The query with sessions / events_clean / orders_clean replaced by those tables limited to the devices."""
    if not devices:
        return sql
    inlist = ", ".join("'" + d + "'" for d in devices)  # values come from DEVICE_TYPES only

    def sub(m):
        t = m.group(3).lower()
        a, d = _DEV_COLS[t]
        return f"{m.group(1)}{m.group(2)}(SELECT * FROM {t} WHERE {device_expr(a, d)} IN ({inlist}))"
    return _TABLE_RE.sub(sub, sql)


@app.middleware("http")
async def _device_filter(request: Request, call_next):
    path = request.url.path
    devices = parse_devices(request.query_params.get("device_type")) if path.startswith("/api/") and not path.startswith(DEVICE_SKIP) else None
    token = DEVICE.set(devices)
    try:
        return await call_next(request)
    finally:
        DEVICE.reset(token)


def q(sql: str, args: list | tuple = ()) -> list[dict]:
    sql = narrow(sql, DEVICE.get())
    with DB_LOCK:
        cur = CON.cursor()
        try:
            cur.execute("SET TimeZone='Asia/Kolkata'")
            cur.execute(sql, list(args))
            if cur.description is None:
                return []
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
        finally:
            cur.close()


def one(sql: str, args=()) -> dict:
    r = q(sql, args)
    return r[0] if r else {}


def has_tables() -> bool:
    return bool(q("SELECT 1 FROM information_schema.tables WHERE table_name='sessions'"))


def sess_where(d_from, d_to, include_excluded, a="s") -> tuple[str, list]:
    w = [f"{a}.date_ist BETWEEN ? AND ?"]
    args = [d_from or "2000-01-01", d_to or "2999-12-31"]
    if not include_excluded:
        w.append(f"NOT {a}.is_excluded")
    return " AND ".join(w), args


def ratio(a, b):
    return round(a / b, 4) if b else 0


def _run_job(name: str, fn):
    def target():
        JOB.update(running=True, name=name, started=datetime.now().isoformat(timespec="seconds"), finished=None, message="", error=None)
        try:
            fn()
            JOB["message"] = "done"
        except Exception as e:  # surfaced in the UI
            JOB["error"] = f"{type(e).__name__}: {e}"
        finally:
            JOB.update(running=False, finished=datetime.now().isoformat(timespec="seconds"))
            if PENDING["reapply"]:
                PENDING["reapply"] = False
                try:
                    _reapply()
                except Exception:  # never let a follow-up failure mask the first job's result
                    pass
    if JOB["running"]:
        raise HTTPException(409, f"A job is already running: {JOB['name']}")
    threading.Thread(target=target, daemon=True).start()


def prev_range(d_from, d_to):
    """The equally long period right before [d_from, d_to]; None for an open-ended range ("All time")."""
    if not d_from or not d_to:
        return None
    a, b = date.fromisoformat(d_from), date.fromisoformat(d_to)
    n = (b - a).days + 1
    pt = a - timedelta(days=1)
    return (pt - timedelta(days=n - 1)).isoformat(), pt.isoformat()


def _csv(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def _reapply():
    """Exclusion edits only need the flagging steps (about 3 s instead of 15 s). Edits made mid-job are queued."""
    if JOB["running"]:
        PENDING["reapply"] = True
        return
    _run_job("apply-exclusions", lambda: transform.run(CON.cursor(), flags_only=True))


def _in(col: str, values: list[str]) -> tuple[str, list]:
    return f"{col} IN ({', '.join('?' for _ in values)})", list(values)

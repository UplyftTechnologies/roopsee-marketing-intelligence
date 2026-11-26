"""Shared price data in Supabase, so several computers see the same prices and decisions. Database side: docs/price-sync.sql.

Supabase holds the true copy; this computer's database is a copy of it that the screens read. Sharing is ON when .env has PRICES_SUPABASE_KEY
(a key for the mi_price_writer role only: tools/make_price_key.py). Without it everything stays on this computer, as before.

  push()            send what is waiting here: readings, our own prices, matches
  pull()            fetch what other computers added or changed
  decide()          a person's decision: saved in Supabase first, refused if someone else changed that match meanwhile
  upload_history()  once, on request: what this computer collected before sharing was on

Nothing here can touch any table but mi_price_*: the key has no access to the others and writes only through the database's functions.

A row's `synced` says: NULL = collected while sharing was off (only upload_history sends it), FALSE = waiting to be sent, TRUE = in Supabase.
"""
import json
import socket
import threading
import uuid
from datetime import datetime, timedelta, timezone

import requests

from . import core
from .db import DB_LOCK

CLIENT = 1                     # raise it (with mi_price_meta.min_client) when the way of writing changes
IST = timezone(timedelta(hours=5, minutes=30))
PAGE = 1000
BATCH = 200
OVERLAP = timedelta(minutes=10)  # re-read a little before the last download: rows can arrive slightly out of order
IMPORTED = "uploaded from a computer's own history"  # what mi_price_import_run writes as the run's message

STATE = {"last_sync": None, "error": None, "holder": None, "holder_since": None, "conflicts": 0}
REMOTE = None                    # tests put a stand-in here
_SYNC = threading.RLock()        # one upload / download at a time


class Unreachable(Exception):
    """Supabase did not answer: nothing was changed there, try again later."""


class Refused(Exception):
    """Supabase answered no (wrong key, old code, bad data ...)."""


class Conflict(Exception):
    """Someone else changed this match first."""

    def __init__(self, row: dict | None):
        super().__init__("changed by someone else")
        self.row = row or {}


# ---------------------------------------------------------------- settings and the web API
def setting(name: str, default: str = "") -> str:
    import os
    if os.environ.get(name) is not None:
        return os.environ[name]
    try:
        from .config import load_env
        return load_env().get(name, default)
    except OSError:
        return default


class Remote:
    """The Supabase web API, limited to what this module needs: reading mi_price_* tables and calling mi_price_* functions."""

    def __init__(self, url: str, key: str, apikey: str | None = None, session=None):
        self.url = url.rstrip("/")
        self.headers = {"apikey": apikey or key, "Authorization": f"Bearer {key}"}
        self.s = session or requests.Session()

    def _call(self, method: str, path: str, **kw):
        try:
            r = self.s.request(method, f"{self.url}/rest/v1/{path}", headers=self.headers, timeout=40, **kw)
        except requests.RequestException as e:
            raise Unreachable(f"Supabase did not answer ({type(e).__name__})") from e
        if r.status_code >= 500 or r.status_code == 429:
            raise Unreachable(f"Supabase is not available (HTTP {r.status_code})")
        if r.status_code >= 400:
            try:
                msg = r.json().get("message") or r.text
            except ValueError:
                msg = r.text
            raise Refused(f"HTTP {r.status_code}: {str(msg)[:250]}")
        return r.json() if r.content else None

    def select(self, table: str, params: dict) -> list[dict]:
        if not table.startswith("mi_price_"):
            raise ValueError("only mi_price_* tables")
        return self._call("GET", table, params=params) or []

    def rpc(self, name: str, body: dict):
        if not name.startswith("mi_price_"):
            raise ValueError("only mi_price_* functions")
        return self._call("POST", f"rpc/{name}", json=body)

    def select_all(self, table: str, order: str, extra: dict | None = None) -> list[dict]:
        out, off = [], 0
        while True:
            page = self.select(table, {"select": "*", "order": order, "limit": PAGE, "offset": off, **(extra or {})})
            out += page
            if len(page) < PAGE:
                return out
            off += PAGE


def remote():
    """The connection when sharing is on, else None."""
    if REMOTE is not None:
        return REMOTE
    key = setting("PRICES_SUPABASE_KEY")
    url = setting("PRICES_SUPABASE_URL") or setting("PRODUCT_SUPABASE_URL")
    return Remote(url, key, setting("PRICES_SUPABASE_API_KEY") or None) if key and url else None


def enabled() -> bool:
    return remote() is not None


def me() -> str:
    """How this computer appears to the others (PRICES_NAME in .env, else the computer's name)."""
    return (setting("PRICES_NAME") or socket.gethostname() or "a computer")[:60]


# ---------------------------------------------------------------- local helpers
def _read(sql: str, args=()) -> list[dict]:
    with DB_LOCK:
        cur = core.CON.cursor()
        cur.execute(sql, list(args))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def _do(sql: str, args=()) -> None:
    with DB_LOCK:
        core.CON.cursor().execute(sql, list(args))


def _local_now() -> datetime:
    return _read("SELECT now()::TIMESTAMP AS t")[0]["t"]


def _age(at, now) -> float:
    return max((now - at).total_seconds(), 0) if at else 0


def _in(ts) -> datetime | None:
    """A Supabase time as this database stores times (India time, no zone)."""
    if not ts:
        return None
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(IST).replace(tzinfo=None)


def _out(ts) -> str | None:
    return ts.replace(tzinfo=IST).isoformat() if ts else None


def _json(v) -> list:
    return json.loads(v) if isinstance(v, str) else (v or [])


# ---------------------------------------------------------------- matches
def _local_match(pid: str, site: str) -> dict | None:
    r = _read("SELECT * FROM price_matches WHERE product_id = ? AND site = ?", [pid, site])
    return r[0] if r else None


def _store_match(r: dict) -> None:
    """Take Supabase's row as this computer's row."""
    _do("""INSERT OR REPLACE INTO price_matches (product_id, site, url, status, method, confidence, matched_name, candidates, rejected, checked_at, updated_at, remote_version, dirty, updated_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, false, ?)""",
        [r["product_id"], r["site"], r.get("url"), r["status"], r.get("method"), r.get("confidence"), r.get("matched_name"), json.dumps(_json(r.get("candidates"))), json.dumps(_json(r.get("rejected"))),
         _in(r.get("checked_at")), _in(r.get("updated_at")), r["version"], r.get("updated_by")])


def _payload(m: dict, by_person: bool = False) -> dict:
    out = {"product_id": m["product_id"], "site": m["site"], "url": m.get("url"), "status": m["status"], "method": m.get("method"), "confidence": m.get("confidence"),
           "matched_name": m.get("matched_name"), "candidates": _json(m.get("candidates")), "rejected": _json(m.get("rejected")), "checked_at": _out(m.get("checked_at"))}
    if by_person:
        out["by_person"] = True
    return out


def push_match(pid: str, site: str, by_person: bool = False) -> dict:
    """Send one changed match. If Supabase refuses it (changed meanwhile, or a person had decided), its row replaces ours."""
    r = remote()
    m = _local_match(pid, site)
    if not m or not m.get("dirty"):
        return {"saved": True}
    res = r.rpc("mi_price_save_match", {"p_client": CLIENT, "p_row": _payload(m, by_person), "p_expected": m.get("remote_version") or 0, "p_by": me()})
    if not res["saved"] and res.get("reason") == "gone":
        res = r.rpc("mi_price_save_match", {"p_client": CLIENT, "p_row": _payload(m, by_person), "p_expected": 0, "p_by": me()})
    if res["saved"]:
        v = res["row"]["version"]
        # the run may have changed the row again while it was being sent: then it stays waiting, on top of the new version
        _do("UPDATE price_matches SET remote_version = ?, updated_by = ?, dirty = (updated_at IS DISTINCT FROM ?) WHERE product_id = ? AND site = ?", [v, me(), m["updated_at"], pid, site])
    elif res.get("row"):
        _store_match(res["row"])
    return res


def pull_matches() -> int:
    local = {(m["product_id"], m["site"]): m for m in _read("SELECT product_id, site, method, remote_version, dirty FROM price_matches")}
    n = 0
    for r in remote().select_all("mi_price_matches", "product_id.asc,site.asc"):
        mine = local.get((r["product_id"], r["site"]))
        if mine:
            if mine["dirty"] or mine["remote_version"] == r["version"]:
                continue  # waiting to be sent, or already the same
            if mine["remote_version"] is None and mine["method"] == "you" and r.get("method") != "you":
                continue  # a decision made here before sharing, not uploaded yet: keep it
        _store_match(r)
        n += 1
    return n


def decide(pid: str, site: str, seen_version, change) -> None:
    """Apply a person's decision (`change()` edits the local row). With sharing on it must reach Supabase, on top of the version the person saw."""
    if not enabled():
        change()
        return
    with _SYNC:
        push_match(pid, site)  # send anything of ours still waiting for this row first
        rows = remote().select("mi_price_matches", {"select": "*", "product_id": f"eq.{pid}", "site": f"eq.{site}"})
        mine = _local_match(pid, site)
        if rows and (not mine or mine.get("remote_version") != rows[0]["version"]):
            _store_match(rows[0])
        current = _local_match(pid, site)
        if seen_version is not None and ((current or {}).get("remote_version") or 0) != seen_version:
            raise Conflict(current)
        change()
        try:
            res = push_match(pid, site, by_person=True)
        except (Unreachable, Refused):
            _restore(pid, site, current)  # not saved there, so not kept here either
            raise
        if not res["saved"]:
            raise Conflict(_local_match(pid, site))


def _restore(pid: str, site: str, row: dict | None) -> None:
    _do("DELETE FROM price_matches WHERE product_id = ? AND site = ?", [pid, site])
    if row:
        cols = list(row)
        vals = [json.dumps(_json(row[c])) if c in ("candidates", "rejected") else row[c] for c in cols]
        _do(f"INSERT INTO price_matches ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals)


# ---------------------------------------------------------------- readings: send
def _push_rows(table: str, fn: str, fields: list[str]) -> int:
    r = remote()
    sent = 0
    runs = _read(f"SELECT DISTINCT t.run_id, p.remote_id FROM {table} t JOIN price_runs p ON p.run_id = t.run_id WHERE t.synced = false AND p.remote_id IS NOT NULL ORDER BY 1")
    for run in runs:
        while True:
            now = _local_now()
            rows = _read(f"SELECT rowid AS _rowid, * FROM {table} WHERE run_id = ? AND synced = false ORDER BY rowid LIMIT ?", [run["run_id"], BATCH])
            if not rows:
                break
            body = [{**{f: x.get(f) for f in fields}, "age_seconds": _age(x["fetched_at"], now)} for x in rows]
            r.rpc(fn, {"p_client": CLIENT, "p_run": run["remote_id"], "p_rows": body})
            _do(f"UPDATE {table} SET synced = true WHERE rowid IN (SELECT unnest(?::BIGINT[]))", [[x["_rowid"] for x in rows]])
            sent += len(rows)
    return sent


SNAPSHOT_FIELDS = ["product_id", "site", "url", "ok", "error", "price", "mrp", "offer_price", "in_stock", "stock_qty", "discount", "page_name", "page_size"]


def push() -> dict:
    """Everything waiting here. Safe to repeat: a reading already there is ignored, a match is checked against its version."""
    with _SYNC:
        out = {"readings": _push_rows("price_snapshots", "mi_price_add_snapshots", SNAPSHOT_FIELDS), "own": _push_rows("price_own", "mi_price_add_own", ["product_id", "price", "mrp"]), "matches": 0, "conflicts": 0}
        for m in _read("SELECT product_id, site FROM price_matches WHERE dirty = true ORDER BY 1, 2"):
            if push_match(m["product_id"], m["site"])["saved"]:
                out["matches"] += 1
            else:
                out["conflicts"] += 1
        STATE["conflicts"] += out["conflicts"]
        return out


# ---------------------------------------------------------------- readings: fetch
def _pull_runs() -> dict:
    """Mirror the shared run list; returns {remote id: local run id}."""
    mine = {x["remote_id"]: x["run_id"] for x in _read("SELECT run_id, remote_id FROM price_runs WHERE remote_id IS NOT NULL")}
    active = _active_run()
    for r in remote().select_all("mi_price_runs", "started_at.asc,run_id.asc"):
        vals = [_in(r.get("finished_at")), r["status"], r.get("sites"), json.dumps(r["summary"]) if r.get("summary") is not None else None, r.get("message"), r.get("host")]
        if r["run_id"] not in mine:
            with DB_LOCK:
                mine[r["run_id"]] = core.CON.cursor().execute(
                    """INSERT INTO price_runs (started_at, finished_at, status, sites, summary, message, host, remote_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING run_id""",
                    [_in(r["started_at"]), *vals, r["run_id"]]).fetchone()[0]
        elif mine[r["run_id"]] != active and not (r.get("message") == IMPORTED and r.get("host") == me()):  # our own uploaded run: what we have says more
            _do("UPDATE price_runs SET finished_at = ?, status = ?, sites = ?, summary = ?, message = ?, host = ? WHERE run_id = ?", [*vals, mine[r["run_id"]]])
    return mine


def _active_run():
    from . import prices
    return prices.PRICE_JOB["run_id"] if prices.PRICE_JOB["running"] else None


def _cursor(name: str) -> str | None:
    r = _read("SELECT value FROM price_sync_state WHERE key = ?", [name])
    return r[0]["value"] if r else None


def _pull_rows(table: str, remote_table: str, key: list[str], fields: list[str], runs: dict) -> int:
    last = _cursor(remote_table)
    extra = {"received_at": f"gt.{(datetime.fromisoformat(last) - OVERLAP).isoformat()}"} if last else {}
    rows = remote().select_all(remote_table, "received_at.asc," + ",".join(f"{k}.asc" for k in key), extra)
    if not rows:
        return 0
    ids = sorted({runs[r["run_id"]] for r in rows if r["run_id"] in runs})
    have = {tuple([x["run_id"], *[x[k] for k in key if k != "run_id"]]) for x in
            _read(f"SELECT run_id, {', '.join(k for k in key if k != 'run_id')} FROM {table} WHERE run_id IN (SELECT unnest(?::BIGINT[]))", [ids])}
    n = 0
    for r in rows:
        run = runs.get(r["run_id"])
        if run is None:
            continue  # its run appeared after the run list was read: fetched next time (the overlap covers it)
        ident = tuple([run, *[r[k] for k in key if k != "run_id"]])
        if ident in have:
            continue
        have.add(ident)
        cols = ["run_id", "fetched_at", "synced", *fields]
        _do(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [run, _in(r["fetched_at"]), True, *[r.get(f) for f in fields]])
        n += 1
    newest = max(datetime.fromisoformat(str(r["received_at"]).replace("Z", "+00:00")) for r in rows if r["run_id"] in runs) if ids else None
    if newest:
        _do("INSERT OR REPLACE INTO price_sync_state VALUES (?, ?)", [remote_table, newest.isoformat()])
    return n


def pull() -> dict:
    with _SYNC:
        out = {"matches": pull_matches()}
        runs = _pull_runs()
        out["readings"] = _pull_rows("price_snapshots", "mi_price_snapshots", ["run_id", "product_id", "site"], SNAPSHOT_FIELDS, runs)
        out["own"] = _pull_rows("price_own", "mi_price_own", ["run_id", "product_id"], ["product_id", "price", "mrp"], runs)
        return out


# ---------------------------------------------------------------- the lock
def read_lock() -> dict:
    """Who is refreshing right now (nothing when free or lapsed)."""
    rows = remote().select("mi_price_lock", {"select": "holder,acquired_at,expires_at,run_id"})
    r = rows[0] if rows else {}
    live = bool(r.get("holder")) and _in(r.get("expires_at")) and _in(r["expires_at"]) > datetime.now(IST).replace(tzinfo=None)
    STATE["holder"], STATE["holder_since"] = (r["holder"], _in(r["acquired_at"])) if live else (None, None)
    return {"holder": STATE["holder"], "since": STATE["holder_since"]}


def new_run_id() -> str:
    return str(uuid.uuid4())


def acquire(run_id: str, sites: str) -> dict:
    return remote().rpc("mi_price_lock_acquire", {"p_client": CLIENT, "p_host": me(), "p_run": run_id, "p_sites": sites})


def renew(token: str) -> bool:
    return bool(remote().rpc("mi_price_lock_renew", {"p_token": token}))


def finish(token: str, status: str, summary: dict, message: str | None) -> bool:
    return bool(remote().rpc("mi_price_finish", {"p_token": token, "p_status": status, "p_summary": json.loads(json.dumps(summary, default=str)), "p_message": message}))


# ---------------------------------------------------------------- everything at once, and the first upload
def sync() -> dict:
    """Send what waits here, fetch what is new there. Never raises: the outcome is kept in STATE for the screen."""
    if not enabled():
        return {"enabled": False}
    try:
        with _SYNC:
            sent = push()
            got = pull()
            read_lock()
        STATE.update(last_sync=datetime.now().isoformat(timespec="seconds"), error=None)
        return {"enabled": True, "ok": True, "sent": sent, "received": got}
    except (Unreachable, Refused) as e:
        STATE["error"] = str(e)
        return {"enabled": True, "ok": False, "error": str(e)}


def waiting() -> dict:
    """What is still only on this computer."""
    one = lambda sql: _read(sql)[0]["n"]  # noqa: E731
    return {"waiting": one("SELECT count(*) AS n FROM price_snapshots WHERE synced = false") + one("SELECT count(*) AS n FROM price_matches WHERE dirty = true"),
            "history": one("SELECT count(*) AS n FROM price_snapshots WHERE synced IS NULL"),
            "history_matches": one("SELECT count(*) AS n FROM price_matches WHERE remote_version IS NULL AND dirty IS NOT TRUE")}


def upload_history() -> dict:
    """Send what this computer collected before sharing was on: its runs, readings, our prices and matches. Safe to run again."""
    r = remote()
    if r is None:
        raise Refused("sharing is not set up on this computer")
    with _SYNC:
        out = {"runs": 0, "readings": 0, "own": 0, "matches": 0, "kept_theirs": 0}
        now = _local_now()
        for run in _read("""SELECT run_id, started_at, status, sites FROM price_runs WHERE remote_id IS NULL AND status <> 'running' AND
                            (run_id IN (SELECT run_id FROM price_snapshots) OR run_id IN (SELECT run_id FROM price_own)) ORDER BY run_id"""):
            rid = new_run_id()
            r.rpc("mi_price_import_run", {"p_client": CLIENT, "p_run": rid, "p_host": me(), "p_status": run["status"], "p_age_seconds": _age(run["started_at"], now), "p_sites": run["sites"]})
            _do("UPDATE price_runs SET remote_id = ?, host = ? WHERE run_id = ?", [rid, me(), run["run_id"]])
            out["runs"] += 1
        for t in ("price_snapshots", "price_own"):
            _do(f"UPDATE {t} SET synced = false WHERE synced IS NULL AND run_id IN (SELECT run_id FROM price_runs WHERE remote_id IS NOT NULL)")
        out["readings"] = _push_rows("price_snapshots", "mi_price_add_snapshots", SNAPSHOT_FIELDS)
        out["own"] = _push_rows("price_own", "mi_price_add_own", ["product_id", "price", "mrp"])
        for m in _read("SELECT * FROM price_matches WHERE remote_version IS NULL ORDER BY product_id, site"):
            took = r.rpc("mi_price_import_match", {"p_client": CLIENT, "p_row": _payload(m), "p_age_seconds": _age(m.get("updated_at"), now), "p_by": me()})
            out["matches" if took else "kept_theirs"] += 1
            # whatever the outcome, the shared row is now the true one (a person's decision made here is only refused for a newer one of a person): the download below replaces ours
            _do("UPDATE price_matches SET dirty = false WHERE product_id = ? AND site = ?", [m["product_id"], m["site"]])
        pull()
        STATE.update(last_sync=datetime.now().isoformat(timespec="seconds"), error=None)
        return out


def check() -> str:
    """One read with the configured key, to prove it works (python -m mi.cli prices-check)."""
    r = remote()
    if r is None:
        return "Sharing is off: there is no PRICES_SUPABASE_KEY in .env (see docs/price-sync.md)."
    meta = r.select("mi_price_meta", {"select": "*"})
    lock = read_lock()
    n = len(r.select("mi_price_runs", {"select": "run_id", "limit": 1000}))
    return f"The key works. Required version {next((x['value'] for x in meta if x['key'] == 'min_client'), '?')} (this code: {CLIENT}); {n} shared runs; " + (
        f"{lock['holder']} is refreshing now." if lock["holder"] else "nobody is refreshing now.")

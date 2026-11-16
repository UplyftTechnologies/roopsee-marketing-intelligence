"""Read-only Meta (Facebook / Instagram) Marketing API client and sync into DuckDB.

* GET requests only. The token comes from .env (META_ACCESS_TOKEN), travels in an Authorization header, and is
  redacted from every error message, so it cannot leak into logs, the API or the browser.
* Optional .env settings:  META_AD_ACCOUNT_IDS=act_123,act_456   META_SINCE=2026-06-01   META_API_VERSION=v25.0
  (default: every accessible ad account that has ever spent money).
* Sync is incremental: the last 7 days are always re-read because Meta restates recent numbers.
"""
import json
import re
import time
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests

from .config import load_env
from .db import DB_LOCK, RAW_SCHEMAS
from .extract import _frame, _insert

DEFAULT_VERSION = "v25.0"
LOOKBACK_DAYS = 7
IST = timezone(timedelta(hours=5, minutes=30))
INSIGHT_FIELDS = ("date_start,account_id,campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,spend,impressions,reach,frequency,clicks,"
                  "inline_link_clicks,ctr,cpc,cpm,actions,action_values")
# omni_* are Meta's de-duplicated totals across web / app / offline; fall back to the plain type
ACTION_KEYS = {"purchases": ("omni_purchase", "purchase"), "add_to_cart": ("omni_add_to_cart", "add_to_cart"),
               "initiate_checkout": ("omni_initiated_checkout", "initiate_checkout"), "view_content": ("omni_view_content", "view_content"),
               "landing_page_views": ("landing_page_view",)}


class MetaError(RuntimeError):
    pass


def redact(text) -> str:
    """Remove anything that looks like an access token from text before it is shown or stored."""
    t = re.sub(r"(access_token=)[^&\s'\"]+", r"\1***", str(text))
    return re.sub(r"EAA[A-Za-z0-9_\-]{20,}", "***", t)


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _i(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def configured() -> bool:
    return bool(load_env().get("META_ACCESS_TOKEN"))


class MetaClient:
    def __init__(self):
        env = load_env()
        self.token = env.get("META_ACCESS_TOKEN")
        if not self.token:
            raise MetaError("META_ACCESS_TOKEN is not set in .env")
        self.version = env.get("META_API_VERSION") or DEFAULT_VERSION
        self.accounts = [("act_" + a.strip().removeprefix("act_")) for a in (env.get("META_AD_ACCOUNT_IDS") or "").split(",") if a.strip()]
        self.since = env.get("META_SINCE") or "2026-06-01"
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {self.token}"
        self.base = f"https://graph.facebook.com/{self.version}"

    def _get(self, url: str, params=None, retries: int = 5) -> dict:
        last = None
        for i in range(retries):
            try:
                r = self.s.get(url, params=params, timeout=90)
            except requests.RequestException as e:
                last = redact(e)
                time.sleep(2 * (i + 1))
                continue
            if r.ok:
                return r.json()
            err = (r.json() if r.headers.get("content-type", "").startswith("application/json") else {}).get("error", {})
            last = f"HTTP {r.status_code} code={err.get('code')}: {redact(err.get('message', r.text[:200]))}"
            if err.get("code") in (4, 17, 32, 613, 80000, 80003, 80004) or r.status_code in (429, 500, 503):  # rate limit / transient
                time.sleep(min(60, 5 * 2 ** i))
                continue
            break  # auth / permission / bad request: retrying will not help
        raise MetaError(last or "request failed")

    def pages(self, path: str, params: dict):
        data = self._get(f"{self.base}/{path}", params)
        while True:
            yield from data.get("data", [])
            nxt = (data.get("paging") or {}).get("next")
            if not nxt:
                return
            data = self._get(nxt)  # the next-page URL already carries every parameter

    def me(self) -> dict:
        return self._get(f"{self.base}/me", {"fields": "id,name"})

    def token_info(self) -> dict:
        d = self._get(f"{self.base}/debug_token", {"input_token": self.token}).get("data", {})
        exp = d.get("expires_at")
        return {"valid": d.get("is_valid"), "type": d.get("type"), "scopes": d.get("scopes"),
                "expires_at": (datetime.fromtimestamp(exp, tz=IST).isoformat(timespec="seconds") if exp else None), "never_expires": exp == 0}

    def discover(self) -> list[dict]:
        return list(self.pages("me/adaccounts", {"fields": "account_id,name,currency,timezone_name,account_status,amount_spent", "limit": 100}))

    def account_ids(self) -> list[str]:
        if self.accounts:
            return self.accounts
        return [a["id"] for a in self.discover() if _f(a.get("amount_spent")) > 0]

    def insights(self, account: str, since: str, until: str) -> list[dict]:
        params = {"level": "ad", "time_increment": 1, "time_range": json.dumps({"since": since, "until": until}), "fields": INSIGHT_FIELDS, "limit": 500}
        return list(self.pages(f"{account}/insights", params))

    def entities(self, account: str) -> list[dict]:
        out = []
        specs = {"campaign": ("campaigns", "id,name,status,effective_status,objective,daily_budget,lifetime_budget,created_time"),
                 "adset": ("adsets", "id,name,campaign_id,status,effective_status,daily_budget,lifetime_budget,created_time"),
                 "ad": ("ads", "id,name,adset_id,campaign_id,status,effective_status,created_time,creative{thumbnail_url}")}
        for kind, (edge, fields) in specs.items():
            for e in self.pages(f"{account}/{edge}", {"fields": fields, "limit": 200}):
                out.append({
                    "account_id": account, "entity_type": kind, "entity_id": e.get("id"), "name": e.get("name"),
                    "campaign_id": e.get("campaign_id") or (e.get("id") if kind == "campaign" else None), "adset_id": e.get("adset_id") or (e.get("id") if kind == "adset" else None),
                    "status": e.get("status"), "effective_status": e.get("effective_status"), "objective": e.get("objective"),
                    "daily_budget": _f(e.get("daily_budget")) / 100 if e.get("daily_budget") else None,  # Meta reports minor units
                    "lifetime_budget": _f(e.get("lifetime_budget")) / 100 if e.get("lifetime_budget") else None,
                    "thumbnail_url": ((e.get("creative") or {}).get("thumbnail_url")), "created_time": e.get("created_time"),
                })
        return out


def parse_insight(r: dict) -> dict:
    acts = {a["action_type"]: _f(a.get("value")) for a in r.get("actions", [])}
    vals = {a["action_type"]: _f(a.get("value")) for a in r.get("action_values", [])}
    pick = lambda d, keys: next((d[k] for k in keys if k in d), 0.0)  # noqa: E731
    return {
        "account_id": r.get("account_id"), "date": r.get("date_start"), "campaign_id": r.get("campaign_id"), "campaign_name": r.get("campaign_name"),
        "adset_id": r.get("adset_id"), "adset_name": r.get("adset_name"), "ad_id": r.get("ad_id"), "ad_name": r.get("ad_name"),
        "spend": _f(r.get("spend")), "impressions": _i(r.get("impressions")), "reach": _i(r.get("reach")), "frequency": _f(r.get("frequency")),
        "clicks": _i(r.get("clicks")), "link_clicks": _i(r.get("inline_link_clicks")), "ctr": _f(r.get("ctr")), "cpc": _f(r.get("cpc")), "cpm": _f(r.get("cpm")),
        "purchases": pick(acts, ACTION_KEYS["purchases"]), "purchase_value": pick(vals, ACTION_KEYS["purchases"]),
        "add_to_cart": pick(acts, ACTION_KEYS["add_to_cart"]), "initiate_checkout": pick(acts, ACTION_KEYS["initiate_checkout"]),
        "view_content": pick(acts, ACTION_KEYS["view_content"]), "landing_page_views": pick(acts, ACTION_KEYS["landing_page_views"]),
        "actions": r.get("actions") or [],
    }


def _log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] meta: {msg}", flush=True)


def sync(con, full: bool = False) -> dict:
    """Pull entities (names, status, budgets) and daily ad-level insights; replaces the re-read window, keeps older days."""
    c = MetaClient()
    accounts = c.account_ids()
    if not accounts:
        raise MetaError("No ad account found: the token can see none with spend. Set META_AD_ACCOUNT_IDS in .env.")
    until = datetime.now(IST).date()
    total = 0
    for acc in accounts:
        ents = c.entities(acc)
        with DB_LOCK:
            con.execute("DELETE FROM raw_meta_entities WHERE account_id = ?", [acc]).fetchall()
        _insert(con, "raw_meta_entities", _frame(ents, RAW_SCHEMAS["raw_meta_entities"]), ignore=False)
        with DB_LOCK:
            last = con.execute("SELECT max(date) FROM raw_meta_insights WHERE account_id = ?", [acc]).fetchall()[0][0]
        since = c.since if (full or last is None) else str(max(date.fromisoformat(c.since), last - timedelta(days=LOOKBACK_DAYS)))
        rows = [parse_insight(r) for r in c.insights(acc, since, str(until))]
        with DB_LOCK:
            con.execute("DELETE FROM raw_meta_insights WHERE account_id = ? AND date >= ?", [acc, since]).fetchall()
        _insert(con, "raw_meta_insights", _frame(rows, RAW_SCHEMAS["raw_meta_insights"]), ignore=False)
        _log(f"{acc}: {len(ents)} campaigns/ad sets/ads, {len(rows)} daily ad rows since {since}")
        total += len(rows)
    with DB_LOCK:
        con.execute("INSERT OR REPLACE INTO etl_meta VALUES ('meta_last_sync', ?)", [datetime.now().isoformat(timespec="seconds")]).fetchall()
        con.execute("INSERT OR REPLACE INTO etl_meta VALUES ('meta_accounts', ?)", [json.dumps(accounts)]).fetchall()
        con.execute("DELETE FROM etl_meta WHERE k = 'meta_last_error'").fetchall()
    return {"accounts": accounts, "rows": total}


def record_error(con, err: Exception) -> None:
    with DB_LOCK:
        con.execute("INSERT OR REPLACE INTO etl_meta VALUES ('meta_last_error', ?)", [redact(err)[:400]]).fetchall()

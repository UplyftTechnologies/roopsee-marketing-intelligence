"""Small Meta Graph API client: token in a header, appsecret_proof, retries only where retrying is safe, redacted errors."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from urllib.parse import parse_qsl, urlparse

import requests

from .common import LauncherError, Settings, log

RATE_LIMIT_CODES = {4, 17, 32, 613}  # "slow down" errors: nothing was created, so a retry is safe
ACCOUNT_LIMIT_CODES = {17, 80004}  # "this ad account was asked too often": retrying at once only makes the block longer

# Calls made by this process, and what Meta said about how full the limit is. Shared by every Meta() in the process.
STATS: dict = {"calls": 0, "reads": 0, "writes": 0, "since": time.time(), "usage_pct": 0, "blocked_until": 0.0, "blocked_why": "", "by": {}}


def usage_snapshot() -> dict:
    left = max(0, int(STATS["blocked_until"] - time.time()))
    return {"calls": STATS["calls"], "reads": STATS["reads"], "writes": STATS["writes"], "since": STATS["since"], "usage_pct": STATS["usage_pct"], "by": dict(sorted(STATS["by"].items(), key=lambda kv: -kv[1])[:8]),
            "blocked_seconds": left, "blocked_why": STATS["blocked_why"] if left else ""}


def _note_headers(h) -> None:
    """Meta reports how much of the limit is used in a header; if it says when access returns, remember it so no further calls are wasted."""
    pct = 0
    try:
        raw = h.get("x-business-use-case-usage")
        if raw:
            for rows in json.loads(raw).values():
                for r in rows:
                    pct = max(pct, int(r.get("call_count", 0)), int(r.get("total_cputime", 0)), int(r.get("total_time", 0)))
                    wait = int(r.get("estimated_time_to_regain_access", 0) or 0)
                    if wait > 0:
                        STATS["blocked_until"] = max(STATS["blocked_until"], time.time() + wait * 60)
                        STATS["blocked_why"] = f"Meta says access returns in about {wait} min"
        raw = h.get("x-ad-account-usage")
        if raw:
            pct = max(pct, int(json.loads(raw).get("acc_id_util_pct", 0)))
    except (ValueError, TypeError, AttributeError):
        return
    STATS["usage_pct"] = pct


class MetaError(LauncherError):
    def __init__(self, msg, code=None, subcode=None):
        super().__init__(msg)
        self.code, self.subcode = code, subcode


class Meta:
    def __init__(self, s: Settings, dry_run: bool = False):
        self.s, self.dry = s, dry_run
        self.base = f"https://graph.facebook.com/{s.version}/"
        self._n = 0

    def _proof(self) -> str:
        return hmac.new(self.s.app_secret.encode(), self.s.token.encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def _enc(data: dict) -> dict:
        return {k: (v if isinstance(v, str) else json.dumps(v)) for k, v in data.items() if v is not None}

    def _send(self, method, path, params=None, data=None, files=None):
        left = STATS["blocked_until"] - time.time()
        if left > 0:  # Meta is limiting this account: asking again would only extend the block
            raise MetaError(f"Meta is limiting calls for this ad account. {STATS['blocked_why'] or 'Try again later'} (about {int(left // 60) + 1} min left). Nothing was sent.", 17)
        params = dict(params or {})
        if self.s.app_secret:
            params["appsecret_proof"] = self._proof()
        headers = {"Authorization": f"Bearer {self.s.token}"}
        last = None
        for attempt in range(4):
            try:
                r = requests.request(method, self.base + path.lstrip("/"), params=params, data=data, files=files, headers=headers, timeout=120)
            except requests.RequestException as e:
                if method == "GET" and attempt < 3:  # a read can always be retried; a write could have gone through
                    time.sleep(2 ** attempt)
                    continue
                raise MetaError(self.s.redact(f"network error on {method} {path}: {e}"))
            STATS["calls"] += 1
            what = re.sub(r"\d{6,}", "id", re.sub(r"act_\d+", "account", path.lstrip("/")))
            STATS["by"][f"{method} {what}"] = STATS["by"].get(f"{method} {what}", 0) + 1
            STATS["reads" if method == "GET" else "writes"] += 1
            _note_headers(r.headers)
            try:
                body = r.json()
            except ValueError:
                body = {"error": {"message": r.text[:300]}}
            if r.ok and "error" not in body:
                return body
            err = body.get("error", {})
            last = MetaError(self.s.redact(
                f"{method} {path} -> {err.get('message', r.status_code)}"
                + (f" | {err['error_user_title']}: {err.get('error_user_msg', '')}" if err.get("error_user_title") else "")
                + f" (code {err.get('code')}, subcode {err.get('error_subcode')}, trace {err.get('fbtrace_id')})"),
                err.get("code"), err.get("error_subcode"))
            if err.get("code") in ACCOUNT_LIMIT_CODES:  # stop at once and wait: the block lasts a few minutes
                STATS["blocked_until"] = max(STATS["blocked_until"], time.time() + 300)
                STATS["blocked_why"] = "Meta said 'too many calls' for this ad account"
                break
            if err.get("code") in RATE_LIMIT_CODES and attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            if method == "GET" and r.status_code >= 500 and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            break
        log(str(last), self.s)
        raise last

    def get(self, path, **params):
        return self._send("GET", path, params=params)

    def pages(self, path, **params):
        """Follow paging cursors."""
        out = []
        res = self.get(path, **params)
        while True:
            out += res.get("data", [])
            nxt = res.get("paging", {}).get("next")
            if not nxt or len(out) > 5000:
                return out
            u = urlparse(nxt)  # Meta's "next" link may name another API version, so rebuild the request ourselves
            q = {k: v for k, v in parse_qsl(u.query) if k not in ("access_token", "appsecret_proof")}
            res = self._send("GET", u.path.split("/", 2)[2], params=q)

    def post(self, path, data: dict, files=None, validate_only: bool = False):
        """Every write goes through here, so dry-run and validate_only apply to all of them."""
        if self.dry:
            self._n += 1
            print(f"    [dry-run] POST {path}\n      " + self.s.redact(json.dumps(data, ensure_ascii=False))[:600])
            if files:
                return {"images": {k: {"hash": f"DRYHASH{self._n}"} for k in files}}
            return {"id": f"DRY_{self._n}"}
        data = dict(data)
        if validate_only:
            data["execution_options"] = ["validate_only"]
        return self._send("POST", path, data=self._enc(data), files=files)

    def find_by_name(self, edge: str, name: str):
        """Crash recovery: if a previous run created the object but died before saving its id, find it again by name."""
        if self.dry:
            return None
        flt = [{"field": "name", "operator": "EQUAL", "value": name}]
        rows = self.get(f"{self.s.account}/{edge}", fields="id,name,effective_status", filtering=json.dumps(flt), limit=5).get("data", [])
        rows = [r for r in rows if r.get("effective_status") not in ("DELETED", "ARCHIVED")]
        return rows[0]["id"] if rows else None

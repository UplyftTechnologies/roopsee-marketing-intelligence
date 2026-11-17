"""Small Meta Graph API client: token in a header, appsecret_proof, retries only where retrying is safe, redacted errors."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl, urlparse

import requests

from .common import LauncherError, Settings, log

RATE_LIMIT_CODES = {4, 17, 32, 613}  # "slow down" errors: nothing was created, so a retry is safe


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

"""Read-only Supabase REST client. Deliberately exposes GET only - the pipeline can never write to production."""
import time
import requests
from .config import supabase_creds


class ReadOnlySupabase:
    def __init__(self):
        self.url, key = supabase_creds()
        self._headers = {"apikey": key, "Authorization": f"Bearer {key}"}
        self._s = requests.Session()

    def select(self, table: str, params: dict, retries: int = 5) -> list[dict]:
        last = None
        for i in range(retries):
            try:
                r = self._s.get(f"{self.url}/rest/v1/{table}", params=params, headers=self._headers, timeout=90)
                if r.ok:
                    return r.json()
                last = f"{r.status_code} {r.text[:150]}"
            except requests.RequestException as e:
                last = repr(e)
            time.sleep(1.5 * (i + 1))
        raise RuntimeError(f"GET {table} failed after {retries} tries: {last}")

"""Paths and environment loading. Only PRODUCTION read credentials are used."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "mi.duckdb"
ENV_PATH = ROOT / ".env"
IST = "Asia/Kolkata"


def load_env() -> dict:
    """Parse KEY=VALUE lines; ignores comments and decoration lines in .env."""
    env = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if m:
            env[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return env


def supabase_creds() -> tuple[str, str]:
    env = load_env()
    url, key = env.get("PRODUCT_SUPABASE_URL"), env.get("PRODUCT_SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("PRODUCT_SUPABASE_URL / PRODUCT_SUPABASE_SERVICE_KEY missing in .env")
    return url.rstrip("/"), key

"""Make the key that lets this computer share prices through Supabase, and put it in .env (see docs/price-sync.md).

    .venv\\Scripts\\python tools\\make_price_key.py

You are asked for two things from Supabase -> Project Settings -> API:
  the JWT secret       read from the keyboard, hidden; never written to disk and never printed
  the anon public key  the website's public key; Supabase's web address wants it next to our key. It gives no access to the price tables.

The key made here is for the database role `mi_price_writer`: it can read the mi_price_* tables and call the mi_price_* functions, nothing else.
It is valid for 1 year. The script only uses the Python standard library and does not contact any server.
"""
import base64
import getpass
import hashlib
import hmac
import json
import re
import time
from pathlib import Path

ENV = Path(__file__).resolve().parent.parent / ".env"
ROLE = "mi_price_writer"
DAYS = 365


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_token(secret: str, now: int, role: str = ROLE, days: int = DAYS) -> str:
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = b64(json.dumps({"role": role, "iss": "supabase", "iat": now, "exp": now + days * 24 * 3600}, separators=(",", ":")).encode())
    signature = b64(hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


def role_of(token: str) -> str | None:
    try:
        part = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))).get("role")
    except (IndexError, ValueError):
        return None


def set_lines(text: str, values: dict) -> str:
    """The .env text with these settings added or replaced; every other line is left exactly as it was."""
    kept = [ln for ln in text.splitlines() if not re.match(rf"^\s*({'|'.join(values)})\s*=", ln)]
    return "\n".join(kept + [f"{k}={v}" for k, v in values.items()]) + "\n"


def main() -> None:
    if not ENV.exists():
        raise SystemExit(f"{ENV} does not exist yet: set up the dashboard first (see readme.md).")
    secret = getpass.getpass("JWT secret (typing is hidden): ").strip()
    if len(secret) < 16:
        raise SystemExit("That does not look like a JWT secret (too short).")
    anon = input("anon public key: ").strip()
    if role_of(anon) != "anon" and not anon.startswith("sb_publishable_"):
        raise SystemExit("That is not the anon (public) key. Do not use the service_role key here. Nothing was changed.")
    name = input("Name this computer shows to the others (empty = its computer name): ").strip()
    values = {"PRICES_SUPABASE_KEY": make_token(secret, int(time.time())), "PRICES_SUPABASE_API_KEY": anon}
    if name:
        values["PRICES_NAME"] = name
    ENV.write_text(set_lines(ENV.read_text(encoding="utf-8"), values), encoding="utf-8")
    print(f"\nAdded to .env: {', '.join(values)} (valid {DAYS} days). Nothing else in the file changed.")
    print("Check it with:  .venv\\Scripts\\python -m mi.cli prices-check\nThen restart the dashboard.")


if __name__ == "__main__":
    main()

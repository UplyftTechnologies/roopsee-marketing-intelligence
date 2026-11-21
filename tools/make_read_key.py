"""Make a Supabase API key that only has the `mi_reader` database role (see docs/read-only-access.md).

    .venv\\Scripts\\python tools\\make_read_key.py

You are asked for the project's JWT secret (Supabase -> Project Settings -> API -> JWT Secret). It is read from the keyboard,
never written to disk and never printed. The script only uses the Python standard library and does not contact any server.
"""
import base64
import getpass
import hashlib
import hmac
import json
import time


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def main() -> None:
    secret = getpass.getpass("JWT secret (typing is hidden): ").strip()
    if len(secret) < 16:
        raise SystemExit("That does not look like a JWT secret (too short).")
    role = input("Database role [mi_reader]: ").strip() or "mi_reader"
    now = int(time.time())
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = b64(json.dumps({"role": role, "iss": "supabase", "iat": now, "exp": now + 10 * 365 * 24 * 3600}, separators=(",", ":")).encode())
    signature = b64(hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    print("\nPut this line in .env:\n")
    print(f"PRODUCT_SUPABASE_READ_KEY={header}.{payload}.{signature}")


if __name__ == "__main__":
    main()

"""Save the response of every read-only endpoint of a running dashboard to a folder, to compare two versions of the code.

    python tests/snapshot.py http://127.0.0.1:8001 before      (run it against the old code)
    python tests/snapshot.py http://127.0.0.1:8001 after       (run it against the new code)
    python tests/snapshot.py --diff before after               (lists every endpoint whose answer changed)

Point the dashboard at a copy of the data with MI_DB_PATH=<file> so the numbers cannot change between the two runs.
"""
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent / "snapshots"
RANGE = "date_from=2026-10-01&date_to=2026-11-15"
VOLATILE = {"/api/jobs", "/api/health", "/api/meta"}  # change with the clock, compared by shape only


def get(base, path):
    try:
        return json.loads(urllib.request.urlopen(base + path, timeout=180).read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"__http_error__": e.code}


def canon(x):
    """Order-insensitive form: ties and unordered groups may come back in a different order between runs."""
    if isinstance(x, dict):
        return {k: canon(v) for k, v in sorted(x.items()) if k != "exported_at"}
    if isinstance(x, list):
        return sorted((canon(i) for i in x), key=lambda i: json.dumps(i, sort_keys=True, default=str))
    if isinstance(x, float):
        return round(x, 5)  # sums added in a different order differ in the last digits
    return x


def shape(x):
    if isinstance(x, dict):
        return {k: shape(v) for k, v in sorted(x.items())}
    if isinstance(x, list):
        return [shape(x[0])] if x else []
    return type(x).__name__


def endpoints(base):
    sid = get(base, f"/api/sessions?{RANGE}&limit=1&sort=started_at&direction=asc")["rows"][0]["session_id"]
    pk = get(base, f"/api/users?{RANGE}&limit=1&sort=sessions&direction=desc")["rows"][0]["person_key"]
    oid = get(base, f"/api/orders?{RANGE}&limit=1&sort=ts&direction=asc")["rows"][0]["order_id"]
    day = f"?{RANGE}"
    return [
        "/api/meta", "/api/jobs", "/api/health", "/api/alerts", "/api/digest", f"/api/overview{day}", f"/api/funnel{day}", f"/api/utm-health{day}", f"/api/campaigns{day}",
        f"/api/cohorts{day}&dim=state", f"/api/cohorts{day}&dim=channel", f"/api/retention{day}", f"/api/loyalty", f"/api/basket{day}", "/api/audiences",
        "/api/audiences/abandoned_checkout/people?limit=20", f"/api/timeseries{day}", f"/api/insights{day}", f"/api/performance{day}",
        f"/api/sessions{day}&limit=50&sort=started_at&direction=asc", f"/api/sessions{day}&limit=50&has=cart&lacks=order&sort=started_at&direction=asc",
        f"/api/sessions{day}&limit=50&search=add_to_cart&sort=started_at&direction=asc", f"/api/sessions{day}&limit=50&only_excluded=true&sort=started_at&direction=asc",
        f"/api/sessions/counts{day}", f"/api/sessions/{sid}", f"/api/person?key={pk}",
        f"/api/users{day}&limit=50&sort=sessions&direction=desc", f"/api/users/counts{day}", f"/api/users{day}&limit=30&preset=has_pincode&sort=sessions&direction=desc",
        f"/api/orders{day}&limit=50&sort=ts&direction=asc", f"/api/orders/analytics{day}", f"/api/orders/{oid}",
        f"/api/report{day}&dimension=channel&limit=100", f"/api/report{day}&dimension=channel_split&limit=100", f"/api/report{day}&dimension=delivery_state&limit=100",
        f"/api/report{day}&dimension=campaign&limit=200&sort=dim&direction=asc",
        "/api/events/names", "/api/events/catalogue", "/api/exclusions", "/api/exclusions/inventory", "/api/exclusions/export",
        "/api/exclusions/preview?kind=city&value=mumbai", "/api/lookup?q=thane",
        "/api/meta/status", f"/api/meta/overview{day}", f"/api/meta/breakdown{day}", f"/api/meta/hierarchy{day}",
    ]


def name_of(path):
    return re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_")[:90]


def snap(base, label):
    folder = OUT / label
    folder.mkdir(parents=True, exist_ok=True)
    errors = []
    for path in endpoints(base):
        data = get(base, path)
        if isinstance(data, dict) and "__http_error__" in data:
            errors.append(f"{data['__http_error__']} {path}")
        base_path = path.split("?")[0]
        if base_path in VOLATILE:
            data = shape(data)
        else:
            data = canon(data)
        (folder / f"{name_of(path)}.json").write_text(json.dumps(data, sort_keys=True, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"saved {len(list(folder.glob('*.json')))} endpoint answers to {folder}")
    if errors:
        print("ENDPOINTS THAT FAILED:")
        for e in errors:
            print("  " + e)
        sys.exit(1)


def diff(a, b):
    fa, fb = OUT / a, OUT / b
    names = sorted({p.name for p in fa.glob("*.json")} | {p.name for p in fb.glob("*.json")})
    bad = 0
    for n in names:
        x, y = fa / n, fb / n
        if not x.exists() or not y.exists():
            print("MISSING", n)
            bad += 1
        elif x.read_text(encoding="utf-8") != y.read_text(encoding="utf-8"):
            print("CHANGED", n)
            bad += 1
    print(f"{len(names)} endpoints compared, {bad} different")
    return bad


if __name__ == "__main__":
    if sys.argv[1] == "--diff":
        sys.exit(1 if diff(sys.argv[2], sys.argv[3]) else 0)
    snap(sys.argv[1].rstrip("/"), sys.argv[2])

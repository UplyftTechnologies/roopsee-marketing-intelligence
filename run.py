"""One-command launcher for Roopsee Marketing Intelligence.

    python run.py                 set everything up if needed, start the dashboard, open the browser
    python run.py --refresh       pull the newest events from Supabase first (read-only), then start
    python run.py --no-browser    don't open a browser tab
    python run.py --rebuild-ui    force a rebuild of the React dashboard

Safe to run repeatedly: every step is skipped when it is already done, and if the dashboard is
already running it just opens it.  Stop with Ctrl+C (or stop.bat if it was started in the background).
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DASH = ROOT / "dashboard"
IS_WIN = os.name == "nt"
VENV_PY = ROOT / ".venv" / ("Scripts/python.exe" if IS_WIN else "bin/python")
PORT = int(os.environ.get("MI_PORT", "8000"))
URL = f"http://127.0.0.1:{PORT}"


def say(msg: str) -> None:
    print(f"\n==> {msg}", flush=True)


def die(msg: str) -> None:
    print(f"\nERROR: {msg}\n", flush=True)
    sys.exit(1)


def run(cmd, cwd=ROOT, shell=False) -> None:
    try:
        subprocess.run(cmd, cwd=cwd, check=True, shell=shell)
    except subprocess.CalledProcessError as e:
        die(f"A setup step failed (exit code {e.returncode}): {cmd if isinstance(cmd, str) else ' '.join(map(str, cmd))}")


def port_in_use() -> bool:
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def is_our_dashboard() -> bool:
    try:
        with urllib.request.urlopen(f"{URL}/api/jobs", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def check_prereqs() -> None:
    if sys.version_info < (3, 10):
        die(f"Python 3.10 or newer is required (found {sys.version.split()[0]}). Install it from https://www.python.org/downloads/")
    env = ROOT / ".env"
    if not env.exists():
        die("The .env file is missing. Create it next to run.py with at least:\n"
            "  PRODUCT_SUPABASE_URL=https://<your-project>.supabase.co\n  PRODUCT_SUPABASE_SERVICE_KEY=<service key>")
    lines = [ln.strip() for ln in env.read_text(encoding="utf-8", errors="ignore").splitlines()]
    for key in ("PRODUCT_SUPABASE_URL", "PRODUCT_SUPABASE_SERVICE_KEY"):
        if not any(ln.startswith(key + "=") and len(ln) > len(key) + 1 for ln in lines):
            die(f"{key} is missing (or commented out) in .env - the dashboard needs it to read your production data.")


def ensure_venv_and_deps() -> None:
    if not VENV_PY.exists():
        say("Creating the Python environment (one time)...")
        run([sys.executable, "-m", "venv", str(ROOT / ".venv")])
    ok = subprocess.run([str(VENV_PY), "-c", "import duckdb, fastapi, uvicorn, pytz, requests, pandas"],
                        capture_output=True).returncode == 0
    if not ok:
        say("Installing Python packages (one time, about a minute)...")
        run([str(VENV_PY), "-m", "pip", "install", "-q", "--disable-pip-version-check", "-r", str(ROOT / "requirements.txt")])


def ui_needs_build(force: bool) -> bool:
    idx = DASH / "dist" / "index.html"
    if force or not idx.exists():
        return True
    built = idx.stat().st_mtime
    sources = [p for p in (DASH / "src").rglob("*") if p.is_file()] + [DASH / "index.html", DASH / "package.json", DASH / "vite.config.js"]
    return any(p.stat().st_mtime > built for p in sources)


def ensure_ui(force: bool) -> None:
    if not ui_needs_build(force):
        return
    from shutil import which
    if not which("npm"):
        if (DASH / "dist" / "index.html").exists():
            print("\nNote: Node.js (npm) was not found, so the dashboard UI was not rebuilt. Using the existing build.")
            return
        die("Node.js is required once to build the dashboard UI. Install the LTS version from https://nodejs.org/ and run again.")
    if not (DASH / "node_modules").exists():
        say("Installing dashboard packages (one time, about a minute)...")
        run("npm install --no-audit --no-fund", cwd=DASH, shell=True)
    say("Building the dashboard UI...")
    run("npm run build", cwd=DASH, shell=True)


def data_state() -> str:
    """'empty' (no events yet) | 'raw' (events but no analytics tables) | 'ready'."""
    if not (ROOT / "data" / "mi.duckdb").exists():
        return "empty"
    code = ("import duckdb\n"
            "c = duckdb.connect(r'%s', read_only=True)\n"
            "t = {r[0] for r in c.execute('select table_name from information_schema.tables').fetchall()}\n"
            "n = c.execute('select count(*) from raw_event_log').fetchall()[0][0] if 'raw_event_log' in t else 0\n"
            "print(n, 'sessions' in t)\n" % (ROOT / "data" / "mi.duckdb"))
    r = subprocess.run([str(VENV_PY), "-c", code], capture_output=True, text=True)
    if r.returncode != 0:
        return "empty"
    n, has = r.stdout.split()
    return "empty" if int(n) == 0 else ("ready" if has == "True" else "raw")


def ensure_data(refresh: bool) -> None:
    state = data_state()
    if state == "empty":
        say("First run: downloading your event data from Supabase (read-only). This takes about 4-5 minutes, once.")
        run([str(VENV_PY), "-m", "mi.cli", "all"])
    elif state == "raw":
        say("Building the analytics tables...")
        run([str(VENV_PY), "-m", "mi.cli", "transform"])
    elif refresh:
        say("Pulling the newest events from Supabase (read-only)...")
        run([str(VENV_PY), "-m", "mi.cli", "all"])


def main(argv) -> int:
    no_browser = "--no-browser" in argv
    print("Roopsee Marketing Intelligence")
    if port_in_use():
        if is_our_dashboard():
            say(f"The dashboard is already running at {URL}")
            if not no_browser:
                webbrowser.open(URL)
            return 0
        die(f"Port {PORT} is used by another program. Close it, or set a different port first:  set MI_PORT=8010")

    check_prereqs()
    ensure_venv_and_deps()
    ensure_ui("--rebuild-ui" in argv)
    ensure_data("--refresh" in argv)

    say(f"Starting the dashboard at {URL}   (press Ctrl+C in this window to stop)")
    server = subprocess.Popen([str(VENV_PY), "-m", "mi.cli", "serve"], cwd=ROOT)
    try:
        for _ in range(60):
            if server.poll() is not None:
                die("The server stopped unexpectedly. Scroll up for the error message.")
            if port_in_use():
                break
            time.sleep(1)
        else:
            die("The server did not start within 60 seconds.")
        print(f"\nReady:  {URL}\n", flush=True)
        if not no_browser:
            webbrowser.open(URL)
        server.wait()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""One-command launcher for Roopsee Marketing Intelligence (macOS, Linux and Windows).

    python3 run.py                 set everything up if needed, start the dashboard, open the browser
    python3 run.py --refresh       pull the newest events from Supabase first (read-only), then start
    python3 run.py --no-browser    don't open a browser tab
    python3 run.py --rebuild-ui    force a rebuild of the React dashboard
    python3 run.py --stop          stop a running dashboard (useful if it was started in the background)

(On Windows use `python` instead of `python3`.)

Safe to run repeatedly: every step is skipped when it is already done, and if the dashboard is
already running it just opens it.  Stop it with Ctrl+C in its terminal, or `--stop` from another one.
Use a different port with the MI_PORT environment variable.
"""
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DASH = ROOT / "dashboard"
DATA = ROOT / "data"
PID_FILE = DATA / "server.pid"
IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"
VENV_PY = ROOT / ".venv" / ("Scripts/python.exe" if IS_WIN else "bin/python")
PORT = int(os.environ.get("MI_PORT", "8000"))
URL = f"http://127.0.0.1:{PORT}"
MIN_PY = (3, 11)
PY = "python" if IS_WIN else "python3"


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


def port_hint() -> str:
    return f"MI_PORT=8010 {PY} run.py" if not IS_WIN else "set MI_PORT=8010   then   python run.py"


# ------------------------------------------------------------------ stop
def pids_on_port(port: int) -> set:
    """PIDs listening on the port (netstat on Windows, lsof on macOS/Linux)."""
    pids = set()
    try:
        if IS_WIN:
            out = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True).stdout
            for line in out.splitlines():
                p = line.split()
                if len(p) >= 5 and p[3] == "LISTENING" and p[1].endswith(f":{port}"):
                    pids.add(int(p[4]))
        else:
            out = subprocess.run(["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"], capture_output=True, text=True).stdout
            pids = {int(x) for x in out.split()}
    except (OSError, ValueError):
        pass
    return pids


def kill_tree(pid: int) -> None:
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        else:
            os.kill(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass


def stop_dashboard() -> int:
    if not port_in_use():
        print(f"The dashboard is not running on port {PORT}.")
        PID_FILE.unlink(missing_ok=True)
        return 0
    if not is_our_dashboard():
        die(f"Port {PORT} is in use, but not by this dashboard, so I won't touch it.")
    pids = pids_on_port(PORT)
    if PID_FILE.exists():
        try:
            pids.add(int(PID_FILE.read_text().strip()))
        except ValueError:
            pass
    for pid in pids:
        kill_tree(pid)
    for _ in range(20):
        if not port_in_use():
            PID_FILE.unlink(missing_ok=True)
            print("Dashboard stopped.")
            return 0
        time.sleep(0.5)
    die(f"Could not stop the dashboard (PIDs {sorted(pids) or 'unknown'}). Close its terminal window or end the process manually.")
    return 1


# ------------------------------------------------------------------ setup steps
def check_prereqs() -> None:
    if sys.version_info < MIN_PY:
        have = sys.version.split()[0]
        hint = ("Install a current Python with Homebrew:  brew install python   (or download from https://www.python.org/downloads/), "
                "then run it with python3 again.") if IS_MAC else "Install it from https://www.python.org/downloads/"
        die(f"Python {MIN_PY[0]}.{MIN_PY[1]} or newer is required (you have {have}). {hint}")
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
        hint = "brew install node" if IS_MAC else "https://nodejs.org/"
        die(f"Node.js is required once to build the dashboard UI. Install the LTS version ({hint}) and run again.")
    if not (DASH / "node_modules").exists():
        say("Installing dashboard packages (one time, about a minute)...")
        run("npm install --no-audit --no-fund", cwd=DASH, shell=True)
    say("Building the dashboard UI...")
    run("npm run build", cwd=DASH, shell=True)


def data_state() -> str:
    """'empty' (no events yet) | 'raw' (events but no analytics tables) | 'ready'."""
    db = DATA / "mi.duckdb"
    if not db.exists():
        return "empty"
    code = ("import duckdb, sys\n"
            "c = duckdb.connect(sys.argv[1], read_only=True)\n"
            "t = {r[0] for r in c.execute('select table_name from information_schema.tables').fetchall()}\n"
            "n = c.execute('select count(*) from raw_event_log').fetchall()[0][0] if 'raw_event_log' in t else 0\n"
            "print(n, 'sessions' in t)\n")
    r = subprocess.run([str(VENV_PY), "-c", code, str(db)], capture_output=True, text=True)
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


# ------------------------------------------------------------------ main
def main(argv) -> int:
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    if "--stop" in argv:
        return stop_dashboard()

    no_browser = "--no-browser" in argv
    print("Roopsee Marketing Intelligence")
    if port_in_use():
        if is_our_dashboard():
            say(f"The dashboard is already running at {URL}  (stop it with: {PY} run.py --stop)")
            if not no_browser:
                webbrowser.open(URL)
            return 0
        die(f"Port {PORT} is used by another program. Close it, or use another port:  {port_hint()}")

    check_prereqs()
    ensure_venv_and_deps()
    ensure_ui("--rebuild-ui" in argv)
    DATA.mkdir(exist_ok=True)
    ensure_data("--refresh" in argv)

    say(f"Starting the dashboard at {URL}   (press Ctrl+C to stop)")
    server = subprocess.Popen([str(VENV_PY), "-m", "mi.cli", "serve"], cwd=ROOT)
    PID_FILE.write_text(str(server.pid))
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
        PID_FILE.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""Roopsee Meta Ads launcher.   python run.py --help

Order:  doctor -> validate -> upload -> setup -> prepare -> (review) -> publish
Everything is created PAUSED. Only 'publish' activates anything. Default environment is the SANDBOX.
Web UI:  python run.py ui
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from shutil import which

from src.common import LauncherError
from src.pipeline import COMMANDS, execute


def ensure_ui_built(force: bool = False) -> None:
    """Build the React UI (once, and again whenever its source changes). Needs Node.js only for this."""
    root = Path(__file__).resolve().parent
    app, dist = root / "ui-app", root / "ui" / "dist" / "index.html"
    srcs = [p for p in (app / "src").rglob("*") if p.is_file()] + [app / "index.html", app / "package.json", app / "vite.config.js"]
    if dist.exists() and not force and not any(p.stat().st_mtime > dist.stat().st_mtime for p in srcs):
        return
    if not which("npm"):
        if dist.exists():
            print("Note: Node.js (npm) was not found, so the UI was not rebuilt. Using the existing build.")
            return
        raise LauncherError("Node.js is needed once to build the UI. Install the LTS version from https://nodejs.org/ and run again.")
    if not (app / "node_modules").exists():
        print("Installing UI packages (one time, about a minute)...")
        subprocess.run("npm install --no-audit --no-fund", cwd=app, shell=True, check=True)
    print("Building the UI...")
    subprocess.run("npm run build", cwd=app, shell=True, check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=COMMANDS + ["ui"])
    ap.add_argument("--batch", help="batch name, e.g. batch_001")
    ap.add_argument("--dry-run", action="store_true", help="print exactly what would be sent; send nothing")
    ap.add_argument("--validate-only", action="store_true", help="ask Meta to validate the request without creating anything")
    ap.add_argument("--confirm-production", action="store_true", help="required for any write when META_ENV=production")
    ap.add_argument("--yes", action="store_true", help="skip the sandbox publish prompt (never skips production)")
    ap.add_argument("--live", action="store_true", help="status: also read the current state from Meta")
    ap.add_argument("--no-browser", action="store_true", help="ui: do not open the browser")
    a = ap.parse_args()
    if a.command == "ui":
        try:
            ensure_ui_built()
        except (LauncherError, subprocess.CalledProcessError) as e:
            print(f"\nERROR: {e}", file=sys.stderr)
            return 1
        from ui.server import serve
        serve(open_browser=not a.no_browser)
        return 0
    try:
        return 0 if execute(a.command, a.batch, a.dry_run, a.validate_only, a.confirm_production, a.yes, False, a.live) else 1
    except LauncherError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted - safe to re-run; finished steps are skipped", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())

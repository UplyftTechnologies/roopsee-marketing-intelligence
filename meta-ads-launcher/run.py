#!/usr/bin/env python3
"""Roopsee Meta Ads launcher.   python run.py --help

Order:  doctor -> validate -> upload -> setup -> prepare -> (review) -> publish
Everything is created PAUSED. Only 'publish' activates anything. Default environment is the SANDBOX.
Web UI:  python run.py ui
"""
from __future__ import annotations

import argparse
import sys

from src.common import LauncherError
from src.pipeline import COMMANDS, execute


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

"""FastAPI service: read-only analytics endpoints + editable exclusions + background refresh.

Run:  .venv/Scripts/python -m uvicorn mi.api:app --port 8000

The code is split by area; this file only wires the parts together and serves the dashboard:
  core        the app, database helpers and shared helpers      acquisition  campaigns, ad tagging health
  system      status, refresh jobs, data health                 people       profiles, users, cohorts, retention, audiences
  overview    overview, funnel, report table, insights          sessions     session list, filters, one session
  orders      orders, order analytics, basket lab               exclusions   rules to hide internal / test / bot traffic
  meta_ads    Meta Ads spend joined to sessions and orders      alerts       what changed this week, and the weekly summary
The API process owns the DuckDB file (single writer). Reads are not blocked by a rebuild (it is one transaction).
"""
from . import acquisition, alerts, chats, core, deeper, events, exclusions, journeys, logins, meta_ads, orders, overview, pain, people, sessions, system
from .config import ROOT
from .core import app

# Everything stays reachable as `mi.api.<name>` (tests and scripts use it): copy each part's names into this module.
for _part in (core, system, overview, acquisition, people, sessions, events, pain, logins, chats, deeper, journeys, orders, exclusions, meta_ads, alerts):
    globals().update({k: v for k, v in vars(_part).items() if not k.startswith("__")})

# ------------------------------------------------------------------ static dashboard (after `npm run build`); mounted last so it never shadows an /api route
from fastapi.staticfiles import StaticFiles  # noqa: E402

DIST = ROOT / "dashboard" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=str(DIST), html=True), name="dashboard")

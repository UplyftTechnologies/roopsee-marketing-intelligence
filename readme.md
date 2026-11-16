# Roopsee Marketing Intelligence

Local analytics for the `event_log` tracking table (570k+ rows) plus orders, users and quiz data in production Supabase.

```
Supabase (production, READ-ONLY REST)
   └─ mi/extract.py    parallel day-window pulls, incremental, idempotent
        └─ data/mi.duckdb  raw_* tables
             └─ mi/transform.py  SQL: identity stitching → sessions → checkout / orders → users_360 → cohorts / campaigns
                  └─ mi/api.py   FastAPI (+ serves the built dashboard)
                       └─ dashboard/   React + Recharts
```

## Quick start

**Double-click `start.bat`.** That's it. It sets up whatever is missing, starts the dashboard and opens
http://127.0.0.1:8000 in your browser. To stop: press `Ctrl+C` in its window, or double-click `stop.bat`.

What it does for you (each step is skipped when already done, so later starts take a few seconds):

1. checks Python 3.10+ and that `.env` has the production Supabase URL and key
2. creates `.venv` and installs the Python packages
3. builds the React dashboard (needs [Node.js LTS](https://nodejs.org/) once; rebuilds only when the UI source changed)
4. **first run only:** downloads your event data from Supabase (read-only, about 4–5 minutes), then builds the analytics tables
5. starts the server and opens the browser. If it is already running, it just opens the page

Needs on a new machine: **Python 3.10+** and **Node.js LTS** (Node only to build the UI), plus the `.env` file.

Options (also work as `python run.py ...`):

| Command | Does |
|---|---|
| `start.bat --refresh` | pull the newest events first, then start |
| `start.bat --no-browser` | don't open a browser tab |
| `start.bat --rebuild-ui` | force a rebuild of the dashboard UI |
| `set MI_PORT=8010` before starting | use another port if 8000 is taken |

Day to day you rarely need `--refresh`: the **Refresh data** button in the dashboard pulls only the new events
(about a minute) and rebuilds.

### Manual / developer commands

```powershell
.venv\Scripts\python -m mi.cli serve        # server only (UI must already be built)
.venv\Scripts\python -m mi.cli all          # extract + transform from the command line
cd dashboard; npm run dev                   # hot-reload UI on http://localhost:5173 (proxies /api to :8000)
```

CLI: `python -m mi.cli {extract | transform | all | serve}`. DuckDB allows one writer, so stop the dashboard
before using `extract` / `transform` from the CLI (or just use the buttons in the dashboard).

### Troubleshooting

| Message | Fix |
|---|---|
| "Python was not found" | install Python 3.10+ and tick **Add python.exe to PATH** |
| "Node.js is required once" | install the Node.js LTS from nodejs.org, then run again |
| "PRODUCT_SUPABASE_URL is missing" | add the production URL and service key to `.env` |
| "Port 8000 is used by another program" | close that program, or `set MI_PORT=8010` and start again |
| Page shows "No analytics tables yet" | press **Refresh data**, or run `start.bat --refresh` |

## Safety

- Only `PRODUCT_SUPABASE_URL` / `PRODUCT_SUPABASE_SERVICE_KEY` are read from `.env`. The client in `mi/supa.py` exposes
  **GET only** – nothing is ever written to production.
- `.env` and `data/` are git-ignored. `data/mi.duckdb` contains customer phone numbers and emails – keep it local.

## Exclusions (edit from the **Exclusions** tab)

Excluded traffic is flagged (`is_excluded`, `excl_reason`), never deleted. Add / edit / disable / delete rules for:
name, IP (supports `45.119.*`), session id, user id, browser (visitor) id, phone, email or `@domain`, host, country,
state, city, device, browser, source, campaign, channel, or any free text. Identity-type rules (user, browser, phone,
email, name) remove every session of that person. Every change re-applies automatically (~15 s).

Built-in rules (all editable): `staff_roles`, `admin_pages`, `dev_hosts`, `non_india`, `staff_orders`,
`@roopsee.com`, `@joinuplyft.com`, `qa_bot`.

## Definitions worth knowing

- **Session** = `session_id`. **Person** = logged-in account, or an anonymous browser (`visitor_id`); a browser is linked to an
  account from any event or `visitor_identity_links` row that carries both.
- **Channel** is derived per session: UTM params → gclid/fbclid → referrer → direct.
- **Order credited twice, on purpose**: to the session it happened in, and to the buyer's *first* visit (first touch).
- **Valid order** = status not `payment_cancelled` / `payment_pending`, and not a ₹1 test order.
- Event names changed across three tracking generations; `event_key()` in `mi/transform.py` maps them to one set
  (the **Data & ETL** tab lists every event name and what it maps to).

## Not built yet

Automated personalised message sending (MSG91 / WhatsApp). `users_360.segment` and the abandoned-checkout list are the inputs for it.

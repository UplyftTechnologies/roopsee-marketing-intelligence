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

## Run

```powershell
# one-time
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
cd dashboard; npm install; npm run build; cd ..

# every time
.venv\Scripts\python -m mi.cli serve        # http://127.0.0.1:8000
```

First load: `python -m mi.cli all` (≈ 2 min for the full backfill, then ≈ 15 s to transform), or press **Refresh data**
in the dashboard. After that, **Refresh data** pulls only new events.

Dev mode with hot reload: `uvicorn mi.api:app --port 8000` and `cd dashboard && npm run dev` (http://localhost:5173).

CLI: `python -m mi.cli {extract | transform | all | serve}`. DuckDB allows one writer, so stop `serve` before using
`extract` / `transform` from the CLI (or just use the buttons in the dashboard).

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

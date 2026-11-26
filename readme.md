# Roopsee Marketing Intelligence

Local analytics for the `event_log` tracking table (570k+ rows) plus orders, users and quiz data in production Supabase.

```
Supabase (production, READ-ONLY REST)
   └─ mi/extract.py    parallel day-window pulls, incremental, idempotent
        └─ data/mi.duckdb  raw_* tables
             └─ mi/transform.py  SQL: identity stitching → sessions → checkout / orders → users_360 → cohorts / campaigns
                  └─ mi/api.py   FastAPI (+ serves the built dashboard), split by area into the modules below
                       └─ dashboard/   React + Recharts
```

```
mi/core.py         the app, database helpers, shared helpers        mi/acquisition.py  campaigns, ad tagging health
mi/system.py       status, refresh jobs, data health                mi/people.py       profiles, users, cohorts, retention, audiences
mi/overview.py     overview, funnel, report table, insights         mi/sessions.py     session list, filters, one session
mi/orders.py       orders, order analytics, basket lab              mi/exclusions.py   hide internal / test / bot traffic
mi/meta_ads.py     Meta Ads joined to sessions and orders           mi/alerts.py       what changed this week, weekly summary
mi/payload.py      which event payload fields are kept              tests/             safety checks (see "Tests")
```

## Quick start (macOS, Linux, Windows – terminal only)

**You need:** Python 3.11+, Node.js LTS (only once, to build the UI) and the `.env` file in this folder.
On a Mac: `brew install python node`.

```bash
cd roopsee-marketing-intelligence
python3 run.py            # on Windows: python run.py
```

That one command sets up whatever is missing, starts the dashboard and opens http://127.0.0.1:8000 in your browser.
Stop it with **Ctrl+C** in that terminal (or `python3 run.py --stop` from another one).

What it does for you – each step is skipped once done, so later starts take a few seconds:

1. checks the Python version and that `.env` has the production Supabase URL and key
2. creates `.venv` and installs the Python packages
3. builds the React dashboard (rebuilds only when the UI source changed)
4. **first run only:** downloads your event data from Supabase (read-only, about 4–5 minutes), then builds the analytics tables
5. starts the server and opens the browser. If it is already running, it just opens the page

`.env` is not in git, so on a new machine copy it into this folder yourself.

| Command | Does |
|---|---|
| `python3 run.py --refresh` | pull the newest events first, then start |
| `python3 run.py --no-browser` | don't open a browser tab |
| `python3 run.py --rebuild-ui` | force a rebuild of the dashboard UI |
| `python3 run.py --stop` | stop a running dashboard |
| `MI_PORT=8010 python3 run.py` | use another port (Windows PowerShell: `$env:MI_PORT=8010; python run.py`) |

Day to day you rarely need `--refresh`: the **Refresh data** button in the dashboard pulls only the new events
(about a minute) and rebuilds. **Nothing updates by itself**: the top bar shows "Data as of …" (amber after 6 hours, red after a day)
so you can see how old the data is, and the dashboard keeps working while a refresh runs.

If the Supabase key is missing from `.env`, the dashboard still starts with the data you already have; only Refresh needs the key.

### Manual / developer commands

Use `.venv/bin/python` on macOS/Linux or `.venv\Scripts\python` on Windows:

```bash
.venv/bin/python -m mi.cli serve        # server only (UI must already be built)
.venv/bin/python -m mi.cli all          # extract + transform from the command line
cd dashboard && npm run dev             # hot-reload UI on http://localhost:5173 (proxies /api to :8000)
```

`python -m mi.cli {extract | transform | all | serve | access | slim | compact | purge}`:

| Command | Does |
|---|---|
| `access` | says which Supabase key is in use and what it can do (never prints the key) |
| `slim` | one-off: removes duplicated fields and tracking plumbing from stored event payloads, then shrinks the file (a 967 MB file became 390 MB). Everything can be restored by a normal pull |
| `compact` | shrinks the file after deleting data |
| `purge 365 [--yes]` | retention: deletes raw events older than N days (dry run unless `--yes`) |

DuckDB allows one writer, so stop the dashboard
before using `extract` / `transform` from the command line (or just use the buttons in the dashboard).

### Troubleshooting

| Message | Fix |
|---|---|
| `command not found: python` (macOS) | use `python3` – macOS has no plain `python` |
| "Python 3.11 or newer is required" | macOS: `brew install python`; otherwise https://www.python.org/downloads/ (the macOS built-in python3 is usually too old) |
| "Node.js is required once" | macOS: `brew install node`; otherwise https://nodejs.org/ (LTS), then run again |
| "no Supabase key found" / "PRODUCT_SUPABASE_URL is missing" | add the production URL and a key to `.env`: `PRODUCT_SUPABASE_READ_KEY` (read-only, best: `docs/read-only-access.md`) or `PRODUCT_SUPABASE_SERVICE_KEY`. The dashboard still opens without it; only Refresh needs it |
| "Port 8000 is used by another program" | close that program, or start with `MI_PORT=8010` |
| Page shows "No analytics tables yet" | press **Refresh data**, or run `python3 run.py --refresh` |

## Optional: Meta Ads

Add these to `.env` (never commit it) and press **Refresh**; the **Meta Ads** page then shows spend, clicks, CTR, CPC and what your own tracking says the spend brought in.

```
META_ACCESS_TOKEN=<token with the ads_read permission>
META_AD_ACCOUNT_IDS=act_1234567890,act_9876543210   # optional; default = every account the token can list that has spent money
META_SINCE=2026-06-01                               # optional first day to pull
```

- **Read-only.** The client only sends GET requests, the token travels in a header and is redacted from every error message and API response.
- A normal user token expires after about 60 days. Create a **System User** token in Business Settings (it does not expire) for production use.
- An ad account can be readable without appearing in the token's account list (for example a boosted-Instagram-post account). If a campaign id in your UTM tags is not matched, look it up in the Graph API and add its account to `META_AD_ACCOUNT_IDS`.
- Campaign matching uses the id in `utm_campaign` (or the ad-set / ad id). Put this in each ad's URL parameters so every click carries real ids: `utm_source=facebook&utm_medium=paid_social&utm_campaign={{campaign.id}}&utm_content={{ad.id}}&utm_term={{adset.id}}`

## Price intelligence (competitor prices)

The **Price intelligence** tab compares every product in the product sheet (`master_products`) with its live **regular** price on
**Nykaa, Tira and Purplle**: where we are dearer or cheapest, by brand and category, revenue at risk, price-sensitive products, competitors
out of stock, price changes and history. **Refresh prices** (on the tab) reads the latest prices; from a terminal:
`.venv/Scripts/python -m mi.cli prices [nykaa|tira|purplle]` (stop the dashboard first, DuckDB has one writer).

- **What is read:** only public product pages and the sitemaps each site lists in its robots.txt (no search pages, no logins), one page at a
  time per site with a 3-4 s pause. A full refresh takes about 15-20 minutes; the first one also loads each site's product list (refreshed weekly).
- **Matching:** the link in the sheet when it points at the site (nykaaman.com links are read on nykaa.com); else brand + name + size from the
  site's product list. Purplle pages carry the barcode, so a Purplle match is automatic only when it equals `bar_code` in the sheet.
  Anything uncertain waits in **Review matches** (confirm, reject or paste the link); decisions are kept.
- **Our price** is the sheet's Selling Price / MRP. The hand-typed `Nykaa Price` / `Tira Price` / `Broadway Price` columns are not used.
- **Storage**: prices are stored in `data/mi.duckdb` (`price_matches`, `price_snapshots`, `price_own`, `price_runs`, `price_index`),
  which a data rebuild never drops. Optionally they are **shared between computers** through Supabase: see [docs/price-sync.md](docs/price-sync.md).
  That is the only thing the dashboard ever writes to Supabase, it is off unless `PRICES_SUPABASE_KEY` is set, and the key only reaches the `mi_price_*` tables.
- Pages are fetched with [Scrapling](https://github.com/D4Vinci/Scrapling) (`pip install -r requirements.txt`; no browser download is needed).
  When a site changes its pages, its pages fail with "layout not recognised" in the Refresh log: the readers are in `mi/price_sites.py`,
  and `tests/test_prices.py` checks them on saved pages (`tests/fixtures/prices`).

## Sharing exclusions

**Exclusions → Share your exclusion list** downloads your rules as JSON or CSV; a teammate opens **Import a list…** on their dashboard and only the missing rules are added. The file contains staff phone numbers, emails and IPs: send it privately.

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

## Tests

```
.venv\Scripts\python -m unittest discover -s tests -v     (macOS/Linux: .venv/bin/python)
```

27 checks for things that must always hold: "did" + "did not" adds up to every session, the same order count on every screen,
pages of a list never repeat a row, every endpoint answers, trimming never drops a field the pipeline reads. They read a copy of
the data, so they are safe to run while the dashboard is open (if the file is locked, point `MI_DB_PATH` at a copy).

`tests/snapshot.py` saves every endpoint's answer to a folder so two versions of the code can be compared (`--diff before after`).

## Keeping the key safe

The pipeline only reads, but a service-role key can do anything. Use a read-only key instead: `docs/read-only-access.md`
(10 minutes, once) and check with `python -m mi.cli access`.

## Definitions worth knowing

Every number is explained in the dashboard: **Admin → Data dictionary**. The short version:


- **Session** = `session_id`. **Person** = logged-in account, or an anonymous browser (`visitor_id`); a browser is linked to an
  account from any event or `visitor_identity_links` row that carries both.
- **Channel** is derived per session: UTM params → gclid/fbclid → referrer → direct.
- **Order credited twice, on purpose**: to the session it happened in, and to the buyer's *first* visit (first touch).
- **Valid order** = status not `payment_cancelled` / `payment_pending`, and not a ₹1 test order. Each sale also has a payment state
  (confirmed / COD pending / unconfirmed / conflicting); unconfirmed ones are flagged "at risk" but still counted.
- **Repeated events**: the tracker often fires one action several times; repeats within 2 seconds are flagged (`is_dup`) and left out of counts, never deleted.
- **Time spent** counts only gaps of 30 minutes or less between events (a session id can live for weeks).
- **A rebuild never freezes the dashboard**: it runs as one transaction and readers keep seeing the previous tables until it commits.
  Results are deterministic: rebuilding the same data twice gives identical numbers.
- Event names changed across three tracking generations; `event_key()` in `mi/transform.py` maps them to one set
  (the **Data & ETL** tab lists every event name and what it maps to).

## Not built yet

Automated personalised message sending (MSG91 / WhatsApp). `users_360.segment` and the abandoned-checkout list are the inputs for it.

# Sharing price data through Supabase

By default the Price intelligence tab keeps everything on one computer. With sharing on, every computer uses the same prices, matches and decisions,
stored in Supabase. The rest of the dashboard still only reads from Supabase: sharing writes to the `mi_price_*` tables and nothing else.

## Set up once per project

1. Supabase → **SQL Editor** → paste all of [`price-sync.sql`](price-sync.sql) → **Run** (if asked, "Run and enable RLS").
   It is safe to run again, and must be run again after the file changes.
2. Run the two **check queries** at the end of the file and read the results.

## Set up on each computer

```
.venv\Scripts\python tools\make_price_key.py
.venv\Scripts\python -m mi.cli prices-check
```

The first asks for the project's JWT secret (typing is hidden, never saved) and the anon public key, and adds the limited key to `.env`.
The second makes one read to prove the key works. Restart the dashboard. The computers need not all refresh prices, but each needs the key to see them.

Then, on a computer that collected prices before sharing was on: open **Price intelligence** and press **Upload this computer's history**.
Nothing from before is sent until you press it.

## How it stays consistent

| | |
|---|---|
| One refresh at a time | A lock in Supabase. Others are told who is refreshing. It lapses 5 minutes after the computer stops answering |
| No duplicates | Every run has a unique id; one reading per run, product and site; sending again changes nothing |
| History is not edited | The key cannot change or delete readings |
| Decisions | Each match has a version. A decision made on an old screen is refused; an automatic result cannot overwrite a person's |
| Clocks | Times are worked out by the database |
| No connection | Downloaded prices can be viewed. New refreshes and decisions are refused. Readings of a run that lost the connection wait and are sent with the next sync |
| Old code | `mi_price_meta.min_client` can refuse dashboards that are too old |

## Keys

- The key only works on the `mi_price_*` tables. Whoever holds it can add price data or hold the refresh lock, so give it only to people who need the shared prices.
- It lasts a year: run `make_price_key.py` again to renew it.
- If it leaks, Supabase → roll the JWT secret (this also changes the project's other keys), or revoke the role's access: `revoke mi_price_writer from authenticator;`

## Tests

`tests/price_sync/` runs the SQL file and two simulated computers on a throwaway local Postgres (no Supabase, no real data). See its README.

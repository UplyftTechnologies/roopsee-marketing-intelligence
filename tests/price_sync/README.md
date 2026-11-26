# Sharing tests

Run `docs/price-sync.sql` and the sharing code against a throwaway Postgres on this computer ([PGlite](https://pglite.dev)). No Supabase, no real data.

    cd tests\price_sync
    npm install
    npm run sql                      # the database script: permissions, lock, versions, removal

    npm run bridge                   # terminal 1: a stand-in for Supabase's web API on port 54999 (restart it before each run)
    ..\..\.venv\Scripts\python two_computers.py     # terminal 2: two simulated computers

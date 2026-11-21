# Read-only access to production data

The dashboard only ever **reads** from Supabase (`mi/supa.py` sends GET requests and nothing else). But the key it uses today,
`PRODUCT_SUPABASE_SERVICE_KEY`, is Supabase's **service-role key**: it bypasses every security rule and can read, change and delete anything.
If that key leaked (a screenshot, a backup of `.env`, a shared laptop) the whole production database would be exposed.

A **read-only key** limits the damage to "someone can read the eight tables the dashboard reads". This takes about 10 minutes, once.

## What the dashboard reads

`event_log`, `users`, `orders`, `quiz_results`, `visitor_identity_links`, `customer_address`, `roopsee_products`, `master_products` and, for the Roop chats page, `assistant_chat_logs` (only its question / answer columns; it holds personal skin details, so keep `data/` local). If a read-only key cannot read it, the refresh carries on and the Roop chats page just shows no data.

## Steps

### 1. Create a database role that can only read those tables
Supabase dashboard → **SQL Editor** → run:

```sql
create role mi_reader nologin noinherit;
grant usage on schema public to mi_reader;
grant select on public.event_log, public.users, public.orders, public.quiz_results,
               public.visitor_identity_links, public.customer_address,
               public.roopsee_products, public.master_products, public.assistant_chat_logs to mi_reader;
grant mi_reader to authenticator;   -- lets the API switch to this role

-- only needed for tables that have Row Level Security switched on (check Table Editor → RLS):
create policy mi_reader_select on public.event_log              for select to mi_reader using (true);
create policy mi_reader_select on public.users                  for select to mi_reader using (true);
create policy mi_reader_select on public.orders                 for select to mi_reader using (true);
create policy mi_reader_select on public.quiz_results           for select to mi_reader using (true);
create policy mi_reader_select on public.visitor_identity_links for select to mi_reader using (true);
create policy mi_reader_select on public.customer_address       for select to mi_reader using (true);
create policy mi_reader_select on public.roopsee_products       for select to mi_reader using (true);
create policy mi_reader_select on public.master_products        for select to mi_reader using (true);
create policy mi_reader_select on public.assistant_chat_logs    for select to mi_reader using (true);
```

(If a table has no RLS, its `create policy` line is harmless to skip. If it errors, skip that line.)

### 2. Make a key for that role
Supabase → **Project Settings → API → JWT Secret** (reveal it). Then, on your computer:

```
.venv\Scripts\python tools\make_read_key.py
```

Paste the JWT secret when asked (it is not stored or shown). The script prints a long token that represents `mi_reader`, valid for 10 years.

### 3. Use it
In `.env`, add the token and take the service key out:

```
PRODUCT_SUPABASE_READ_KEY=<the token>
# PRODUCT_SUPABASE_SERVICE_KEY=   <- remove or leave commented
```

`PRODUCT_SUPABASE_READ_KEY` is preferred over `PRODUCT_SUPABASE_ANON_KEY` and `PRODUCT_SUPABASE_SERVICE_KEY` when several are set.

### 4. Check it
```
.venv\Scripts\python -m mi.cli access
```
shows which key is in use and its role (`mi_reader` is what you want; `service_role` means full access). It never prints the key, and it does not contact production.
Then press **Refresh** in the dashboard: if any table cannot be read you get a clear error naming the table.

## If you used the anon key instead
Supabase's `anon` key is public by design and protected by Row Level Security. It only works if you wrote policies that let `anon` read these tables, which would also let anyone on the internet read them. Prefer the `mi_reader` role above.

## Rotating
If the service key was ever pasted anywhere else (chat, email, screenshots), rotate it: Project Settings → API → **Generate new JWT secret** (this invalidates every key, so re-create the `mi_reader` token afterwards and update any other app that uses the old keys).

-- Shared price data for the Price intelligence tab, in Supabase.
--
-- REVIEW FIRST, then run the whole file once in the Supabase SQL Editor. It is safe to run again (nothing is dropped, no data is replaced).
--
-- What it creates, all named mi_price_*:
--   mi_price_runs        one row per price run, from any computer
--   mi_price_snapshots   every price read (only ever added to)
--   mi_price_own         our own price at each run (only ever added to)
--   mi_price_matches     which shop page is which product, with a version number per row
--   mi_price_lock        one row: who is refreshing prices right now
--   mi_price_meta        the oldest dashboard version allowed to write
--   mi_price_* functions the ONLY way to write
--   mi_price_writer      a role that can read the tables above and call those functions, and nothing else
--
-- It does not read, change or reference any existing table. The website's public (anon) and signed-in (authenticated) keys get no access.
-- To remove everything again, see the end of the file.

begin;

-- ------------------------------------------------------------------ the role
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'mi_price_writer') then
    create role mi_price_writer nologin noinherit;
  end if;
end $$;
grant usage on schema public to mi_price_writer;
grant mi_price_writer to authenticator;   -- lets the API switch to this role when a key names it

-- ------------------------------------------------------------------ tables
create table if not exists public.mi_price_meta (key text primary key, value text not null);
insert into public.mi_price_meta (key, value) values ('min_client', '1') on conflict (key) do nothing;

create table if not exists public.mi_price_runs (
  run_id      uuid primary key,                       -- made by the computer that runs it, so two computers never clash
  host        text not null,                          -- which computer / person
  started_at  timestamptz not null default now(),
  finished_at timestamptz,
  status      text not null default 'running' check (status in ('running', 'done', 'done with problems', 'stopped', 'failed')),
  sites       text,
  summary     jsonb,
  message     text
);

create table if not exists public.mi_price_snapshots (
  run_id      uuid not null references public.mi_price_runs (run_id),
  product_id  text not null,
  site        text not null check (site in ('nykaa', 'tira', 'purplle')),
  url         text,
  fetched_at  timestamptz not null,                   -- worked out by the database from "how long ago", so a wrong computer clock does not matter
  received_at timestamptz not null default now(),     -- when it arrived here: what a computer uses to download only what is new
  ok          boolean not null,
  error       text,
  price       numeric check (price is null or price >= 0),
  mrp         numeric check (mrp is null or mrp >= 0),
  offer_price numeric,
  in_stock    boolean,
  stock_qty   bigint,
  discount    text,
  page_name   text,
  page_size   text,
  primary key (run_id, product_id, site)              -- sending the same reading twice changes nothing
);
create index if not exists mi_price_snapshots_latest   on public.mi_price_snapshots (product_id, site, fetched_at desc);
create index if not exists mi_price_snapshots_received on public.mi_price_snapshots (received_at);

create table if not exists public.mi_price_own (
  run_id      uuid not null references public.mi_price_runs (run_id),
  product_id  text not null,
  price       numeric,
  mrp         numeric,
  fetched_at  timestamptz not null,
  received_at timestamptz not null default now(),
  primary key (run_id, product_id)
);
create index if not exists mi_price_own_received on public.mi_price_own (received_at);

create table if not exists public.mi_price_matches (
  product_id   text not null,
  site         text not null check (site in ('nykaa', 'tira', 'purplle')),
  url          text,
  status       text not null check (status in ('matched', 'review', 'none', 'rejected')),
  method       text,                                  -- 'you' = a person decided it
  confidence   numeric,
  matched_name text,
  candidates   jsonb not null default '[]'::jsonb,
  rejected     jsonb not null default '[]'::jsonb,
  checked_at   timestamptz,
  version      integer not null default 1,            -- goes up with every change; a save must name the version it saw
  updated_at   timestamptz not null default now(),
  updated_by   text,
  primary key (product_id, site)
);
create index if not exists mi_price_matches_updated on public.mi_price_matches (updated_at);

create table if not exists public.mi_price_lock (
  id          boolean primary key default true check (id),   -- there is exactly one row
  holder      text,
  token       uuid,
  run_id      uuid,
  acquired_at timestamptz,
  expires_at  timestamptz
);
insert into public.mi_price_lock (id) values (true) on conflict (id) do nothing;

-- ------------------------------------------------------------------ functions (the only way to write)
create or replace function public.mi_price_require(p_client integer) returns void
language plpgsql security definer set search_path = public, pg_temp as $$
declare need integer;
begin
  select value::integer into need from mi_price_meta where key = 'min_client';
  if coalesce(p_client, 0) < need then
    raise exception 'This dashboard is too old to write prices (version %, needs %). Pull the latest code.', coalesce(p_client, 0), need using errcode = 'P0001';
  end if;
end $$;

-- Take the right to refresh prices. Only one computer holds it; it lapses 5 minutes after the last renewal.
create or replace function public.mi_price_lock_acquire(p_client integer, p_host text, p_run uuid, p_sites text) returns jsonb
language plpgsql security definer set search_path = public, pg_temp as $$
declare got mi_price_lock;
begin
  perform mi_price_require(p_client);
  update mi_price_lock set holder = p_host, token = gen_random_uuid(), run_id = p_run, acquired_at = now(), expires_at = now() + interval '5 minutes'
   where id and (token is null or expires_at < now())
  returning * into got;
  if not found then
    select * into got from mi_price_lock where id;
    return jsonb_build_object('ok', false, 'holder', got.holder, 'since', got.acquired_at, 'expires', got.expires_at);
  end if;
  -- a run that still says "running" lost its lock: its computer closed or went offline
  update mi_price_runs set status = 'stopped', finished_at = now(), message = 'no sign of life from that computer' where status = 'running' and run_id <> p_run;
  insert into mi_price_runs (run_id, host, sites) values (p_run, p_host, p_sites)
    on conflict (run_id) do update set status = 'running', finished_at = null, message = null;
  return jsonb_build_object('ok', true, 'token', got.token, 'expires', got.expires_at);
end $$;

-- Keep holding it. false = someone else has taken it since: stop the run.
create or replace function public.mi_price_lock_renew(p_token uuid) returns boolean
language plpgsql security definer set search_path = public, pg_temp as $$
begin
  update mi_price_lock set expires_at = now() + interval '5 minutes' where id and token = p_token;
  return found;
end $$;

-- Close the run and let the next computer in.
create or replace function public.mi_price_finish(p_token uuid, p_status text, p_summary jsonb, p_message text) returns boolean
language plpgsql security definer set search_path = public, pg_temp as $$
declare r uuid;
begin
  select run_id into r from mi_price_lock where id and token = p_token for update;
  if not found then return false; end if;
  update mi_price_runs set status = p_status, finished_at = now(), summary = p_summary, message = p_message where run_id = r;
  update mi_price_lock set holder = null, token = null, run_id = null, acquired_at = null, expires_at = null where id;
  return true;
end $$;

-- Add price readings of a run. Each row says how many seconds ago it was read. Rows already here are left as they are.
create or replace function public.mi_price_add_snapshots(p_client integer, p_run uuid, p_rows jsonb) returns integer
language plpgsql security definer set search_path = public, pg_temp as $$
declare n integer;
begin
  perform mi_price_require(p_client);
  insert into mi_price_snapshots (run_id, product_id, site, url, fetched_at, ok, error, price, mrp, offer_price, in_stock, stock_qty, discount, page_name, page_size)
  select p_run, x.product_id, x.site, x.url, now() - make_interval(secs => greatest(coalesce(x.age_seconds, 0), 0)), x.ok, x.error, x.price, x.mrp, x.offer_price,
         x.in_stock, x.stock_qty, x.discount, x.page_name, x.page_size
    from jsonb_to_recordset(p_rows) as x(product_id text, site text, url text, age_seconds double precision, ok boolean, error text, price numeric, mrp numeric,
                                         offer_price numeric, in_stock boolean, stock_qty bigint, discount text, page_name text, page_size text)
  on conflict (run_id, product_id, site) do nothing;
  get diagnostics n = row_count;
  return n;
end $$;

-- Add our own prices as they were at a run.
create or replace function public.mi_price_add_own(p_client integer, p_run uuid, p_rows jsonb) returns integer
language plpgsql security definer set search_path = public, pg_temp as $$
declare n integer;
begin
  perform mi_price_require(p_client);
  insert into mi_price_own (run_id, product_id, price, mrp, fetched_at)
  select p_run, x.product_id, x.price, x.mrp, now() - make_interval(secs => greatest(coalesce(x.age_seconds, 0), 0))
    from jsonb_to_recordset(p_rows) as x(product_id text, price numeric, mrp numeric, age_seconds double precision)
  on conflict (run_id, product_id) do nothing;
  get diagnostics n = row_count;
  return n;
end $$;

-- Save one match. p_expected = the version the computer saw (0 = it saw none). Refused when the row has changed since,
-- or when an automatic result would overwrite a person's decision. Either way the current row comes back.
create or replace function public.mi_price_save_match(p_client integer, p_row jsonb, p_expected integer, p_by text) returns jsonb
language plpgsql security definer set search_path = public, pg_temp as $$
declare
  cur mi_price_matches;
  n mi_price_matches;
begin
  perform mi_price_require(p_client);
  n := jsonb_populate_record(null::mi_price_matches, p_row);
  n.candidates := coalesce(n.candidates, '[]'::jsonb);
  n.rejected := coalesce(n.rejected, '[]'::jsonb);
  select * into cur from mi_price_matches where product_id = n.product_id and site = n.site for update;
  if not found then
    if coalesce(p_expected, 0) <> 0 then return jsonb_build_object('saved', false, 'reason', 'gone'); end if;
    n.version := 1; n.updated_at := now(); n.updated_by := p_by;
    insert into mi_price_matches select (n).* on conflict (product_id, site) do nothing;
    if found then return jsonb_build_object('saved', true, 'row', to_jsonb(n)); end if;
    select * into cur from mi_price_matches where product_id = n.product_id and site = n.site;   -- someone inserted it a moment ago
    return jsonb_build_object('saved', false, 'reason', 'changed', 'row', to_jsonb(cur));
  end if;
  if cur.version is distinct from p_expected then return jsonb_build_object('saved', false, 'reason', 'changed', 'row', to_jsonb(cur)); end if;
  -- "by_person" marks a change a person made on screen, such as "Look again", which hands the row back to the automatic search
  if cur.method = 'you' and n.method is distinct from 'you' and coalesce(p_row ->> 'by_person', '') <> 'true' then
    return jsonb_build_object('saved', false, 'reason', 'decided by a person', 'row', to_jsonb(cur));
  end if;
  update mi_price_matches set url = n.url, status = n.status, method = n.method, confidence = n.confidence, matched_name = n.matched_name, candidates = n.candidates,
         rejected = n.rejected, checked_at = n.checked_at, version = cur.version + 1, updated_at = now(), updated_by = p_by
   where product_id = n.product_id and site = n.site
  returning * into cur;
  return jsonb_build_object('saved', true, 'row', to_jsonb(cur));
end $$;

-- First upload of a computer's existing history: register its old runs ...
create or replace function public.mi_price_import_run(p_client integer, p_run uuid, p_host text, p_status text, p_age_seconds double precision, p_sites text) returns void
language plpgsql security definer set search_path = public, pg_temp as $$
begin
  perform mi_price_require(p_client);
  insert into mi_price_runs (run_id, host, started_at, finished_at, status, sites, message)
  values (p_run, p_host, now() - make_interval(secs => greatest(p_age_seconds, 0)), now() - make_interval(secs => greatest(p_age_seconds, 0)),
          case when p_status = 'running' then 'stopped' else p_status end, p_sites, 'uploaded from a computer''s own history')
  on conflict (run_id) do nothing;
end $$;

-- ... and its matches: a person's decision beats an automatic one; between two of the same kind, the newer one wins.
create or replace function public.mi_price_import_match(p_client integer, p_row jsonb, p_age_seconds double precision, p_by text) returns boolean
language plpgsql security definer set search_path = public, pg_temp as $$
declare
  cur mi_price_matches;
  n mi_price_matches;
begin
  perform mi_price_require(p_client);
  n := jsonb_populate_record(null::mi_price_matches, p_row);
  n.candidates := coalesce(n.candidates, '[]'::jsonb);
  n.rejected := coalesce(n.rejected, '[]'::jsonb);
  n.updated_at := now() - make_interval(secs => greatest(coalesce(p_age_seconds, 0), 0));
  n.updated_by := p_by;
  select * into cur from mi_price_matches where product_id = n.product_id and site = n.site for update;
  if not found then
    n.version := 1;
    insert into mi_price_matches select (n).* on conflict (product_id, site) do nothing;
    return found;
  end if;
  if (cur.method = 'you' and n.method is distinct from 'you')
     or ((cur.method is not distinct from 'you') = (n.method is not distinct from 'you') and cur.updated_at >= n.updated_at) then
    return false;
  end if;
  update mi_price_matches set url = n.url, status = n.status, method = n.method, confidence = n.confidence, matched_name = n.matched_name, candidates = n.candidates,
         rejected = n.rejected, checked_at = n.checked_at, version = cur.version + 1, updated_at = n.updated_at, updated_by = n.updated_by
   where product_id = n.product_id and site = n.site;
  return true;
end $$;

-- ------------------------------------------------------------------ who may do what
-- Supabase gives new tables and functions to the public keys by default: take that away, and give the new role only reading and the functions above.
do $$
declare t text; f record;
begin
  foreach t in array array['mi_price_meta', 'mi_price_runs', 'mi_price_snapshots', 'mi_price_own', 'mi_price_matches', 'mi_price_lock'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on table public.%I from public, anon, authenticated, mi_price_writer', t);
    execute format('grant select on table public.%I to mi_price_writer', t);
    execute format('drop policy if exists mi_price_read on public.%I', t);
    execute format('create policy mi_price_read on public.%I for select to mi_price_writer using (true)', t);
  end loop;
  for f in select p.oid::regprocedure as sig, p.proname from pg_proc p join pg_namespace s on s.oid = p.pronamespace
            where s.nspname = 'public' and p.proname like 'mi\_price\_%' loop
    execute format('revoke all on function %s from public, anon, authenticated', f.sig);
    if f.proname <> 'mi_price_require' then execute format('grant execute on function %s to mi_price_writer', f.sig); end if;
  end loop;
end $$;

commit;

-- ------------------------------------------------------------------ CHECK (run these two after the script, and read the results)
-- 1. Every table the new role can touch. Expected: only mi_price_* tables, with SELECT only.
--      select table_schema, table_name, string_agg(privilege_type, ', ' order by privilege_type) as can
--        from information_schema.role_table_grants where grantee in ('mi_price_writer', 'PUBLIC') and table_schema = 'public' group by 1, 2 order by 1, 2;
-- 2. Functions of your database that the new role could also call because they are open to everyone. Expected: only mi_price_* rows.
--    Any other row, above all one with security_definer = true, is worth a look before you create the key.
--      select p.oid::regprocedure as function, p.prosecdef as security_definer from pg_proc p join pg_namespace s on s.oid = p.pronamespace
--       where s.nspname = 'public' and has_function_privilege('mi_price_writer', p.oid, 'execute') order by 2 desc, 1;

-- ------------------------------------------------------------------ REMOVE (only if you want it all gone; this deletes the shared price data)
--   drop function if exists public.mi_price_import_match, public.mi_price_import_run, public.mi_price_save_match, public.mi_price_add_own,
--        public.mi_price_add_snapshots, public.mi_price_finish, public.mi_price_lock_renew, public.mi_price_lock_acquire, public.mi_price_require;
--   drop table if exists public.mi_price_snapshots, public.mi_price_own, public.mi_price_matches, public.mi_price_lock, public.mi_price_runs, public.mi_price_meta;
--   revoke usage on schema public from mi_price_writer; drop role if exists mi_price_writer;

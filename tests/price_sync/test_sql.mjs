// Run docs/price-sync.sql on a throwaway Postgres (PGlite) set up like Supabase, and try the situations the design promises to handle.
import { PGlite } from '@electric-sql/pglite'
import { readFileSync } from 'node:fs'
import assert from 'node:assert/strict'

const sql = readFileSync(new URL('../../docs/price-sync.sql', import.meta.url), 'utf8')
const db = new PGlite()
await db.exec(`
  create role anon nologin; create role authenticated nologin; create role authenticator nologin;
  -- Supabase's default: new tables and functions in public are open to the public keys
  alter default privileges in schema public grant all on tables to anon, authenticated;
  alter default privileges in schema public grant execute on functions to anon, authenticated;
  create table public.orders (id int primary key, phone text);
`)
await db.exec(sql)
await db.exec(sql)  // running it twice must be harmless

let passed = 0
const as = async (role, fn) => { await db.exec(`set role ${role}`); try { return await fn() } finally { await db.exec('reset role') } }
const one = async (q, a = []) => (await db.query(q, a)).rows[0]
const refused = async (role, q, a = [], like = /permission denied/) => { await assert.rejects(as(role, () => db.query(q, a)), like) }
const test = async (name, fn) => { await fn(); passed += 1; console.log('ok  ', name) }
const W = 'mi_price_writer'
const R1 = '11111111-1111-1111-1111-111111111111', R2 = '22222222-2222-2222-2222-222222222222', R3 = '33333333-3333-3333-3333-333333333333'
const lock = (host, run) => as(W, async () => (await one('select mi_price_lock_acquire(1, $1, $2, $3) as r', [host, run, 'nykaa'])).r)
const snap = (run, rows) => as(W, async () => (await one('select mi_price_add_snapshots(1, $1, $2::jsonb) as n', [run, JSON.stringify(rows)])).n)
const save = (row, expected, by) => as(W, async () => (await one('select mi_price_save_match(1, $1::jsonb, $2, $3) as r', [JSON.stringify(row), expected, by])).r)
const imp = (row, age, by) => as(W, async () => (await one('select mi_price_import_match(1, $1::jsonb, $2, $3) as r', [JSON.stringify(row), age, by])).r)
const M = { product_id: 'RS/F/1', site: 'nykaa', url: 'https://www.nykaa.com/a/p/1', status: 'matched', method: 'name', confidence: 0.9 }

await test('the writer cannot reach anything else, nor write the price tables directly', async () => {
  await refused(W, 'select * from orders')
  await refused(W, 'delete from mi_price_snapshots')
  await refused(W, "update mi_price_matches set status = 'none'")
  await refused(W, "insert into mi_price_runs (run_id, host) values (gen_random_uuid(), 'x')")
  await refused(W, 'delete from mi_price_runs')
  await refused(W, "update mi_price_meta set value = '0'")
})
await test('the public website keys get nothing', async () => {
  for (const role of ['anon', 'authenticated']) {
    await refused(role, 'select * from mi_price_matches')
    await refused(role, 'select * from mi_price_snapshots')
    await refused(role, "select mi_price_lock_acquire(1, 'x', gen_random_uuid(), 'nykaa')")
    await refused(role, 'select mi_price_add_snapshots(1, gen_random_uuid(), \'[]\'::jsonb)')
    await refused(role, "select mi_price_save_match(1, '{}'::jsonb, 0, 'x')")
  }
})
let t1
await test('only one computer can refresh at a time', async () => {
  t1 = await lock('asha-pc', R1)
  assert.equal(t1.ok, true)
  const b = await lock('ravi-pc', R2)
  assert.equal(b.ok, false); assert.equal(b.holder, 'asha-pc')
})
await test('readings are added once, and their time comes from the database', async () => {
  const rows = [{ product_id: 'RS/F/1', site: 'nykaa', ok: true, price: 900, age_seconds: 3600 }, { product_id: 'RS/F/2', site: 'nykaa', ok: false, error: 'HTTP 500', age_seconds: -999 }]
  assert.equal(await snap(R1, rows), 2)
  assert.equal(await snap(R1, rows), 0)
  assert.equal(await snap(R1, [{ ...rows[0], price: 1 }]), 0)  // history is not edited
  assert.equal(Number((await one("select price from mi_price_snapshots where product_id = 'RS/F/1'")).price), 900)
  assert.ok((await one("select extract(epoch from now() - fetched_at) as s from mi_price_snapshots where product_id = 'RS/F/1'")).s >= 3599)
  assert.ok((await one("select fetched_at <= now() as ok from mi_price_snapshots where product_id = 'RS/F/2'")).ok)  // never in the future
  assert.equal(await as(W, async () => (await one("select mi_price_add_own(1, $1, '[{\"product_id\":\"RS/F/1\",\"price\":1000,\"mrp\":1200}]') as n", [R1])).n), 1)
})
await test('a silent computer loses the lock, and finds out', async () => {
  await db.exec("update mi_price_lock set expires_at = now() - interval '1 second'")
  const b = await lock('ravi-pc', R2)
  assert.equal(b.ok, true)
  assert.equal((await one('select status from mi_price_runs where run_id = $1', [R1])).status, 'stopped')
  assert.equal(await as(W, async () => (await one('select mi_price_lock_renew($1) as r', [t1.token])).r), false)
  assert.equal(await as(W, async () => (await one("select mi_price_finish($1, 'done', '{}', null) as r", [t1.token])).r), false)
  assert.equal(await snap(R1, [{ product_id: 'RS/F/3', site: 'tira', ok: true, price: 5 }]), 1)  // what it had read can still be sent
  assert.equal(await as(W, async () => (await one('select mi_price_lock_renew($1) as r', [b.token])).r), true)
  assert.equal(await as(W, async () => (await one("select mi_price_finish($1, 'done', '{\"ok\":1}', null) as r", [b.token])).r), true)
  assert.equal((await lock('asha-pc', R3)).ok, true)
})
await test('a save based on an old version is refused and shows the current row', async () => {
  const a = await save(M, 0, 'asha'); assert.equal(a.saved, true); assert.equal(a.row.version, 1)
  const b = await save({ ...M, status: 'review' }, 0, 'ravi'); assert.deepEqual([b.saved, b.reason, b.row.version], [false, 'changed', 1])
  const c = await save({ ...M, status: 'rejected', method: 'you', url: null, rejected: [M.url] }, 1, 'ravi'); assert.deepEqual([c.saved, c.row.version, c.row.updated_by], [true, 2, 'ravi'])
  const d = await save({ ...M, status: 'matched', method: 'you' }, 1, 'asha'); assert.deepEqual([d.saved, d.reason, d.row.updated_by], [false, 'changed', 'ravi'])
})
await test('an automatic result never overwrites a person; a person can change it', async () => {
  const a = await save(M, 2, 'job'); assert.deepEqual([a.saved, a.reason], [false, 'decided by a person'])
  const b = await save({ ...M, method: 'you' }, 2, 'asha'); assert.equal(b.saved, true); assert.equal(b.row.version, 3)
  assert.equal((await save({ ...M, product_id: 'nope' }, 4, 'x')).reason, 'gone')
})
await test('first upload: a person beats the job, otherwise the newer wins', async () => {
  const x = { ...M, product_id: 'RS/F/9' }
  assert.equal(await imp(x, 500, 'a'), true)
  assert.equal(await imp({ ...x, url: 'older' }, 900, 'b'), false)
  assert.equal(await imp({ ...x, url: 'newer' }, 100, 'b'), true)
  assert.equal(await imp({ ...x, url: 'person', method: 'you' }, 5000, 'c'), true)   // old, but a person's
  assert.equal(await imp({ ...x, url: 'job-again' }, 1, 'a'), false)
  assert.equal(await imp({ ...x, url: 'person-newer', method: 'you' }, 10, 'd'), true)
  assert.equal((await one("select url from mi_price_matches where product_id = 'RS/F/9'")).url, 'person-newer')
  await as(W, () => db.query("select mi_price_import_run(1, gen_random_uuid(), 'a', 'running', 86400, 'nykaa')"))
  assert.equal((await one("select count(*)::int as n from mi_price_runs where status = 'running'")).n, 1)  // only the live one
})
await test('bad data is refused', async () => {
  await assert.rejects(snap(R3, [{ product_id: 'p', site: 'amazon', ok: true }]), /check constraint/)
  await assert.rejects(snap(R3, [{ product_id: 'p', site: 'tira', ok: true, price: -1 }]), /check constraint/)
  await assert.rejects(snap('99999999-9999-9999-9999-999999999999', [{ product_id: 'p', site: 'tira', ok: true }]), /foreign key/)
  await assert.rejects(save({ ...M, product_id: 'p', status: 'wrong' }, 0, 'x'), /check constraint/)
})
await test('old code is refused', async () => {
  await db.exec("update mi_price_meta set value = '2' where key = 'min_client'")
  await assert.rejects(lock('old-pc', R2), /too old/)
  await assert.rejects(snap(R3, []), /too old/)
  await assert.rejects(save(M, 3, 'x'), /too old/)
})
await test('the two check queries show only the new objects', async () => {
  const t = (await db.query("select table_name, privilege_type from information_schema.role_table_grants where grantee in ('mi_price_writer','PUBLIC') and table_schema = 'public'")).rows
  assert.ok(t.length === 6 && t.every((r) => r.table_name.startsWith('mi_price_') && r.privilege_type === 'SELECT'))
  const f = (await db.query("select p.proname from pg_proc p join pg_namespace s on s.oid = p.pronamespace where s.nspname = 'public' and has_function_privilege('mi_price_writer', p.oid, 'execute')")).rows
  assert.ok(f.length === 8 && f.every((r) => r.proname.startsWith('mi_price_') && r.proname !== 'mi_price_require'), JSON.stringify(f))
})
const remove = sql.slice(sql.indexOf('--   drop function if exists')).split('\n').map((l) => l.replace(/^--\s+/, '')).join('\n')
await test('the removal lines take everything away and nothing else', async () => {
  await db.exec(remove)
  assert.equal((await one("select count(*)::int as n from information_schema.tables where table_name like 'mi_price%'")).n, 0)
  assert.equal((await one("select count(*)::int as n from pg_roles where rolname = 'mi_price_writer'")).n, 0)
  await db.query('select * from orders')
})
console.log(`\n${passed} checks passed`)

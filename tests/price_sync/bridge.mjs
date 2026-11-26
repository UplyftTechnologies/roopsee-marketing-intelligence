// A stand-in for Supabase's web API over a throwaway Postgres running the real docs/price-sync.sql. Every request runs as mi_price_writer.
import { PGlite } from '@electric-sql/pglite'
import { createServer } from 'node:http'
import { readFileSync } from 'node:fs'

const sql = readFileSync(new URL('../../docs/price-sync.sql', import.meta.url), 'utf8')
const db = new PGlite()
await db.exec(`create role anon nologin; create role authenticated nologin; create role authenticator nologin;
  alter default privileges in schema public grant all on tables to anon, authenticated;
  alter default privileges in schema public grant execute on functions to anon, authenticated;`)
await db.exec(sql)
await db.exec(sql)
let down = false
let queue = Promise.resolve()
const OPS = { eq: '=', gt: '>' }
const ident = (s) => { if (!/^[a-z_0-9]+$/.test(s)) throw new Error(`bad name ${s}`); return s }

async function handle(req, body) {
  const url = new URL(req.url, 'http://x')
  if (url.pathname === '/__down') { down = JSON.parse(body).down; return [200, {}] }
  if (url.pathname === '/__sql') return [200, (await db.query(JSON.parse(body).sql)).rows]
  if (down) return [503, { message: 'down for the test' }]
  if (req.headers.authorization !== 'Bearer test-key') return [401, { message: 'Invalid API key' }]
  const path = url.pathname.replace('/rest/v1/', '')
  await db.exec('set role mi_price_writer')
  try {
    if (req.method === 'GET') {
      const args = []; const where = []; let order = ''; let limit = ''; let offset = ''; let cols = '*'
      for (const [k, v] of url.searchParams) {
        if (k === 'select') cols = v === '*' ? '*' : v.split(',').map(ident).join(',')
        else if (k === 'order') order = ' order by ' + v.split(',').map((p) => { const [c, d] = p.split('.'); return `${ident(c)} ${d === 'desc' ? 'desc' : 'asc'}` }).join(',')
        else if (k === 'limit') limit = ` limit ${Number(v)}`
        else if (k === 'offset') offset = ` offset ${Number(v)}`
        else { const i = v.indexOf('.'); args.push(v.slice(i + 1)); where.push(`${ident(k)} ${OPS[v.slice(0, i)]} $${args.length}`) }
      }
      const q = `select ${cols} from public.${ident(path)}${where.length ? ' where ' + where.join(' and ') : ''}${order}${limit}${offset}`
      const r = await db.query(`select coalesce(json_agg(row_to_json(t)), '[]'::json)::text as j from (${q}) t`, args)
      return [200, JSON.parse(r.rows[0].j)]
    }
    const fn = ident(path.replace('rpc/', ''))
    await db.exec('reset role')
    const meta = (await db.query(`select p.proargnames as names, (select array_agg(format_type(t, null) order by o) from unnest(p.proargtypes::oid[]) with ordinality x(t, o)) as types,
                                  format_type(p.prorettype, null) as ret from pg_proc p where p.proname = $1`, [fn])).rows[0]
    if (!meta) return [404, { message: 'no such function' }]
    await db.exec('set role mi_price_writer')
    const input = JSON.parse(body || '{}')
    const args = []
    const list = Object.entries(input).map(([k, v]) => {
      const type = meta.types[meta.names.indexOf(k)]
      if (!type) throw new Error(`unknown argument ${k}`)
      args.push(type === 'jsonb' && v !== null ? JSON.stringify(v) : v)
      return `${ident(k)} => $${args.length}::${type}`
    }).join(', ')
    if (meta.ret === 'void') { await db.query(`select public.${fn}(${list})`, args); return [204, null] }
    const r = await db.query(`select to_json(public.${fn}(${list}))::text as j`, args)
    return [200, JSON.parse(r.rows[0].j)]
  } finally { await db.exec('reset role') }
}

createServer((req, res) => {
  let body = ''
  req.on('data', (c) => { body += c })
  req.on('end', () => {
    queue = queue.then(async () => {
      let out
      try { out = await handle(req, body) } catch (e) { await db.exec('reset role'); out = [400, { message: e.message }] }
      res.writeHead(out[0], { 'content-type': 'application/json' })
      res.end(out[1] === null ? '' : JSON.stringify(out[1]))
    })
  })
}).listen(54999, '127.0.0.1', () => console.log('bridge ready'))

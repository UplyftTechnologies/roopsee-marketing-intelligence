import { useEffect, useState } from 'react'
import { dt, inr, num, useApi, useFilters, usePersisted } from '../api'
import { Badge, Card, Chips, ExportBtn, Loading, Pager, Search, Table, nextSort } from '../ui'
import BulkExclude from '../components/BulkExclude'

const TONE = { 'Repeat buyer': 'good', Buyer: 'good', 'Abandoned checkout': 'serious', 'Cart, no checkout': 'warn', 'Quiz done, no cart': 'warn' }
const PRESETS = [['', 'Everyone'], ['cart_abandoners', 'Cart abandoners'], ['checkout_abandoners', 'Checkout abandoners'], ['logged_in', 'Logged in'], ['buyers', 'Buyers'], ['reachable', 'Reachable by phone'], ['has_pincode', 'Has a delivery pincode'], ['saved_address', 'Saved an address']]
const TEXT_SORTS = ['name', 'email', 'city', 'segment', 'first_channel']

export default function Users() {
  const f = useFilters()
  const [search, setSearch] = usePersisted('users.search', '')
  const [segment, setSegment] = usePersisted('users.segment', '')
  const [preset, setPreset] = usePersisted('users.preset', '')
  const [sort, setSort] = usePersisted('users.sort', { key: 'last_seen', dir: 'desc' })
  const [offset, setOffset] = useState(0)
  const [sel, setSel] = useState(new Set())
  const [limit, setLimit] = usePersisted('users.limit', 50)
  const counts = useApi('/users/counts')
  const s = useApi('/users', { search, segment: segment || undefined, preset: preset || undefined, sort: sort.key, direction: sort.dir, limit, offset })
  useEffect(() => { setOffset(0); setSel(new Set()) }, [search, segment, preset, sort, limit])
  const toggle = (id) => setSel((p) => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n })
  const toggleAll = (ids, on) => setSel((p) => { const n = new Set(p); ids.forEach((i) => (on ? n.add(i) : n.delete(i))); return n })

  return (
    <>
      <div className="chip-row">
        <Search value={search} onChange={setSearch} placeholder="Search name, phone, email, city, id…" />
      </div>
      <div className="chip-row" role="group" aria-label="Quick views">
        {PRESETS.map(([k, label]) => (
          <button key={k || 'all'} type="button" className={`chip ${preset === k ? 'on' : ''}`} onClick={() => setPreset(k)}>
            {label}{k && counts.data ? ` (${num(counts.data[k])})` : counts.data && !k ? ` (${num(counts.data.total)})` : ''}
          </button>
        ))}
      </div>
      <Loading state={s}>
        {({ rows, total, segments }) => {
          const chosen = rows.filter((r) => sel.has(r.person_key))
          return (
            <>
              <Chips value={segment} onChange={setSegment} options={[{ value: '', label: 'All segments' }, ...segments.map((g) => ({ value: g.segment, label: `${g.segment} (${num(g.n)})` }))]} />
              <Card sticky title={`${num(total)} people`} sub="a person = a logged-in account, or an anonymous browser · click a row for their full profile · click a column title to sort · a person who later ordered is never a cart or checkout abandoner"
                right={<ExportBtn name="people" rows={rows} fields={[['Name', 'name'], ['Phone', 'phone10'], ['Email', 'email'], ['Segment', 'segment'], ['First channel', 'first_channel'], ['City', 'city'], ['State', 'state'], ['Sessions', 'sessions'], ['Orders', 'orders'], ['Revenue', 'revenue'], ['Age', 'age_bucket'], ['Skin type', 'skin_type']]} />}>
                <BulkExclude rows={chosen} noun="users" onClear={() => setSel(new Set())} fields={[
                  { label: 'user account', kind: 'user_id', get: (r) => r.user_id }, { label: 'browser', kind: 'visitor_id', get: (r) => (r.user_id ? null : r.person_key) },
                  { label: 'phone number', kind: 'phone', get: (r) => r.phone10 }, { label: 'email', kind: 'email', get: (r) => r.email },
                ]} />
                <Table selectable selected={sel} onToggle={toggle} onToggleAll={toggleAll} rowId={(r) => r.person_key}
                  sort={sort} onSort={(k) => setSort(nextSort(sort, k, TEXT_SORTS))}
                  onRow={(r) => f.go('person', { key: r.person_key })} rowClass={(r) => (r.is_excluded ? 'excluded' : '')} cols={[
                    { label: 'Person', cls: 'nw', sortBy: 'name', render: (r) => r.name || (r.is_registered ? <span className="muted">no name</span> : <span className="muted mono">anon {r.person_key.slice(0, 8)}</span>) },
                    { label: 'Phone', cls: 'mono', render: (r) => r.phone10 || '–' },
                    { label: 'Email', sortBy: 'email', render: (r) => (r.email ? <span className="trunc" style={{ display: 'block', maxWidth: 190 }} title={r.email}>{r.email}</span> : <span className="muted">–</span>) },
                    { label: 'Segment', sortBy: 'segment', render: (r) => <Badge tone={TONE[r.segment]}>{r.segment}</Badge> },
                    { label: 'First source', sortBy: 'first_channel', render: (r) => <span title={r.first_campaign}>{r.first_channel}</span> },
                    { label: 'Location', sortBy: 'city', render: (r) => <span title={r.ip_city && r.ip_city !== r.city ? `Visitor IP says ${r.ip_city}` : ''}>{[r.city, r.state].filter(Boolean).join(', ') || '–'}</span> },
                    { label: 'Pincode', cls: 'mono', sortBy: 'delivery_pincode', render: (r) => (r.delivery_pincode ? <>{r.delivery_pincode}{r.has_saved_address ? <span title="Saved an address"> ✓</span> : null}</> : <span className="muted">–</span>) },
                    { label: 'Sessions', num: true, sortBy: 'sessions', render: (r) => r.sessions },
                    { label: 'Carts', num: true, sortBy: 'cart_sessions', render: (r) => r.cart_sessions }, { label: 'Orders', num: true, sortBy: 'orders', render: (r) => r.orders },
                    { label: 'Revenue', num: true, sortBy: 'revenue', render: (r) => (r.revenue ? inr(r.revenue) : '–') },
                    { label: 'Last seen', cls: 'nw', sortBy: 'last_seen', render: (r) => dt(r.last_seen) },
                    { label: '', render: (r) => (r.is_excluded ? <Badge tone="bad">excluded</Badge> : null) },
                  ]} rows={rows} empty="Nobody matches these filters." />
                <Pager total={total} limit={limit} offset={offset} setOffset={setOffset} setLimit={setLimit} />
              </Card>
            </>
          )
        }}
      </Loading>
    </>
  )
}

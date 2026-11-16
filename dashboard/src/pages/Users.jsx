import { useEffect, useState } from 'react'
import { dt, inr, num, useApi } from '../api'
import { Badge, Card, Chips, ExportBtn, Loading, Pager, Search, Table } from '../ui'
import { useQuickExclude } from './Sessions'

const TONE = { 'Repeat buyer': 'good', Buyer: 'good', 'Abandoned checkout': 'serious', 'Cart, no checkout': 'warn', 'Quiz done, no cart': 'warn' }

export default function Users() {
  const [search, setSearch] = useState('')
  const [segment, setSegment] = useState('')
  const [sort, setSort] = useState('last_seen')
  const [offset, setOffset] = useState(0)
  const { exclude, msg } = useQuickExclude()
  const limit = 50
  const s = useApi('/users', { search, segment: segment || undefined, sort, limit, offset })
  useEffect(() => setOffset(0), [search, segment, sort])
  return (
    <>
      <div className="chip-row">
        <Search value={search} onChange={setSearch} placeholder="Search name, phone, email, city, id…" />
        <select className="field" value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="last_seen">Sort: last seen</option><option value="first_seen">Sort: first seen</option>
          <option value="revenue">Sort: revenue</option><option value="sessions">Sort: sessions</option>
        </select>
      </div>
      <Loading state={s}>
        {({ rows, total, segments }) => (
          <>
            <Chips value={segment} onChange={setSegment} options={[{ value: '', label: 'All segments' }, ...segments.map((g) => ({ value: g.segment, label: `${g.segment} (${num(g.n)})` }))]} />
            <Card right={<ExportBtn name="people" rows={rows} fields={[['Name', 'name'], ['Phone', 'phone10'], ['Email', 'email'], ['Segment', 'segment'], ['First channel', 'first_channel'], ['City', 'city'], ['State', 'state'], ['Sessions', 'sessions'], ['Orders', 'orders'], ['Revenue', 'revenue'], ['Age', 'age_bucket'], ['Skin type', 'skin_type']]} />} title={`${num(total)} people`} sub="a person = a logged-in account, or an anonymous browser. Segments drive the future automated-message step.">
              {msg && <div className="muted" style={{ marginBottom: 8 }}>{msg}</div>}
              <Table rowClass={(r) => (r.is_excluded ? 'excluded' : '')} cols={[
                { label: 'Person', render: (r) => r.name || (r.is_registered ? <span className="muted">no name</span> : <span className="muted mono">anon {r.person_key.slice(0, 8)}</span>) },
                { label: 'Phone', cls: 'mono', render: (r) => r.phone10 || '–' },
                { label: 'Segment', render: (r) => <Badge tone={TONE[r.segment]}>{r.segment}</Badge> },
                { label: 'First source', render: (r) => <span title={r.first_campaign}>{r.first_channel}</span> },
                { label: 'Location', render: (r) => [r.city, r.state].filter(Boolean).join(', ') || '–' },
                { label: 'Sessions', num: true, render: (r) => r.sessions },
                { label: 'Carts', num: true, render: (r) => r.cart_sessions }, { label: 'Orders', num: true, render: (r) => r.orders },
                { label: 'Revenue', num: true, render: (r) => (r.revenue ? inr(r.revenue) : '–') },
                { label: 'Age / skin', render: (r) => [r.age_bucket, r.skin_type].filter(Boolean).join(' · ') || '–' },
                { label: 'Last seen', render: (r) => dt(r.last_seen) },
                { label: '', render: (r) => (r.is_excluded ? <Badge tone="bad">excluded</Badge>
                  : <button className="btn small danger" onClick={() => exclude(r.user_id ? 'user_id' : 'visitor_id', r.user_id || r.person_key, 'from users tab')}>Exclude</button>) },
              ]} rows={rows} />
              <Pager total={total} limit={limit} offset={offset} setOffset={setOffset} />
            </Card>
          </>
        )}
      </Loading>
    </>
  )
}

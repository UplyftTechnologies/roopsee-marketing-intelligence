import { useEffect, useState } from 'react'
import { dt, inr, num, pct, useApi, useFilters } from '../api'
import { Badge, Card, ExportBtn, Kpi, Loading, Pager, Table } from '../ui'

function People({ id, onClose }) {
  const f = useFilters()
  const [only, setOnly] = useState(true)
  const [offset, setOffset] = useState(0)
  const limit = 25
  const s = useApi(`/audiences/${id}/people`, { only_reachable: only, limit, offset }, { scoped: true })
  useEffect(() => setOffset(0), [id, only])
  return (
    <Loading state={s}>
      {(d) => (
        <Card title={d.title} sub={d.description}
          right={<span className="chip-row">
            <label className="toggle"><input type="checkbox" checked={only} onChange={(e) => setOnly(e.target.checked)} /> Only people with a phone number</label>
            <ExportBtn name={`audience-${id}`} rows={d.rows} fields={[['Name', 'name'], ['Phone', 'phone10'], ['Email', 'email'], ['City', 'city'], ['State', 'state'], ['Segment', 'segment'], ['First channel', 'first_channel'], ['Orders', 'orders'], ['Revenue', 'revenue'], ['Skin type', 'skin_type'], ['Age', 'age_bucket'], ['Last cart value', 'last_cart_value'], ['Last seen', 'last_seen']]} />
            <button className="btn small" onClick={onClose}>Close</button>
          </span>}>
          <div className="banner ok" style={{ marginBottom: 10 }}><div><b>Suggested next step:</b> {d.action}<div className="muted">Messaging is not built yet; export the list or use it as a target for the automated step later.</div></div></div>
          <Table onRow={(r) => f.go('person', { key: r.person_key })} cols={[
            { label: 'Person', render: (r) => r.name || <span className="muted">no name</span> },
            { label: 'Phone', cls: 'mono', render: (r) => r.phone10 || <span className="muted">none</span> },
            { label: 'Place', render: (r) => [r.city, r.state].filter(Boolean).join(', ') || '–' },
            { label: 'First channel', key: 'first_channel' },
            { label: 'Last cart', num: true, render: (r) => (r.last_cart_value ? inr(r.last_cart_value) : '–') },
            { label: 'Orders', num: true, render: (r) => r.orders }, { label: 'Spent', num: true, render: (r) => (r.revenue ? inr(r.revenue) : '–') },
            { label: 'Skin / age', render: (r) => [r.skin_type, r.age_bucket].filter(Boolean).join(' · ') || '–' },
            { label: 'Last seen', render: (r) => dt(r.last_seen) },
          ]} rows={d.rows} empty="Nobody in this group has a phone number yet. Untick the box to see everyone." />
          <Pager total={d.total} limit={limit} offset={offset} setOffset={setOffset} />
        </Card>
      )}
    </Loading>
  )
}

export default function Audiences() {
  const s = useApi('/audiences', {}, { scoped: true })
  const [open, setOpen] = useState(null)
  return (
    <Loading state={s}>
      {({ audiences, totals, as_of }) => (
        <>
          <div className="kpis">
            <Kpi label="People tracked" value={num(totals.people)} note="accounts and anonymous browsers" />
            <Kpi label="Reachable by phone" help="reachable" value={num(totals.reachable)} note={pct(totals.reachable / (totals.people || 1), 1) + ' of everyone'} />
            <Kpi label="Registered accounts" value={num(totals.registered)} />
            <Kpi label="As of" value={new Date(as_of + 'T00:00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })} note="date range does not apply here" />
          </div>
          <div className="banner">
            <div><b>Only {pct(totals.reachable / (totals.people || 1), 1)} of the people who visit can be contacted.</b> Most browse without logging in, so there is no phone number to reach them.
              <div className="muted">Asking for a phone number earlier (for example at the end of the skin quiz) grows every audience below.</div></div>
          </div>
          <div className="insight-grid">
            {audiences.map((a) => {
              const reach = a.people ? a.reachable / a.people : 0
              return (
                <article key={a.id} className={`insight ${open === a.id ? 'info' : ''}`} style={{ gap: 8 }}>
                  <div className="insight-title">{a.title}</div>
                  <div style={{ fontSize: 28, fontWeight: 650 }}>{num(a.people)} <span className="muted" style={{ fontSize: 13, fontWeight: 400 }}>people</span></div>
                  <div style={{ width: '100%' }}>
                    <div style={{ height: 8, background: 'var(--surface-2)', borderRadius: 4 }}><div style={{ height: 8, width: `${Math.max(2, reach * 100)}%`, background: 'var(--series-1)', borderRadius: 4 }} /></div>
                    <div className="muted" style={{ fontSize: 12, marginTop: 3 }}>{num(a.reachable)} reachable by phone ({pct(reach, 0)})</div>
                  </div>
                  <p>{a.description}</p>
                  {a.cart_value > 0 && <Badge tone="warn">{inr(a.cart_value)} left in last carts</Badge>}
                  {a.revenue > 0 && <Badge>{inr(a.revenue)} spent so far</Badge>}
                  <div className="muted" style={{ fontSize: 12 }}><b>Try:</b> {a.action}</div>
                  <button className="btn small primary" onClick={() => setOpen(open === a.id ? null : a.id)}>{open === a.id ? 'Hide list' : 'View list'}</button>
                </article>
              )
            })}
          </div>
          {open && <People id={open} onClose={() => setOpen(null)} />}
        </>
      )}
    </Loading>
  )
}

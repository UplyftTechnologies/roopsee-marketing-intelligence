import { useEffect, useState } from 'react'
import { dt, inr, num, pct, useApi, useFilters } from '../api'
import { Badge, Card, ExportBtn, Loading, Pager, Table } from '../ui'
import { Bars, NotBuilt } from './deeper/common'
import { UntrackedNote } from '../components/RevenueNotes'

// Audiences is an all-time page: the date range in the top bar does not apply (empty dates = all time)
const ALL_TIME = { date_from: '', date_to: '' }
const GROUPS = ['Interest', 'Price range', 'Discounts', 'Discovery', 'Device', 'Skin concern (quiz)', 'Journey stage']

export default function Segments({ label, setLabel }) {
  const f = useFilters()
  const s = useApi('/segments', { label: label || undefined, ...ALL_TIME })
  return (
    <Loading state={s}>
      {(d) => {
        if (!d.ready) return <NotBuilt />
        const by = {}
        d.labels.forEach((l) => { (by[l.group] = by[l.group] || []).push(l) })
        const groups = [...GROUPS.filter((g) => by[g]), ...Object.keys(by).filter((g) => !GROUPS.includes(g))]
        const cur = d.labels.find((l) => l.key === label)
        return (
          <>
            <div className="banner" role="note">
              <span>Every person carries any number of labels (a quiz user can also be a makeup user and a budget shopper). {num(d.totals.people)} people have been tracked; {pct(d.base.buyer_rate, 1)} of them have bought. Click a label to see who has it and what else they are. Label rules: <span className="mono">mi/deeper_defs.py</span>.</span>
            </div>
            <UntrackedNote untracked={d.untracked} />
            {groups.map((g) => (
              <section key={g}>
                <div className="section-head"><h2>{g}</h2></div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))', gap: 12 }}>
                  {by[g].map((l) => (
                    <button key={l.key} type="button" className="kpi click" aria-pressed={label === l.key} onClick={() => setLabel(label === l.key ? '' : l.key)} title={l.description}
                      style={{ textAlign: 'left', ...(label === l.key ? { borderColor: 'var(--accent)', boxShadow: 'inset 0 0 0 1px var(--accent)' } : null) }}>
                      <div className="label">{l.title}</div>
                      <div className="value">{num(l.people)}</div>
                      <div className="note">
                        {pct(l.share, 1)} of people · buy {pct(l.buyer_rate, 1)}{l.buyer_rate >= 1.5 * d.base.buyer_rate && l.buyers >= 3 ? ' ▲' : l.buyers >= 3 && l.buyer_rate <= 0.5 * d.base.buyer_rate ? ' ▼' : ''}
                        <br />{num(l.reachable)} reachable{l.revenue ? ` · ${inr(l.revenue)}` : ''}
                      </div>
                    </button>
                  ))}
                </div>
              </section>
            ))}
            {cur && <Detail cur={cur} d={d} f={f} />}
          </>
        )
      }}
    </Loading>
  )
}

function Detail({ cur, d, f }) {
  const [only, setOnly] = useState(false)
  const [sort, setSort] = useState('last_seen')
  const [limit, setLimit] = useState(50)
  const [offset, setOffset] = useState(0)
  useEffect(() => { setOffset(0) }, [cur.key, only, sort, limit])
  const p = useApi('/segments/people', { ...ALL_TIME, label: cur.key, only_reachable: only || undefined, sort, limit, offset })
  return (
    <div id="segment-detail" className="grid g2" style={{ gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 2.2fr)' }}>
      <Card title={cur.title} sub={cur.description}>
        <div className="muted" style={{ fontSize: 13, lineHeight: 1.7 }}>
          <b>{num(cur.people)}</b> people · <b>{num(cur.buyers)}</b> bought ({pct(cur.buyer_rate, 1)} against {pct(d.base.buyer_rate, 1)} overall)<br />
          {num(cur.repeat_buyers)} bought more than once · average order {cur.aov ? inr(cur.aov) : '–'} · {num(cur.reachable)} with a phone number · {cur.avg_sessions} visits each
        </div>
        <div style={{ marginTop: 10 }}><b>They are also</b></div>
        <Bars items={d.co.map((c) => ({ name: c.key, label: c.title, count: c.people }))} total={cur.people} empty="No other labels." />
      </Card>
      <Card title="People" sub="click a row for the person"
        right={<span className="chip-row"><label className="muted" style={{ fontSize: 12 }}><input type="checkbox" checked={only} onChange={(e) => setOnly(e.target.checked)} /> Only with a phone number</label>
          <select className="field" value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort people"><option value="last_seen">Latest first</option><option value="revenue">Highest spend</option><option value="sessions">Most visits</option><option value="evidence">Strongest signal</option></select>
          {p.data && <ExportBtn name={`segment-${cur.key}`} rows={p.data.rows} fields={[['Name', 'name'], ['Phone', 'phone10'], ['Email', 'email'], ['City', 'city'], ['Journey stage', 'segment'], ['Labels', (r) => (r.labels || []).join(' | ')], ['Visits', 'sessions'], ['Orders', 'orders'], ['Revenue', 'revenue'], ['Signal', 'evidence'], ['Last seen', 'last_seen']]} />}</span>}>
        <Loading state={p}>
          {({ rows, total }) => (
            <>
              <Table scroll onRow={(r) => f.go('person', { key: r.person_key })} rows={rows} empty="Nobody matches." cols={[
                { label: 'Who', cls: 'nw', render: (r) => r.name || (r.phone10 ? <span className="mono">{r.phone10}</span> : <span className="muted" title="Never logged in on this browser">Guest</span>) },
                { label: 'Phone', cls: 'mono nw', render: (r) => r.phone10 || <span className="muted">–</span> },
                { label: 'City', cls: 'nw', render: (r) => r.city || '–' },
                { label: 'Labels', render: (r) => <span>{(r.labels || []).slice(0, 5).map((t) => <Badge key={t}>{t}</Badge>)}</span> },
                { label: 'Stage', cls: 'nw', render: (r) => r.segment },
                { label: 'Visits', num: true, render: (r) => num(r.sessions) },
                { label: 'Orders', num: true, render: (r) => num(r.orders) },
                { label: 'Last seen', cls: 'nw', render: (r) => dt(r.last_seen) },
              ]} />
              <Pager total={total} limit={limit} offset={offset} setOffset={setOffset} setLimit={setLimit} />
            </>
          )}
        </Loading>
      </Card>
    </div>
  )
}

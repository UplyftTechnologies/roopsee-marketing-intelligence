import { useState } from 'react'
import { num, pct, useApi, useFilters } from '../api'
import { Badge, Card, Chips, ExportBtn, Loading, Table } from '../ui'

const LEVELS = [{ value: 'campaign', label: 'Campaign' }, { value: 'adset', label: 'Ad set' }, { value: 'ad', label: 'Ad' }, { value: 'channel', label: 'Channel' }]
const FILTER = { campaign: 'campaign_id', adset: 'adset', ad: 'ad', channel: 'channel' }
const unknown = (k) => String(k).startsWith('(')

/** Which campaigns, ad sets, ads and channels bring people who open Roop, and what those visits do next. A row opens the visits behind it. */
export default function RoopUsage({ compact = false, title = 'Roop by campaign', defaultLevel = 'campaign' }) {
  const f = useFilters()
  const [level, setLevel] = useState(defaultLevel)
  const [all, setAll] = useState(false)
  const s = useApi('/roop/usage', { level, only_used: all ? false : undefined, min_sessions: all ? 30 : 1, limit: compact ? 12 : 200 })
  const open = (r, asked) => {
    if (unknown(r.key) && level !== 'channel') return
    f.go('sessions', { [FILTER[level]]: r.key, has: [asked ? 'roop_asked' : 'roop'], ...(level === 'channel' ? { channel: r.key } : {}) })
  }
  return (
    <Card title={title} sub="visits that opened Roop (the assistant), the ones that asked it something, and what they did, against visits that did not use it · click a row to see those visits"
      right={<span className="chip-row"><Chips value={level} onChange={setLevel} options={LEVELS} />
        <label className="muted" style={{ fontSize: 12 }}><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> Include those with no Roop use</label>
        {s.data?.ready && <ExportBtn name={`roop-by-${level}`} rows={s.data.rows} fields={[['Name', 'name'], ['Id', 'key'], ['Channel', 'channel'], ['Visits', 'sessions'], ['Opened Roop', 'opened'], ['Asked', 'asked'], ['Got an answer', 'answered'], ['Clicked a product', 'clicked'],
          ['Roop visits that added to cart', 'roop_carted'], ['Roop visits that ordered', 'roop_ordered'], ['Other visits that ordered', 'other_ordered'], ['Other visits', 'other_sessions'], ['Top topics', (r) => r.topics.map((t) => t.name).join(' | ')]]} />}</span>}>
      <Loading state={s}>
        {(d) => {
          if (!d.ready) return <div className="muted">Press Refresh to build the tables this needs.</div>
          const t = d.totals
          return (
            <>
              <div className="muted" style={{ marginBottom: 8, fontSize: 13 }}>
                In these dates <b>{num(d.all.opened)}</b> of {num(d.all.sessions)} visits ({pct(t.use_rate, 1)}) opened Roop and <b>{num(d.all.asked)}</b> asked it something.
                Visits that opened it ordered <b>{pct(t.roop_order_rate, 1)}</b> of the time, against <b>{pct(t.other_order_rate, 1)}</b> for the rest.
              </div>
              <Table scroll rows={d.rows} onRow={(r) => open(r, false)} empty="Nobody opened Roop from these in these dates." cols={[
                { label: LEVELS.find((x) => x.value === level).label, sortBy: 'name', render: (r) => (
                  <span title={r.key}><span className="trunc" style={{ display: 'inline-block', maxWidth: 240, verticalAlign: 'bottom' }}>{r.name}</span>{!r.named && level !== 'channel' && !unknown(r.key) ? <span className="muted"> · not in Meta</span> : null}</span>) },
                ...(level !== 'channel' ? [{ label: 'Channel', cls: 'nw', sortBy: 'channel', render: (r) => r.channel }] : []),
                { label: 'Visits', num: true, sortBy: 'sessions', render: (r) => num(r.sessions) },
                { label: 'Opened Roop', num: true, sortBy: 'opened', render: (r) => <b>{num(r.opened)}</b> },
                { label: 'Share', num: true, sortBy: 'use_rate', render: (r) => pct(r.use_rate, 1) },
                { label: 'Asked', num: true, sortBy: 'asked', render: (r) => (r.asked ? <button type="button" className="btn small" onClick={(e) => { e.stopPropagation(); open(r, true) }} title="See the visits that asked Roop a question">{num(r.asked)}</button> : '–') },
                { label: 'Answered', num: true, sortBy: 'answered', render: (r) => num(r.answered) },
                { label: 'Clicked a product', num: true, sortBy: 'clicked', render: (r) => num(r.clicked) },
                { label: 'Cart', num: true, sortBy: 'roop_cart_rate', render: (r) => (r.opened ? <span title={`other visits: ${pct(r.other_cart_rate, 1)}`}>{pct(r.roop_cart_rate, 0)}</span> : '–') },
                { label: 'Ordered', num: true, sortBy: 'roop_ordered', render: (r) => (r.opened ? <span title={`other visits: ${pct(r.other_order_rate, 1)}`}>{num(r.roop_ordered)} <span className="muted">({pct(r.roop_order_rate, 0)} vs {pct(r.other_order_rate, 1)})</span></span> : '–') },
                { label: 'They asked about', render: (r) => (r.topics.length ? <span>{r.topics.map((x) => <Badge key={x.name}>{x.name} {x.count}</Badge>)}</span> : <span className="muted">–</span>) },
              ]} />
              {d.rows.some((r) => unknown(r.key)) && <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>Rows in brackets are visits with no {level === 'campaign' ? 'campaign tag' : level === 'adset' ? 'ad set' : 'ad id'} in their link: they cannot be listed by it.</div>}
            </>
          )
        }}
      </Loading>
    </Card>
  )
}

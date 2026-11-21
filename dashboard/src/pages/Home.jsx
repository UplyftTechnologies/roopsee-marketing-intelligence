import { useState } from 'react'
import { inr, num, useApi, useFilters } from '../api'
import { Card, Loading, Table } from '../ui'
import { loginCols } from './Logins'
import { METRICS } from '../metrics'
import { Scorecard, ScorecardStrip } from '../components/Scorecard'
import MetricChart from '../components/LazyMetricChart'
import DataHealth from '../components/DataHealth'
import { Alerts, WeeklyDigest } from '../components/AlertsDigest'
import { RevenueSplit } from '../components/RevenueNotes'

const GROUPS = [
  { key: 'attention', title: 'Needs attention', tones: ['bad', 'warn'], blurb: 'Things that are costing you customers or money' },
  { key: 'working', title: "What's working", tones: ['good'], blurb: 'Keep doing more of this' },
  { key: 'know', title: 'Good to know', tones: ['info'], blurb: 'Context that helps you decide' },
]
const ICON = { bad: '■', warn: '◆', good: '▲', info: '●' }
const CARDS = ['sessions', 'logins', 'cart_rate', 'orders', 'revenue']

function Tip() {
  const [hide, setHide] = useState(() => { try { return localStorage.getItem('tip-dismissed') === '1' } catch { return false } })
  if (hide) return null
  return (
    <div className="banner ok">
      <div>
        <b>How to read this dashboard.</b> Pick a date range at the top: every number compares with the period before it.
        The cards below are generated from your data; <b>Open</b> jumps to the rows behind a finding.
        Staff, test and bot traffic is hidden by default (change it from the “Internal traffic” menu).
      </div>
      <div className="spacer" />
      <button className="btn small" onClick={() => { try { localStorage.setItem('tip-dismissed', '1') } catch { /* ignore */ } setHide(true) }}>Got it</button>
    </div>
  )
}

function MiniList({ title, rows, fmt, onRow, state }) {
  const max = Math.max(1, ...rows.map((r) => r.value))
  return (
    <Card title={title}>
      {state?.error ? <div className="muted">Could not load</div> : !state?.data ? <div className="skeleton" style={{ height: 150 }} /> : rows.length === 0 ? <div className="muted">Nothing in this range</div> : (
        <div className="mini-list">
          {rows.map((r) => (
            <div key={r.name} className="mini-row" style={{ cursor: onRow ? 'pointer' : 'default' }} onClick={onRow ? () => onRow(r) : undefined}>
              <span className="name" title={r.name}>{r.name}</span><span className="val">{fmt(r.value)}</span>
              <span className="mini-bar"><i style={{ width: `${(r.value / max) * 100}%` }} /></span>
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

export default function Home() {
  const f = useFilters()
  const ins = useApi('/insights')
  const ts = useApi('/timeseries')
  const chan = useApi('/report', { dimension: 'channel', limit: 6 })
  const city = useApi('/report', { dimension: 'city', limit: 8, min_sessions: 5 })
  const prod = useApi('/basket')
  const lg = useApi('/logins', { summary: false, limit: 10 })
  const [metric, setMetric] = useState('sessions')
  return (
    <Loading state={ins}>
      {({ kpis, prev, insights }) => (
        <>
          <Tip />
          <Alerts />
          <WeeklyDigest />
          <ScorecardStrip>
            {CARDS.map((k) => (
              <Scorecard key={k} metric={k} kpis={kpis} prev={prev} compare={f.compare} spark={ts.data?.current[METRICS[k].series]} active={metric === k} onClick={() => setMetric(k)} />
            ))}
          </ScorecardStrip>
          <RevenueSplit kpis={kpis} />
          <Card title={METRICS[metric].label} sub="Click a tile above to change the chart">
            {ts.data ? <MetricChart ts={ts.data} metric={metric} compare={f.compare} height={230} ranges={{ cur: f.rangeText, prev: f.prevText }} note={(!f.to || f.to === f.meta?.range?.last) ? 'The latest day may be incomplete' : undefined} /> : <div className="skeleton" style={{ height: 250 }} />}
          </Card>

          <Card title="Recent logins" sub="the latest people to log in, new accounts and returning customers"
            right={<button className="btn small" onClick={() => f.go('logins')}>See all logins →</button>}>
            {lg.error ? <div className="muted">Could not load</div> : !lg.data ? <div className="skeleton" style={{ height: 150 }} />
              : !lg.data.ready ? <div className="muted">Press Refresh to build the login table.</div>
                : <Table rows={lg.data.rows} onRow={(r) => f.go('person', { key: r.person_key })} empty="No logins in this range." cols={loginCols(false)} />}
          </Card>

          {GROUPS.map((g) => {
            const items = insights.filter((i) => g.tones.includes(i.tone))
            if (!items.length) return null
            return (
              <section key={g.key}>
                <div className="section-head"><h2>{g.title}</h2><span className="muted">{g.blurb}</span></div>
                <div className="insight-grid">
                  {items.map((i, n) => (
                    <article key={n} className={`insight ${i.tone}`}>
                      <div className="insight-title"><span className={`tone ${i.tone}`} aria-hidden>{ICON[i.tone]}</span>{i.title}</div>
                      <p>{i.detail}</p>
                      {i.tab && <button className="btn small" onClick={() => f.go(i.tab, i.filters)}>Open →</button>}
                    </article>
                  ))}
                </div>
              </section>
            )
          })}
          {insights.length === 0 && <div className="empty">Not enough data in this range to generate findings. Try a wider date range.</div>}

          <div className="grid g3">
            <MiniList title="Top channels · sessions" state={chan} fmt={num}
              rows={(chan.data?.rows || []).map((r) => ({ name: r.dim, value: r.sessions }))} onRow={(r) => f.go('sessions', { channel: r.name })} />
            <MiniList title="Top cities · sessions" state={city} fmt={num}
              rows={(city.data?.rows || []).filter((r) => r.dim !== 'Unknown').slice(0, 6).map((r) => ({ name: r.dim, value: r.sessions }))} onRow={(r) => f.go('sessions', { search: r.name })} />
            <MiniList title="Top products · revenue" state={prod} fmt={inr}
              rows={(prod.data?.products || []).slice(0, 6).map((p) => ({ name: p.product_name, value: p.revenue }))} onRow={() => f.go('basket')} />
          </div>
          <DataHealth />
        </>
      )}
    </Loading>
  )
}

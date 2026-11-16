import { useState } from 'react'
import { inr, num, pct, useApi, useFilters } from '../api'
import { Kpi, Loading, delta } from '../ui'

const GROUPS = [
  { key: 'attention', title: 'Needs attention', tones: ['bad', 'warn'], blurb: 'Things that are costing you customers or money' },
  { key: 'working', title: "What's working", tones: ['good'], blurb: 'Keep doing more of this' },
  { key: 'know', title: 'Good to know', tones: ['info'], blurb: 'Context that helps you decide' },
]
const ICON = { bad: '■', warn: '◆', good: '▲', info: '●' }

function Tip() {
  const [hide, setHide] = useState(() => { try { return localStorage.getItem('tip-dismissed') === '1' } catch { return false } })
  if (hide) return null
  return (
    <div className="banner ok">
      <div>
        <b>How to read this dashboard.</b> Pick a date range at the top – everything compares with the period before it.
        The cards below are generated from your data; click <b>Open</b> to jump to the exact rows behind a finding.
        Staff, test and bot traffic is hidden by default (change it any time in <b>Exclusions</b>).
      </div>
      <div className="spacer" />
      <button className="btn small" onClick={() => { try { localStorage.setItem('tip-dismissed', '1') } catch { /* ignore */ } setHide(true) }}>Got it</button>
    </div>
  )
}

export default function Home() {
  const f = useFilters()
  const s = useApi('/insights')
  return (
    <Loading state={s}>
      {({ kpis: k, prev: p, insights }) => {
        const d = (key, kind) => (f.compare && p ? delta(k[key], p[key], kind) : null)
        return (
          <>
            <Tip />
            <div className="kpis">
              <Kpi big label="Sessions" help="sessions" value={num(k.sessions)} d={d('sessions')} note={`${num(k.people)} people`} />
              <Kpi big label="Add-to-cart rate" help="cartRate" value={pct(k.cart_rate)} d={d('cart_rate', 'rate')} note={`${num(k.cart_sessions)} sessions`} />
              <Kpi big label="Orders" help="orders" value={num(k.orders)} d={d('orders')} note={`${pct(k.order_cvr, 2)} of sessions`} />
              <Kpi big label="Revenue" help="revenue" value={inr(k.revenue)} d={d('revenue')} note={`AOV ${inr(k.aov)}`} />
            </div>
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
          </>
        )
      }}
    </Loading>
  )
}

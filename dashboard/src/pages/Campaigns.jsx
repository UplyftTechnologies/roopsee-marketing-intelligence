import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { inr, num, pct, useApi } from '../api'
import { Badge, Card, Chips, Loading, RateBar, Table, axis, chartTip, verdictTone } from '../ui'

const CH = ['All', 'Paid Google', 'Paid Meta', 'MyGate Partner', 'Organic Search', 'Organic Social', 'Direct', 'Referral']

export default function Campaigns() {
  const [channel, setChannel] = useState('All')
  const [min, setMin] = useState(30)
  const s = useApi('/campaigns', { min_sessions: min })
  return (
    <Loading state={s}>
      {({ rows, baseline_cart_rate: base }) => {
        const shown = rows.filter((r) => channel === 'All' || r.channel === channel)
        const maxCart = Math.max(0.0001, ...shown.map((r) => r.cart_rate))
        const chart = shown.filter((r) => r.sessions >= 100).slice(0, 12).map((r) => ({ name: r.campaign.slice(0, 28), cart_rate: +(r.cart_rate * 100).toFixed(2), sessions: r.sessions }))
        return (
          <>
            <div className="chip-row" style={{ justifyContent: 'space-between' }}>
              <Chips options={CH} value={channel} onChange={setChannel} />
              <label className="toggle">Min sessions
                <select className="field" value={min} onChange={(e) => setMin(+e.target.value)}>{[1, 10, 30, 100, 300].map((n) => <option key={n}>{n}</option>)}</select>
              </label>
            </div>
            <Card title="Which campaigns are working?" sub={`Site-wide cart rate is ${pct(base, 2)}. Orders are credited to both the session they happened in and the buyer's FIRST visit (first touch); the verdict uses the higher of the two.`}>
              <Table
                cols={[
                  { label: 'Campaign', render: (r) => <span className="trunc" style={{ display: 'block', maxWidth: 240 }} title={r.campaign}>{r.campaign}</span> },
                  { label: 'Channel', key: 'channel' }, { label: 'Source / medium', render: (r) => `${r.source} / ${r.medium}` },
                  { label: 'Sessions', num: true, render: (r) => num(r.sessions) },
                  { label: 'Engaged', num: true, render: (r) => pct(r.engaged_rate, 0) },
                  { label: 'Quiz done', num: true, render: (r) => pct(r.quiz_rate, 1) },
                  { label: 'Cart rate', num: true, render: (r) => <RateBar v={r.cart_rate} max={maxCart} text={pct(r.cart_rate, 1)} /> },
                  { label: 'Checkout', num: true, render: (r) => pct(r.checkout_rate, 1) },
                  { label: 'Orders (same session)', num: true, render: (r) => num(r.orders) },
                  { label: 'Orders (first touch)', num: true, render: (r) => num(r.ft_orders) },
                  { label: 'Revenue', num: true, render: (r) => inr(r.best_revenue) },
                  { label: 'Verdict', render: (r) => <Badge tone={verdictTone[r.verdict]}>{r.verdict}</Badge> },
                ]}
                rows={shown}
              />
            </Card>
            <Card title="Cart rate by campaign" sub="campaigns with at least 100 sessions, % of sessions that added to cart">
              {chart.length === 0 ? <div className="empty">No campaign has 100+ sessions in this selection</div> : (
                <ResponsiveContainer width="100%" height={Math.max(180, chart.length * 30)}>
                  <BarChart data={chart} layout="vertical" margin={{ left: 20, right: 20 }}>
                    <CartesianGrid stroke="var(--grid)" horizontal={false} />
                    <XAxis type="number" {...axis} unit="%" />
                    <YAxis type="category" dataKey="name" {...axis} width={190} />
                    <Tooltip {...chartTip} formatter={(v, n, p) => [`${v}% (${num(p.payload.sessions)} sessions)`, 'Cart rate']} />
                    <Bar dataKey="cart_rate" fill="var(--series-1)" radius={[0, 4, 4, 0]} maxBarSize={16} isAnimationActive={false} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </Card>
          </>
        )
      }}
    </Loading>
  )
}

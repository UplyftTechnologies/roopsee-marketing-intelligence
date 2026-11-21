import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { day, inr, num, pct, useApi } from '../api'
import { Card, Chips, CopyTable, Loading, RateBar, Table, axis, chartTip } from '../ui'

const DIMS = [['state', 'State'], ['city', 'City'], ['age', 'Age group'], ['gender', 'Gender'], ['channel', 'First channel'],
  ['campaign', 'First campaign'], ['device', 'Device'], ['skin_type', 'Skin type'], ['segment', 'Segment'], ['landing', 'Landing page']]
const RAMP = ['var(--seq-100)', 'var(--seq-200)', 'var(--seq-300)', 'var(--seq-400)', 'var(--seq-500)', 'var(--seq-600)']

function Retention() {
  const s = useApi('/retention', { weeks: 8 })
  return (
    <Loading state={s}>
      {({ cohorts, weeks }) => (
        <Card title="Weekly retention" sub="people grouped by the week they first visited; cells = share who came back N weeks later (any session)">
          {cohorts.length === 0 ? <div className="empty">No cohorts in this range</div> : (
            <CopyTable cls="table-wrap">
              <table>
                <thead><tr><th>Cohort week</th><th className="num">People</th><th className="num">Buyers</th>{Array.from({ length: weeks + 1 }, (_, i) => <th key={i} className="num">Wk {i}</th>)}</tr></thead>
                <tbody>
                  {cohorts.map((c) => (
                    <tr key={c.cohort_week}>
                      <td>{day(c.cohort_week)}</td><td className="num">{num(c.size)}</td><td className="num">{num(c.buyers)}</td>
                      {Array.from({ length: weeks + 1 }, (_, i) => {
                        const v = c.weeks[i]
                        if (v === undefined) return <td key={i} />
                        const step = Math.min(5, Math.floor(v * 5.999))
                        return <td key={i} className="num" title={`${pct(v)} of ${num(c.size)}`} style={{ background: RAMP[step], color: step >= 3 ? '#fff' : '#0b0b0b' }}>{pct(v, 0)}</td>
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </CopyTable>
          )}
        </Card>
      )}
    </Loading>
  )
}

export default function Cohorts() {
  const [dim, setDim] = useState('state')
  const s = useApi('/cohorts', { dim })
  return (
    <>
      <Chips options={DIMS.map(([v, label]) => ({ value: v, label }))} value={dim} onChange={setDim} />
      <Loading state={s}>
        {({ rows }) => {
          const maxBuy = Math.max(0.0001, ...rows.map((r) => r.buyer_rate))
          const chart = rows.slice(0, 15)
          return (
            <>
              <div className="grid g-main">
                <Card title={`People by ${DIMS.find((d) => d[0] === dim)[1].toLowerCase()}`} sub="people = browsers/accounts, grouped by when they first visited in the selected range">
                  <ResponsiveContainer width="100%" height={Math.max(200, chart.length * 26)}>
                    <BarChart data={chart} layout="vertical" margin={{ left: 10, right: 20 }}>
                      <CartesianGrid stroke="var(--grid)" horizontal={false} />
                      <XAxis type="number" {...axis} tickFormatter={num} />
                      <YAxis type="category" dataKey="value" {...axis} width={130} />
                      <Tooltip {...chartTip} formatter={(v) => [num(v), 'People']} />
                      <Bar dataKey="people" fill="var(--series-1)" radius={[0, 4, 4, 0]} maxBarSize={16} isAnimationActive={false} />
                    </BarChart>
                  </ResponsiveContainer>
                </Card>
                <Card title="How to read this">
                  <div className="muted">
                    Each row is a cohort. <b>Cart rate</b> = people who ever added to cart; <b>Buyer rate</b> = people with a valid order.
                    Age and gender come only from people who completed the skin quiz (a minority), so those cohorts are small.
                  </div>
                </Card>
              </div>
              <Card title="Cohort table">
                <Table cols={[
                  { label: DIMS.find((d) => d[0] === dim)[1], key: 'value' },
                  { label: 'People', sortBy: 'people', num: true, render: (r) => num(r.people) },
                  { label: 'Avg sessions', sortBy: 'avg_sessions', num: true, render: (r) => r.avg_sessions },
                  { label: 'Quiz done', sortBy: 'quiz_done', num: true, render: (r) => num(r.quiz_done) },
                  { label: 'Cart rate', sortBy: 'cart_rate', num: true, render: (r) => pct(r.cart_rate, 1) },
                  { label: 'Checked out', sortBy: 'checked_out', num: true, render: (r) => num(r.checked_out) },
                  { label: 'Buyers', sortBy: 'buyers', num: true, render: (r) => num(r.buyers) },
                  { label: 'Buyer rate', sortBy: 'buyer_rate', num: true, render: (r) => <RateBar v={r.buyer_rate} max={maxBuy} text={pct(r.buyer_rate, 2)} /> },
                  { label: 'Repeat', sortBy: 'repeat_buyers', num: true, render: (r) => num(r.repeat_buyers) },
                  { label: 'Revenue', sortBy: 'revenue', num: true, render: (r) => inr(r.revenue) },
                ]} rows={rows} />
              </Card>
            </>
          )
        }}
      </Loading>
      <Retention />
    </>
  )
}

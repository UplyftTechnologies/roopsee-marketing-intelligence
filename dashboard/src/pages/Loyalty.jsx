import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { day, inr, num, pct, useApi } from '../api'
import { Card, CopyTable, Kpi, Loading, Table, axis, chartTip } from '../ui'

const RAMP = ['var(--seq-100)', 'var(--seq-200)', 'var(--seq-300)', 'var(--seq-400)', 'var(--seq-500)', 'var(--seq-600)']

function Cohorts({ cohorts, asOf }) {
  const end = new Date(asOf + 'T00:00:00')
  const maxM = Math.max(0, ...cohorts.flatMap((c) => Object.keys(c.months).map(Number)))
  const maxV = Math.max(1, ...cohorts.flatMap((c) => Object.values(c.months)))
  const cols = Array.from({ length: Math.min(maxM, 8) + 1 }, (_, i) => i)
  return (
    <Card title="Revenue per customer over time" sub="customers grouped by the month of their first order; each cell = cumulative revenue per customer, N months after that first order">
      {cohorts.length === 0 ? <div className="empty">No orders yet</div> : (
        <CopyTable cls="table-wrap">
          <table>
            <thead><tr><th>First order</th><th className="num">Customers</th>{cols.map((m) => <th key={m} className="num">Month {m}</th>)}</tr></thead>
            <tbody>
              {cohorts.map((c) => {
                let last = null
                const [cy, cm] = c.cohort.split('-').map(Number)
                const elapsed = (end.getFullYear() - cy) * 12 + (end.getMonth() + 1 - cm)
                return (
                  <tr key={c.cohort}>
                    <td>{new Date(c.cohort + 'T00:00:00').toLocaleDateString('en-IN', { month: 'short', year: 'numeric' })}</td>
                    <td className="num">{num(c.customers)}</td>
                    {cols.map((m) => {
                      if (m > elapsed) return <td key={m} />
                      if (c.months[m] !== undefined) last = c.months[m]
                      const v = c.months[m] !== undefined ? c.months[m] : null
                      const shown = v ?? (last !== null && m <= maxM ? last : null)
                      if (shown === null) return <td key={m} />
                      const step = Math.min(5, Math.floor((shown / maxV) * 5.999))
                      return <td key={m} className="num" title={v === null ? 'no further orders (carried forward)' : ''} style={{ background: RAMP[step], color: step >= 3 ? '#fff' : '#0b0b0b', opacity: v === null ? 0.65 : 1 }}>{inr(shown)}</td>
                    })}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </CopyTable>
      )}
      <div className="muted" style={{ marginTop: 8 }}>Faded cells repeat the last known value: the customers placed no further orders that month. Months that have not happened yet are left blank. Cohorts of 2–6 people, so use as a shape, not a forecast.</div>
    </Card>
  )
}

export default function Loyalty() {
  const s = useApi('/loyalty', {}, { scoped: true })
  return (
    <Loading state={s}>
      {(d) => {
        const k = d.kpis
        return (
          <>
            <div className="kpis">
              <Kpi label="Customers" value={num(k.customers)} note={`${num(k.multi_order_customers)} placed 2+ orders`} />
              <Kpi label="Came back on another day" help="repeat" value={pct(k.repeat_rate, 0)} note={`${num(k.repeat_customers)} of ${num(k.customers)} customers`} />
              <Kpi label="Revenue from returners" value={pct(k.repeat_revenue_share, 0)} note={inr(k.repeat_revenue)} />
              <Kpi label="Average lifetime value" help="ltv" value={inr(k.ltv)} note={`${k.orders_per_customer.toFixed(2)} orders per customer`} />
            </div>
            {k.same_day_multi > 0 && (
              <div className="banner">
                <div><b>{k.same_day_multi} customers placed several orders, but all on the same day.</b> They are not counted as returning, because split or retried orders are not repeat purchases.
                  <div className="muted">Median time between a customer’s orders: {d.median_gap_days === null ? '–' : `${d.median_gap_days.toFixed(1)} days`} (includes those same-day pairs).</div></div>
              </div>
            )}
            <div className="grid g2">
              <Card title="Orders per customer" sub="how many customers placed 1, 2, 3 or 4+ orders">
                <ResponsiveContainer width="100%" height={210}>
                  <BarChart data={d.dist} margin={{ left: -10, right: 8 }}>
                    <CartesianGrid stroke="var(--grid)" vertical={false} />
                    <XAxis dataKey="orders" {...axis} /><YAxis {...axis} width={36} allowDecimals={false} />
                    <Tooltip {...chartTip} formatter={(v, n, p) => [`${v} customers, ${inr(p.payload.revenue)}`, 'Customers']} labelFormatter={(l) => `${l} order${l === '1' ? '' : 's'}`} />
                    <Bar dataKey="customers" fill="var(--series-1)" radius={[4, 4, 0, 0]} maxBarSize={44} isAnimationActive={false} />
                  </BarChart>
                </ResponsiveContainer>
              </Card>
              <Card title="Time between a customer’s orders">
                <ResponsiveContainer width="100%" height={210}>
                  <BarChart data={d.gaps.map((g) => ({ ...g, label: g.gap.slice(3) }))} margin={{ left: -10, right: 8 }}>
                    <CartesianGrid stroke="var(--grid)" vertical={false} />
                    <XAxis dataKey="label" {...axis} /><YAxis {...axis} width={36} allowDecimals={false} />
                    <Tooltip {...chartTip} formatter={(v) => [v, 'Orders']} />
                    <Bar dataKey="orders" fill="var(--series-1)" radius={[4, 4, 0, 0]} maxBarSize={44} isAnimationActive={false} />
                  </BarChart>
                </ResponsiveContainer>
              </Card>
            </div>

            <div className="grid g2">
              <Card title="Customer value by first channel" sub="the channel that first brought the customer">
                <Table cols={[
                  { label: 'Channel', key: 'channel' }, { label: 'Customers', sortBy: 'customers', num: true, render: (r) => num(r.customers) },
                  { label: 'Orders', sortBy: 'orders', num: true, render: (r) => num(r.orders) }, { label: 'Revenue', sortBy: 'revenue', num: true, render: (r) => inr(r.revenue) },
                  { label: 'Lifetime value', sortBy: 'ltv', num: true, help: 'ltv', render: (r) => inr(r.ltv) }, { label: 'Came back', sortBy: 'repeaters', num: true, render: (r) => `${r.repeaters} (${pct(r.repeaters / (r.customers || 1), 0)})` },
                ]} rows={d.by_channel} />
              </Card>
              <Card title="Where customers are now" sub={`days since their last order, as of ${day(d.as_of)}`}>
                <Table cols={[
                  { label: 'Last order', sortBy: 'bucket', render: (r) => r.bucket.slice(3) }, { label: 'Customers', sortBy: 'customers', num: true, render: (r) => num(r.customers) },
                  { label: 'Came back before', sortBy: 'repeaters', num: true, render: (r) => num(r.repeaters) }, { label: 'Lifetime revenue', sortBy: 'revenue', num: true, render: (r) => inr(r.revenue) },
                ]} rows={d.recency} />
              </Card>
            </div>

            <Cohorts cohorts={d.cohorts} asOf={d.as_of} />

            <Card title="Products people buy again" sub="bought on at least two different orders by the same customer">
              <Table cols={[{ label: 'Product', sortBy: 'product_name', render: (r) => <span className="trunc" style={{ display: 'block', maxWidth: 380 }} title={r.product_name}>{r.product_name}</span> }, { label: 'Brand', key: 'brand' },
                { label: 'Customers who reordered', sortBy: 'repeat_customers', num: true, render: (r) => num(r.repeat_customers) }]} rows={d.reordered} empty="No product has been reordered by the same customer yet" />
            </Card>
            <div className="muted">This page always covers all orders (the date range at the top does not apply). Hide internal traffic still does.</div>
          </>
        )
      }}
    </Loading>
  )
}

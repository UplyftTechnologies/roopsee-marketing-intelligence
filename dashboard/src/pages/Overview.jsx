import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { day, inr, num, pct, useApi, dur, useFilters } from '../api'
import { Card, Kpi, Legend, Loading, SERIES, Table, axis, chartTip, RateBar, delta } from '../ui'

const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const RAMP = ['var(--seq-100)', 'var(--seq-200)', 'var(--seq-300)', 'var(--seq-400)', 'var(--seq-500)', 'var(--seq-600)']

function Heatmap({ hours }) {
  const m = {}
  let max = 0
  hours.forEach((h) => { m[`${h.dow}-${h.hour}`] = h.sessions; max = Math.max(max, h.sessions) })
  return (
    <div>
      <div className="heat">
        <span />
        {Array.from({ length: 24 }, (_, h) => <span key={h} style={{ textAlign: 'center' }}>{h % 3 === 0 ? h : ''}</span>)}
        {DOW.map((d, di) => (
          <>
            <span key={d} className="lab">{d}</span>
            {Array.from({ length: 24 }, (_, h) => {
              const v = m[`${di}-${h}`] || 0
              const step = v ? Math.min(5, Math.floor((v / max) * 5.999)) : -1
              return <span key={h} className="cell" title={`${d} ${h}:00 – ${num(v)} sessions`} style={step >= 0 ? { background: RAMP[step] } : undefined} />
            })}
          </>
        ))}
      </div>
      <div className="legend">Sessions by hour of day (IST) · lighter = fewer, darker = more · peak {num(max)}</div>
    </div>
  )
}

const dd = (f, k, p, key, kind) => (f.compare && p ? delta(k[key], p[key], kind) : null)

export default function Overview() {
  const f = useFilters()
  const s = useApi('/overview')
  return (
    <Loading state={s}>
      {({ kpis: k, prev: p, daily, channels, devices, hours, landing, staff_orders: so }) => (
        <>
          {so.orders > 0 && (
            <div className={`banner ${so.excluded ? '' : 'ok'}`}>
              <div>
                <b>{num(so.orders)} orders ({inr(so.revenue)}) were placed from admin / staff accounts</b> in this range.{' '}
                {so.excluded
                  ? 'They are currently excluded from every metric below as team / test orders.'
                  : 'They are currently counted as real customer orders.'}
                <div className="muted">Team keying in real customer orders? Turn the <span className="mono">staff_orders</span> rule off in Exclusions to count them.</div>
              </div>
            </div>
          )}
          <div className="kpis">
            <Kpi label="Sessions" help="sessions" value={num(k.sessions)} d={dd(f, k, p, 'sessions')} note={`${num(k.visitors)} browsers · ${num(k.people)} people`} />
            <Kpi label="Orders" help="orders" value={num(k.orders)} d={dd(f, k, p, 'orders')} note={`${pct(k.order_cvr, 2)} of sessions`} />
            <Kpi label="Revenue" help="revenue" value={inr(k.revenue)} d={dd(f, k, p, 'revenue')} note={`AOV ${inr(k.aov)}`} />
            <Kpi label="Added to cart" help="cart" value={num(k.cart_sessions)} d={dd(f, k, p, 'cart_sessions')} note={`${pct(k.cart_rate)} of sessions`} />
            <Kpi label="Reached checkout" help="checkout" value={num(k.checkout_sessions)} d={dd(f, k, p, 'checkout_sessions')} />
            <Kpi label="Quiz completed" help="quiz" value={num(k.quiz_done)} d={dd(f, k, p, 'quiz_done')} note={`${num(k.quiz_started)} with a tracked start`} />
            <Kpi label="Bounce rate" help="bounce" value={pct(k.bounce_rate)} d={dd(f, k, p, 'bounce_rate', 'rate')} goodWhen="down" />
            <Kpi label="Avg session" help="avgSession" value={dur(k.avg_duration_s)} note={`${num(k.app_sessions)} in Android app`} />
          </div>

          <div className="grid g-main">
            <Card title="Sessions per day">
              <ResponsiveContainer width="100%" height={230}>
                <BarChart data={daily} margin={{ left: -10, right: 8 }}>
                  <CartesianGrid stroke="var(--grid)" vertical={false} />
                  <XAxis dataKey="date" tickFormatter={day} {...axis} minTickGap={24} />
                  <YAxis {...axis} width={46} tickFormatter={num} />
                  <Tooltip {...chartTip} labelFormatter={day} formatter={(v) => [num(v), 'Sessions']} />
                  <Bar dataKey="sessions" fill="var(--series-1)" radius={[3, 3, 0, 0]} maxBarSize={14} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </Card>
            <Card title="Where sessions come from" sub="click a channel to see its sessions">
              <Table
                cols={[
                  { label: 'Channel', key: 'channel' },
                  { label: 'Sessions', num: true, render: (r) => <RateBar v={r.sessions} max={channels[0]?.sessions} text={num(r.sessions)} /> },
                  { label: 'Carts', num: true, render: (r) => num(r.carts) },
                  { label: 'Orders', num: true, render: (r) => num(r.orders) },
                ]}
                rows={channels}
                onRow={(r) => f.go('sessions', { channel: r.channel })}
              />
            </Card>
          </div>

          <div className="grid g2">
            <Card title="Cart, checkout and order sessions per day" sub="same scale, no dual axis">
              <ResponsiveContainer width="100%" height={230}>
                <LineChart data={daily} margin={{ left: -10, right: 8 }}>
                  <CartesianGrid stroke="var(--grid)" vertical={false} />
                  <XAxis dataKey="date" tickFormatter={day} {...axis} minTickGap={24} />
                  <YAxis {...axis} width={40} allowDecimals={false} />
                  <Tooltip {...chartTip} labelFormatter={day} />
                  <Line type="monotone" dataKey="carts" name="Added to cart" stroke={SERIES[0]} strokeWidth={2} dot={false} activeDot={{ r: 4 }} isAnimationActive={false} />
                  <Line type="monotone" dataKey="checkouts" name="Reached checkout" stroke={SERIES[1]} strokeWidth={2} dot={false} activeDot={{ r: 4 }} isAnimationActive={false} />
                  <Line type="monotone" dataKey="orders" name="Orders" stroke={SERIES[2]} strokeWidth={2} dot={false} activeDot={{ r: 4 }} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
              <Legend items={[['Added to cart', SERIES[0]], ['Reached checkout', SERIES[1]], ['Orders', SERIES[2]]]} />
            </Card>
            <Card title="Revenue per day">
              <ResponsiveContainer width="100%" height={230}>
                <BarChart data={daily} margin={{ left: -4, right: 8 }}>
                  <CartesianGrid stroke="var(--grid)" vertical={false} />
                  <XAxis dataKey="date" tickFormatter={day} {...axis} minTickGap={24} />
                  <YAxis {...axis} width={54} tickFormatter={inr} />
                  <Tooltip {...chartTip} labelFormatter={day} formatter={(v) => [inr(v), 'Revenue']} />
                  <Bar dataKey="revenue" fill="var(--series-1)" radius={[3, 3, 0, 0]} maxBarSize={14} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </Card>
          </div>

          <div className="grid g-main">
            <Card title="When people visit"><Heatmap hours={hours} /></Card>
            <div className="grid" style={{ gap: 14 }}>
              <Card title="Device">
                <Table cols={[{ label: 'Device', key: 'device' }, { label: 'Sessions', num: true, render: (r) => <RateBar v={r.sessions} max={devices[0]?.sessions} text={num(r.sessions)} /> }]} rows={devices} />
              </Card>
              <Card title="Landing page type" sub="where sessions start">
                <Table cols={[{ label: 'Page', key: 'landing_type' }, { label: 'Sessions', num: true, render: (r) => num(r.sessions) }, { label: 'Cart rate', num: true, render: (r) => pct(r.carts / r.sessions) }]} rows={landing} />
              </Card>
            </div>
          </div>
        </>
      )}
    </Loading>
  )
}

import { useEffect, useState } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { dt, inr, num, pct, useApi, useFilters, usePersisted } from '../api'
import { Badge, Card, Chips, ExportBtn, Loading, Pager, Search, Table, axis, chartTip, nextSort } from '../ui'
import { Heatmap } from './Overview'
import { METRICS } from '../metrics'
import { Scorecard, ScorecardStrip } from '../components/Scorecard'
import MetricChart from '../components/MetricChart'
import ShareLink from '../components/ShareLink'

export const STATUS_TONE = { placed: '', accepted: '', picked_up: '', out_for_delivery: 'warn', delivered: 'good', completed: 'good', payment_cancelled: 'bad', payment_pending: 'warn' }
const ordinal = (n) => { const t = n % 100; return n + (t >= 11 && t <= 13 ? 'th' : ['th', 'st', 'nd', 'rd'][n % 10] || 'th') }
export const niceStatus = (s) => (s || '–').replace(/_/g, ' ')
const SCOPES = [['sales', 'Sales', 'Orders that count as sales (paid or cash on delivery), excluding test and internal orders'], ['all', 'All orders', 'Every real order, including ones where payment was cancelled or is pending'],
  ['unpaid', 'Payment cancelled / pending', 'Orders that never completed payment'], ['internal', 'Internal & test', 'Test orders and orders from staff accounts or excluded customers']]
const TEXT_SORTS = ['customer_name', 'city', 'status', 'payment_method', 'coupon_code']

/** Multi-select chips for filter values. */
function MultiPick({ label, options, value, onChange }) {
  if (!options?.length) return null
  return (
    <div className="chip-row" role="group" aria-label={label}>
      <span className="muted" style={{ fontSize: 12, minWidth: 74 }}>{label}</span>
      {options.map((o) => {
        const on = value.includes(o)
        return <button key={o} type="button" className={`chip ${on ? 'on' : ''}`} aria-pressed={on} onClick={() => onChange(on ? value.filter((x) => x !== o) : [...value, o])}>{on ? '✓ ' : ''}{niceStatus(o)}</button>
      })}
    </div>
  )
}

function OrdersTable() {
  const f = useFilters()
  const sh = f.prefill?.share || null  // opened from a shared link
  const [scope, setScope] = usePersisted('orders.scope', sh?.scope ?? 'sales', !!sh)
  const [status, setStatus] = usePersisted('orders.status', sh?.status ?? [], !!sh)
  const [payment, setPayment] = usePersisted('orders.payment', sh?.payment ?? [], !!sh)
  const [coupon, setCoupon] = usePersisted('orders.coupon', sh?.coupon ?? '', !!sh)
  const [search, setSearch] = usePersisted('orders.search', sh?.search ?? '', !!sh)
  const [sort, setSort] = usePersisted('orders.sort', sh?.sort ?? { key: 'ts', dir: 'desc' }, !!sh)
  const [offset, setOffset] = useState(0)
  const [limit, setLimit] = usePersisted('orders.limit', sh?.limit ?? 25, !!sh)
  const s = useApi('/orders', { scope, status: status.join(',') || undefined, payment: payment.join(',') || undefined, coupon: coupon || undefined, search, sort: sort.key, direction: sort.dir, limit, offset })
  useEffect(() => setOffset(0), [scope, status, payment, coupon, search, sort, limit])
  return (
    <>
      <div className="chip-row">
        <Search value={search} onChange={setSearch} placeholder="Search order id, name, phone, email, city, pincode, coupon…" />
        <ShareLink tab="orders" state={{ scope, status, payment, coupon, search, sort }} />
      </div>
      <div className="chip-row" role="group" aria-label="Which orders">
        {SCOPES.map(([k, l, tip]) => <button key={k} type="button" title={tip} className={`chip ${scope === k ? 'on' : ''}`} onClick={() => setScope(k)}>{l}</button>)}
      </div>
      <Loading state={s}>
        {({ rows, total, summary, options }) => (
          <>
            <Card title="Filters" sub="pick any combination">
              <MultiPick label="Status" options={options.statuses} value={status} onChange={setStatus} />
              <div style={{ marginTop: 6 }}><MultiPick label="Payment" options={options.payment_methods} value={payment} onChange={setPayment} /></div>
              <div className="chip-row" style={{ marginTop: 6 }}>
                <span className="muted" style={{ fontSize: 12, minWidth: 74 }}>Coupon</span>
                <select className="field" value={coupon} onChange={(e) => setCoupon(e.target.value)} aria-label="Coupon"><option value="">Any</option>{options.coupons.map((c) => <option key={c}>{c}</option>)}</select>
                {(status.length > 0 || payment.length > 0 || coupon) && <button type="button" className="btn small" onClick={() => { setStatus([]); setPayment([]); setCoupon('') }}>Clear filters</button>}
              </div>
            </Card>
            <Card title={`${num(total)} orders`} sub={`${inr(summary.gmv)} order value · ${inr(summary.aov)} average · click an order for everything about it · click a column title to sort`}
              right={<ExportBtn name="orders" rows={rows} fields={[['Order id', 'order_id'], ['Placed', 'ts'], ['Customer', 'customer_name'], ['Phone', 'phone10'], ['Email', 'email'], ['City', 'city'], ['Pincode', 'pincode'], ['Items', 'items'], ['Order value', 'total'], ['Products total', 'products_total'], ['Coupon', 'coupon_code'], ['Coupon discount', 'coupon_discount'], ['Delivery fee', 'delivery_fee'], ['Payment', 'payment_method'], ['Payment status', 'payment_status'], ['Status', 'status'], ['Failure reason', 'payment_failed_reason'], ['Customer order #', 'nth_order'], ['Channel', 'channel'], ['Campaign', 'campaign']]} />}>
              <Table scroll sort={sort} onSort={(k) => setSort(nextSort(sort, k, TEXT_SORTS))} onRow={(r) => f.go('order', { key: r.order_id })}
                rowClass={(r) => (r.is_excluded || !r.is_valid ? 'excluded' : '')} empty="No orders match these filters." rows={rows} cols={[
                  { label: 'Order', cls: 'mono nw', render: (r) => r.order_id.slice(0, 8) },
                  { label: 'Placed', cls: 'nw', sortBy: 'ts', render: (r) => dt(r.ts) },
                  { label: 'Customer', cls: 'nw', sortBy: 'customer_name', render: (r) => <>{r.customer_name || <span className="muted">no name</span>}{(r.phone10 || r.nth_order > 1) && <div className="muted mono" style={{ fontSize: 11.5 }}>{r.phone10}{r.nth_order > 1 ? `${r.phone10 ? ' · ' : ''}${ordinal(r.nth_order)} order` : ''}</div>}</> },
                  { label: 'City', cls: 'nw', sortBy: 'city', render: (r) => r.city || '–' },
                  { label: 'Items', sortBy: 'items_count', render: (r) => <span className="trunc" style={{ display: 'block', maxWidth: 190 }} title={r.items}>{r.items_count} · {r.items || '–'}</span> },
                  { label: 'Order value', num: true, sortBy: 'total', render: (r) => <b>{inr(r.total)}</b> },
                  { label: 'Coupon', cls: 'nw', sortBy: 'coupon_code', render: (r) => (r.coupon_code ? <span title={r.coupon_discount ? `${inr(r.coupon_discount)} off` : ''}>{r.coupon_code.split(',')[0]}</span> : <span className="muted">–</span>) },
                  { label: 'Payment', cls: 'nw', sortBy: 'payment_method', render: (r) => r.payment_method || <span className="muted">–</span> },
                  { label: 'Status', cls: 'nw', sortBy: 'status', render: (r) => <span title={r.payment_failed_reason || ''}><Badge tone={STATUS_TONE[r.status]}>{niceStatus(r.status)}</Badge>{r.is_valid && (r.payment_state === 'unconfirmed' || r.payment_state === 'conflicting') ? <> <Badge tone="warn">{r.payment_state === 'conflicting' ? 'payment conflict' : 'payment unconfirmed'}</Badge></> : null}</span> },
                  { label: '', render: (r) => (r.is_test ? <Badge>test</Badge> : r.is_staff_order ? <Badge tone="warn">staff</Badge> : r.is_excluded ? <Badge tone="bad">excluded</Badge> : null) },
                ]} />
              <Pager total={total} limit={limit} offset={offset} setOffset={setOffset} setLimit={setLimit} />
            </Card>
          </>
        )}
      </Loading>
    </>
  )
}

const CARDS = ['o_orders', 'gmv', 'o_aov', 'cancelled']
function Analytics() {
  const f = useFilters()
  const s = useApi('/orders/analytics')
  const [metric, setMetric] = useState('gmv')
  return (
    <Loading state={s}>
      {(a) => {
        const k = a.kpis
        const ts = { dates: a.dates, current: a.current, previous: a.previous, prev_dates: a.prev_dates }
        const online = a.payment.filter((p) => !/^cod/i.test(p.method) && p.attempts)
        const onlineAttempts = online.reduce((x, p) => x + p.attempts, 0)
        const onlineOrders = online.reduce((x, p) => x + p.orders, 0)
        return (
          <>
            <ScorecardStrip>
              {CARDS.map((m) => <Scorecard key={m} metric={m} kpis={k} prev={a.prev} compare={f.compare} spark={a.current[METRICS[m].series]} active={metric === m} onClick={() => setMetric(m)} />)}
              <Scorecard metric="cod_share" kpis={k} prev={a.prev} compare={f.compare} note={`${num(k.cod_orders)} COD · ${num(k.online_orders)} online`} />
              <Scorecard metric="repeat_share" kpis={k} prev={a.prev} compare={f.compare} note={`${num(k.first_orders)} first · ${num(k.repeat_orders)} repeat`} />
            </ScorecardStrip>
            <Card title={METRICS[metric].label} sub="Click a tile above to change the chart">
              <MetricChart ts={ts} metric={metric} compare={f.compare} height={240} ranges={{ cur: f.rangeText, prev: f.prevText }} />
            </Card>

            {a.revenue_split?.length > 0 && (
              <Card title="Revenue by payment status" sub="every valid sale counts as revenue; this is how much of it is paid">
                <div className="mini-list">
                  {a.revenue_split.map((x) => (
                    <div key={x.state} className="mini-row">
                      <span className="name">{{ confirmed: 'Paid (confirmed)', cod_pending: 'Cash on delivery, not collected yet', unconfirmed: 'No confirmed payment', conflicting: 'Payment shows cancelled, order went ahead' }[x.state] || x.state}</span>
                      <span className="val">{num(x.orders)} orders · {inr(x.revenue)}</span>
                      <span className="mini-bar"><i style={{ width: `${(x.revenue / Math.max(1, k.gmv)) * 100}%` }} /></span>
                    </div>
                  ))}
                </div>
                <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
                  Discounts given: coupons {inr(k.coupon_discount)} and wallet credit {inr(k.wallet_used)} (the recorded coupon amount also holds the wallet amount when no coupon code was used; it is shown separately here).
                </div>
              </Card>
            )}
            {(k.at_risk_orders > 0 || k.cod_pending_orders > 0) && (
              <div className="banner">
                <div>
                  {k.at_risk_orders > 0 && <><b>{num(k.at_risk_orders)} counted sale{k.at_risk_orders === 1 ? '' : 's'} ({inr(k.at_risk_value)}) {k.at_risk_orders === 1 ? 'has' : 'have'} no confirmed payment.</b> They are included in the numbers above; check them before relying on revenue. </>}
                  {k.cod_pending_orders > 0 && <span className="muted">{num(k.cod_pending_orders)} cash-on-delivery order{k.cod_pending_orders === 1 ? '' : 's'} ({inr(k.cod_pending_value)}) {k.cod_pending_orders === 1 ? 'is' : 'are'} waiting for cash collection, which is normal.</span>}
                </div>
              </div>
            )}

            {onlineAttempts >= 5 && onlineOrders / onlineAttempts < 0.6 && (
              <div className="banner">
                <div><b>Only {pct(onlineOrders / onlineAttempts, 0)} of online payment attempts complete.</b> {num(onlineAttempts - onlineOrders)} of {num(onlineAttempts)} online orders were abandoned or cancelled at payment, while cash on delivery orders almost always go through.
                  <div className="muted">The reasons recorded are listed below; this is the biggest revenue leak in the orders data.</div></div>
              </div>
            )}

            <div className="grid g2">
              <Card title="Payments" sub="attempts → completed, by payment method">
                <Table rows={a.payment} empty="No orders in this range" cols={[
                  { label: 'Method', key: 'method' }, { label: 'Attempts', num: true, sortBy: 'attempts', render: (r) => num(r.attempts) }, { label: 'Completed', num: true, sortBy: 'orders', render: (r) => num(r.orders) },
                  { label: 'Cancelled', num: true, sortBy: 'cancelled', render: (r) => num(r.cancelled) }, { label: 'Success', num: true, sortBy: (r) => (r.attempts ? r.orders / r.attempts : 0), render: (r) => pct(r.attempts ? r.orders / r.attempts : 0, 0) },
                  { label: 'Order value', num: true, sortBy: 'gmv', render: (r) => inr(r.gmv) }]} />
              </Card>
              <Card title="Why payments failed" sub="recorded reason on cancelled / pending orders">
                <Table rows={a.failures} empty="No failed payments in this range" cols={[{ label: 'Reason', key: 'reason' }, { label: 'Orders', num: true, sortBy: 'n', render: (r) => num(r.n) }]} />
              </Card>
            </div>

            <div className="grid g2">
              <Card title="Order status" sub="where orders are in their life">
                <Table rows={a.status} cols={[{ label: 'Status', sortBy: 'status', render: (r) => <Badge tone={STATUS_TONE[r.status]}>{niceStatus(r.status)}</Badge> }, { label: 'Orders', num: true, sortBy: 'n', render: (r) => num(r.n) }, { label: 'Value', num: true, sortBy: 'gmv', render: (r) => inr(r.gmv) }]} />
              </Card>
              <Card title="Delivery" sub="valid orders in this range">
                <div className="kpis" style={{ gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }}>
                  <div className="kpi"><div className="label">Marked delivered</div><div className="value">{num(a.delivery.delivered)}</div><div className="note">of {num(k.orders)} orders</div></div>
                  <div className="kpi"><div className="label">Median time to deliver</div><div className="value">{a.delivery.median_h == null ? '–' : `${a.delivery.median_h.toFixed(1)}h`}</div><div className="note">{a.delivery.delivered ? `${pct(a.delivery.within_24h / a.delivery.delivered, 0)} within 24h` : 'no deliveries recorded'}</div></div>
                </div>
                <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>Only orders whose status was updated to delivered are counted, so this understates deliveries if status updates are missed.</div>
              </Card>
            </div>

            <div className="grid g2">
              <Card title="Coupons" sub="valid orders by coupon">
                <Table rows={a.coupons} cols={[{ label: 'Coupon', key: 'coupon' }, { label: 'Orders', num: true, sortBy: 'orders', render: (r) => num(r.orders) }, { label: 'Order value', num: true, sortBy: 'gmv', render: (r) => inr(r.gmv) },
                  { label: 'Avg order', num: true, sortBy: 'aov', render: (r) => inr(r.aov) }, { label: 'Avg discount', num: true, sortBy: 'avg_discount', render: (r) => (r.avg_discount ? inr(r.avg_discount) : '–') }]} />
                <div className="muted" style={{ marginTop: 6, fontSize: 12 }}>Coupons gave away {pct(k.discount_pct, 0)} of product value in this range ({inr(k.coupon_discount)}).</div>
              </Card>
              <Card title="New vs repeat customers">
                <Table rows={a.customers} cols={[{ label: 'Customer', key: 'kind' }, { label: 'Orders', num: true, sortBy: 'orders', render: (r) => num(r.orders) }, { label: 'Order value', num: true, sortBy: 'gmv', render: (r) => inr(r.gmv) }, { label: 'Avg order', num: true, sortBy: 'aov', render: (r) => inr(r.aov) }]} />
              </Card>
            </div>

            <div className="grid g2">
              <Card title="Top cities">
                <Table rows={a.cities} cols={[{ label: 'City', key: 'city' }, { label: 'Orders', num: true, sortBy: 'orders', render: (r) => num(r.orders) }, { label: 'Order value', num: true, sortBy: 'gmv', render: (r) => inr(r.gmv) }, { label: 'Avg order', num: true, sortBy: 'aov', render: (r) => inr(r.aov) }]} />
              </Card>
              <Card title="Top pincodes">
                <Table rows={a.pincodes} cols={[{ label: 'Pincode', key: 'pincode', cls: 'mono' }, { label: 'City', key: 'city' }, { label: 'Orders', num: true, sortBy: 'orders', render: (r) => num(r.orders) }, { label: 'Order value', num: true, sortBy: 'gmv', render: (r) => inr(r.gmv) }]} />
              </Card>
            </div>

            <div className="grid g2">
              <Card title="Order value distribution" sub="valid orders by size">
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={a.buckets.map((b) => ({ ...b, label: b.band.slice(3) }))} margin={{ left: -14, right: 6 }}>
                    <CartesianGrid stroke="var(--grid)" vertical={false} /><XAxis dataKey="label" {...axis} /><YAxis {...axis} allowDecimals={false} width={36} />
                    <Tooltip {...chartTip} formatter={(v) => [v, 'Orders']} /><Bar dataKey="orders" fill="var(--series-1)" radius={[4, 4, 0, 0]} maxBarSize={44} isAnimationActive={false} />
                  </BarChart>
                </ResponsiveContainer>
              </Card>
              <Card title="Where orders come from" sub="channel of the order's own session. A Direct order is credited to the last campaign visit in the 7 days before it, when there was one.">
                <Table rows={a.credited_channels || a.channels} cols={[{ label: 'Channel', key: 'channel' }, { label: 'Orders', num: true, sortBy: 'orders', render: (r) => num(r.orders) }, { label: 'Order value', num: true, sortBy: 'gmv', render: (r) => inr(r.gmv) }, { label: 'Avg order', num: true, sortBy: 'aov', render: (r) => inr(r.aov) }]} />
              </Card>
            </div>
            <Card title="When people order"><Heatmap hours={a.hours.map((h) => ({ ...h, sessions: h.orders }))} unit="orders" /></Card>
            {a.riders.length > 0 && a.riders.some((r) => r.rider !== 'Unassigned') && (
              <Card title="Riders"><Table rows={a.riders} cols={[{ label: 'Rider', key: 'rider' }, { label: 'Orders', num: true, sortBy: 'orders', render: (r) => num(r.orders) }, { label: 'Delivered', num: true, sortBy: 'delivered', render: (r) => num(r.delivered) }, { label: 'Median hours', num: true, sortBy: 'median_h', render: (r) => (r.median_h == null ? '–' : r.median_h.toFixed(1)) }]} /></Card>
            )}
          </>
        )
      }}
    </Loading>
  )
}

export default function Orders() {
  const f = useFilters()
  const [tab, setTab] = useState(f.prefill?.tab || new URLSearchParams(location.search).get('otab') || 'orders')
  return (
    <>
      <Chips value={tab} onChange={setTab} options={[{ value: 'orders', label: 'All orders' }, { value: 'analytics', label: 'Order analytics' }]} />
      {tab === 'orders' ? <OrdersTable /> : <Analytics />}
    </>
  )
}

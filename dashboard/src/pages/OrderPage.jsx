import { dt, inr, num, tod, useApi, useFilters } from '../api'
import { Badge, Card, Table } from '../ui'
import { CopyBtn, Facts } from '../components/profile'
import Icon from '../components/Icon'
import { STATUS_TONE, niceStatus } from './Orders'

const ord = (n) => { const t = n % 100; return n + (t >= 11 && t <= 13 ? 'th' : ['th', 'st', 'nd', 'rd'][n % 10] || 'th') }

export default function OrderPage() {
  const f = useFilters()
  const id = f.prefill?.key
  const s = useApi(`/orders/${encodeURIComponent(id || '')}`, {}, { scoped: false })
  if (s.error) return <div className="banner err">Could not load this order. {s.error} <button className="btn small" onClick={f.back}>Back to {f.backLabel}</button></div>
  if (!s.data) return <div className="skeleton" style={{ height: 320 }} />
  const { order: o, items, timeline, customer, other_orders: others, session } = s.data
  const t0 = timeline.length ? new Date(timeline[0].at).getTime() : 0
  const gap = (at) => { const m = Math.round((new Date(at).getTime() - t0) / 60000); return m < 1 ? '' : m < 90 ? `+${m} min` : m < 2880 ? `+${(m / 60).toFixed(1)} h` : `+${(m / 1440).toFixed(1)} d` }

  return (
    <>
      <div className="profile-head">
        <button type="button" className="pill-btn" onClick={f.back}><Icon name="left" size={16} />{f.backLabel}</button>
        <div style={{ minWidth: 0, flex: 1 }}>
          <h2 style={{ fontSize: 20 }}>{inr(o.total)} <span className="muted" style={{ fontSize: 14, fontWeight: 400 }}>· {dt(o.ts)}</span></h2>
          <div className="muted mono" style={{ fontSize: 12 }}>{o.order_id} <CopyBtn text={o.order_id} title="Copy order id" /></div>
          <div className="chip-row" style={{ marginTop: 6 }}>
            <Badge tone={STATUS_TONE[o.status]}>{niceStatus(o.status)}</Badge>
            {o.payment_method && <Badge>{o.payment_method}</Badge>}
            {o.nth_order && <Badge>{ord(o.nth_order)} order of this customer</Badge>}
            {o.is_test && <Badge>test order</Badge>}{o.is_staff_order && <Badge tone="warn">placed from a staff account</Badge>}{o.is_excluded && !o.is_test && <Badge tone="bad">excluded from analytics</Badge>}
          </div>
        </div>
        {session && <button type="button" className="pill-btn" onClick={() => f.go('session', { key: session.session_id })}>View session →</button>}
        {customer && <button type="button" className="pill-btn" onClick={() => f.go('person', { key: customer.person_key })}>View customer →</button>}
      </div>

      {!o.is_placed && (
        <div className="banner">
          <div><b>This order was never completed.</b> {o.payment_failed_reason ? `Reason recorded: “${o.payment_failed_reason}”.` : 'No reason was recorded.'}
            <div className="muted">It is not counted as a sale in any revenue number.</div></div>
        </div>
      )}

      <div className="scorecards">
        <div className="sc static"><span className="sc-label">Order value</span><span className="sc-value">{inr(o.total)}</span><span className="sc-note">what the customer paid</span></div>
        <div className="sc static"><span className="sc-label">Products</span><span className="sc-value">{inr(o.products_total)}</span><span className="sc-note">{num(o.items_count)} item{o.items_count === 1 ? '' : 's'} before discounts</span></div>
        <div className="sc static"><span className="sc-label">Discount</span><span className="sc-value">{inr(o.coupon_discount || 0)}</span><span className="sc-note">{o.coupon_code ? o.coupon_code : 'no coupon'}</span></div>
        <div className="sc static"><span className="sc-label">Delivery fee</span><span className="sc-value">{o.delivery_fee ? inr(o.delivery_fee) : 'Free'}</span><span className="sc-note">{o.handling_fee ? `+ ${inr(o.handling_fee)} handling` : 'no handling fee'}</span></div>
        <div className="sc static"><span className="sc-label">Wallet used</span><span className="sc-value">{inr(o.wallet_amount_used || 0)}</span><span className="sc-note">{o.cashback_amount ? `${inr(o.cashback_amount)} cashback` : 'no cashback'}</span></div>
      </div>

      <div className="grid g-main">
        <div className="stack">
          <Card title={`Items (${items.length})`}>
            <Table rows={items} empty="No item details stored for this order" cols={[
              { label: 'Product', render: (i) => <span className="trunc" style={{ display: 'block', maxWidth: 340 }} title={i.product_name}>{i.product_name}</span>, sortBy: 'product_name' },
              { label: 'Brand', key: 'brand' }, { label: 'Type', key: 'product_type' },
              { label: 'Qty', num: true, sortBy: 'qty', render: (i) => i.qty }, { label: 'Price', num: true, sortBy: 'price', render: (i) => inr(i.price) }, { label: 'Line total', num: true, sortBy: 'line_total', render: (i) => <b>{inr(i.line_total)}</b> },
            ]} />
          </Card>
          <Card title="What happened, in order" sub="from the timestamps recorded on the order">
            {timeline.length === 0 ? <div className="empty">No timestamps recorded</div> : (
              <div className="timeline">
                {timeline.map((e) => (
                  <div key={e.label} className="tl-item key"><span className="tl-time">{dt(e.at)} <small>{tod(e.at)}</small></span><b>{e.label}</b> <span className="muted">{gap(e.at)}</span></div>
                ))}
              </div>
            )}
            {o.status && !['placed', 'payment_cancelled', 'payment_pending'].includes(o.status) && !o.delivered_at && o.status !== 'completed' && <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>Current status: {niceStatus(o.status)}</div>}
          </Card>
          {others.length > 0 && (
            <Card title={`This customer's other orders (${others.length})`}>
              <Table onRow={(r) => f.go('order', { key: r.order_id })} rows={others} cols={[{ label: 'Placed', sortBy: 'ts', render: (r) => dt(r.ts) }, { label: 'Value', num: true, sortBy: 'total', render: (r) => inr(r.total) },
                { label: 'Status', render: (r) => <Badge tone={STATUS_TONE[r.status]}>{niceStatus(r.status)}</Badge> }, { label: '#', num: true, render: (r) => r.nth_order || '–' }]} />
            </Card>
          )}
        </div>
        <div className="stack">
          <Card title="Customer" right={customer && <button type="button" className="btn small" onClick={() => f.go('person', { key: customer.person_key })}>Profile →</button>}>
            <Facts rows={[['Name', o.customer_name], ['Phone', o.phone10], ['Email', o.email_l], ['City', [o.city, o.state].filter(Boolean).join(', ')], ['Pincode', o.pincode],
              ['Segment', customer?.segment], ['Sessions', customer?.sessions ? num(customer.sessions) : null], ['Orders so far', customer?.orders ? num(customer.orders) : null], ['First came via', customer?.first_channel]]} />
          </Card>
          <Card title="Payment">
            <Facts rows={[['Method', o.payment_method], ['Payment status', o.payment_status], ['Order status', niceStatus(o.status)], ['Paid at', o.paid_at ? dt(o.paid_at) : null], ['Failure reason', o.payment_failed_reason], ['Cash collected', o.cod_collected_at ? dt(o.cod_collected_at) : null]]} />
          </Card>
          <Card title="Delivery">
            <Facts rows={[['Rider', o.rider_name], ['Courier', o.courier_partner], ['Tracking id', o.tracking_id], ['Picked up', o.picked_up_at ? dt(o.picked_up_at) : null], ['Out for delivery', o.delivery_started_at ? dt(o.delivery_started_at) : null],
              ['Delivered', o.delivered_at ? dt(o.delivered_at) : null]]} />
            {!o.rider_name && !o.courier_partner && !o.delivered_at && <div className="muted" style={{ fontSize: 12 }}>No delivery details recorded yet.</div>}
          </Card>
          <Card title="Where it came from" right={session && <button type="button" className="btn small" onClick={() => f.go('session', { key: session.session_id })}>Session →</button>}>
            {session ? <Facts rows={[['Channel', o.channel], ['Source / medium', `${o.source} / ${o.medium}`], ['Campaign', o.campaign !== '(not set)' ? o.campaign : null], ['Landing page', session.landing_path], ['Device', o.is_app ? 'Android app' : o.device], ['Session started', dt(session.started_at)]]} />
              : <div className="muted">This order is not linked to a tracked session (older orders and some cash-on-delivery orders), so its source is unknown.</div>}
          </Card>
        </div>
      </div>
    </>
  )
}

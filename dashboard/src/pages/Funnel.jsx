import { useState } from 'react'
import { dt, inr, num, pct, useApi } from '../api'
import { Badge, Card, Chips, Loading, Table } from '../ui'

const RAMP = ['var(--seq-250)', 'var(--seq-300)', 'var(--seq-350)', 'var(--seq-400)', 'var(--seq-500)', 'var(--seq-600)']
const OUTCOME = {
  ordered: ['Ordered', 'good'], payment_abandoned: ['Abandoned at payment', 'serious'],
  checkout_abandoned: ['Left at checkout', 'warn'], address_only: ['Only entered address', ''],
}
const CHANNELS = ['All', 'Paid Google', 'Paid Meta', 'MyGate Partner', 'Organic Search', 'Organic Social', 'Direct', 'Referral']

export default function Funnel() {
  const [channel, setChannel] = useState('All')
  const s = useApi('/funnel', { channel: channel === 'All' ? undefined : channel })
  return (
    <>
      <Chips options={CHANNELS} value={channel} onChange={setChannel} />
      <Loading state={s}>
        {(d) => {
          const top = d.stages[0].sessions || 1
          return (
            <>
              <Card title="Purchase funnel" sub="share of sessions that reached each step (each step = a session that did the action)">
                {d.stages.map((st, i) => (
                  <div className="fn-row" key={st.stage}>
                    <div>{st.stage}</div>
                    <div><div className="fn-bar" style={{ width: `${Math.max(0.5, (st.sessions / top) * 100)}%`, background: RAMP[i] }} title={`${num(st.sessions)} sessions`} /></div>
                    <div className="fn-meta"><b style={{ color: 'var(--text-primary)' }}>{num(st.sessions)}</b> · {pct(st.of_first, 2)} of all{i ? ` · ${pct(st.of_prev, 0)} of prev` : ''}</div>
                  </div>
                ))}
                <div className="muted" style={{ marginTop: 6 }}>
                  Tracked order sessions: {num(d.stages[5].sessions)} · orders in the database for this range: <b>{num(d.actual_orders)}</b> (some orders – COD, older sessions – have no tracked checkout events).
                </div>
              </Card>

              <div className="grid g2">
                <Card title="Skin quiz & login" sub="the quiz is the main lead magnet">
                  <Table cols={[{ label: 'Step', key: 'k' }, { label: 'Sessions', num: true, key: 'v', render: (r) => num(r.v) }]}
                    rows={[
                      { k: 'Quiz started', v: d.quiz.quiz_start }, { k: 'Quiz completed', v: d.quiz.quiz_done },
                      { k: 'Quiz completed AND added to cart', v: d.quiz.quiz_to_cart }, { k: 'Logged in (OTP / Google)', v: d.quiz.login },
                    ]} />
                  <div className="muted" style={{ marginTop: 8 }}>{d.quiz.quiz_done <= d.quiz.quiz_start ? `Quiz completion ${pct(d.quiz.quiz_done / (d.quiz.quiz_start || 1), 0)} · ` : 'Older tracking logged completions without a start event · '}quiz → cart {pct(d.quiz.quiz_to_cart / (d.quiz.quiz_done || 1), 0)}</div>
                </Card>
                <Card title="Checkout outcomes" sub="sessions that reached checkout or payment">
                  <Table cols={[
                    { label: 'Outcome', render: (r) => <Badge tone={OUTCOME[r.outcome]?.[1]}>{OUTCOME[r.outcome]?.[0] || r.outcome}</Badge> },
                    { label: 'Sessions', num: true, render: (r) => num(r.sessions) },
                    { label: 'Avg cart', num: true, render: (r) => inr(r.avg_cart_value) },
                    { label: 'Cart value', num: true, render: (r) => inr(r.cart_value) },
                  ]} rows={d.checkout_outcomes} />
                </Card>
              </div>

              <Card title="Abandoned checkouts to follow up" sub="latest 40 with a known phone shown first by recency; phone = last 10 digits">
                <Table cols={[
                  { label: 'When', render: (r) => dt(r.checkout_at) },
                  { label: 'Who', render: (r) => r.name || <span className="muted">anonymous</span> },
                  { label: 'Phone', cls: 'mono', render: (r) => r.phone10 || '–' },
                  { label: 'Cart', num: true, render: (r) => inr(r.cart_value) },
                  { label: 'Stopped at', render: (r) => <Badge tone={OUTCOME[r.outcome]?.[1]}>{OUTCOME[r.outcome]?.[0]}</Badge> },
                  { label: 'Channel', key: 'channel' }, { label: 'City', key: 'city' }, { label: 'Device', key: 'device' },
                ]} rows={d.abandoned} />
              </Card>

              <div className="grid g2">
                <Card title="Most added-to-cart products">
                  <Table cols={[{ label: 'Product', render: (r) => <span className="trunc" title={r.product_name} style={{ display: 'block' }}>{r.product_name}</span> }, { label: 'Brand', key: 'brand' },
                    { label: 'Adds', num: true, render: (r) => num(r.adds) }]} rows={d.top_products} />
                </Card>
                <Card title="Payment method vs outcome">
                  <Table cols={[{ label: 'Method', key: 'method' }, { label: 'Outcome', render: (r) => OUTCOME[r.outcome]?.[0] || r.outcome }, { label: 'Sessions', num: true, render: (r) => num(r.n) }]} rows={d.payment_methods} />
                </Card>
              </div>
            </>
          )
        }}
      </Loading>
    </>
  )
}

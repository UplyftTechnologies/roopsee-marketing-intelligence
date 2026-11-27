import { dt, inr, num, pct, useApi, useFilters, usePersisted } from '../api'
import { Badge, Card, Chips, ExportBtn, Kpi, Loading, Table } from '../ui'

const RAMP = ['var(--seq-250)', 'var(--seq-300)', 'var(--seq-350)', 'var(--seq-400)', 'var(--seq-500)', 'var(--seq-600)']
const OUTCOME = {
  ordered: ['Ordered', 'good'], payment_abandoned: ['Abandoned at payment', 'serious'],
  checkout_abandoned: ['Left at checkout', 'warn'], address_only: ['Only entered address', ''],
}
const CHANNELS = ['All', 'Paid Google', 'Paid Meta', 'MyGate Partner', 'Organic Search', 'Organic Social', 'Direct', 'Referral']

export default function Funnel() {
  const f = useFilters()
  const [channel, setChannel] = usePersisted('funnel.channel', f.prefill?.channel || 'All', !!f.prefill?.channel)
  const s = useApi('/funnel', { channel: channel === 'All' ? undefined : channel })
  return (
    <>
      <div role="group" aria-label="Funnel traffic channel"><Chips options={CHANNELS} value={channel} onChange={setChannel} /></div>
      <Loading state={s}>
        {(d) => {
          const top = d.stages[0].sessions || 1
          const checkout = d.stages[3]
          const ordered = d.stages[5]
          return (
            <>
              <div className="kpis">
                <Kpi label="Sessions" value={num(d.stages[0].sessions)} help="sessions" />
                <Kpi label="Reached checkout" value={num(checkout.sessions)} note={`${pct(checkout.of_first, 1)} of sessions`} />
                <Kpi label="Sessions that ordered" value={num(ordered.sessions)} note={`${pct(ordered.of_first, 2)} of sessions`} />
              </div>
              <Card title="Purchase funnel" sub="share of sessions that reached each step (each step = a session that did the action)">
                {d.stages.map((st, i) => (
                  <div className="fn-row" key={st.stage}>
                    <div>{st.stage}</div>
                    <div><div className="fn-bar" style={{ width: `${Math.max(0.5, (st.sessions / top) * 100)}%`, background: RAMP[i] }} title={`${num(st.sessions)} sessions`} /></div>
                    <div className="fn-meta"><b style={{ color: 'var(--text-primary)' }}>{num(st.sessions)}</b> · {pct(st.of_first, 2)} of all{i ? ` · ${pct(st.of_prev, 0)} of prev` : ''}</div>
                  </div>
                ))}
                <div className="muted" style={{ marginTop: 6 }}>
                  {num(ordered.sessions)} tracked sessions placed an order. The order database recorded <b>{num(d.actual_orders)} valid orders</b> across all channels in this date range.
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
                <Card title="Checkout outcomes" sub="Sessions that reached checkout or payment across all channels in the selected dates.">
                  <Table cols={[
                    { label: 'Outcome', sortBy: 'outcome', render: (r) => <Badge tone={OUTCOME[r.outcome]?.[1]}>{OUTCOME[r.outcome]?.[0] || r.outcome}</Badge> },
                    { label: 'Sessions', sortBy: 'sessions', num: true, render: (r) => num(r.sessions) },
                    { label: 'Avg cart', sortBy: 'avg_cart_value', num: true, render: (r) => inr(r.avg_cart_value) },
                    { label: 'Cart value', sortBy: 'cart_value', num: true, render: (r) => inr(r.cart_value) },
                  ]} rows={d.checkout_outcomes} />
                </Card>
              </div>

              <Card right={<ExportBtn name="abandoned-checkouts" rows={d.abandoned} fields={[['When', 'checkout_at'], ['Name', 'name'], ['Phone', 'phone10'], ['Cart value', 'cart_value'], ['Stopped at', 'outcome'], ['Channel', 'channel'], ['City', 'city']]} />} title="Abandoned checkouts to follow up" sub="latest 40 with a known phone shown first by recency; phone = last 10 digits">
                <Table cols={[
                  { label: 'When', sortBy: 'checkout_at', render: (r) => dt(r.checkout_at) },
                  { label: 'Who', sortBy: 'name', render: (r) => r.name || <span className="muted" title="Never logged in on this browser">Guest</span> },
                  { label: 'Phone', sortBy: 'phone10', cls: 'mono', render: (r) => r.phone10 || '–' },
                  { label: 'Cart', sortBy: 'cart_value', num: true, render: (r) => inr(r.cart_value) },
                  { label: 'Stopped at', sortBy: 'outcome', render: (r) => <Badge tone={OUTCOME[r.outcome]?.[1]}>{OUTCOME[r.outcome]?.[0]}</Badge> },
                  { label: 'Channel', key: 'channel' }, { label: 'City', key: 'city' }, { label: 'Device', key: 'device' },
                ]} rows={d.abandoned} />
              </Card>

              <div className="grid g2">
                <Card title="Most added-to-cart products">
                  <Table cols={[{ label: 'Product', sortBy: 'product_name', render: (r) => <span className="trunc" title={r.product_name} style={{ display: 'block' }}>{r.product_name}</span> }, { label: 'Brand', key: 'brand' },
                    { label: 'Adds', sortBy: 'adds', num: true, render: (r) => num(r.adds) }]} rows={d.top_products} />
                </Card>
                <Card title="Payment method vs outcome">
                  <Table cols={[{ label: 'Method', key: 'method' }, { label: 'Outcome', sortBy: 'outcome', render: (r) => OUTCOME[r.outcome]?.[0] || r.outcome }, { label: 'Sessions', sortBy: 'n', num: true, render: (r) => num(r.n) }]} rows={d.payment_methods} />
                </Card>
              </div>
            </>
          )
        }}
      </Loading>
    </>
  )
}

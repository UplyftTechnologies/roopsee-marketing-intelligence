import { num, pct, useApi } from '../../api'
import { Card, ExportBtn, Kpi, Loading, Table } from '../../ui'
import { Bars, NotBuilt, hours, secs } from './common'

export default function QuizPay() {
  const s = useApi('/deeper/quiz')
  return (
    <Loading state={s}>
      {(d) => {
        if (!d.ready) return <NotBuilt />
        const f = d.funnel
        const b = d.baseline
        const p = d.pay
        const pf = p.funnel
        const quizFunnel = [{ name: 'Started the quiz', count: f.engaged }, ...d.steps.map((x) => ({ name: `step ${x.step}`, label: `Reached step ${x.step}: ${x.question || ''}`, count: x.sessions })),
          { name: 'Finished the quiz', count: f.completed }, { name: 'Added to cart', count: f.completed_carted }, { name: 'Reached checkout', count: f.completed_checkout }, { name: 'Ordered', count: f.completed_ordered }]
        const payFunnel = [{ name: 'Tapped pay', count: pf.tapped }, { name: 'Payment started', count: pf.started }, { name: 'Payment window opened', count: pf.window }, { name: 'Paid online', count: pf.paid }, { name: 'Order confirmed', count: pf.confirmed }]
        return (
          <>
            <h3 style={{ margin: 0 }}>Quiz to purchase</h3>
            <div className="kpis">
              <Kpi label="Started the quiz" value={num(f.engaged)} note="visits that answered at least one question" />
              <Kpi label="Finished" value={pct(f.engaged ? f.completed / f.engaged : 0, 0)} note={`${num(f.completed)} visits · ${num(f.abandoned)} left part-way`} />
              <Kpi label="Finishers who ordered" value={pct(f.completed ? f.completed_ordered / f.completed : 0, 1)} note={`${num(f.completed_ordered)} visits · others who took the quiz: ${pct(f.engaged - f.completed ? f.other_ordered / (f.engaged - f.completed) : 0, 1)}`} />
              <Kpi label="Finishers who added to cart" value={pct(f.completed ? f.completed_carted / f.completed : 0, 0)} note={`visits with no quiz: ${pct(b.sessions ? b.carted / b.sessions : 0, 1)}`} />
            </div>
            <div className="grid g2">
              <Card title="Where the quiz loses people" sub="visits at each step, then what finishers did next"><Bars items={quizFunnel} total={f.engaged} empty="Nobody took the quiz in these dates." /></Card>
              <Card title="Left part-way" sub="the step people were on when they left">
                <Bars items={d.drops.map((x) => ({ name: `step ${x.step}`, label: `Left on step ${x.step}`, count: x.sessions }))} empty="Nobody left part-way (or the step was not recorded)." />
                <div style={{ marginTop: 12 }}><b>From finishing the quiz to the first order</b>
                  {d.quiz_to_order.people ? <><div className="muted" style={{ fontSize: 12 }}>{num(d.quiz_to_order.people)} people ordered after finishing it. Typical wait: {hours(d.quiz_to_order.median_hours)}.</div><Bars items={d.quiz_to_order.buckets} total={d.quiz_to_order.people} /></>
                    : <div className="muted">Nobody who finished the quiz in these dates has ordered yet.</div>}</div>
              </Card>
            </div>
            <div className="grid g3">
              <Card title="Quiz result they got" sub="the program picked, and what those visits did"
                right={<ExportBtn name="quiz-programs" rows={d.programs} fields={[['Program', 'name'], ['Visits', 'sessions'], ['Added to cart', 'carted'], ['Ordered', 'ordered']]} />}>
                <Table rows={d.programs} empty="No finished quizzes." cols={[{ label: 'Program', key: 'name' }, { label: 'Visits', num: true, sortBy: 'sessions', render: (r) => num(r.sessions) }, { label: 'Cart', num: true, render: (r) => pct(r.sessions ? r.carted / r.sessions : 0, 0) }, { label: 'Ordered', num: true, sortBy: 'ordered', render: (r) => num(r.ordered) }]} />
              </Card>
              <Card title="Concern they named" sub="from the quiz answers">
                <Table rows={d.concerns} empty="No concerns recorded." cols={[{ label: 'Concern', key: 'name' }, { label: 'Visits', num: true, sortBy: 'sessions', render: (r) => num(r.sessions) }, { label: 'Cart', num: true, render: (r) => pct(r.sessions ? r.carted / r.sessions : 0, 0) }, { label: 'Ordered', num: true, sortBy: 'ordered', render: (r) => num(r.ordered) }]} />
              </Card>
              <Card title="Skin type">
                <Table rows={d.skin_types} empty="No skin types recorded." cols={[{ label: 'Skin type', key: 'name' }, { label: 'Visits', num: true, sortBy: 'sessions', render: (r) => num(r.sessions) }, { label: 'Ordered', num: true, sortBy: 'ordered', render: (r) => num(r.ordered) }]} />
              </Card>
            </div>

            <h3 style={{ margin: '8px 0 0' }}>Order to confirmation</h3>
            <div className="kpis">
              <Kpi label="Tapped pay" value={num(pf.tapped)} note={`${num(pf.dropped)} never got an order confirmed`} />
              <Kpi label="Typical time to confirm" value={secs(p.median_seconds)} note="from tapping pay to the confirmed order" />
              <Kpi label="Time in the payment window" value={secs(p.popup_median_s)} note="online payments" />
              <Kpi label="Orders confirmed" value={pct(p.orders.orders ? p.orders.confirmed / p.orders.orders : 0, 0)} note={`${num(p.orders.confirmed)} of ${num(p.orders.orders)} sales have a confirmed payment`} />
            </div>
            <div className="grid g2">
              <Card title="From the pay tap to a confirmed order" sub="visits at each step"><Bars items={payFunnel} total={pf.tapped} empty="Nobody tapped pay in these dates." /></Card>
              <Card title="How long it takes" sub="tap on pay to confirmed order">
                <Bars items={p.buckets} empty="No confirmed orders with a pay tap in these dates." />
                {p.by_method.length > 0 && <div style={{ marginTop: 10 }}><Table rows={p.by_method} cols={[{ label: 'Method', key: 'name' }, { label: 'Orders', num: true, sortBy: 'orders', render: (r) => num(r.orders) }, { label: 'Typical time', num: true, render: (r) => secs(r.median_seconds) }]} /></div>}
                {p.orders.median_paid_s != null && <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>From the orders table: online payments are confirmed {secs(p.orders.median_paid_s)} after the order is created (9 in 10 within {secs(p.orders.p90_paid_s)}); {num(p.orders.online_paid)} orders have a payment time.</div>}
              </Card>
            </div>
          </>
        )
      }}
    </Loading>
  )
}

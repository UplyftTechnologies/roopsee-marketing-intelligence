import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { day, num, pct, useApi } from '../api'
import { Card, ExportBtn, Kpi, Loading, Table, axis, chartTip } from '../ui'
import { Bars, NotBuilt, hours, secs } from './deeper/common'

/** Journeys › More detail: the facts under a journey that are not funnel steps (moved from the old Deeper analysis tab). Backend: mi/journey_detail.py */

export const HAS_DETAIL = ['purchase', 'search', 'quiz', 'checkout']
const KIND = { filter: 'Filter', sort: 'Sort', apply_filters: 'Applied filters' }

function Purchase({ b }) {
  return (
    <Card title="What led up to the first order" sub="every customer's first valid order in these dates, and the visits before it">
      {b.orders === 0 ? <div className="muted">No first orders in these dates.</div> : (
        <>
          <div className="kpis">
            <Kpi label="First orders" value={num(b.orders)} />
            <Kpi label="Typical visits before it" value={b.median_visits ?? '–'} note="including the visit that ordered" />
            <Kpi label="Typical time to order" value={b.median_days == null ? '–' : b.median_days < 1 ? 'same day' : `${b.median_days} days`} note="first visit to order" />
            <Kpi label="Used 2+ channels" value={num(b.multi_channel)} note={`${pct(b.orders ? b.multi_channel / b.orders : 0, 0)} of first orders`} />
          </div>
          <div className="grid g3" style={{ marginTop: 12 }}>
            <div><b>Visits before ordering</b><Bars items={b.visits} total={b.orders} /></div>
            <div><b>Time from first visit</b><Bars items={b.days} total={b.orders} /></div>
            <div><b>First landing page</b><Bars items={b.first_landing} total={b.orders} /></div>
          </div>
          <div style={{ marginTop: 12 }}>
            <b>First channel that brought them</b>
            <Table rows={b.first_channel} cols={[{ label: 'Channel', key: 'name' }, { label: 'First orders', num: true, sortBy: 'orders', render: (r) => num(r.orders) }, { label: 'Typical visits', num: true, render: (r) => r.median_visits ?? '–' }]} />
          </div>
        </>
      )}
    </Card>
  )
}

function Search({ d }) {
  const k = d.kpis
  const zeroShare = k.searches + k.no_result_events ? (k.zero_searches + k.no_result_events) / (k.searches + k.no_result_events) : 0
  return (
    <>
      <div className="kpis">
        <Kpi label="Searches" value={num(k.searches)} note="every search run (the funnel above counts visits)" />
        <Kpi label="Searches with no result" value={num(k.zero_searches + k.no_result_events)} note={`${pct(zeroShare, 0)} of searches`} />
        <Kpi label="Tapped a search result" value={num(k.click_sessions)} note="visits that tapped a product in the results (the event itself; the funnel step also counts visits that went further)" />
        <Kpi label="Used filters or sorting" value={num(k.filter_sessions)} note={`${num(k.abandon_sessions)} visits left a search half-way`} />
      </div>
      <div className="banner" role="note">
        <span>Visits that searched add to cart <b>{pct(k.searcher_cart_rate, 1)}</b> of the time and order <b>{pct(k.searcher_order_rate, 1)}</b>; visits that looked at products without searching: <b>{pct(k.other_cart_rate, 1)}</b> and <b>{pct(k.other_order_rate, 1)}</b>.</span>
      </div>
      <Card title="What people searched for" sub="the most searched words, what came back, and whether those visits went on to order"
        right={<ExportBtn name="search-terms" rows={d.terms} fields={[['Term', 'term'], ['Searches', 'searches'], ['Visits', 'sessions'], ['Average results', 'avg_results'], ['No-result events', 'no_result_events'], ['Result taps', 'clicks'], ['Visits that ordered', 'ordered_sessions']]} />}>
        <Table scroll rows={d.terms} empty="No searches in these dates." cols={[
          { label: 'Search', key: 'term', cls: 'mono' },
          { label: 'Searches', num: true, sortBy: 'searches', render: (r) => num(r.searches) },
          { label: 'Visits', num: true, sortBy: 'sessions', render: (r) => num(r.sessions) },
          { label: 'Results', num: true, sortBy: 'avg_results', render: (r) => r.avg_results ?? '–' },
          { label: 'No result', num: true, sortBy: 'zero_share', render: (r) => (r.zero_share ? <span style={{ color: r.zero_share >= 0.5 ? 'var(--critical)' : undefined }}>{pct(r.zero_share, 0)}</span> : '–') },
          { label: 'Result taps', num: true, sortBy: 'clicks', render: (r) => num(r.clicks) },
          { label: 'Ordered', num: true, sortBy: 'ordered_sessions', render: (r) => num(r.ordered_sessions) },
        ]} />
      </Card>
      <div className="grid g2">
        <Card title="Searches each day">
          <div style={{ height: 200 }}>
            <ResponsiveContainer>
              <BarChart data={d.daily} margin={{ left: 0, right: 12, top: 8, bottom: 0 }}>
                <CartesianGrid stroke="var(--grid)" vertical={false} />
                <XAxis dataKey="day" tickFormatter={day} {...axis} minTickGap={32} />
                <YAxis {...axis} width={40} allowDecimals={false} />
                <Tooltip {...chartTip} labelFormatter={day} />
                <Legend />
                <Bar dataKey="searches" name="Searches" stackId="a" fill="var(--series-1)" />
                <Bar dataKey="no_results" name="No result" stackId="a" fill="var(--series-3)" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <div style={{ display: 'grid', gap: 14, alignContent: 'start' }}>
          <Card title="Where they searched" sub="and how often it found nothing">
            <Table rows={d.by_source} empty="Nothing here." cols={[{ label: 'From', key: 'source' }, { label: 'Searches', num: true, sortBy: 'searches', render: (r) => num(r.searches) },
              { label: 'No result', num: true, render: (r) => num(r.zero + r.no_result_events) }]} />
          </Card>
          <Card title="Filters and sorting" sub="what people use to narrow the shop"
            right={<ExportBtn name="filters" rows={d.filters} fields={[['Kind', 'kind'], ['Value', 'value'], ['Uses', 'uses'], ['Visits', 'sessions']]} />}>
            <Table scroll rows={d.filters} empty="No filters were used." cols={[{ label: 'Kind', render: (r) => KIND[r.kind] || r.kind }, { label: 'Value', key: 'value', cls: 'mono' },
              { label: 'Uses', num: true, sortBy: 'uses', render: (r) => num(r.uses) }, { label: 'Visits', num: true, sortBy: 'sessions', render: (r) => num(r.sessions) }]} />
          </Card>
        </div>
      </div>
    </>
  )
}

function Quiz({ d }) {
  const first = d.steps[0]?.sessions
  return (
    <>
      <div className="grid g2">
        <Card title="Where the quiz loses people" sub="visits that reached each question">
          <Bars items={d.steps.map((x) => ({ name: `step ${x.step}`, label: `Step ${x.step}: ${x.question || ''}`, count: x.sessions }))} total={first} empty="Nobody answered the quiz in these dates." />
        </Card>
        <Card title="Left part-way" sub="the question people were on when they left">
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
    </>
  )
}

function Checkout({ p }) {
  return (
    <>
      <div className="kpis">
        <Kpi label="Typical time to confirm" value={secs(p.median_seconds)} note={`from tapping pay to the confirmed order · ${num(p.timed)} orders timed`} />
        <Kpi label="Time in the payment window" value={secs(p.popup_median_s)} note="online payments" />
        <Kpi label="Sales with a confirmed payment" value={pct(p.orders.orders ? p.orders.confirmed / p.orders.orders : 0, 0)} note={`${num(p.orders.confirmed)} of ${num(p.orders.orders)} sales`} />
      </div>
      <Card title="How long it takes" sub="tap on pay to confirmed order (the pay steps themselves are in the funnel above)">
        <div className="grid g2">
          <Bars items={p.buckets} empty="No confirmed orders with a pay tap in these dates." />
          {p.by_method.length > 0 && <Table rows={p.by_method} cols={[{ label: 'Method', key: 'name' }, { label: 'Orders', num: true, sortBy: 'orders', render: (r) => num(r.orders) }, { label: 'Typical time', num: true, render: (r) => secs(r.median_seconds) }]} />}
        </div>
        {p.orders.median_paid_s != null && <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>From the orders table: online payments are confirmed {secs(p.orders.median_paid_s)} after the order is created (9 in 10 within {secs(p.orders.p90_paid_s)}); {num(p.orders.online_paid)} orders have a payment time.</div>}
      </Card>
    </>
  )
}

export default function JourneyDetail({ journey }) {
  const s = useApi('/journeys/detail', { journey })
  return (
    <section>
      <div className="section-head"><h2>More detail</h2></div>
      <Loading state={s}>
        {(d) => {
          if (!d.ready) return <NotBuilt />
          if (journey === 'purchase') return <Purchase b={d.purchase} />
          if (journey === 'search') return <Search d={d.search} />
          if (journey === 'quiz') return <Quiz d={d.quiz} />
          return <Checkout p={d.checkout} />
        }}
      </Loading>
    </section>
  )
}

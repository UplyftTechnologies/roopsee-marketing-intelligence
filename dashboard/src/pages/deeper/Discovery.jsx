import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { day, dt, num, pct, useApi } from '../../api'
import { Card, ExportBtn, Kpi, Loading, Table, axis, chartTip } from '../../ui'
import { Bars, NotBuilt } from './common'

const KIND = { filter: 'Filter', sort: 'Sort', apply_filters: 'Applied filters' }

export default function Discovery() {
  const s = useApi('/deeper/discovery')
  return (
    <Loading state={s}>
      {(d) => {
        if (!d.ready) return <NotBuilt />
        const k = d.kpis
        const zeroShare = k.searches + k.no_result_events ? (k.zero_searches + k.no_result_events) / (k.searches + k.no_result_events) : 0
        return (
          <>
            <div className="kpis">
              <Kpi label="Searches" value={num(k.searches)} note={`by ${num(k.searching_sessions)} visits (${pct(k.sessions ? k.searching_sessions / k.sessions : 0, 1)})`} />
              <Kpi label="Searches with no result" value={num(k.zero_searches + k.no_result_events)} note={`${pct(zeroShare, 0)} of searches`} />
              <Kpi label="Clicked a result" value={num(k.click_sessions)} note={`${pct(k.searching_sessions ? k.click_sessions / k.searching_sessions : 0, 0)} of visits that searched`} />
              <Kpi label="Searched, then left" value={num(k.abandon_sessions)} note="the search was abandoned" />
            </div>
            <div className="banner" role="note">
              <span>Visits that searched add to cart <b>{pct(k.searcher_cart_rate, 1)}</b> of the time and order <b>{pct(k.searcher_order_rate, 1)}</b>; visits that looked at products without searching: <b>{pct(k.other_cart_rate, 1)}</b> and <b>{pct(k.other_order_rate, 1)}</b>.</span>
            </div>

            <div className="grid g2">
              <Card title="After a search" sub="visits that searched, and how far they got"><Bars items={d.funnel} total={d.funnel[0]?.count} empty="No searches in these dates." /></Card>
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
            </div>

            <Card title="What people searched for" sub="the most searched words, what came back, and whether those visits went on to order"
              right={<ExportBtn name="search-terms" rows={d.terms} fields={[['Term', 'term'], ['Searches', 'searches'], ['Visits', 'sessions'], ['Average results', 'avg_results'], ['No-result events', 'no_result_events'], ['Result clicks', 'clicks'], ['Visits that ordered', 'ordered_sessions']]} />}>
              <Table scroll rows={d.terms} empty="No searches in these dates." cols={[
                { label: 'Search', key: 'term', cls: 'mono' },
                { label: 'Searches', num: true, sortBy: 'searches', render: (r) => num(r.searches) },
                { label: 'Visits', num: true, sortBy: 'sessions', render: (r) => num(r.sessions) },
                { label: 'Results', num: true, sortBy: 'avg_results', render: (r) => r.avg_results ?? '–' },
                { label: 'No result', num: true, sortBy: 'zero_share', render: (r) => (r.zero_share ? <span style={{ color: r.zero_share >= 0.5 ? 'var(--critical)' : undefined }}>{pct(r.zero_share, 0)}</span> : '–') },
                { label: 'Clicked', num: true, sortBy: 'clicks', render: (r) => num(r.clicks) },
                { label: 'Ordered', num: true, sortBy: 'ordered_sessions', render: (r) => num(r.ordered_sessions) },
              ]} />
            </Card>

            <div className="grid g2">
              <Card title="Searched for, not found" sub="words that returned nothing: products people want that the shop does not show"
                right={<ExportBtn name="search-no-results" rows={d.missing} fields={[['Search', 'term'], ['Times', 'events'], ['Visits', 'sessions'], ['Last seen', 'last_seen']]} />}>
                <Table scroll rows={d.missing} empty="Every search found something." cols={[
                  { label: 'Search', key: 'term', cls: 'mono' }, { label: 'Times', num: true, sortBy: 'events', render: (r) => num(r.events) }, { label: 'Visits', num: true, sortBy: 'sessions', render: (r) => num(r.sessions) },
                  { label: 'Last', cls: 'nw', sortBy: 'last_seen', render: (r) => dt(r.last_seen) }]} />
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
      }}
    </Loading>
  )
}

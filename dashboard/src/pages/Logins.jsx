import { useEffect, useState } from 'react'
import { dt, num, pct, useApi, useFilters, usePersisted } from '../api'
import { Badge, Card, Chips, ExportBtn, Kpi, Loading, Pager, Search, Table, delta, nextSort } from '../ui'
import MetricChart from '../components/LazyMetricChart'

const TEXT_SORTS = ['name', 'method', 'city', 'channel', 'device']
const hourLabel = (h) => `${h % 12 || 12}${h < 12 ? 'am' : 'pm'}`

/** Columns shared by the Home list and the Logins page. */
export const loginCols = (full) => [
  { label: 'Time', cls: 'nw', sortBy: 'at', render: (r) => dt(r.at) },
  { label: 'Who', cls: 'nw', sortBy: 'name', render: (r) => r.name || (r.phone10 ? <span className="mono">{r.phone10}</span> : <span className="muted">anonymous</span>) },
  ...(full ? [{ label: 'Phone', cls: 'mono nw', render: (r) => r.phone10 || <span className="muted">–</span> }, { label: 'Email', cls: 'nw', render: (r) => (r.email ? <span className="trunc" style={{ display: 'block', maxWidth: 180 }} title={r.email}>{r.email}</span> : <span className="muted">–</span>) }] : []),
  { label: 'How', cls: 'nw', sortBy: 'method', render: (r) => r.method },
  { label: 'Account', cls: 'nw', render: (r) => (r.is_new ? <Badge tone="good">New account</Badge> : <span className="muted">Returning</span>) },
  { label: 'City', cls: 'nw', sortBy: 'city', render: (r) => r.city || r.region || '–' },
  { label: 'Device', cls: 'nw', sortBy: 'device', render: (r) => (r.is_app ? 'Android app' : r.device || '–') },
  { label: 'Channel', cls: 'nw', sortBy: 'channel', render: (r) => <span title={r.campaign}>{r.channel}</span> },
  ...(full ? [{ label: 'Ordered', cls: 'nw', render: (r) => (r.ordered ? <Badge tone="good">same visit</Badge> : <span className="muted">–</span>) }] : []),
]

const csvFields = [['Time', 'at'], ['Name', 'name'], ['Phone', 'phone10'], ['Email', 'email'], ['How', 'method'], ['New account', (r) => (r.is_new ? 'yes' : 'no')], ['City', 'city'], ['Device', (r) => (r.is_app ? 'Android app' : r.device)],
  ['Channel', 'channel'], ['Campaign', 'campaign'], ['Ordered in the visit', (r) => (r.ordered ? 'yes' : 'no')], ['Session id', 'session_id']]

export default function Logins() {
  const f = useFilters()
  const [method, setMethod] = usePersisted('logins.method', '')
  const [kind, setKind] = usePersisted('logins.kind', '')
  const [search, setSearch] = usePersisted('logins.search', '')
  const [sort, setSort] = usePersisted('logins.sort', { key: 'at', dir: 'desc' })
  const [limit, setLimit] = usePersisted('logins.limit', 50)
  const [offset, setOffset] = useState(0)
  useEffect(() => { setOffset(0) }, [method, kind, search, sort, limit])
  const s = useApi('/logins', { method: method || undefined, kind: kind || undefined, search: search || undefined, sort: sort.key, direction: sort.dir, limit, offset, compare: f.compare || undefined })
  return (
    <>
      <div className="chip-row">
        <Search value={search} onChange={setSearch} placeholder="Search name, phone, email, city or session id…" />
        <Chips value={method} onChange={setMethod} options={[{ value: '', label: 'Any method' }, { value: 'Phone OTP', label: 'Phone OTP' }, { value: 'Google', label: 'Google' }]} />
        <Chips value={kind} onChange={setKind} options={[{ value: '', label: 'New & returning' }, { value: 'new', label: 'New accounts' }, { value: 'returning', label: 'Returning' }]} />
      </div>
      <Loading state={s}>
        {(d) => {
          if (!d.ready) return <div className="banner err">The login table is not built yet. Press <b>Refresh</b> (top right) to build it.</div>
          const t = d.totals
          const p = d.prev
          const ts = { dates: d.dates, current: d.current, prev_dates: d.prev_dates, previous: d.previous }
          const maxH = Math.max(1, ...d.by_hour.map((h) => h.logins))
          const maxM = Math.max(1, ...d.by_method.map((m) => m.logins))
          const maxC = Math.max(1, ...d.by_channel.map((m) => m.logins))
          return (
            <>
              <div className="kpis">
                <Kpi label="Logins" value={num(t.logins)} d={p ? delta(t.logins, p.logins) : null} note="one per visit with a login" />
                <Kpi label="People who logged in" value={num(t.login_people)} d={p ? delta(t.login_people, p.login_people) : null} />
                <Kpi label="New accounts" value={num(t.login_new)} d={p ? delta(t.login_new, p.login_new) : null} note={`${pct(t.logins ? t.login_new / t.logins : 0, 0)} of logins`} />
                <Kpi label="Ordered in the same visit" value={num(d.after?.ordered_same_visit ?? 0)} note={`${pct(t.logins ? (d.after?.ordered_same_visit ?? 0) / t.logins : 0, 0)} of logins`} />
              </div>
              <Card title="Logins per day" sub="one login per visit: the several events of a login count once">
                <MetricChart ts={ts} metric="logins" compare={f.compare && Boolean(p)} height={230} ranges={{ cur: f.rangeText, prev: f.prevText }} />
              </Card>
              <div className="grid g3">
                <Card title="How they logged in">
                  <div className="mini-list">{d.by_method.map((m) => (
                    <div key={m.name} className="mini-row"><span className="name">{m.name}</span><span className="val">{num(m.logins)} · {num(m.new_accounts)} new</span><span className="mini-bar"><i style={{ width: `${(m.logins / maxM) * 100}%` }} /></span></div>))}</div>
                </Card>
                <Card title="Where they came from" sub="channel of the visit">
                  <div className="mini-list">{d.by_channel.map((m) => (
                    <div key={m.name} className="mini-row"><span className="name">{m.name}</span><span className="val">{num(m.logins)}</span><span className="mini-bar"><i style={{ width: `${(m.logins / maxC) * 100}%` }} /></span></div>))}</div>
                </Card>
                <Card title="Busiest hours" sub="India time">
                  <div className="mini-list">{[...d.by_hour].sort((a, b) => b.logins - a.logins).slice(0, 6).map((h) => (
                    <div key={h.hour} className="mini-row"><span className="name">{hourLabel(h.hour)} – {hourLabel((h.hour + 1) % 24)}</span><span className="val">{num(h.logins)}</span><span className="mini-bar"><i style={{ width: `${(h.logins / maxH) * 100}%` }} /></span></div>))}</div>
                </Card>
              </div>
              <Card title={`${num(d.total)} logins`} sub="click a row for the person · click a column title to sort"
                right={<ExportBtn name="logins" rows={d.rows} fields={csvFields} />}>
                <Table scroll sort={sort} onSort={(k) => setSort(nextSort(sort, k, TEXT_SORTS))} onRow={(r) => f.go('person', { key: r.person_key })} rows={d.rows}
                  empty="No logins in this range. Try a wider date range or clear a filter." cols={loginCols(true)} />
                <Pager total={d.total} limit={limit} offset={offset} setOffset={setOffset} setLimit={setLimit} />
              </Card>
            </>
          )
        }}
      </Loading>
    </>
  )
}

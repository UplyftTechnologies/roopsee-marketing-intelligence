import { useRef, useState } from 'react'
import { dt, num, pct, useApi, useFilters, usePersisted } from '../api'
import { Badge, Card, Chips, ExportBtn, Kpi, Loading, Search, Table } from '../ui'
import PageSpeed from '../components/PageSpeed'

const sec = (ms) => (ms == null ? '–' : `${(ms / 1000).toFixed(1)}s`)
const SHORT = { slow_page_load: 'Slow page', slow_api: 'Slow request', api_failed: 'Request failed', app_error: 'Page error' }
const TONE = { slow_page_load: 'warn', slow_api: 'warn', api_failed: 'bad', app_error: 'bad' }
const pretty = (p) => { try { return decodeURIComponent(p || '') } catch { return p || '' } }

/** Page speed: the load-time summary, then every visit that ran into a slow or broken moment. */
export default function SpeedPage() {
  const f = useFilters()
  const [problem, setProblem] = usePersisted('speed.problem', '')
  const [orderedOnly, setOrderedOnly] = useState(false)
  const [search, setSearch] = useState('')
  const details = useRef(null)
  const s = useApi('/speed/sessions', { problem: problem || undefined })
  const showDetails = (nextProblem = '', nextOrderedOnly = false) => {
    setProblem(nextProblem)
    setOrderedOnly(nextOrderedOnly)
    setSearch('')
    requestAnimationFrame(() => details.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  }
  return (
    <>
      <PageSpeed linked={false} />
      <Loading state={s}>
        {(d) => {
          if (!d.ready) return <div className="banner">Press Refresh once to build the tables this needs.</div>
          const m = d.summary
          const q = search.trim().toLowerCase()
          const rows = d.rows.filter((r) => (!orderedOnly || r.ordered) && (!q || [r.name, r.phone10, r.city, r.device, r.channel, r.session_id, ...(r.pages || []), ...(r.details || [])].some((v) => String(v || '').toLowerCase().includes(q))))
          return (
            <>
              <div className="kpis">
                <Kpi label="Visits with a problem" value={num(m.affected)} note={`${pct(m.visits ? m.affected / m.visits : 0, 1)} of ${num(m.visits)} visits`} onClick={() => showDetails()} hint="Show all visits with a problem" />
                {Object.keys(d.labels).map((k) => <Kpi key={k} label={d.labels[k]} value={num(m[k])} note="visits" onClick={() => showDetails(k)} hint={`Show visits with ${SHORT[k].toLowerCase()}`} />)}
                <Kpi label="Ordered, with a problem" value={pct(m.order_rate_hit, 2)} note={`${pct(m.order_rate_clean, 2)} for visits without one`} onClick={() => showDetails('', true)} hint="Show affected visits that ordered" />
              </div>
              <div ref={details} />
              <Card title="Visits that had a problem" sub="newest first · click a visit to open its full timeline"
                right={<><Chips value={problem} onChange={(next) => { setProblem(next); setOrderedOnly(false) }} options={[{ value: '', label: 'All' }, ...Object.keys(d.labels).map((k) => ({ value: k, label: SHORT[k] }))]} />
                  <ExportBtn name="speed-problem-visits" rows={rows} fields={[['Started', 'started_at'], ['Session id', 'session_id'], ['Name', 'name'], ['Phone', 'phone10'], ['City', 'city'], ['Device', 'device'], ['Channel', 'channel'],
                    ['Problems', (r) => r.problems.map((k) => SHORT[k]).join(' | ')], ['Pages', (r) => (r.pages || []).map(pretty).join(' | ')], ['Slow pages', 'slow_pages'], ['Worst load (ms)', 'worst_load_ms'], ['Slow requests', 'slow_requests'],
                    ['Worst request (ms)', 'worst_request_ms'], ['Failed requests', 'failed_requests'], ['Page errors', 'errors'], ['Details', (r) => (r.details || []).join(' | ')], ['Ordered', (r) => (r.ordered ? 'yes' : 'no')]]} /></>}>
                <div className="chip-row" style={{ marginBottom: 8 }}>
                  <Search value={search} onChange={setSearch} placeholder="Filter: name, phone, city, page, error, session id…" />
                  <span className="muted" style={{ fontSize: 12 }}>{num(rows.length)} visits shown{d.total > d.rows.length ? ` (the latest ${num(d.rows.length)} of ${num(d.total)}: pick fewer days to see the rest)` : ''}</span>
                </div>
                <Table id="speed-sessions" scroll rows={rows} onRow={(r) => f.go('session', { key: r.session_id })} empty="No visit had a problem in these dates." cols={[
                  { label: 'Started', cls: 'nw', sortBy: 'started_at', render: (r) => dt(r.started_at) },
                  { label: 'Who', cls: 'nw', sortBy: 'name', render: (r) => r.name || (r.phone10 ? <span className="mono">{r.phone10}</span> : <span className="muted">anonymous</span>) },
                  { label: 'Problems', render: (r) => <span className="chip-row" style={{ gap: 4 }}>{r.problems.map((k) => <Badge key={k} tone={TONE[k]}>{SHORT[k]}</Badge>)}</span> },
                  { label: 'Pages affected', render: (r) => (r.pages?.length ? <div style={{ maxWidth: 260 }}>{r.pages.slice(0, 2).map((p) => <div key={p} className="mono trunc" title={pretty(p)}>{pretty(p)}</div>)}{r.pages_hit > 2 && <span className="muted">+{num(r.pages_hit - 2)} more</span>}</div> : '–') },
                  { label: 'Worst load', num: true, sortBy: 'worst_load_ms', render: (r) => (r.worst_load_ms == null ? '–' : <Badge tone={r.worst_load_ms > 4000 ? 'bad' : 'warn'}>{sec(r.worst_load_ms)}</Badge>) },
                  { label: 'Slow pages', num: true, sortBy: 'slow_pages', render: (r) => r.slow_pages || '–' },
                  { label: 'Slow requests', num: true, sortBy: 'slow_requests', render: (r) => (r.slow_requests ? `${num(r.slow_requests)}${r.worst_request_ms ? ` · worst ${sec(r.worst_request_ms)}` : ''}` : '–') },
                  { label: 'Failed requests', num: true, sortBy: 'failed_requests', render: (r) => r.failed_requests || '–' },
                  { label: 'Page errors', num: true, sortBy: 'errors', render: (r) => r.errors || '–' },
                  { label: 'Details', hidden: true, render: (r) => <span className="trunc" style={{ display: 'block', maxWidth: 260 }} title={(r.details || []).join(' | ')}>{(r.details || []).join(' | ') || '–'}</span> },
                  { label: 'City · device', cls: 'nw', sortBy: 'city', render: (r) => `${r.city || '–'} · ${r.device || '–'}` },
                  { label: 'Channel', hidden: true, cls: 'nw', sortBy: 'channel', render: (r) => r.channel },
                  { label: 'Ordered', cls: 'nw', sortBy: (r) => (r.ordered ? 1 : 0), render: (r) => (r.ordered ? <Badge tone="good">ordered</Badge> : <span className="muted">no</span>) },
                ]} />
              </Card>
            </>
          )
        }}
      </Loading>
    </>
  )
}

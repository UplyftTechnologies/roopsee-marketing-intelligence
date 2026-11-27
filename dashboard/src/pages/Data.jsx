import { useState } from 'react'
import { KEY_LABEL, api, dt, num, useApi, useFilters } from '../api'
import { Badge, Card, Kpi, Loading, Search, Table } from '../ui'

export default function DataPage() {
  const f = useFilters()
  const meta = { data: f.meta }
  const cat = useApi('/events/catalogue', {})
  const [filter, setFilter] = useState('')
  const [starting, setStarting] = useState('')
  const [requestError, setRequestError] = useState('')
  const m = meta.data
  const run = async (mode) => {
    setStarting(mode)
    setRequestError('')
    try { await api('/refresh', { method: 'POST', params: { mode } }); await f.reloadMeta() }
    catch (error) { setRequestError(error.message) }
    finally { setStarting('') }
  }
  return (
    <>
      <Loading state={meta}>
        {() => (
          <>
            <div className="kpis">
              <Kpi label="Raw events stored" value={num(m.raw_events?.n)} note={`${dt(m.raw_events?.first)} → ${dt(m.raw_events?.last)}`} />
              <Kpi label="Events kept / excluded" value={`${num(m.counts?.events - m.counts?.events_excluded)} / ${num(m.counts?.events_excluded)}`} />
              <Kpi label="Sessions kept / excluded" value={`${num(m.counts?.sessions - m.counts?.sessions_excluded)} / ${num(m.counts?.sessions_excluded)}`} />
              <Kpi label="People (kept)" value={num(m.counts?.people - m.counts?.people_excluded)} />
              <Kpi label="Valid orders (kept)" value={num(m.counts?.orders - m.counts?.orders_excluded)} note={`${num(m.counts?.orders_excluded)} excluded`} />
            </div>
            <Card title="Dashboard refresh" sub="Pull new activity and catalog data, or rebuild reports from the data already on this computer.">
              <div className="chip-row">
                <button type="button" className="btn primary" disabled={m.job.running || !!starting} onClick={() => run('full')}>{starting === 'full' ? 'Starting…' : 'Refresh dashboard'}</button>
                <button type="button" className="btn" disabled={m.job.running || !!starting} onClick={() => run('transform')}>{starting === 'transform' ? 'Starting…' : 'Rebuild reports only'}</button>
                {m.job.running && <span role="status"><Badge tone="warn">{m.job.message}</Badge></span>}
              </div>
              {(requestError || m.job.error) && <div className="banner err" role="alert">Refresh failed. {requestError || m.job.error}</div>}
              <div className="pipeline-times">
                <span><b>Last successful rebuild</b> {m.last_transform ? dt(m.last_transform) : '–'}</span>
                <span><b>Latest site event</b> {m.raw_events?.last ? dt(m.raw_events.last) : '–'}</span>
                {m.job.finished && <span><b>Last refresh attempt finished</b> {dt(m.job.finished)}</span>}
              </div>
              <details>
                <summary>How refresh works</summary>
                <p className="muted">The dashboard pulls events incrementally from Supabase with a one-hour overlap, stores them in DuckDB, and rebuilds the report tables. A rebuild typically takes 15–20 seconds.</p>
              </details>
            </Card>
          </>
        )}
      </Loading>
      <Loading state={cat}>
        {(rows) => (
          <Card title="Event catalogue" sub="every event name in the data and how it maps to a key funnel event – use this to spot tracking drift or events worth mapping"
            right={<Search placeholder="Search event names" value={filter} onChange={setFilter} />}>
            <Table cols={[
              { label: 'Event name', cls: 'mono', key: 'event_name' },
              { label: 'Mapped to', sortBy: 'event_key', render: (r) => (r.event_key.startsWith('(') ? <span className="muted">{r.event_key}</span> : <Badge tone="good">{KEY_LABEL[r.event_key] || r.event_key}</Badge>) },
              { label: 'Events', sortBy: 'events', num: true, render: (r) => num(r.events) }, { label: 'Sessions', sortBy: 'sessions', num: true, render: (r) => num(r.sessions) },
              { label: 'First seen', sortBy: 'first_seen', render: (r) => dt(r.first_seen) }, { label: 'Last seen', sortBy: 'last_seen', render: (r) => dt(r.last_seen) },
            ]} rows={rows.filter((r) => r.event_name.includes(filter.toLowerCase()))} />
          </Card>
        )}
      </Loading>
    </>
  )
}

import { useState } from 'react'
import { KEY_LABEL, api, dt, num, useApi, useFilters } from '../api'
import { Badge, Card, Kpi, Loading, Table } from '../ui'

export default function DataPage() {
  const f = useFilters()
  const meta = { data: f.meta }
  const cat = useApi('/events/catalogue', {})
  const [filter, setFilter] = useState('')
  const m = meta.data
  const run = async (mode) => { await api('/refresh', { method: 'POST', params: { mode } }); f.reloadMeta() }
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
            <Card title="Pipeline" sub="Supabase (read-only REST) → DuckDB raw tables → SQL transforms → this dashboard">
              <div className="chip-row">
                <button className="btn primary" disabled={m.job.running} onClick={() => run('full')}>Pull new events + rebuild</button>
                <button className="btn" disabled={m.job.running} onClick={() => run('transform')}>Rebuild only (no download)</button>
                {m.job.running && <Badge tone="warn">{m.job.name}: {m.job.message}</Badge>}
                {m.job.error && <Badge tone="bad">{m.job.error}</Badge>}
                <span className="muted">Last rebuild: {m.last_transform || '–'} · finished job: {m.job.finished ? dt(m.job.finished) : '–'}</span>
              </div>
              <div className="muted" style={{ marginTop: 10 }}>
                Pulls are incremental (only events newer than the last stored one, minus a 1-hour overlap) and use GET requests only – production is never written to.
                A full rebuild takes roughly 15–20 seconds.
              </div>
            </Card>
          </>
        )}
      </Loading>
      <Loading state={cat}>
        {(rows) => (
          <Card title="Event catalogue" sub="every event name in the data and how it maps to a key funnel event – use this to spot tracking drift or events worth mapping"
            right={<input className="field" placeholder="filter event name…" aria-label="Filter event names" value={filter} onChange={(e) => setFilter(e.target.value)} />}>
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

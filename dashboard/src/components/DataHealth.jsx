import { dt, num, useApi } from '../api'
import { Badge, Card, Table } from '../ui'

const TONE = { ok: 'good', warn: 'warn', bad: 'bad' }
const WORD = { ok: 'Healthy', warn: 'Needs a look', bad: 'Problem' }

/** How trustworthy is the data right now: freshness, pipeline runs and data-quality checks, in plain language. */
export default function DataHealth() {
  const s = useApi('/health', {}, { scoped: false })
  const d = s.data
  return (
    <Card title="Data health" sub="is the data fresh and complete enough to trust?" right={d ? <Badge tone={TONE[d.status]}>{WORD[d.status]}</Badge> : null}>
      {s.error && <div className="muted">Could not load: {s.error}</div>}
      {!d && !s.error && <div className="skeleton" style={{ height: 120 }} />}
      {d && (
        <>
          <div className="mini-list">
            {d.checks.map((c) => (
              <div key={c.key} className="health-row">
                <Badge tone={TONE[c.status]}>{c.label}</Badge>
                <span className="muted" style={{ fontSize: 13 }}>{c.detail}</span>
              </div>
            ))}
          </div>
          {d.runs.length > 0 && (
            <details style={{ marginTop: 10 }}>
              <summary className="muted" style={{ cursor: 'pointer', fontSize: 12 }}>Last pipeline runs ({d.runs.length})</summary>
              <Table rows={d.runs} cols={[
                { label: 'Step', render: (r) => r.step.replace('extract:raw_', 'pull ').replace('extract:', 'pull ') },
                { label: 'Finished', cls: 'nw', render: (r) => dt(r.finished_at) },
                { label: 'Rows', num: true, render: (r) => (r.rows == null ? '–' : num(r.rows)) },
                { label: 'Note', render: (r) => r.note || '' },
              ]} />
            </details>
          )}
        </>
      )}
    </Card>
  )
}

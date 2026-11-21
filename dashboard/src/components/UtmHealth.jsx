import { num, useApi } from '../api'
import { Badge, Card, Table } from '../ui'

const TONE = { ok: 'good', warn: 'warn', bad: 'bad' }

/** Are ads tagged well enough to be told apart? Plain-language checks with the fix for each, and the campaign names that do not match. */
export default function UtmHealth() {
  const s = useApi('/utm-health')
  const d = s.data
  return (
    <Card title="Ad tagging health" sub="campaign tags (UTM parameters) on your ad links decide whether visits and orders can be credited to the right campaign">
      {s.error && <div className="muted">Could not load: {s.error}</div>}
      {!d && !s.error && <div className="skeleton" style={{ height: 160 }} />}
      {d && (
        <>
          <div className="mini-list">
            {d.checks.map((c) => (
              <div key={c.label} className="health-row" style={{ alignItems: 'flex-start' }}>
                <Badge tone={TONE[c.status]}>{c.label}</Badge>
                <div style={{ flex: 1, minWidth: 220 }}>
                  <div style={{ fontSize: 13 }}>{c.detail}</div>
                  {c.status !== 'ok' && <div className="muted" style={{ fontSize: 12 }}>How to fix: {c.fix}</div>}
                </div>
              </div>
            ))}
          </div>
          <div className="grid g2" style={{ marginTop: 14 }}>
            <div>
              <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>Paid Meta campaign names we cannot match to a Meta campaign</div>
              <Table rows={d.unmatched_meta} empty="Every Paid Meta visit matches a campaign." cols={[
                { label: 'Name in the ad link', render: (r) => <span className="trunc" style={{ display: 'block', maxWidth: 260 }} title={r.campaign}>{r.campaign}</span> },
                { label: 'Visits', num: true, sortBy: 'sessions', render: (r) => num(r.sessions) },
              ]} />
            </div>
            <div>
              <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>Visits with no campaign name, by channel</div>
              <Table rows={d.by_channel} cols={[
                { label: 'Channel', key: 'channel' },
                { label: 'Visits', num: true, sortBy: 'sessions', render: (r) => num(r.sessions) },
                { label: 'No campaign name', num: true, sortBy: 'not_set', render: (r) => `${num(r.not_set)} (${r.sessions ? Math.round((100 * r.not_set) / r.sessions) : 0}%)` },
              ]} />
            </div>
          </div>
        </>
      )}
    </Card>
  )
}

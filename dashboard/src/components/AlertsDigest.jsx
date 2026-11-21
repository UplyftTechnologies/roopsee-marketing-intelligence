import { useState } from 'react'
import { useApi, useFilters } from '../api'
import { Badge, Card } from '../ui'

const TONE = { bad: 'bad', warn: 'warn', info: '' }
const WORD = { bad: 'Act now', warn: 'Look at', info: 'Opportunity' }

/** What changed this week that you would want to know about, worst first. Click one to open the page behind it. */
export function Alerts() {
  const f = useFilters()
  const s = useApi('/alerts', {}, { scoped: false })
  const d = s.data
  if (s.error) return null
  if (!d) return <div className="skeleton" style={{ height: 90 }} />
  return (
    <Card title="Needs your attention" sub={d.range ? `changes in the last 7 complete days (${d.range.from} to ${d.range.to}) against the 7 before` : undefined}
      right={<Badge tone={d.alerts.some((a) => a.level === 'bad') ? 'bad' : d.alerts.some((a) => a.level === 'warn') ? 'warn' : 'good'}>
        {d.alerts.length ? `${d.alerts.length} to look at` : 'All clear'}</Badge>}>
      {d.alerts.length === 0 && <div className="muted">Nothing unusual this week: tracking, orders, payments and ad tagging look normal.</div>}
      <div className="mini-list">
        {d.alerts.map((a) => (
          <div key={a.title} className="health-row" role="button" tabIndex={0} style={{ cursor: 'pointer', alignItems: 'flex-start' }}
            onClick={() => f.go(a.tab, a.prefill || {})} onKeyDown={(e) => { if (e.key === 'Enter') f.go(a.tab, a.prefill || {}) }}>
            <Badge tone={TONE[a.level]}>{WORD[a.level]}</Badge>
            <div style={{ flex: 1, minWidth: 220 }}><b style={{ fontWeight: 500 }}>{a.title}</b><div className="muted" style={{ fontSize: 13 }}>{a.detail}</div></div>
          </div>
        ))}
      </div>
    </Card>
  )
}

/** This week against last week in a few lines, ready to paste into a message. */
export function WeeklyDigest() {
  const s = useApi('/digest', {}, { scoped: false })
  const [copied, setCopied] = useState(false)
  const d = s.data
  if (s.error || !d || !d.lines?.length) return null
  const copy = async () => {
    try { await navigator.clipboard.writeText(d.text); setCopied(true); setTimeout(() => setCopied(false), 2000) } catch { window.prompt('Copy this summary', d.text) }
  }
  return (
    <Card title="The week in short" sub={d.head} right={<button type="button" className="btn small" onClick={copy}>{copied ? 'Copied ✓' : 'Copy as text'}</button>}>
      <ul className="digest">{d.lines.map((l) => <li key={l}>{l}</li>)}</ul>
    </Card>
  )
}

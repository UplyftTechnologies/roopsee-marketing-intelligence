import { useState } from 'react'
import { useApi, useFilters } from '../api'
import { Badge, Card, Help } from '../ui'

const ALERT_WORD = { bad: 'Act now', warn: 'Look at', info: 'Opportunity' }
const ALERT_TONE = { bad: 'bad', warn: 'warn', info: '' }
const INSIGHT_WORD = { bad: 'Problem', warn: 'Look at', good: 'Working', info: 'Good to know' }
const INSIGHT_TONE = { bad: 'bad', warn: 'warn', good: 'good', info: '' }
const HOW = 'Every number compares with the period before it (pick dates at the top). “This week” items compare the last 7 complete days with the 7 before; the others are found in the dates you picked. Click an item to open the rows behind it. Staff, test and bot traffic is hidden unless you change it under Filters.'

function Item({ badge, tone, when, title, detail, onOpen }) {
  return (
    <div className="attn-row" role={onOpen ? 'button' : undefined} tabIndex={onOpen ? 0 : undefined} onClick={onOpen}
      onKeyDown={onOpen ? (e) => { if (e.key === 'Enter') onOpen() } : undefined}>
      <Badge tone={tone}>{badge}</Badge>
      <div className="attn-body">
        <div className="attn-title">{title}{when && <span className="attn-when">{when}</span>}</div>
        <div className="muted attn-detail">{detail}</div>
      </div>
      {onOpen && <span className="attn-go" aria-hidden>→</span>}
    </div>
  )
}

/** Copies "the week in short" (this week against last week) as text, ready to paste into a message. */
export function CopyDigest() {
  const s = useApi('/digest', {}, { scoped: false })
  const [copied, setCopied] = useState(false)
  const d = s.data
  if (s.error || !d || !d.lines?.length) return null
  const copy = async () => {
    try { await navigator.clipboard.writeText(d.text); setCopied(true); setTimeout(() => setCopied(false), 2000) } catch { window.prompt('Copy this summary', d.text) }
  }
  return <button type="button" className="btn small" onClick={copy} title={`${d.head}\n\n${d.lines.join('\n')}`}>{copied ? 'Copied ✓' : 'Copy weekly summary'}</button>
}

/** One list of what needs a look: this week's alerts (worst first), then the problems found in the chosen dates. */
export function Attention({ insights }) {
  const f = useFilters()
  const s = useApi('/alerts', {}, { scoped: false })
  const alerts = s.data?.alerts || []
  const found = insights.filter((i) => i.tone === 'bad' || i.tone === 'warn')
  const n = alerts.filter((a) => a.level !== 'info').length + found.length
  return (
    <Card title={<>What needs attention <Help text={HOW} /></>} sub={s.data?.range ? `this week = ${s.data.range.from} to ${s.data.range.to}, against the 7 days before` : 'alerts and findings, worst first'}
      right={<span className="chip-row"><Badge tone={n ? (alerts.some((a) => a.level === 'bad') || found.some((i) => i.tone === 'bad') ? 'bad' : 'warn') : 'good'}>{n ? `${n} to look at` : 'All clear'}</Badge><CopyDigest /></span>}>
      {!s.data && !s.error ? <div className="skeleton" style={{ height: 120 }} /> : (
        <div className="attn-list">
          {alerts.map((a) => <Item key={`a-${a.title}`} badge={ALERT_WORD[a.level]} tone={ALERT_TONE[a.level]} when="this week" title={a.title} detail={a.detail} onOpen={() => f.go(a.tab, a.prefill || {})} />)}
          {found.map((i, k) => <Item key={`i-${k}`} badge={INSIGHT_WORD[i.tone]} tone={INSIGHT_TONE[i.tone]} when="in these dates" title={i.title} detail={i.detail} onOpen={i.tab ? () => f.go(i.tab, i.filters) : undefined} />)}
          {!alerts.length && !found.length && <div className="muted">Nothing unusual: tracking, orders, payments and ad tagging look normal.</div>}
        </div>
      )}
    </Card>
  )
}

/** What is going well, and context worth knowing, from the chosen dates. */
export function Working({ insights }) {
  const f = useFilters()
  const items = insights.filter((i) => i.tone === 'good' || i.tone === 'info')
  return (
    <Card title="What's working & good to know" sub="found in the dates you picked">
      <div className="attn-list">
        {items.map((i, k) => <Item key={k} badge={INSIGHT_WORD[i.tone]} tone={INSIGHT_TONE[i.tone]} title={i.title} detail={i.detail} onOpen={i.tab ? () => f.go(i.tab, i.filters) : undefined} />)}
        {!items.length && <div className="muted">Not enough data in these dates for findings. Try a wider date range.</div>}
      </div>
    </Card>
  )
}

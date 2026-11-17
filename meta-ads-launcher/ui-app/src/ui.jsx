import { useEffect, useState } from 'react'
import Icon from './Icon'

export function Card({ title, sub, right, children, className = '' }) {
  return (
    <section className={`card ${className}`}>
      {(title || right) && (
        <div className="card-head">
          <div><h3>{title}</h3>{sub && <div className="sub">{sub}</div>}</div>
          {right && <div className="chip-row">{right}</div>}
        </div>
      )}
      {children}
    </section>
  )
}

export const Badge = ({ tone = '', children, title }) => <span className={`badge ${tone}`} title={title}>{children}</span>
export const Banner = ({ tone = '', children }) => <div className={`banner ${tone}`}><div>{children}</div></div>

export function Field({ label, hint, children }) {
  return (
    <label className="lf">
      <span className="lf-label">{label}</span>
      {children}
      {hint && <span className="lf-hint">{hint}</span>}
    </label>
  )
}

export function Loading({ state, children }) {
  if (state.loading && !state.data) return <div className="skeleton-wrap"><div className="skeleton" style={{ height: 90 }} /><div className="skeleton" style={{ height: 220 }} /></div>
  if (state.error) return <div className="banner err">{state.error}</div>
  return state.data ? children(state.data) : null
}

/** Fetch once (and again when `deps` change). */
export function useLoad(fn, deps = []) {
  const [st, setSt] = useState({ data: null, loading: true, error: null })
  const [n, setN] = useState(0)
  useEffect(() => {
    let live = true
    setSt((s) => ({ ...s, loading: true, error: null }))
    fn().then((data) => live && setSt({ data, loading: false, error: null })).catch((e) => live && setSt({ data: null, loading: false, error: e.message }))
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, n])
  return [st, () => setN((x) => x + 1)]
}

export const STATUS_TONE = { ACTIVE: 'good', PAUSED: '', CAMPAIGN_PAUSED: '', ADSET_PAUSED: '', IN_PROCESS: 'warn', PENDING_REVIEW: 'warn', WITH_ISSUES: 'bad', DISAPPROVED: 'bad', ARCHIVED: '' }
export const statusText = (s) => (s ? s.toLowerCase().replace(/_/g, ' ') : '–')

/** Progress of a background job: a plain checklist, plain-English hints on failure, and the technical log folded away. */
export function JobPanel({ job }) {
  if (!job) return null
  const mark = { waiting: '○', running: '◐', done: '✓', failed: '✕' }
  return (
    <div className="jobpanel">
      <ol className="jsteps">
        {job.steps.map((s, i) => <li key={i} className={`js ${s.status}`}><span className="jmark">{mark[s.status]}</span>{s.title}</li>)}
      </ol>
      {job.status === 'done' && job.ok === false && job.hints?.length > 0 && (
        <div className="banner err"><div><b>What this probably means</b>{job.hints.map((h, i) => <div key={i} style={{ marginTop: 4 }}>{h}</div>)}</div></div>
      )}
      <details className="tech" open={job.status === 'done' && job.ok === false}>
        <summary>Technical details</summary>
        <pre className="log">{job.log || '…'}</pre>
      </details>
    </div>
  )
}

export function CopyBtn({ text, label = 'Copy' }) {
  const [ok, setOk] = useState(false)
  return (
    <button type="button" className="btn small" onClick={() => { navigator.clipboard?.writeText(text); setOk(true); setTimeout(() => setOk(false), 1200) }}>
      <Icon name={ok ? 'check' : 'copy'} size={13} /> {ok ? 'Copied' : label}
    </button>
  )
}

/** Expandable campaign > ad set > ad rows (same look as the dashboard's Meta Ads structure). */
export function Tree({ nodes }) {
  const [open, setOpen] = useState(() => new Set())
  const [q, setQ] = useState('')
  const ql = q.trim().toLowerCase()
  const has = (n) => !ql || n.name.toLowerCase().includes(ql) || String(n.id).includes(ql) || (n.children || []).some(has)
  const rows = []
  const push = (n, level) => {
    rows.push({ n, level })
    const kids = (n.children || []).filter(has)
    if (kids.length && (open.has(n.id) || ql)) kids.forEach((k) => push(k, level + 1))
  }
  nodes.filter(has).forEach((n) => push(n, 0))
  const all = nodes.flatMap((c) => [c.id, ...c.children.map((a) => a.id)])
  const toggle = (id) => { const x = new Set(open); if (x.has(id)) x.delete(id); else x.add(id); setOpen(x) }
  const lv = ['campaign', 'adset', 'ad']
  return (
    <>
      <div className="chip-row" style={{ marginBottom: 10 }}>
        <button type="button" className="btn small" onClick={() => setOpen(new Set(all))}>Expand all</button>
        <button type="button" className="btn small" onClick={() => setOpen(new Set())}>Collapse all</button>
        <input className="field" style={{ maxWidth: 240 }} placeholder="Find a campaign, ad set or ad…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search" />
      </div>
      {rows.length === 0 ? <div className="empty">Nothing here yet.</div> : (
        <div className="table-wrap">
          <table className="tree">
            <thead><tr><th>Campaign → ad set → ad</th><th>Status</th><th className="num">Budget / day</th><th>Goal</th><th>ID</th></tr></thead>
            <tbody>
              {rows.map(({ n, level }) => {
                const kids = n.children ? n.children.length : 0
                const isOpen = open.has(n.id) || (!!ql && kids > 0)
                return (
                  <tr key={`${level}-${n.id}`} className={`lv-${lv[level]}`}>
                    <td>
                      <div className="nm">
                        {kids ? <button type="button" className="caret" aria-expanded={isOpen} aria-label={isOpen ? 'Collapse' : 'Expand'} onClick={() => toggle(n.id)}><span style={{ display: 'inline-block', transition: 'transform .12s', transform: isOpen ? 'rotate(90deg)' : 'none' }}>›</span></button> : <span className="caret" />}
                        <span className="tag">{level === 1 ? 'ad set' : lv[level]}</span>
                        <span className="trunc" style={{ maxWidth: 340 }} title={n.name}>{n.name}</span>
                        {kids > 0 && <span className="muted" style={{ fontSize: 12 }}>{kids}</span>}
                      </div>
                    </td>
                    <td className="nw"><Badge tone={STATUS_TONE[n.status]}>{statusText(n.status)}</Badge></td>
                    <td className="num">{n.daily_budget ? '₹' + Number(n.daily_budget).toLocaleString('en-IN') : '–'}</td>
                    <td className="muted">{(n.objective || n.goal || '').replace('OUTCOME_', '').toLowerCase().replace(/_/g, ' ')}</td>
                    <td className="mono muted">{n.id}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

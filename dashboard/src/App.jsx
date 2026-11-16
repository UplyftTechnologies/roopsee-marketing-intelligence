import { useEffect, useMemo, useState } from 'react'
import { FilterCtx, api, num } from './api'
import Overview from './pages/Overview'
import Funnel from './pages/Funnel'
import Campaigns from './pages/Campaigns'
import Cohorts from './pages/Cohorts'
import Sessions from './pages/Sessions'
import Users from './pages/Users'
import Exclusions from './pages/Exclusions'
import DataPage from './pages/Data'

const TABS = [
  ['overview', 'Overview', Overview], ['funnel', 'Funnel & checkout', Funnel], ['campaigns', 'Campaigns', Campaigns],
  ['cohorts', 'Cohorts & geo', Cohorts], ['sessions', 'Sessions', Sessions], ['users', 'Users', Users],
  ['exclusions', 'Exclusions', Exclusions], ['data', 'Data & ETL', DataPage],
]
const iso = (d) => d.toISOString().slice(0, 10)
const shift = (s, n) => { const d = new Date(s + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return iso(d) }

export default function App() {
  const [tab, setTab] = useState(() => location.hash.slice(1) || 'overview')
  const [meta, setMeta] = useState(null)
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [includeExcluded, setIncludeExcluded] = useState(false)
  const [tick, setTick] = useState(0)
  const [theme, setTheme] = useState(() => localStorage.getItem('theme') || 'auto')

  useEffect(() => { location.hash = tab }, [tab])
  useEffect(() => {
    if (theme === 'auto') document.documentElement.removeAttribute('data-theme')
    else document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('theme', theme)
  }, [theme])

  const loadMeta = () => api('/meta').then(setMeta).catch(() => {})
  useEffect(() => { loadMeta() }, [tick])
  // while a background job runs, poll; when it finishes reload every view
  useEffect(() => {
    if (!meta?.job?.running) return
    const t = setInterval(async () => {
      const j = await api('/jobs')
      if (!j.running) { setTick((x) => x + 1); clearInterval(t) } else setMeta((m) => ({ ...m, job: j }))
    }, 1500)
    return () => clearInterval(t)
  }, [meta?.job?.running])

  const last = meta?.range?.last
  const preset = (n) => { if (!last) return; setTo(last); setFrom(n ? shift(last, -(n - 1)) : '') }
  const ctx = useMemo(() => ({ from, to, includeExcluded, tick, bump: () => setTick((x) => x + 1), meta, reloadMeta: loadMeta }),
    [from, to, includeExcluded, tick, meta])
  const Page = TABS.find((t) => t[0] === tab)?.[2] || Overview
  const job = meta?.job

  const startRefresh = async () => { await api('/refresh', { method: 'POST', params: { mode: 'full' } }); loadMeta() }

  return (
    <FilterCtx.Provider value={ctx}>
      <header className="topbar">
        <div className="topbar-row">
          <div className="brand">Roopsee Marketing Intelligence<small>{meta?.counts ? `${num(meta.counts.events)} events · data to ${meta.range?.last ?? '–'}` : 'connecting…'}</small></div>
          <div className="chip-row">
            {[['7d', 7], ['30d', 30], ['All', 0]].map(([l, n]) => <button key={l} className="chip" onClick={() => preset(n)}>{l}</button>)}
            <input className="field" type="date" value={from} onChange={(e) => setFrom(e.target.value)} aria-label="From date" />
            <span className="muted">→</span>
            <input className="field" type="date" value={to} onChange={(e) => setTo(e.target.value)} aria-label="To date" />
          </div>
          <label className="toggle" title="Show internal / bot traffic that Exclusions would normally remove">
            <input type="checkbox" checked={includeExcluded} onChange={(e) => setIncludeExcluded(e.target.checked)} /> Include excluded traffic
          </label>
          <div className="spacer" />
          {job?.running
            ? <span className="badge warn">{job.name}: {job.message || 'running'}…</span>
            : job?.error ? <span className="badge bad" title={job.error}>last job failed</span> : null}
          <button className="btn primary" disabled={job?.running} onClick={startRefresh} title="Pull new events from Supabase (read-only) and rebuild">Refresh data</button>
          <button className="btn" onClick={() => setTheme(theme === 'dark' ? 'light' : theme === 'light' ? 'auto' : 'dark')}>Theme: {theme}</button>
        </div>
        <nav className="tabs">
          {TABS.map(([k, label]) => <button key={k} className={`tab ${tab === k ? 'active' : ''}`} onClick={() => setTab(k)}>{label}</button>)}
        </nav>
      </header>
      <main className="page">
        {meta && !meta.ready
          ? <div className="banner err">No analytics tables yet. Run <span className="mono">python -m mi.cli all</span> or press “Refresh data”.</div>
          : <Page />}
      </main>
    </FilterCtx.Provider>
  )
}

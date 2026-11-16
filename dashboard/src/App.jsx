import { useEffect, useMemo, useRef, useState } from 'react'
import { FilterCtx, api, num } from './api'
import Home from './pages/Home'
import Overview from './pages/Overview'
import Funnel from './pages/Funnel'
import Campaigns from './pages/Campaigns'
import Cohorts from './pages/Cohorts'
import Sessions from './pages/Sessions'
import Users from './pages/Users'
import Exclusions from './pages/Exclusions'
import DataPage from './pages/Data'

// [key, label, glyph, one-line description, component, group]
const NAV = [
  ['home', 'Home', '◎', 'What matters right now', Home, 'Start here'],
  ['performance', 'Performance', '▤', 'Traffic, orders and trends over time', Overview, 'Analyse'],
  ['funnel', 'Funnel & checkout', '▽', 'Where people drop off, who to follow up', Funnel, 'Analyse'],
  ['campaigns', 'Campaigns', '◈', 'Which ads and sources are working', Campaigns, 'Analyse'],
  ['cohorts', 'Cohorts & geo', '◉', 'Who your customers are and where from', Cohorts, 'Analyse'],
  ['sessions', 'Sessions', '☰', 'Every visit, with a full event timeline', Sessions, 'Explore'],
  ['users', 'Users', '☺', 'People and where they are in the journey', Users, 'Explore'],
  ['exclusions', 'Exclusions', '⊘', 'Remove internal, test and bot traffic', Exclusions, 'Set up'],
  ['data', 'Data & ETL', '⟳', 'Refresh data, tracking health', DataPage, 'Set up'],
]
const iso = (d) => d.toISOString().slice(0, 10)
const shift = (s, n) => { const d = new Date(s + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return iso(d) }
const fmt = (s) => (s ? new Date(s + 'T00:00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) : '')
const daysBetween = (a, b) => Math.round((new Date(b) - new Date(a)) / 86400000) + 1

export default function App() {
  const initial = location.hash.slice(1)
  const [tab, setTab] = useState(NAV.some((n) => n[0] === initial) ? initial : 'home')
  const [prefill, setPrefill] = useState({})
  const [navKey, setNavKey] = useState(0)
  const [meta, setMeta] = useState(null)
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [custom, setCustom] = useState(false)
  const [hideInternal, setHideInternal] = useState(true)
  const [compare, setCompare] = useState(true)
  const [tick, setTick] = useState(0)
  const [theme, setTheme] = useState(() => localStorage.getItem('theme') || 'auto')
  const [menu, setMenu] = useState(false)
  const inited = useRef(false)

  const go = (key, pre = {}) => { setPrefill(pre); setTab(key); setNavKey((k) => k + 1); setMenu(false); window.scrollTo(0, 0) }
  useEffect(() => { location.hash = tab }, [tab])
  useEffect(() => {
    if (theme === 'auto') document.documentElement.removeAttribute('data-theme')
    else document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('theme', theme)
  }, [theme])

  const loadMeta = () => api('/meta').then(setMeta).catch(() => {})
  useEffect(() => { loadMeta() }, [tick])
  useEffect(() => {
    if (!meta?.job?.running) return
    const t = setInterval(async () => {
      const j = await api('/jobs')
      if (!j.running) { setTick((x) => x + 1); clearInterval(t) } else setMeta((m) => ({ ...m, job: j }))
    }, 1500)
    return () => clearInterval(t)
  }, [meta?.job?.running])

  const first = meta?.range?.first
  const last = meta?.range?.last
  // default view: the last 30 days of data (a sensible, comparable window)
  useEffect(() => {
    if (last && !inited.current) { inited.current = true; setTo(last); setFrom(shift(last, -29)) }
  }, [last])

  const presets = last ? [
    ['Today', last, last], ['Yesterday', shift(last, -1), shift(last, -1)], ['Last 7 days', shift(last, -6), last],
    ['Last 30 days', shift(last, -29), last], ['All time', '', ''],
  ] : []
  const active = presets.find(([, f, t]) => f === from && t === to)?.[0]
  const ctx = useMemo(() => ({ from, to, includeExcluded: !hideInternal, compare, tick, bump: () => setTick((x) => x + 1), meta, reloadMeta: loadMeta, go, prefill }),
    [from, to, hideInternal, compare, tick, meta, prefill])
  const cur = NAV.find((n) => n[0] === tab) || NAV[0]
  const Page = cur[4]
  const job = meta?.job
  const c = meta?.counts
  const rangeText = from && to ? (from === to ? fmt(from) : `${fmt(from)} – ${fmt(to)}`) : first ? `All time (${fmt(first)} – ${fmt(last)})` : 'All time'
  const prevText = from && to ? `${fmt(shift(from, -daysBetween(from, to)))} – ${fmt(shift(from, -1))}` : null
  const tc = meta?.tracking_change
  const prevStart = from && to ? shift(from, -daysBetween(from, to)) : null
  const crossesUpgrade = tc && ((from ? from < tc : first && first < tc) || (compare && prevStart && prevStart < tc))
  const startRefresh = async () => { await api('/refresh', { method: 'POST', params: { mode: 'full' } }); loadMeta() }
  let lastGroup = null

  return (
    <FilterCtx.Provider value={ctx}>
      <div className="shell">
        <aside className={`side ${menu ? 'open' : ''}`}>
          <div className="side-brand"><b>Roopsee</b><span>Marketing Intelligence</span></div>
          <nav>
            {NAV.map(([k, label, glyph, desc, , group]) => {
              const header = group !== lastGroup ? <div key={`g-${group}`} className="nav-group">{group}</div> : null
              lastGroup = group
              return (
                <div key={k}>
                  {header}
                  <button className={`nav-item ${tab === k ? 'active' : ''}`} onClick={() => go(k)} title={desc}>
                    <span className="glyph" aria-hidden>{glyph}</span>
                    <span><span className="nav-label">{label}</span><span className="nav-desc">{desc}</span></span>
                  </button>
                </div>
              )
            })}
          </nav>
          <div className="side-foot">
            <div className="muted" style={{ fontSize: 12 }}>
              {c ? `${num(c.events)} events · data to ${fmt(last)}` : 'connecting…'}
              <br />Rebuilt {meta?.last_transform ? new Date(meta.last_transform).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '–'}
            </div>
            <button className="btn primary" style={{ width: '100%' }} disabled={job?.running} onClick={startRefresh}
              title="Pull new events from Supabase (read-only) and rebuild everything">{job?.running ? 'Working…' : 'Refresh data'}</button>
            {job?.running && <div className="badge warn">{job.name}: {job.message || 'running'}…</div>}
            {job?.error && <div className="badge bad" title={job.error}>last job failed</div>}
            <label className="muted" style={{ fontSize: 12 }}>Theme{' '}
              <select className="field" value={theme} onChange={(e) => setTheme(e.target.value)}>
                <option value="auto">Match system</option><option value="light">Light</option><option value="dark">Dark</option>
              </select>
            </label>
          </div>
        </aside>

        <div className="content">
          <header className="filterbar">
            <button className="btn menu-btn" onClick={() => setMenu(!menu)} aria-label="Menu">☰</button>
            <div className="fb-title"><h1>{cur[1]}</h1><span className="muted">{cur[3]}</span></div>
            <div className="spacer" />
            {tab !== 'exclusions' && tab !== 'data' && (
              <>
                <div className="chip-row" role="group" aria-label="Date range">
                  {presets.map(([l, f, t]) => <button key={l} className={`chip ${active === l && !custom ? 'on' : ''}`} onClick={() => { setFrom(f); setTo(t); setCustom(false) }}>{l}</button>)}
                  <button className={`chip ${custom || !active ? 'on' : ''}`} onClick={() => setCustom(!custom)}>Custom</button>
                </div>
                {(custom || !active) && (
                  <span className="chip-row">
                    <input className="field" type="date" min={first} max={last} value={from} onChange={(e) => setFrom(e.target.value)} aria-label="From date" />
                    <span className="muted">→</span>
                    <input className="field" type="date" min={first} max={last} value={to} onChange={(e) => setTo(e.target.value)} aria-label="To date" />
                  </span>
                )}
                <label className="toggle" title="Removes staff, test, bot and non-India traffic. Edit the rules in Exclusions.">
                  <input type="checkbox" checked={hideInternal} onChange={(e) => setHideInternal(e.target.checked)} />
                  Hide internal &amp; bot traffic{c && hideInternal ? ` (${num(c.sessions_excluded)} sessions)` : ''}
                </label>
                {prevText && (
                  <label className="toggle" title="Show change versus the previous period of the same length">
                    <input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} /> Compare
                  </label>
                )}
              </>
            )}
          </header>
          {tab !== 'exclusions' && tab !== 'data' && (
            <div className="rangebar">Showing <b>{rangeText}</b>{prevText && compare ? <> · compared with <b>{prevText}</b></> : null}{!hideInternal ? <> · <b>including</b> internal &amp; bot traffic</> : null}
              {crossesUpgrade && <span className="upgrade-note">⚠ Tracking was upgraded on {fmt(tc)}. Session counts, bounce rate and session length from before that date are not comparable with after it.</span>}</div>
          )}
          <main className="page" key={navKey}>
            {meta && !meta.ready
              ? <div className="banner err">No analytics tables yet. Run <span className="mono">python -m mi.cli all</span> or press “Refresh data”.</div>
              : <Page />}
          </main>
        </div>
      </div>
    </FilterCtx.Provider>
  )
}

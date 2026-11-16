import { useEffect, useMemo, useRef, useState } from 'react'
import { FilterCtx, api, num } from './api'
import Icon from './components/Icon'
import Popover from './components/Popover'
import DatePicker from './components/DatePicker'
import Home from './pages/Home'
import Overview from './pages/Overview'
import Funnel from './pages/Funnel'
import Campaigns from './pages/Campaigns'
import Cohorts from './pages/Cohorts'
import Sessions from './pages/Sessions'
import Users from './pages/Users'
import Exclusions from './pages/Exclusions'
import DataPage from './pages/Data'
import Basket from './pages/Basket'
import Loyalty from './pages/Loyalty'
import Audiences from './pages/Audiences'
import Person from './pages/Person'
import SessionPage from './pages/SessionPage'

// [key, label, icon, one-line description (tooltip + page subtitle), component, group]
const NAV = [
  ['home', 'Home', 'home', 'What matters right now', Home, ''],
  ['performance', 'Performance', 'chart', 'Traffic, orders and trends over time', Overview, 'Reports'],
  ['funnel', 'Funnel & checkout', 'funnel', 'Where people drop off, who to follow up', Funnel, 'Reports'],
  ['campaigns', 'Campaigns', 'megaphone', 'Which ads and sources are working', Campaigns, 'Reports'],
  ['cohorts', 'Cohorts & geo', 'globe', 'Who your customers are and where from', Cohorts, 'Reports'],
  ['basket', 'Basket & AOV', 'basket', 'What people buy and how to raise order value', Basket, 'Reports'],
  ['loyalty', 'Retention & LTV', 'loop', 'Who comes back and what they are worth', Loyalty, 'Reports'],
  ['audiences', 'Audiences', 'target', 'Who you can reach, and with what', Audiences, 'Grow'],
  ['sessions', 'Sessions', 'list', 'Every visit, with a full event timeline', Sessions, 'Explore'],
  ['users', 'Users', 'users', 'People and where they are in the journey', Users, 'Explore'],
  ['exclusions', 'Exclusions', 'ban', 'Remove internal, test and bot traffic', Exclusions, 'Admin'],
  ['data', 'Data & ETL', 'database', 'Refresh data, tracking health', DataPage, 'Admin'],
]
// Detail pages: not in the menu, reached by clicking a person or a session
const EXTRA = [
  ['person', 'Person', 'users', 'Everything about one person', Person, 'Users'],
  ['session', 'Session', 'list', 'Everything about one session', SessionPage, 'Sessions'],
]
function parseHash() {
  const [a, ...rest] = decodeURIComponent(location.hash.slice(1)).split('/')
  if ((a === 'person' || a === 'session') && rest.length) return { tab: a, prefill: { key: rest.join('/') } }
  return { tab: NAV.some((n) => n[0] === a) ? a : 'home', prefill: {} }
}
const iso = (d) => d.toISOString().slice(0, 10)
const shift = (s, n) => { const d = new Date(s + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return iso(d) }
const fmt = (s) => (s ? new Date(s + 'T00:00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) : '')
const daysBetween = (a, b) => Math.round((new Date(b) - new Date(a)) / 86400000) + 1

export default function App() {
  const [init] = useState(parseHash)
  const [tab, setTab] = useState(init.tab)
  const [prefill, setPrefill] = useState(init.prefill)
  const lastHash = useRef('')
  const [navKey, setNavKey] = useState(0)
  const [meta, setMeta] = useState(null)
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [hideInternal, setHideInternal] = useState(true)
  const [compare, setCompare] = useState(true)
  const [tick, setTick] = useState(0)
  const [theme, setTheme] = useState(() => { const q = new URLSearchParams(location.search).get('theme'); return ['light', 'dark', 'auto'].includes(q) ? q : localStorage.getItem('theme') || 'light' })
  const [collapsed, setCollapsed] = useState(() => { const q = new URLSearchParams(location.search).get('rail'); return q ? q === '1' : localStorage.getItem('rail') === '1' })
  const [menu, setMenu] = useState(false)
  const inited = useRef(false)

  const go = (key, pre = {}) => { setPrefill(pre); setTab(key); setNavKey((k) => k + 1); setMenu(false); window.scrollTo(0, 0) }
  useEffect(() => {
    const h = (tab === 'person' || tab === 'session') && prefill.key ? `${tab}/${prefill.key}` : tab
    lastHash.current = h
    location.hash = (tab === 'person' || tab === 'session') && prefill.key ? `${tab}/${encodeURIComponent(prefill.key)}` : tab
  }, [tab, prefill])
  useEffect(() => {
    const onHash = () => {
      if (decodeURIComponent(location.hash.slice(1)) === lastHash.current) return
      const n = parseHash()
      setPrefill(n.prefill); setTab(n.tab); setNavKey((k) => k + 1)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  useEffect(() => {
    if (theme === 'auto') document.documentElement.removeAttribute('data-theme')
    else document.documentElement.setAttribute('data-theme', theme)
    try { localStorage.setItem('theme', theme) } catch { /* ignore */ }
  }, [theme])
  useEffect(() => { try { localStorage.setItem('rail', collapsed ? '1' : '0') } catch { /* ignore */ } }, [collapsed])

  const loadMeta = () => api('/meta').then(setMeta).catch(() => {})
  useEffect(() => { loadMeta() }, [tick])
  useEffect(() => {
    if (!meta?.job?.running) return undefined
    const t = setInterval(async () => {
      const j = await api('/jobs')
      if (!j.running) { setTick((x) => x + 1); clearInterval(t) } else setMeta((m) => ({ ...m, job: j }))
    }, 1500)
    return () => clearInterval(t)
  }, [meta?.job?.running])

  const first = meta?.range?.first
  const last = meta?.range?.last
  useEffect(() => { if (last && !inited.current) { inited.current = true; setTo(last); setFrom(shift(last, -29)) } }, [last])

  const presets = last ? [
    ['Today', last, last], ['Yesterday', shift(last, -1), shift(last, -1)], ['Last 7 days', shift(last, -6), last],
    ['Last 30 days', shift(last, -29), last], ['All time', '', ''],
  ] : []
  const active = presets.find(([, f, t]) => f === from && t === to)?.[0]
  const rangeText = from && to ? (from === to ? fmt(from) : `${fmt(from)} – ${fmt(to)}`) : first ? `${fmt(first)} – ${fmt(last)}` : 'All time'
  const canCompare = !!(from && to)
  const prevText = canCompare ? `${fmt(shift(from, -daysBetween(from, to)))} – ${fmt(shift(from, -1))}` : null
  const cur = [...NAV, ...EXTRA].find((n) => n[0] === tab) || NAV[0]
  const railActive = tab === 'person' ? 'users' : tab === 'session' ? 'sessions' : tab
  const Page = cur[4]
  const dateless = tab === 'loyalty' || tab === 'audiences'
  const noDates = dateless || ['exclusions', 'data', 'person', 'session'].includes(tab)
  const job = meta?.job
  const c = meta?.counts
  const tc = meta?.tracking_change
  const prevStart = canCompare ? shift(from, -daysBetween(from, to)) : null
  const crossesUpgrade = !noDates && tc && ((from ? from < tc : first && first < tc) || (compare && prevStart && prevStart < tc))
  const upgradeText = tc ? `Tracking was upgraded on ${fmt(tc)}. Session counts, bounce rate and session length from before that date are not comparable with after it.` : ''

  const ctx = useMemo(() => ({ from, to, includeExcluded: !hideInternal, compare: compare && canCompare, tick, bump: () => setTick((x) => x + 1), meta, reloadMeta: loadMeta, go, prefill, rangeText, prevText }),
    [from, to, hideInternal, compare, canCompare, tick, meta, prefill, rangeText, prevText])
  const startRefresh = async () => { await api('/refresh', { method: 'POST', params: { mode: 'full' } }); loadMeta() }
  let lastGroup = null

  return (
    <FilterCtx.Provider value={ctx}>
      <div className={`app ${collapsed ? 'collapsed' : ''}`}>
        <aside className={`rail ${menu ? 'open' : ''}`} aria-label="Main navigation">
          <div className="rail-brand"><div className="logo">R</div><div><b>Roopsee</b><small>Marketing Intelligence</small></div></div>
          <nav>
            {NAV.map(([k, label, icon, desc, , group]) => {
              const header = group && group !== lastGroup ? <div key={`g-${group}`} className="rail-group">{group}</div> : null
              lastGroup = group || lastGroup
              return (
                <div key={k}>
                  {header}
                  <button type="button" className={`rail-item ${railActive === k ? 'active' : ''}`} onClick={() => go(k)} title={`${label} – ${desc}`} aria-current={railActive === k ? 'page' : undefined}>
                    <Icon name={icon} /><span className="rail-label">{label}</span>
                  </button>
                </div>
              )
            })}
          </nav>
          <div className="rail-foot">
            <div className="muted hide-collapsed">
              {c ? `${num(c.events)} events · to ${fmt(last)}` : 'connecting…'}<br />
              Rebuilt {meta?.last_transform ? new Date(meta.last_transform).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '–'}
            </div>
            <label className="muted hide-collapsed" style={{ fontSize: 12 }}>Theme{' '}
              <select className="field" value={theme} onChange={(e) => setTheme(e.target.value)}>
                <option value="light">Light</option><option value="dark">Dark</option><option value="auto">Match system</option>
              </select>
            </label>
            <button type="button" className="rail-toggle" onClick={() => setCollapsed(!collapsed)} aria-label={collapsed ? 'Expand menu' : 'Collapse menu'} title={collapsed ? 'Expand menu' : 'Collapse menu'}>
              <Icon name={collapsed ? 'right' : 'left'} size={18} /><span className="rail-label">Collapse</span>
            </button>
          </div>
        </aside>

        <div className="main">
          <header className="topbar2">
            <button type="button" className="icon-btn menu-btn2" onClick={() => setMenu(!menu)} aria-label="Open menu"><Icon name="menu" /></button>
            <div><span className="crumb">{cur[5] || 'Roopsee'}</span><h1>{cur[1]}</h1></div>
            <div style={{ flex: 1 }} />
            {job?.running && <span className="badge warn">{job.name}: {job.message || 'running'}…</span>}
            {job?.error && <span className="badge bad" title={job.error}>last job failed</span>}
            {!noDates && (
              <DatePicker presets={presets} active={active} from={from} to={to} rangeText={rangeText} prevText={prevText} compare={compare} setCompare={setCompare}
                setRange={(f, t) => { setFrom(f); setTo(t) }} first={first} last={last} canCompare={canCompare} note={crossesUpgrade ? upgradeText : null} />
            )}
            {!['exclusions', 'data', 'person', 'session'].includes(tab) && (
              <Popover align="right" width={320} trigger={({ open, toggle }) => (
                <button type="button" className="pill-btn" aria-expanded={open} onClick={toggle} title="Internal, test and bot traffic">
                  <span className={`dot ${hideInternal ? '' : 'off'}`} />{hideInternal ? 'Internal traffic hidden' : 'All traffic shown'}<Icon name="chevron" size={16} />
                </button>
              )}>
                {(close) => (
                  <>
                    <label className="row-between" style={{ cursor: 'pointer' }}>
                      <span><b style={{ fontWeight: 500 }}>Hide internal &amp; bot traffic</b><br /><small className="muted">Staff, test, dev and non-India traffic{c ? `: ${num(c.sessions_excluded)} sessions, ${num(c.people_excluded)} people` : ''}</small></span>
                      <span className="switch"><input type="checkbox" checked={hideInternal} onChange={(e) => setHideInternal(e.target.checked)} /><i /></span>
                    </label>
                    <div className="pop-sep" />
                    <button type="button" className="pop-item" onClick={() => { close(); go('exclusions') }}>Edit exclusion rules<Icon name="right" size={16} /></button>
                  </>
                )}
              </Popover>
            )}
            <button type="button" className="pill-btn" disabled={job?.running} onClick={startRefresh} title="Pull new events from Supabase (read-only) and rebuild everything">
              <Icon name="refresh" size={18} />{job?.running ? 'Updating…' : 'Refresh'}
            </button>
          </header>
          {crossesUpgrade && <div className="notice" role="note"><Icon name="info" size={18} />{upgradeText}</div>}
          {dateless && <div className="notice" role="note"><Icon name="info" size={18} />All-time view: the date range does not apply to this page.</div>}
          <main className="page" key={navKey}>
            {meta && !meta.ready
              ? <div className="banner err">No analytics tables yet. Run <span className="mono">python3 run.py</span> or press “Refresh”.</div>
              : <Page />}
          </main>
        </div>
      </div>
    </FilterCtx.Provider>
  )
}

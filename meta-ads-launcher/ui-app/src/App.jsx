import { useEffect, useMemo, useState } from 'react'
import Icon from './Icon'
import EnvSwitch from './EnvSwitch'
import { api } from './api'
import Overview from './pages/Overview'
import Builder from './pages/Builder'
import Creatives from './pages/Creatives'
import Campaigns from './pages/Campaigns'
import Setup from './pages/Setup'
import Run from './pages/Run'
import Health from './pages/Health'
import Library from './pages/Library'
import Manage from './pages/Manage'

// key, label, icon, description, page, group
const NAV = [
  ['new', 'New campaign', 'plus', 'Create a campaign step by step', Builder, 'Create'],
  ['overview', 'Overview', 'overview', 'Everything on Meta, live', Overview, 'Manage'],
  ['manage', 'Edit live campaigns', 'setup', 'Edit ad sets, add or change creatives, pause or turn on', Manage, 'Manage'],
  ['campaigns', 'Campaigns & ad sets', 'setup', 'Set up campaigns, ad sets and audiences', Campaigns, 'Manage'],
  ['library', 'Past campaigns', 'overview', 'Your saved copy of past campaigns, ad sets, ads and media', Library, 'Library'],
  ['creatives', 'Creatives', 'image', 'Your images', Creatives, 'Library'],
  ['setup', 'Links & tracking', 'setup', 'Web page links and tracking tags', Setup, 'Advanced'],
  ['run', 'Run', 'run', 'Run steps by hand, go live', Run, 'Advanced'],
  ['health', 'Health', 'health', 'Check the connection', Health, 'Advanced'],
]

function parseHash() {
  const [a, qs] = decodeURIComponent(location.hash.slice(1)).split('?')
  return { tab: NAV.some((n) => n[0] === a) ? a : 'overview', params: Object.fromEntries(new URLSearchParams(qs || '')) }
}

const callsTip = (u) => ['Calls this launcher has made to Meta since it started', ...Object.entries(u.by || {}).map(([k, v]) => `${v} × ${k}`)].join('\n')

export default function App() {
  const [{ tab, params }, setRoute] = useState(parseHash)
  const [env, setEnv] = useState(null)
  const [theme, setTheme] = useState(() => { const q = new URLSearchParams(location.search).get('theme'); return ['light', 'dark', 'auto'].includes(q) ? q : localStorage.getItem('theme') || 'light' })
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('rail') === '1')
  const [menu, setMenu] = useState(false)
  const [navKey, setNavKey] = useState(0)
  const [usage, setUsage] = useState(null)

  const go = (key, p = {}) => {
    const qs = new URLSearchParams(p).toString()
    location.hash = key + (qs ? '?' + qs : '')
    setMenu(false)
    window.scrollTo(0, 0)
  }
  useEffect(() => {
    const on = () => { setRoute(parseHash()); setNavKey((k) => k + 1) }
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  useEffect(() => {
    if (theme === 'auto') document.documentElement.removeAttribute('data-theme')
    else document.documentElement.setAttribute('data-theme', theme)
    try { localStorage.setItem('theme', theme) } catch { /* ignore */ }
  }, [theme])
  useEffect(() => { try { localStorage.setItem('rail', collapsed ? '1' : '0') } catch { /* ignore */ } }, [collapsed])
  useEffect(() => { api('/api/state').then(setEnv).catch(() => {}) }, [navKey])
  useEffect(() => { // how many calls this session made to Meta (a local read, not a call to Meta)
    const load = () => api('/api/usage').then(setUsage).catch(() => {})
    load(); const t = setInterval(load, 15000); return () => clearInterval(t)
  }, [navKey])

  const cur = NAV.find((n) => n[0] === tab) || NAV[1]
  const Page = cur[4]
  const prod = env?.env === 'production'
  const ctx = useMemo(() => ({ go, env }), [env]) // eslint-disable-line react-hooks/exhaustive-deps
  let lastGroup = null

  return (
    <div className={`app ${collapsed ? 'collapsed' : ''}`}>
      <aside className={`rail ${menu ? 'open' : ''}`} aria-label="Main navigation">
        <div className="rail-brand"><div className="logo">R</div><div><b>Roopsee</b><small>Ads Launcher</small></div></div>
        <nav>
          {NAV.map(([k, label, icon, desc, , group]) => {
            const header = group !== lastGroup ? <div key={`g-${group}`} className="rail-group">{group}</div> : null
            lastGroup = group
            return (
              <div key={k}>
                {header}
                <button type="button" className={`rail-item ${tab === k ? 'active' : ''}`} onClick={() => go(k)} title={`${label} – ${desc}`} aria-current={tab === k ? 'page' : undefined}>
                  <Icon name={icon} /><span className="rail-label">{label}</span>
                </button>
              </div>
            )
          })}
        </nav>
        <div className="rail-foot">
          <div className="muted hide-collapsed">{env ? `${env.env === 'production' ? 'Production' : 'Sandbox'} · ${env.account || 'no account set'}` : 'connecting…'}</div>
          {usage && <div className="muted hide-collapsed" style={{ fontSize: 12 }} title={callsTip(usage)}>Meta calls this session: <b>{usage.calls}</b>{usage.usage_pct ? ` · limit ${usage.usage_pct}% used` : ''}</div>}
          <label className="muted hide-collapsed" style={{ fontSize: 12 }}>Theme{' '}
            <select className="field" value={theme} onChange={(e) => setTheme(e.target.value)}>
              <option value="light">Light</option><option value="dark">Dark</option><option value="auto">Match system</option>
            </select>
          </label>
          <button type="button" className="rail-toggle" onClick={() => setCollapsed(!collapsed)} aria-label={collapsed ? 'Expand menu' : 'Collapse menu'}>
            <Icon name={collapsed ? 'right' : 'left'} size={18} /><span className="rail-label">Collapse</span>
          </button>
        </div>
      </aside>

      <div className="main">
        <header className="topbar2">
          <button type="button" className="icon-btn menu-btn2" onClick={() => setMenu(!menu)} aria-label="Open menu"><Icon name="menu" /></button>
          <div><span className="crumb">{cur[5]}</span><h1>{cur[1]}</h1></div>
          <div style={{ flex: 1 }} />
          {env && <EnvSwitch env={env} startOpen={new URLSearchParams(location.search).get('envmenu') || false} onSwitched={() => { setNavKey((k) => k + 1); window.scrollTo(0, 0) }} />}
          <a className="pill-btn" href="http://127.0.0.1:8000" target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }} title="Open the performance dashboard">Performance dashboard<Icon name="external" size={15} /></a>
        </header>
        {env && (prod
          ? <div className="notice prod" role="note"><Icon name="info" size={18} />PRODUCTION: this is your real ad account. Everything is created paused, and nothing is turned on without your typed confirmation.</div>
          : <div className="notice" role="note"><Icon name="info" size={18} />Sandbox: nothing is delivered and no money is spent. Sandbox ads cannot be seen in Ads Manager; use the Overview page.</div>)}
        {usage?.blocked_seconds > 0 && <div className="notice prod" role="alert"><Icon name="info" size={18} />Meta is limiting calls for this ad account. {usage.blocked_why} Try again in about {Math.ceil(usage.blocked_seconds / 60)} min. Nothing is sent to Meta until then.</div>}
        <main className="page" key={navKey}>
          <Page ctx={ctx} params={params} />
        </main>
      </div>
    </div>
  )
}

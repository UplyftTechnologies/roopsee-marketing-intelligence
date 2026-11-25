import { Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react'
import { DEVICE_OPTIONS, FilterCtx, SALES_OPTIONS, api, clearPersisted, decodeShare, num } from './api'
import Icon from './components/Icon'
import Popover from './components/Popover'
import DatePicker from './components/DatePicker'

// pages load on demand, so the first screen downloads only what it needs
const Home = lazy(() => import('./pages/Home'))
const Overview = lazy(() => import('./pages/Overview'))
const PainPoints = lazy(() => import('./pages/PainPoints'))
const Journeys = lazy(() => import('./pages/Journeys'))
const Funnel = lazy(() => import('./pages/Funnel'))
const Campaigns = lazy(() => import('./pages/Campaigns'))
const Cohorts = lazy(() => import('./pages/Cohorts'))
const Sessions = lazy(() => import('./pages/Sessions'))
const Deeper = lazy(() => import('./pages/Deeper'))
const MapPage = lazy(() => import('./pages/MapPage'))
const Prices = lazy(() => import('./pages/Prices'))
const Events = lazy(() => import('./pages/Events'))
const Logins = lazy(() => import('./pages/Logins'))
const Chats = lazy(() => import('./pages/Chats'))
const Users = lazy(() => import('./pages/Users'))
const Exclusions = lazy(() => import('./pages/Exclusions'))
const DataPage = lazy(() => import('./pages/Data'))
const Basket = lazy(() => import('./pages/Basket'))
const Loyalty = lazy(() => import('./pages/Loyalty'))
const Audiences = lazy(() => import('./pages/Audiences'))
const Person = lazy(() => import('./pages/Person'))
const SessionPage = lazy(() => import('./pages/SessionPage'))
const Orders = lazy(() => import('./pages/Orders'))
const OrderPage = lazy(() => import('./pages/OrderPage'))
const MetaAds = lazy(() => import('./pages/MetaAds'))
const Dictionary = lazy(() => import('./pages/Dictionary'))

// [key, label, icon, one-line description (tooltip + page subtitle), component, group]
const NAV = [
  ['home', 'Home', 'home', 'What matters right now', Home, ''],
  ['performance', 'Performance', 'chart', 'Traffic, orders and trends over time', Overview, 'Reports'],
  ['orders', 'Orders', 'receipt', 'Every order, payments, delivery and order analytics', Orders, 'Reports'],
  ['funnel', 'Funnel & checkout', 'funnel', 'Where people drop off, who to follow up', Funnel, 'Reports'],
  ['journeys', 'Journeys', 'route', 'Every journey: purchase, checkout, login, quiz, search, Roop and delivery, and each visit', Journeys, 'Reports'],
  ['painpoints', 'Pain points', 'alert', 'What went wrong from login to payment, and who got stuck', PainPoints, 'Reports'],
  ['campaigns', 'Campaigns', 'megaphone', 'Which ads and sources are working', Campaigns, 'Reports'],
  ['meta', 'Meta Ads', 'trend', 'Spend from Meta joined to your orders', MetaAds, 'Reports'],
  ['deeper', 'Ads & landing pages', 'image', 'What the visits each ad and landing product brought did, and ad → skin concern → products', Deeper, 'Reports'],
  ['map', 'Map', 'map', 'Visits, checkouts started and orders on a map, by state, city and pincode', MapPage, 'Reports'],
  ['cohorts', 'Cohorts & geo', 'globe', 'Who your customers are and where from', Cohorts, 'Reports'],
  ['basket', 'Basket & AOV', 'basket', 'What people buy and how to raise order value', Basket, 'Reports'],
  ['prices', 'Price intelligence', 'tag', 'Our prices against Nykaa, Tira and Purplle, and what to reprice', Prices, 'Reports'],
  ['loyalty', 'Retention & LTV', 'loop', 'Who comes back and what they are worth', Loyalty, 'Reports'],
  ['audiences', 'Audiences', 'target', 'Who you can reach, and with what', Audiences, 'Grow'],
  ['sessions', 'Sessions', 'list', 'Every visit, with a full event timeline', Sessions, 'Explore'],
  ['events', 'Events', 'pulse', 'Every tracked event, from event names down to payload fields', Events, 'Explore'],
  ['logins', 'Logins', 'login', 'Every login: who, how, new or returning', Logins, 'Explore'],
  ['chats', 'Roop chats', 'chat', 'What shoppers ask Roop, and what it answers', Chats, 'Explore'],
  ['users', 'Users', 'users', 'People and where they are in the journey', Users, 'Explore'],
  ['exclusions', 'Exclusions', 'ban', 'Remove internal, test and bot traffic', Exclusions, 'Admin'],
  ['data', 'Data & ETL', 'database', 'Refresh data, tracking health', DataPage, 'Admin'],
  ['dictionary', 'Data dictionary', 'book', 'How every number is worked out', Dictionary, 'Admin'],
]
// Detail pages: not in the menu, reached by clicking a person or a session
const EXTRA = [
  ['person', 'Person', 'users', 'Everything about one person', Person, 'Users'],
  ['session', 'Session', 'list', 'Everything about one session', SessionPage, 'Sessions'],
  ['order', 'Order', 'receipt', 'Everything about one order', OrderPage, 'Orders'],
]
function parseHash() {
  const [path, query = ''] = decodeURIComponent(location.hash.slice(1)).split('?')
  const [a, ...rest] = path.split('/')
  if ((a === 'person' || a === 'session' || a === 'order') && rest.length) return { tab: a, prefill: { key: rest.join('/') } }
  const share = decodeShare(new URLSearchParams(query).get('s'))  // a shared link carries the dates and filters
  return { tab: NAV.some((n) => n[0] === a) ? a : 'home', prefill: share ? { share } : {} }
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
  const [hideInternal, setHideInternal] = useState(init.prefill.share?.hide ?? true)
  const [compare, setCompare] = useState(true)
  const [deviceType, setDeviceType] = useState(() => init.prefill.share?.device ?? (() => { try { return sessionStorage.getItem('mi:device') || '' } catch { return '' } })())
  useEffect(() => { try { sessionStorage.setItem('mi:device', deviceType) } catch { /* ignore */ } }, [deviceType])
  const [salesBasis, setSalesBasis] = useState(() => init.prefill.share?.sales ?? (() => { try { return sessionStorage.getItem('mi:sales') || '' } catch { return '' } })())
  useEffect(() => { try { sessionStorage.setItem('mi:sales', salesBasis) } catch { /* ignore */ } }, [salesBasis])
  const [tick, setTick] = useState(0)
  const [hideUpgrade, setHideUpgrade] = useState(false)
  const [theme, setTheme] = useState(() => { const q = new URLSearchParams(location.search).get('theme'); return ['light', 'dark', 'auto'].includes(q) ? q : localStorage.getItem('theme') || 'light' })
  const [collapsed, setCollapsed] = useState(() => { const q = new URLSearchParams(location.search).get('rail'); return q ? q === '1' : localStorage.getItem('rail') === '1' })
  const [menu, setMenu] = useState(false)
  const inited = useRef(false)
  const topbarRef = useRef(null)
  useEffect(() => {  // the sticky bar can wrap on small screens; tables pin their headings just below it
    const el = topbarRef.current
    if (!el) return undefined
    const set = () => document.documentElement.style.setProperty('--topbar-h', `${el.offsetHeight}px`)
    set()
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(set) : null
    ro?.observe(el)
    return () => ro?.disconnect()
  }, [])

  const go = (key, pre = {}) => { setPrefill(pre); setTab(key); setNavKey((k) => k + 1); setMenu(false); window.scrollTo(0, 0) }
  useEffect(() => {
    const h = ['person', 'session', 'order'].includes(tab) && prefill.key ? `${tab}/${prefill.key}` : tab
    lastHash.current = h
    location.hash = ['person', 'session', 'order'].includes(tab) && prefill.key ? `${tab}/${encodeURIComponent(prefill.key)}` : tab
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
  const [clock, setClock] = useState(Date.now())
  const [doneMsg, setDoneMsg] = useState('')
  const startN = useRef(null)
  useEffect(() => { const t = setInterval(() => setClock(Date.now()), 60000); return () => clearInterval(t) }, [])
  useEffect(() => {
    if (!meta?.job?.running) return undefined
    if (startN.current === null) startN.current = meta.raw_events?.n ?? 0
    const t = setInterval(async () => {
      const j = await api('/jobs')
      if (!j.running) {
        clearInterval(t)
        const m = await api('/meta').catch(() => null)
        if (m) {
          setMeta(m)
          const added = (m.raw_events?.n ?? 0) - (startN.current ?? 0)
          if (!j.error) { setDoneMsg(added > 0 ? `Updated: ${added.toLocaleString('en-IN')} new events` : 'Updated: no new events'); setTimeout(() => setDoneMsg(''), 12000) }
        }
        startN.current = null
        setTick((x) => x + 1)
      } else setMeta((m) => ({ ...m, job: j }))
    }, 1500)
    return () => clearInterval(t)
  }, [meta?.job?.running])
  const lastEvent = meta?.raw_events?.last ? new Date(meta.raw_events.last) : null
  const ageH = lastEvent ? (clock - lastEvent.getTime()) / 36e5 : null
  const ageText = ageH == null ? '' : ageH < 1 ? `${Math.max(1, Math.round(ageH * 60))} min ago` : ageH < 48 ? `${Math.round(ageH)} h ago` : `${Math.round(ageH / 24)} days ago`
  const freshTone = ageH == null ? '' : ageH <= 6 ? 'good' : ageH <= 24 ? 'warn' : 'bad'

  const first = meta?.range?.first
  const last = meta?.range?.last
  useEffect(() => {
    if (!last || inited.current) return
    inited.current = true
    const sh = init.prefill.share
    if (sh && 'from' in sh) { setFrom(sh.from || ''); setTo(sh.to || '') } else { setTo(last); setFrom(shift(last, -29)) }
  }, [last])

  const presets = last ? [
    ['Today', last, last], ['Yesterday', shift(last, -1), shift(last, -1)], ['Last 7 days', shift(last, -6), last],
    ['Last 30 days', shift(last, -29), last], ['All time', '', ''],
  ] : []
  const active = presets.find(([, f, t]) => f === from && t === to)?.[0]
  const rangeText = from && to ? (from === to ? fmt(from) : `${fmt(from)} – ${fmt(to)}`) : first ? `${fmt(first)} – ${fmt(last)}` : 'All time'
  const canCompare = !!(from && to)
  const prevText = canCompare ? `${fmt(shift(from, -daysBetween(from, to)))} – ${fmt(shift(from, -1))}` : null
  const cur = [...NAV, ...EXTRA].find((n) => n[0] === tab) || NAV[0]
  const railActive = tab === 'person' ? 'users' : tab === 'session' ? 'sessions' : tab === 'order' ? 'orders' : tab
  const Page = cur[4]
  const dateless = tab === 'loyalty' || tab === 'audiences'
  // pages built on people or campaigns (not on visits) cannot be narrowed by device
  // the pages that show revenue and orders can count only paid sales
  const salesApplies = ['home', 'performance', 'orders', 'basket', 'funnel'].includes(tab)
  const deviceApplies = !['campaigns', 'cohorts', 'users', 'audiences', 'loyalty', 'meta', 'exclusions', 'data', 'dictionary', 'person'].includes(tab)
  const noDates = dateless || ['exclusions', 'data', 'dictionary', 'person', 'session', 'order'].includes(tab)
  const job = meta?.job
  const c = meta?.counts
  const tc = meta?.tracking_change
  useEffect(() => { try { setHideUpgrade(!!tc && localStorage.getItem('mi:hide-upgrade') === tc) } catch { /* ignore */ } }, [tc])
  const prevStart = canCompare ? shift(from, -daysBetween(from, to)) : null
  const crossesUpgrade = !noDates && tc && ((from ? from < tc : first && first < tc) || (compare && prevStart && prevStart < tc))
  const upgradeText = tc ? `Tracking was upgraded on ${fmt(tc)}. Session counts, bounce rate and session length from before that date are not comparable with after it.` : ''

  const ctx = useMemo(() => ({ from, to, includeExcluded: !hideInternal, deviceType, deviceApplies, salesBasis, salesApplies, compare: compare && canCompare, tick, bump: () => setTick((x) => x + 1), meta, reloadMeta: loadMeta, go, prefill, rangeText, prevText }),
    [from, to, hideInternal, deviceType, deviceApplies, salesBasis, salesApplies, compare, canCompare, tick, meta, prefill, rangeText, prevText])
  const changed = (hideInternal ? 0 : 1) + (deviceType && deviceApplies ? 1 : 0) + (salesBasis && salesApplies ? 1 : 0)
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
                  <button type="button" className={`rail-item ${railActive === k ? 'active' : ''}`} onClick={() => { clearPersisted(k); go(k) }} title={`${label} – ${desc}`} aria-current={railActive === k ? 'page' : undefined}>
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
          <header className="topbar2" ref={topbarRef}>
            <button type="button" className="icon-btn menu-btn2" onClick={() => setMenu(!menu)} aria-label="Open menu"><Icon name="menu" /></button>
            <div className="page-title"><h1>{cur[1]}</h1><span className="crumb" title={cur[3]}>{cur[5] ? `${cur[5]} · ` : ''}{cur[3]}</span></div>
            <div style={{ flex: 1 }} />
            {job?.running
              ? <span className="badge warn" role="status">Refreshing: {job.message || 'working'} · {Math.max(0, Math.round((Date.now() - new Date(job.started).getTime()) / 1000))}s</span>
              : lastEvent && <span className={`badge ${freshTone}`} title={`Newest event ${lastEvent.toLocaleString('en-IN')}${meta?.last_transform ? ` · tables rebuilt ${new Date(meta.last_transform).toLocaleString('en-IN')}` : ''}. Press Refresh to pull newer data.`}>Data {ageText}</span>}
            {doneMsg && <span className="badge good" role="status">{doneMsg}</span>}
            {job?.error && <span className="badge bad" title={job.error}>last refresh failed: {String(job.error).slice(0, 60)}</span>}
            {!noDates && (
              <DatePicker presets={presets} active={active} from={from} to={to} rangeText={rangeText} prevText={prevText} compare={compare} setCompare={setCompare}
                setRange={(f, t) => { setFrom(f); setTo(t) }} first={first} last={last} canCompare={canCompare} note={crossesUpgrade ? upgradeText : null} />
            )}
            {crossesUpgrade && !hideUpgrade && (
              <span className="badge info upgrade-chip" title={upgradeText}><Icon name="info" size={14} />Tracking changed {fmt(tc)}
                <button type="button" className="chip-x" aria-label="Hide this note" title="Hide this note" onClick={() => { setHideUpgrade(true); try { localStorage.setItem('mi:hide-upgrade', tc) } catch { /* ignore */ } }}>×</button></span>
            )}
            {!['exclusions', 'data', 'dictionary', 'person', 'session', 'order'].includes(tab) && (
              <Popover align="right" width={320} trigger={({ open, toggle }) => (
                <button type="button" className="pill-btn" aria-expanded={open} onClick={toggle} title="Hidden traffic, devices and which sales count">
                  <Icon name="sliders" size={17} />Filters{changed > 0 ? <span className="count-badge">{changed}</span> : <small>default</small>}<Icon name="chevron" size={16} />
                </button>
              )}>
                {(close) => (
                  <div className="filter-pop">
                    <div className="pop-label">Traffic</div>
                    <label className="row-between" style={{ cursor: 'pointer' }}>
                      <span><b style={{ fontWeight: 500 }}>Hide internal &amp; bot traffic</b><br /><small className="muted">Staff, test, dev and non-India traffic{c ? `: ${num(c.sessions_excluded)} sessions, ${num(c.people_excluded)} people` : ''}</small></span>
                      <span className="switch"><input type="checkbox" checked={hideInternal} onChange={(e) => setHideInternal(e.target.checked)} /><i /></span>
                    </label>
                    <button type="button" className="pop-item" onClick={() => { close(); go('exclusions') }}>Edit exclusion rules<Icon name="right" size={16} /></button>
                    <div className="pop-sep" />
                    <div className="pop-label">Device{!deviceApplies && <small className="muted"> · not used on this page (it counts people or campaigns)</small>}</div>
                    <div className="seg">
                      {DEVICE_OPTIONS.map(([v, label]) => (
                        <button key={v} type="button" className={`chip ${deviceType === v ? 'on' : ''}`} aria-pressed={deviceType === v} disabled={!deviceApplies} onClick={() => setDeviceType(v)}>{label}</button>
                      ))}
                    </div>
                    {salesApplies && (
                      <>
                        <div className="pop-sep" />
                        <div className="pop-label">Sales counted</div>
                        <div className="seg">
                          {SALES_OPTIONS.map(([v, label]) => (
                            <button key={v} type="button" className={`chip ${salesBasis === v ? 'on' : ''}`} aria-pressed={salesBasis === v} onClick={() => setSalesBasis(v)}>{label}</button>
                          ))}
                        </div>
                        <small className="muted">All sales = every valid order when it is placed. Cash on delivery is counted before the cash is collected.</small>
                      </>
                    )}
                    {changed > 0 && <><div className="pop-sep" /><button type="button" className="pop-item" onClick={() => { setHideInternal(true); setDeviceType(''); setSalesBasis('') }}>Reset to default</button></>}
                  </div>
                )}
              </Popover>
            )}
            <button type="button" className="pill-btn" disabled={job?.running} onClick={startRefresh} title="Pull new events from Supabase (read-only) and rebuild everything">
              <Icon name="refresh" size={18} />{job?.running ? 'Updating…' : 'Refresh'}
            </button>
          </header>
          {freshTone === 'bad' && !job?.running && <div className="notice" role="note"><Icon name="info" size={18} />The data is {ageText} old, so recent activity is missing. Press Refresh to pull the latest events.</div>}
          {deviceType && !deviceApplies && !['exclusions', 'data', 'dictionary'].includes(tab) && <div className="notice" role="note"><Icon name="info" size={18} />The device filter does not apply to this page: it is built on people or campaigns, not on single visits.</div>}
          {dateless && <div className="notice" role="note"><Icon name="info" size={18} />All-time view: the date range does not apply to this page.</div>}
          <main className="page" key={navKey}>
            {meta && !meta.ready
              ? <div className="banner err">No analytics tables yet. Run <span className="mono">python3 run.py</span> or press “Refresh”.</div>
              : <Suspense fallback={<div className="skeleton" style={{ height: 320 }} />}><Page /></Suspense>}
          </main>
        </div>
      </div>
    </FilterCtx.Provider>
  )
}

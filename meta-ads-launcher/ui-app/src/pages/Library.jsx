import { useCallback, useEffect, useState } from 'react'
import { api, inr } from '../api'
import { Badge, Banner, Card } from '../ui'

const ago = (t) => {
  if (!t) return 'never'
  const m = Math.max(0, Math.round((Date.now() / 1000 - t) / 60))
  return m < 2 ? 'just now' : m < 90 ? `${m} min ago` : m < 2880 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} days ago`
}
const nice = (s) => (s || '').toLowerCase().replace(/_/g, ' ')
const TABS = [['campaigns', 'Campaigns'], ['adsets', 'Ad sets'], ['ads', 'Ads'], ['media', 'Media'], ['made', 'Made with this launcher']]

/** Your saved copy of past campaigns, ad sets, ads and media. Everything here is read from disk: no calls to Meta except Sync and Refresh. */
export default function Library({ ctx }) {
  const [st, setSt] = useState(null)
  const [tab, setTab] = useState('campaigns')
  const [q, setQ] = useState('')
  const [rows, setRows] = useState(null)
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState(false)

  const loadStatus = useCallback(() => api('/api/library/status').then(setSt).catch((e) => setMsg({ tone: 'err', text: e.message })), [])
  useEffect(() => { loadStatus() }, [loadStatus])
  // while a sync runs, look at its progress every 1.5 s (a read of local state, not a call to Meta)
  useEffect(() => {
    if (!st?.sync?.running) return undefined
    const t = setInterval(loadStatus, 1500)
    return () => clearInterval(t)
  }, [st?.sync?.running, loadStatus])
  const wasRunning = st?.sync?.running
  useEffect(() => { if (st && !wasRunning) load() }, [wasRunning, tab]) // eslint-disable-line react-hooks/exhaustive-deps

  const load = useCallback(async () => {
    setRows(null)
    try {
      if (tab === 'made') setRows((await api('/api/history')).filter((h) => h.answers))
      else setRows((await api(`/api/library/items?kind=${tab}&q=${encodeURIComponent(q)}`)).items)
    } catch (e) { setMsg({ tone: 'err', text: e.message }) }
  }, [tab, q])
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t) }, [q]) // eslint-disable-line react-hooks/exhaustive-deps

  const sync = async () => {
    setMsg(null)
    try { await api('/api/library/sync', { method: 'POST' }); loadStatus() } catch (e) { setMsg({ tone: 'err', text: e.message }) }
  }
  const refresh = async (id) => {
    setBusy(id); setMsg(null)
    try { await api(`/api/library/refresh/${id}`, { method: 'POST' }); await loadStatus(); await load(); setMsg({ tone: 'good', text: 'Refreshed from Meta.' }) } catch (e) { setMsg({ tone: 'err', text: e.message }) }
    setBusy(false)
  }
  const drop = async (id) => {
    if (!window.confirm('Remove the local copy of this campaign? Nothing changes on Meta.')) return
    await api(`/api/library/campaigns/${id}`, { method: 'DELETE' }); await loadStatus(); load()
  }
  const clearAll = async () => {
    if (!window.confirm('Remove the whole local library for this account (campaigns, ad sets, ads and saved images)? Nothing changes on Meta. You can sync again any time.')) return
    await api('/api/library/clear', { method: 'POST' }); await loadStatus(); load()
  }
  // a campaign made with this launcher: copy its answers into a new draft, with fresh names and IDs
  const dupMade = async (h) => {
    const a = JSON.parse(JSON.stringify(h.answers))
    a.campaign = { ...(a.campaign || {}), name: '' }
    a.adsets = (a.adsets || []).map((s) => ({ ...s, name: '' }))
    a.ads = (a.ads || []).map((ad) => ({ ...ad, ad_key: '' }))
    const r = await api('/api/drafts/new', { method: 'PUT', body: { title: `Copy of ${h.campaign}`, answers: a } })
    ctx.go('new', { draft: r.id })
  }

  const running = st?.sync?.running
  const counts = st?.counts || {}
  return (
    <div className="stack">
      <Card title="Your local library" sub="A saved copy of this ad account's campaigns, ad sets, ads and images, so duplicating needs no waiting and no calls to Meta."
        right={st?.synced ? <Badge tone={st.stale ? 'warn' : 'good'}>{st.stale ? 'Possibly out of date' : 'Up to date'}</Badge> : <Badge>Not synced yet</Badge>}>
        {st && (
          <div className="lib-stats">
            <div><b>{st.synced ? ago(st.synced_at) : 'never'}</b><span>last synced</span></div>
            <div><b>{counts.campaigns ?? 0}</b><span>campaigns</span></div>
            <div><b>{counts.adsets ?? 0}</b><span>ad sets</span></div>
            <div><b>{counts.ads ?? 0}</b><span>ads</span></div>
            <div><b>{st.images}</b><span>images ({st.images_full} in full size)</span></div>
            <div><b>{st.videos}</b><span>videos (details and cover)</span></div>
            <div><b>{st.megabytes} MB</b><span>on this computer</span></div>
          </div>
        )}
        <div className="row" style={{ marginTop: 12 }}>
          <button type="button" className="btn primary" disabled={running} onClick={sync}>{running ? 'Syncing…' : st?.synced ? 'Sync from Meta' : 'Sync your account now'}</button>
          {st?.synced && <button type="button" className="btn small danger" disabled={running} onClick={clearAll}>Remove the local copy</button>}
          <span className="muted" style={{ fontSize: 12.5 }}>A full sync takes a handful of calls to Meta. It only reads; nothing on Meta is changed.</span>
        </div>
        {running && (
          <div style={{ marginTop: 10 }}>
            <div className="mini">{st.sync.phase}{st.sync.total ? ` · ${st.sync.done} of ${st.sync.total}` : ''}</div>
            <div className="bar"><i style={{ width: `${st.sync.total ? Math.round((100 * st.sync.done) / st.sync.total) : 8}%` }} /></div>
          </div>
        )}
        {!running && st?.sync?.finished > 0 && !st.sync.error && <div className="mini" style={{ marginTop: 8 }}>Last sync used {st.sync.calls_used} call(s) to Meta{st.sync.note ? ` (${st.sync.note})` : ''}.</div>}
        {st?.sync?.error && <Banner tone="err">{st.sync.error}</Banner>}
        {st?.stale && <Banner>The copy is more than a week old, so it may differ from what is on Meta now. Sync again, or refresh a single campaign.</Banner>}
        {msg && <Banner tone={msg.tone}>{msg.text}</Banner>}
      </Card>

      {!st?.synced && tab !== 'made' && (
        <Card title="Start by syncing">
          <div className="sub">Press <b>Sync your account now</b> above. It reads your campaigns, ad sets, ads and images once and saves them here. After that you can duplicate any of them, with its images, without waiting on Meta.</div>
        </Card>
      )}

      <Card>
        <div className="row" style={{ marginBottom: 10 }}>
          <div className="stabs" role="tablist">{TABS.map(([k, l]) => <button type="button" key={k} role="tab" aria-selected={tab === k} className={`stab ${tab === k ? 'on' : ''}`} onClick={() => { setTab(k); setRows(null) }}>{l}</button>)}</div>
          {tab !== 'made' && <input className="field right" style={{ maxWidth: 280 }} placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} />}
        </div>

        {rows === null && <div className="muted">Loading…</div>}
        {rows && rows.length === 0 && <div className="empty">{tab === 'made' ? 'Nothing made with this launcher yet.' : st?.synced ? 'Nothing matches.' : 'Nothing saved yet. Sync your account first.'}</div>}

        {tab === 'campaigns' && rows?.map((c) => (
          <div key={c.id} className="list-row">
            <span className="grow"><b>{c.name}</b><br /><span className="muted">{nice(c.objective)} · {c.adsets} ad set(s) · {c.ads} ad(s){c.daily_budget ? ` · ${inr(c.daily_budget / 100)}/day` : ''} · saved {ago(c.synced_at)}</span></span>
            <Badge>{nice(c.status)}</Badge>
            <button type="button" className="btn small primary" onClick={() => ctx.go('new', { dup: c.id })}>Duplicate</button>
            <button type="button" className="btn small" disabled={busy === c.id} onClick={() => refresh(c.id)} title="Read this one campaign again from Meta (3 calls)">{busy === c.id ? 'Refreshing…' : 'Refresh'}</button>
            <button type="button" className="btn small danger" onClick={() => drop(c.id)}>Remove</button>
          </div>
        ))}

        {tab === 'adsets' && rows?.map((a) => (
          <div key={a.id} className="list-row">
            <span className="grow"><b>{a.name}</b><br /><span className="muted">{a.campaign} · {nice(a.goal)}</span></span>
            <Badge>{nice(a.status)}</Badge>
            <button type="button" className="btn small primary" onClick={() => ctx.go('new', { dupset: a.id })}>Use in a new campaign</button>
          </div>
        ))}

        {tab === 'ads' && rows?.map((a) => (
          <div key={a.id} className="list-row">
            {a.thumb ? <img className="lib-thumb" src={a.thumb} alt="" loading="lazy" /> : <div className="lib-thumb none">{a.type}</div>}
            <span className="grow"><b>{a.name}</b><br /><span className="muted">{a.type} · {a.campaign}{a.adset ? ' › ' + a.adset : ''}</span>{a.text && <div className="mini">{a.text}</div>}</span>
            <Badge>{nice(a.status)}</Badge>
            <button type="button" className="btn small primary" onClick={() => ctx.go('new', { dupad: a.id })}>Use in a new campaign</button>
          </div>
        ))}

        {tab === 'media' && rows && rows.length > 0 && (
          <div className="thumbs">
            {rows.map((m) => (
              <div key={m.kind + m.id} className="thumb">
                {m.thumb ? <img src={m.thumb} alt="" loading="lazy" /> : <div className="noimg">no preview saved</div>}
                <div><b>{m.name || m.id.slice(0, 10)}</b>
                  <span className="muted">{m.kind === 'video' ? `video${m.length ? ` · ${Math.round(m.length)} s` : ''}` : `${m.width || '?'}×${m.height || '?'}`}</span>
                  {m.kind === 'image' && (m.full ? <Badge tone="good">full size saved</Badge> : <Badge>preview only</Badge>)}
                  {m.kind === 'image' && <button type="button" className="btn small" onClick={() => ctx.go('new', { metahash: m.id })}>Use in a campaign</button>}
                </div>
              </div>
            ))}
          </div>
        )}

        {tab === 'made' && rows?.map((h) => (
          <div key={h.batch} className="list-row">
            <span className="grow"><b>{h.campaign}</b><br /><span className="muted">{h.goal} · {inr(h.budget)}/day · {h.adsets || 1} ad set(s) · {h.ads} ad(s) · {(h.created || '').slice(0, 10)}</span></span>
            <button type="button" className="btn small primary" onClick={() => dupMade(h)}>Duplicate</button>
          </div>
        ))}
      </Card>
    </div>
  )
}

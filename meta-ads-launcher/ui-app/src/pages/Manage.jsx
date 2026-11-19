import { useEffect, useMemo, useState } from 'react'
import { api, followJob, inr } from '../api'
import { Badge, Banner, Card, JobPanel, Loading, useLoad } from '../ui'
import { AdSetCard, ImportModal, newSet } from './Builder'
import { Step4 } from './Wizard'
import FormatCard, { KIND_INFO, newFormatAd } from './Formats'

const nice = (s) => (s || '').toLowerCase().replace(/_/g, ' ')
const tone = (st) => (/DISAPPROVED|WITH_ISSUES/.test(st || '') ? 'bad' : /^ACTIVE$/.test(st || '') ? 'good' : /PAUSED|ARCHIVED|DELETED/.test(st || '') ? '' : 'warn')
const budget = (x) => (x.daily_budget ? `${inr(x.daily_budget)}/day` : x.lifetime_budget ? `${inr(x.lifetime_budget)} total` : '')

/** Edit the ad sets of campaigns that already exist, add new creatives to them, change the creative of an ad, pause or turn on.
 *  Every change shows before and after, can be tested by Meta first, is logged, and can be undone. */
export default function Manage({ ctx, params }) {
  const [opts] = useLoad(() => api('/api/wizard/options'))
  return <Loading state={opts}>{(o) => (params.campaign ? <CampaignView id={params.campaign} o={o} ctx={ctx} /> : <Pick ctx={ctx} />)}</Loading>
}

function Pick({ ctx }) {
  const [rows, setRows] = useState(null)
  const [q, setQ] = useState('')
  const [err, setErr] = useState(null)
  useEffect(() => { api('/api/library/items?kind=campaigns').then((r) => setRows(r.items)).catch((e) => setErr(e.message)) }, [])
  const list = (rows || []).filter((c) => !q.trim() || (c.name || '').toLowerCase().includes(q.trim().toLowerCase()))
  return (
    <div className="stack">
      <Card title="Edit a live campaign" sub="Pick a campaign. It is read live from Meta before anything is shown, so you always edit what is really there.">
        {err && <Banner tone="err">{err}</Banner>}
        <input className="field" placeholder="Search campaigns…" value={q} onChange={(e) => setQ(e.target.value)} style={{ maxWidth: 320, marginBottom: 8 }} />
        {rows === null && <div className="muted">Loading…</div>}
        {rows && rows.length === 0 && <div className="empty">Nothing saved yet. Open <b>Past campaigns</b> and press Sync first.</div>}
        {list.map((c) => (
          <div key={c.id} className="list-row">
            <span className="grow"><b>{c.name}</b><br /><span className="muted">{nice(c.objective)} · {c.adsets} ad set(s) · {c.ads} ad(s)</span></span>
            <Badge tone={tone(c.status)}>{nice(c.status)}</Badge>
            <button type="button" className="btn small primary" onClick={() => ctx.go('manage', { campaign: c.id })}>Open</button>
          </div>
        ))}
      </Card>
      <ChangeLog />
    </div>
  )
}

function CampaignView({ id, o, ctx }) {
  const [d, setD] = useState(null)
  const [err, setErr] = useState(null)
  const [panel, setPanel] = useState(null) // { type: 'edit' | 'add' | 'replace', adset, ad }
  const [msg, setMsg] = useState(null)
  const [tick, setTick] = useState(0)
  useEffect(() => { setD(null); setPanel(null) }, [id])
  useEffect(() => { setErr(null); api(`/api/manage/campaign/${id}`).then(setD).catch((e) => setErr(e.message)) }, [id, tick])  // (a refresh keeps what is on screen, so an open editor and its Undo button stay)
  const reload = () => setTick((t) => t + 1)
  const env = d?.env
  const setStatus = async (kind, oid, status, name) => {
    const body = { kind, id: oid, status }
    if (env === 'production') {
      if (!window.confirm(`This changes your real ad account: ${status === 'ACTIVE' ? 'turn on' : 'pause'} "${name}"?`)) return
      body.confirm_production = true
      if (status === 'ACTIVE') { const t = window.prompt('This can spend money. Type TURN ON to confirm'); if (!t) return; body.typed = t }
    }
    try { await api('/api/manage/status', { method: 'POST', body }); setMsg({ tone: 'good', text: `${name}: ${status === 'ACTIVE' ? 'turned on' : 'paused'}.` }); reload() } catch (e) { setMsg({ tone: 'err', text: e.message }) }
  }
  if (err) return <div className="stack"><Banner tone="err">{err}</Banner><button type="button" className="btn" onClick={() => ctx.go('manage')}>Back to the list</button></div>
  if (!d) return <div className="muted">Reading the campaign from Meta…</div>
  return (
    <div className="stack">
      <Card title={d.campaign.name} sub={`${nice(d.campaign.objective)} · ${budget(d.campaign) || 'budget on each ad set'} · read live from Meta just now`}
        right={<><Badge tone={tone(d.campaign.status)}>{nice(d.campaign.status)}</Badge><button type="button" className="btn small" onClick={reload}>Refresh</button><button type="button" className="btn small" onClick={() => ctx.go('manage')}>All campaigns</button></>}>
        {msg && <Banner tone={msg.tone}>{msg.text}</Banner>}
        {d.adsets.length === 0 && <div className="empty">This campaign has no ad sets.</div>}
        {d.adsets.map((a) => (
          <div key={a.id} className="mset">
            <div className="row">
              <span className="grow"><b>{a.name}</b><br /><span className="muted">{nice(a.goal)}{budget(a) ? ' · ' + budget(a) : ''} · {a.ads.length} ad(s)</span></span>
              <Badge tone={tone(a.status)}>{nice(a.status)}</Badge>
              <button type="button" className="btn small primary" onClick={() => setPanel({ type: 'edit', adset: a.id })}>Edit settings</button>
              <button type="button" className="btn small" onClick={() => setPanel({ type: 'add', adset: a.id })}>Add creatives</button>
              {a.status === 'PAUSED' || /PAUSED/.test(a.status || '') ? <button type="button" className="btn small" onClick={() => setStatus('adset', a.id, 'ACTIVE', a.name)}>Turn on</button>
                : <button type="button" className="btn small" onClick={() => setStatus('adset', a.id, 'PAUSED', a.name)}>Pause</button>}
            </div>
            {a.ads.map((ad) => (
              <div key={ad.id} className="list-row mad">
                {ad.thumb ? <img className="lib-thumb" src={ad.thumb} alt="" loading="lazy" /> : <div className="lib-thumb none">{ad.type}</div>}
                <span className="grow"><b>{ad.name}</b><br /><span className="muted">{ad.type}{ad.text ? ' · ' + ad.text : ''}</span></span>
                <Badge tone={tone(ad.status)}>{nice(ad.status)}</Badge>
                <button type="button" className="btn small" onClick={() => setPanel({ type: 'replace', adset: a.id, ad: ad.id })}>Change creative</button>
                {/PAUSED/.test(ad.status || '') ? <button type="button" className="btn small" onClick={() => setStatus('ad', ad.id, 'ACTIVE', ad.name)}>Turn on</button>
                  : <button type="button" className="btn small" onClick={() => setStatus('ad', ad.id, 'PAUSED', ad.name)}>Pause</button>}
              </div>
            ))}
          </div>
        ))}
      </Card>
      <ChangeLog key={tick} />
      {panel?.type === 'edit' && <EditAdSet id={panel.adset} o={o} env={env} onClose={() => setPanel(null)} onDone={reload} />}
      {panel?.type === 'add' && <AddCreatives adsets={d.adsets} startId={panel.adset} o={o} env={env} onClose={() => setPanel(null)} onDone={reload} />}
      {panel?.type === 'replace' && <ReplaceCreative ad={d.adsets.flatMap((a) => a.ads).find((x) => x.id === panel.ad)} adset={d.adsets.find((a) => a.id === panel.adset)} o={o} env={env} onClose={() => setPanel(null)} onDone={reload} />}
    </div>
  )
}

/** The tick (and the typed word when money could be spent) that production asks for. */
function Confirm({ env, spends, tick, setTick, typed, setTyped }) {
  if (env !== 'production') return <div className="mini">You are on the sandbox: nothing real is changed.</div>
  return (
    <div className="stack" style={{ marginTop: 8 }}>
      <label className="chk"><input type="checkbox" checked={tick} onChange={(e) => setTick(e.target.checked)} /><b>I understand this changes the real ad account</b></label>
      {spends && <label className="lf"><span className="lf-label">This can spend money. Type <b>TURN ON</b> to confirm</span><input className="field" style={{ maxWidth: 200 }} value={typed} onChange={(e) => setTyped(e.target.value)} /></label>}
    </div>
  )
}

function Modal({ title, onClose, children }) {
  useEffect(() => { const on = (e) => { if (e.key === 'Escape') onClose() }; window.addEventListener('keydown', on); return () => window.removeEventListener('keydown', on) }, [onClose])
  return (
    <div className="lb-bg" onClick={onClose} role="dialog" aria-modal="true" aria-label={title}>
      <div className="modal wide" onClick={(e) => e.stopPropagation()}>
        <div className="row"><h3 className="grow">{title}</h3><button type="button" className="btn small" onClick={onClose}>Close</button></div>
        {children}
      </div>
    </div>
  )
}

function Changes({ pv }) {
  if (!pv) return null
  return (
    <div className="stack" style={{ marginTop: 10 }}>
      {pv.errors?.length > 0 && <Banner tone="err"><b>Fix these first</b>{pv.errors.map((e, i) => <div key={i}>• {e}</div>)}</Banner>}
      {pv.nothing && !pv.errors?.length && <Banner>Nothing is different from what is on Meta.</Banner>}
      {pv.changes?.length > 0 && (
        <div className="xnotice"><div className="xn-head"><b>What will change</b></div>
          {pv.changes.map((c, i) => <div key={i} className="xn-row"><span className="xn-where">{c.what}</span><span className="xn-what">{c.before ? <><span className="muted">{c.before} → </span><b>{c.after}</b></> : <b>{c.after}</b>}</span></div>)}
        </div>
      )}
      {pv.risks?.length > 0 && <Banner>{pv.risks.map((r, i) => <div key={i}>• {r}</div>)}</Banner>}
      {pv.warnings?.length > 0 && <Banner>{pv.warnings.map((r, i) => <div key={i}>• {r}</div>)}</Banner>}
    </div>
  )
}

function EditAdSet({ id, o, env, onClose, onDone }) {
  const [d, setD] = useState(null)
  const [base, setBase] = useState(null)
  const [form, setForm] = useState(null)
  const [pv, setPv] = useState(null)
  const [res, setRes] = useState(null)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const [tick, setTick] = useState(false)
  const [typed, setTyped] = useState('')
  useEffect(() => { api(`/api/manage/adset/${id}`).then((r) => { setD(r); setBase(r.form); setForm(newSet({ ...r.form, imported: true, rev: 1 })) }).catch((e) => setErr(e.message)) }, [id])
  const upd = (p) => { setForm((f) => ({ ...f, ...p })); setPv(null); setRes(null) }
  const call = async (path, extra, set) => {
    setBusy(true); setErr(null)
    try { set(await api(path, { method: 'POST', body: { base, form, confirm_production: tick, typed, ...extra } })) } catch (e) { setErr(e.message) }
    setBusy(false)
  }
  const undo = async () => { try { await api(`/api/manage/undo/${res.log_id}`, { method: 'POST', body: { confirm_production: tick, typed } }); setRes({ undone: true }); onDone() } catch (e) { setErr(e.message) } }
  return (
    <Modal title={d ? `Edit the ad set “${d.form.name}”` : 'Edit the ad set'} onClose={onClose}>
      {err && <Banner tone="err">{err}</Banner>}
      {!form && !err && <div className="muted">Reading the ad set from Meta…</div>}
      {form && d && (
        <>
          <div className="sub">Now {nice(d.status)}. {d.campaign.shared_budget ? 'The campaign shares one budget, so the budget is changed on the campaign.' : ''} Change what you need. Nothing is sent until you press Apply.</div>
          <AdSetCard o={o} s={form} i={0} many={false} per={!d.campaign.shared_budget} upd={upd} manage />
          <div className="row" style={{ marginTop: 10 }}>
            <button type="button" className="btn" disabled={busy} onClick={() => call(`/api/manage/adset/${id}/preview`, {}, setPv)}>Show what will change</button>
            <button type="button" className="btn" disabled={busy || !pv || pv.errors?.length || pv.nothing} onClick={() => call(`/api/manage/adset/${id}/apply`, { check_only: true }, setRes)}>Check with Meta</button>
            <button type="button" className="btn primary" disabled={busy || !pv || pv.errors?.length || pv.nothing || res?.applied} onClick={() => call(`/api/manage/adset/${id}/apply`, {}, (r) => { setRes(r); if (r.applied) onDone() })}>Apply the change</button>
          </div>
          <Changes pv={pv} />
          {pv && !pv.nothing && !pv.errors?.length && <Confirm env={env} spends={pv.spend_up} tick={tick} setTick={setTick} typed={typed} setTyped={setTyped} />}
          {res?.checked && <Banner tone="ok">{res.message}</Banner>}
          {res?.applied && <Banner tone="ok"><b>Applied.</b> {res.verified ? 'Meta confirms the new values.' : `Applied, but Meta did not show: ${(res.not_confirmed || []).join(', ')}.`} <button type="button" className="btn small" onClick={undo}>Undo this change</button></Banner>}
          {res?.undone && <Banner tone="ok">Undone. The ad set is back as it was.</Banner>}
        </>
      )}
    </Modal>
  )
}

/** The ad builder, for the ads that will go into existing ad sets (the same cards as when building a new campaign). */
function AdsBuilder({ o, a, setA }) {
  const [modal, setModal] = useState(false)
  const set = (k, v) => setA((x) => ({ ...x, [k]: v }))
  const addFormat = async (kind) => { const key = (await api('/api/next-key?theme=' + encodeURIComponent(kind))).key; setA((x) => ({ ...x, ads: [...x.ads, newFormatAd(kind, key, o)] })) }
  return (
    <div className="stack">
      <div className="row"><button type="button" className="btn small" onClick={() => setModal(true)}>Import, duplicate or use a template</button></div>
      <div className="choices">{Object.entries(KIND_INFO).map(([k, v]) => <button type="button" key={k} className="choice" onClick={() => addFormat(k)}><b>{v.label}</b><span>{v.help}</span></button>)}</div>
      <Step4 o={o} a={a} setA={setA} set={set} noPreview saveTpl={null}
        renderKind={(ad, i, h) => <FormatCard key={ad.ad_key + i} ad={ad} i={i} a={a} o={o} all={h.all} upd={h.upd} toggleSet={h.toggleSet} remove={h.remove} onSave={() => {}} />} />
      {modal && <ImportModal kind="ad" onClose={() => setModal(false)} onApply={(list, mode) => { setA((x) => ({ ...x, ads: [...(mode === 'replace' ? [] : x.ads), ...list.map(({ sets, ...rest }) => ({ ...rest, sets: null }))] })); setModal(false) }} />}
    </div>
  )
}

const blankAds = (o) => ({ defaults: { primary_text: '', headline: '', cta: 'LEARN_MORE', destination: o.destinations?.[0]?.url || '', description: '' }, ads: [] })

function useJob() {
  const [job, setJob] = useState(null)
  const run = async (jobId) => { const j = await followJob(jobId, setJob); return j }
  return [job, run]
}

function AddCreatives({ adsets, startId, o, env, onClose, onDone }) {
  const [targets, setTargets] = useState([startId])
  const [a, setA] = useState(() => blankAds(o))
  const [pv, setPv] = useState(null)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const [tick, setTick] = useState(false)
  const [typed, setTyped] = useState('')
  const [turnOn, setTurnOn] = useState(false)
  const [job, follow] = useJob()
  const [done, setDone] = useState(false)
  const stubs = useMemo(() => adsets.filter((x) => targets.includes(x.id)).map((x) => ({ uid: x.id, audience: 'custom', custom: { countries: x.name }, placements: 'automatic', label: x.name })), [adsets, targets])
  const view = { ...a, adsets: stubs }
  const body = () => ({ adset_ids: targets, ads: a.ads.map((ad) => ({ ...ad, sets: ad.sets && ad.sets.length < stubs.length ? ad.sets : null })), confirm_production: tick, typed, turn_on: turnOn })
  const preview = async () => { setBusy(true); setErr(null); try { setPv(await api('/api/manage/ads/preview', { method: 'POST', body: body() })) } catch (e) { setErr(e.message) } setBusy(false) }
  const apply = async () => {
    setBusy(true); setErr(null)
    try { const r = await api('/api/manage/ads/apply', { method: 'POST', body: body() }); const j = await follow(r.job); setDone(j.ok !== false); if (j.ok === false) setErr('Some ads were not created. The log below says why; pressing Apply again continues where it stopped.'); onDone() } catch (e) { setErr(e.message) }
    setBusy(false)
  }
  return (
    <Modal title="Add new creatives to existing ad sets" onClose={onClose}>
      <div className="lf-label">Add them to</div>
      <div className="row" style={{ gap: 14, flexWrap: 'wrap' }}>{adsets.map((x) => <label key={x.id} className="chk"><input type="checkbox" checked={targets.includes(x.id)} onChange={() => setTargets((t) => (t.includes(x.id) ? t.filter((i) => i !== x.id) : [...t, x.id]))} />{x.name}</label>)}</div>
      <div className="sub" style={{ margin: '8px 0' }}>New ads are created <b>paused</b>. They start delivering only when you turn them on.</div>
      <AdsBuilder o={o} a={view} setA={(fn) => setA((x) => { const next = typeof fn === 'function' ? fn({ ...x, adsets: stubs }) : fn; const { adsets: _drop, ...rest } = next; return rest })} />
      {err && <Banner tone="err">{err}</Banner>}
      <div className="row" style={{ marginTop: 12 }}>
        <button type="button" className="btn" disabled={busy || !a.ads.length || !targets.length} onClick={preview}>Check these ads</button>
        <button type="button" className="btn primary" disabled={busy || !pv || pv.errors?.length || done} onClick={apply}>{turnOn ? 'Add the ads and turn them on' : 'Add the ads (paused)'}</button>
      </div>
      {pv && (
        <div className="stack" style={{ marginTop: 10 }}>
          {pv.errors?.length > 0 && <Banner tone="err"><b>Fix these first</b>{pv.errors.map((e, i) => <div key={i}>• {e}</div>)}</Banner>}
          {!pv.errors?.length && <Banner tone="ok">{pv.ads.length} ad(s) ready: {pv.ads.map((x) => `${x.name} → ${x.adset}`).join('; ')}</Banner>}
          {pv.fixes?.length > 0 && <Banner><b>Fixed for you</b>{pv.fixes.map((e, i) => <div key={i}>• {e}</div>)}</Banner>}
          {pv.warnings?.length > 0 && <Banner>{pv.warnings.map((e, i) => <div key={i}>• {e}</div>)}</Banner>}
        </div>
      )}
      <label className="chk" style={{ marginTop: 8 }}><input type="checkbox" checked={turnOn} onChange={(e) => setTurnOn(e.target.checked)} />Turn the new ads on right away <span className="muted">(they start spending)</span></label>
      <Confirm env={env} spends={turnOn} tick={tick} setTick={setTick} typed={typed} setTyped={setTyped} />
      {job && <JobPanel job={job} />}
      {done && <Banner tone="ok">Done. The new ads are on Meta{turnOn ? '' : ', paused'}.</Banner>}
    </Modal>
  )
}

function ReplaceCreative({ ad, adset, o, env, onClose, onDone }) {
  const [mode, setMode] = useState('new_ad')
  const [switchOver, setSwitchOver] = useState(false)
  const [a, setA] = useState(() => blankAds(o))
  const [pv, setPv] = useState(null)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const [tick, setTick] = useState(false)
  const [typed, setTyped] = useState('')
  const [job, follow] = useJob()
  const [done, setDone] = useState(false)
  const view = { ...a, adsets: [{ uid: adset.id, audience: 'custom', custom: { countries: adset.name }, placements: 'automatic', label: adset.name }] }
  const body = () => ({ ad_id: ad.id, mode, ad: { ...a.ads[0], sets: null }, switch_over: switchOver, confirm_production: tick, typed })
  const preview = async () => { setBusy(true); setErr(null); try { setPv(await api('/api/manage/ad/preview', { method: 'POST', body: body() })) } catch (e) { setErr(e.message) } setBusy(false) }
  const apply = async () => {
    setBusy(true); setErr(null)
    try { const r = await api('/api/manage/ad/apply', { method: 'POST', body: body() }); const j = await follow(r.job); setDone(j.ok !== false); if (j.ok === false) setErr('It did not finish. The log below says why.'); onDone() } catch (e) { setErr(e.message) }
    setBusy(false)
  }
  const spends = switchOver || (mode === 'in_place' && /^ACTIVE$/.test(ad.status || ''))
  return (
    <Modal title={`Change the creative of “${ad.name}”`} onClose={onClose}>
      <div className="stack">
        <label className="chk"><input type="radio" checked={mode === 'new_ad'} onChange={() => setMode('new_ad')} /><span><b>Add a new ad and keep the old one</b> <span className="muted">(recommended: the old ad and its results are untouched)</span></span></label>
        {mode === 'new_ad' && <label className="chk" style={{ marginLeft: 24 }}><input type="checkbox" checked={switchOver} onChange={(e) => setSwitchOver(e.target.checked)} />Turn the new ad on and pause the old one <span className="muted">(otherwise the new ad is created paused)</span></label>}
        <label className="chk"><input type="radio" checked={mode === 'in_place'} onChange={() => setMode('in_place')} /><span><b>Replace the creative of this ad</b> <span className="muted">(the ad keeps its ID but goes back into Meta's review; the old creative is kept, so this can be undone)</span></span></label>
      </div>
      <div className="lf-label" style={{ marginTop: 12 }}>The new creative (build exactly one ad)</div>
      <AdsBuilder o={o} a={view} setA={(fn) => setA((x) => { const next = typeof fn === 'function' ? fn({ ...x, adsets: view.adsets }) : fn; const { adsets: _drop, ...rest } = next; return rest })} />
      {err && <Banner tone="err">{err}</Banner>}
      <div className="row" style={{ marginTop: 12 }}>
        <button type="button" className="btn" disabled={busy || a.ads.length !== 1} onClick={preview}>Check this creative</button>
        <button type="button" className="btn primary" disabled={busy || !pv || pv.errors?.length || done} onClick={apply}>{mode === 'new_ad' ? (switchOver ? 'Add it, turn it on, pause the old one' : 'Add the new ad (paused)') : 'Replace the creative'}</button>
      </div>
      {a.ads.length > 1 && <Banner>Build exactly one ad here. Remove the extra ones.</Banner>}
      {pv && (
        <div className="stack" style={{ marginTop: 10 }}>
          {pv.errors?.length > 0 && <Banner tone="err"><b>Fix these first</b>{pv.errors.map((e, i) => <div key={i}>• {e}</div>)}</Banner>}
          {!pv.errors?.length && <Banner tone="ok">Ready. Old ad: {pv.old.name} ({pv.old.type}, {nice(pv.old.status)}).</Banner>}
          {pv.fixes?.length > 0 && <Banner><b>Fixed for you</b>{pv.fixes.map((e, i) => <div key={i}>• {e}</div>)}</Banner>}
          {pv.warnings?.length > 0 && <Banner>{pv.warnings.map((e, i) => <div key={i}>• {e}</div>)}</Banner>}
        </div>
      )}
      <Confirm env={env} spends={spends} tick={tick} setTick={setTick} typed={typed} setTyped={setTyped} />
      {job && <JobPanel job={job} />}
      {done && <Banner tone="ok">Done.</Banner>}
    </Modal>
  )
}

function ChangeLog() {
  const [rows, setRows] = useState(null)
  const [msg, setMsg] = useState(null)
  const [n, setN] = useState(0)
  useEffect(() => { api('/api/manage/log').then((r) => setRows(r)).catch(() => setRows({ changes: [] })) }, [n])
  const undo = async (e) => {
    const body = {}
    if (rows.env === 'production') {
      if (!window.confirm(`Undo this change on your real ad account?\n${e.note}`)) return
      body.confirm_production = true
      if (e.kind === 'status' && e.before?.status === 'ACTIVE') { const t = window.prompt('This can spend money. Type TURN ON to confirm'); if (!t) return; body.typed = t }
    }
    try { const r = await api(`/api/manage/undo/${e.id}`, { method: 'POST', body }); setMsg({ tone: 'good', text: 'Undone. ' + (r.note || '') }); setN((x) => x + 1) } catch (x) { setMsg({ tone: 'err', text: x.message }) }
  }
  return (
    <Card title="Changes made here" sub="Every change is recorded with what it replaced. The newest is first.">
      {msg && <Banner tone={msg.tone}>{msg.text}</Banner>}
      {rows && rows.changes.length === 0 && <div className="muted">No changes yet.</div>}
      {(rows?.changes || []).slice(0, 12).map((e) => (
        <div key={e.id} className="list-row">
          <span className="grow"><b>{e.name || e.object_id}</b> <span className="muted">· {nice(e.kind)} · {(e.ts || '').replace('T', ' ').slice(0, 16)}</span><br /><span className="muted">{e.note}</span></span>
          {e.undone ? <Badge>undone</Badge> : e.kind === 'undo' ? null : <button type="button" className="btn small" onClick={() => undo(e)}>Undo</button>}
        </div>
      ))}
    </Card>
  )
}

import { useEffect, useRef, useState } from 'react'
import Icon from '../Icon'
import { api, followJob, inr } from '../api'
import { Badge, Banner, Card, Field, Loading, useLoad } from '../ui'
import { downloadJson, exportAdSets, exportAd, exportCampaign } from '../jsonio'
import { FeedPreview, Progress, Step4, audLabel, placeLabel, uid } from './Wizard'
import TargetingEditor from './Targeting'
import FormatCard, { KIND_INFO, newFormatAd } from './Formats'

const EVENTS = [['', 'Default for the goal'], ['PURCHASE', 'Purchase'], ['INITIATE_CHECKOUT', 'Started checkout'], ['ADD_TO_CART', 'Added to cart'], ['LEAD', 'Lead'], ['COMPLETE_REGISTRATION', 'Registration'], ['VIEW_CONTENT', 'Viewed content']]
const SPECIAL = [['EMPLOYMENT', 'Jobs'], ['HOUSING', 'Housing'], ['ISSUES_ELECTIONS_POLITICS', 'Social issues, elections or politics'], ['ONLINE_GAMBLING_AND_GAMING', 'Online gambling and gaming'], ['FINANCIAL_PRODUCTS_SERVICES', 'Financial products and services']]
const ROAS = 'LOWEST_COST_WITH_MIN_ROAS'
const CAPPED = ['LOWEST_COST_WITH_BID_CAP', 'COST_CAP']
const CONVERSION = ['OFFSITE_CONVERSIONS', 'VALUE']

const newSet = (x = {}) => ({
  uid: uid(), audience: 'all', custom: { countries: 'IN', age_min: 18, age_max: 45, gender: 'all' }, placements: 'instagram', daily_budget: 500, lifetime_budget: '', goal: '', event: '',
  bid_strategy: '', bid_amount: '', roas: '', billing_event: '', destination_type: '', start_date: '', end_date: '', targeting_extra: {}, extra: {}, label: '', ...x,
})
const blank = (o, recipe) => ({
  goal: recipe?.goal || 'traffic', budget_mode: 'campaign', daily_budget: 500, start_date: '', end_date: '', adsets: [newSet({ placements: recipe?.placements || 'instagram' })], ads: [],
  campaign: { spend_cap: '', bid_strategy: '', special_ad_categories: [], extra: {} },
  defaults: { primary_text: '', headline: '', description: '', cta: 'LEARN_MORE', destination: o.destinations[0]?.url || '' },
})
/** Older drafts had one audience, or fewer fields: fill every field in. */
const normalize = (x, o) => {
  const b = blank(o)
  const out = { ...b, ...x, campaign: { ...b.campaign, ...(x.campaign || {}) }, defaults: { ...b.defaults, ...(x.defaults || {}) } }
  const list = x.adsets && x.adsets.length ? x.adsets : [{ audience: x.audience || 'all', custom: x.custom, placements: x.placements || 'instagram' }]
  out.adsets = list.map((s) => ({ ...newSet(), ...s, custom: { ...newSet().custom, ...(s.custom || {}) }, uid: s.uid || uid() }))
  return out
}
const toServer = (a) => {
  const all = a.adsets.map((s) => s.uid)
  return { ...a, ads: a.ads.map((ad) => ({ ...ad, sets: (ad.sets || all).filter((u) => all.includes(u)) })) }
}

// ---- small pieces -------------------------------------------------------------------------------------------------------------
function JsonBox({ label, hint, value, onChange }) {
  const [text, setText] = useState(() => (value && Object.keys(value).length ? JSON.stringify(value, null, 2) : ''))
  const [err, setErr] = useState(null)
  return (
    <Field label={label} hint={err ? undefined : hint}>
      <textarea className="field mono" rows={4} spellCheck={false} placeholder="{ }" value={text} onChange={(e) => {
        const t = e.target.value
        setText(t)
        if (!t.trim()) { setErr(null); onChange({}); return }
        try {
          const j = JSON.parse(t)
          if (j && typeof j === 'object' && !Array.isArray(j)) { onChange(j); setErr(null) } else setErr('This must be a JSON object, like { "key": "value" }')
        } catch (x) { setErr('Not valid JSON yet: ' + x.message) }
      }} />
      {err && <span className="lf-hint" style={{ color: 'var(--critical)' }}>{err}</span>}
    </Field>
  )
}

const LEVEL = { 1: ['camp', 'Campaign'], 2: ['set', 'Ad sets'], 3: ['ad', 'Ads'] }
function Section({ n, title, sub, state, open, onToggle, children }) {
  const [lv, lvName] = LEVEL[n] || ['', '']
  return (
    <section className={`card sect ${open ? 'open' : ''}`} data-lv={lv}>
      <button type="button" className="sect-head" onClick={onToggle} aria-expanded={open}>
        <span className={`sect-n ${state}`}>{state === 'done' ? '✓' : state === 'bad' ? '!' : n}</span>
        <span className="grow"><span className="lvtag">Level {n} · {lvName}</span><b>{title}</b><span className="sub" style={{ display: 'block' }}>{sub}</span></span>
        <span style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform .12s' }}><Icon name="chevron" size={18} /></span>
      </button>
      {open && <div className="sect-body">{children}</div>}
    </section>
  )
}

/** What extra mechanisms came with an import, in three groups: sent as is, to check, and left out on purpose (with the reason). */
function ExtrasNotice({ found }) {
  if (!found?.length) return null
  const groups = [['dropped', 'Left out on purpose', 'bad'], ['review', 'Check before creating', 'warn'], ['kept', 'Imported as is', 'good']]
  return (
    <div className="xnotice" role="note">
      <div className="xn-head"><b>This import carries {found.length} extra setting{found.length === 1 ? '' : 's'}</b>
        <span>The builder has no field for some of them. This is what happens to each one.</span></div>
      {groups.map(([st, title, tone]) => {
        const rows = found.filter((x) => x.status === st)
        if (!rows.length) return null
        return (
          <div key={st} className={`xn-group ${tone}`}>
            <div className="xn-title"><i />{title} <span className="muted">({rows.length})</span></div>
            {rows.map((x, i) => <div key={i} className="xn-row"><span className="xn-where">{x.where}</span><span className="xn-what"><b>{x.what}</b><span className="muted"> {x.why}</span></span></div>)}
          </div>
        )
      })}
    </div>
  )
}

function ReportView({ r, kind }) {
  const block = (title, items, tone) => items?.length > 0 && (
    <div style={{ marginTop: 8 }}><div className="lf-label">{title}</div>
      <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>{items.map((x, i) => <li key={i} style={{ color: tone === 'bad' ? 'var(--critical)' : undefined }}>{x}</li>)}</ul></div>
  )
  const what = kind === 'ad' ? 'ad(s)' : 'ad set(s)'
  return (
    <div>
      <div className="chip-row"><Badge tone={r.errors.length ? 'bad' : 'good'}>{r.errors.length ? 'Problem' : `${r.count} ${what} read`}</Badge><Badge>{r.format || 'unknown format'}</Badge></div>
      {block('Problems', r.errors, 'bad')}
      <ExtrasNotice found={r.special} />
      {block('Needs your attention', r.warnings)}
      <details className="xn-more">
        <summary>Full details of the import</summary>
        {block('Filled in', r.filled)}
        {block('Converted for you', r.converted)}
        {block('Kept as extra settings (shown under More options)', r.kept_as_extra)}
        {block('Left out (Meta fills these in itself, or the launcher manages them)', r.ignored)}
      </details>
    </div>
  )
}

const KIND = {
  adset: { title: 'Import ad sets', one: 'an ad set', json: '/api/adsets/import', list: '/api/adsets/from-meta', copy: '/api/adsets/from-meta/', key: 'adsets', find: 'Find an ad set or campaign by name…' },
  campaign: { title: 'Import a campaign', one: 'a campaign', json: '/api/campaigns/import', list: '/api/campaigns/from-meta', copy: '/api/campaigns/from-meta/', key: 'campaigns', find: 'Find a campaign by name…' },
  ad: { title: 'Import ads', one: 'an ad', json: '/api/ads/import', list: '/api/ads/from-meta', copy: '/api/ads/from-meta/', key: 'ads', find: 'Find an ad or campaign by name…' },
}

/** Import from a JSON file / pasted text, copy from your ad account, or use a saved template. Works for ad sets, whole campaigns and ads. */
function ImportModal({ kind, onClose, onApply }) {
  const K = KIND[kind]
  const [tab, setTab] = useState('json')
  const [text, setText] = useState('')
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [list, setList] = useState(null)
  const [tpls, setTpls] = useState(null)
  const [q, setQ] = useState('')
  const file = useRef(null)
  useEffect(() => { const on = (e) => { if (e.key === 'Escape') onClose() }; window.addEventListener('keydown', on); return () => window.removeEventListener('keydown', on) }, [onClose])
  const read = async (t) => { setBusy(true); setErr(null); setRes(null); try { setRes(await api(K.json, { method: 'POST', body: { text: t } })) } catch (e) { setErr(e.message) } setBusy(false) }
  const onFile = async (f) => { if (!f) return; if (f.size > 200 * 1024) { setErr('That file is too large (200 KB limit).'); return } const t = await f.text(); setText(t); read(t) }
  const sample = async (format) => { const j = await api('/api/adsets/sample?format=' + format); downloadJson(j, `adset-sample-${format}.json`) }
  const loadList = async () => { setBusy(true); setErr(null); try { setList((await api(K.list))[K.key]) } catch (e) { setErr(e.message) } setBusy(false) }
  const copy = async (id) => { setBusy(true); setErr(null); setRes(null); try { setRes(await api(K.copy + id)) } catch (e) { setErr(e.message) } setBusy(false) }
  const loadTpls = async () => { try { setTpls((await api('/api/templates?kind=' + kind)).templates) } catch (e) { setErr(e.message) } }
  const useTpl = async (id) => { setBusy(true); setErr(null); setRes(null); try { const t = await api('/api/templates/' + id); setRes(await api(K.json, { method: 'POST', body: { json: t.payload } })) } catch (e) { setErr(e.message) } setBusy(false) }
  useEffect(() => { if (tab === 'meta' && !list) loadList(); if (tab === 'tpl' && !tpls) loadTpls() }, [tab]) // eslint-disable-line react-hooks/exhaustive-deps
  const rows = (list || []).filter((x) => !q.trim() || `${x.name} ${x.campaign || ''}`.toLowerCase().includes(q.trim().toLowerCase()))
  const items = kind === 'adset' ? res?.adsets : kind === 'ad' ? res?.ads : res?.answers
  const ok = kind === 'campaign' ? !!res?.answers && (res.answers.goal || res.answers.adsets?.length || res.answers.ads?.length) : items?.length > 0
  const go = (tabName) => { setTab(tabName); setRes(null); setErr(null) }
  return (
    <div className="lb-bg" onClick={onClose} role="dialog" aria-modal="true" aria-label={K.title}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="row"><h3 className="grow">{K.title}</h3><button type="button" className="btn small" onClick={onClose}>Close</button></div>
        <div className="chip-row" style={{ margin: '10px 0' }}>
          <button type="button" className={`chip ${tab === 'json' ? 'on' : ''}`} onClick={() => go('json')}>From a JSON file</button>
          <button type="button" className={`chip ${tab === 'meta' ? 'on' : ''}`} onClick={() => go('meta')}>Copy from my Meta account</button>
          <button type="button" className={`chip ${tab === 'tpl' ? 'on' : ''}`} onClick={() => go('tpl')}>My templates</button>
        </div>
        {err && <Banner tone="err">{err}</Banner>}
        {tab === 'json' && (
          <>
            <div className="sub">Upload a file or paste the text. Meta's own JSON and the launcher's format both work{kind === 'campaign' ? ', and a campaign file can include its ad sets and ads' : ''}. It is only read as data, and anything active is created paused.</div>
            <div className="drop" style={{ marginTop: 8, padding: 14 }} onClick={() => file.current.click()} onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); onFile(e.dataTransfer.files[0]) }}>
              Drop a .json file here, or click to choose
              <input ref={file} type="file" accept=".json,application/json" hidden onChange={(e) => { onFile(e.target.files[0]); e.target.value = '' }} />
            </div>
            <textarea className="field mono" rows={7} style={{ marginTop: 8 }} spellCheck={false} placeholder="…or paste JSON here" value={text} onChange={(e) => setText(e.target.value)} />
            <div className="row" style={{ marginTop: 8 }}>
              <button type="button" className="btn primary" disabled={busy || !text.trim()} onClick={() => read(text)}>{busy ? 'Reading…' : 'Read it'}</button>
              {kind === 'adset' && <><span className="muted">Samples:</span>
                <button type="button" className="btn small" onClick={() => sample('launcher')}>Launcher format</button>
                <button type="button" className="btn small" onClick={() => sample('meta')}>Meta format</button></>}
            </div>
          </>
        )}
        {tab === 'meta' && !res && (
          <>
            <input className="field" placeholder={K.find} value={q} onChange={(e) => setQ(e.target.value)} />
            {kind === 'campaign' && <div className="mini" style={{ marginTop: 6 }}>Copies the campaign with all its ad sets (up to 10) and ads (up to 40). Nothing on Meta is changed.</div>}
            {busy && !list && <div className="muted" style={{ marginTop: 8 }}>Loading from Meta…</div>}
            <div className="pick-list">{rows.slice(0, 80).map((x) => (
              <button type="button" key={x.id} className="list-row pick-row" onClick={() => copy(x.id)}>
                <span className="grow"><b>{x.name}</b><br /><span className="muted">{x.campaign ? x.campaign + ' · ' : ''}{((x.goal || x.objective || '')).toLowerCase().replace(/_/g, ' ')}</span></span><Badge>{(x.status || '').toLowerCase().replace(/_/g, ' ')}</Badge>
              </button>))}</div>
          </>
        )}
        {tab === 'tpl' && !res && (
          <div className="pick-list">
            {tpls && tpls.length === 0 && <div className="muted">No saved templates yet. Use "Save as template" next to {K.one} to add one.</div>}
            {(tpls || []).map((t) => (
              <div key={t.id} className="list-row"><button type="button" className="pick-row grow" style={{ textAlign: 'left', background: 'none', border: 0, cursor: 'pointer', color: 'inherit' }} onClick={() => useTpl(t.id)}><b>{t.title}</b><br /><span className="muted">{(t.saved || '').slice(0, 10)}{t.note ? ' · ' + t.note : ''}</span></button>
                <button type="button" className="btn small danger" onClick={async () => { await api('/api/templates/' + t.id, { method: 'DELETE' }); loadTpls() }}>Delete</button></div>
            ))}
          </div>
        )}
        {res && (
          <div style={{ marginTop: 12 }}>
            <ReportView r={res.report} kind={kind} />
            {ok && (
              <div className="row" style={{ marginTop: 12 }}>
                {kind === 'campaign' ? <button type="button" className="btn primary" onClick={() => onApply(res.answers, 'replace')}>Use it (replaces what you have)</button> : (
                  <>
                    <button type="button" className="btn primary" onClick={() => onApply(items, 'replace')}>{kind === 'ad' ? 'Replace my ads' : 'Replace my ad sets'}</button>
                    <button type="button" className="btn" onClick={() => onApply(items, 'add')}>{kind === 'ad' ? 'Add them as new ads' : 'Add them as new ad sets'}</button>
                  </>
                )}
                <button type="button" className="btn small" onClick={() => setRes(null)}>Back</button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function AdSetCard({ o, s, i, many, per, upd, dup, del }) {
  const [tab, setTab] = useState(() => (/[?&]tab=(\w+)/.exec(window.location.hash) || [])[1] || 'basics')
  const has = (v) => v && typeof v === 'object' && Object.keys(v).length > 0
  const delivery = !!(s.goal || s.event || s.bid_strategy || s.bid_amount || s.billing_event || s.destination_type || s.start_date || s.end_date || s.lifetime_budget || s.roas)
  const tabs = [['basics', 'Basics', false], ['targeting', 'Targeting', has(s.targeting_extra)], ['delivery', 'Bidding & schedule', delivery], ['expert', 'Expert', has(s.extra)]]
  const conv = CONVERSION.includes(s.goal)
  const places = o.placements.filter((x) => x.id !== 'custom' || s.placements === 'custom')
  return (
    <fieldset className="set">
      <legend>Ad set {i + 1}{s.label ? <span className="muted"> · {s.label}</span> : null} {s.imported && <Badge>imported</Badge>}</legend>
      <div className="set-top">
        <div className="stabs" role="tablist">
          {tabs.map(([k, l, on]) => <button type="button" role="tab" aria-selected={tab === k} key={k} className={`stab ${tab === k ? 'on' : ''}`} onClick={() => setTab(k)}>{l}{on && <i className="sdot" title="Has custom settings" />}</button>)}
        </div>
        <span className="set-actions">
          <button type="button" className="btn small" onClick={dup}>Duplicate</button>
          <button type="button" className="btn small danger" disabled={!many} onClick={del}>Remove</button>
        </span>
      </div>
      {tab === 'basics' && <>
      <div className="fgrid">
        <Field label="Ad set name" hint="Leave empty for an automatic name"><input className="field" value={s.name || ''} placeholder="For example Skincare | Women 25-40 | Reels" onChange={(e) => upd({ name: e.target.value })} /></Field>
        <Field label="Who sees it">
          <select className="field" value={s.audience} onChange={(e) => upd({ audience: e.target.value })}>
            <optgroup label="Ready-made">{o.audiences.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}</optgroup>
            {o.saved_audiences?.length > 0 && <optgroup label="Your saved audiences">{o.saved_audiences.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}</optgroup>}
            <option value="custom">Something else…</option>
          </select>
        </Field>
        <Field label="Where the ads appear">
          <select className="field" value={s.placements} onChange={(e) => upd({ placements: e.target.value })}>{places.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}</select>
        </Field>
        {per && <Field label="Daily budget"><span className="pre"><b>₹</b><input className="field" type="number" min="1" value={s.daily_budget} onChange={(e) => upd({ daily_budget: e.target.value })} /></span></Field>}
      </div>
      {s.audience === 'custom' && (
        <div className="fgrid age" style={{ marginTop: 10 }}>
          <Field label="Countries" hint="Two-letter codes (IN, AE). Leave empty when you pick states or cities under Detailed targeting"><input className="field" value={s.custom.countries} onChange={(e) => upd({ custom: { ...s.custom, countries: e.target.value } })} /></Field>
          <Field label="Youngest"><input className="field" type="number" value={s.custom.age_min} onChange={(e) => upd({ custom: { ...s.custom, age_min: Number(e.target.value) } })} /></Field>
          <Field label="Oldest"><input className="field" type="number" value={s.custom.age_max} onChange={(e) => upd({ custom: { ...s.custom, age_max: Number(e.target.value) } })} /></Field>
          <Field label="Gender"><select className="field" value={s.custom.gender} onChange={(e) => upd({ custom: { ...s.custom, gender: e.target.value } })}><option value="all">Everyone</option><option value="women">Women</option><option value="men">Men</option></select></Field>
        </div>
      )}
      </>}
      {tab === 'targeting' && <div className="tabpane">
        <div className="sub" style={{ marginBottom: 6 }}>Optional. Narrow or widen who sees the ads by place, interest, language and audiences you already have.</div>
        <TargetingEditor s={s} upd={upd} />
      </div>}
      {tab === 'delivery' && <div className="tabpane">
        <div className="fgrid">
          <Field label="What Meta should aim for" hint="Leave as the default unless you want something specific">
            <select className="field" value={s.goal} onChange={(e) => upd({ goal: e.target.value })}>{o.results.map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}</select>
          </Field>
          {conv && <Field label="Which action counts"><select className="field" value={s.event} onChange={(e) => upd({ event: e.target.value })}>{EVENTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>}
          <Field label="How Meta bids" hint={many && !per ? 'With one shared budget this applies to the whole campaign' : ''}>
            <select className="field" value={s.bid_strategy} onChange={(e) => upd({ bid_strategy: e.target.value })}><option value="">Lowest cost (Meta decides)</option>{o.bids.filter((x) => x.value !== 'LOWEST_COST_WITHOUT_CAP').map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}</select>
          </Field>
          {s.bid_strategy === ROAS && <Field label="Minimum return on ad spend" hint="For example 2.5: every ₹1 spent should bring back ₹2.5"><input className="field" type="number" min="0.1" step="0.1" value={s.roas !== '' && s.roas != null ? s.roas : (s.extra?.bid_constraints?.roas_average_floor ? s.extra.bid_constraints.roas_average_floor / 10000 : '')} onChange={(e) => upd({ roas: e.target.value })} /></Field>}
          {CAPPED.includes(s.bid_strategy) && <Field label="Bid amount (₹)" hint="Your cap or target cost"><input className="field" type="number" min="1" value={s.bid_amount} onChange={(e) => upd({ bid_amount: e.target.value })} /></Field>}
          <Field label="You pay for"><select className="field" value={s.billing_event} onChange={(e) => upd({ billing_event: e.target.value })}>{o.billings.map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}</select></Field>
          <Field label="Where people go"><select className="field" value={s.destination_type} onChange={(e) => upd({ destination_type: e.target.value })}>{o.destination_types.map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}</select></Field>
          {per && <Field label="Lifetime budget instead (₹)" hint="Needs an end date. Leave empty to use the daily budget"><input className="field" type="number" min="1" value={s.lifetime_budget} onChange={(e) => upd({ lifetime_budget: e.target.value })} /></Field>}
          <Field label="Starts (this ad set only)"><input className="field" type="date" value={s.start_date} onChange={(e) => upd({ start_date: e.target.value })} /></Field>
          <Field label="Ends (this ad set only)"><input className="field" type="date" value={s.end_date} onChange={(e) => upd({ end_date: e.target.value })} /></Field>
        </div>
      </div>}
      {tab === 'expert' && <div className="tabpane">
        <div className="sub" style={{ margin: '0 0 8px' }}><b>Anything else (expert).</b> Meta's own setting names, as JSON. Cities, interests, your custom audiences, exclusions, manual placements and more go here. Meta checks it before anything is created.</div>
        <div className="fgrid">
          <JsonBox key={s.uid + 't' + (s.rev || 0)} label="Extra targeting" hint='For example {"flexible_spec":[{"interests":[{"id":"6003139266461"}]}]}' value={s.targeting_extra} onChange={(v) => upd({ targeting_extra: v })} />
          <JsonBox key={s.uid + 'x' + (s.rev || 0)} label="Extra ad set settings" hint='For example {"attribution_spec":[{"event_type":"CLICK_THROUGH","window_days":7}]}' value={s.extra} onChange={(v) => upd({ extra: v })} />
        </div>
      </div>}
    </fieldset>
  )
}

// ---- the page --------------------------------------------------------------------------------------------------------------------
export default function Builder({ ctx, params }) {
  const [opts] = useLoad(() => api('/api/wizard/options'))
  return <Loading state={opts}>{(o) => <Flow o={o} ctx={ctx} params={params} />}</Loading>
}

function Flow({ o, ctx, params }) {
  const [started, setStarted] = useState(false)
  const [a, setA] = useState(() => blank(o))
  const [openSec, setOpenSec] = useState(params.open || 'campaign')
  const [seen, setSeen] = useState({})  // sections the person has opened: only those can show a red warning
  useEffect(() => { if (openSec) setSeen((s) => (s[openSec] ? s : { ...s, [openSec]: true })) }, [openSec])
  const [plan, setPlan] = useState(null)
  const [check, setCheck] = useState(null)
  const [phase, setPhase] = useState('edit')
  const [job, setJob] = useState(null)
  const [batch, setBatch] = useState(null)
  const [prodOk, setProdOk] = useState(false)
  const [err, setErr] = useState(null)
  const [draftId, setDraftId] = useState('new')
  const [toast, setToast] = useState(null)
  const [modal, setModal] = useState(params.modal === '1' ? 'adset' : false)
  const prod = o.env === 'production'
  const sig = JSON.stringify(toServer(a))
  const say = (t) => { setToast(t); setTimeout(() => setToast(null), 2500) }
  const set = (k, v) => setA((x) => ({ ...x, [k]: v }))
  const setCamp = (patch) => setA((x) => ({ ...x, campaign: { ...x.campaign, ...patch } }))
  const updSet = (i, patch) => setA((x) => ({ ...x, adsets: x.adsets.map((s, j) => (j === i ? { ...s, ...patch } : s)) }))

  // links from other pages
  useEffect(() => {
    if (params.image) { setA((x) => ({ ...x, ads: [{ image: params.image, ad_key: params.image.split('/').pop().replace(/\.[^.]+$/, ''), ...x.defaults }] })); setStarted(true); setOpenSec('ads') }
  }, [params.image]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!params.metahash) return
    api('/api/meta-images?hashes=' + params.metahash).then(async (r) => {
      const img = r.images?.[0]
      if (!img) return
      const m = /^RS_([A-Za-z0-9]+)_\d+/.exec(img.name || '')
      const key = (await api('/api/next-key?theme=' + encodeURIComponent(m ? m[1] : 'meta'))).key
      setA((x) => ({ ...x, ads: [{ image_hash: img.hash, ad_key: key, preview_url: img.full || img.thumb, ...x.defaults }] })); setStarted(true); setOpenSec('ads')
    }).catch(() => {})
  }, [params.metahash]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (params.draft) api('/api/drafts/' + params.draft).then((d) => { setA(normalize(d.answers, o)); setDraftId(d.id); setStarted(true) }).catch(() => {})
  }, [params.draft]) // eslint-disable-line react-hooks/exhaustive-deps

  // the live plain-language plan (no Meta call except a cached pixel lookup)
  useEffect(() => {
    if (!started) return undefined
    let live = true
    const t = setTimeout(() => api('/api/wizard/preview', { method: 'POST', body: JSON.parse(sig) }).then((p) => live && setPlan(p)).catch(() => {}), 500)
    return () => { live = false; clearTimeout(t) }
  }, [sig, started])
  // autosave the draft
  useEffect(() => {
    if (!started || phase !== 'edit') return undefined
    const t = setTimeout(() => api('/api/drafts/' + draftId, { method: 'PUT', body: { title: `${o.goals.find((g) => g.id === a.goal)?.label || 'Campaign'} · ${a.adsets.length} ad set(s) · ${a.ads.length} ad(s)`, answers: a } }).then((r) => setDraftId(r.id)).catch(() => {}), 2500)
    return () => clearTimeout(t)
  }, [sig, started]) // eslint-disable-line react-hooks/exhaustive-deps

  const runCheck = async () => {
    setCheck({ loading: true, sig })
    try { setCheck({ data: await api('/api/wizard/check', { method: 'POST', body: JSON.parse(sig) }), sig }) } catch (e) { setCheck({ err: e.message, sig }) }
  }
  const create = async () => {
    setErr(null)
    try {
      const r = await api('/api/wizard/create', { method: 'POST', body: { answers: JSON.parse(sig), confirm_production: prodOk } })
      setBatch(r.batch); setPhase('running'); setJob(null)
      const j = await followJob(r.job, setJob)
      setPhase('done')
      if (j.ok && draftId !== 'new') api('/api/drafts/' + draftId, { method: 'DELETE' }).catch(() => {})
    } catch (e) { setErr(e.message) }
  }
  const retry = async () => {
    setPhase('running'); setJob(null)
    try { const r = await api('/api/wizard/retry', { method: 'POST', body: { batch, confirm_production: prodOk } }); await followJob(r.job, setJob) } catch (e) { setErr(e.message) }
    setPhase('done')
  }
  const reset = () => { setA(blank(o)); setDraftId('new'); setPhase('edit'); setJob(null); setBatch(null); setPlan(null); setCheck(null); setStarted(false); setOpenSec('campaign') }

  const applyImport = (forms, mode) => {
    const made = forms.map((f) => newSet({ ...f, imported: true, rev: 1 }))
    setA((x) => ({ ...x, adsets: mode === 'replace' ? made : [...x.adsets, ...made], budget_mode: (mode === 'replace' ? made.length : x.adsets.length + made.length) > 1 && made.some((m) => m.daily_budget) ? 'adset' : x.budget_mode }))
    setModal(false); setOpenSec('adsets'); say(`${made.length} ad set(s) imported. Review them below.`)
  }
  const applyAds = (list, mode) => {
    const made = list.map((ad) => { const { sets, ...rest } = ad; return { ...rest, sets: null } })
    setA((x) => ({ ...x, ads: mode === 'replace' ? made : [...x.ads, ...made] }))
    setModal(false); setStarted(true); setOpenSec('ads'); say(`${made.length} ad(s) imported. Choose where each one appears.`)
  }
  const addFormat = async (kind) => {
    try {
      const key = (await api('/api/next-key?theme=' + encodeURIComponent(kind))).key
      setA((x) => ({ ...x, ads: [...x.ads, newFormatAd(kind, key, o)] }))
    } catch (e) { setErr(e.message) }
  }
  const applyCampaign = (ans) => {
    setA((x) => {
      const sets = (ans.adsets || []).map((f) => newSet({ ...f, imported: true, rev: 1 }))
      const base = sets.length ? sets : x.adsets
      const ads = (ans.ads || []).map((ad) => {
        const { set_idx, sets: _s, ...rest } = ad
        const mine = (set_idx || []).filter((i) => base[i]).map((i) => base[i].uid)
        return { ...(rest.creative_spec ? {} : x.defaults), ...rest, sets: mine.length && mine.length < base.length ? mine : null }
      })
      let mode = ans.budget_mode || x.budget_mode
      let daily = ans.daily_budget ?? x.daily_budget
      if (base.length === 1 && mode === 'adset') { mode = 'campaign'; daily = base[0].daily_budget || daily }
      return {
        ...x, goal: ans.goal || x.goal, budget_mode: mode, daily_budget: daily, start_date: ans.start_date ?? x.start_date, end_date: ans.end_date ?? x.end_date,
        campaign: { ...x.campaign, ...(ans.campaign || {}), extra: { ...(ans.campaign?.extra || {}) }, rev: (x.campaign.rev || 0) + 1 },
        adsets: base, ads: ads.length ? ads : x.ads,
      }
    })
    setModal(false); setStarted(true); setOpenSec('campaign'); say('Campaign imported. Review each section.')
  }
  const saveTpl = async (kind, payload) => {
    const title = window.prompt('Name this template', kind === 'ad' ? (payload.label || payload.ad_key || 'Ad') : kind === 'campaign' ? 'Campaign setup' : 'Ad set')
    if (!title) return
    const body = kind === 'ad' ? exportAd(payload, a.adsets.map((s) => s.uid)) : payload
    try { await api('/api/templates/new', { method: 'PUT', body: { kind, title, payload: body } }); say('Template saved.') } catch (e) { setErr(e.message) }
  }

  if (phase !== 'edit') return <Progress job={job} phase={phase} prod={prod} ctx={ctx} retry={retry} back={() => setPhase('edit')} again={reset} err={err} />
  const modalEl = modal ? <ImportModal kind={modal} onClose={() => setModal(false)} onApply={modal === 'campaign' ? applyCampaign : modal === 'ad' ? applyAds : applyImport} /> : null
  if (!started) return <><Start o={o} onImport={() => setModal('campaign')} start={(recipe) => { setA(blank(o, recipe)); setStarted(true); setOpenSec('campaign') }} load={(x, id) => { setA(normalize(x, o)); setDraftId(id); setStarted(true) }}
    copy={(x) => { const n = normalize(x, o); const d = x.ads?.[0] || n.defaults; setA({ ...n, ads: [], adsets: n.adsets.map((s) => ({ ...s, uid: uid() })), defaults: { ...n.defaults, primary_text: d.primary_text || '', headline: d.headline || '', cta: d.cta || 'LEARN_MORE', destination: d.destination || n.defaults.destination } }); setStarted(true) }} />{modalEl}</>

  const errs = plan?.errors || []
  const errOf = (re) => errs.filter((e) => re.test(e))
  const campErrs = errs.filter((e) => !/^Ad set \d|^Ad \d|^Add at least one ad\b/.test(e))
  const setErrs = errOf(/^Ad set \d|^Add at least one ad set/)
  const adErrs = errOf(/^Ad \d|^Add at least one ad\b/)
  const many = a.adsets.length > 1
  const per = many && a.budget_mode === 'adset'
  const goal = o.goals.find((g) => g.id === a.goal)
  const total = a.adsets.reduce((t, s) => t + (Number(s.daily_budget) || 0), 0)
  const st = (bad, done, key) => (bad && seen[key] ? 'bad' : done && !bad ? 'done' : '')
  const checkStale = check && check.sig !== sig
  const goSec = (e) => (/^Ad set \d|^Add at least one ad set/.test(e) ? 'adsets' : /^Ad \d|^Add at least one ad\b/.test(e) ? 'ads' : 'campaign')
  const names = plan?.summary
  const steps = [['campaign', 'Campaign', campErrs.length, true], ['adsets', 'Ad sets', setErrs.length, a.adsets.length > 0], ['ads', 'Ads', adErrs.length, a.ads.length > 0]]
  const allOk = !!plan && errs.length === 0

  return (
    <div className="builder">
      <div className="stack">
        {err && <Banner tone="err">{err}</Banner>}
        <nav className="pbar" aria-label="Steps">
          {steps.map(([k, label, bad, filled], i) => (
            <button type="button" key={k} className={`pstep ${openSec === k ? 'on' : ''} ${filled && !bad ? 'ok' : ''}`} onClick={() => setOpenSec(k)}>
              <i>{filled && !bad ? '✓' : i + 1}</i><span>{label}</span>
            </button>
          ))}
          <span className={`pstep end ${allOk ? 'ok' : ''}`}><i>{allOk ? '✓' : 4}</i><span>Check and create</span></span>
        </nav>
        <Section n="1" title="Campaign" state={st(campErrs.length, Number(a.daily_budget) > 0 || per, 'campaign')} open={openSec === 'campaign'} onToggle={() => setOpenSec(openSec === 'campaign' ? '' : 'campaign')}
          sub={`${names?.campaign_name || 'New campaign'} · ${goal?.label || ''} · ${per ? inr(total) + ' per day in total' : inr(a.daily_budget) + ' per day'}`}>
          <div className="row" style={{ marginBottom: 10 }}>
            <button type="button" className="btn small" onClick={() => setModal('campaign')}><Icon name="plus" size={13} /> Import or copy a campaign</button>
            <button type="button" className="btn small" onClick={() => downloadJson(exportCampaign(a), 'campaign.json')}>Export the whole campaign as JSON</button>
            <button type="button" className="btn small" onClick={() => saveTpl('campaign', exportCampaign(a))}>Save as template</button>
          </div>
          <div className="fgrid" style={{ marginBottom: 12 }}>
            <Field label="Campaign name" hint="Leave empty for an automatic name like Roopsee | Sales | 18 Nov"><input className="field" value={a.campaign.name || ''} placeholder="For example Skincare | Sales | Diwali" onChange={(e) => setCamp({ name: e.target.value })} /></Field>
          </div>
          <div className="choices">
            {o.goals.map((g) => (
              <button type="button" key={g.id} className={`choice ${a.goal === g.id ? 'on' : ''}`} onClick={() => set('goal', g.id)}>
                <b>{g.label}</b><span>{g.help}</span>
                {g.id === 'sales' && <span className="mini">Needs your pixel. If it is not in .env, I look for one in your ad account.</span>}
              </button>
            ))}
          </div>
          {many && (
            <div className="choices" style={{ margin: '14px 0' }}>
              <button type="button" className={`choice ${!per ? 'on' : ''}`} onClick={() => set('budget_mode', 'campaign')}><b>One budget for the whole campaign</b><span>Meta shares it between your ad sets, giving more to the one that does better.</span></button>
              <button type="button" className={`choice ${per ? 'on' : ''}`} onClick={() => set('budget_mode', 'adset')}><b>A separate budget for each ad set</b><span>You set each audience's budget in its own card below.</span></button>
            </div>
          )}
          <div className="fgrid" style={{ marginTop: 14 }}>
            {!per && <Field label={many ? 'Daily budget for the whole campaign' : 'Daily budget'}><span className="pre"><b>₹</b><input className="field" type="number" min="1" value={a.daily_budget} onChange={(e) => set('daily_budget', e.target.value)} /></span></Field>}
            <Field label="Start date (optional)" hint="Used once you turn the campaign on"><input className="field" type="date" value={a.start_date} onChange={(e) => set('start_date', e.target.value)} /></Field>
            <Field label="End date (optional)"><input className="field" type="date" value={a.end_date} onChange={(e) => set('end_date', e.target.value)} /></Field>
          </div>
          {!per && <div className="chip-row" style={{ marginTop: 8 }}>{[300, 500, 1000, 2000].map((v) => <button type="button" key={v} className={`chip ${Number(a.daily_budget) === v ? 'on' : ''}`} onClick={() => set('daily_budget', v)}>{inr(v)}</button>)}</div>}
          <details className="more" open={!!(a.campaign.spend_cap || a.campaign.bid_strategy || a.campaign.roas || a.campaign.special_ad_categories?.length || Object.keys(a.campaign.extra || {}).length)}>
            <summary>More options</summary>
            <div className="fgrid" style={{ marginTop: 10 }}>
              <Field label="Spending limit for the whole campaign (₹)" hint="Meta stops delivering once this is reached"><input className="field" type="number" min="1" value={a.campaign.spend_cap} onChange={(e) => setCamp({ spend_cap: e.target.value })} /></Field>
              {!per && <Field label="How Meta bids (whole campaign)"><select className="field" value={a.campaign.bid_strategy} onChange={(e) => setCamp({ bid_strategy: e.target.value })}><option value="">Lowest cost (Meta decides)</option>{o.bids.filter((x) => x.value !== 'LOWEST_COST_WITHOUT_CAP').map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}</select></Field>}
              {!per && a.campaign.bid_strategy === ROAS && <Field label="Minimum return on ad spend" hint="For example 2.5. Applies to every ad set unless one sets its own"><input className="field" type="number" min="0.1" step="0.1" value={a.campaign.roas || ''} onChange={(e) => setCamp({ roas: e.target.value })} /></Field>}
            </div>
            <div style={{ marginTop: 10 }}>
              <span className="lf-label">Special ad category <span className="muted">(required for credit, jobs, housing, political and similar ads)</span></span>
              <div className="row" style={{ gap: 14, flexWrap: 'wrap' }}>{SPECIAL.map(([v, l]) => <label key={v} className="chk"><input type="checkbox" checked={(a.campaign.special_ad_categories || []).includes(v)} onChange={(e) => { const cur = a.campaign.special_ad_categories || []; setCamp({ special_ad_categories: e.target.checked ? [...cur, v] : cur.filter((x) => x !== v) }) }} />{l}</label>)}</div>
              {a.campaign.special_ad_categories?.length > 0 && <div className="fgrid" style={{ marginTop: 8 }}><Field label="Country the ads run in" hint="Two-letter code, for example IN"><input className="field" value={a.campaign.special_ad_category_country ?? 'IN'} onChange={(e) => setCamp({ special_ad_category_country: e.target.value.toUpperCase() })} /></Field></div>}
            </div>
            <div style={{ marginTop: 10 }}><JsonBox key={'cx' + (a.campaign.rev || 0)} label="Anything else for the campaign (expert)" hint="Meta's own setting names as JSON" value={a.campaign.extra} onChange={(v) => setCamp({ extra: v })} /></div>
          </details>
          {campErrs.length > 0 && <Banner tone="err">{campErrs.map((e, i) => <div key={i}>{e}</div>)}</Banner>}
          <div className="row" style={{ marginTop: 12 }}><button type="button" className="btn primary" onClick={() => setOpenSec('adsets')}>Next: ad sets</button></div>
        </Section>

        <Section n="2" title="Ad sets" state={st(setErrs.length, a.adsets.length > 0, 'adsets')} open={openSec === 'adsets'} onToggle={() => setOpenSec(openSec === 'adsets' ? '' : 'adsets')}
          sub={names?.adsets?.length ? `${a.adsets.length} ad set${a.adsets.length === 1 ? '' : 's'} · ${names.adsets.map((x) => x.name).join(', ').slice(0, 90)}` : `${a.adsets.length} ad set${a.adsets.length === 1 ? '' : 's'} · who sees the ads and where`}>
          <div className="row" style={{ marginBottom: 10 }}>
            <button type="button" className="btn small" onClick={() => setModal('adset')}><Icon name="plus" size={13} /> Import from JSON or Meta</button>
            <button type="button" className="btn small" onClick={() => downloadJson(exportAdSets(a.adsets), 'adsets.json')}>Export as JSON</button>
            <button type="button" className="btn small" onClick={() => saveTpl('adset', exportAdSets(a.adsets))}>Save as template</button>
            <span className="muted" style={{ fontSize: 12 }}>One ad set is one audience in one kind of place. Add more to compare.</span>
          </div>
          {a.adsets.map((s, i) => (
            <AdSetCard key={s.uid} o={o} s={s} i={i} many={many} per={per} upd={(p) => updSet(i, p)}
              dup={() => setA((x) => ({ ...x, adsets: [...x.adsets.slice(0, i + 1), { ...s, uid: uid(), imported: false, custom: { ...s.custom } }, ...x.adsets.slice(i + 1)] }))}
              del={() => setA((x) => ({ ...x, adsets: x.adsets.filter((_, j) => j !== i) }))} />
          ))}
          <div className="row" style={{ marginTop: 12 }}>
            <button type="button" className="btn" onClick={() => setA((x) => ({ ...x, adsets: [...x.adsets, newSet({ audience: x.adsets.length % 2 ? 'all' : 'women', placements: x.adsets[0]?.placements === 'custom' ? 'instagram' : x.adsets[0]?.placements })] }))}><Icon name="plus" size={14} /> Add another ad set</button>
            <button type="button" className="btn primary" onClick={() => setOpenSec('ads')}>Next: ads</button>
          </div>
          {setErrs.length > 0 && <Banner tone="err">{setErrs.map((e, i) => <div key={i}>{e}</div>)}</Banner>}
        </Section>

        <Section n="3" title="Ads" state={st(adErrs.length, a.ads.length > 0, 'ads')} open={openSec === 'ads'} onToggle={() => setOpenSec(openSec === 'ads' ? '' : 'ads')}
          sub={a.ads.length ? `${a.ads.length} ad${a.ads.length === 1 ? '' : 's'}` : 'Add your images and write the text'}>
          <div className="row" style={{ marginBottom: 10 }}>
            <button type="button" className="btn small" onClick={() => setModal('ad')}><Icon name="plus" size={13} /> Import or copy ads</button>
          </div>
          <div className="mini" style={{ marginBottom: 6 }}>Or build a different kind of ad (image ads are below as before):</div>
          <div className="choices" style={{ marginBottom: 12 }}>
            {Object.entries(KIND_INFO).map(([k, v]) => <button type="button" key={k} className="choice" onClick={() => addFormat(k)}><b>{v.label}</b><span>{v.help}</span></button>)}
          </div>
          <Step4 o={o} a={a} setA={setA} set={set} noPreview saveTpl={saveTpl}
            renderKind={(ad, i, h) => <FormatCard key={ad.ad_key + i} ad={ad} i={i} a={a} o={o} all={h.all} upd={h.upd} toggleSet={h.toggleSet} remove={h.remove} onSave={() => saveTpl('ad', ad)} />} />
          {adErrs.length > 0 && <Banner tone="err">{adErrs.map((e, i) => <div key={i}>{e}</div>)}</Banner>}
          <div className="row" style={{ marginTop: 12 }}>
            <button type="button" className="btn primary" disabled={!allOk || check?.loading} onClick={runCheck}>{check?.loading ? 'Asking Meta…' : 'Next: check with Meta'}</button>
            <span className="muted" style={{ fontSize: 12.5 }}>{allOk ? 'Nothing is created by the check.' : `Fix ${errs.length} thing${errs.length === 1 ? '' : 's'} first (see the summary on the right).`}</span>
          </div>
        </Section>
      </div>

      <aside className="sticky side-panel">
        <Card title="Summary" sub={errs.length ? `${errs.length} thing${errs.length === 1 ? '' : 's'} to fix` : plan ? 'Ready to create' : 'Working it out…'}
          right={plan ? <Badge tone={errs.length ? 'bad' : 'good'}>{errs.length ? 'Not ready' : 'Ready'}</Badge> : null}>
          {plan && (
            <>
              <div className="tree" aria-label="Structure of the campaign">
                <button type="button" className="tn camp" onClick={() => setOpenSec('campaign')}>
                  <span className="tlv">Campaign</span><b>{plan.summary.campaign_name}</b>
                  <span className="tmeta">{plan.summary.goal} · {plan.summary.budget_mode === 'adset' ? `${inr(plan.summary.total_budget)}/day in total` : `${inr(plan.summary.daily_budget)}/day`}</span>
                </button>
                <div className="tkids">
                  {plan.summary.adsets.map((x, i) => {
                    const kids = (plan.summary.ad_list || []).filter((ad) => ad.adset === x.name)
                    return (
                      <div key={i} className="tbranch">
                        <button type="button" className="tn set" onClick={() => setOpenSec('adsets')}>
                          <span className="tlv">Ad set {i + 1}</span><b>{x.name}</b>
                          <span className="tmeta">{x.audience} · {x.placements}{x.goal ? ' · ' + x.goal : ''}{x.bid ? ' · ' + x.bid : ''}{x.extras?.length ? ' · +extra settings' : ''}</span>
                        </button>
                        <div className="tkids">
                          {kids.map((ad, j) => (
                            <button type="button" key={j} className="tn ad" onClick={() => setOpenSec('ads')}>
                              <span className="tlv">Ad</span><b>{ad.name}</b>
                              <span className="tmeta">{ad.type}</span>
                            </button>
                          ))}
                          {kids.length === 0 && <button type="button" className="tn empty" onClick={() => setOpenSec('ads')}>No ads in this ad set yet</button>}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
              <div className="tacct">{o.account} · {prod ? 'PRODUCTION' : 'sandbox'} · created paused</div>
            </>
          )}
          {errs.length > 0 && <Banner tone="err"><b>Fix these</b>{errs.map((e, i) => <div key={i} className="fixrow"><button type="button" className="linkish" onClick={() => setOpenSec(goSec(e))}>• {e}</button></div>)}</Banner>}
          {plan?.warnings?.length > 0 && <Banner><b>Worth knowing</b>{plan.warnings.map((e, i) => <div key={i} style={{ marginTop: 3 }}>• {e}</div>)}</Banner>}
        </Card>

        <Card title="Check with Meta" sub="Asks Meta whether it would accept this. Nothing is created.">
          <button type="button" className="btn" disabled={!plan || errs.length > 0 || check?.loading} onClick={runCheck}>{check?.loading ? 'Asking Meta…' : check?.data ? 'Check again' : 'Check with Meta'}</button>
          {check?.err && <Banner tone="err">{check.err}</Banner>}
          {check?.data && (
            <div className="checks" style={{ marginTop: 10, opacity: checkStale ? 0.55 : 1 }}>
              {checkStale && <div className="mini">You changed something since this check. Check again.</div>}
              {check.data.checks.map((c, i) => (
                <div key={i} style={{ alignItems: 'flex-start' }}>
                  <Badge tone={c.ok ? 'good' : c.ok === false ? 'bad' : 'warn'}>{c.ok ? 'OK' : c.ok === false ? 'Fix' : 'Skipped'}</Badge>
                  <span><b>{c.object}</b> <span className="muted">{c.name.slice(0, 40)}</span><br /><span style={{ fontSize: 12.5 }}>{c.ok === false ? (c.plain || c.message) : c.message}</span>{c.hint && c.ok === false ? <><br /><span className="mini">{c.hint}</span></> : null}</span>
                </div>
              ))}
              {check.data.tested_against && <div className="mini" style={{ marginTop: 6 }}>Ad sets were tested against your existing campaign "{check.data.tested_against}" (nothing on it was changed).</div>}
            </div>
          )}
        </Card>

        <Card title="Create">
          <div className="sub">Uploads your images, then creates the campaign, its ad sets and the ads. <b>Everything is created paused</b>, so nothing runs or spends.</div>
          {prod && <label className="chk" style={{ marginTop: 8 }}><input type="checkbox" checked={prodOk} onChange={(e) => setProdOk(e.target.checked)} /><b>I understand this creates objects in the real ad account (paused)</b></label>}
          <button type="button" className="btn primary" style={{ marginTop: 10, width: '100%' }} disabled={!plan || errs.length > 0 || (prod && !prodOk)} onClick={create}>Create on Meta (paused)</button>
          {(!plan || errs.length > 0) && <div className="mini" style={{ marginTop: 6 }}>{errs.length ? `Fix ${errs.length} thing${errs.length === 1 ? '' : 's'} above to enable this.` : 'Working it out…'}</div>}
          {allOk && prod && !prodOk && <div className="mini" style={{ marginTop: 6 }}>Tick the box above to enable this.</div>}
        </Card>

        {a.ads.some((x) => !x.creative_spec && !x.kind) && <div><div className="mini" style={{ marginBottom: 6 }}>How the first image ad will look</div><FeedPreview ad={a.ads.find((x) => !x.creative_spec && !x.kind)} /></div>}
      </aside>
      {modalEl}
      {toast && <div className="toast">{toast}</div>}
    </div>
  )
}

function Start({ o, start, load, copy, onImport }) {
  const [drafts, reloadD] = useLoad(() => api('/api/drafts'))
  const [hist] = useLoad(() => api('/api/history'))
  return (
    <>
      <Card title="What do you want to do?" sub="Pick one and everything sensible is filled in for you. You can change anything afterwards. Everything is created paused.">
        <div className="grp-label">Quick start with a goal</div>
        <div className="choices even">
          {o.recipes.map((r) => (
            <button type="button" key={r.id} className="choice" onClick={() => start(r)}>
              <b>{r.title}</b><span>{r.text}</span>
            </button>
          ))}
        </div>
        <div className="grp-label">Or</div>
        <div className="choices even two">
          <button type="button" className="choice alt" onClick={() => start(null)}><b>Start from scratch</b><span>Choose each setting yourself, with every option open.</span></button>
          <button type="button" className="choice alt" onClick={onImport}><b>Import or copy a campaign</b><span>From a JSON file, one of your campaigns on Meta (with its ad sets and ads), or a saved template.</span></button>
        </div>
        {o.missing.length > 0 && <Banner tone="err">Missing in <span className="mono">.env</span>: {o.missing.join(', ')}. Creating will not work until this is fixed.</Banner>}
      </Card>
      {drafts.data?.length > 0 && (
        <Card title="Continue a draft" sub="Saved automatically as you go">
          {drafts.data.map((d) => (
            <div key={d.id} className="list-row"><b className="grow">{d.title}</b><span className="muted">{(d.updated || '').replace('T', ' ').slice(0, 16)}</span>
              <button type="button" className="btn small" onClick={async () => load((await api('/api/drafts/' + d.id)).answers, d.id)}>Continue</button>
              <button type="button" className="btn small danger" onClick={async () => { await api('/api/drafts/' + d.id, { method: 'DELETE' }); reloadD() }}>Delete</button></div>
          ))}
        </Card>
      )}
      {hist.data?.length > 0 && (
        <Card title="Start from an earlier campaign" sub="Copies the ad sets and text. Then add the images you want, including ones you used before.">
          {hist.data.map((h) => (
            <div key={h.batch} className="list-row"><span className="grow"><b>{h.campaign}</b><br /><span className="muted">{h.goal} · {inr(h.budget)}/day · {h.adsets || 1} ad set(s) · {h.ads} ad(s)</span></span>
              <button type="button" className="btn small" disabled={!h.answers} onClick={() => copy(h.answers)}>Copy</button></div>
          ))}
        </Card>
      )}
    </>
  )
}

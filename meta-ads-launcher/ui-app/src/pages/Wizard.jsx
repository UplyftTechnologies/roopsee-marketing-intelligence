import { useEffect, useRef, useState } from 'react'
import Icon from '../Icon'
import { api, followJob, inr } from '../api'
import { Badge, Banner, Card, Field, JobPanel, Loading, useLoad } from '../ui'
import { MetaImageGrid, MetaImg } from '../MetaImages'

const STEPS = ['What for', 'Who sees it', 'Budget', 'Ads', 'Review']
const uid = () => 's' + Math.random().toString(36).slice(2, 7)
const newSet = (x = {}) => ({ uid: uid(), audience: 'all', custom: { countries: 'IN', age_min: 18, age_max: 45, gender: 'all' }, placements: 'instagram', daily_budget: 500, ...x })
const blank = (o) => ({
  goal: 'traffic', budget_mode: 'campaign', daily_budget: 500, start_date: '', end_date: '', adsets: [newSet()], ads: [],
  defaults: { primary_text: '', headline: '', description: '', cta: 'LEARN_MORE', destination: o.destinations[0]?.url || '' },
})
/** Older drafts had one audience; turn them into a list of ad sets. */
const normalize = (x, o) => {
  const b = blank(o)
  const out = { ...b, ...x, defaults: { ...b.defaults, ...(x.defaults || {}) } }
  if (!x.adsets || !x.adsets.length) out.adsets = [newSet({ audience: x.audience || 'all', custom: x.custom || b.adsets[0].custom, placements: x.placements || 'instagram' })]
  out.adsets = out.adsets.map((s) => ({ ...s, uid: s.uid || uid() }))
  return out
}
/** What the server needs: every ad knows exactly which ad sets it goes in. */
const toServer = (a) => {
  const all = a.adsets.map((s) => s.uid)
  return { ...a, ads: a.ads.map((ad) => ({ ...ad, sets: (ad.sets || all).filter((u) => all.includes(u)) })) }
}

const themeOf = (name, fallback) => { const m = /^RS_([A-Za-z0-9]+)_\d+/.exec(name || ''); return m ? m[1] : (fallback || 'meta') }
const CtaLabel = { LEARN_MORE: 'Learn more', SHOP_NOW: 'Shop now', SIGN_UP: 'Sign up', GET_OFFER: 'Get offer', ORDER_NOW: 'Order now', CONTACT_US: 'Contact us', SUBSCRIBE: 'Subscribe' }
const audLabel = (o, s) => (s.audience === 'custom' ? `Custom (${s.custom.countries}, ${s.custom.age_min}-${s.custom.age_max}${s.custom.gender !== 'all' ? ', ' + s.custom.gender : ''})`
  : o.audiences.find((x) => x.id === s.audience)?.label || s.audience)
const placeLabel = (o, s) => o.placements.find((x) => x.id === s.placements)?.label || s.placements

function Counter({ label, value, limit, children }) {
  const n = (value || '').length
  return (
    <label className="lf">
      <span className="lf-label">{label}<span className={`cnt ${n > limit ? 'over' : ''}`}>{n}/{limit}</span></span>
      {children}
    </label>
  )
}

function FeedPreview({ ad }) {
  let host = ''
  try { host = new URL(ad.destination).host } catch { /* ignore */ }
  return (
    <div className="fp">
      <div className="ph"><i>R</i>Roopsee.<small>Sponsored</small></div>
      <div className="pt">{ad.primary_text || 'Your main text appears here'}</div>
      {ad.image ? <img src={'/' + ad.image} alt="" /> : ad.preview_url ? <MetaImg src={ad.preview_url} alt="" /> : <div className="noimg">{ad.image_hash ? 'Image already on Meta' : 'No image yet'}</div>}
      <div className="cta"><div><small>{host}</small><b>{ad.headline || 'Your headline'}</b></div><span>{CtaLabel[ad.cta] || 'Learn more'}</span></div>
    </div>
  )
}

export default function Wizard({ ctx, params }) {
  const [opts] = useLoad(() => api('/api/wizard/options'))
  return <Loading state={opts}>{(o) => <Flow o={o} ctx={ctx} params={params} />}</Loading>
}

function Flow({ o, ctx, params }) {
  const [step, setStep] = useState(0) // 0 = start screen
  const [a, setA] = useState(() => blank(o))
  const [draftId, setDraftId] = useState('new')
  const [phase, setPhase] = useState('edit') // edit | running | done
  const [job, setJob] = useState(null)
  const [plan, setPlan] = useState(null)
  const [prodOk, setProdOk] = useState(false)
  const [err, setErr] = useState(null)
  const [batch, setBatch] = useState(null)
  const [toast, setToast] = useState(null)
  const prod = o.env === 'production'

  useEffect(() => { // coming from the Creatives page with an image picked
    if (params.image) { setA((x) => ({ ...x, ads: [{ image: params.image, ad_key: params.image.split('/').pop().replace(/\.[^.]+$/, ''), ...x.defaults }] })); setStep(Number(params.step) || 1) }
  }, [params.image]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { // coming from Creatives > Already on Meta > Use in a campaign
    if (!params.metahash) return
    api('/api/meta-images?hashes=' + params.metahash).then(async (r) => {
      const img = r.images?.[0]
      if (!img) return
      const key = (await api('/api/next-key?theme=' + encodeURIComponent(themeOf(img.name)))).key
      setA((x) => ({ ...x, ads: [{ image_hash: img.hash, ad_key: key, preview_url: img.full || img.thumb, ...x.defaults }] }))
      setStep(4)
    }).catch(() => {})
  }, [params.metahash]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { // a link to a saved draft: #new?draft=<id>
    if (params.draft) api('/api/drafts/' + params.draft).then((d) => { setA(normalize(d.answers, o)); setDraftId(d.id); setStep(Number(params.step) || 1) }).catch(() => {})
  }, [params.draft]) // eslint-disable-line react-hooks/exhaustive-deps
  const set = (k, v) => setA((x) => ({ ...x, [k]: v }))
  const say = (t) => { setToast(t); setTimeout(() => setToast(null), 2500) }

  const saveDraft = async (quiet) => {
    try {
      const r = await api('/api/drafts/' + draftId, { method: 'PUT', body: { title: `${o.goals.find((g) => g.id === a.goal)?.label || 'Campaign'} · ${a.adsets.length} ad set(s) · ${a.ads.length} ad(s)`, answers: a } })
      setDraftId(r.id); if (!quiet) say('Draft saved')
    } catch { /* drafts are optional */ }
  }
  const goto = (n) => { setErr(null); setStep(n); window.scrollTo(0, 0); if (n >= 2) saveDraft(true) }

  useEffect(() => { // review: ask the server for the plain-language plan
    if (step !== 5) return
    setPlan(null)
    api('/api/wizard/preview', { method: 'POST', body: toServer(a) }).then(setPlan).catch((e) => setErr(e.message))
  }, [step]) // eslint-disable-line react-hooks/exhaustive-deps

  const create = async () => {
    setErr(null)
    try {
      const r = await api('/api/wizard/create', { method: 'POST', body: { answers: toServer(a), confirm_production: prodOk } })
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
  const reset = () => { setA(blank(o)); setDraftId('new'); setPhase('edit'); setJob(null); setBatch(null); setPlan(null); setStep(0) }

  if (phase !== 'edit') return <Progress job={job} phase={phase} prod={prod} ctx={ctx} retry={retry} back={() => { setPhase('edit'); setStep(5) }} again={reset} err={err} />

  return (
    <>
      {step > 0 && (
        <div className="stepper" role="list">
          {STEPS.map((s, i) => (
            <button type="button" key={s} role="listitem" className={`stp ${step === i + 1 ? 'on' : ''} ${step > i + 1 ? 'done' : ''}`} disabled={step <= i + 1} onClick={() => goto(i + 1)}>
              <i>{step > i + 1 ? '✓' : i + 1}</i>{s}
            </button>
          ))}
        </div>
      )}
      {err && <Banner tone="err">{err}</Banner>}
      {step === 0 && <Start o={o} begin={() => goto(1)} load={(x, id) => { setA(normalize(x, o)); setDraftId(id); goto(1) }}
        copy={(x) => { const n = normalize(x, o); const d = x.ads?.[0] || n.defaults; setA({ ...n, ads: [], adsets: n.adsets.map((s) => ({ ...s, uid: uid() })), defaults: { primary_text: d.primary_text || '', headline: d.headline || '', description: d.description || '', cta: d.cta || 'LEARN_MORE', destination: d.destination || o.destinations[0]?.url || '' } }); goto(1) }} />}
      {step === 1 && <Step1 o={o} a={a} set={set} />}
      {step === 2 && <Step2 o={o} a={a} setA={setA} />}
      {step === 3 && <Step3 o={o} a={a} setA={setA} set={set} />}
      {step === 4 && <Step4 o={o} a={a} setA={setA} set={set} />}
      {step === 5 && <Step5 o={o} a={a} plan={plan} prod={prod} prodOk={prodOk} setProdOk={setProdOk} create={create} />}
      {step > 0 && (
        <div className="wiz-foot">
          <button type="button" className="btn" onClick={() => goto(step - 1)}>Back</button>
          <button type="button" className="btn" onClick={() => saveDraft(false)}>Save draft</button>
          <div className="right row">{step < 5 && <NextBtn step={step} a={a} next={() => goto(step + 1)} />}</div>
        </div>
      )}
      {toast && <div className="toast">{toast}</div>}
    </>
  )
}

function NextBtn({ step, a, next }) {
  const budgetBad = a.budget_mode === 'adset' && a.adsets.length > 1 ? a.adsets.some((s) => !(Number(s.daily_budget) > 0)) : !(Number(a.daily_budget) > 0)
  const bad = (step === 3 && budgetBad) || (step === 4 && a.ads.length === 0)
  return <button type="button" className="btn primary" disabled={bad} onClick={next} title={bad ? (step === 3 ? 'Enter a daily budget' : 'Add at least one ad') : ''}>{step === 4 ? 'Review' : 'Next'}</button>
}

function Start({ o, begin, load, copy }) {
  const [drafts, reloadD] = useLoad(() => api('/api/drafts'))
  const [hist] = useLoad(() => api('/api/history'))
  return (
    <>
      <Card title="Create a campaign" sub="Answer a few simple questions. You can add several ad sets and several ads. Everything is created paused, so nothing runs or spends until you go live.">
        <div className="row"><button type="button" className="btn primary" onClick={begin}><Icon name="plus" size={16} /> Start a new campaign</button>
          <span className="muted">Takes a few minutes. You end with a campaign on Meta that is switched off.</span></div>
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
        <Card title="Start from an earlier campaign" sub="Copies the ad sets and text. You choose new images, because every image can be used only once.">
          {hist.data.map((h) => (
            <div key={h.batch} className="list-row"><span className="grow"><b>{h.campaign}</b><br /><span className="muted">{h.goal} · {inr(h.budget)}/day · {h.adsets || 1} ad set(s) · {h.ads} ad(s)</span></span>
              <button type="button" className="btn small" disabled={!h.answers} onClick={() => copy(h.answers)}>Copy</button></div>
          ))}
        </Card>
      )}
    </>
  )
}

function Step1({ o, a, set }) {
  return (
    <Card title="What should this campaign do?" sub="Pick the result you care about most">
      <div className="choices">
        {o.goals.map((g) => (
          <button type="button" key={g.id} className={`choice ${a.goal === g.id ? 'on' : ''}`} onClick={() => set('goal', g.id)}>
            <b>{g.label}</b><span>{g.help}</span>
            {g.id === 'sales' && <span>{o.pixel ? <Badge tone="good">Pixel connected</Badge> : <Badge tone="bad">Pixel not set in .env</Badge>}</span>}
          </button>
        ))}
      </div>
    </Card>
  )
}

function Step2({ o, a, setA }) {
  const upd = (i, patch) => setA((x) => ({ ...x, adsets: x.adsets.map((s, j) => (j === i ? { ...s, ...patch } : s)) }))
  const add = () => setA((x) => ({ ...x, adsets: [...x.adsets, newSet({ audience: x.adsets.length % 2 ? 'all' : 'women' })] }))
  const dup = (i) => setA((x) => ({ ...x, adsets: [...x.adsets.slice(0, i + 1), { ...x.adsets[i], uid: uid(), custom: { ...x.adsets[i].custom } }, ...x.adsets.slice(i + 1)] }))
  const del = (i) => setA((x) => ({ ...x, adsets: x.adsets.filter((_, j) => j !== i) }))
  return (
    <Card title="Who should see it, and where?" sub="One ad set is one audience in one kind of place. Add more ad sets to compare audiences or places side by side.">
      {a.adsets.map((s, i) => (
        <fieldset key={s.uid} className="set">
          <legend>Ad set {i + 1}</legend>
          <div className="fgrid">
            <Field label="Who sees it">
              <select className="field" value={s.audience} onChange={(e) => upd(i, { audience: e.target.value })}>
                <optgroup label="Ready-made">{o.audiences.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}</optgroup>
                {o.saved_audiences?.length > 0 && <optgroup label="Your saved audiences">{o.saved_audiences.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}</optgroup>}
                <option value="custom">Something else…</option>
              </select>
            </Field>
            <Field label="Where the ads appear">
              <select className="field" value={s.placements} onChange={(e) => upd(i, { placements: e.target.value })}>{o.placements.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}</select>
            </Field>
          </div>
          {s.audience === 'custom' && (
            <div className="fgrid" style={{ marginTop: 10 }}>
              <Field label="Countries" hint="Two-letter codes, separated by commas (IN, AE)"><input className="field" value={s.custom.countries} onChange={(e) => upd(i, { custom: { ...s.custom, countries: e.target.value } })} /></Field>
              <Field label="Youngest"><input className="field" type="number" value={s.custom.age_min} onChange={(e) => upd(i, { custom: { ...s.custom, age_min: Number(e.target.value) } })} /></Field>
              <Field label="Oldest"><input className="field" type="number" value={s.custom.age_max} onChange={(e) => upd(i, { custom: { ...s.custom, age_max: Number(e.target.value) } })} /></Field>
              <Field label="Gender"><select className="field" value={s.custom.gender} onChange={(e) => upd(i, { custom: { ...s.custom, gender: e.target.value } })}><option value="all">Everyone</option><option value="women">Women</option><option value="men">Men</option></select></Field>
            </div>
          )}
          <div className="row" style={{ marginTop: 10 }}>
            <button type="button" className="btn small" onClick={() => dup(i)}>Duplicate</button>
            <button type="button" className="btn small danger" disabled={a.adsets.length === 1} onClick={() => del(i)}>Remove</button>
          </div>
        </fieldset>
      ))}
      <div className="row" style={{ marginTop: 12 }}>
        <button type="button" className="btn" onClick={add}><Icon name="plus" size={14} /> Add another ad set</button>
        <span className="muted">{a.adsets.length === 1 ? 'Optional. Use it to try a second audience.' : `${a.adsets.length} ad sets`}</span>
      </div>
    </Card>
  )
}

function Step3({ o, a, setA, set }) {
  const many = a.adsets.length > 1
  const per = many && a.budget_mode === 'adset'
  const total = a.adsets.reduce((t, s) => t + (Number(s.daily_budget) || 0), 0)
  const setBud = (i, v) => setA((x) => ({ ...x, adsets: x.adsets.map((s, j) => (j === i ? { ...s, daily_budget: v } : s)) }))
  return (
    <Card title="How much per day?" sub="The most Meta will try to spend each day once the campaign is on">
      {many && (
        <div className="choices" style={{ marginBottom: 14 }}>
          <button type="button" className={`choice ${!per ? 'on' : ''}`} onClick={() => set('budget_mode', 'campaign')}><b>One budget for the whole campaign</b><span>Meta shares it between your ad sets, giving more to the one that does better.</span></button>
          <button type="button" className={`choice ${per ? 'on' : ''}`} onClick={() => set('budget_mode', 'adset')}><b>A separate budget for each ad set</b><span>You decide exactly how much each audience gets.</span></button>
        </div>
      )}
      {!per ? (
        <>
          <div className="fgrid"><Field label={many ? 'Daily budget for the whole campaign' : 'Daily budget'}><span className="pre"><b>₹</b><input className="field" type="number" min="1" value={a.daily_budget} onChange={(e) => set('daily_budget', e.target.value)} /></span></Field></div>
          <div className="chip-row" style={{ marginTop: 8 }}>{[300, 500, 1000, 2000].map((v) => <button type="button" key={v} className={`chip ${Number(a.daily_budget) === v ? 'on' : ''}`} onClick={() => set('daily_budget', v)}>{inr(v)}</button>)}</div>
        </>
      ) : (
        <>
          <table><thead><tr><th>Ad set</th><th>Who sees it</th><th style={{ width: 170 }}>Daily budget</th></tr></thead>
            <tbody>{a.adsets.map((s, i) => (
              <tr key={s.uid}><td>Ad set {i + 1}</td><td>{audLabel(o, s)} · {placeLabel(o, s)}</td>
                <td><span className="pre"><b>₹</b><input className="field" type="number" min="1" value={s.daily_budget} onChange={(e) => setBud(i, e.target.value)} /></span></td></tr>))}</tbody></table>
          <div className="sub" style={{ marginTop: 8 }}>Together: <b>{inr(total)}</b> per day</div>
        </>
      )}
      <div className="fgrid" style={{ marginTop: 16 }}>
        <Field label="Start date (optional)" hint="Only used once you turn the campaign on"><input className="field" type="date" value={a.start_date} onChange={(e) => set('start_date', e.target.value)} /></Field>
        <Field label="End date (optional)"><input className="field" type="date" value={a.end_date} onChange={(e) => set('end_date', e.target.value)} /></Field>
      </div>
      <Banner tone="ok">The campaign is created <b>paused</b>. No money is spent until you turn it on yourself.</Banner>
    </Card>
  )
}

function Step4({ o, a, setA, set }) {
  const d = a.defaults
  const [theme, setTheme] = useState(o.categories[0] || '')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const [lib, setLib] = useState(null)
  const [hash, setHash] = useState({ hash: '', key: '' })
  const [pick, setPick] = useState(false)
  const input = useRef(null)
  const setD = (k, v) => set('defaults', { ...d, [k]: v })
  const addAd = (extra) => setA((x) => ({ ...x, ads: [...x.ads, { ...x.defaults, ...extra }] }))
  const upd = (i, k, v) => setA((x) => ({ ...x, ads: x.ads.map((ad, j) => (j === i ? { ...ad, [k]: v } : ad)) }))
  const all = a.adsets.map((s) => s.uid)
  const toggleSet = (i, u) => {
    const cur = a.ads[i].sets || all
    let next = cur.includes(u) ? cur.filter((x) => x !== u) : [...cur, u]
    if (next.length === 0) return // an ad must appear somewhere
    if (next.length === all.length) next = null
    upd(i, 'sets', next)
  }

  const upload = async (files) => {
    if (!theme.trim()) { setMsg('Type a theme first (for example acne). It names the images.'); return }
    setBusy(true); setMsg(null)
    for (const f of files) {
      const fd = new FormData(); fd.append('file', f); fd.append('category', theme.trim().toLowerCase().replace(/[^a-z0-9_]/g, '_'))
      try { const r = await api('/api/creatives', { method: 'POST', body: fd }); addAd({ image: r.saved, ad_key: r.key }) } catch (e) { setMsg(`${f.name}: ${e.message}`) }
    }
    setBusy(false)
  }
  const addMeta = async (img) => {
    try {
      const key = (await api('/api/next-key?theme=' + encodeURIComponent(themeOf(img.name, theme)))).key
      addAd({ image_hash: img.hash, ad_key: key, preview_url: img.full || img.thumb })
      setMsg(null); setPick(false)
    } catch (e) { setMsg(e.message) }
  }
  const openLib = async () => setLib((await api('/api/creatives')).filter((c) => !c.used && !a.ads.some((x) => x.image === c.path)))

  return (
    <div className="wiz">
      <div className="stack">
        <Card title="Your ads" sub={a.adsets.length > 1 ? 'Each image becomes one ad. Choose which ad sets show it. An ad shown in two ad sets is created once for each.' : 'Each image becomes one ad. Write the text once below, then adjust any ad if you want.'}>
          <fieldset className="set"><legend>Text used for every new ad</legend>
            <div className="fgrid">
              <Counter label="Main text" value={d.primary_text} limit={125}><textarea className="field" value={d.primary_text} onChange={(e) => setD('primary_text', e.target.value)} placeholder="What do you want to say?" /></Counter>
              <div className="stack">
                <Counter label="Headline" value={d.headline} limit={40}><input className="field" value={d.headline} onChange={(e) => setD('headline', e.target.value)} /></Counter>
                <Field label="Button"><select className="field" value={d.cta} onChange={(e) => setD('cta', e.target.value)}>{o.ctas.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}</select></Field>
              </div>
              <DestPick o={o} value={d.destination} onChange={(v) => setD('destination', v)} />
            </div>
            {a.ads.length > 0 && <button type="button" className="btn small" style={{ marginTop: 8 }} onClick={() => setA((x) => ({ ...x, ads: x.ads.map((ad) => ({ ...ad, primary_text: d.primary_text, headline: d.headline, cta: d.cta, destination: d.destination })) }))}>Apply this text to all {a.ads.length} ad(s)</button>}
          </fieldset>

          <div className="fgrid" style={{ margin: '14px 0 8px' }}>
            <Field label="Theme of the new images" hint="For example acne, pigmentation, trust. Names the images RS_ACNE_001…">
              <input className="field" list="wthemes" value={theme} onChange={(e) => setTheme(e.target.value)} placeholder="acne" />
            </Field>
          </div>
          <datalist id="wthemes">{o.categories.map((c) => <option key={c} value={c} />)}</datalist>
          <div className="drop" onClick={() => input.current.click()} onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); upload([...e.dataTransfer.files]) }}>
            {busy ? 'Uploading…' : 'Drop images here, or click to choose. You can pick several.'}
            <input ref={input} type="file" accept=".jpg,.jpeg,.png" multiple hidden onChange={(e) => { upload([...e.target.files]); e.target.value = '' }} />
          </div>
          {msg && <Banner tone="err">{msg}</Banner>}
          <div className="row" style={{ marginTop: 10 }}>
            <button type="button" className="btn small" onClick={openLib}>Pick from my library</button>
            <button type="button" className="btn small" onClick={() => setPick(!pick)}>{pick ? 'Close Meta images' : 'Pick an image already on Meta'}</button>
            <details><summary className="btn small" style={{ display: 'inline-block', cursor: 'pointer' }}>Or paste an image hash</summary>
              <div className="fgrid" style={{ marginTop: 8 }}>
                <Field label="Image hash"><input className="field" value={hash.hash} onChange={(e) => setHash({ ...hash, hash: e.target.value })} placeholder="32 letters and digits" /></Field>
                <Field label="Ad ID (optional)" hint="Leave empty and one is made from the theme above, like RS_SKINCARE_001."><input className="field" value={hash.key} onChange={(e) => setHash({ ...hash, key: e.target.value.toUpperCase() })} /></Field>
              </div>
              <button type="button" className="btn small" style={{ marginTop: 8 }} onClick={async () => {
                const h = hash.hash.trim().toLowerCase()
                if (!/^[0-9a-f]{32}$/.test(h)) { setMsg('That image hash does not look right. It should be 32 letters and digits.'); return }
                let img
                try { img = (await api('/api/meta-images?hashes=' + h)).images?.[0] } catch (e) { setMsg(e.message); return }
                if (!img) { setMsg('That hash is not in this ad account. Use "Pick an image already on Meta" to see the ones you have.'); return }
                let key = hash.key.trim()
                if (!key) { try { key = (await api('/api/next-key?theme=' + encodeURIComponent(themeOf(img.name, theme)))).key } catch (e) { setMsg(e.message); return } }
                setMsg(null); addAd({ image_hash: img.hash, ad_key: key, preview_url: img.full || img.thumb }); setHash({ hash: '', key: '' })
              }}>Add this ad</button>
            </details>
          </div>
          {pick && <div style={{ marginTop: 12 }}><MetaImageGrid limit={24} actions={(i) => <button type="button" className="btn small primary" onClick={() => addMeta(i)}>Use this image</button>} /></div>}
          {lib && (lib.length === 0 ? <div className="muted" style={{ marginTop: 8 }}>No unused images in your library.</div> : (
            <div className="picker" style={{ marginTop: 10 }}>{lib.map((c) => <button type="button" key={c.path} className="pick" onClick={() => { addAd({ image: c.path, ad_key: c.key }); setLib(lib.filter((x) => x.path !== c.path)) }}><img src={'/' + c.path} alt="" /><span>{c.key}</span></button>)}</div>
          ))}
        </Card>

        {a.ads.map((ad, i) => (
          <div key={ad.ad_key + i} className="adcard">
            {ad.image ? <img className="pic" src={'/' + ad.image} alt="" /> : ad.preview_url ? <div className="pic metapic"><MetaImg src={ad.preview_url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} /></div> : <div className="pic">image hash<br />{(ad.image_hash || '').slice(0, 8)}…</div>}
            <div className="stack">
              <div className="row">{ad.image ? <b>{ad.ad_key}</b> : <label className="lf" style={{ minWidth: 220 }}><span className="lf-label">Ad ID (must be new, like RS_SKINCARE_001)</span><span className="mini mono">hash {(ad.image_hash || '').slice(0, 10)}…</span><input className="field" value={ad.ad_key || ''} onChange={(e) => upd(i, 'ad_key', e.target.value.toUpperCase())} /></label>}
                <button type="button" className="btn small danger right" onClick={() => setA((x) => ({ ...x, ads: x.ads.filter((_, j) => j !== i) }))}><Icon name="trash" size={13} /> Remove</button></div>
              {a.adsets.length > 1 && (
                <div><span className="lf-label">Show this ad in</span>
                  <div className="row" style={{ gap: 14 }}>{a.adsets.map((s, j) => <label key={s.uid} className="chk" title={`${audLabel(o, s)} · ${placeLabel(o, s)}`}><input type="checkbox" checked={(ad.sets || all).includes(s.uid)} onChange={() => toggleSet(i, s.uid)} />Ad set {j + 1}<span className="muted">· {s.audience === 'custom' ? 'Custom' : audLabel(o, s).split(',')[0]}</span></label>)}</div></div>
              )}
              <Counter label="Main text" value={ad.primary_text} limit={125}><textarea className="field" value={ad.primary_text} onChange={(e) => upd(i, 'primary_text', e.target.value)} /></Counter>
              <div className="fgrid">
                <Counter label="Headline" value={ad.headline} limit={40}><input className="field" value={ad.headline} onChange={(e) => upd(i, 'headline', e.target.value)} /></Counter>
                <Field label="Button"><select className="field" value={ad.cta} onChange={(e) => upd(i, 'cta', e.target.value)}>{o.ctas.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}</select></Field>
              </div>
              <DestPick o={o} value={ad.destination} onChange={(v) => upd(i, 'destination', v)} />
            </div>
          </div>
        ))}
      </div>
      <div className="sticky">
        <div className="mini" style={{ marginBottom: 6 }}>How it will look</div>
        {a.ads.length === 0 ? <FeedPreview ad={{ ...d }} /> : a.ads.slice(0, 3).map((ad, i) => <FeedPreview key={i} ad={ad} />)}
        {a.ads.length > 3 && <div className="mini">+ {a.ads.length - 3} more</div>}
      </div>
    </div>
  )
}

function DestPick({ o, value, onChange }) {
  const known = o.destinations.some((x) => x.url === value)
  const [other, setOther] = useState(!known && !!value)
  return (
    <div className="stack">
      <Field label="Web page people land on">
        <select className="field" value={other ? '__other' : value} onChange={(e) => { if (e.target.value === '__other') setOther(true); else { setOther(false); onChange(e.target.value) } }}>
          {o.destinations.map((x) => <option key={x.url} value={x.url}>{x.label}</option>)}
          <option value="__other">Another link…</option>
        </select>
      </Field>
      {other && <input className="field" value={value} onChange={(e) => onChange(e.target.value)} placeholder="https://roopsee.com/…" />}
    </div>
  )
}

function Step5({ o, a, plan, prod, prodOk, setProdOk, create }) {
  if (!plan) return <div className="skeleton-wrap"><div className="skeleton" style={{ height: 160 }} /></div>
  const s = plan.summary
  const blocked = plan.errors.length > 0 || (prod && !prodOk)
  const per = s.budget_mode === 'adset'
  return (
    <div className="wiz">
      <div className="stack">
        {plan.errors.length > 0 && <Banner tone="err"><b>Fix these first</b>{plan.errors.map((e, i) => <div key={i} style={{ marginTop: 4 }}>• {e}</div>)}</Banner>}
        {plan.warnings.length > 0 && <Banner>{plan.warnings.map((e, i) => <div key={i}>• {e}</div>)}</Banner>}
        <Card title="Check everything" sub="Nothing has been created yet">
          <dl className="summary">
            <dt>Goal</dt><dd>{s.goal}</dd>
            <dt>Budget</dt><dd>{per ? `${inr(s.total_budget)} per day in total, split by you across the ad sets` : `${inr(s.daily_budget)} per day for the whole campaign`}{s.start ? ` · from ${s.start}` : ''}{s.end ? ` · until ${s.end}` : ''}</dd>
            <dt>Campaign name</dt><dd>{plan.names.campaign}</dd>
            <dt>Ads</dt><dd>{s.ads} ad(s) in total{s.ads !== a.ads.length ? ` (${a.ads.length} image(s), some shown in more than one ad set)` : ''}</dd>
            <dt>Account</dt><dd>{o.account} · {prod ? 'PRODUCTION (real)' : 'sandbox'}</dd>
          </dl>
        </Card>
        <Card title={`Ad sets (${s.adsets.length})`}>
          <table><thead><tr><th>Ad set</th><th>Who sees it</th><th>Where</th>{per && <th className="num">Budget</th>}<th className="num">Ads</th></tr></thead>
            <tbody>{s.adsets.map((x, i) => <tr key={i}><td>{i + 1}</td><td>{x.audience}</td><td>{x.placements}</td>{per && <td className="num">{inr(x.budget)}</td>}<td className="num">{x.ads}</td></tr>)}</tbody></table>
        </Card>
        <Card title="What happens when you press Create">
          <ol style={{ margin: 0, paddingLeft: 20, lineHeight: 1.8 }}>
            <li>Your images are uploaded to Meta.</li>
            <li>The campaign and its {s.adsets.length} ad set(s) are created <b>paused</b>.</li>
            <li>Each of the {s.ads} ad(s) is created <b>paused</b>.</li>
          </ol>
          <div className="sub" style={{ marginTop: 6 }}>Nothing runs or spends. Turning it on is a separate step, afterwards.</div>
          {prod && <label className="chk" style={{ marginTop: 10 }}><input type="checkbox" checked={prodOk} onChange={(e) => setProdOk(e.target.checked)} /><b>I understand this creates objects in the real ad account (paused)</b></label>}
          <div className="wiz-foot"><button type="button" className="btn primary" disabled={blocked} onClick={create}>Create on Meta (paused)</button>{blocked && plan.errors.length === 0 && <span className="muted">Tick the box above to continue.</span>}</div>
        </Card>
      </div>
      <div className="sticky">
        <div className="mini" style={{ marginBottom: 6 }}>Previews</div>
        {a.ads.slice(0, 3).map((ad, i) => <FeedPreview key={i} ad={ad} />)}
      </div>
    </div>
  )
}

function Progress({ job, phase, prod, ctx, retry, back, again, err }) {
  const r = job?.result
  const ok = job?.status === 'done' && job.ok
  return (
    <>
      {err && <Banner tone="err">{err}</Banner>}
      <Card title={phase === 'running' ? 'Creating your campaign…' : ok ? 'Done' : 'It did not finish'}>
        {ok && r && (
          <div className="big-ok" style={{ marginBottom: 12 }}>
            <div className="tick"><Icon name="check" size={24} /></div>
            <div><b style={{ fontSize: 16 }}>Your campaign is created and paused.</b><div className="muted">Nothing is running and nothing is being spent.</div></div>
          </div>
        )}
        <JobPanel job={job} />
        {phase === 'done' && !ok && (
          <div className="row" style={{ marginTop: 10 }}>
            <button type="button" className="btn primary" onClick={retry}>Try again</button>
            <button type="button" className="btn" onClick={back}>Go back and change something</button>
            <span className="muted">Trying again skips what already worked.</span>
          </div>
        )}
      </Card>
      {ok && r && (
        <Card title="What was created" sub={prod ? 'On your real ad account' : 'In the sandbox (not visible in Ads Manager)'}>
          <dl className="summary">
            <dt>Campaign</dt><dd>{r.campaign.name}<br /><span className="mono muted">{r.campaign.id}</span></dd>
            <dt>Ad sets</dt><dd>{r.adsets.map((x) => <div key={x.name}>{x.name} <span className="mono muted">{x.id}</span></div>)}</dd>
            <dt>Ads</dt><dd>{r.ads.map((x) => <div key={x.key}>{x.key} <Badge>{(x.status || 'paused').toLowerCase()}</Badge> <span className="mono muted">{x.id}</span></div>)}</dd>
          </dl>
          <div className="row" style={{ marginTop: 14 }}>
            {r.ads_manager_url && <a className="btn primary" href={r.ads_manager_url} target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>Open in Ads Manager <Icon name="external" size={14} /></a>}
            <button type="button" className="btn" onClick={() => ctx.go('overview')}>See it on the Overview</button>
            <button type="button" className="btn" onClick={() => ctx.go('run', { batch: r.batch })}>Turn it on…</button>
            <button type="button" className="btn" onClick={again}>Create another</button>
          </div>
          {r.ads_manager_url && <div className="mini" style={{ marginTop: 8 }}>If the Ads Manager link does not open the campaign, search for its name there.</div>}
        </Card>
      )}
    </>
  )
}

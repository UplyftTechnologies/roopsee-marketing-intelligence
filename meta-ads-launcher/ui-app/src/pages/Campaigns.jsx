import { useState } from 'react'
import Icon from '../Icon'
import { api, inr } from '../api'
import { Badge, Banner, Card, Field, Loading, useLoad } from '../ui'

const GOALS = { OUTCOME_TRAFFIC: 'Website visits', OUTCOME_SALES: 'Sales', OUTCOME_LEADS: 'Leads', OUTCOME_AWARENESS: 'Awareness', OUTCOME_ENGAGEMENT: 'Engagement' }
const OPT = { LINK_CLICKS: 'Link clicks', LANDING_PAGE_VIEWS: 'Landing page views', OFFSITE_CONVERSIONS: 'Conversions on the website (needs the pixel)', REACH: 'Reach', IMPRESSIONS: 'Impressions' }
const EVENTS = { PURCHASE: 'Purchase', INITIATE_CHECKOUT: 'Started checkout', ADD_TO_CART: 'Added to cart', LEAD: 'Lead', COMPLETE_REGISTRATION: 'Registration', VIEW_CONTENT: 'Viewed content' }
const PLACES = [['instagram', 'Instagram'], ['facebook', 'Facebook'], ['automatic', 'Automatic (let Meta decide)']]
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const day = (t) => (t ? String(t).slice(0, 10) : '')

const genderOf = (g) => (Array.isArray(g) && g.length === 1 ? (g[0] === 2 ? 'women' : 'men') : 'all')
const gendersOf = (g) => (g === 'women' ? [2] : g === 'men' ? [1] : [])

export default function Campaigns() {
  const [st] = useLoad(async () => ({ cfg: await api('/api/config'), state: await api('/api/state') }))
  return <Loading state={st}>{(d) => <Editor d={d} />}</Loading>
}

function Editor({ d }) {
  const onMeta = d.state.entities || {}
  const init = () => {
    const sets = d.cfg.adsets.adsets || []
    const keys = new Set((d.cfg.campaigns.campaigns || []).map((c) => c.key))
    return {
      camps: (d.cfg.campaigns.campaigns || []).map((c) => ({ ...c, adsets: sets.filter((a) => a.campaign_key === c.key).map((a) => ({ ...a })) })),
      orphans: sets.filter((a) => !keys.has(a.campaign_key)),
    }
  }
  const [m, setM] = useState(init)
  const allAud = Object.entries(d.cfg.audiences.audiences || {})
  const [auds, setAuds] = useState(() => allAud.filter(([k]) => !k.startsWith('WIZ_')).map(([k, v]) => ({ key: k, countries: (v.countries || []).join(', '), age_min: v.age_min, age_max: v.age_max, gender: genderOf(v.genders) })))
  const auto = allAud.filter(([k]) => k.startsWith('WIZ_'))
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const audNames = [...auds.map((a) => a.key).filter(Boolean), ...auto.map(([k]) => k)]
  const cLocked = (c) => !c._new && !!onMeta[`campaign:${c.key}`]
  const aLocked = (a) => !a._new && !!onMeta[`adset:${a.key}`]

  const setCamp = (i, patch) => setM((x) => ({ ...x, camps: x.camps.map((c, j) => (j === i ? { ...c, ...patch } : c)) }))
  const setSet = (i, k, patch) => setM((x) => ({ ...x, camps: x.camps.map((c, j) => (j === i ? { ...c, adsets: c.adsets.map((a, n) => (n === k ? { ...a, ...patch } : a)) } : c)) }))
  const addCamp = () => setM((x) => ({ ...x, camps: [...x.camps, { key: '', objective: 'OUTCOME_TRAFFIC', budget_strategy: 'CBO', daily_budget: 500, status: 'PAUSED', adsets: [], _new: true }] }))
  const addSet = (i) => setM((x) => ({ ...x, camps: x.camps.map((c, j) => (j === i ? { ...c, adsets: [...c.adsets, { key: '', campaign_key: c.key, audience: audNames[0] || '', placements: ['instagram'], optimization_goal: c.objective === 'OUTCOME_SALES' ? 'OFFSITE_CONVERSIONS' : 'LINK_CLICKS', _new: true }] } : c)) }))
  const copyName = (k, taken) => { let n = `${k} copy`, i = 1; while (taken.has(n)) { i += 1; n = `${k} copy ${i}` } return n }
  const dupSet = (i, k) => setM((x) => {
    const taken = new Set(x.camps.flatMap((c) => c.adsets.map((a) => a.key)))
    return { ...x, camps: x.camps.map((c, j) => (j === i ? { ...c, adsets: [...c.adsets.slice(0, k + 1), { ...c.adsets[k], key: copyName(c.adsets[k].key, taken), _new: true }, ...c.adsets.slice(k + 1)] } : c)) }
  })
  const dupCamp = (i) => setM((x) => {
    const takenC = new Set(x.camps.map((c) => c.key)); const takenA = new Set(x.camps.flatMap((c) => c.adsets.map((a) => a.key)))
    const src = x.camps[i]; const nk = copyName(src.key, takenC)
    const copy = { ...src, key: nk, _new: true, adsets: src.adsets.map((a) => { const k = copyName(a.key, takenA); takenA.add(k); return { ...a, key: k, campaign_key: nk, _new: true } }) }
    return { ...x, camps: [...x.camps.slice(0, i + 1), copy, ...x.camps.slice(i + 1)] }
  })
  const delCamp = (i) => setM((x) => ({ ...x, camps: x.camps.filter((_, j) => j !== i) }))
  const delSet = (i, k) => setM((x) => ({ ...x, camps: x.camps.map((c, j) => (j === i ? { ...c, adsets: c.adsets.filter((_, n) => n !== k) } : c)) }))

  const save = async () => {
    const problems = []
    const names = new Set()
    m.camps.forEach((c) => { if (!c.key.trim()) problems.push('Give every campaign a name.'); if (names.has(c.key)) problems.push(`Two campaigns are called "${c.key}".`); names.add(c.key) })
    const anames = new Set()
    m.camps.forEach((c) => c.adsets.forEach((a) => { if (!a.key.trim()) problems.push(`Give every ad set in "${c.key}" a name.`); if (anames.has(a.key)) problems.push(`Two ad sets are called "${a.key}".`); anames.add(a.key) }))
    auds.forEach((a) => { if (!a.key.trim()) problems.push('Give every audience a name.') })
    if (problems.length) { setRes({ errors: [...new Set(problems)], warnings: [] }); return }
    setBusy(true)
    try {
      const clean = (o) => { const x = { ...o }; delete x._new; delete x.adsets; return x }
      const campaigns = m.camps.map((c) => { const x = clean(c); x.status = 'PAUSED'; if (x.budget_strategy === 'ABO') delete x.daily_budget; else x.daily_budget = Number(x.daily_budget) || 0; return x })
      const adsets = [...m.camps.flatMap((c) => c.adsets.map((a) => { const x = clean(a); x.campaign_key = c.key; ['optimization_event', 'daily_budget', 'start_time', 'end_time'].forEach((k) => { if (x[k] === '' || x[k] === undefined || x[k] === null) delete x[k] }); if (c.budget_strategy !== 'ABO') delete x.daily_budget; return x })), ...m.orphans]
      const audiences = Object.fromEntries([...auds.map((a) => [a.key.trim(), { countries: String(a.countries).split(',').map((s) => s.trim().toUpperCase()).filter(Boolean), age_min: Number(a.age_min) || 18, age_max: Number(a.age_max) || 45, genders: gendersOf(a.gender) }]), ...auto])
      await api('/api/config/audiences', { method: 'PUT', body: { audiences } })
      await api('/api/config/campaigns', { method: 'PUT', body: { campaigns } })
      const r = await api('/api/config/adsets', { method: 'PUT', body: { adsets } })
      setRes(r)
      await sleep(50)
    } catch (e) { setRes({ errors: [e.message], warnings: [] }) }
    setBusy(false)
  }

  const setAud = (i, patch) => setAuds(auds.map((a, j) => (j === i ? { ...a, ...patch } : a)))
  return (
    <>
      <Banner tone="ok">Set up campaigns, ad sets and audiences here. The <b>New campaign</b> page uses the same pieces and fills them in for you. Everything you create is made <b>paused</b>.</Banner>

      <Card title="Audiences" sub="Who can see your ads. Define one once, then pick it for any ad set." right={<button type="button" className="btn small" onClick={() => setAuds([...auds, { key: '', countries: 'IN', age_min: 18, age_max: 45, gender: 'all', _new: true }])}><Icon name="plus" size={13} /> Add audience</button>}>
        {auds.length === 0 && <div className="muted">No saved audiences yet.</div>}
        {auds.map((a, i) => (
          <div key={i} className="fgrid" style={{ padding: '8px 0', borderBottom: '1px solid var(--grid)' }}>
            <Field label="Name">{a._new ? <input className="field" value={a.key} onChange={(e) => setAud(i, { key: e.target.value })} /> : <div style={{ padding: '6px 0' }}><b>{a.key}</b></div>}</Field>
            <Field label="Countries" hint="Codes like IN, AE"><input className="field" value={a.countries} onChange={(e) => setAud(i, { countries: e.target.value })} /></Field>
            <Field label="Youngest"><input className="field" type="number" value={a.age_min} onChange={(e) => setAud(i, { age_min: e.target.value })} /></Field>
            <Field label="Oldest"><input className="field" type="number" value={a.age_max} onChange={(e) => setAud(i, { age_max: e.target.value })} /></Field>
            <Field label="Gender"><select className="field" value={a.gender} onChange={(e) => setAud(i, { gender: e.target.value })}><option value="all">Everyone</option><option value="women">Women</option><option value="men">Men</option></select></Field>
            {a._new && <div><button type="button" className="btn small danger" onClick={() => setAuds(auds.filter((_, j) => j !== i))}>Remove</button></div>}
          </div>
        ))}
        {auto.length > 0 && <div className="mini" style={{ marginTop: 8 }}>{auto.length} more were made automatically by the New campaign flow and are kept as they are.</div>}
      </Card>

      {m.orphans.length > 0 && <Banner tone="err">{m.orphans.length} ad set(s) have no campaign ({m.orphans.map((a) => a.key).join(', ')}). They are kept as they are. Fix their campaign in the config file or ask for help.</Banner>}

      {m.camps.map((c, i) => {
        const locked = cLocked(c)
        const abo = c.budget_strategy === 'ABO'
        return (
          <Card key={i} className="campcard" title={c.key || 'New campaign'} sub={locked ? 'Already created on Meta, so its settings are locked. Make a copy to change them.' : 'Not created on Meta yet'}
            right={<>{locked ? <Badge tone="good">on Meta</Badge> : <Badge>draft</Badge>}<button type="button" className="btn small" onClick={() => dupCamp(i)}>Make a copy</button>{!locked && <button type="button" className="btn small danger" onClick={() => delCamp(i)}>Remove</button>}</>}>
            <div className="fgrid">
              <Field label="Name on Meta" hint={c._new ? '' : 'Names cannot change here'}>{c._new ? <input className="field" value={c.key} onChange={(e) => setCamp(i, { key: e.target.value })} /> : <div style={{ padding: '6px 0' }}><b>{c.key}</b></div>}</Field>
              <Field label="What it is for"><select className="field" disabled={locked} value={c.objective} onChange={(e) => setCamp(i, { objective: e.target.value })}>{Object.entries(GOALS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
              <Field label="How the budget works"><select className="field" disabled={locked} value={c.budget_strategy} onChange={(e) => setCamp(i, { budget_strategy: e.target.value })}><option value="CBO">One budget for the whole campaign</option><option value="ABO">A separate budget for each ad set</option></select></Field>
              {!abo && <Field label="Daily budget (₹)"><input className="field" type="number" disabled={locked} value={c.daily_budget ?? ''} onChange={(e) => setCamp(i, { daily_budget: e.target.value })} /></Field>}
            </div>
            {c.objective === 'OUTCOME_SALES' && !d.state.ready && null}
            <div style={{ marginTop: 14 }}>
              <div className="lf-label" style={{ marginBottom: 6 }}>Ad sets ({c.adsets.length})</div>
              {c.adsets.length === 0 && <div className="muted">No ad sets yet. A campaign needs at least one to show ads.</div>}
              {c.adsets.map((a, k) => {
                const al = aLocked(a)
                const conv = a.optimization_goal === 'OFFSITE_CONVERSIONS'
                return (
                  <fieldset key={k} className="set">
                    <legend>{a.key || 'New ad set'} {al && <Badge tone="good">on Meta</Badge>}</legend>
                    <div className="fgrid">
                      <Field label="Name on Meta">{a._new ? <input className="field" value={a.key} onChange={(e) => setSet(i, k, { key: e.target.value })} /> : <div style={{ padding: '6px 0' }}><b>{a.key}</b></div>}</Field>
                      <Field label="Who sees it"><select className="field" disabled={al} value={a.audience} onChange={(e) => setSet(i, k, { audience: e.target.value })}>{audNames.map((n) => <option key={n} value={n}>{n}</option>)}</select></Field>
                      <Field label="Where it shows"><div className="row">{PLACES.map(([p, l]) => <label key={p} className="chk"><input type="checkbox" disabled={al} checked={(a.placements || []).includes(p)} onChange={(e) => { const s = new Set(a.placements || []); if (e.target.checked) s.add(p); else s.delete(p); setSet(i, k, { placements: [...s] }) }} />{l.split(' (')[0]}</label>)}</div></Field>
                      <Field label="What Meta should aim for"><select className="field" disabled={al} value={a.optimization_goal} onChange={(e) => setSet(i, k, { optimization_goal: e.target.value })}>{Object.entries(OPT).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
                      {conv && <Field label="Which action counts"><select className="field" disabled={al} value={a.optimization_event || ''} onChange={(e) => setSet(i, k, { optimization_event: e.target.value })}><option value="">Choose…</option>{Object.entries(EVENTS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>}
                      {abo && <Field label="Daily budget (₹)"><input className="field" type="number" disabled={al} value={a.daily_budget ?? ''} onChange={(e) => setSet(i, k, { daily_budget: e.target.value === '' ? '' : Number(e.target.value) })} /></Field>}
                      <Field label="Start date (optional)"><input className="field" type="date" disabled={al} value={day(a.start_time)} onChange={(e) => setSet(i, k, { start_time: e.target.value ? `${e.target.value}T00:00:00+0530` : '' })} /></Field>
                      <Field label="End date (optional)"><input className="field" type="date" disabled={al} value={day(a.end_time)} onChange={(e) => setSet(i, k, { end_time: e.target.value ? `${e.target.value}T23:59:00+0530` : '' })} /></Field>
                    </div>
                    <div className="row" style={{ marginTop: 8 }}>
                      <button type="button" className="btn small" onClick={() => dupSet(i, k)}>Make a copy</button>
                      {!al && <button type="button" className="btn small danger" onClick={() => delSet(i, k)}>Remove</button>}
                    </div>
                  </fieldset>
                )
              })}
              <button type="button" className="btn" style={{ marginTop: 8 }} onClick={() => addSet(i)}><Icon name="plus" size={14} /> Add an ad set to this campaign</button>
              {abo && c.adsets.length > 0 && <div className="sub" style={{ marginTop: 6 }}>Total daily budget: <b>{inr(c.adsets.reduce((t, a) => t + (Number(a.daily_budget) || 0), 0))}</b></div>}
            </div>
          </Card>
        )
      })}

      <div className="row">
        <button type="button" className="btn" onClick={addCamp}><Icon name="plus" size={14} /> Add a campaign</button>
        <button type="button" className="btn primary" disabled={busy} onClick={save}>{busy ? 'Saving…' : 'Save everything'}</button>
      </div>
      {res && (
        <div>
          {res.errors.map((e, i) => <div key={i} className="banner err" style={{ marginBottom: 6 }}><div>{e}</div></div>)}
          {res.warnings.map((e, i) => <div key={i} className="banner" style={{ marginBottom: 6 }}><div>{e}</div></div>)}
          {!res.errors.length && <div className="banner ok"><div>Saved. Everything checks out.</div></div>}
        </div>
      )}
    </>
  )
}

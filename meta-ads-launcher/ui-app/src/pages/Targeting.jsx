import { useEffect, useState } from 'react'
import { api } from '../api'
import { Badge, Banner, Field } from '../ui'

const PLURAL = { country: 'countries', region: 'regions', city: 'cities', zip: 'zips', neighborhood: 'neighborhoods', subcity: 'subcities', medium_geo_area: 'medium_geo_areas', geo_market: 'geo_markets' }
const GEO_KEYS = Object.values(PLURAL).filter((k) => k !== 'countries')
const TYPE_WORD = { country: 'Country', region: 'State / region', city: 'City', zip: 'Postcode', neighborhood: 'Neighbourhood', subcity: 'Sub-city', medium_geo_area: 'Area', geo_market: 'Market' }

const PLATFORMS = [
  ['facebook', 'Facebook', 'facebook_positions', [['feed', 'Feed'], ['story', 'Stories'], ['facebook_reels', 'Reels'], ['instream_video', 'In-stream video'], ['video_feeds', 'Video feeds'], ['search', 'Search results'], ['marketplace', 'Marketplace'], ['right_hand_column', 'Right column'], ['profile_feed', 'Profile feed'], ['notification', 'Notifications']]],
  ['instagram', 'Instagram', 'instagram_positions', [['stream', 'Feed'], ['story', 'Stories'], ['reels', 'Reels'], ['explore', 'Explore'], ['explore_home', 'Explore home'], ['profile_feed', 'Profile feed'], ['ig_search', 'Search results']]],
  ['messenger', 'Messenger', 'messenger_positions', [['messenger_home', 'Inbox'], ['story', 'Stories']]],
  ['audience_network', 'Audience Network', 'audience_network_positions', [['classic', 'Native, banner, interstitial'], ['rewarded_video', 'Rewarded video']]],
  ['threads', 'Threads', 'threads_positions', [['threads_stream', 'Feed']]],
  ['whatsapp', 'WhatsApp', 'whatsapp_positions', [['status', 'Status']]],
]
const POS_KEYS = PLATFORMS.map((p) => p[2])
const ATTR = [
  ['', 'Meta default', null],
  ['c7v1', '7-day click and 1-day view', [{ event_type: 'CLICK_THROUGH', window_days: 7 }, { event_type: 'VIEW_THROUGH', window_days: 1 }]],
  ['c7v1e1', '7-day click, 1-day view, 1-day engaged view', [{ event_type: 'CLICK_THROUGH', window_days: 7 }, { event_type: 'VIEW_THROUGH', window_days: 1 }, { event_type: 'ENGAGED_VIDEO_VIEW', window_days: 1 }]],
  ['c7', '7-day click only', [{ event_type: 'CLICK_THROUGH', window_days: 7 }]],
  ['c1', '1-day click only', [{ event_type: 'CLICK_THROUGH', window_days: 1 }]],
]
const attrId = (spec) => {
  if (!spec) return ''
  const j = JSON.stringify(spec)
  return ATTR.find((a) => a[2] && JSON.stringify(a[2]) === j)?.[0] || 'other'
}
const has = (o) => o && typeof o === 'object' && Object.keys(o).length > 0
const LANG = { 6: 'English (US)', 24: 'English (UK)', 46: 'Hindi' }
const list = (v) => (Array.isArray(v) ? v : [])

function Search({ kind, placeholder, onPick, country, actions, cls }) {
  const [q, setQ] = useState('')
  const [rows, setRows] = useState([])
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (q.trim().length < 2) { setRows([]); setErr(null); return undefined }
    let live = true
    const t = setTimeout(async () => {
      setBusy(true)
      try { const r = await api(`/api/targeting/search?kind=${kind}&q=${encodeURIComponent(q.trim())}${country ? '&country=' + country : ''}${cls ? '&cls=' + cls : ''}`); if (live) { setRows(r.results); setErr(null) } } catch (e) { if (live) setErr(e.message) }
      if (live) setBusy(false)
    }, 400)
    return () => { live = false; clearTimeout(t) }
  }, [q, kind, country, cls])
  return (
    <div>
      <input className="field" style={{ width: '100%' }} placeholder={placeholder} value={q} onChange={(e) => setQ(e.target.value)} />
      {err && <div className="lf-hint" style={{ color: 'var(--critical)' }}>{err}</div>}
      {busy && <div className="mini">Searching…</div>}
      {rows.length > 0 && (
        <div className="pick-list" style={{ maxHeight: 220 }}>
          {rows.map((r) => (
            <div key={r.key ?? r.id} className="list-row">
              <span className="grow"><b>{r.name}</b>{r.type && <Badge>{TYPE_WORD[r.type] || r.type}</Badge>}<br />
                <span className="muted" style={{ fontSize: 12 }}>{r.region ? r.region + ', ' : ''}{r.country || ''}{r.path ? r.path.replace('Interests > ', '') : ''}{r.size ? ` · about ${Number(r.size).toLocaleString('en-IN')} people` : ''}</span></span>
              {actions(r, () => { setQ(''); setRows([]) })}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function Chips({ items, onRemove, tone, max = 8 }) {
  const [all, setAll] = useState(false)
  if (!items.length) return null
  const shown = all ? items : items.slice(0, max)
  return <div className="chip-row" style={{ margin: '6px 0' }}>{shown.map((x) => <button type="button" key={x.k} className="chip on" style={tone === 'bad' ? { borderColor: 'var(--critical)' } : undefined} title="Click to remove" onClick={() => onRemove(x)}>{x.label} ×</button>)}
    {items.length > max && <button type="button" className="btn small" onClick={() => setAll(!all)}>{all ? 'Show fewer' : `Show all ${items.length}`}</button>}</div>
}

/** Detailed targeting for one ad set. It reads and writes Meta's own targeting JSON (targeting_extra), so the expert box and this editor always agree. */
const CATS = [['behaviors', 'Behaviours'], ['life_events', 'Life events'], ['industries', 'Industries'], ['income', 'Income'], ['family_statuses', 'Family status']]
const SAFETY = [['', 'Meta default (standard)'], ['FACEBOOK_STRICT,AN_STRICT', 'Limited: avoid sensitive content'], ['FACEBOOK_STANDARD,AN_STANDARD', 'Standard'], ['FACEBOOK_RELAXED,AN_RELAXED', 'Expanded: allow more content']]

export default function TargetingEditor({ s, upd, pageId }) {
  const te = s.targeting_extra || {}
  const locked = s.audience !== 'custom' && s.audience !== 'all' && s.audience !== 'women'
  const [auds, setAuds] = useState(null)
  const [aerr, setAerr] = useState(null)
  const [note, setNote] = useState(null)
  const countries = String(s.custom?.countries || '').split(',').map((x) => x.trim().toUpperCase()).filter(Boolean)
  const geo = te.geo_locations || {}
  const exg = te.excluded_geo_locations || {}

  /** apply a change to targeting_extra (and optionally the custom audience); refresh the expert JSON box */
  const commit = (nextTe, custom, extra) => {
    const clean = { ...nextTe }
    for (const k of ['geo_locations', 'excluded_geo_locations']) if (clean[k] && !has(clean[k])) delete clean[k]
    const patch = { targeting_extra: clean, rev: (s.rev || 0) + 1 }
    if (s.audience !== 'custom') patch.audience = 'custom'
    patch.custom = { countries: 'IN', age_min: 18, age_max: 45, gender: s.audience === 'women' ? 'women' : 'all', ...(s.audience === 'custom' ? s.custom : {}), ...(custom || {}) }
    if (extra) patch.extra = extra
    upd(patch)
  }
  const setCountries = (arr) => ({ countries: arr.join(', ') })

  const addPlace = (r, excluded, done) => {
    setNote(null)
    const field = excluded ? 'excluded_geo_locations' : 'geo_locations'
    const g = { ...(te[field] || {}) }
    let custom
    if (r.type === 'country') {
      if (excluded) g.countries = [...new Set([...list(g.countries), r.key])]
      else {
        if (GEO_KEYS.some((k) => list(geo[k]).some((x) => x.country === r.key))) { setNote(`Remove the places inside ${r.name} first, or Meta will see a conflict.`); return }
        custom = setCountries([...new Set([...countries, r.key])])
      }
    } else {
      const k = PLURAL[r.type]
      if (!k) return
      if (list(g[k]).some((x) => String(x.key) === String(r.key))) { done(); return }
      g[k] = [...list(g[k]), { key: r.key, name: r.name, ...(r.country ? { country: r.country } : {}), ...(r.region ? { region: r.region } : {}), ...(r.region_id ? { region_id: String(r.region_id) } : {}) }]
      if (!excluded && countries.includes(r.country)) {
        custom = setCountries(countries.filter((c) => c !== r.country))
        setNote(`${r.country} as a whole country was replaced by the places you chose. Meta rejects both together.`)
      }
    }
    commit({ ...te, [field]: g }, custom)
    done()
  }
  const removePlace = (x, excluded) => {
    const field = excluded ? 'excluded_geo_locations' : 'geo_locations'
    const g = { ...(te[field] || {}) }
    let custom
    if (x.type === 'country') {
      if (excluded) g.countries = list(g.countries).filter((c) => c !== x.key)
      else custom = setCountries(countries.filter((c) => c !== x.key))
    } else g[x.list] = list(g[x.list]).filter((y) => String(y.key) !== String(x.key))
    if (!excluded) {
      const left = GEO_KEYS.some((k) => list(g[k]).length)
      const nowCountries = x.type === 'country' ? countries.filter((c) => c !== x.key) : countries
      if (!left && !nowCountries.length) custom = setCountries([x.type === 'country' ? x.key : (x.country || 'IN')])  // never leave an ad set with no location at all
    }
    commit({ ...te, [field]: g }, custom)
  }
  const placeChips = (g, excluded) => [
    ...(excluded ? list(g.countries) : countries).map((c) => ({ k: 'c' + c, label: `Country: ${c}`, type: 'country', key: c })),
    ...GEO_KEYS.flatMap((k) => list(g[k]).map((x) => ({ k: k + x.key, label: `${TYPE_WORD[Object.keys(PLURAL).find((t) => PLURAL[t] === k)] || k}: ${x.name || x.key}${x.region && k === 'cities' ? ', ' + x.region : ''}`, type: 'place', list: k, key: x.key, country: x.country }))),
  ]
  const setRadius = (key, v) => {
    const g = { ...geo, cities: list(geo.cities).map((c) => (String(c.key) === String(key) ? (v ? { ...c, radius: Number(v), distance_unit: 'kilometer' } : (({ radius, distance_unit, ...r }) => r)(c)) : c)) }
    commit({ ...te, geo_locations: g })
  }

  // interests
  const groups = list(te.flexible_spec)
  const interests = list(groups[0]?.interests)
  const setInterests = (arr) => {
    const g0 = { ...(groups[0] || {}), interests: arr }
    if (!arr.length) delete g0.interests
    const rest = groups.slice(1)
    const fs = has(g0) ? [g0, ...rest] : rest
    const t = { ...te }
    if (fs.length) t.flexible_spec = fs; else delete t.flexible_spec
    commit(t)
  }
  const exInterests = list(te.exclusions?.interests)
  const setExInterests = (arr) => {
    const t = { ...te, exclusions: { ...(te.exclusions || {}), interests: arr } }
    if (!arr.length) { delete t.exclusions.interests; if (!has(t.exclusions)) delete t.exclusions }
    commit(t)
  }
  const addInterest = (r, excluded, done) => {
    const cur = excluded ? exInterests : interests
    if (cur.some((x) => String(x.id) === String(r.id))) { done(); return }
    ;(excluded ? setExInterests : setInterests)([...cur, { id: String(r.id), name: r.name }])
    done()
  }

  // behaviours, life events, industries, income, family status (they live in the same box as interests)
  const setCat = (cls, arr) => {
    const g0 = { ...(groups[0] || {}), [cls]: arr }
    if (!arr.length) delete g0[cls]
    const rest = groups.slice(1)
    const fs = has(g0) ? [g0, ...rest] : rest
    const t = { ...te }
    if (fs.length) t.flexible_spec = fs; else delete t.flexible_spec
    commit(t)
  }
  const exCat = (cls) => list(te.exclusions?.[cls])
  const setExCat = (cls, arr) => {
    const t = { ...te, exclusions: { ...(te.exclusions || {}), [cls]: arr } }
    if (!arr.length) { delete t.exclusions[cls]; if (!has(t.exclusions)) delete t.exclusions }
    commit(t)
  }
  const addCat = (cls, r, excluded, done) => {
    const cur = excluded ? exCat(cls) : list(groups[0]?.[cls])
    if (cur.some((x) => String(x.id) === String(r.id))) { done(); return }
    ;(excluded ? setExCat : setCat)(cls, [...cur, { id: String(r.id), name: r.name }])
    done()
  }
  // people connected to your Page, mobile system, where ads may appear
  const conn = list(te.connections).length ? 'in' : list(te.excluded_connections).length ? 'out' : list(te.friends_of_connections).length ? 'friends' : ''
  const setConn = (v) => {
    const t = { ...te }
    delete t.connections; delete t.excluded_connections; delete t.friends_of_connections
    if (v && pageId) t[v === 'in' ? 'connections' : v === 'out' ? 'excluded_connections' : 'friends_of_connections'] = [{ id: pageId }]
    commit(t)
  }
  const os = list(te.user_os)[0] || ''
  const setOs = (v) => { const t = { ...te }; if (v) t.user_os = [v]; else delete t.user_os; commit(t) }
  const safety = list(te.brand_safety_content_filter_levels).join(',')
  const setSafety = (v) => { const t = { ...te }; if (v) t.brand_safety_content_filter_levels = v.split(','); else delete t.brand_safety_content_filter_levels; commit(t) }

  // languages
  const locales = list(te.locales)
  const setLocales = (arr) => { const t = { ...te }; if (arr.length) t.locales = arr; else delete t.locales; commit(t) }

  // saved audiences
  const loadAuds = async () => { setAerr(null); try { setAuds((await api('/api/targeting/audiences')).audiences) } catch (e) { setAerr(e.message) } }
  const setCA = (key, arr) => { const t = { ...te }; if (arr.length) t[key] = arr; else delete t[key]; commit(t) }

  // advantage audience
  const adv = te.targeting_automation?.advantage_audience === 1
  const setAdv = (on) => commit({ ...te, targeting_automation: { ...(te.targeting_automation || {}), advantage_audience: on ? 1 : 0 } })

  // placements
  const manual = s.placements === 'custom'
  const plats = list(te.publisher_platforms)
  const setManual = (on) => {
    const t = { ...te }
    if (on) { t.publisher_platforms = plats.length ? plats : ['facebook', 'instagram'] } else { delete t.publisher_platforms; POS_KEYS.forEach((k) => delete t[k]); delete t.device_platforms }
    upd({ placements: on ? 'custom' : 'automatic', targeting_extra: t, rev: (s.rev || 0) + 1 })
  }
  const togglePlat = (id, posKey, all) => {
    const t = { ...te }
    const on = plats.includes(id)
    t.publisher_platforms = on ? plats.filter((p) => p !== id) : [...plats, id]
    if (on) delete t[posKey]; else t[posKey] = all.map((x) => x[0])
    if (!t.publisher_platforms.length) { setNote('Pick at least one platform.'); return }
    upd({ targeting_extra: t, rev: (s.rev || 0) + 1 })
  }
  const togglePos = (posKey, p, all) => {
    const cur = list(te[posKey]).length ? list(te[posKey]) : all.map((x) => x[0])
    const next = cur.includes(p) ? cur.filter((x) => x !== p) : [...cur, p]
    if (!next.length) { setNote('Keep at least one place for a platform, or untick the platform.'); return }
    upd({ targeting_extra: { ...te, [posKey]: next }, rev: (s.rev || 0) + 1 })
  }
  const devices = list(te.device_platforms)
  const setDevices = (v) => { const t = { ...te }; if (v) t.device_platforms = v.split(','); else delete t.device_platforms; upd({ targeting_extra: t, rev: (s.rev || 0) + 1 }) }

  // attribution
  const attr = attrId(s.extra?.attribution_spec)
  const setAttr = (id) => {
    const x = { ...(s.extra || {}) }
    const spec = ATTR.find((a) => a[0] === id)?.[2]
    if (spec) x.attribution_spec = spec; else delete x.attribution_spec
    upd({ extra: x, rev: (s.rev || 0) + 1 })
  }

  const incl = placeChips(geo, false)
  const excl = placeChips(exg, true)
  return (
    <fieldset className="set plain">
      <legend className="sr">Detailed targeting</legend>
      {locked && <Banner>This ad set uses your saved audience “{s.audience}”. Choose “Something else…” under Who sees it to edit locations, interests and the rest here.</Banner>}
      <div style={{ opacity: locked ? 0.5 : 1, pointerEvents: locked ? 'none' : 'auto' }} className="stack">
        {note && <Banner>{note}</Banner>}

        <div>
          <span className="lf-label">Locations</span>
          <Chips items={incl} onRemove={(x) => removePlace(x, false)} />
          {GEO_KEYS.includes('cities') && list(geo.cities).length > 0 && (
            <div className="row" style={{ flexWrap: 'wrap', gap: 10, margin: '4px 0' }}>
              {list(geo.cities).map((c) => <label key={c.key} className="mini">{c.name || c.key} radius (km) <input className="field" style={{ width: 120, display: 'inline-block' }} type="number" min="1" max="80" value={c.radius && c.distance_unit === 'kilometer' ? c.radius : ''} placeholder={c.radius ? c.radius + ' ' + (c.distance_unit || '') : 'default'} onChange={(e) => setRadius(c.key, e.target.value)} /></label>)}
            </div>
          )}
          <Search kind="geo" placeholder="Search a country, state, city, postcode or neighbourhood…" onPick={addPlace}
            actions={(r, done) => <><button type="button" className="btn small" onClick={() => addPlace(r, false, done)}>Include</button><button type="button" className="btn small" onClick={() => addPlace(r, true, done)}>Exclude</button></>} />
          {excl.length > 0 && <><span className="lf-label" style={{ marginTop: 8, display: 'block' }}>Excluded places</span><Chips items={excl} tone="bad" onRemove={(x) => removePlace(x, true)} /></>}
          <div className="fgrid" style={{ marginTop: 8 }}>
            <Field label="Who counts as being there">
              <select className="field" value={JSON.stringify(geo.location_types || [])} onChange={(e) => { const v = JSON.parse(e.target.value); const g = { ...geo }; if (v.length) g.location_types = v; else delete g.location_types; commit({ ...te, geo_locations: g }) }}>
                <option value="[]">Meta default (living there or recently there)</option>
                <option value='["home"]'>People who live there</option>
                <option value='["recent"]'>People recently there</option>
                <option value='["travel_in"]'>People travelling there</option>
                <option value='["home","recent"]'>Living or recently there</option>
              </select>
            </Field>
          </div>
        </div>

        <div>
          <span className="lf-label">Interests</span>
          <Chips items={interests.map((x) => ({ k: x.id, label: x.name || x.id, id: x.id }))} onRemove={(x) => setInterests(interests.filter((i) => String(i.id) !== String(x.id)))} />
          <Search kind="interest" placeholder="Search an interest, for example skin care…" actions={(r, done) => <><button type="button" className="btn small" onClick={() => addInterest(r, false, done)}>Include</button><button type="button" className="btn small" onClick={() => addInterest(r, true, done)}>Exclude</button></>} />
          {exInterests.length > 0 && <><span className="lf-label" style={{ marginTop: 8, display: 'block' }}>Excluded interests</span><Chips tone="bad" items={exInterests.map((x) => ({ k: x.id, label: x.name || x.id, id: x.id }))} onRemove={(x) => setExInterests(exInterests.filter((i) => String(i.id) !== String(x.id)))} /></>}
          <div className="mini">Several interests in one box mean “any of these”. Behaviours and “must match both” groups are in the expert box below.</div>
        </div>

        <div>
          <span className="lf-label">Languages</span>
          <Chips items={locales.map((x) => ({ k: String(x), label: LANG[typeof x === 'object' ? x.key : x] || 'Language ' + (typeof x === 'object' ? x.name || x.key : x), id: x }))} onRemove={(x) => setLocales(locales.filter((l) => l !== x.id))} />
          <Search kind="locale" placeholder="Add a language, for example Hindi…" actions={(r, done) => <button type="button" className="btn small" onClick={() => { if (!locales.includes(r.key)) setLocales([...locales, r.key]); done() }}>Add {r.name}</button>} />
          <div className="mini">Leave empty to reach everyone regardless of language.</div>
        </div>

        <div>
          <span className="lf-label">Your saved audiences (custom and lookalike)</span>
          <Chips items={list(te.custom_audiences).map((x) => ({ k: x.id, label: x.name || x.id, id: x.id }))} onRemove={(x) => setCA('custom_audiences', list(te.custom_audiences).filter((a) => a.id !== x.id))} />
          <Chips tone="bad" items={list(te.excluded_custom_audiences).map((x) => ({ k: 'x' + x.id, label: 'Not: ' + (x.name || x.id), id: x.id }))} onRemove={(x) => setCA('excluded_custom_audiences', list(te.excluded_custom_audiences).filter((a) => a.id !== x.id))} />
          {!auds && <button type="button" className="btn small" onClick={loadAuds}>Choose from my audiences</button>}
          {aerr && <div className="lf-hint" style={{ color: 'var(--critical)' }}>{aerr}</div>}
          {auds && (auds.length === 0 ? <div className="muted">Your ad account has no custom audiences.</div> : (
            <div className="pick-list" style={{ maxHeight: 200 }}>{auds.map((a) => (
              <div key={a.id} className="list-row"><span className="grow"><b>{a.name}</b><br /><span className="muted" style={{ fontSize: 12 }}>{a.subtype}{a.size ? ` · ${Number(a.size).toLocaleString('en-IN')}+ people` : ''}</span></span>
                <button type="button" className="btn small" onClick={() => !list(te.custom_audiences).some((x) => x.id === a.id) && setCA('custom_audiences', [...list(te.custom_audiences), { id: a.id, name: a.name }])}>Include</button>
                <button type="button" className="btn small" onClick={() => !list(te.excluded_custom_audiences).some((x) => x.id === a.id) && setCA('excluded_custom_audiences', [...list(te.excluded_custom_audiences), { id: a.id, name: a.name }])}>Exclude</button></div>))}</div>
          ))}
        </div>

        <label className="chk"><input type="checkbox" checked={adv} onChange={(e) => setAdv(e.target.checked)} /><b>Let Meta widen the audience (Advantage audience)</b></label>
        {adv && <div className="mini">Meta needs the oldest age to be 65 and the youngest at most 25 for this. “Check with Meta” will tell you if it does not accept it.</div>}

        <div>
          <label className="chk"><input type="checkbox" checked={manual} onChange={(e) => setManual(e.target.checked)} /><b>Choose the places the ads appear myself</b></label>
          {manual && (
            <div className="stack" style={{ marginTop: 8 }}>
              {PLATFORMS.map(([id, name, posKey, all]) => {
                const on = plats.includes(id)
                const cur = list(te[posKey]).length ? list(te[posKey]) : all.map((x) => x[0])
                return (
                  <div key={id}>
                    <label className="chk"><input type="checkbox" checked={on} onChange={() => togglePlat(id, posKey, all)} /><b>{name}</b></label>
                    {on && <div className="row" style={{ gap: 12, flexWrap: 'wrap', marginLeft: 24 }}>{all.map(([p, l]) => <label key={p} className="chk"><input type="checkbox" checked={cur.includes(p)} onChange={() => togglePos(posKey, p, all)} />{l}</label>)}</div>}
                  </div>
                )
              })}
              <Field label="Devices">
                <select className="field" value={devices.join(',')} onChange={(e) => setDevices(e.target.value)}>
                  <option value="">All devices</option><option value="mobile">Mobile only</option><option value="desktop">Desktop only</option>
                </select>
              </Field>
            </div>
          )}
        </div>

        <details className="more" open={CATS.some(([c]) => list(groups[0]?.[c]).length || exCat(c).length) || !!conn || !!os || !!safety}>
          <summary>More audience controls: behaviours, life events, connections, device, content</summary>
          <div className="stack" style={{ marginTop: 10 }}>
            {CATS.map(([cls, name]) => (
              <div key={cls}>
                <span className="lf-label">{name}</span>
                <Chips items={list(groups[0]?.[cls]).map((x) => ({ k: x.id, label: x.name || x.id, id: x.id }))} onRemove={(x) => setCat(cls, list(groups[0]?.[cls]).filter((i) => String(i.id) !== String(x.id)))} />
                <Search kind="category" cls={cls} placeholder={`Search ${name.toLowerCase()}…`} actions={(r, done) => <><button type="button" className="btn small" onClick={() => addCat(cls, r, false, done)}>Include</button><button type="button" className="btn small" onClick={() => addCat(cls, r, true, done)}>Exclude</button></>} />
                {exCat(cls).length > 0 && <Chips tone="bad" items={exCat(cls).map((x) => ({ k: 'x' + x.id, label: 'Not: ' + (x.name || x.id), id: x.id }))} onRemove={(x) => setExCat(cls, exCat(cls).filter((i) => String(i.id) !== String(x.id)))} />}
              </div>
            ))}
            <div className="fgrid">
              <Field label="People connected to your Page" hint={pageId ? '' : 'Needs META_…_PAGE_ID in .env'}>
                <select className="field" value={conn} disabled={!pageId} onChange={(e) => setConn(e.target.value)}>
                  <option value="">Everyone</option><option value="in">Only people who like my Page</option><option value="out">Not people who like my Page</option><option value="friends">Friends of people who like my Page</option>
                </select>
              </Field>
              <Field label="Mobile system">
                <select className="field" value={os} onChange={(e) => setOs(e.target.value)}><option value="">Any</option><option value="Android">Android</option><option value="iOS">iOS</option></select>
              </Field>
              <Field label="Content the ads may appear next to" hint="Applies to Facebook, Instagram and Audience Network">
                <select className="field" value={SAFETY.some(([v]) => v === safety) ? safety : 'other'} onChange={(e) => setSafety(e.target.value)}>
                  {SAFETY.map(([v, l]) => <option key={v} value={v}>{l}</option>)}{!SAFETY.some(([v]) => v === safety) && <option value="other">Custom (set in the expert box)</option>}
                </select>
              </Field>
            </div>
          </div>
        </details>

        <Field label="How conversions are counted (attribution)" hint="Leave on Meta's default unless you compare against another report">
          <select className="field" value={attr} onChange={(e) => setAttr(e.target.value)}>
            {ATTR.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            {attr === 'other' && <option value="other">Custom (set in the expert box)</option>}
          </select>
        </Field>
      </div>
    </fieldset>
  )
}

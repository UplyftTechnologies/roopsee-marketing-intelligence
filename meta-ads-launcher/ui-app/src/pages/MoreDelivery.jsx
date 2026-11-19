import { useState } from 'react'
import { api } from '../api'
import { Banner, Field } from '../ui'

const DAYS = [[1, 'Mon'], [2, 'Tue'], [3, 'Wed'], [4, 'Thu'], [5, 'Fri'], [6, 'Sat'], [0, 'Sun']]  // Meta counts Sunday as 0
const HOURS = Array.from({ length: 25 }, (_, h) => h)
const hh = (h) => `${String(h).padStart(2, '0')}:00`

/** Extra delivery controls for one ad set. Everything is written as Meta's own names into the ad set's extra settings,
 *  so copying, templates, import and the Expert tab all carry it. */
export default function DeliveryMore({ s, upd, o, per, conv }) {
  const ex = s.extra || {}
  const off = o.currency_offset || 100
  const [pix, setPix] = useState(null)
  const [cc, setCc] = useState(null)
  const [err, setErr] = useState(null)
  const put = (k, v) => {
    const x = { ...(s.extra || {}) }
    if (v === undefined || v === null || v === '' || (Array.isArray(v) && !v.length) || (typeof v === 'object' && !Array.isArray(v) && !Object.keys(v).length)) delete x[k]
    else x[k] = v
    upd({ extra: x, rev: (s.rev || 0) + 1 })
  }
  const putPO = (k, v) => { const po = { ...(ex.promoted_object || {}) }; if (v) po[k] = v; else delete po[k]; put('promoted_object', po) }

  // ---- time of day
  const rows = Array.isArray(ex.adset_schedule) ? ex.adset_schedule : []
  const setRows = (arr) => {
    const x = { ...(s.extra || {}) }
    if (arr.length) { x.adset_schedule = arr; x.pacing_type = ['day_parting'] } else { delete x.adset_schedule; if ((x.pacing_type || []).includes('day_parting')) delete x.pacing_type }
    upd({ extra: x, rev: (s.rev || 0) + 1 })
  }
  const newRow = () => ({ start_minute: 9 * 60, end_minute: 21 * 60, days: [1, 2, 3, 4, 5, 6, 0], timezone_type: 'ADVERTISER' })
  const setRow = (i, p) => setRows(rows.map((r, j) => (j === i ? { ...r, ...p } : r)))
  const toggleDay = (i, d) => { const cur = rows[i].days || []; const next = cur.includes(d) ? cur.filter((x) => x !== d) : [...cur, d]; if (next.length) setRow(i, { days: next }) }

  // ---- how often one person sees the ad
  const fc = (Array.isArray(ex.frequency_control_specs) ? ex.frequency_control_specs[0] : null) || null
  const setFc = (p) => put('frequency_control_specs', p ? [{ event: 'IMPRESSIONS', interval_days: 7, max_frequency: 3, ...(fc || {}), ...p }] : undefined)

  // ---- spend limits (one shared campaign budget only)
  const money = (v) => (v ? Math.round(Number(v) / off) : '')
  const setMoney = (k, r) => put(k, r === '' ? undefined : Math.round(Number(r) * off))

  const loadPix = async () => { setErr(null); try { setPix((await api('/api/meta/pixels')).pixels) } catch (e) { setErr(e.message) } }
  const loadCc = async () => { setErr(null); try { setCc((await api('/api/meta/custom-conversions')).conversions) } catch (e) { setErr(e.message) } }
  const [lab, setLab] = useState((ex.adlabels || []).map((l) => l.name).join(', '))

  return (
    <div className="stack">
      <div>
        <label className="chk"><input type="checkbox" checked={rows.length > 0} onChange={(e) => setRows(e.target.checked ? [newRow()] : [])} /><b>Run only at certain times of day</b></label>
        {rows.length > 0 && (
          <div className="stack" style={{ marginTop: 8 }}>
            {rows.map((r, i) => (
              <div key={i} className="row" style={{ gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
                {DAYS.map(([d, n]) => <label key={d} className="chk"><input type="checkbox" checked={(r.days || []).includes(d)} onChange={() => toggleDay(i, d)} />{n}</label>)}
                <select className="field" style={{ width: 92 }} value={Math.floor((r.start_minute || 0) / 60)} onChange={(e) => setRow(i, { start_minute: Number(e.target.value) * 60 })} aria-label="From">{HOURS.slice(0, 24).map((h) => <option key={h} value={h}>{hh(h)}</option>)}</select>
                <span className="muted">to</span>
                <select className="field" style={{ width: 92 }} value={Math.floor((r.end_minute || 0) / 60)} onChange={(e) => setRow(i, { end_minute: Number(e.target.value) * 60 })} aria-label="To">{HOURS.slice(1).map((h) => <option key={h} value={h}>{hh(h)}</option>)}</select>
                <button type="button" className="btn small danger" onClick={() => setRows(rows.filter((_, j) => j !== i))}>×</button>
              </div>
            ))}
            <div><button type="button" className="btn small" onClick={() => setRows([...rows, newRow()])}>Add another time window</button></div>
            <div className="mini">Times follow your ad account's time zone. Meta only allows this with a lifetime budget for the ad set (use “A separate budget for each ad set” and fill in “Lifetime budget instead”) and an end date.</div>
          </div>
        )}
      </div>

      <div>
        <label className="chk"><input type="checkbox" checked={!!fc} onChange={(e) => setFc(e.target.checked ? {} : null)} /><b>Limit how often one person sees the ad</b></label>
        {fc && (
          <div className="row" style={{ marginTop: 8, gap: 8, alignItems: 'center' }}>
            <span>At most</span><input className="field" style={{ width: 80 }} type="number" min="1" value={fc.max_frequency ?? ''} onChange={(e) => setFc({ max_frequency: e.target.value === '' ? '' : Number(e.target.value) })} />
            <span>times every</span><input className="field" style={{ width: 80 }} type="number" min="1" max="90" value={fc.interval_days ?? ''} onChange={(e) => setFc({ interval_days: e.target.value === '' ? '' : Number(e.target.value) })} /><span>days</span>
          </div>
        )}
        {fc && <div className="mini">Meta allows this only when the result is “Reach”.</div>}
      </div>

      {!per && (
        <div className="fgrid">
          <Field label="Smallest daily spend for this ad set (₹)" hint="Meta spends at least this much on it. Shared campaign budget only"><input className="field" type="number" min="0" value={money(ex.daily_min_spend_target)} onChange={(e) => setMoney('daily_min_spend_target', e.target.value)} /></Field>
          <Field label="Highest daily spend for this ad set (₹)" hint="Meta never spends more than this on it per day"><input className="field" type="number" min="0" value={money(ex.daily_spend_cap)} onChange={(e) => setMoney('daily_spend_cap', e.target.value)} /></Field>
        </div>
      )}

      {conv && (
        <div className="fgrid">
          <Field label="Pixel (dataset)" hint="Leave on the default to use the one in .env or the one found in your account">
            {pix ? (
              <select className="field" value={ex.promoted_object?.pixel_id || ''} onChange={(e) => putPO('pixel_id', e.target.value)}>
                <option value="">Default pixel</option>{pix.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.id}</option>)}
              </select>
            ) : <div><button type="button" className="btn small" onClick={loadPix}>{ex.promoted_object?.pixel_id ? `Pixel ${ex.promoted_object.pixel_id}` : 'Choose a pixel'}</button></div>}
          </Field>
          <Field label="Custom conversion" hint="Counts your own rule. It replaces the pixel and the standard event">
            {cc ? (
              <select className="field" value={ex.promoted_object?.custom_conversion_id || ''} onChange={(e) => putPO('custom_conversion_id', e.target.value)}>
                <option value="">None (use the standard event)</option>{cc.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            ) : <div><button type="button" className="btn small" onClick={loadCc}>{ex.promoted_object?.custom_conversion_id ? `Conversion ${ex.promoted_object.custom_conversion_id}` : 'Choose a custom conversion'}</button></div>}
          </Field>
        </div>
      )}
      {err && <Banner tone="err">{err}</Banner>}

      <div className="fgrid">
        <Field label="Labels (optional)" hint="Comma separated. Ads Manager can filter by them"><input className="field" value={lab} onChange={(e) => { setLab(e.target.value); put('adlabels', e.target.value.split(',').map((x) => x.trim()).filter(Boolean).map((name) => ({ name }))) }} /></Field>
        <Field label="EU: who benefits from the ad (optional)" hint="Needed when you target the European Union"><input className="field" value={ex.dsa_beneficiary || ''} onChange={(e) => put('dsa_beneficiary', e.target.value)} /></Field>
        <Field label="EU: who pays for the ad (optional)"><input className="field" value={ex.dsa_payor || ''} onChange={(e) => put('dsa_payor', e.target.value)} /></Field>
      </div>
    </div>
  )
}

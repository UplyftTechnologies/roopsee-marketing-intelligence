import { useEffect, useRef, useState } from 'react'
import { KEY_LABEL, api, dt, dur, inr, num, pct, useApi, useFilters, usePersisted } from '../api'
import { Badge, Card, Chips, ExportBtn, Kpi, Loading, Pager, Table, nextSort } from '../ui'
import { STAGE, STAGE_TONE } from '../shared'

/** Journeys › My presets: saved lists of user actions, and the visits (or people) that match them. Backend: mi/presets.py */

const EMPTY = { name: '', note: '', definition: { steps: [{ action: 'key:add_to_cart', did: true }], ordered: false, gap: 'eventually' } }
const keyLabel = (k) => KEY_LABEL[k] || k.replace(/_/g, ' ')

/** POST /journey-presets/match with the global filters, reloading when they or the definition change. */
function useMatch(definition, extra) {
  const f = useFilters()
  const [state, setState] = useState({ data: null, loading: true, error: null })
  const dev = f.deviceApplies ? f.deviceType || '' : ''
  const key = JSON.stringify([definition, extra, f.from, f.to, f.includeExcluded, dev, f.tick])
  useEffect(() => {
    if (!definition) return undefined
    let live = true
    setState((s) => ({ ...s, loading: true, error: null }))
    const t = setTimeout(() => {
      api('/journey-presets/match', { method: 'POST', body: definition, params: { date_from: f.from, date_to: f.to, include_excluded: f.includeExcluded, device_type: dev || undefined, ...extra } })
        .then((data) => live && setState({ data, loading: false, error: null }))
        .catch((error) => live && setState({ data: null, loading: false, error: error.message }))
    }, 300)  // the editor changes on every keystroke: wait until it settles
    return () => { live = false; clearTimeout(t) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  return state
}

/** One step of a preset as words. */
const stepText = (s, labels) => {
  const [kind, v] = [s.action.split(':')[0], s.action.slice(s.action.indexOf(':') + 1)]
  const what = labels[s.action] || (kind === 'event' ? v : keyLabel(v))
  return `${s.did ? '' : 'did not: '}${what}`
}

function StepChips({ d, labels }) {
  const joiner = d.ordered ? (d.gap === 'next' ? ' → right after → ' : ' → later → ') : ' + '
  return (
    <span style={{ fontSize: 13 }}>
      {d.steps.map((s, i) => (
        <span key={i}>{i > 0 && <span className="muted">{d.ordered && s.did && d.steps[i - 1].did ? joiner : ' + '}</span>}<span className={`chip ${s.did ? '' : 'off'}`} style={s.did ? undefined : { textDecoration: 'line-through' }}>{stepText(s, labels)}</span></span>
      ))}
    </span>
  )
}

/** Build or change a preset. The count below updates as you edit. */
function Editor({ initial, actions, labels, maxSteps, onSaved, onCancel }) {
  const [p, setP] = useState(initial)
  const [err, setErr] = useState('')
  const names = useApi('/events/names', {}, { scoped: false })
  const d = p.definition
  const setD = (patch) => setP({ ...p, definition: { ...d, ...patch } })
  const setStep = (i, patch) => setD({ steps: d.steps.map((s, j) => (j === i ? { ...s, ...patch } : s)) })
  const move = (i, by) => { const s = [...d.steps]; const [x] = s.splice(i, 1); s.splice(i + by, 0, x); setD({ steps: s }) }
  const preview = useMatch(d, { limit: 1 })
  const save = async () => {
    setErr('')
    try {
      const body = { name: p.name, note: p.note, definition: d }
      const r = p.id ? await api(`/journey-presets/${p.id}`, { method: 'PUT', body }) : await api('/journey-presets', { method: 'POST', body })
      onSaved(r.id)
    } catch (e) { setErr(e.message) }
  }
  const didCount = d.steps.filter((s) => s.did && !s.action.startsWith('flag:')).length
  return (
    <Card title={p.id ? `Edit “${initial.name}”` : 'New preset'} sub="pick the actions a visit must (or must not) contain · the count updates as you build">
      <div style={{ display: 'grid', gap: 10 }}>
        <div className="chip-row">
          <input className="field" style={{ minWidth: 280 }} placeholder="Name, e.g. Searched, carted, did not buy" aria-label="Preset name" value={p.name} onChange={(e) => setP({ ...p, name: e.target.value })} maxLength={80} />
          <input className="field" style={{ minWidth: 320, flex: 1 }} placeholder="Note (optional): why this group matters" aria-label="Note" value={p.note || ''} onChange={(e) => setP({ ...p, note: e.target.value })} />
        </div>
        {d.steps.map((s, i) => {
          const kind = s.action.split(':')[0]
          return (
            <div key={i} className="chip-row" style={{ alignItems: 'center' }}>
              <span className="muted" style={{ width: 22 }}>{i + 1}.</span>
              <select className="field" value={s.did ? 'did' : 'not'} onChange={(e) => setStep(i, { did: e.target.value === 'did' })} aria-label={`Step ${i + 1}: did or did not`}>
                <option value="did">Did</option><option value="not">Did not</option>
              </select>
              <select className="field" value={kind === 'event' ? 'event:' : s.action} onChange={(e) => setStep(i, { action: e.target.value === 'event:' ? 'event:' : e.target.value })} aria-label={`Step ${i + 1}: action`}>
                {['Key actions', 'Outcome'].map((g) => <optgroup key={g} label={g}>{actions.filter((a) => a.group === g).map((a) => <option key={a.action} value={a.action}>{a.label}</option>)}</optgroup>)}
                <optgroup label="Any tracked event"><option value="event:">A specific event name…</option></optgroup>
              </select>
              {kind === 'event' && (
                <>
                  <input className="field mono" list="preset-event-names" style={{ minWidth: 240 }} placeholder="event name, e.g. payment_failed" aria-label={`Step ${i + 1}: event name`}
                    value={s.action.slice(6)} onChange={(e) => setStep(i, { action: 'event:' + e.target.value.trim() })} />
                </>
              )}
              <button type="button" className="btn small" disabled={i === 0} onClick={() => move(i, -1)} aria-label="Move up">↑</button>
              <button type="button" className="btn small" disabled={i === d.steps.length - 1} onClick={() => move(i, 1)} aria-label="Move down">↓</button>
              <button type="button" className="btn small" disabled={d.steps.length === 1} onClick={() => setD({ steps: d.steps.filter((_, j) => j !== i) })} aria-label="Remove step">Remove</button>
            </div>
          )
        })}
        <datalist id="preset-event-names">{(names.data || []).slice(0, 400).map((n) => <option key={n.event_name} value={n.event_name}>{`${num(n.sessions)} sessions`}</option>)}</datalist>
        <div className="chip-row" style={{ alignItems: 'center' }}>
          <button type="button" className="btn small" disabled={d.steps.length >= maxSteps} onClick={() => setD({ steps: [...d.steps, { action: 'key:checkout_view', did: true }] })}>+ Add a step</button>
          <label style={{ fontSize: 13 }}><input type="checkbox" checked={d.ordered} onChange={(e) => setD({ ordered: e.target.checked })} /> The “Did” steps happen in this order</label>
          {d.ordered && (
            <select className="field" value={d.gap} onChange={(e) => setD({ gap: e.target.value })} aria-label="Gap between steps">
              <option value="eventually">each any time later</option><option value="next">each directly after the one before</option>
            </select>
          )}
        </div>
        {d.ordered && <div className="muted" style={{ fontSize: 12 }}>
          {didCount < 2 ? 'Order only matters with two or more “Did” steps. ' : ''}
          “Directly after” means the next key action or named event, ignoring page views, clicks and scrolls. “Did not” steps and “Placed a real order” always look at the whole visit.
        </div>}
        <div className="banner ok" style={{ margin: 0 }} role="status">
          {preview.loading ? 'Counting…' : preview.error ? <span>Cannot count yet: {preview.error}</span> : (
            <span><b>{num(preview.data.summary.visits)}</b> visits ({pct(preview.data.summary.of_all, 1)} of all) by <b>{num(preview.data.summary.people)}</b> people match
              {preview.data.summary.ordered ? `, ${num(preview.data.summary.ordered)} of them ordered (${inr(preview.data.summary.revenue)})` : ', none of them ordered'}.
              <span className="muted"> After each step: {preview.data.steps.map((x) => num(x.visits)).join(' → ')}</span></span>
          )}
        </div>
        {err && <div className="banner err" style={{ margin: 0 }}>{err}</div>}
        <div className="chip-row">
          <button type="button" className="btn primary" disabled={!p.name.trim() || !!preview.error} onClick={save}>{p.id ? 'Save changes' : 'Save preset'}</button>
          <button type="button" className="btn" onClick={onCancel}>Cancel</button>
        </div>
      </div>
    </Card>
  )
}

/** The visits or people that match one preset. */
function Matches({ preset, labels, onClose }) {
  const f = useFilters()
  const [mode, setMode] = usePersisted('presets.mode', 'visits')
  const [sort, setSort] = useState({ key: 'started_at', dir: 'desc' })
  const [limit, setLimit] = usePersisted('presets.limit', 50)
  const [offset, setOffset] = useState(0)
  useEffect(() => { setOffset(0) }, [preset.id, mode, sort, limit, f.from, f.to, f.includeExcluded, f.deviceType])
  const s = useMatch(preset.definition, { mode, sort: sort.key, direction: sort.dir, limit, offset })
  const who = (r) => r.name || (r.phone10 ? <span className="mono">{r.phone10}</span> : <span className="muted">anonymous</span>)
  return (
    <Loading state={s}>
      {(d) => {
        const m = d.summary
        const first = d.steps[0]?.visits || 1
        return (
          <>
            <div className="kpis">
              <Kpi label="Matching visits" value={num(m.visits)} note={`${pct(m.of_all, 1)} of all visits in these dates`} />
              <Kpi label="People" value={num(m.people)} note="each person once" />
              <Kpi label="Of them ordered" value={num(m.ordered)} note={m.visits ? `${pct(m.ordered / m.visits, 1)} of the matching visits` : '–'} />
              <Kpi label="Order value" value={inr(m.revenue)} note="real orders in the matching visits" />
            </div>
            <Card title={preset.name} sub={preset.note || 'how many visits are left after each step'} right={<button type="button" className="btn small" onClick={onClose}>Close</button>}>
              <div style={{ display: 'grid', gap: 6 }}>
                {d.steps.map((x, i) => (
                  <div key={i} style={{ display: 'grid', gridTemplateColumns: 'minmax(160px, 260px) 1fr auto', gap: 10, alignItems: 'center' }}>
                    <div>{i + 1}. {stepText(x, labels)}</div>
                    <div style={{ background: 'var(--surface-2)', borderRadius: 6, height: 18 }}><div style={{ width: `${Math.max(0.5, (x.visits / first) * 100)}%`, height: '100%', borderRadius: 6, background: 'var(--series-1)', opacity: 0.85 }} /></div>
                    <div style={{ minWidth: 120, textAlign: 'right' }}><b>{num(x.visits)}</b>{i > 0 && <span className="muted"> · {pct(x.visits / (d.steps[i - 1].visits || 1), 0)} of prev</span>}</div>
                  </div>
                ))}
              </div>
            </Card>
            <Card title={`${num(d.total)} ${mode === 'visits' ? 'visits' : 'people'}`}
              sub={mode === 'visits' ? 'each row is one matching visit · the path shows the first time of each key action · click a row for the full session' : 'each row is a person with at least one matching visit · click a row for the person'}
              right={<span className="chip-row">
                <Chips value={mode} onChange={(v) => { setMode(v); setSort({ key: v === 'visits' ? 'started_at' : 'last_seen', dir: 'desc' }) }} options={[{ value: 'visits', label: 'Visits' }, { value: 'people', label: 'People' }]} />
                <ExportBtn name={`preset-${preset.name.toLowerCase().replace(/[^a-z0-9]+/g, '-')}-${mode}`} rows={d.rows} fields={mode === 'visits'
                  ? [['Started', 'started_at'], ['Name', 'name'], ['Phone', 'phone10'], ['Channel', 'channel'], ['Campaign', 'campaign'], ['City', 'city'], ['Device', 'device'], ['Path', 'key_events'], ['Ended at', 'stage_name'], ['Order value', 'order_value'], ['Seconds', 'duration_s'], ['Session id', 'session_id']]
                  : [['Name', 'name'], ['Phone', 'phone10'], ['City', 'city'], ['First channel', 'first_channel'], ['Matching visits', 'visits'], ['First match', 'first_seen'], ['Last match', 'last_seen'], ['Best outcome', 'stage_name'], ['Orders', 'orders'], ['Revenue', 'revenue'], ['Latest session id', 'latest_session']]} />
              </span>}>
              {mode === 'visits' ? (
                <Table scroll sort={sort} onSort={(k) => setSort(nextSort(sort, k, ['channel', 'city']))} onRow={(r) => f.go('session', { key: r.session_id })} rowClass={(r) => (r.is_excluded ? 'excluded' : '')} rows={d.rows}
                  empty="No visit matches this preset in these dates. Try wider dates or fewer steps." cols={[
                    { label: 'Started', cls: 'nw', sortBy: 'started_at', render: (r) => dt(r.started_at) },
                    { label: 'Who', cls: 'nw', render: (r) => <a href={`#person/${encodeURIComponent(r.person_key)}`} onClick={(e) => { e.preventDefault(); e.stopPropagation(); f.go('person', { key: r.person_key }) }}>{who(r)}</a> },
                    { label: 'Path', render: (r) => <span style={{ fontSize: 12 }}>{(r.key_events || '').split(' > ').filter(Boolean).slice(0, 9).map(keyLabel).join(' → ') || <span className="muted">no key action</span>}</span> },
                    { label: 'Ended at', cls: 'nw', render: (r) => <Badge tone={STAGE_TONE[r.stage]}>{r.stage_name}</Badge> },
                    { label: 'Order', num: true, sortBy: 'order_value', render: (r) => (r.order_value ? inr(r.order_value) : <span className="muted">–</span>) },
                    { label: 'Channel', cls: 'nw', sortBy: 'channel', render: (r) => <span title={r.campaign}>{r.channel}</span> },
                    { label: 'Place · device', cls: 'nw', sortBy: 'city', render: (r) => `${r.city || '–'} · ${r.is_app ? 'App' : r.device || '–'}` },
                    { label: 'Time', num: true, sortBy: 'duration', render: (r) => dur(r.duration_s) }]} />
              ) : (
                <Table scroll sort={sort} onSort={(k) => setSort(nextSort(sort, k, []))} onRow={(r) => f.go('person', { key: r.person_key })} rows={d.rows} empty="Nobody matches this preset in these dates." cols={[
                  { label: 'Who', cls: 'nw', render: who },
                  { label: 'Phone', cls: 'mono nw', render: (r) => r.phone10 || <span className="muted">–</span> },
                  { label: 'City', cls: 'nw', render: (r) => r.city || '–' },
                  { label: 'Matching visits', num: true, sortBy: 'visits', render: (r) => num(r.visits) },
                  { label: 'Last match', cls: 'nw', sortBy: 'last_seen', render: (r) => dt(r.last_seen) },
                  { label: 'Best outcome', cls: 'nw', render: (r) => <Badge tone={STAGE_TONE[r.stage]}>{STAGE[r.stage]}</Badge> },
                  { label: 'Orders', num: true, sortBy: 'orders', render: (r) => num(r.orders) },
                  { label: 'Latest visit', cls: 'mono nw', render: (r) => <a href={`#session/${encodeURIComponent(r.latest_session)}`} onClick={(e) => { e.preventDefault(); e.stopPropagation(); f.go('session', { key: r.latest_session }) }}>{r.latest_session.slice(0, 10)}…</a> }]} />
              )}
              <Pager total={d.total} limit={limit} offset={offset} setOffset={setOffset} setLimit={setLimit} />
            </Card>
          </>
        )
      }}
    </Loading>
  )
}

export default function JourneyPresets() {
  const f = useFilters()
  const [rev, setRev] = useState(0)
  const list = useApi('/journey-presets', { rev }, { scoped: false })
  const counts = useApi('/journey-presets/counts', { rev })
  const [open, setOpen] = usePersisted('presets.open', null)
  const [editing, setEditing] = useState(null)
  const [msg, setMsg] = useState('')
  const fileRef = useRef(null)
  const reload = () => setRev((x) => x + 1)
  const remove = async (p) => {
    if (!window.confirm(`Delete the preset “${p.name}”?`)) return
    await api(`/journey-presets/${p.id}`, { method: 'DELETE' })
    if (open === p.id) setOpen(null)
    reload()
  }
  const importFile = async (file) => {
    setMsg('')
    try {
      const data = JSON.parse(await file.text())
      const r = await api('/journey-presets/import', { method: 'POST', body: { presets: Array.isArray(data) ? data : data.presets || [] } })
      setMsg(`Imported ${r.added} preset${r.added === 1 ? '' : 's'}${r.skipped ? `; ${r.skipped} skipped because a preset with that name already exists` : ''}.`)
      reload()
    } catch (e) { setMsg(`Could not import: ${e.message}`) }
  }
  return (
    <Loading state={list}>
      {({ presets, actions, max_steps: maxSteps }) => {
        const labels = Object.fromEntries(actions.map((a) => [a.action, a.label]))
        const c = counts.data?.counts || {}
        const sel = presets.find((p) => p.id === open)
        return (
          <>
            <div className="chip-row">
              <button type="button" className="btn primary" onClick={() => { setEditing(EMPTY); setOpen(null) }}>+ New preset</button>
              <a className="btn" href="/api/journey-presets/export" download>Export presets</a>
              <button type="button" className="btn" onClick={() => fileRef.current?.click()}>Import presets…</button>
              <input ref={fileRef} type="file" accept="application/json,.json" style={{ display: 'none' }} onChange={(e) => { if (e.target.files[0]) importFile(e.target.files[0]); e.target.value = '' }} />
              <span className="muted" style={{ fontSize: 12 }}>A preset is a list of actions; it finds every visit that did them. Counts follow the dates, device and hidden-traffic filters.</span>
            </div>
            {msg && <div className="banner ok">{msg}</div>}
            {editing && <Editor key={editing.id || 'new'} initial={editing} actions={actions} labels={labels} maxSteps={maxSteps} onCancel={() => setEditing(null)} onSaved={(id) => { setEditing(null); setOpen(id); reload() }} />}
            <div className="grid g2">
              {presets.map((p) => {
                const n = c[p.id]
                return (
                  <Card key={p.id} title={p.name} sub={p.note || (p.source === 'built-in' ? 'built in · edit or delete it like any other' : '')}
                    right={p.source === 'built-in' ? <Badge>built in</Badge> : null}>
                    <div style={{ display: 'grid', gap: 8 }}>
                      <StepChips d={p.definition} labels={labels} />
                      <div style={{ fontSize: 14 }}>
                        {!n ? <span className="muted">counting…</span> : n.error ? <span className="badge bad">{n.error}</span>
                          : <span><b>{num(n.visits)}</b> visits · {num(n.people)} people · {num(n.ordered)} ordered{n.revenue ? ` (${inr(n.revenue)})` : ''} <span className="muted">· {pct(n.of_all, 1)} of all visits</span></span>}
                      </div>
                      <div className="chip-row">
                        <button type="button" className="btn small primary" aria-pressed={open === p.id} onClick={() => { setOpen(open === p.id ? null : p.id); setEditing(null) }}>{open === p.id ? 'Hide sessions' : 'Show sessions'}</button>
                        <button type="button" className="btn small" onClick={() => { setEditing({ ...p, note: p.note || '' }); setOpen(null); window.scrollTo(0, 0) }}>Edit</button>
                        <button type="button" className="btn small" onClick={() => { setEditing({ name: `${p.name} (copy)`, note: p.note || '', definition: p.definition }); setOpen(null); window.scrollTo(0, 0) }}>Copy</button>
                        <button type="button" className="btn small danger" onClick={() => remove(p)}>Delete</button>
                      </div>
                    </div>
                  </Card>
                )
              })}
            </div>
            {!presets.length && !editing && <div className="empty">No presets yet. Press “New preset” to make one.</div>}
            {sel && <Matches key={sel.id} preset={sel} labels={labels} onClose={() => setOpen(null)} />}
            {f.includeExcluded && <div className="muted" style={{ fontSize: 12 }}>Hidden internal traffic is included in these counts (“All traffic shown” is on).</div>}
          </>
        )
      }}
    </Loading>
  )
}

import { KEY_LABEL, num, pct, useApi, useFilters } from '../../api'
import { Card, Chips, Loading } from '../../ui'

const UNITS = [{ value: 'key', label: 'Key actions' }, { value: 'name', label: 'Every event' }, { value: 'page', label: 'Pages' }]
const label = (ev, unit) => (unit === 'key' ? KEY_LABEL[ev] || ev : unit === 'page' ? `${ev} page` : ev)

/** The journey builder: pick an event, then the event that came next, and the next, as a chain. */
export default function Chain({ steps, setSteps, unit, setUnit, mode, setMode, onlyOrdered, setOnlyOrdered }) {
  const f = useFilters()
  const s = useApi('/deeper/chain', { step: steps.length ? steps : undefined, unit, mode, only_ordered: onlyOrdered || undefined })
  return (
    <>
      <div className="chip-row">
        <span className="muted" style={{ fontSize: 12 }}>Events are</span>
        <Chips value={unit} onChange={(v) => { setUnit(v); setSteps([]) }} options={UNITS} />
        <span className="muted" style={{ fontSize: 12 }}>Each step happens</span>
        <Chips value={mode} onChange={setMode} options={[{ value: 'eventually', label: 'any time after the one before' }, { value: 'next', label: 'right after the one before' }]} />
        <label className="muted" style={{ fontSize: 12 }}><input type="checkbox" checked={onlyOrdered} onChange={(e) => setOnlyOrdered(e.target.checked)} /> Only visits that ordered</label>
        {steps.length > 0 && <button type="button" className="btn" onClick={() => setSteps([])}>Start again</button>}
      </div>
      <Loading state={s}>
        {(d) => (
          <div className="grid g2">
            <Card title="The chain" sub={steps.length ? `${num(d.total)} visits had at least one event in these dates` : 'pick the first event on the right'}>
              {!steps.length && <div className="muted">Nothing picked yet. Choose where the journey starts.</div>}
              <div style={{ display: 'grid', gap: 6 }}>
                {d.steps.map((x, i) => (
                  <div key={i} style={{ display: 'grid', gap: 2 }}>
                    {i > 0 && <div className="muted" style={{ textAlign: 'center' }}>↓ {mode === 'next' ? 'right after' : 'then'}</div>}
                    <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: '8px 10px', display: 'grid', gap: 4 }}>
                      <div className="row-between">
                        <b>{i + 1}. {label(x.event, unit)}</b>
                        {i === steps.length - 1 && <button type="button" className="btn small" onClick={() => setSteps(steps.slice(0, -1))} aria-label="Remove this step">Remove ✕</button>}
                      </div>
                      <div className="mini-bar"><i style={{ width: `${Math.max(1, x.of_all * 100)}%` }} /></div>
                      <div className="muted" style={{ fontSize: 12 }}>
                        {num(x.sessions)} visits · {pct(x.of_all, 1)} of all{i > 0 ? ` · ${pct(x.of_prev, 0)} of the step before` : ''} · {num(x.ordered)} ordered ({pct(x.sessions ? x.ordered / x.sessions : 0, 0)})
                      </div>
                    </div>
                  </div>
                ))}
                {steps.length > 0 && (
                  <div className="muted" style={{ fontSize: 12 }}>
                    {num(d.ended)} of the {num(d.last)} visits that reached the last step did nothing more.
                    {unit === 'name' && <> <button type="button" className="btn small" onClick={() => f.go('events', { event: steps[steps.length - 1] })}>See these events →</button></>}
                  </div>
                )}
              </div>
            </Card>
            <Card title={steps.length ? 'What happened next' : 'Where does the journey start?'}
              sub={steps.length ? 'the event that came right after the last step · click one to add it to the chain' : 'visits that did each event, most common first'}>
              {!d.next.length ? <div className="muted">{steps.length ? 'Nothing came next: the visits ended here.' : 'No events in these dates.'}</div> : (
                <div style={{ display: 'grid', gap: 6, maxHeight: 560, overflow: 'auto' }}>
                  {d.next.map((n) => {
                    const base = steps.length ? d.last || 1 : d.total || 1
                    return (
                      <button key={n.ev} type="button" className="pop-item" style={{ display: 'grid', gap: 2, textAlign: 'left' }} onClick={() => setSteps([...steps, n.ev])}>
                        <span className="row-between"><b>{label(n.ev, unit)}</b><span>{num(n.sessions)}</span></span>
                        <span className="mini-bar"><i style={{ width: `${Math.max(1, (n.sessions / base) * 100)}%` }} /></span>
                        {steps.length > 0 && <span className="muted" style={{ fontSize: 12 }}>{pct(n.sessions / base, 0)} of the visits at the last step{n.ordered ? ` · ${n.ordered} ordered` : ''}</span>}
                      </button>
                    )
                  })}
                </div>
              )}
            </Card>
          </div>
        )}
      </Loading>
    </>
  )
}

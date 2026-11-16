import { useState } from 'react'
import Icon from './Icon'
import Popover from './Popover'

/** One control for range + comparison, like Google Analytics: presets, custom dates and a Compare switch. */
export default function DatePicker({ presets, active, from, to, rangeText, prevText, compare, setCompare, setRange, first, last, canCompare, note }) {
  const [cf, setCf] = useState(from)
  const [ct, setCt] = useState(to)
  return (
    <Popover align="right" width={330} trigger={({ open, toggle }) => (
      <button type="button" className="pill-btn" aria-expanded={open} aria-haspopup="dialog" onClick={() => { setCf(from); setCt(to); toggle() }}>
        <Icon name="calendar" size={18} />
        <span>{active || 'Custom'}<small> · {rangeText}</small></span>
        <Icon name="chevron" size={16} />
      </button>
    )}>
      {(close) => (
        <>
          <div className="pop-title">Date range</div>
          {presets.map(([label, f, t]) => (
            <button key={label} type="button" className={`pop-item ${active === label ? 'on' : ''}`} onClick={() => { setRange(f, t); close() }}>
              {label}{active === label && <Icon name="check" size={16} />}
            </button>
          ))}
          <div className="pop-sep" />
          <div className="pop-title">Custom range</div>
          <div className="row-between" style={{ gap: 8 }}>
            <input className="field" type="date" min={first} max={last} value={cf} onChange={(e) => setCf(e.target.value)} aria-label="From date" />
            <span className="muted">→</span>
            <input className="field" type="date" min={first} max={last} value={ct} onChange={(e) => setCt(e.target.value)} aria-label="To date" />
          </div>
          <div style={{ padding: '0 10px 6px' }}>
            <button type="button" className="btn small primary" disabled={!cf || !ct || cf > ct} onClick={() => { setRange(cf, ct); close() }}>Apply</button>
          </div>
          <div className="pop-sep" />
          <label className="row-between" style={{ cursor: canCompare ? 'pointer' : 'default' }}>
            <span><b style={{ fontWeight: 500 }}>Compare</b><br /><small className="muted">{canCompare ? `with ${prevText}` : 'pick a date range to compare'}</small></span>
            <span className="switch"><input type="checkbox" checked={compare && canCompare} disabled={!canCompare} onChange={(e) => setCompare(e.target.checked)} /><i /></span>
          </label>
          {note && <><div className="pop-sep" /><div className="muted" style={{ padding: '2px 10px 6px', fontSize: 12 }}>{note}</div></>}
        </>
      )}
    </Popover>
  )
}

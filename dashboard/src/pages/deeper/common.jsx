import { num } from '../../api'

/** Ranked horizontal bars. items: [{ name, count, label? }] */
export function Bars({ items, total, empty = 'Nothing here.', unit = '', onPick, active }) {
  if (!items || !items.length) return <div className="muted">{empty}</div>
  const max = Math.max(...items.map((i) => i.count), 1)
  return (
    <div className="mini-list">
      {items.map((i) => (
        <div key={i.name} className="mini-row" style={onPick ? { cursor: 'pointer', opacity: active && active !== i.name ? 0.55 : 1 } : undefined}
          role={onPick ? 'button' : undefined} tabIndex={onPick ? 0 : undefined} onClick={onPick ? () => onPick(i.name) : undefined} onKeyDown={onPick ? (e) => { if (e.key === 'Enter') onPick(i.name) } : undefined}>
          <span className="name" title={i.label || i.name}>{i.label || i.name}</span>
          <span className="val">{num(i.count)}{unit}{total ? ` · ${Math.round((i.count / total) * 100)}%` : ''}</span>
          <span className="mini-bar"><i style={{ width: `${(i.count / max) * 100}%` }} /></span>
        </div>
      ))}
    </div>
  )
}

export const NotBuilt = () => <div className="banner err">These tables are not built yet. Press <b>Refresh</b> (top right) to build them.</div>

export const rate = (n, d) => (d ? `${((n / d) * 100).toFixed(d < 50 ? 0 : 1)}%` : '–')
export const secs = (s) => (s == null ? '–' : s < 60 ? `${Math.round(s)} s` : s < 3600 ? `${Math.floor(s / 60)} min ${Math.round(s % 60)} s` : `${(s / 3600).toFixed(1)} h`)
export const hours = (h) => (h == null ? '–' : h < 1 ? `${Math.round(h * 60)} min` : h < 48 ? `${h.toFixed(1)} h` : `${(h / 24).toFixed(1)} days`)

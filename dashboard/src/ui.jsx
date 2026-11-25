import { memo, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal, flushSync } from 'react-dom'
import Popover from './components/Popover'

/* ---------- metric glossary: shown as hover/focus help next to labels ---------- */
export const GLOSSARY = {
  sessions: 'One visit to the site or app (a unique session id). One person can have several sessions.',
  browsers: 'Distinct devices/browsers (visitor ids). Someone using phone and laptop counts twice here.',
  people: 'Distinct accounts, or anonymous browsers that never logged in. Browsers are merged into an account once the person logs in.',
  logins: 'Visits in which someone logged in (phone OTP or Google). The several events of one login count once. A login is new when the account was created within an hour of it.',
  orders: 'Valid orders only: not cancelled / payment pending, not a ₹1 test order, and not excluded.',
  revenue: 'Order totals of valid, non-excluded orders (after discounts, before refunds).',
  aov: 'Average order value = revenue ÷ orders.',
  cart: 'Sessions where something was added to the cart.',
  cartRate: 'Share of sessions that added something to the cart.',
  checkout: 'Sessions that opened the checkout page.',
  quiz: 'Sessions that finished the skin quiz. Older tracking logged completions without a start event, so completions can exceed starts.',
  bounce: 'Sessions with at most one page view and no clicks, scrolls, searches or other actions: the visitor landed and left.',
  avgSession: 'Average length of sessions that lasted more than 0 seconds.',
  firstTouch: 'Credits an order to the very first visit of the buyer (the campaign that brought them), not just the session where they paid.',
  engaged: 'Sessions with 5+ events or a product view.',
  repeat: 'A customer who ordered on at least two different days. Several orders on the same day (split or retried orders) do not count.',
  ltv: 'Lifetime value: total revenue from a customer so far. Young business, so this is early and will grow.',
  reachable: 'People with a phone number on file (from login or checkout), so they can be contacted.',
  nudge: 'Orders whose basket is 70-99% of the chosen threshold: a small add-on would push them over it.',
  segment: 'Where a person is in the journey: Buyer, Abandoned checkout, Cart no checkout, Quiz done, Engaged browser or Visitor.',
}

export const Help = ({ id, text }) => (
  <span className="help" tabIndex={0} data-tip={text || GLOSSARY[id]} aria-label={text || GLOSSARY[id]}>ⓘ</span>
)

export const Card = ({ title, sub, right, children, style, help }) => (
  <section className="card" style={style}>
    {(title || right) && (
      <div className="card-head">
        <div>
          <h3>{title}{help && <> <Help id={help} /></>}</h3>
          {sub && <div className="sub">{sub}</div>}
        </div>
        <div className="card-actions">{right}<span className="copy-slot" /></div>
      </div>
    )}
    {children}
  </section>
)

/** Change vs the previous period. kind 'count' → relative %, 'rate' → percentage-point difference. */
export function delta(cur, prev, kind = 'count') {
  if (prev === null || prev === undefined || cur === null || cur === undefined) return null
  if (kind === 'rate') {
    const d = (cur - prev) * 100
    if (Math.abs(d) < 0.05) return { dir: 0, text: 'no change' }
    return { dir: d > 0 ? 1 : -1, text: `${d > 0 ? '+' : ''}${d.toFixed(1)} pts` }
  }
  if (!prev) return cur ? { dir: 1, text: 'new' } : null
  const c = ((cur - prev) / prev) * 100
  if (Math.abs(c) < 0.5) return { dir: 0, text: 'no change' }
  return { dir: c > 0 ? 1 : -1, text: `${c > 0 ? '+' : ''}${Math.abs(c) >= 100 ? c.toFixed(0) : c.toFixed(1)}%` }
}

export const Delta = ({ d, goodWhen = 'up' }) => {
  if (!d) return null
  const good = d.dir === 0 || goodWhen === null ? null : (d.dir > 0) === (goodWhen === 'up')
  const arrow = d.dir > 0 ? '▲' : d.dir < 0 ? '▼' : '■'
  return (
    <span className="delta" title="Compared with the previous period of the same length">
      <span className={good === null ? '' : good ? 'ok' : 'bad'}>{arrow}</span> {d.text}
    </span>
  )
}

/** `onClick` makes the whole tile a button (for example, to open the rows behind the number). */
export const Kpi = ({ label, value, note, help, d, goodWhen, big, onClick, hint }) => (
  <div className={`kpi ${big ? 'big' : ''}${onClick ? ' click' : ''}`} title={hint}
    {...(onClick ? { role: 'button', tabIndex: 0, onClick, onKeyDown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick() } } } : {})}>
    <div className="label">{label}{help && <> <Help id={help} /></>}</div>
    <div className="value">{value}</div>
    <div className="note">{d ? <><Delta d={d} goodWhen={goodWhen} /> <span className="muted">vs previous</span></> : null}{d && note ? ' · ' : ''}{note}</div>
  </div>
)

export const Skeleton = () => (
  <div className="skeleton-wrap" aria-busy="true" aria-label="Loading">
    <div className="skeleton-row">{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton" style={{ height: 84 }} />)}</div>
    <div className="skeleton" style={{ height: 260 }} />
    <div className="skeleton" style={{ height: 180 }} />
  </div>
)

export const Loading = ({ state, children }) => {
  if (state.error) return <div className="banner err">Could not load: {state.error}</div>
  if (!state.data) return <Skeleton />
  return children(state.data)
}

export const Badge = ({ tone, children }) => <span className={`badge ${tone || ''}`}>{children}</span>

export const verdictTone = { Winning: 'good', Converting: 'good', Promising: 'warn', 'No carts - review': 'bad', 'Too early': '' }

/** Next server-side sort state when a header is clicked: same key flips direction, a new key starts descending (ascending for text). */
export const nextSort = (cur, key, textKeys = []) => (cur.key === key ? { key, dir: cur.dir === 'desc' ? 'asc' : 'desc' } : { key, dir: textKeys.includes(key) ? 'asc' : 'desc' })

/** Plain text of a rendered <table> as tab-separated lines (pastes straight into Excel / Google Sheets). Checkbox columns, help icons and sort arrows are left out. */
export function tableToTsv(table) {
  const clean = (s) => String(s ?? '').replace(/\s+/g, ' ').trim()
  const cell = (el) => {
    const c = el.cloneNode(true)
    c.querySelectorAll('.help, .arrow, .sr-only').forEach((n) => n.remove())
    return clean(c.textContent)
  }
  const lines = []
  table.querySelectorAll('tr').forEach((tr) => {
    const cells = [...tr.children].filter((c) => !c.classList.contains('sel'))
    if (cells.length) lines.push(cells.map(cell).join('\t'))
  })
  return lines.join('\n')
}

async function writeClipboard(text) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    const ta = document.createElement('textarea')  // fallback for non-secure contexts / blocked clipboard API
    ta.value = text
    ta.style.cssText = 'position:fixed;opacity:0'
    document.body.appendChild(ta)
    ta.select()
    let ok = false
    try { ok = document.execCommand('copy') } catch { ok = false }
    ta.remove()
    return ok
  }
}

/** Copies a table to the clipboard. `getTable()` returns the <table> element; `prepare()` (optional) runs first, e.g. to draw rows that are not on screen yet. */
export function CopyBtn({ getTable, prepare }) {
  const [state, setState] = useState('')
  const go = async () => {
    if (prepare) await prepare()
    const t = getTable()
    const ok = t ? await writeClipboard(tableToTsv(t)) : false
    setState(ok ? 'ok' : 'fail')
    setTimeout(() => setState(''), 2000)
  }
  return <button type="button" className="btn small copy-btn" onClick={go} title="Copy this table to the clipboard (paste into Excel or Google Sheets)">{state === 'ok' ? 'Copied ✓' : state === 'fail' ? 'Copy failed' : '⧉ Copy'}</button>
}

/** Wraps any hand-written <table> so it gets a Copy button too. */
export function CopyTable({ children, cls, menu, hiddenLabels }) {
  const box = useRef(null)
  const slot = useCopySlot(box)
  const btn = <>{menu}<CopyBtn getTable={() => box.current?.querySelector('table')} /></>
  return (
    <div className="tbl" data-hidden={hiddenLabels && hiddenLabels.length ? JSON.stringify(hiddenLabels) : undefined}>
      {slot ? createPortal(btn, slot) : <div className="copy-row">{btn}</div>}
      <div className={cls} ref={box}>{children}</div>
    </div>
  )
}

/** Where a table's Copy button goes: the header of the card it sits in (when it is that card's only table), else a slim row above the table. */
function useCopySlot(box) {
  const [slot, setSlot] = useState(null)
  useEffect(() => {
    const card = box.current?.closest('.card')
    const target = card?.querySelector(':scope > .card-head .copy-slot')
    setSlot(target && card.querySelectorAll('.tbl').length === 1 ? target : null)
  })
  return slot
}

/* ---------- choosing which columns of a table to show (remembered per table in this browser) ---------- */
const colId = (c) => c.key || c.label
const store = {
  get(k) { try { return JSON.parse(localStorage.getItem(k)) } catch { return null } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)) } catch { /* private window: the choice just is not kept */ } },
  del(k) { try { localStorage.removeItem(k) } catch { /* ignore */ } },
}

/** Which columns of a table are shown. A column can be marked `hidden` (off until chosen) or `essential` (kept by "Essentials"); columns with no label (pictures) always show,
 *  and so does the first labelled column (it names the row). The choice and any saved views are kept per table key. */
export function useColumns(key, cols) {
  const k = `mi.cols.${key}`
  const sk = `mi.colsets.${key}`
  const [saved, setSaved] = useState(() => store.get(k))
  const [sets, setSets] = useState(() => store.get(sk) || [])
  const pickable = cols.filter((c) => c.label)
  const locked = pickable.length ? colId(pickable[0]) : null
  const isOn = (c) => {
    if (!c.label || colId(c) === locked) return true
    if (!saved || !saved.known || !saved.known.includes(colId(c))) return !c.hidden  // never chosen, or a column added later: its default
    return saved.on.includes(colId(c))
  }
  const visible = cols.filter(isOn)
  const defaults = pickable.filter((c) => !c.hidden).map(colId)
  const essentials = (pickable.some((c) => c.essential) ? pickable.filter((c) => c.essential) : pickable.filter((c) => !c.hidden).slice(0, 6)).map(colId)
  const setOn = (ids) => { const v = { on: [...new Set([locked, ...ids].filter(Boolean))], known: pickable.map(colId) }; setSaved(v); store.set(k, v) }
  const reset = () => { setSaved(null); store.del(k) }
  const saveSet = (name) => {
    const n = name.trim().slice(0, 40)
    if (!n) return
    const next = [...sets.filter((x) => x.name !== n), { name: n, on: pickable.filter(isOn).map(colId) }]
    setSets(next); store.set(sk, next)
  }
  const dropSet = (name) => { const next = sets.filter((x) => x.name !== name); setSets(next); store.set(sk, next) }
  const shown = pickable.filter(isOn).length
  return { visible, pickable, isOn, locked, setOn, reset, defaults, essentials, sets, saveSet, dropSet, shown, total: pickable.length, changed: Boolean(saved),
    worth: pickable.length > 4 || pickable.some((c) => c.hidden), hiddenLabels: pickable.filter((c) => !isOn(c)).map((c) => String(c.label)) }
}

/** The "Columns" button of a table: tick what to show, jump to All / Essentials, keep named views. */
export function ColumnsMenu({ cc }) {
  const [name, setName] = useState('')
  if (!cc.worth) return null
  return (
    <Popover width={300} trigger={({ open, toggle }) => (
      <button type="button" className={`btn small cols-btn${open ? ' on' : ''}`} onClick={toggle} aria-expanded={open} title="Choose which columns to show in this table">
        ▦ Columns{cc.changed || cc.pickable.some((c) => c.hidden) ? <span className="cols-count">{cc.shown}/{cc.total}</span> : null}
      </button>
    )}>
      <div className="cols-panel">
        <div className="chip-row" style={{ marginBottom: 6 }}>
          <button type="button" className="btn small" onClick={() => cc.setOn(cc.pickable.map(colId))}>All</button>
          <button type="button" className="btn small" onClick={() => cc.setOn(cc.essentials)}>Essentials</button>
          <button type="button" className="btn small" onClick={cc.reset} disabled={!cc.changed}>Reset</button>
          <span className="muted" style={{ fontSize: 12, marginLeft: 'auto' }}>{cc.shown} of {cc.total}</span>
        </div>
        <div className="cols-list">
          {cc.pickable.map((c) => (
            <label key={colId(c)} className="cols-item" title={colId(c) === cc.locked ? 'This column names the row, so it always shows' : undefined}>
              <input type="checkbox" checked={cc.isOn(c)} disabled={colId(c) === cc.locked}
                onChange={(e) => cc.setOn(e.target.checked ? [...cc.pickable.filter(cc.isOn).map(colId), colId(c)] : cc.pickable.filter((x) => cc.isOn(x) && colId(x) !== colId(c)).map(colId))} />
              <span>{c.label}</span>{c.hidden && <span className="muted cols-extra">extra</span>}
            </label>
          ))}
        </div>
        <div className="cols-sets">
          {cc.sets.map((v) => (
            <span key={v.name} className="chip-row" style={{ gap: 2 }}>
              <button type="button" className="chip" onClick={() => cc.setOn(v.on)} title="Show this saved set of columns">{v.name}</button>
              <button type="button" className="icon-x" onClick={() => cc.dropSet(v.name)} aria-label={`Delete the view ${v.name}`} title="Delete this view">✕</button>
            </span>
          ))}
          <form className="chip-row" onSubmit={(e) => { e.preventDefault(); cc.saveSet(name); setName('') }}>
            <input className="field" value={name} onChange={(e) => setName(e.target.value)} placeholder="Save these columns as…" aria-label="Name for this set of columns" style={{ flex: 1, minWidth: 0 }} />
            <button type="submit" className="btn small" disabled={!name.trim()}>Save</button>
          </form>
        </div>
      </div>
    </Popover>
  )
}

const CHUNK = 200
/** One table row. Large tables skip redrawing rows whose data and selection did not change (ticking one box no longer redraws thousands of rows). */
const Row = memo(function Row({ r, id, cols, idOf, onRow, rowClass, selectable, isSel, onToggle }) {
  return (
    <tr className={`${onRow ? 'click' : ''} ${rowClass ? rowClass(r) : ''}`} onClick={onRow ? () => onRow(r) : undefined}
      tabIndex={onRow ? 0 : undefined} role={onRow ? 'link' : undefined}
      onKeyDown={onRow ? (e) => { if ((e.key === 'Enter' || e.key === ' ') && e.target === e.currentTarget) { e.preventDefault(); onRow(r) } } : undefined}>
      {selectable && <td className="sel" onClick={(e) => e.stopPropagation()}><input type="checkbox" aria-label="Select row" checked={isSel} onChange={() => onToggle(id)} /></td>}
      {cols.map((c) => (
        <td key={idOf(c)} className={`${c.num ? 'num' : ''} ${c.cls || ''}`}>
          {c.render ? c.render(r) : r[c.key] ?? '–'}
        </td>
      ))}
    </tr>
  )
}, (a, b) => a.big && b.big && a.r === b.r && a.isSel === b.isSel && a.selectable === b.selectable && a.sig === b.sig)

/** Table with click-to-sort headers and optional row selection.
 *  `scroll`: the table scrolls inside a box (both ways) with the column headings pinned; rows are added as you scroll down.
 *  Columns: { label, key?, sortBy? (field name or fn), num?, render?, cls? }  - sortable when key or sortBy is set.
 *  Client sort by default; pass `sort` ({key, dir}) + `onSort(key)` for server-side sorting of paginated data. */
export function Table({ cols, rows, onRow, empty = 'Nothing here for this selection. Try a wider date range or turn off “Hide internal & bot traffic”.', rowClass, selectable, selected, onToggle, onToggleAll, rowId, sort, onSort, scroll, id: tableId }) {
  const [local, setLocal] = useState(null)
  const cc = useColumns(tableId || cols.filter((c) => c.label).map((c) => c.label).join('|').slice(0, 160), cols)
  const vis = cc.visible
  const [shown, setShown] = useState(CHUNK)
  const wrap = useRef(null)
  const tail = useRef(null)
  const slot = useCopySlot(wrap)
  const [edge, setEdge] = useState('')  // 'l' / 'r': there are more columns to scroll to on that side (shown as a fade)
  useEffect(() => {
    const el = wrap.current
    if (!el) return undefined
    const upd = () => setEdge(`${el.scrollLeft > 2 ? 'l' : ''}${el.scrollLeft + el.clientWidth < el.scrollWidth - 2 ? 'r' : ''}`)
    upd()
    el.addEventListener('scroll', upd, { passive: true })
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(upd) : null
    ro?.observe(el)
    return () => { el.removeEventListener('scroll', upd); ro?.disconnect() }
  }, [rows, cols])
  const server = typeof onSort === 'function'
  const sortOf = (c) => c.sortBy ?? c.key
  const idOf = (c) => c.key || c.label
  const data = useMemo(() => {
    if (server || !local || !rows) return rows
    const c = cols.find((x) => idOf(x) === local.id)
    const sb = c && sortOf(c)
    if (!sb) return rows
    const get = typeof sb === 'function' ? sb : (r) => r[sb]
    const m = local.dir === 'asc' ? 1 : -1
    return [...rows].sort((a, b) => {
      const x = get(a); const y = get(b)
      if (x == null && y == null) return 0
      if (x == null) return 1
      if (y == null) return -1
      return (typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y), 'en', { numeric: true, sensitivity: 'base' })) * m
    })
  }, [rows, local, cols, server])
  const count = data ? data.length : 0
  useEffect(() => { setShown(CHUNK); if (scroll && wrap.current) wrap.current.scrollTop = 0 }, [rows]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {  // draw the next chunk when the end of the drawn rows comes near
    if (!tail.current || shown >= count || typeof IntersectionObserver === 'undefined') return undefined
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) setShown((n) => n + CHUNK) }, { root: scroll ? wrap.current : null, rootMargin: '600px' })
    io.observe(tail.current)
    return () => io.disconnect()
  }, [shown, count, scroll])
  if (!rows || !rows.length) return <div className="empty">{empty}</div>
  const click = (c) => {
    const sb = sortOf(c)
    if (!sb) return
    if (server) { onSort(typeof sb === 'function' ? idOf(c) : sb); return }
    const id = idOf(c)
    if (!local || local.id !== id) {
      const v = typeof sb === 'function' ? sb(rows[0]) : rows[0][sb]
      setLocal({ id, dir: typeof v === 'number' ? 'desc' : 'asc', flipped: false })
    } else if (!local.flipped) setLocal({ id, dir: local.dir === 'desc' ? 'asc' : 'desc', flipped: true })
    else setLocal(null)
  }
  const dirOf = (c) => {
    const sb = sortOf(c)
    if (!sb) return null
    if (server) return sort && sort.key === (typeof sb === 'function' ? idOf(c) : sb) ? sort.dir : null
    return local && local.id === idOf(c) ? local.dir : null
  }
  const sig = vis.map(idOf).join('|')
  const ids = selectable ? data.map(rowId) : []
  const allOn = selectable && ids.length > 0 && ids.every((i) => selected.has(i))
  const showAll = () => { flushSync(() => setShown(count)) }  // copy includes rows that are not drawn yet
  return (
    <div className="tbl" data-edge={edge} data-hidden={cc.hiddenLabels.length ? JSON.stringify(cc.hiddenLabels) : undefined}>
    {(() => {
      const btn = <><ColumnsMenu cc={cc} /><CopyBtn getTable={() => wrap.current?.querySelector('table')} prepare={shown < count ? showAll : undefined} /></>
      return slot ? createPortal(btn, slot) : <div className="copy-row">{btn}</div>
    })()}
    <div className={`table-wrap${scroll ? ' scroll' : ''}`} ref={wrap}>
      <table>
        <thead>
          <tr>
            {selectable && <th className="sel"><input type="checkbox" aria-label="Select all rows" checked={allOn} onChange={(e) => onToggleAll(ids, e.target.checked)} /></th>}
            {vis.map((c) => {
              const d = dirOf(c)
              const can = !!sortOf(c)
              return (
                <th key={idOf(c)} className={`${c.num ? 'num' : ''} ${can ? 'sortable' : ''} ${d ? 'sorted' : ''}`} onClick={can ? () => click(c) : undefined}
                  aria-sort={d ? (d === 'asc' ? 'ascending' : 'descending') : undefined} title={can ? 'Click to sort' : undefined}>
                  {c.label}{c.help && <> <Help id={c.help} /></>}{d && <span className="arrow">{d === 'asc' ? '▲' : '▼'}</span>}
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {data.slice(0, shown).map((r, i) => {
            const id = selectable ? rowId(r) : i
            return <Row key={id} r={r} id={id} cols={vis} idOf={idOf} onRow={onRow} rowClass={rowClass} selectable={selectable} isSel={selectable ? selected.has(id) : false}
              onToggle={onToggle} big={count > 150} sig={sig} />
          })}
        </tbody>
      </table>
      {shown < count && <div ref={tail} className="muted" style={{ padding: '10px 4px', fontSize: 12 }}>Showing {shown.toLocaleString('en-IN')} of {count.toLocaleString('en-IN')} rows, more as you scroll…</div>}
    </div>
    </div>
  )
}

/** Download the rows as CSV. fields = [[header, key | fn(row)], ...] */
export function ExportBtn({ rows, fields: allFields, name }) {
  const ref = useRef(null)
  const [follow, setFollow] = useState(() => store.get('mi.exportShown') === true)
  if (!rows || !rows.length) return null
  const go = () => {
    let fields = allFields
    if (follow) {  // only what is on screen: drop the fields named like a column hidden in a table of this card
      const hidden = new Set()
      ref.current?.closest('.card')?.querySelectorAll('.tbl[data-hidden]').forEach((t) => { try { JSON.parse(t.dataset.hidden).forEach((l) => hidden.add(l.toLowerCase())) } catch { /* ignore */ } })
      if (hidden.size) fields = allFields.filter(([h]) => !hidden.has(String(h).toLowerCase()))
    }
    const esc = (v) => (v === null || v === undefined ? '' : `"${String(v).replace(/"/g, '""')}"`)
    const lines = [fields.map(([h]) => esc(h)).join(',')]
    rows.forEach((r) => lines.push(fields.map(([, k]) => esc(typeof k === 'function' ? k(r) : r[k])).join(',')))
    const url = URL.createObjectURL(new Blob(['﻿' + lines.join('\n')], { type: 'text/csv;charset=utf-8' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `${name}-${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }
  return (
    <span className="export-grp" ref={ref}>
      <button className="btn small" onClick={go} title="Download the rows loaded on this screen as a CSV file">Export CSV ({rows.length.toLocaleString('en-IN')} rows)</button>
      <label className="muted export-follow" title="When ticked, the CSV leaves out the columns you hid with the Columns button"><input type="checkbox" checked={follow} onChange={(e) => { setFollow(e.target.checked); store.set('mi.exportShown', e.target.checked) }} /> shown columns only</label>
    </span>
  )
}

/** Horizontal rate bar used inside table cells (single hue, thin, anchored left). */
export const RateBar = ({ v, max = 1, text }) => (
  <span>
    <span className="inline-bar" style={{ width: Math.max(1, Math.min(1, v / (max || 1)) * 70) }} />
    {text}
  </span>
)

export const ALL_ROWS = 5000
const PAGE_SIZES = [25, 50, 100, ALL_ROWS]
/** Prev / Next pager. Pass `setLimit` to also offer a rows-per-page choice including “All” (up to ALL_ROWS rows at a time). */
export function Pager({ total, limit, offset, setOffset, setLimit }) {
  if (!total) return null
  return (
    <div className="pager">
      {setLimit && (
        <label className="muted" style={{ fontSize: 12 }}>Rows{' '}
          <select className="field" value={limit} onChange={(e) => setLimit(+e.target.value)} aria-label="Rows per page">
            {[...new Set([...PAGE_SIZES, limit])].sort((a, b) => a - b).map((n) => <option key={n} value={n}>{n === ALL_ROWS ? 'All' : n}</option>)}
          </select>
        </label>
      )}
      <span>{offset + 1}–{Math.min(offset + limit, total)} of {total.toLocaleString('en-IN')}</span>
      <button className="btn small" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>Prev</button>
      <button className="btn small" disabled={offset + limit >= total} onClick={() => setOffset(offset + limit)}>Next</button>
      {limit >= ALL_ROWS && total > limit && <span className="muted" style={{ fontSize: 12, flexBasis: '100%', textAlign: 'right' }}>“All” shows up to {ALL_ROWS.toLocaleString('en-IN')} rows at a time. Use Next for the rest, or narrow the list with filters.</span>}
    </div>
  )
}

export function Chips({ options, value, onChange }) {
  return (
    <div className="chip-row">
      {options.map((o) => {
        const v = typeof o === 'string' ? o : o.value
        const l = typeof o === 'string' ? o : o.label
        return <button key={v} className={`chip ${value === v ? 'on' : ''}`} disabled={typeof o !== 'string' && o.disabled} onClick={() => onChange(v)}>{l}</button>
      })}
    </div>
  )
}

/** Debounced search box. */
export function Search({ value, onChange, placeholder }) {
  const [v, setV] = useState(value || '')
  return (
    <input className="field search-field" style={{ minWidth: 340 }} placeholder={placeholder} aria-label={placeholder} type="search" value={v}
      onChange={(e) => { setV(e.target.value); clearTimeout(Search.t); Search.t = setTimeout(() => onChange(e.target.value), 350) }} />
  )
}

export const chartTip = {
  contentStyle: { background: 'var(--surface-1)', border: '1px solid var(--border)', borderRadius: 8, color: 'var(--text-primary)', fontSize: 12 },
  labelStyle: { color: 'var(--text-secondary)' },
  itemStyle: { color: 'var(--text-primary)' },
  cursor: { fill: 'var(--surface-2)', opacity: 0.6 },
}
export const axis = { stroke: 'var(--grid)', tick: { fill: 'var(--text-muted)', fontSize: 11 }, tickLine: false }
export const SERIES = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)', 'var(--series-4)', 'var(--series-5)', 'var(--series-6)', 'var(--series-7)', 'var(--series-8)']
export const Legend = ({ items }) => (
  <div className="legend">{items.map(([label, color]) => <span key={label}><i style={{ background: color }} />{label}</span>)}</div>
)

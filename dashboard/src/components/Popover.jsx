import { useEffect, useRef, useState } from 'react'

/** Click-to-open popover. `trigger({ open, toggle })` renders the button; `children` may be a node or `(close) => node`. */
export default function Popover({ trigger, children, align = 'right', width, label = 'Options' }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const panel = useRef(null)
  const close = () => {
    setOpen(false)
    ref.current?.querySelector('button[aria-expanded]')?.focus()
  }
  useEffect(() => {
    if (!open) return undefined
    const first = panel.current?.querySelector('button:not(:disabled), input:not(:disabled), select:not(:disabled), a[href]') || panel.current
    first?.focus({ preventScroll: true })
    const onDown = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    const onKey = (e) => { if (e.key === 'Escape') close() }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey) }
  }, [open])
  return (
    <div className="pop" ref={ref}>
      {trigger({ open, toggle: () => setOpen((o) => !o) })}
      {open && <div className={`pop-panel ${align}`} style={{ width }} role="dialog" aria-label={label} tabIndex={-1} ref={panel}>{typeof children === 'function' ? children(close) : children}</div>}
    </div>
  )
}

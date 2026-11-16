import { useEffect, useRef, useState } from 'react'

/** Click-to-open popover. `trigger({ open, toggle })` renders the button; `children` may be a node or `(close) => node`. */
export default function Popover({ trigger, children, align = 'right', width }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    const onDown = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey) }
  }, [open])
  const close = () => setOpen(false)
  return (
    <div className="pop" ref={ref}>
      {trigger({ open, toggle: () => setOpen((o) => !o) })}
      {open && <div className={`pop-panel ${align}`} style={{ width }} role="dialog">{typeof children === 'function' ? children(close) : children}</div>}
    </div>
  )
}

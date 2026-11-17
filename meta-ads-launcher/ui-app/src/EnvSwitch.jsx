import { useEffect, useRef, useState } from 'react'
import Icon from './Icon'
import { api } from './api'

/** The environment pill. Click it, pick Sandbox or Production. (This UI window only; restarting goes back to .env.) */
export default function EnvSwitch({ env, onSwitched, startOpen = false }) {
  const [open, setOpen] = useState(!!startOpen)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const box = useRef(null)
  const prod = env.env === 'production'

  useEffect(() => {
    if (!open) return undefined
    const on = (e) => { if (box.current && !box.current.contains(e.target)) close() }
    document.addEventListener('mousedown', on)
    return () => document.removeEventListener('mousedown', on)
  }, [open])

  const close = () => { setOpen(false); setErr(null) }
  const choose = async (target) => {
    if (target === env.env) return close()
    setBusy(true); setErr(null)
    try { await api('/api/env', { method: 'POST', body: { env: target } }); close(); onSwitched() } catch (e) { setErr(e.message) }
    setBusy(false)
  }
  const row = (id, label, desc) => (
    <button type="button" className={`pop-item ${env.env === id ? 'on' : ''}`} onClick={() => choose(id)} disabled={busy || !env.ready?.[id]} title={env.ready?.[id] ? '' : 'Not set up in .env'}>
      <span><b style={{ fontWeight: 500 }}><span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', marginRight: 8, background: id === 'production' ? 'var(--critical)' : 'var(--good)' }} />{label}</b><br /><small className="muted">{desc}</small></span>
      {env.env === id && <Icon name="check" size={16} />}
    </button>
  )

  return (
    <span className="pop" ref={box}>
      <button type="button" className="pill-btn" aria-expanded={open} onClick={() => (open ? close() : setOpen(true))} title="Switch between Sandbox and Production">
        <span className={`dot ${prod ? 'prod' : ''}`} />{prod ? 'Production' : 'Sandbox'}<small>{env.account}</small><Icon name="chevron" size={16} />
      </button>
      {open && (
        <div className="pop-panel right" style={{ width: 320 }}>
          <div className="pop-title">Which ad account?</div>
          {row('sandbox', 'Sandbox', 'Practice account. Nothing is delivered or spent.')}
          {row('production', 'Production', 'Your real ad account.')}
          {err && <div className="banner err" style={{ margin: '8px 10px 4px' }}><div>{err}</div></div>}
          <div className="mini" style={{ padding: '8px 10px 4px' }}>Applies to this window only. Restarting goes back to <span className="mono">.env</span>.</div>
        </div>
      )}
    </span>
  )
}

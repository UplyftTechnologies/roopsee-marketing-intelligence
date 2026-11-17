import { useEffect, useRef, useState } from 'react'
import Icon from './Icon'
import { api } from './api'

/** The environment pill. Click it to switch between Sandbox and Production (this UI session only). */
export default function EnvSwitch({ env, onSwitched, startOpen = false }) {
  const [open, setOpen] = useState(startOpen)
  const [ask, setAsk] = useState(startOpen === 'prod') // showing the typed confirmation for production
  const [typed, setTyped] = useState('')
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

  const close = () => { setOpen(false); setAsk(false); setTyped(''); setErr(null) }
  const switchTo = async (target) => {
    setBusy(true); setErr(null)
    try { await api('/api/env', { method: 'POST', body: { env: target, confirm_text: typed } }); close(); onSwitched() } catch (e) { setErr(e.message) }
    setBusy(false)
  }
  const choose = (target) => {
    if (target === env.env) return close()
    if (target === 'production') { setAsk(true); return }
    switchTo('sandbox')
  }
  const row = (id, label, desc) => (
    <button type="button" className={`pop-item ${env.env === id ? 'on' : ''}`} onClick={() => choose(id)} disabled={!env.ready?.[id]} title={env.ready?.[id] ? '' : 'Not set up in .env'}>
      <span><b style={{ fontWeight: 500 }}><span className={`dot ${id === 'production' ? 'prod' : ''}`} style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', marginRight: 8, background: id === 'production' ? 'var(--critical)' : 'var(--good)' }} />{label}</b><br /><small className="muted">{desc}</small></span>
      {env.env === id && <Icon name="check" size={16} />}
    </button>
  )

  return (
    <span className="pop" ref={box}>
      <button type="button" className="pill-btn" aria-expanded={open} onClick={() => (open ? close() : setOpen(true))} title="Switch between Sandbox and Production">
        <span className={`dot ${prod ? 'prod' : ''}`} />{prod ? 'Production' : 'Sandbox'}<small>{env.account}</small><Icon name="chevron" size={16} />
      </button>
      {open && (
        <div className="pop-panel right" style={{ width: 340 }}>
          <div className="pop-title">Which ad account do you want to work on?</div>
          {row('sandbox', 'Sandbox', 'Practice account. Nothing is delivered or spent.')}
          {row('production', 'Production', 'Your real ad account. New things are still created paused.')}
          {ask && (
            <div style={{ padding: '8px 10px 4px' }}>
              <div className="pop-sep" />
              <div className="banner err" style={{ marginBottom: 8 }}><div>You are about to work on your <b>real ad account</b>. Type <b>PRODUCTION</b> to confirm.</div></div>
              <input className="field" style={{ width: '100%' }} autoFocus placeholder="PRODUCTION" value={typed} onChange={(e) => setTyped(e.target.value)} />
              <div className="row" style={{ marginTop: 8 }}>
                <button type="button" className="btn danger" disabled={busy || typed !== 'PRODUCTION'} onClick={() => switchTo('production')}>Switch to Production</button>
                <button type="button" className="btn" onClick={() => { setAsk(false); setTyped('') }}>Cancel</button>
              </div>
            </div>
          )}
          {err && <div className="banner err" style={{ margin: '8px 10px 4px' }}><div>{err}</div></div>}
          <div className="mini" style={{ padding: '8px 10px 4px' }}>Applies to this window only. Restarting the UI goes back to the setting in <span className="mono">.env</span>.</div>
        </div>
      )}
    </span>
  )
}

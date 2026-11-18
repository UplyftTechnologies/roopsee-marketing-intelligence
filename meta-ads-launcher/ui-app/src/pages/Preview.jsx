import { useEffect, useState } from 'react'
import { api } from '../api'
import { Banner } from '../ui'

/** Ask Meta to draw the ad in a real placement. */
export default function PreviewBtn({ ad }) {
  const [fmts, setFmts] = useState(null)
  const [fmt, setFmt] = useState('MOBILE_FEED_STANDARD')
  const [url, setUrl] = useState(null)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { api('/api/ads/preview-formats').then((r) => setFmts(r.formats)).catch(() => {}) }, [])
  const go = async () => {
    setBusy(true); setErr(null); setUrl(null)
    const body = { format: fmt }
    if (ad.creative_spec && !ad.kind) body.creative_spec = ad.creative_spec; else body.ad = ad
    try { setUrl((await api('/api/ads/preview', { method: 'POST', body })).url) } catch (e) { setErr(e.message) }
    setBusy(false)
  }
  return (
    <div className="stack">
      <div className="row">
        <select className="field" style={{ width: 'auto' }} value={fmt} onChange={(e) => setFmt(e.target.value)}>{(fmts || [{ id: fmt, label: fmt }]).map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}</select>
        <button type="button" className="btn small" disabled={busy} onClick={go}>{busy ? 'Asking Meta…' : 'Preview this ad'}</button>
      </div>
      {err && <Banner tone="err">{err}</Banner>}
      {url && <iframe title="Meta preview" src={url} width="420" height="640" style={{ border: '1px solid var(--border, #ddd)', borderRadius: 8, maxWidth: '100%' }} />}
    </div>
  )
}


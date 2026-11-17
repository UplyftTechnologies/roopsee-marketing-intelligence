import { useEffect, useState } from 'react'
import { api } from './api'
import { Badge, CopyBtn, Loading, useLoad } from './ui'

/** An image from Meta's servers. Falls back to a plain box if the link has expired or fails. */
export function MetaImg({ src, alt = '', className = '', style }) {
  const [bad, setBad] = useState(false)
  useEffect(() => setBad(false), [src])
  if (!src || bad) return <div className={`noimg ${className}`} style={style}>{src ? 'preview not available' : 'no preview'}</div>
  return <img src={src} alt={alt} className={className} style={style} loading="lazy" onError={() => setBad(true)} />
}

/** Full-size image with its hash and details. */
export function Lightbox({ img, onClose, actions }) {
  useEffect(() => {
    const on = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', on)
    return () => window.removeEventListener('keydown', on)
  }, [onClose])
  return (
    <div className="lb-bg" onClick={onClose} role="dialog" aria-modal="true" aria-label="Image preview">
      <div className="lb" onClick={(e) => e.stopPropagation()}>
        <div className="lb-img"><MetaImg src={img.full} alt={img.name || img.hash} style={{ maxHeight: '68vh', maxWidth: '100%', objectFit: 'contain' }} /></div>
        <div className="lb-side">
          <b style={{ fontSize: 15 }}>{img.name || 'Image'}</b>
          <div className="chip-row">
            {img.width && <Badge>{img.width} × {img.height}</Badge>}
            {img.created && <Badge>added {img.created}</Badge>}
          </div>
          <div><div className="lf-label">Image hash</div><div className="mono" style={{ wordBreak: 'break-all' }}>{img.hash}</div></div>
          <div className="row"><CopyBtn text={img.hash} label="Copy hash" />{img.full && <a className="btn small" href={img.full} target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>Open full size</a>}</div>
          {actions && <div className="row">{actions(img)}</div>}
          <div style={{ flex: 1 }} />
          <button type="button" className="btn" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  )
}

/** Browse the images already in the ad account: thumbnails with their hash; click for the actual image. */
export function MetaImageGrid({ actions, limit = 60 }) {
  const [st, reload] = useLoad(() => api('/api/meta-images'))
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(null)
  const [more, setMore] = useState(limit)
  return (
    <Loading state={st}>
      {(d) => {
        const ql = q.trim().toLowerCase()
        const rows = d.images.filter((x) => !ql || (x.name || '').toLowerCase().includes(ql) || x.hash.includes(ql))
        return (
          <>
            <div className="row" style={{ marginBottom: 10 }}>
              <input className="field" style={{ maxWidth: 260 }} placeholder="Find by name or hash…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search images" />
              <button type="button" className="btn small" onClick={async () => { await api('/api/meta-images?refresh=true'); reload() }}>Refresh</button>
              <span className="muted" style={{ fontSize: 12 }}>{rows.length} image(s) in {d.account} · click one to see it full size</span>
            </div>
            {rows.length === 0 ? <div className="empty">No images found.</div> : (
              <div className="thumbs">
                {rows.slice(0, more).map((i) => (
                  <div key={i.hash} className="thumb">
                    <button type="button" className="thumb-btn" onClick={() => setOpen(i)} title="See the full image"><MetaImg src={i.thumb} alt={i.name || i.hash} /></button>
                    <div>
                      <b title={i.name}>{(i.name || 'Image').slice(0, 26)}</b>
                      <span className="muted">{i.width}×{i.height} · {i.created}</span>
                      <span className="mono muted" title={i.hash}>{i.hash.slice(0, 10)}…</span>
                      <div className="row" style={{ gap: 6 }}><CopyBtn text={i.hash} label="Hash" />{actions && actions(i)}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
            {rows.length > more && <div style={{ marginTop: 10 }}><button type="button" className="btn small" onClick={() => setMore(more + 60)}>Show more ({rows.length - more} left)</button></div>}
            {open && <Lightbox img={open} onClose={() => setOpen(null)} actions={actions} />}
          </>
        )
      }}
    </Loading>
  )
}

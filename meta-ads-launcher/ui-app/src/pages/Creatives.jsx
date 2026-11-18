import { useRef, useState } from 'react'
import { api } from '../api'
import { Badge, Card, Field, Loading, useLoad } from '../ui'
import { MetaImageGrid } from '../MetaImages'

export default function Creatives({ ctx }) {
  const [st, reload] = useLoad(() => api('/api/creatives'))
  const [theme, setTheme] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const input = useRef(null)

  const upload = async (files) => {
    if (!theme.trim()) { setMsg({ tone: 'err', text: 'Type a theme first (for example acne). Each image is saved under that theme.' }); return }
    setBusy(true); setMsg(null)
    const ok = []; const bad = []
    for (const f of files) {
      const fd = new FormData(); fd.append('file', f); fd.append('category', theme.trim().toLowerCase().replace(/[^a-z0-9_]/g, '_'))
      try { const r = await api('/api/creatives', { method: 'POST', body: fd }); ok.push(`${r.key} (${r.width}x${r.height})`) } catch (e) { bad.push(`${f.name}: ${e.message}`) }
    }
    setBusy(false); reload()
    setMsg({ tone: bad.length ? 'err' : 'ok', text: [ok.length ? `Saved ${ok.join(', ')}.` : '', ...bad].filter(Boolean).join(' ') })
  }

  return (
    <>
      <Card title="Add images" sub="Saved as creatives/<theme>/RS_<THEME>_001 and so on. Use 1080px or wider; square or 4:5 works best.">
        <div className="fgrid">
          <Field label="Theme (what the images are about)" hint="For example acne, pigmentation, trust, retargeting">
            <input className="field" value={theme} onChange={(e) => setTheme(e.target.value)} placeholder="acne" list="themes" />
          </Field>
        </div>
        <datalist id="themes">{(st.data || []).map((c) => c.category).filter((v, i, a) => a.indexOf(v) === i).map((c) => <option key={c} value={c} />)}</datalist>
        <div className="drop" style={{ marginTop: 12 }} onClick={() => input.current.click()} onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); upload([...e.dataTransfer.files]) }}>
          {busy ? 'Uploading…' : 'Drop images here, or click to choose (you can pick several)'}
          <input ref={input} type="file" accept=".jpg,.jpeg,.png" multiple hidden onChange={(e) => { upload([...e.target.files]); e.target.value = '' }} />
        </div>
        {msg && <div className={`banner ${msg.tone}`} style={{ marginTop: 10 }}><div>{msg.text}</div></div>}
      </Card>

      <Card title="Your images" sub="Each image can be used in any number of campaigns. It is uploaded to Meta once and reused">
        <Loading state={st}>
          {(items) => items.length === 0 ? <div className="empty">No images yet.</div> : (
            <div className="thumbs">
              {items.map((i) => (
                <div key={i.path} className="thumb">
                  <img src={'/' + i.path} alt={i.key} loading="lazy" />
                  <div>
                    <b>{i.key}</b>
                    <span className="muted">{i.category} · {i.width}×{i.height}</span>
                    <div className="chip-row">
                      <Badge tone={i.hash ? 'good' : ''}>{i.hash ? 'on Meta' : 'not uploaded'}</Badge>
                      {i.used && <Badge>used in an ad</Badge>}
                      {i.width && i.width < 1080 && <Badge tone="warn">small</Badge>}
                    </div>
                    {<button type="button" className="btn small" onClick={() => ctx.go('new', { image: i.path })}>Use in a campaign</button>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Loading>
      </Card>

      <Card title="Already on Meta" sub="The images in your ad account, shown as Meta has them, with the hash to reuse. Click an image to see it full size.">
        <MetaImageGrid actions={(i) => <button type="button" className="btn small" onClick={() => ctx.go('new', { metahash: i.hash })}>Use in a campaign</button>} />
      </Card>
    </>
  )
}

import { useState } from 'react'
import Icon from '../Icon'
import { api } from '../api'
import { Badge, Banner, Field } from '../ui'
import { MetaImg } from '../MetaImages'
import PreviewBtn from './Preview'

/** An ad that carries a whole creative copied from Meta or imported as JSON (carousel, video, catalog, dynamic, existing post ...). */
export default function SpecAdCard({ ad, i, a, all, o, upd, remove, toggleSet, onSave }) {
  const sm = ad.summary || {}
  const [imgs, setImgs] = useState(null)
  const [edit, setEdit] = useState(null) // text of the JSON editor while open
  const [err, setErr] = useState(null)
  const [prev, setPrev] = useState(false)
  const loadImgs = async () => {
    try { setImgs((await api('/api/meta-images?hashes=' + (sm.image_hashes || []).slice(0, 6).join(','))).images || []) } catch (e) { setErr(e.message) }
  }
  const apply = async () => {
    let spec
    try { spec = JSON.parse(edit) } catch (e) { setErr('Not valid JSON: ' + e.message); return }
    try {
      const r = await api('/api/ads/describe', { method: 'POST', body: { creative_spec: spec } })
      setA2(r)
    } catch (e) { setErr(e.message) }
  }
  const setA2 = (r) => { upd(i, 'creative_spec', r.creative_spec); upd(i, 'summary', r.summary); setEdit(null); setErr(null) }
  return (
    <div className="adcard" style={{ gridTemplateColumns: '1fr' }}>
      <div className="stack">
        <div className="row">
          <Badge tone="good">{sm.kind || 'Ad'}</Badge>
          {sm.cards > 0 && <Badge>{sm.cards} cards</Badge>}
          {ad.label && <span className="muted" style={{ fontSize: 12.5 }}>from “{ad.label.slice(0, 60)}”</span>}
          <button type="button" className="btn small danger right" onClick={remove}><Icon name="trash" size={13} /> Remove</button>
        </div>
        <div className="fgrid">
          <Field label="Ad name (optional)" hint="Shown in Ads Manager. Empty uses an automatic name"><input className="field" value={ad.name || ''} placeholder="For example Skincare | Serum | Video 1" onChange={(e) => upd(i, 'name', e.target.value)} /></Field>
        </div>
        {a.adsets.length > 1 && (
          <div><span className="lf-label">Show this ad in</span>
            <div className="row" style={{ gap: 14 }}>{a.adsets.map((s, j) => <label key={s.uid} className="chk"><input type="checkbox" checked={(ad.sets || all).includes(s.uid)} onChange={() => toggleSet(i, s.uid)} />Ad set {j + 1}</label>)}</div></div>
        )}
        <div style={{ fontSize: 13 }}>
          {sm.texts?.length > 0 && <div><span className="muted">Text{sm.text_count > 1 ? ` (${sm.text_count} versions)` : ''}: </span>{sm.texts[0].slice(0, 160)}{sm.texts[0].length > 160 ? '…' : ''}</div>}
          {sm.titles?.length > 0 && <div><span className="muted">Headline{sm.title_count > 1 ? ` (${sm.title_count} versions)` : ''}: </span>{sm.titles[0]}</div>}
          {sm.link && <div><span className="muted">Goes to: </span>{sm.link}</div>}
          <div className="muted">{sm.image_hashes?.length || 0} image(s), {sm.video_ids?.length || 0} video(s) already on Meta</div>
        </div>
        {sm.image_hashes?.length > 0 && !imgs && <button type="button" className="btn small" onClick={loadImgs}>Show the images</button>}
        {imgs && <div className="picker">{imgs.map((m) => <div key={m.hash} className="pick"><MetaImg src={m.thumb || m.full} alt="" /></div>)}</div>}
        <div className="row">
          <button type="button" className="btn small" onClick={() => setEdit(edit == null ? JSON.stringify(ad.creative_spec, null, 2) : null)}>{edit == null ? 'Edit the creative (expert)' : 'Close editor'}</button>
          <button type="button" className="btn small" onClick={() => setPrev(!prev)}>{prev ? 'Hide preview' : 'Show a Meta preview'}</button>
          <button type="button" className="btn small" onClick={onSave}>Save as template</button>
        </div>
        {prev && <PreviewBtn ad={ad} />}
        {edit != null && (
          <div className="stack">
            <textarea className="field mono" rows={14} spellCheck={false} value={edit} onChange={(e) => setEdit(e.target.value)} />
            <div className="row"><button type="button" className="btn small primary" onClick={apply}>Apply changes</button><span className="mini">Meta's own creative JSON. Page and Instagram ids are set for you; Meta checks it before anything is created.</span></div>
          </div>
        )}
        {err && <Banner tone="err">{err}</Banner>}
      </div>
    </div>
  )
}

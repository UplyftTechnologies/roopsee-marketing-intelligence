import { useEffect, useRef, useState } from 'react'
import Icon from '../Icon'
import { api } from '../api'
import { Badge, Banner, Field } from '../ui'
import { MetaImageGrid, MetaImg } from '../MetaImages'
import { Counter, DestPick, audLabel } from './Wizard'
import PreviewBtn from './Preview'

export const KIND_INFO = {
  video: { label: 'Video', help: 'One video with text and a button.' },
  carousel: { label: 'Carousel', help: '2 to 10 cards people swipe through, each with its own picture, headline and link.' },
  post: { label: 'Existing post', help: 'Boost a post that is already on your Facebook Page.' },
  dynamic: { label: 'Advantage+ (many versions)', help: 'Give several images, texts and headlines. Meta tries the combinations and learns the best.' },
  catalog: { label: 'Catalog (products)', help: 'Show products from your catalog automatically.' },
}

const mediaSrc = (m) => (m?.preview || (m?.file && m.kind === 'image' ? '/' + m.file : ''))

/** Pick a picture or a video: upload one, choose one already on Meta (or, for video, your Meta videos). */
function MediaPick({ kind, value, onChange, label }) {
  const [open, setOpen] = useState(false)
  const [vids, setVids] = useState(null)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const input = useRef(null)
  const isVid = kind === 'video'
  const upload = async (f) => {
    if (!f) return
    setBusy(true); setErr(null)
    const fd = new FormData(); fd.append('file', f)
    try { const r = await api('/api/media', { method: 'POST', body: fd }); onChange(isVid ? { file: r.file, kind: 'video', name: r.name } : { file: r.file, kind: 'image', name: r.name }) } catch (e) { setErr(e.message) }
    setBusy(false)
  }
  const loadVids = async () => { setOpen(!open); if (!vids && !open) { try { setVids((await api('/api/meta/videos')).videos) } catch (e) { setErr(e.message) } } }
  return (
    <div className="stack">
      <span className="lf-label">{label}</span>
      <div className="row" style={{ alignItems: 'flex-start' }}>
        {value ? (
          <div className="pick" style={{ width: 96, height: 96, flex: 'none' }}>
            {mediaSrc(value) ? <img src={mediaSrc(value)} alt="" /> : value.thumb ? <MetaImg src={value.thumb} alt="" /> : <div className="noimg" style={{ fontSize: 11 }}>{isVid ? 'video' : 'image'}<br />{(value.name || value.hash || value.video_id || '').toString().slice(0, 14)}</div>}
          </div>
        ) : <div className="pick" style={{ width: 96, height: 96, flex: 'none', display: 'grid', placeItems: 'center' }}><span className="muted" style={{ fontSize: 11 }}>none yet</span></div>}
        <div className="stack">
          <div className="row">
            <button type="button" className="btn small" disabled={busy} onClick={() => input.current.click()}>{busy ? 'Uploading…' : isVid ? 'Upload a video' : 'Upload a picture'}</button>
            <input ref={input} type="file" hidden accept={isVid ? '.mp4,.mov' : '.jpg,.jpeg,.png'} onChange={(e) => { upload(e.target.files[0]); e.target.value = '' }} />
            <button type="button" className="btn small" onClick={isVid ? loadVids : () => setOpen(!open)}>{open ? 'Close' : isVid ? 'Pick a video from Meta' : 'Pick from Meta'}</button>
            {value && <button type="button" className="btn small danger" onClick={() => onChange(null)}>Clear</button>}
          </div>
          {value?.file && <span className="mini">Uploaded to Meta when you create the ad. {isVid ? 'Videos can take a few minutes to process.' : ''}</span>}
        </div>
      </div>
      {err && <Banner tone="err">{err}</Banner>}
      {open && !isVid && <MetaImageGrid limit={24} actions={(i) => <button type="button" className="btn small primary" onClick={() => { onChange({ hash: i.hash, kind: 'image', name: i.name, preview: i.full || i.thumb }); setOpen(false) }}>Use this</button>} />}
      {open && isVid && vids && (vids.length === 0 ? <div className="muted">No videos in this ad account yet.</div> : (
        <div className="pick-list" style={{ maxHeight: 260 }}>{vids.map((v) => (
          <div key={v.id} className="list-row">
            {v.thumb ? <MetaImg src={v.thumb} alt="" style={{ width: 54, height: 54, objectFit: 'cover', borderRadius: 6 }} /> : null}
            <span className="grow"><b>{(v.title || 'Video').slice(0, 60)}</b><br /><span className="muted">{v.seconds}s</span></span>
            <button type="button" className="btn small primary" onClick={() => { onChange({ video_id: v.id, thumb: v.thumb, kind: 'video', name: v.title }); setOpen(false) }}>Use this</button>
          </div>))}</div>
      ))}
    </div>
  )
}

/** A list of short texts (Advantage+): add, edit, remove, up to a limit. */
function TextList({ label, items, onChange, max = 5, limit, placeholder, area }) {
  const list = items.length ? items : ['']
  return (
    <div className="stack">
      <span className="lf-label">{label} <span className="muted">({items.filter((x) => x.trim()).length}/{max})</span></span>
      {list.map((t, i) => (
        <div key={i} className="row">
          {area ? <textarea className="field" style={{ flex: 1 }} value={t} placeholder={placeholder} onChange={(e) => onChange(list.map((x, j) => (j === i ? e.target.value : x)))} />
            : <input className="field" style={{ flex: 1 }} value={t} placeholder={placeholder} onChange={(e) => onChange(list.map((x, j) => (j === i ? e.target.value : x)))} />}
          {limit && <span className={`cnt ${t.length > limit ? 'over' : ''}`}>{t.length}/{limit}</span>}
          {list.length > 1 && <button type="button" className="btn small danger" onClick={() => onChange(list.filter((_, j) => j !== i))}>×</button>}
        </div>
      ))}
      {list.length < max && <div><button type="button" className="btn small" onClick={() => onChange([...list, ''])}><Icon name="plus" size={12} /> Add another</button></div>}
    </div>
  )
}

function PostPick({ value, onChange }) {
  const [posts, setPosts] = useState(null)
  const [err, setErr] = useState(null)
  const load = async () => { setErr(null); try { setPosts((await api('/api/meta/posts')).posts) } catch (e) { setErr(e.message) } }
  return (
    <div className="stack">
      <Field label="Post id" hint="Looks like 1175723048967774_122127934839430745. Pick one below or paste it."><input className="field" value={value || ''} onChange={(e) => onChange(e.target.value.trim())} /></Field>
      {!posts && <div><button type="button" className="btn small" onClick={load}>Show my Page's recent posts</button></div>}
      {err && <Banner tone="err">{err}</Banner>}
      {posts && (
        <div className="pick-list" style={{ maxHeight: 300 }}>{posts.map((p) => (
          <div key={p.id} className="list-row">
            {p.picture ? <MetaImg src={p.picture} alt="" style={{ width: 54, height: 54, objectFit: 'cover', borderRadius: 6 }} /> : null}
            <span className="grow"><b>{p.text || '(no text)'}</b><br /><span className="muted">{p.date}</span></span>
            <button type="button" className={`btn small ${value === p.id ? '' : 'primary'}`} onClick={() => onChange(p.id)}>{value === p.id ? 'Chosen' : 'Use this'}</button>
          </div>))}</div>
      )}
    </div>
  )
}

function CatalogPick({ ad, upd }) {
  const [cats, setCats] = useState(null)
  const [sets, setSets] = useState(null)
  const [err, setErr] = useState(null)
  const loadCats = async () => { setErr(null); try { setCats((await api('/api/meta/catalogs')).catalogs) } catch (e) { setErr(e.message) } }
  const loadSets = async (id) => { try { setSets((await api('/api/meta/product-sets?catalog=' + id)).sets) } catch (e) { setErr(e.message) } }
  return (
    <div className="stack">
      <Field label="Product set id" hint="The group of products to show. Find it in Commerce Manager under Catalog > Sets, or pick it below."><input className="field" value={ad.product_set_id || ''} onChange={(e) => upd({ product_set_id: e.target.value.trim() })} /></Field>
      {!cats && <div><button type="button" className="btn small" onClick={loadCats}>Look up my catalogs</button></div>}
      {err && <Banner>{err} You can still paste the product set id above.</Banner>}
      {cats && cats.map((c) => <div key={c.id} className="list-row"><span className="grow"><b>{c.name}</b> <span className="muted">{c.products ?? ''} products</span></span><button type="button" className="btn small" onClick={() => loadSets(c.id)}>Show its sets</button></div>)}
      {sets && sets.map((x) => <div key={x.id} className="list-row"><span className="grow"><b>{x.name}</b> <span className="muted">{x.products ?? ''} products</span></span><button type="button" className="btn small primary" onClick={() => upd({ product_set_id: x.id, product_set_name: x.name })}>Use this set</button></div>)}
    </div>
  )
}

export const newFormatAd = (kind, key, o) => {
  const d = o.destinations[0]?.url || ''
  const base = { kind, ad_key: key, sets: null, destination: d, cta: kind === 'catalog' ? 'SHOP_NOW' : 'LEARN_MORE' }
  if (kind === 'video') return { ...base, video: null, thumb_image: null, primary_text: '', headline: '', description: '' }
  if (kind === 'carousel') return { ...base, primary_text: '', optimized: true, end_card: false, cards: [{ image: null, headline: '', description: '', link: '' }, { image: null, headline: '', description: '', link: '' }] }
  if (kind === 'post') return { ...base, post_id: '' }
  if (kind === 'dynamic') return { ...base, images: [], videos: [], bodies: [''], titles: [''], descriptions: [], ctas: ['LEARN_MORE'] }
  return { ...base, product_set_id: '', primary_text: '', headline: '{{product.name}}', description: '{{product.price}}', multiple_images: false }
}

/** The card for a video / carousel / post / Advantage+ / catalog ad. */
export default function FormatCard({ ad, i, a, o, all, upd, toggleSet, remove, onSave }) {
  const set = (patch) => upd(i, patch)
  const info = KIND_INFO[ad.kind]
  const [prev, setPrev] = useState(false)
  const cards = ad.cards || []
  const setCard = (j, patch) => set({ cards: cards.map((c, k) => (k === j ? { ...c, ...patch } : c)) })
  const move = (j, d) => { const n = j + d; if (n < 0 || n >= cards.length) return; const c = [...cards];[c[j], c[n]] = [c[n], c[j]]; set({ cards: c }) }
  return (
    <div className="adcard" style={{ gridTemplateColumns: '1fr' }}>
      <div className="stack">
        <div className="row">
          <Badge tone="good">{info?.label || ad.kind}</Badge>
          <button type="button" className="btn small danger right" onClick={remove}><Icon name="trash" size={13} /> Remove</button>
        </div>
        <div className="fgrid">
          <Field label="Ad ID (must be new, like RS_SKINCARE_001)"><input className="field" value={ad.ad_key || ''} onChange={(e) => set({ ad_key: e.target.value.toUpperCase() })} /></Field>
          <Field label="Ad name (optional)" hint="Shown in Ads Manager. Empty uses the Ad ID"><input className="field" value={ad.name || ''} placeholder={ad.ad_key || ''} onChange={(e) => set({ name: e.target.value })} /></Field>
        </div>
        {a.adsets.length > 1 && (
          <div><span className="lf-label">Show this ad in</span>
            <div className="row" style={{ gap: 14 }}>{a.adsets.map((s, j) => <label key={s.uid} className="chk" title={audLabel(o, s)}><input type="checkbox" checked={(ad.sets || all).includes(s.uid)} onChange={() => toggleSet(i, s.uid)} />Ad set {j + 1}</label>)}</div></div>
        )}

        {ad.kind === 'video' && (
          <>
            <MediaPick kind="video" label="Video" value={ad.video} onChange={(v) => set({ video: v })} />
            <MediaPick kind="image" label="Cover picture (optional when the video already has one)" value={ad.thumb_image} onChange={(v) => set({ thumb_image: v })} />
            <Counter label="Main text" value={ad.primary_text} limit={125}><textarea className="field" value={ad.primary_text} onChange={(e) => set({ primary_text: e.target.value })} /></Counter>
            <div className="fgrid">
              <Counter label="Headline" value={ad.headline} limit={40}><input className="field" value={ad.headline} onChange={(e) => set({ headline: e.target.value })} /></Counter>
              <Field label="Button"><select className="field" value={ad.cta} onChange={(e) => set({ cta: e.target.value })}>{o.ctas.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}</select></Field>
            </div>
            <Counter label="Description under the headline (optional)" value={ad.description} limit={30}><input className="field" value={ad.description || ''} onChange={(e) => set({ description: e.target.value })} /></Counter>
            <DestPick o={o} value={ad.destination} onChange={(v) => set({ destination: v })} />
          </>
        )}

        {ad.kind === 'carousel' && (
          <>
            <Counter label="Main text" value={ad.primary_text} limit={125}><textarea className="field" value={ad.primary_text} onChange={(e) => set({ primary_text: e.target.value })} /></Counter>
            <DestPick o={o} value={ad.destination} onChange={(v) => set({ destination: v })} />
            <div className="row"><label className="chk"><input type="checkbox" checked={!!ad.optimized} onChange={(e) => set({ optimized: e.target.checked })} />Let Meta put the best cards first</label>
              <label className="chk"><input type="checkbox" checked={!!ad.end_card} onChange={(e) => set({ end_card: e.target.checked })} />Show a final card with my Page</label></div>
            {cards.map((c, j) => (
              <fieldset className="set" key={j}>
                <legend>Card {j + 1}</legend>
                <MediaPick kind="image" label="Picture" value={c.image} onChange={(v) => setCard(j, { image: v })} />
                <div className="fgrid" style={{ marginTop: 8 }}>
                  <Counter label="Headline" value={c.headline} limit={40}><input className="field" value={c.headline} onChange={(e) => setCard(j, { headline: e.target.value })} /></Counter>
                  <Counter label="Description (optional)" value={c.description} limit={20}><input className="field" value={c.description || ''} onChange={(e) => setCard(j, { description: e.target.value })} /></Counter>
                  <Field label="Link (empty = the page above)"><input className="field" value={c.link || ''} placeholder="https://roopsee.com/…" onChange={(e) => setCard(j, { link: e.target.value })} /></Field>
                </div>
                <div className="row" style={{ marginTop: 6 }}>
                  <button type="button" className="btn small" disabled={j === 0} onClick={() => move(j, -1)}>Move up</button>
                  <button type="button" className="btn small" disabled={j === cards.length - 1} onClick={() => move(j, 1)}>Move down</button>
                  <button type="button" className="btn small danger" disabled={cards.length <= 2} onClick={() => set({ cards: cards.filter((_, k) => k !== j) })}>Remove card</button>
                </div>
              </fieldset>
            ))}
            {cards.length < 10 && <div><button type="button" className="btn small" onClick={() => set({ cards: [...cards, { image: null, headline: '', description: '', link: '' }] })}><Icon name="plus" size={12} /> Add a card</button></div>}
          </>
        )}

        {ad.kind === 'post' && <PostPick value={ad.post_id} onChange={(v) => set({ post_id: v })} />}

        {ad.kind === 'dynamic' && (
          <>
            <fieldset className="set"><legend>Pictures</legend>
              <div className="row" style={{ flexWrap: 'wrap', gap: 10 }}>{(ad.images || []).map((m, j) => (
                <div key={j} className="pick" style={{ width: 84, height: 84 }}>{mediaSrc(m) ? <img src={mediaSrc(m)} alt="" /> : <div className="noimg" style={{ fontSize: 10 }}>{(m.hash || '').slice(0, 8)}</div>}
                  <button type="button" className="btn small danger" style={{ position: 'absolute', top: 2, right: 2, padding: '0 6px' }} onClick={() => set({ images: ad.images.filter((_, k) => k !== j) })}>×</button></div>))}</div>
              {(ad.images || []).length < 10 && <MediaPick kind="image" label="Add a picture" value={null} onChange={(v) => v && set({ images: [...(ad.images || []), v] })} />}
            </fieldset>
            <fieldset className="set"><legend>Videos (optional)</legend>
              <div className="row" style={{ flexWrap: 'wrap', gap: 10 }}>{(ad.videos || []).map((m, j) => <Badge key={j}>{(m.name || m.video_id || 'video').toString().slice(0, 24)}<button type="button" className="btn small" style={{ marginLeft: 6, padding: '0 6px' }} onClick={() => set({ videos: ad.videos.filter((_, k) => k !== j) })}>×</button></Badge>)}</div>
              {(ad.videos || []).length < 10 && <MediaPick kind="video" label="Add a video" value={null} onChange={(v) => v && set({ videos: [...(ad.videos || []), v] })} />}
            </fieldset>
            <TextList label="Main texts" items={ad.bodies || []} onChange={(v) => set({ bodies: v })} limit={125} area placeholder="What do you want to say?" />
            <TextList label="Headlines" items={ad.titles || []} onChange={(v) => set({ titles: v })} limit={40} placeholder="A short headline" />
            <TextList label="Descriptions (optional)" items={ad.descriptions || []} onChange={(v) => set({ descriptions: v })} limit={30} placeholder="A short line under the headline" />
            <div className="fgrid">
              <Field label="Button"><select className="field" value={(ad.ctas || ['LEARN_MORE'])[0]} onChange={(e) => set({ ctas: [e.target.value] })}>{o.ctas.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}</select></Field>
            </div>
            <DestPick o={o} value={ad.destination} onChange={(v) => set({ destination: v })} />
          </>
        )}

        {ad.kind === 'catalog' && (
          <>
            <CatalogPick ad={ad} upd={set} />
            <Counter label="Main text" value={ad.primary_text} limit={125}><textarea className="field" value={ad.primary_text} onChange={(e) => set({ primary_text: e.target.value })} /></Counter>
            <div className="fgrid">
              <Field label="Headline" hint="{{product.name}} fills in each product's name"><input className="field" value={ad.headline} onChange={(e) => set({ headline: e.target.value })} /></Field>
              <Field label="Line under it" hint="{{product.price}} fills in the price"><input className="field" value={ad.description} onChange={(e) => set({ description: e.target.value })} /></Field>
              <Field label="Button"><select className="field" value={ad.cta} onChange={(e) => set({ cta: e.target.value })}>{o.ctas.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}</select></Field>
            </div>
            <label className="chk"><input type="checkbox" checked={!!ad.multiple_images} onChange={(e) => set({ multiple_images: e.target.checked })} />Show several pictures per product</label>
            <DestPick o={o} value={ad.destination} onChange={(v) => set({ destination: v })} />
          </>
        )}

        <details className="more"><summary>More: tracking tags and preview</summary>
          <div className="stack" style={{ marginTop: 8 }}>
            <Field label="URL tags (optional)" hint="Leave empty to use the launcher's standard tags"><input className="field mono" value={ad.url_tags || ''} onChange={(e) => set({ url_tags: e.target.value })} placeholder="utm_source=facebook&utm_medium=paid_social&…" /></Field>
            <div><button type="button" className="btn small" onClick={() => setPrev(!prev)}>{prev ? 'Hide preview' : 'Show a Meta preview'}</button></div>
            {prev && <PreviewBtn ad={ad} />}
          </div>
        </details>
        <div className="row"><button type="button" className="btn small" onClick={onSave}>Save as template</button></div>
      </div>
    </div>
  )
}


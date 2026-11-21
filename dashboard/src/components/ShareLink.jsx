import { useState } from 'react'
import { shareLink, useFilters } from '../api'

/** Copies a link that opens this page with the same date range, traffic setting and filters, to send to a teammate. */
export default function ShareLink({ tab, state }) {
  const f = useFilters()
  const [done, setDone] = useState(false)
  const copy = async () => {
    const url = shareLink(tab, { from: f.from, to: f.to, hide: !f.includeExcluded, ...state })
    try { await navigator.clipboard.writeText(url); setDone(true); setTimeout(() => setDone(false), 2200) } catch { window.prompt('Copy this link', url) }
  }
  return <button type="button" className="btn" onClick={copy} title="Copy a link that opens this page with the same dates and filters">{done ? 'Link copied ✓' : 'Copy link'}</button>
}

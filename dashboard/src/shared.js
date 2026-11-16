import { useState } from 'react'
import { api, useFilters } from './api'

export const STAGE = ['Browsed', 'Viewed product', 'Added to cart', 'Reached checkout', 'Started payment', 'Ordered']
export const STAGE_TONE = ['', '', 'warn', 'warn', 'serious', 'good']

/** Adds one exclusion rule and refreshes; the API re-applies it in the background (a few seconds). */
export function useQuickExclude() {
  const f = useFilters()
  const [msg, setMsg] = useState('')
  const exclude = async (kind, value, note) => {
    if (!value) return
    try {
      const r = await api('/exclusions', { method: 'POST', body: { kind, value, note } })
      setMsg(r.added ? `Excluded ${kind} “${value}”. Rebuilding…` : `${kind} “${value}” is already in the exclusion list`)
      f.reloadMeta()
    } catch (e) { setMsg(`Failed: ${e.message}`) }
  }
  return { exclude, msg }
}

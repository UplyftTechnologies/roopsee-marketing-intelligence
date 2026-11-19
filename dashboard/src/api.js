import { createContext, useContext, useEffect, useState } from 'react'

export async function api(path, { method = 'GET', params, body } = {}) {
  const qs = new URLSearchParams()
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') qs.set(k, v)
  })
  const res = await fetch(`/api${path}${qs.toString() ? `?${qs}` : ''}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    let msg = res.statusText
    try { msg = (await res.json()).detail || msg } catch { /* ignore */ }
    throw new Error(msg)
  }
  return res.json()
}

/** useState that survives leaving the page and coming back (kept per browser tab in sessionStorage). `fresh` = ignore what was stored. */
export function usePersisted(key, initial, fresh = false) {
  const [v, setV] = useState(() => {
    if (!fresh) { try { const s = sessionStorage.getItem(`mi:${key}`); if (s != null) return JSON.parse(s) } catch { /* ignore */ } }
    return initial
  })
  useEffect(() => { try { sessionStorage.setItem(`mi:${key}`, JSON.stringify(v)) } catch { /* ignore */ } }, [key, v])
  return [v, setV]
}

/** Global filters shared by every tab. `tick` bumps after a refresh/exclusion apply so views reload. */
export const FilterCtx = createContext(null)
export const useFilters = () => useContext(FilterCtx)

/** Fetch with the global date range + include-excluded flag applied (pass `scoped: false` to skip). */
export function useApi(path, extra = {}, { scoped = true } = {}) {
  const f = useFilters()
  const [state, setState] = useState({ data: null, loading: true, error: null })
  const key = JSON.stringify([path, extra, scoped ? [f.from, f.to, f.includeExcluded] : null, f.tick])
  useEffect(() => {
    let live = true
    setState((s) => ({ ...s, loading: true, error: null }))
    const params = scoped
      ? { date_from: f.from, date_to: f.to, include_excluded: f.includeExcluded, ...extra }
      : extra
    api(path, { params })
      .then((data) => live && setState({ data, loading: false, error: null }))
      .catch((error) => live && setState({ data: null, loading: false, error: error.message }))
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  return state
}

const nf = new Intl.NumberFormat('en-IN')
export const num = (v) => (v === null || v === undefined ? '–' : nf.format(Math.round(v)))
export const inr = (v) => (v === null || v === undefined ? '–' : '₹' + nf.format(Math.round(v)))
export const pct = (v, d = 1) => (v === null || v === undefined ? '–' : (v * 100).toFixed(d) + '%')
export const dt = (v) => {
  if (!v) return '–'
  const d = new Date(v)
  return d.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: true })
}
export const tod = (v) => (v ? new Date(v).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: 'numeric', minute: '2-digit', second: '2-digit', hour12: true }) : '–')
export const day = (v) => (v ? new Date(v + (String(v).length === 10 ? 'T00:00:00' : '')).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' }) : '–')
export const dur = (s) => {
  if (!s && s !== 0) return '–'
  if (s < 60) return `${Math.round(s)}s`
  if (s < 3600) return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`
  if (s < 86400) return `${(s / 3600).toFixed(1)}h`
  return `${(s / 86400).toFixed(1)}d`
}
export const KEY_LABEL = {
  product_view: 'Product view', add_to_cart: 'Add to cart', view_cart: 'View cart', checkout_view: 'Checkout',
  address: 'Address', pay_started: 'Pay started', order_placed: 'Order placed', quiz_started: 'Quiz started',
  quiz_completed: 'Quiz done', login: 'Login', search: 'Search', wishlist: 'Wishlist', assistant: 'Assistant', app_open: 'App open',
}

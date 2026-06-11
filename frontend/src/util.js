export const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// "just now" / "2 min ago" / "1 hr ago" / "3 days ago" from an ISO timestamp.
export function relativeTime(iso) {
  if (!iso) return ''
  const then = new Date(iso).getTime()
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000))
  if (secs < 45) return 'just now'
  const mins = Math.round(secs / 60)
  if (mins < 60) return `${mins} min ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs} hr${hrs > 1 ? 's' : ''} ago`
  const days = Math.round(hrs / 24)
  return `${days} day${days > 1 ? 's' : ''} ago`
}

// Prefer the matching error message from a DRF error payload, else a fallback.
export function formatError(data, fallback = 'Something went wrong.') {
  if (!data) return fallback
  if (typeof data === 'string') return data
  if (data.detail) return data.detail
  return (
    Object.entries(data)
      .map(([field, msgs]) => `${field}: ${[].concat(msgs).join(' ')}`)
      .join(' ') || fallback
  )
}

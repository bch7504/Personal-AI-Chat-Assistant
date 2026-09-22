import { HANOI_TZ, formatClock, formatDateShort } from './datetime'

const PALETTE = ['#526ff5', '#8b5cf6', '#10b981', '#f59e0b', '#ef4444', '#06b6d4', '#ec4899']

function hanoiDateKey(date) {
  return new Intl.DateTimeFormat('en-CA', { timeZone: HANOI_TZ }).format(date)
}

export function getInitials(name) {
  return (name || '?').trim().split(/\s+/).map(w => w[0]).slice(0, 2).join('').toUpperCase()
}

export function getColor(id) {
  const key = String(id ?? '')
  let hash = 0
  for (let i = 0; i < key.length; i++) hash = (hash * 31 + key.charCodeAt(i)) >>> 0
  return PALETTE[hash % PALETTE.length]
}

export function formatTime(iso) {
  if (!iso) return ''
  const date = new Date(iso)
  const now = new Date()
  if (hanoiDateKey(date) === hanoiDateKey(now)) return formatClock(iso)
  const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000)
  if (hanoiDateKey(date) === hanoiDateKey(yesterday)) return 'Yesterday'
  return formatDateShort(iso)
}

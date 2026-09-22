// The whole app displays times in Hanoi time (Asia/Ho_Chi_Minh, UTC+7) regardless of the
// viewer's machine/browser timezone - dates are stored in UTC on the backend, this is the
// single place that converts them for display.
export const HANOI_TZ = 'Asia/Ho_Chi_Minh'

export function formatDateShort(iso) {
  if (!iso) return ''
  return new Intl.DateTimeFormat('en-US', { timeZone: HANOI_TZ, month: 'short', day: 'numeric' }).format(new Date(iso))
}

export function formatClock(iso) {
  if (!iso) return ''
  return new Intl.DateTimeFormat('en-US', { timeZone: HANOI_TZ, hour: 'numeric', minute: '2-digit' }).format(new Date(iso))
}

export function formatDateTime(iso) {
  if (!iso) return ''
  return new Intl.DateTimeFormat('en-US', {
    timeZone: HANOI_TZ, year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  }).format(new Date(iso))
}

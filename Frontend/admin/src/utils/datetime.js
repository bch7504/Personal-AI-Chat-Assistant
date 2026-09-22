export const HANOI_TZ = 'Asia/Ho_Chi_Minh'
export const formatDateShort = (iso) => iso ? new Intl.DateTimeFormat('en-US', { timeZone: HANOI_TZ, month: 'short', day: 'numeric' }).format(new Date(iso)) : ''
export const formatDateTime = (iso) => iso ? new Intl.DateTimeFormat('en-US', { timeZone: HANOI_TZ, year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(new Date(iso)) : ''
export const formatClock = (iso) => iso ? new Intl.DateTimeFormat('en-US', { timeZone: HANOI_TZ, hour: 'numeric', minute: '2-digit' }).format(new Date(iso)) : ''

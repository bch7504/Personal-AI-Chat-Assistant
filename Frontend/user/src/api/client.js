function configuredUrl(name, legacyName, localFallback) {
  const value = import.meta.env[name] || (legacyName ? import.meta.env[legacyName] : '')
  if (value) return value
  return localFallback
}

// This project is local-only, so built assets intentionally keep localhost defaults.
export const API_BASE_URL = configuredUrl('VITE_API_BASE_URL', 'VITE_API_URL', 'http://127.0.0.1:8000/api/v1')
export const WS_BASE_URL = configuredUrl('VITE_WS_BASE_URL', 'VITE_WS_URL', 'ws://127.0.0.1:8000/api/v1/ws')

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === 'string' ? detail : 'Request failed')
    this.status = status
    this.detail = detail
  }
}

const inFlightReads = new Map()

async function executeRequest(path, { method, body, token }) {
  const headers = { 'Content-Type': 'application/json' }
  if (token) headers.Authorization = `Bearer ${token}`
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const payload = await res.json().catch(() => null)
    throw new ApiError(res.status, payload?.detail || res.statusText)
  }
  if (res.status === 204) return null
  return res.json()
}

export function apiFetch(path, { method = 'GET', body, token } = {}) {
  const normalizedMethod = method.toUpperCase()
  if (normalizedMethod !== 'GET') return executeRequest(path, { method: normalizedMethod, body, token })

  // StrictMode and sibling widgets can mount together. Share the same GET promise so a single
  // browser tab never sends duplicate concurrent reads for the same authenticated resource.
  const requestKey = `${token || 'anonymous'}:${path}`
  const pending = inFlightReads.get(requestKey)
  if (pending) return pending
  const request = executeRequest(path, { method: normalizedMethod, body, token })
    .finally(() => inFlightReads.delete(requestKey))
  inFlightReads.set(requestKey, request)
  return request
}

const configuredApiUrl = import.meta.env.VITE_API_BASE_URL
export const API_BASE_URL = configuredApiUrl || 'http://127.0.0.1:8000/api/v1'

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === 'string' ? detail : 'Request failed')
    this.status = status
    this.detail = detail
  }
}

export async function apiFetch(path, { method = 'GET', body, token } = {}) {
  const headers = { 'Content-Type': 'application/json' }
  if (token) headers.Authorization = `Bearer ${token}`
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    throw new ApiError(response.status, payload?.detail || response.statusText)
  }
  if (response.status === 204) return null
  return response.json()
}

import { apiFetch } from './client'

export const listSupportGrants = (token, workspaceId) =>
  apiFetch(`/platform/support-grants${workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : ''}`, { token })

export const requestSupportGrant = (token, body) =>
  apiFetch('/platform/support-grants', { method: 'POST', token, body })

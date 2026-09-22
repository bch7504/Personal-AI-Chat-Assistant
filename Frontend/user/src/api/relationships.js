import { apiFetch } from './client'

export const listRelationships = (token, workspaceId, { query, includeArchived = false } = {}) => {
  const params = new URLSearchParams()
  if (query) params.set('q', query)
  if (includeArchived) params.set('include_archived', 'true')
  return apiFetch(`/workspaces/${workspaceId}/relationships${params.toString() ? `?${params}` : ''}`, { token })
}

export const createRelationship = (token, workspaceId, body) =>
  apiFetch(`/workspaces/${workspaceId}/relationships`, { method: 'POST', token, body })

export const updateRelationship = (token, workspaceId, relationshipId, body) =>
  apiFetch(`/workspaces/${workspaceId}/relationships/${relationshipId}`, { method: 'PATCH', token, body })

export const archiveRelationship = (token, workspaceId, relationshipId) =>
  apiFetch(`/workspaces/${workspaceId}/relationships/${relationshipId}`, { method: 'DELETE', token })

export const listExternalContacts = (token, workspaceId) =>
  apiFetch(`/workspaces/${workspaceId}/external-contacts`, { token })

export const createExternalContact = (token, workspaceId, body) =>
  apiFetch(`/workspaces/${workspaceId}/external-contacts`, { method: 'POST', token, body })

export const listPeopleInsights = (token, workspaceId, { query, segment = 'all', limit = 100 } = {}) => {
  const params = new URLSearchParams({ segment, limit: String(limit) })
  if (query) params.set('q', query)
  return apiFetch(`/workspaces/${workspaceId}/people-insights?${params}`, { token })
}

export const updatePeoplePreference = (token, workspaceId, userId, body) =>
  apiFetch(`/workspaces/${workspaceId}/people-insights/${userId}`, { method: 'PATCH', token, body })

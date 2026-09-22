import { apiFetch } from './client'

export const getStats = (token) => apiFetch('/admin/stats', { token })

export const getAIManagement = (token) => apiFetch('/admin/ai-management', { token })
export const updateAIManagement = (token, body) =>
  apiFetch('/admin/ai-management', { method: 'PATCH', token, body })
export const getSystemHealth = (token) => apiFetch('/admin/system-health', { token })
export const getAIUsage = (token, days = 7) => apiFetch(`/admin/ai-usage?days=${days}`, { token })
export const updateDailyBudget = (token, daily_token_budget) =>
  apiFetch('/admin/settings/budget', { method: 'PATCH', token, body: { daily_token_budget } })
export const listAuditLog = (
  token,
  { q = '', actorType = '', workspaceId = '', limit = 50, offset = 0 } = {},
) => {
  const params = new URLSearchParams({ limit, offset })
  if (q) params.set('q', q)
  if (actorType) params.set('actor_type', actorType)
  if (workspaceId) params.set('workspace_id', workspaceId)
  return apiFetch(`/admin/audit-log?${params}`, { token })
}

export const listUsers = (token, q) =>
  apiFetch(`/admin/users${q ? `?q=${encodeURIComponent(q)}` : ''}`, { token })

export const getCompany = token => apiFetch('/admin/company', { token })

export const listManagedWorkspaces = (token, organizationId) =>
  apiFetch(`/workspaces/${organizationId}/agent-workspaces`, { token })

export const createManagedWorkspace = (token, organizationId, body) =>
  apiFetch(`/workspaces/${organizationId}/agent-workspaces`, { method: 'POST', token, body })

export const updateManagedWorkspace = (token, organizationId, workspaceId, body) =>
  apiFetch(`/workspaces/${organizationId}/agent-workspaces/${workspaceId}`, {
    method: 'PATCH', token, body,
  })

export const assignManagedWorkspaceLead = (token, organizationId, workspaceId, email) =>
  apiFetch(`/workspaces/${organizationId}/agent-workspaces/${workspaceId}/lead`, {
    method: 'PATCH', token, body: { email },
  })

export const listManagedWorkspaceMembers = (token, organizationId, workspaceId) =>
  apiFetch(`/workspaces/${organizationId}/agent-workspaces/${workspaceId}/members`, { token })

export const addManagedWorkspaceMember = (token, organizationId, workspaceId, body) =>
  apiFetch(`/workspaces/${organizationId}/agent-workspaces/${workspaceId}/members`, {
    method: 'POST', token, body,
  })

export const revokeManagedWorkspaceMember = (
  token, organizationId, workspaceId, membershipId,
) => apiFetch(
  `/workspaces/${organizationId}/agent-workspaces/${workspaceId}/members/${membershipId}`,
  { method: 'DELETE', token },
)

export const updateUserRole = (token, userId, role) =>
  apiFetch(`/admin/users/${userId}/role`, { method: 'PATCH', token, body: { role } })

export const updateUserStatus = (token, userId, is_active) =>
  apiFetch(`/admin/users/${userId}/status`, { method: 'PATCH', token, body: { is_active } })

export const listConversations = (token) => apiFetch('/admin/conversations', { token })

export const getConversationMessages = (token, conversationId) =>
  apiFetch(`/admin/conversations/${conversationId}/messages`, { token })

export const deleteConversation = (token, conversationId) =>
  apiFetch(`/admin/conversations/${conversationId}`, { method: 'DELETE', token })

const scopedParams = (workspaceId, ownerId) => {
  const params = new URLSearchParams({ workspace_id: workspaceId })
  if (ownerId) params.set('owner_id', ownerId)
  return params.toString()
}

export const listTasks = (token, workspaceId, ownerId) =>
  apiFetch(`/admin/tasks?${scopedParams(workspaceId, ownerId)}`, { token })

export const deleteTask = (token, workspaceId, taskId) =>
  apiFetch(`/admin/tasks/${taskId}?workspace_id=${encodeURIComponent(workspaceId)}`, { method: 'DELETE', token })

export const listReminders = (token, workspaceId, ownerId) =>
  apiFetch(`/admin/reminders?${scopedParams(workspaceId, ownerId)}`, { token })

export const deleteReminder = (token, workspaceId, reminderId) =>
  apiFetch(`/admin/reminders/${reminderId}?workspace_id=${encodeURIComponent(workspaceId)}`, { method: 'DELETE', token })

export const listMemories = (token, workspaceId, ownerId) =>
  apiFetch(`/admin/memories?${scopedParams(workspaceId, ownerId)}`, { token })

export const deleteMemory = (token, workspaceId, memoryId) =>
  apiFetch(`/admin/memories/${memoryId}?workspace_id=${encodeURIComponent(workspaceId)}`, { method: 'DELETE', token })

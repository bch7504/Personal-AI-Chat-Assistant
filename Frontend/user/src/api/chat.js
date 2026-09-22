import { apiFetch } from './client'

export const listUsers = (token, search, workspaceId) => {
  const params = new URLSearchParams()
  if (search) params.set('search', search)
  if (workspaceId) params.set('workspace_id', workspaceId)
  return apiFetch(`/users${params.toString() ? `?${params.toString()}` : ''}`, { token })
}

export const listConversations = (token, workspaceId) => {
  const params = new URLSearchParams()
  if (workspaceId) params.set('workspace_id', workspaceId)
  return apiFetch(`/conversations${params.toString() ? `?${params.toString()}` : ''}`, { token })
}

export const createConversation = (token, { type, participant_ids, name, workspace_id, ai_enabled = false }) =>
  apiFetch('/conversations', { method: 'POST', token, body: { type, participant_ids, name, workspace_id, ai_enabled } })

export const listChannelMembers = (token, workspaceId, agentWorkspaceId) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/channel-members`, { token })

export const createChannel = (token, workspaceId, agentWorkspaceId, body) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/channels`, {
    method: 'POST', token, body,
  })

export const getMessages = (token, conversationId, { before, limit = 50 } = {}) => {
  const params = new URLSearchParams({ limit: String(limit) })
  if (before) params.set('before', before)
  return apiFetch(`/conversations/${conversationId}/messages?${params.toString()}`, { token })
}

export const sendMessage = (token, conversationId, content) =>
  apiFetch(`/conversations/${conversationId}/messages`, { method: 'POST', token, body: { content } })

export const markRead = (token, conversationId) =>
  apiFetch(`/conversations/${conversationId}/read`, { method: 'POST', token })

export const getAiPermission = (token, conversationId) =>
  apiFetch(`/conversations/${conversationId}/ai-permission`, { token })

export const setAiPermission = (token, conversationId, updates) =>
  apiFetch(`/conversations/${conversationId}/ai-permission`, { method: 'PUT', token, body: updates })

export const setGroupAiPolicy = (token, conversationId, enabled) =>
  apiFetch(`/conversations/${conversationId}/ai-policy`, { method: 'PUT', token, body: { enabled } })

export const hideConversation = (token, conversationId) =>
  apiFetch(`/conversations/${conversationId}`, { method: 'DELETE', token })

export const leaveConversation = (token, conversationId) =>
  apiFetch(`/conversations/${conversationId}/leave`, { method: 'POST', token })

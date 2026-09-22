import { apiFetch } from './client'

export const listWorkspaces = (token) => apiFetch('/workspaces', { token })

export const listWorkspaceMembers = (token, workspaceId) =>
  apiFetch(`/workspaces/${workspaceId}/members`, { token })

export const addWorkspaceMember = (token, workspaceId, email, role = 'member') =>
  apiFetch(`/workspaces/${workspaceId}/members`, {
    method: 'POST',
    token,
    body: { email, role },
  })

export const listWorkspaceSupportGrants = (token, workspaceId) =>
  apiFetch(`/workspaces/${workspaceId}/support-grants`, { token })

export const approveWorkspaceSupportGrant = (token, workspaceId, grantId) =>
  apiFetch(`/workspaces/${workspaceId}/support-grants/${grantId}/approve`, { method: 'POST', token })

export const rejectWorkspaceSupportGrant = (token, workspaceId, grantId) =>
  apiFetch(`/workspaces/${workspaceId}/support-grants/${grantId}/reject`, { method: 'POST', token })

export const revokeWorkspaceSupportGrant = (token, workspaceId, grantId) =>
  apiFetch(`/workspaces/${workspaceId}/support-grants/${grantId}/revoke`, { method: 'POST', token })

export const listAgentWorkspaces = (token, workspaceId) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces`, { token })

export const listAvailableAgentWorkspaces = (token, workspaceId) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/available`, { token })

export const createAgentWorkspace = (token, workspaceId, body) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces`, { method: 'POST', token, body })

export const updateAgentWorkspace = (token, workspaceId, agentWorkspaceId, body) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}`, { method: 'PATCH', token, body })

export const assignAgentWorkspaceLead = (token, workspaceId, agentWorkspaceId, email) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/lead`, {
    method: 'PATCH', token, body: { email },
  })

export const listAgentWorkspaceMembers = (token, workspaceId, agentWorkspaceId) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/members`, { token })

export const addAgentWorkspaceMember = (token, workspaceId, agentWorkspaceId, body) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/members`, {
    method: 'POST', token, body,
  })

export const revokeAgentWorkspaceMember = (token, workspaceId, agentWorkspaceId, membershipId) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/members/${membershipId}`, {
    method: 'DELETE', token,
  })

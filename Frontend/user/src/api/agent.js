import { apiFetch } from './client'

export const chatWithAgent = (token, { message, conversation_id, thread_id, workspace_id, context_limit, scope, messages }) =>
  apiFetch('/chat', { method: 'POST', token, body: { message, conversation_id, thread_id, workspace_id, context_limit, scope, messages } })

export const resumeAgent = (token, { thread_id, approved, edits }) =>
  apiFetch('/chat/resume', { method: 'POST', token, body: { thread_id, approved, edits } })

export const getAIUsageStatus = token =>
  apiFetch('/usage/status', { token })

export const getDeliveryBrief = (token, workspaceId, agentWorkspaceId, payload) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/delivery/brief`, {
    method: 'POST', token, body: payload,
  })

export const listDeliveryThreads = (token, workspaceId, agentWorkspaceId, conversationId = '') =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/delivery/threads${conversationId ? `?selected_conversation_id=${encodeURIComponent(conversationId)}` : ''}`, { token })

export const getDeliveryThreadMessages = (token, workspaceId, agentWorkspaceId, threadId, conversationId = '') =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/delivery/threads/${threadId}/messages${conversationId ? `?selected_conversation_id=${encodeURIComponent(conversationId)}` : ''}`, { token })

export const deleteDeliveryThread = (token, workspaceId, agentWorkspaceId, threadId, conversationId = '') =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/delivery/threads/${encodeURIComponent(threadId)}${conversationId ? `?selected_conversation_id=${encodeURIComponent(conversationId)}` : ''}`, { method: 'DELETE', token })

export const getDeliveryCapabilities = (token, workspaceId, agentWorkspaceId) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/delivery/capabilities`, { token })

export const getDeliveryReleaseTargets = (token, workspaceId, agentWorkspaceId) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/delivery/release-targets`, { token })

export const getDeliveryDashboard = (token, workspaceId, agentWorkspaceId) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/delivery/dashboard`, { token })

export const createDeliveryTask = (token, workspaceId, agentWorkspaceId, payload) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/delivery/tasks`, {
    method: 'POST', token, body: payload,
  })

export const listDeliveryTaskReviews = (token, workspaceId, agentWorkspaceId, conversationId = '') =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/delivery/task-reviews${conversationId ? `?selected_conversation_id=${encodeURIComponent(conversationId)}` : ''}`, { token })

export const reviewDeliveryTask = (token, workspaceId, agentWorkspaceId, taskId, payload) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/delivery/tasks/${taskId}/review`, {
    method: 'PATCH', token, body: payload,
  })

export const listDeliveryWorkflows = (token, workspaceId, agentWorkspaceId, limit = 20) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/delivery/workflows?limit=${limit}`, { token })

export const getDeliveryWorkflow = (token, workspaceId, agentWorkspaceId, workflowId) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/delivery/workflows/${workflowId}`, { token })

export const getDeliveryWorkflowEvents = (token, workspaceId, agentWorkspaceId, workflowId) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/delivery/workflows/${workflowId}/events`, { token })

export const cancelDeliveryWorkflow = (token, workspaceId, agentWorkspaceId, workflowId, expectedRowVersion) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/delivery/workflows/${workflowId}/cancel`, {
    method: 'POST', token, body: { expected_row_version: expectedRowVersion },
  })

export const createDeliveryDependency = (token, workspaceId, agentWorkspaceId, payload) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/delivery/dependencies`, {
    method: 'POST', token, body: payload,
  })

export const updateDeliveryDependency = (token, workspaceId, agentWorkspaceId, dependencyId, payload) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/delivery/dependencies/${dependencyId}`, {
    method: 'PATCH', token, body: payload,
  })

export const createDeliveryDecision = (token, workspaceId, agentWorkspaceId, payload) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/delivery/decisions`, {
    method: 'POST', token, body: payload,
  })

export const updateDeliveryDecision = (token, workspaceId, agentWorkspaceId, decisionId, payload) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/delivery/decisions/${decisionId}`, {
    method: 'PATCH', token, body: payload,
  })

export const createDeliveryCheckpoint = (token, workspaceId, agentWorkspaceId, payload) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/delivery/checkpoints`, {
    method: 'POST', token, body: payload,
  })

export const listDeliveryCheckpoints = (token, workspaceId, agentWorkspaceId, conversationId = '') =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/delivery/checkpoints${conversationId ? `?selected_conversation_id=${encodeURIComponent(conversationId)}` : ''}`, { token })

export const reviewDeliveryCheckpointQuality = (token, workspaceId, agentWorkspaceId, checkpointId, payload) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/delivery/checkpoints/${checkpointId}/quality-review`, {
    method: 'PATCH', token, body: payload,
  })

export const getQualityCapabilities = (token, workspaceId, agentWorkspaceId) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/quality/capabilities`, { token })

export const getQualityBrief = (token, workspaceId, agentWorkspaceId, payload) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/quality/brief`, {
    method: 'POST', token, body: payload,
  })

export const getQualityControlPlane = (token, workspaceId, agentWorkspaceId, releaseId) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/quality/control-plane?release_id=${encodeURIComponent(releaseId)}`, { token })

const createQualityRecord = (kind) => (token, workspaceId, agentWorkspaceId, payload) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/quality/${kind}`, {
    method: 'POST', token, body: payload,
  })

export const createQualityRequirement = createQualityRecord('requirements')
export const createQualityTestCase = createQualityRecord('test-cases')
export const createQualityEvidence = createQualityRecord('evidence')
export const createQualityTestRun = createQualityRecord('test-runs')
export const createQualityDefect = createQualityRecord('defects')
export const createQualityPolicy = createQualityRecord('policies')
export const createQualityWaiver = createQualityRecord('waivers')

export const transitionQualityRecord = (token, workspaceId, agentWorkspaceId, recordType, recordId, payload) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/quality/records/${recordType}/${recordId}`, {
    method: 'PATCH', token, body: payload,
  })

export const listQualityReleaseCandidates = (token, workspaceId, agentWorkspaceId) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/quality/release-candidates`, { token })

export const updateQualityReleaseCandidate = (token, workspaceId, agentWorkspaceId, candidateId, payload) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/quality/release-candidates/${candidateId}/status`, {
    method: 'PATCH', token, body: payload,
  })

export const listDeliveryReleaseCandidates = (token, workspaceId, agentWorkspaceId) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/delivery/release-candidates`, { token })

export const createDeliveryReleaseCandidate = (token, workspaceId, agentWorkspaceId, payload) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/delivery/release-candidates`, {
    method: 'POST', token, body: payload,
  })

export const updateDeliveryReleaseCandidate = (token, workspaceId, agentWorkspaceId, candidateId, payload) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/delivery/release-candidates/${candidateId}/status`, {
    method: 'PATCH', token, body: payload,
  })

export const createWorkspaceActionProposal = (token, workspaceId, agentWorkspaceId, payload) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/action-proposals`, {
    method: 'POST', token, body: payload,
  })

export const listWorkspaceActionProposals = (token, workspaceId, agentWorkspaceId) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/action-proposals`, { token })

export const decideWorkspaceActionProposal = (token, workspaceId, agentWorkspaceId, proposalId, payload) =>
  apiFetch(`/workspaces/${workspaceId}/agent-workspaces/${agentWorkspaceId}/action-proposals/${proposalId}`, {
    method: 'PATCH', token, body: payload,
  })

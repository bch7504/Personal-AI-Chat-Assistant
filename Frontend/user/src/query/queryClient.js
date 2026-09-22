import { QueryClient } from '@tanstack/react-query'
import { ApiError } from '../api/client'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      gcTime: 10 * 60_000,
      refetchOnMount: true,
      refetchOnWindowFocus: false,
      refetchOnReconnect: true,
      retry: (failureCount, error) => {
        if (error instanceof ApiError && error.status < 500) return false
        return failureCount < 1
      },
    },
    mutations: { retry: false },
  },
})

export const queryKeys = {
  workspaces: ['workspaces'],
  tasks: ['tasks', 'all'],
  reminders: ['reminders'],
  memories: ['memories'],
  calendarConnection: ['calendar-connection'],
  calendarEvents: (timeMin, timeMax) => ['calendar-events', timeMin || '', timeMax || ''],
  conversations: workspaceId => ['conversations', workspaceId],
  messages: conversationId => ['messages', conversationId],
  availableAgents: workspaceId => ['available-agent-workspaces', workspaceId],
  deliveryDashboard: (workspaceId, agentWorkspaceId) => ['delivery-dashboard', workspaceId, agentWorkspaceId],
  deliveryCapabilities: (workspaceId, agentWorkspaceId) => ['delivery-capabilities', workspaceId, agentWorkspaceId],
  deliveryThreads: (workspaceId, agentWorkspaceId, scopeId = '') => ['delivery-threads', workspaceId, agentWorkspaceId, scopeId],
  deliveryThreadMessages: (workspaceId, agentWorkspaceId, threadId, scopeId = '') => ['delivery-thread-messages', workspaceId, agentWorkspaceId, threadId, scopeId],
  deliveryReleaseTargets: (workspaceId, agentWorkspaceId) => ['delivery-release-targets', workspaceId, agentWorkspaceId],
  deliveryReleaseCandidates: (workspaceId, agentWorkspaceId) => ['delivery-release-candidates', workspaceId, agentWorkspaceId],
  qualityCapabilities: (workspaceId, agentWorkspaceId) => ['quality-capabilities', workspaceId, agentWorkspaceId],
  qualityControlPlane: (workspaceId, agentWorkspaceId, releaseId) => ['quality-control-plane', workspaceId, agentWorkspaceId, releaseId],
  qualityReleaseCandidates: (workspaceId, agentWorkspaceId) => ['quality-release-candidates', workspaceId, agentWorkspaceId],
  assistantThreads: ['assistant-threads'],
  assistantMessages: threadId => ['assistant-messages', threadId],
  assistantPending: threadId => ['assistant-pending', threadId],
  aiUsage: userId => ['ai-usage', userId || 'anonymous'],
}

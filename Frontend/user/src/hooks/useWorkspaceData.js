import { useQuery } from '@tanstack/react-query'
import { getDeliveryDashboard } from '../api/agent'
import { listConversations } from '../api/chat'
import { listAvailableAgentWorkspaces, listWorkspaces } from '../api/workspaces'
import { queryKeys } from '../query/queryClient'

export function useWorkspacesQuery(token) {
  return useQuery({
    queryKey: queryKeys.workspaces,
    queryFn: () => listWorkspaces(token),
    enabled: Boolean(token),
    staleTime: 5 * 60_000,
  })
}

export function useConversationsQuery(token, workspaceId) {
  return useQuery({
    queryKey: queryKeys.conversations(workspaceId),
    queryFn: () => listConversations(token, workspaceId),
    enabled: Boolean(token && workspaceId),
    staleTime: 30_000,
  })
}

export function useAvailableAgentsQuery(token, workspaceId) {
  return useQuery({
    queryKey: queryKeys.availableAgents(workspaceId),
    queryFn: () => listAvailableAgentWorkspaces(token, workspaceId),
    enabled: Boolean(token && workspaceId),
    // Keep this short-lived because assignment is an authorization signal. The protected
    // backend endpoints still enforce current membership on every request, so the cached value
    // only avoids a redundant UI lookup when a user switches tabs or revisits a route.
    staleTime: 60_000,
    refetchOnMount: true,
    refetchOnWindowFocus: false,
  })
}

export function useDeliveryDashboardQuery(token, workspaceId, agentWorkspaceId) {
  return useQuery({
    queryKey: queryKeys.deliveryDashboard(workspaceId, agentWorkspaceId),
    queryFn: () => getDeliveryDashboard(token, workspaceId, agentWorkspaceId),
    enabled: Boolean(token && workspaceId && agentWorkspaceId),
    staleTime: 30_000,
  })
}

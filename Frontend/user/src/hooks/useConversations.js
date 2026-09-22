import { useCallback } from 'react'
import { useConversationsQuery } from './useWorkspaceData'
import { queryClient, queryKeys } from '../query/queryClient'

export function useConversations(token, workspaceId) {
  const query = useConversationsQuery(token, workspaceId)
  const conversations = query.data?.conversations || []
  const setConversations = useCallback(updater => {
    queryClient.setQueryData(queryKeys.conversations(workspaceId), previous => {
      const current = previous?.conversations || []
      const next = typeof updater === 'function' ? updater(current) : updater
      return { ...(previous || {}), conversations: next }
    })
  }, [workspaceId])

  return { conversations, setConversations, loading: query.isPending, refresh: query.refetch }
}

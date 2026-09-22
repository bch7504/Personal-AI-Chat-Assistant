import { useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getMessages } from '../api/chat'
import { queryClient, queryKeys } from '../query/queryClient'

// `unreadHint` is a snapshot of the conversation's unread_count, taken by the caller BEFORE it
// gets zeroed locally on open - see ChatPage.jsx's onSelect. It only sizes the initial fetch (see
// below); it is NOT a dependency of the effect, so a later unrelated bump to the conversation list
// doesn't re-trigger a refetch/reset of the divider mid-read.
export function useMessages(token, conversationId, unreadHint = 0) {
  const query = useQuery({
    queryKey: queryKeys.messages(conversationId),
    queryFn: async () => {
      const limit = Math.min(200, Math.max(50, unreadHint + 10))
      const data = await getMessages(token, conversationId, { limit })
      return { ...data, initial_unread_count: unreadHint }
    },
    enabled: Boolean(token && conversationId),
    staleTime: 15_000,
  })
  const setMessages = useCallback(updater => {
    queryClient.setQueryData(queryKeys.messages(conversationId), previous => {
      const current = previous?.messages || []
      const next = typeof updater === 'function' ? updater(current) : updater
      return { ...(previous || {}), messages: next }
    })
  }, [conversationId])
  const setReadReceipts = useCallback(updater => {
    queryClient.setQueryData(queryKeys.messages(conversationId), previous => {
      const current = previous?.read_receipts || []
      const next = typeof updater === 'function' ? updater(current) : updater
      return { ...(previous || {}), read_receipts: next }
    })
  }, [conversationId])

  return {
    messages: query.data?.messages || [],
    setMessages,
    readReceipts: query.data?.read_receipts || [],
    setReadReceipts,
    loading: query.isPending && Boolean(conversationId),
    firstUnreadMessageId: query.data?.first_unread_message_id || null,
    unreadCount: query.data?.initial_unread_count || 0,
  }
}

import { useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { listTasks } from '../api/tasks'
import { listReminders } from '../api/reminders'
import { listMemories } from '../api/memories'
import { queryClient, queryKeys } from '../query/queryClient'

function useCachedList(token, queryKey, queryFn, staleTime = 30_000) {
  const query = useQuery({ queryKey, queryFn: () => queryFn(token), enabled: Boolean(token), staleTime })
  const setItems = useCallback(updater => {
    queryClient.setQueryData(queryKey, previous => (
      typeof updater === 'function' ? updater(previous || []) : updater
    ))
  }, [queryKey])
  return {
    items: query.data || [],
    setItems,
    loading: query.isPending,
    error: query.error,
    refresh: query.refetch,
  }
}

export const useTasksQuery = token => useCachedList(
  token,
  queryKeys.tasks,
  currentToken => listTasks(currentToken, { scope: 'all' }),
)
export const useRemindersQuery = token => useCachedList(token, queryKeys.reminders, listReminders)
export const useMemoriesQuery = token => useCachedList(token, queryKeys.memories, listMemories, 60_000)

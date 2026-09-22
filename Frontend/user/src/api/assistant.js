import { apiFetch } from './client'

export const listAssistantThreads = (token) => apiFetch('/assistant/threads', { token })

export const getAssistantThreadMessages = (token, threadId) =>
  apiFetch(`/assistant/threads/${threadId}/messages`, { token })

export const getAssistantThreadPending = (token, threadId) =>
  apiFetch(`/assistant/threads/${threadId}/pending`, { token })

export const deleteAssistantThread = (token, threadId) =>
  apiFetch(`/assistant/threads/${encodeURIComponent(threadId)}`, { method: 'DELETE', token })

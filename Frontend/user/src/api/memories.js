import { apiFetch } from './client'

export const listMemories = (token) => apiFetch('/memories', { token })

export const createMemory = (token, { category, title, detail, memory_type }) =>
  apiFetch('/memories', { method: 'POST', token, body: { category, title, detail, memory_type } })

export const updateMemory = (token, memoryId, updates) =>
  apiFetch(`/memories/${memoryId}`, { method: 'PATCH', token, body: updates })

export const deleteMemory = (token, memoryId) =>
  apiFetch(`/memories/${memoryId}`, { method: 'DELETE', token })

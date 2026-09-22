import { apiFetch } from './client'

export const listCalendarEvents = (token, { time_min, time_max } = {}) => {
  const params = new URLSearchParams()
  if (time_min) params.set('time_min', time_min)
  if (time_max) params.set('time_max', time_max)
  const qs = params.toString()
  return apiFetch(`/calendar/events${qs ? `?${qs}` : ''}`, { token })
}

export const createCalendarEvent = (token, { summary, start_iso, end_iso, description, attendees, create_reminder, reminder_lead_minutes }) =>
  apiFetch('/calendar/events', { method: 'POST', token, body: { summary, start_iso, end_iso, description, attendees, create_reminder, reminder_lead_minutes } })

export const updateCalendarEvent = (token, eventId, { summary, start_iso, end_iso, description } = {}) =>
  apiFetch(`/calendar/events/${eventId}`, { method: 'PATCH', token, body: { summary, start_iso, end_iso, description } })

export const deleteCalendarEvent = (token, eventId) =>
  apiFetch(`/calendar/events/${eventId}`, { method: 'DELETE', token })

export const getCalendarConnection = (token) => apiFetch('/calendar/connection', { token })
export const getCalendarOAuthUrl = (token) => apiFetch('/calendar/oauth/url', { token })
export const disconnectCalendar = (token) =>
  apiFetch('/calendar/connection', { method: 'DELETE', token })

export const listEventCandidates = (token, conversationId) =>
  apiFetch(`/calendar/candidates?conversation_id=${encodeURIComponent(conversationId)}`, { token })

export const confirmEventCandidate = (token, candidateId, options = {}) =>
  apiFetch(`/calendar/candidates/${candidateId}/confirm`, { method: 'POST', token, body: options })

export const dismissEventCandidate = (token, candidateId) =>
  apiFetch(`/calendar/candidates/${candidateId}/dismiss`, { method: 'POST', token })

export const backfillEventCandidates = (token, conversationId, batchSize = 200) =>
  apiFetch(`/conversations/${conversationId}/event-backfill`, { method: 'POST', token, body: { batch_size: batchSize } })

import { apiFetch } from './client'

export const listReminders = (token) => apiFetch('/reminders', { token })

export const createReminder = (token, { title, due_at_iso, lead_minutes, message }) =>
  apiFetch('/reminders', { method: 'POST', token, body: { title, due_at_iso, lead_minutes, message } })

export const cancelReminder = (token, reminderId) =>
  apiFetch(`/reminders/${reminderId}`, { method: 'DELETE', token })

export const updateReminder = (token, reminderId, changes) =>
  apiFetch(`/reminders/${reminderId}`, { method: 'PATCH', token, body: changes })

export const snoozeReminder = (token, reminderId, minutes = 10) =>
  apiFetch(`/reminders/${reminderId}/snooze`, { method: 'POST', token, body: { minutes } })

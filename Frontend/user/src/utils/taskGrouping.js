// Shared "what needs attention" grouping for tasks - originally inline in TaskInboxPage.jsx, now
// also used by AssistantContextPanel.jsx's "Cần chú ý" list, so both compute the same thing the
// same way instead of drifting apart.
export const DUE_SOON_HOURS = 48

export const byDueAtThenPriority = (a, b) => {
  const rank = { High: 0, Medium: 1, Low: 2 }
  if (!a.due_at && !b.due_at) return (rank[a.priority] ?? 1) - (rank[b.priority] ?? 1)
  if (!a.due_at) return 1
  if (!b.due_at) return -1
  return new Date(a.due_at) - new Date(b.due_at)
}

export function groupTasks(tasks) {
  const now = Date.now()
  const soonCutoff = now + DUE_SOON_HOURS * 3600 * 1000
  const active = tasks.filter(t => t.status === 'pending' || t.status === 'in_progress')

  const needsDecision = tasks.filter(t => t.status === 'suggested').sort(byDueAtThenPriority)
  const overdue = active.filter(t => t.due_at && new Date(t.due_at).getTime() < now).sort(byDueAtThenPriority)
  const dueSoon = active
    .filter(t => t.due_at && new Date(t.due_at).getTime() >= now && new Date(t.due_at).getTime() <= soonCutoff)
    .sort(byDueAtThenPriority)
  const shownIds = new Set([...overdue, ...dueSoon].map(t => t.id))
  const highPriority = active.filter(t => t.priority === 'High' && !shownIds.has(t.id)).sort(byDueAtThenPriority)

  return { needsDecision, overdue, dueSoon, highPriority }
}

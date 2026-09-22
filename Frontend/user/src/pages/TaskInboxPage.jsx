import { useEffect } from 'react'
import { Link, useOutletContext } from 'react-router-dom'
import PageHeader from '../components/common/PageHeader'
import StatCard from '../components/common/StatCard'
import { formatDue } from '../components/task/TaskTable'
import { useAuth } from '../context/AuthContext'
import { updateTaskStatus } from '../api/tasks'
import { useTasksQuery } from '../hooks/usePersonalData'
import { getTaskScopeLabel, upsertTaskWithContext } from '../utils/taskScope'

const sourceLabel = { manual: 'Manual', proactive: 'AI suggestion' }
const priorityClass = { High: 'danger', Medium: 'warning', Low: 'info' }
const DUE_SOON_HOURS = 48

const byDueAtThenPriority = (a, b) => {
  const rank = { High: 0, Medium: 1, Low: 2 }
  if (!a.due_at && !b.due_at) return (rank[a.priority] ?? 1) - (rank[b.priority] ?? 1)
  if (!a.due_at) return 1
  if (!b.due_at) return -1
  return new Date(a.due_at) - new Date(b.due_at)
}

// "Inbox nhiệm vụ ưu tiên" (đề bài, Nâng cao): a triage feed distinct from the full /tasks list -
// only what needs a decision or attention *right now*, ranked instead of just chronological.
export default function TaskInboxPage() {
  const { token } = useAuth()
  const { subscribe } = useOutletContext()
  const { items: tasks, setItems: setTasks, loading } = useTasksQuery(token)

  const upsertTask = (task) => setTasks(prev => upsertTaskWithContext(prev, task))

  useEffect(() => subscribe((data) => {
    if (['task_suggested', 'task_created', 'task_updated', 'task_submitted', 'task_reviewed'].includes(data.type)) upsertTask(data.task)
    if (data.type === 'task_deleted') setTasks(prev => prev.filter(t => t.id !== data.task_id))
  }), [subscribe])

  const now = Date.now()
  const soonCutoff = now + DUE_SOON_HOURS * 3600 * 1000
  const active = tasks.filter(t => ['pending', 'in_progress', 'blocked'].includes(t.status))

  const needsDecision = tasks.filter(t => t.status === 'suggested').sort(byDueAtThenPriority)
  const awaitingReview = tasks.filter(t => t.status === 'submitted').sort(byDueAtThenPriority)
  const changesRequested = tasks.filter(t => t.status === 'changes_requested').sort(byDueAtThenPriority)
  const overdue = active.filter(t => t.due_at && new Date(t.due_at).getTime() < now).sort(byDueAtThenPriority)
  const dueSoon = active
    .filter(t => t.due_at && new Date(t.due_at).getTime() >= now && new Date(t.due_at).getTime() <= soonCutoff)
    .sort(byDueAtThenPriority)
  const shownIds = new Set([...overdue, ...dueSoon].map(t => t.id))
  const highPriority = active.filter(t => t.priority === 'High' && !shownIds.has(t.id)).sort(byDueAtThenPriority)

  const accept = (task) => updateTaskStatus(token, task.id, 'pending').then(upsertTask)
  const dismiss = (task) => updateTaskStatus(token, task.id, 'dismissed').then(upsertTask)
  const complete = (task) => updateTaskStatus(token, task.id, 'completed').then(upsertTask)

  const totalInboxCount = needsDecision.length + awaitingReview.length + changesRequested.length + overdue.length + dueSoon.length + highPriority.length
  const completionAction = task => task.requires_review
    ? <Link className="btn btn-sm btn-primary" to="/tasks">Submit evidence</Link>
    : <button className="btn btn-sm btn-primary" onClick={() => complete(task)}>Complete</button>

  const Section = ({ icon, title, items, tone, actions }) => {
    if (!items.length) return null
    return (
      <section className="suggested-section">
        <div className="section-heading">
          <div>
            <span className="ai-label"><i className={`bi ${icon}`} /> {title}</span>
            <h3>{items.length} {items.length === 1 ? 'item' : 'items'}</h3>
          </div>
        </div>
        <div className="suggestion-grid">
          {items.map(task => (
            <div className="suggestion-card" key={task.id}>
              <div className={`suggestion-check text-${tone}`}><i className="bi bi-flag-fill" /></div>
              <div className="flex-grow-1">
                <h4>{task.title}</h4>
                <div className="suggestion-meta">
                  <span><i className="bi bi-diagram-3" />{getTaskScopeLabel(task)}</span>
                  {task.conversation_name && <span><i className="bi bi-people" />{task.conversation_name}</span>}
                  <span><i className="bi bi-chat-left-text" />{sourceLabel[task.source] || task.source}</span>
                  <span><i className="bi bi-calendar3" />{formatDue(task.due_at)}</span>
                  <span><span className={`soft-badge ${priorityClass[task.priority]}`}><i />{task.priority}</span></span>
                </div>
              </div>
              <div className="suggestion-actions">{actions(task)}</div>
            </div>
          ))}
        </div>
      </section>
    )
  }

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="My Work"
        title="Task Inbox"
        description="What needs your attention first across personal and workspace assignments."
        action={<Link to="/tasks" className="btn btn-light rounded-3"><i className="bi bi-list-task me-2" />All tasks</Link>}
      />
      <div className="stats-grid">
        <StatCard label="Needs decision" value={needsDecision.length + changesRequested.length} icon="bi-stars" color={(needsDecision.length + changesRequested.length) ? 'primary' : 'success'} />
        <StatCard label="Overdue" value={overdue.length} icon="bi-exclamation-circle" color={overdue.length ? 'danger' : 'success'} />
        <StatCard label="Due within 48h" value={dueSoon.length} icon="bi-hourglass-split" color={dueSoon.length ? 'warning' : 'success'} />
        <StatCard label="High priority" value={highPriority.length} icon="bi-flag" color={highPriority.length ? 'warning' : 'success'} />
      </div>

      {loading && <p className="text-muted small p-3 mb-0">Loading...</p>}

      {!loading && totalInboxCount === 0 && (
        <div className="content-card p-4 text-center text-muted">
          <i className="bi bi-check2-circle fs-3 d-block mb-2 text-success" />
          You're all caught up — nothing overdue, due soon, or waiting on a decision.
        </div>
      )}

      <Section
        icon="bi-stars" title="Needs your decision" items={needsDecision} tone="primary"
        actions={(task) => <>
          <button className="btn btn-sm btn-primary" onClick={() => accept(task)}>Accept</button>
          <button className="btn btn-sm btn-light" onClick={() => dismiss(task)}>Dismiss</button>
        </>}
      />
      <Section icon="bi-arrow-repeat" title="Lead requested changes" items={changesRequested} tone="danger" actions={completionAction} />
      <Section icon="bi-hourglass" title="Awaiting Lead review" items={awaitingReview} tone="warning" actions={() => <span className="text-muted small">No action needed</span>} />
      <Section
        icon="bi-exclamation-circle" title="Overdue" items={overdue} tone="danger"
        actions={completionAction}
      />
      <Section
        icon="bi-hourglass-split" title="Due within 48 hours" items={dueSoon} tone="warning"
        actions={completionAction}
      />
      <Section
        icon="bi-flag" title="High priority" items={highPriority} tone="warning"
        actions={completionAction}
      />
    </div>
  )
}

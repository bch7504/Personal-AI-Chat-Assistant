import { useEffect, useState } from 'react'
import { Link, useOutletContext } from 'react-router-dom'
import PageHeader from '../components/common/PageHeader'
import StatCard from '../components/common/StatCard'
import TaskTable, { formatDue } from '../components/task/TaskTable'
import NewTaskModal from '../components/task/NewTaskModal'
import TaskSubmissionModal from '../components/task/TaskSubmissionModal'
import TaskReminderModal from '../components/task/TaskReminderModal'
import { useAuth } from '../context/AuthContext'
import { updateTaskStatus, deleteTask } from '../api/tasks'
import { useTasksQuery } from '../hooks/usePersonalData'
import { getTaskScope, upsertTaskWithContext } from '../utils/taskScope'

const sourceLabel = { manual: 'Manual', proactive: 'AI suggestion' }

export default function TaskPage() {
  const { token } = useAuth()
  const { subscribe } = useOutletContext()
  const { items: tasks, setItems: setTasks, loading, error: queryError } = useTasksQuery(token)
  const [query, setQuery] = useState('')
  const [newOpen, setNewOpen] = useState(false)
  const [error, setError] = useState('')
  const [submissionTask, setSubmissionTask] = useState(null)
  const [reminderTask, setReminderTask] = useState(null)
  const [scopeFilter, setScopeFilter] = useState('all')

  const upsertTask = (task) => setTasks(prev => upsertTaskWithContext(prev, task))
  const removeTask = (taskId) => setTasks(prev => prev.filter(t => t.id !== taskId))

  // Realtime: proactive suggestions land here the moment Orbit finds them, and any change made
  // from another tab/device (or the agent chat) shows up without a manual refresh. Harmless if
  // it duplicates an update this tab already applied optimistically below - upsert is idempotent.
  useEffect(() => subscribe((data) => {
    if (['task_suggested', 'task_created', 'task_updated', 'task_submitted', 'task_reviewed'].includes(data.type)) upsertTask(data.task)
    if (data.type === 'task_deleted') removeTask(data.task_id)
  }), [subscribe])

  const matchesScope = task => scopeFilter === 'all' || getTaskScope(task) === scopeFilter
  const suggestions = tasks.filter(t => t.status === 'suggested' && matchesScope(t))
  const mainTasks = tasks.filter(t => !['suggested', 'dismissed', 'invalidated'].includes(t.status))
  const shownTasks = mainTasks.filter(t => (
    matchesScope(t)
    && t.title.toLowerCase().includes(query.toLowerCase())
  ))
  const scopeCounts = {
    all: mainTasks.length,
    personal: mainTasks.filter(task => getTaskScope(task) === 'personal').length,
    product_delivery: mainTasks.filter(task => getTaskScope(task) === 'product_delivery').length,
  }
  const completed = mainTasks.filter(t => t.status === 'completed').length
  const overdue = mainTasks.filter(t => t.status === 'pending' && t.due_at && new Date(t.due_at) < new Date()).length
  const pending = mainTasks.length - completed - overdue

  const accept = (task) => updateTaskStatus(token, task.id, 'pending').then(upsertTask)
  const dismiss = (task) => updateTaskStatus(token, task.id, 'dismissed').then(upsertTask)
  const updateStatus = (task, status, extra = {}) => updateTaskStatus(token, task.id, status, { ...extra, expected_row_version: task.row_version }).then(upsertTask).catch(err => setError(err.detail || 'Task đã thay đổi; vui lòng tải lại.'))
  const complete = (task) => updateStatus(task, 'completed')
  const start = (task) => updateStatus(task, 'in_progress')
  const block = (task) => {
    const reason = window.prompt('Lý do task bị chặn là gì?')
    if (reason?.trim()) updateStatus(task, 'blocked', { blocked_reason: reason.trim() })
  }
  const remove = (task) => deleteTask(token, task.id).then(() => removeTask(task.id))

  return <div className="page-container">
    <PageHeader eyebrow="My Work" title="My Tasks" description="All work assigned to you across personal and Product Delivery scopes." action={<div className="d-flex gap-2"><Link to="/tasks/inbox" className="btn btn-light rounded-3"><i className="bi bi-inbox me-2"/>Priority inbox</Link><button className="btn btn-primary rounded-3" onClick={()=>setNewOpen(true)}><i className="bi bi-plus-lg me-2"/>Add personal task</button></div>}/>
    {(error || queryError) && <div className="auth-error mb-3">{error || queryError.detail || 'Could not load tasks.'}</div>}
    <div className="stats-grid"><StatCard label="Total tasks" value={mainTasks.length} icon="bi-list-task"/><StatCard label="Completed" value={completed} icon="bi-check2-circle" color="success"/><StatCard label="Pending" value={pending} icon="bi-hourglass-split" color="warning"/><StatCard label="Overdue" value={overdue} icon="bi-exclamation-circle" color="danger" note={overdue ? 'Needs attention' : undefined}/></div>
    <section className="content-card"><div className="card-toolbar"><div><h3>My assigned tasks</h3><span>{shownTasks.length} of {mainTasks.length} tasks</span></div><div className="toolbar-actions flex-wrap"><div className="btn-group btn-group-sm" role="group" aria-label="Task scope"><button className={`btn ${scopeFilter === 'all' ? 'btn-primary' : 'btn-light'}`} onClick={()=>setScopeFilter('all')}>All ({scopeCounts.all})</button><button className={`btn ${scopeFilter === 'personal' ? 'btn-primary' : 'btn-light'}`} onClick={()=>setScopeFilter('personal')}>Personal ({scopeCounts.personal})</button><button className={`btn ${scopeFilter === 'product_delivery' ? 'btn-primary' : 'btn-light'}`} onClick={()=>setScopeFilter('product_delivery')}>Product Delivery ({scopeCounts.product_delivery})</button></div><div className="mini-search"><i className="bi bi-search"/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search tasks"/></div></div></div>{loading ? <p className="text-muted small p-3 mb-0">Loading...</p> : <TaskTable tasks={shownTasks} onStart={start} onBlock={block} onSubmit={setSubmissionTask} onComplete={complete} onReminder={setReminderTask} onDelete={remove}/>}</section>
    <section className="suggested-section"><div className="section-heading"><div><span className="ai-label"><i className="bi bi-stars"/> AI suggestions</span><h3>Tasks you may have missed</h3><p>Orbit found these action items in your conversations.</p></div></div><div className="suggestion-grid">{suggestions.map(s=><div className="suggestion-card" key={s.id}><div className="suggestion-check"><i className="bi bi-stars"/></div><div className="flex-grow-1"><h4>{s.title}</h4><div className="suggestion-meta"><span><i className="bi bi-chat-left-text"/>{sourceLabel[s.source] || s.source}</span><span><i className="bi bi-calendar3"/>{formatDue(s.due_at)}</span></div></div><div className="suggestion-actions"><button className="btn btn-sm btn-primary" onClick={() => accept(s)}>Accept</button><button className="btn btn-sm btn-light" onClick={() => dismiss(s)}>Dismiss</button></div></div>)}
      {!loading && !suggestions.length && <p className="text-muted small mb-0">No new suggestions right now — try "Extract tasks" in a conversation's AI panel.</p>}
    </div></section>
    <NewTaskModal open={newOpen} onClose={()=>setNewOpen(false)} onCreated={upsertTask}/>
    <TaskSubmissionModal task={submissionTask} onClose={()=>setSubmissionTask(null)} onSubmitted={upsertTask}/>
    <TaskReminderModal task={reminderTask} onClose={()=>setReminderTask(null)} onSaved={upsertTask}/>
  </div>
}

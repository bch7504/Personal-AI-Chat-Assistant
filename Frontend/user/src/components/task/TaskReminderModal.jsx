import { useEffect, useState } from 'react'
import { updateTask } from '../../api/tasks'
import { useAuth } from '../../context/AuthContext'

const toLocalInput = value => {
  if (!value) return ''
  const date = new Date(value)
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}

export default function TaskReminderModal({ task, onClose, onSaved }) {
  const { token, user } = useAuth()
  const [dueAt, setDueAt] = useState('')
  const [autoReminder, setAutoReminder] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    setDueAt(toLocalInput(task?.due_at))
    setAutoReminder(task?.auto_reminder_enabled !== false)
    setError('')
  }, [task])

  if (!task) return null
  const personalTask = !task.agent_workspace_id
  const globallyEnabled = user?.preferences?.auto_task_reminders === true

  const submit = async event => {
    event.preventDefault()
    setSaving(true)
    setError('')
    try {
      const updates = {
        expected_row_version: task.row_version,
        auto_reminder_enabled: autoReminder,
      }
      if (personalTask) updates.due_at = dueAt ? new Date(dueAt).toISOString() : null
      const updated = await updateTask(token, task.id, updates)
      onSaved(updated)
      onClose()
    } catch (err) {
      setError(err.detail || 'Could not update task reminder settings.')
    } finally {
      setSaving(false)
    }
  }

  return <div className="modal show d-block" tabIndex="-1" style={{background:'rgba(20,30,50,.32)'}} onClick={onClose}>
    <div className="modal-dialog modal-dialog-centered" onClick={event=>event.stopPropagation()}><div className="modal-content">
      <div className="modal-header"><div><h5 className="modal-title">Deadline & reminder</h5><small className="text-muted">{task.title}</small></div><button className="btn-close" onClick={onClose}/></div>
      <form onSubmit={submit}><div className="modal-body d-flex flex-column gap-3">
        {error && <div className="auth-error">{error}</div>}
        <label><span className="form-label">Deadline</span><input className="form-control" type="datetime-local" value={dueAt} onChange={event=>setDueAt(event.target.value)} disabled={!personalTask}/>{!personalTask && <small className="text-muted d-block mt-1">Workspace deadlines are changed through the Workspace Agent approval flow.</small>}</label>
        <div className="setting-toggle border rounded-3 px-3"><div><strong>Automatic deadline reminder</strong><p>Follow this task whenever its deadline changes.</p></div><div className="form-check form-switch"><input className="form-check-input" type="checkbox" checked={autoReminder} onChange={event=>setAutoReminder(event.target.checked)}/></div></div>
        {!globallyEnabled && <div className="alert alert-light border small mb-0"><i className="bi bi-info-circle me-2"/>Automatic task reminders are currently disabled in Profile &gt; Notifications. This task setting will take effect when the global option is enabled.</div>}
      </div><div className="modal-footer"><button type="button" className="btn btn-light" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={saving}>{saving ? 'Saving...' : 'Save settings'}</button></div></form>
    </div></div>
  </div>
}

import { useState } from 'react'
import { createTask } from '../../api/tasks'
import { useAuth } from '../../context/AuthContext'

export default function NewTaskModal({ open, onClose, onCreated }) {
  const { token } = useAuth()
  const [title, setTitle] = useState('')
  const [dueAt, setDueAt] = useState('')
  const [priority, setPriority] = useState('Medium')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  if (!open) return null

  const submit = async (event) => {
    event.preventDefault()
    if (!title.trim()) return
    setSubmitting(true); setError('')
    try {
      const task = await createTask(token, {
        title: title.trim(),
        due_at: dueAt ? new Date(dueAt).toISOString() : null,
        priority,
        conversation_id: null,
        source: 'manual',
      })
      onCreated(task)
      setTitle(''); setDueAt(''); setPriority('Medium')
      onClose()
    } catch (err) { setError(err.detail || 'Could not create task.') }
    finally { setSubmitting(false) }
  }

  return <div className="modal show d-block" tabIndex="-1" style={{background:'rgba(20,30,50,.32)'}} onClick={onClose}>
    <div className="modal-dialog modal-dialog-centered" onClick={event=>event.stopPropagation()}><div className="modal-content">
      <div className="modal-header"><h5 className="modal-title">New personal task</h5><button className="btn-close" onClick={onClose}/></div>
      <form onSubmit={submit}><div className="modal-body d-flex flex-column gap-3">
        {error && <div className="auth-error">{error}</div>}
        <input className="form-control" placeholder="Task title" value={title} onChange={event=>setTitle(event.target.value)} maxLength={200} required/>
        <label className="form-label small mb-0">Due date<input type="datetime-local" className="form-control mt-1" value={dueAt} onChange={event=>setDueAt(event.target.value)}/></label>
        <select className="form-select" value={priority} onChange={event=>setPriority(event.target.value)}><option>High</option><option>Medium</option><option>Low</option></select>
      </div><div className="modal-footer"><button type="button" className="btn btn-light" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={submitting}>{submitting?'Creating...':'Create task'}</button></div></form>
    </div></div>
  </div>
}

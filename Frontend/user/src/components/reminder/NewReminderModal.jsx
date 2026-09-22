import { useState } from 'react'
import { useAuth } from '../../context/AuthContext'
import { createReminder } from '../../api/reminders'

export default function NewReminderModal({ open, onClose, onCreated }) {
  const { token } = useAuth()
  const [title, setTitle] = useState('')
  const [dueAt, setDueAt] = useState('')
  const [leadMinutes, setLeadMinutes] = useState(30)
  const [message, setMessage] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  if (!open) return null

  const submit = async (e) => {
    e.preventDefault()
    if (!title.trim() || !dueAt) return
    setSubmitting(true); setError('')
    try {
      const reminder = await createReminder(token, {
        title: title.trim(),
        due_at_iso: new Date(dueAt).toISOString(),
        lead_minutes: Number(leadMinutes) || 0,
        message: message.trim(),
      })
      onCreated(reminder)
      onClose()
      setTitle(''); setDueAt(''); setLeadMinutes(30); setMessage('')
    } catch (err) { setError(err.detail || 'Could not create reminder') }
    finally { setSubmitting(false) }
  }

  return (
    <div className="modal show d-block" tabIndex="-1" style={{ background: 'rgba(20,30,50,.32)' }} onClick={onClose}>
      <div className="modal-dialog modal-dialog-centered" onClick={e => e.stopPropagation()}>
        <div className="modal-content">
          <div className="modal-header"><h5 className="modal-title">New reminder</h5><button className="btn-close" onClick={onClose} /></div>
          <form onSubmit={submit}>
            <div className="modal-body d-flex flex-column gap-3">
              {error && <div className="auth-error">{error}</div>}
              <input className="form-control" placeholder="Reminder title" value={title} onChange={e => setTitle(e.target.value)} required />
              <div className="row g-2">
                <div className="col"><label className="form-label small">Due at</label><input type="datetime-local" className="form-control" value={dueAt} onChange={e => setDueAt(e.target.value)} required /></div>
                <div className="col"><label className="form-label small">Lead time (minutes)</label><input type="number" min="0" className="form-control" value={leadMinutes} onChange={e => setLeadMinutes(e.target.value)} /></div>
              </div>
              <textarea className="form-control" placeholder="Message (optional)" value={message} onChange={e => setMessage(e.target.value)} rows={2} />
            </div>
            <div className="modal-footer">
              <button type="button" className="btn btn-light" onClick={onClose}>Cancel</button>
              <button type="submit" className="btn btn-primary" disabled={submitting}>{submitting ? 'Scheduling...' : 'Schedule reminder'}</button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}

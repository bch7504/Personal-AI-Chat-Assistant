import { useState } from 'react'
import { useAuth } from '../../context/AuthContext'
import { createCalendarEvent } from '../../api/calendar'

export default function NewEventModal({ open, onClose, onCreated }) {
  const { token } = useAuth()
  const [summary, setSummary] = useState('')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [description, setDescription] = useState('')
  const [createReminder, setCreateReminder] = useState(true)
  const [reminderLeadMinutes, setReminderLeadMinutes] = useState(30)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  if (!open) return null

  const submit = async (e) => {
    e.preventDefault()
    if (!summary.trim() || !start || !end) return
    if (new Date(end) <= new Date(start)) { setError('End time must be later than start time.'); return }
    setSubmitting(true); setError('')
    try {
      const event = await createCalendarEvent(token, {
        summary: summary.trim(),
        start_iso: new Date(start).toISOString(),
        end_iso: new Date(end).toISOString(),
        description: description.trim() || undefined,
        create_reminder: createReminder,
        reminder_lead_minutes: reminderLeadMinutes,
      })
      onCreated(event)
      onClose()
      setSummary(''); setStart(''); setEnd(''); setDescription(''); setCreateReminder(true); setReminderLeadMinutes(30)
    } catch (err) { setError(err.detail || 'Could not create event') }
    finally { setSubmitting(false) }
  }

  return (
    <div className="modal show d-block" tabIndex="-1" style={{ background: 'rgba(20,30,50,.32)' }} onClick={onClose}>
      <div className="modal-dialog modal-dialog-centered" onClick={e => e.stopPropagation()}>
        <div className="modal-content">
          <div className="modal-header"><h5 className="modal-title">New event</h5><button className="btn-close" onClick={onClose} /></div>
          <form onSubmit={submit}>
            <div className="modal-body d-flex flex-column gap-3">
              {error && <div className="auth-error">{error}</div>}
              <input className="form-control" placeholder="Event title" value={summary} onChange={e => setSummary(e.target.value)} required />
              <div className="row g-2">
                <div className="col"><label className="form-label small">Start</label><input type="datetime-local" className="form-control" value={start} onChange={e => setStart(e.target.value)} required /></div>
                <div className="col"><label className="form-label small">End</label><input type="datetime-local" className="form-control" value={end} onChange={e => setEnd(e.target.value)} required /></div>
              </div>
              <textarea className="form-control" placeholder="Description (optional)" value={description} onChange={e => setDescription(e.target.value)} rows={3} />
              <div className="border rounded-3 p-3">
                <label className="form-check form-switch mb-0"><input className="form-check-input" type="checkbox" checked={createReminder} onChange={e=>setCreateReminder(e.target.checked)}/><span className="form-check-label fw-semibold">Create an Orbit reminder</span></label>
                {createReminder && <label className="form-label small mt-3 mb-0 w-100">Remind me before<select className="form-select mt-1" value={reminderLeadMinutes} onChange={e=>setReminderLeadMinutes(Number(e.target.value))}><option value={15}>15 minutes</option><option value={30}>30 minutes</option><option value={60}>1 hour</option><option value={1440}>1 day</option></select></label>}
              </div>
            </div>
            <div className="modal-footer">
              <button type="button" className="btn btn-light" onClick={onClose}>Cancel</button>
              <button type="submit" className="btn btn-primary" disabled={submitting}>{submitting ? 'Creating...' : 'Create event'}</button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}

import { useEffect, useState } from 'react'
import { Link, useOutletContext } from 'react-router-dom'
import PageHeader from '../components/common/PageHeader'
import NewReminderModal from '../components/reminder/NewReminderModal'
import { useAuth } from '../context/AuthContext'
import { cancelReminder, snoozeReminder } from '../api/reminders'
import { useRemindersQuery } from '../hooks/usePersonalData'
import { getColor } from '../utils/avatar'
import { formatDateTime } from '../utils/datetime'

const statusLabel = { scheduled: 'Scheduled', fired: 'Fired', cancelled: 'Cancelled' }
const statusClass = { scheduled: 'primary', fired: 'success', cancelled: 'secondary' }

export default function ReminderPage() {
  const { token } = useAuth()
  const { subscribe } = useOutletContext()
  const { items: reminders, setItems: setReminders, loading, error: queryError, refresh } = useRemindersQuery(token)
  const [newOpen, setNewOpen] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => subscribe((data) => {
    if (['reminder_created', 'reminder_updated'].includes(data.type)) {
      setReminders(prev => [...prev.filter(reminder => reminder.id !== data.reminder.id), data.reminder])
    }
    if (data.type === 'reminder_deleted') {
      setReminders(prev => prev.filter(reminder => reminder.id !== data.reminder_id))
    }
    if (data.type === 'reminder_fired') {
      setReminders(prev => prev.map(r => r.id === data.reminder.id ? { ...r, status: 'fired' } : r))
    }
  }), [subscribe])

  const onCreated = (reminder) => setReminders(prev => [...prev.filter(item => item.id !== reminder.id), reminder])
  const onCancel = (reminder) => cancelReminder(token, reminder.id).then(refresh).catch(err => setError(err.detail || 'Could not cancel reminder.'))
  const onSnooze = (reminder) => snoozeReminder(token, reminder.id, 10).then(refresh).catch(err => setError(err.detail || 'Could not snooze reminder.'))

  return <div className="page-container">
    <PageHeader eyebrow="Stay focused" title="Reminders" description="Gentle nudges for everything that matters." action={<button className="btn btn-primary" onClick={() => setNewOpen(true)}><i className="bi bi-plus-lg me-2"/>New reminder</button>}/>
    {(error || queryError) && <div className="auth-error mb-3">{error || queryError.detail || 'Could not load reminders.'}</div>}
    <div className="reminder-layout"><section className="content-card reminder-list"><div className="card-toolbar"><div><h3>Upcoming reminders</h3><span>{reminders.filter(r => r.status === 'scheduled').length} active reminders</span></div></div>
      {loading ? <p className="text-muted small p-3 mb-0">Loading...</p> : reminders.map(r => (
        <div className={`reminder-row ${r.status !== 'scheduled' ? 'disabled' : ''}`} key={r.id}>
          <div className="reminder-icon" style={{ background: `${getColor(r.id)}12`, color: getColor(r.id) }}><i className="bi bi-alarm"/></div>
          <div className="reminder-info"><h4>{r.title}</h4><strong>{formatDateTime(r.due_at)}</strong><div><span><i className="bi bi-bell"/>Reminds at {formatDateTime(r.fire_at)}</span>{r.task_id && <span><i className="bi bi-link-45deg"/>Follows task deadline</span>}{r.calendar_event_id && <span><i className="bi bi-calendar-event"/>Linked Google Calendar event</span>}{r.message && <span><i className="bi bi-chat-left-text"/>{r.message}</span>}</div></div>
          <div className="reminder-controls"><span className={`status-badge ${statusClass[r.status]}`}>{statusLabel[r.status]}</span>{!r.task_id && <button className="btn btn-sm btn-light" onClick={() => onSnooze(r)}>Snooze 10m</button>}{r.status === 'scheduled' && (r.task_id ? <Link className="btn btn-sm btn-light" to="/tasks">Manage task</Link> : r.calendar_event_id ? <Link className="btn btn-sm btn-light" to="/calendar">Open calendar</Link> : <button className="btn btn-sm btn-light" onClick={() => onCancel(r)}>Cancel</button>)}</div>
        </div>
      ))}
      {!loading && !reminders.length && <p className="text-muted small p-3 mb-0">No reminders yet.</p>}
    </section>
      <aside><div className="notification-preview"><div className="preview-label"><span>Preview</span><i className="bi bi-phone"/></div><div className="phone-notification"><div className="orbit-mini"><i className="bi bi-command"/></div><div><div><strong>Orbit</strong><time>now</time></div><h4>Product launch call</h4><p>Starting in 30 minutes • Product Launch</p></div></div><div className="preview-glow"/></div><div className="reminder-tip"><i className="bi bi-lightbulb"/><div><strong>Realtime</strong><p>Khi reminder đến giờ, bạn sẽ thấy thông báo hiện ngay dù đang ở trang khác.</p></div></div></aside>
    </div>
    <NewReminderModal open={newOpen} onClose={() => setNewOpen(false)} onCreated={onCreated} />
  </div>
}

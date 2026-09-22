import { useEffect, useState } from 'react'
import { Link, useOutletContext } from 'react-router-dom'
import FullCalendar from '@fullcalendar/react'
import dayGridPlugin from '@fullcalendar/daygrid'
import timeGridPlugin from '@fullcalendar/timegrid'
import interactionPlugin from '@fullcalendar/interaction'
import PageHeader from '../components/common/PageHeader'
import NewEventModal from '../components/calendar/NewEventModal'
import ConnectCalendarCard from '../components/calendar/ConnectCalendarCard'
import { useAuth } from '../context/AuthContext'
import {
  listCalendarEvents, deleteCalendarEvent,
  getCalendarConnection, disconnectCalendar,
} from '../api/calendar'
import { getColor } from '../utils/avatar'
import { HANOI_TZ, formatDateTime } from '../utils/datetime'

export default function CalendarPage() {
  const { token } = useAuth()
  const { subscribe } = useOutletContext()
  const [connected, setConnected] = useState(null) // null = not checked yet
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState(null)
  const [newEventOpen, setNewEventOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const refresh = () => {
    setLoading(true); setError('')
    listCalendarEvents(token)
      .then(list => { setConnected(true); setEvents(list.map(e => ({ ...e, color: getColor(e.id) }))) })
      .catch(err => {
        if (err.status === 409) { setConnected(false); setEvents([]) } // not connected, not an error
        else setError(err.detail?.message || err.detail || 'Could not load Google Calendar events.')
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    setLoading(true)
    getCalendarConnection(token)
      .then(({ connected: isConnected }) => {
        if (isConnected) refresh()
        else { setConnected(false); setLoading(false) }
      })
      .catch(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])

  const upsertEvent = (event) => setEvents(prev => [...prev.filter(e => e.id !== event.id), { ...event, color: getColor(event.id) }])
  const removeEvent = (eventId) => setEvents(prev => prev.filter(e => e.id !== eventId))

  // Realtime: each user has their own Google Calendar now, the backend only ever pushes to the
  // owner. Source: this UI, another tab, the agent in chat, or a direct edit in Google Calendar
  // itself (caught by syncToken polling while this user is online).
  useEffect(() => subscribe((data) => {
    if (data.type === 'calendar_event_created' || data.type === 'calendar_event_updated') upsertEvent(data.event)
    if (data.type === 'calendar_event_deleted') removeEvent(data.event_id)
  }), [subscribe])

  const removeSelected = async () => {
    if (!selected || deleting) return
    setDeleting(true)
    try {
      await deleteCalendarEvent(token, selected.id)
      removeEvent(selected.id)
      setSelected(null)
    } catch (err) {
      setError(err.detail?.message || err.detail || 'Could not delete this event.')
    } finally { setDeleting(false) }
  }

  const disconnect = async () => {
    try {
      await disconnectCalendar(token)
      setConnected(false); setEvents([])
    } catch (err) {
      setError(err.detail?.message || err.detail || 'Could not disconnect Google Calendar.')
    }
  }

  const headerAction = connected
    ? <div className="d-flex gap-2">
        <button className="btn btn-light btn-sm" onClick={disconnect}><i className="bi bi-google me-2" />Disconnect</button>
        <button className="btn btn-primary" onClick={() => setNewEventOpen(true)}><i className="bi bi-plus-lg me-2" />New event</button>
      </div>
    : null

  return <div className="page-container calendar-page">
    <PageHeader eyebrow="Schedule" title="Calendar" description="Your Google Calendar events, all in one place." action={headerAction}/>
    {error && <div className="auth-error mb-3">{error}</div>}
    {loading ? <p className="text-muted small">Loading calendar...</p> : connected === false ? (
      <ConnectCalendarCard onConnected={() => { setConnected(true); refresh() }} />
    ) : (
      <div className="calendar-layout"><section className="content-card calendar-card"><FullCalendar plugins={[dayGridPlugin,timeGridPlugin,interactionPlugin]} initialView="dayGridMonth" timeZone={HANOI_TZ} headerToolbar={{left:'prev,next today',center:'title',right:'dayGridMonth,timeGridWeek,timeGridDay'}} events={events} eventClick={({event:e})=>setSelected(e)} height="auto"/></section>
        <aside className="detected-sidebar"><div className="detected-head"><span><i className="bi bi-stars"/></span><div><h3>AI-detected events</h3><p>Active</p></div></div><p className="text-muted small">Orbit đang tự động rà tin nhắn tìm cam kết/lịch hẹn. Khi phát hiện, việc gợi ý sẽ xuất hiện trong <Link to="/tasks">Tasks → AI suggestions</Link> để bạn Accept/Dismiss trước khi tạo event thật.</p></aside>
      </div>
    )}
    {selected && <div className="modal-backdrop-custom" onClick={()=>setSelected(null)}><div className="event-modal" onClick={e=>e.stopPropagation()}><button className="icon-btn modal-close" onClick={()=>setSelected(null)}><i className="bi bi-x-lg"/></button><div className="event-modal-icon"><i className="bi bi-calendar-event"/></div><span className="eyebrow">Event details</span><h3>{selected.title}</h3><div className="event-detail-row"><i className="bi bi-clock"/><span><strong>{formatDateTime(selected.start)}</strong>{selected.end && <small>{' → '}{formatDateTime(selected.end)}</small>}</span></div>{selected.url && <a className="btn btn-primary w-100 mt-3" href={selected.url} target="_blank" rel="noreferrer">Open in Google Calendar</a>}<button className="btn btn-light text-danger w-100 mt-2" onClick={removeSelected} disabled={deleting}><i className="bi bi-trash me-2"/>{deleting?'Deleting...':'Delete event'}</button></div></div>}
    <NewEventModal open={newEventOpen} onClose={() => setNewEventOpen(false)} onCreated={upsertEvent} />
  </div>
}

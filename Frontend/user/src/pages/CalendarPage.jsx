import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useOutletContext } from 'react-router-dom'
import FullCalendar from '@fullcalendar/react'
import dayGridPlugin from '@fullcalendar/daygrid'
import timeGridPlugin from '@fullcalendar/timegrid'
import interactionPlugin from '@fullcalendar/interaction'
import luxonPlugin from '@fullcalendar/luxon3'
import PageHeader from '../components/common/PageHeader'
import NewEventModal from '../components/calendar/NewEventModal'
import ConnectCalendarCard from '../components/calendar/ConnectCalendarCard'
import { useAuth } from '../context/AuthContext'
import { deleteCalendarEvent, disconnectCalendar, getCalendarConnection, listCalendarEvents } from '../api/calendar'
import { useTasksQuery } from '../hooks/usePersonalData'
import { getColor } from '../utils/avatar'
import { HANOI_TZ, formatDateTime } from '../utils/datetime'
import { getTaskScopeLabel, upsertTaskWithContext } from '../utils/taskScope'
import { queryClient, queryKeys } from '../query/queryClient'

const HIDDEN_TASK_STATUSES = new Set(['suggested', 'completed', 'dismissed', 'invalidated'])

const taskStatusLabel = task => {
  if (task.status === 'blocked') return 'Blocked'
  if (task.status === 'in_progress') return 'In progress'
  if (task.status === 'submitted') return 'Awaiting review'
  if (task.status === 'changes_requested') return 'Changes requested'
  if (task.due_at && new Date(task.due_at) < new Date()) return 'Overdue'
  return 'Pending'
}

const taskColor = task => {
  const status = taskStatusLabel(task)
  if (status === 'Overdue' || status === 'Blocked' || status === 'Changes requested') return '#e85070'
  if (task.priority === 'High') return '#f59e0b'
  if (task.status === 'in_progress') return '#6d5ce8'
  return '#3b82f6'
}

export default function CalendarPage() {
  const { token } = useAuth()
  const { subscribe } = useOutletContext()
  const { items: tasks, setItems: setTasks, loading: tasksLoading, error: tasksError } = useTasksQuery(token)
  const [connected, setConnected] = useState(null)
  const [events, setEvents] = useState([])
  const [visibleSources, setVisibleSources] = useState({ google: true, tasks: true })
  const [checking, setChecking] = useState(true)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState(null)
  const [newEventOpen, setNewEventOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const visibleRange = useRef(null)

  const deadlineTasks = useMemo(
    () => tasks.filter(task => task.due_at && !HIDDEN_TASK_STATUSES.has(task.status)),
    [tasks],
  )
  const calendarItems = useMemo(() => [
    ...(visibleSources.google ? events : []),
    ...(visibleSources.tasks ? deadlineTasks.map(task => ({
      id: `task:${task.id}`,
      title: task.title,
      start: task.due_at,
      backgroundColor: taskColor(task),
      borderColor: taskColor(task),
      textColor: '#fff',
      classNames: ['orbit-task-event'],
      extendedProps: { sourceType: 'task', task },
    })) : []),
  ], [deadlineTasks, events, visibleSources])

  const refresh = (range = visibleRange.current) => {
    setLoading(true); setError('')
    const requestedRange = range || {}
    queryClient.fetchQuery({
      queryKey: queryKeys.calendarEvents(requestedRange.time_min, requestedRange.time_max),
      queryFn: () => listCalendarEvents(token, requestedRange),
      staleTime: 30_000,
    }).then(list => {
      setConnected(true)
      setEvents(list.map(event => ({
        ...event,
        color: getColor(event.id),
        extendedProps: { ...(event.extendedProps || {}), sourceType: 'google' },
      })))
    }).catch(err => {
      if (err.status === 409) { setConnected(false); setEvents([]) }
      else setError(err.detail?.message || err.detail || 'Could not load Google Calendar events.')
    }).finally(() => setLoading(false))
  }

  useEffect(() => {
    setChecking(true)
    queryClient.fetchQuery({
      queryKey: queryKeys.calendarConnection,
      queryFn: () => getCalendarConnection(token),
      staleTime: 60_000,
    }).then(result => setConnected(result.connected)).catch(() => {})
      .finally(() => setChecking(false))
  }, [token])

  const onDatesSet = ({ start, end }) => {
    const range = { time_min: start.toISOString(), time_max: end.toISOString() }
    visibleRange.current = range
    refresh(range)
  }
  const upsertEvent = event => {
    setEvents(previous => [...previous.filter(item => item.id !== event.id), {
      ...event,
      color: getColor(event.id),
      extendedProps: { ...(event.extendedProps || {}), sourceType: 'google' },
    }])
    queryClient.setQueriesData({ queryKey: ['calendar-events'] }, previous => (
      Array.isArray(previous) ? [...previous.filter(item => item.id !== event.id), event] : previous
    ))
  }
  const removeEvent = eventId => {
    setEvents(previous => previous.filter(item => item.id !== eventId))
    queryClient.setQueriesData({ queryKey: ['calendar-events'] }, previous => (
      Array.isArray(previous) ? previous.filter(item => item.id !== eventId) : previous
    ))
  }

  useEffect(() => subscribe(data => {
    if (data.type === 'calendar_event_created' || data.type === 'calendar_event_updated') upsertEvent(data.event)
    if (data.type === 'calendar_event_deleted') removeEvent(data.event_id)
    if (['task_suggested', 'task_created', 'task_updated', 'task_submitted', 'task_reviewed'].includes(data.type)) {
      setTasks(previous => upsertTaskWithContext(previous, data.task))
    }
    if (data.type === 'task_deleted') setTasks(previous => previous.filter(task => task.id !== data.task_id))
  }), [setTasks, subscribe])

  const selectCalendarItem = ({ event, jsEvent }) => {
    jsEvent.preventDefault()
    if (event.extendedProps.sourceType === 'task') {
      setSelected({ kind: 'task', task: event.extendedProps.task })
      return
    }
    setSelected({ kind: 'google', event })
  }

  const removeSelected = async () => {
    if (selected?.kind !== 'google' || deleting) return
    setDeleting(true)
    try { await deleteCalendarEvent(token, selected.event.id); removeEvent(selected.event.id); setSelected(null) }
    catch (err) { setError(err.detail?.message || err.detail || 'Could not delete this event.') }
    finally { setDeleting(false) }
  }
  const disconnect = async () => {
    try { await disconnectCalendar(token); queryClient.setQueryData(queryKeys.calendarConnection, { connected: false }); setConnected(false); setEvents([]) }
    catch (err) { setError(err.detail?.message || err.detail || 'Could not disconnect Google Calendar.') }
  }
  const action = connected ? <div className="d-flex gap-2"><button className="btn btn-light" onClick={disconnect}><i className="bi bi-google me-2" />Disconnect</button><button className="btn btn-primary" onClick={() => setNewEventOpen(true)}><i className="bi bi-plus-lg me-2" />New event</button></div> : null

  return <div className="page-container calendar-page">
    <PageHeader eyebrow="Schedule" title="Calendar" description="Google events and deadlines from work assigned to you." action={action} />
    {(error || tasksError) && <div className="auth-error mb-3">{error || tasksError.detail || 'Could not load assigned tasks.'}</div>}
    {checking ? <p className="text-muted small">Loading calendar...</p> : connected === false ? <ConnectCalendarCard onConnected={() => { queryClient.setQueryData(queryKeys.calendarConnection, { connected: true }); setConnected(true); refresh() }} /> : <div className="calendar-layout"><section className="content-card calendar-card">
      <div className="calendar-source-toolbar">
        <div><strong>Show on calendar</strong><small>Task deadlines stay in Orbit unless you explicitly add them to Google Calendar.</small></div>
        <div className="calendar-source-filters">
          <button type="button" className={visibleSources.google ? 'active google' : ''} onClick={() => setVisibleSources(previous => ({ ...previous, google: !previous.google }))}><i className="bi bi-google" />Google events <b>{events.length}</b></button>
          <button type="button" className={visibleSources.tasks ? 'active tasks' : ''} onClick={() => setVisibleSources(previous => ({ ...previous, tasks: !previous.tasks }))}><i className="bi bi-check2-square" />Tasks <b>{deadlineTasks.length}</b></button>
        </div>
      </div>
      {(loading || tasksLoading) && <p className="text-muted small mb-2">Refreshing calendar...</p>}
      <FullCalendar plugins={[dayGridPlugin,timeGridPlugin,interactionPlugin,luxonPlugin]} initialView="dayGridMonth" timeZone={HANOI_TZ} headerToolbar={{left:'prev,next today',center:'title',right:'dayGridMonth,timeGridWeek,timeGridDay'}} events={calendarItems} eventClick={selectCalendarItem} datesSet={onDatesSet} height="auto" />
    </section><aside className="detected-sidebar"><div className="detected-head"><span><i className="bi bi-stars" /></span><div><h3>AI-detected events</h3><p>Consent-aware</p></div></div><p className="text-muted small">Group candidates still require a conversation manager to confirm them. The resulting event is written only to that manager's connected calendar. Review suggestions from the relevant conversation or <Link to="/tasks">Tasks</Link>.</p><div className="calendar-task-legend"><strong>Task deadline colors</strong><span><i className="danger" />Overdue / blocked</span><span><i className="warning" />High priority</span><span><i className="primary" />In progress / pending</span></div></aside></div>}
    {selected?.kind === 'google' && <div className="modal-backdrop-custom" onClick={()=>setSelected(null)}><div className="event-modal" onClick={event=>event.stopPropagation()}><button className="icon-btn modal-close" onClick={()=>setSelected(null)}><i className="bi bi-x-lg" /></button><div className="event-modal-icon"><i className="bi bi-calendar-event" /></div><span className="eyebrow">Google event</span><h3>{selected.event.title}</h3><div className="event-detail-row"><i className="bi bi-clock" /><span><strong>{formatDateTime(selected.event.start)}</strong>{selected.event.end && <small>{' → '}{formatDateTime(selected.event.end)}</small>}</span></div>{selected.event.url && <a className="btn btn-primary w-100 mt-3" href={selected.event.url} target="_blank" rel="noreferrer">Open in Google Calendar</a>}<button className="btn btn-light text-danger w-100 mt-2" onClick={removeSelected} disabled={deleting}><i className="bi bi-trash me-2" />{deleting ? 'Deleting...' : 'Delete event'}</button></div></div>}
    {selected?.kind === 'task' && <div className="modal-backdrop-custom" onClick={()=>setSelected(null)}><div className="event-modal task-deadline-modal" onClick={event=>event.stopPropagation()}><button className="icon-btn modal-close" onClick={()=>setSelected(null)}><i className="bi bi-x-lg" /></button><div className="event-modal-icon task"><i className="bi bi-check2-square" /></div><span className="eyebrow">Task deadline · {getTaskScopeLabel(selected.task)}</span><h3>{selected.task.title}</h3><div className="task-deadline-badges"><span className={`priority ${selected.task.priority.toLowerCase()}`}>{selected.task.priority} priority</span><span className={`status ${taskStatusLabel(selected.task).toLowerCase().replaceAll(' ', '-')}`}>{taskStatusLabel(selected.task)}</span></div><div className="event-detail-row"><i className="bi bi-clock" /><span><small>Deadline</small><strong>{formatDateTime(selected.task.due_at)}</strong></span></div>{selected.task.blocked_reason && <div className="event-detail-row"><i className="bi bi-exclamation-octagon" /><span><small>Blocker</small><strong>{selected.task.blocked_reason}</strong></span></div>}<Link className="btn btn-primary w-100 mt-3" to="/tasks"><i className="bi bi-arrow-up-right me-2" />Open in My Tasks</Link><p className="task-calendar-note"><i className="bi bi-info-circle" />This deadline is displayed by Orbit and has not been written to Google Calendar.</p></div></div>}
    <NewEventModal open={newEventOpen} onClose={() => setNewEventOpen(false)} onCreated={upsertEvent} />
  </div>
}

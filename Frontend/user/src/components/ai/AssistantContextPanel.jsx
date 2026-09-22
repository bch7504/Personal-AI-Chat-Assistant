import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { useWorkspace } from '../../context/WorkspaceContext'
import { listCalendarEvents } from '../../api/calendar'
import { useConversationsQuery } from '../../hooks/useWorkspaceData'
import { useMemoriesQuery, useTasksQuery } from '../../hooks/usePersonalData'
import { queryKeys } from '../../query/queryClient'
import { groupTasks } from '../../utils/taskGrouping'
import { formatClock, formatDateShort } from '../../utils/datetime'

const attentionLabel = (task, overdueIds, dueSoonIds) => {
  if (overdueIds.has(task.id)) return { text: 'Quá hạn', tone: 'danger' }
  if (dueSoonIds.has(task.id)) {
    const isToday = task.due_at && new Date(task.due_at).toDateString() === new Date().toDateString()
    return isToday ? { text: 'Hôm nay', tone: 'warning' } : { text: 'Sắp tới', tone: 'primary' }
  }
  return { text: task.priority, tone: 'primary' }
}

export default function AssistantContextPanel({ open, width, resizing, onClose, onCollapse, onResizeStart }) {
  const { token } = useAuth()
  const { workspaceId } = useWorkspace()
  const navigate = useNavigate()
  const dateRange = useMemo(() => {
    const now = new Date()
    const weekAhead = new Date(now.getTime() + 7 * 24 * 3600 * 1000)
    return { time_min: now.toISOString(), time_max: weekAhead.toISOString() }
  }, [])
  const conversationsQuery = useConversationsQuery(token, workspaceId)
  const tasksQuery = useTasksQuery(token)
  const memoriesQuery = useMemoriesQuery(token)
  const calendarQuery = useQuery({
    queryKey: queryKeys.calendarEvents(dateRange.time_min, dateRange.time_max),
    queryFn: () => listCalendarEvents(token, dateRange),
    enabled: Boolean(token),
    staleTime: 30_000,
  })
  const conversationsCount = conversationsQuery.data?.conversations?.length ?? null
  const tasks = tasksQuery.items
  const events = calendarQuery.data || []
  const calendarConnected = calendarQuery.error?.status !== 409
  const memories = memoriesQuery.items

  const openTasksCount = tasks.filter(t => t.status === 'pending' || t.status === 'in_progress').length
  const { overdue, dueSoon, highPriority } = groupTasks(tasks)
  const overdueIds = new Set(overdue.map(t => t.id))
  const dueSoonIds = new Set(dueSoon.map(t => t.id))
  const attention = [...overdue, ...dueSoon, ...highPriority].slice(0, 3)
  const nextEvent = events[0]
  const latestMemory = [...memories].sort((a, b) => new Date(b.created_at) - new Date(a.created_at))[0]

  const contextSources = [
    { icon: 'bi-chat-dots', label: 'Trò chuyện', value: conversationsCount ?? '—', color: '#526ff5' },
    { icon: 'bi-check2-square', label: 'Task mở', value: openTasksCount, color: '#8b5cf6' },
    { icon: 'bi-calendar4-week', label: 'Sự kiện', value: calendarConnected ? events.length : '—', color: '#10b981' },
    { icon: 'bi-journal-bookmark', label: 'Memory', value: memories.length, color: '#f59e0b' },
  ]

  return <><div className={`context-backdrop ${open?'show':''}`} onClick={onClose}/><aside className={`assistant-context ${open?'open':''}`}>
    <div className={`context-resize-handle ${resizing ? 'active' : ''}`} role="separator" aria-label="Kéo để thay đổi độ rộng bảng tổng quan" aria-orientation="vertical" title="Kéo sang trái hoặc phải để đổi độ rộng" data-width={`${width}px`} onPointerDown={onResizeStart}><span><i className="bi bi-grip-vertical"/></span></div>
    <div className="context-title"><div><span>Bối cảnh của bạn</span><h3>Tổng quan hôm nay</h3></div><div className="context-title-actions"><button className="icon-btn context-collapse-btn" onClick={onCollapse} aria-label="Ẩn bảng tổng quan để mở rộng vùng chat" title="Ẩn bảng tổng quan"><i className="bi bi-layout-sidebar-inset-reverse"/></button><button className="icon-btn context-close" onClick={onClose} aria-label="Đóng bảng tổng quan"><i className="bi bi-x-lg"/></button></div></div>
    <div className="context-source-grid">{contextSources.map(x=><div key={x.label}><span style={{background:`${x.color}12`,color:x.color}}><i className={`bi ${x.icon}`}/></span><strong>{x.value}</strong><small>{x.label}</small></div>)}</div>
    <section className="context-section">
      <div className="context-section-head"><h4><i className="bi bi-calendar-event"/> Tiếp theo</h4><button onClick={()=>navigate('/calendar')}>Xem lịch</button></div>
      {!calendarConnected && <p className="context-empty">Kết nối Google Calendar để xem sự kiện sắp tới.</p>}
      {calendarConnected && !nextEvent && <p className="context-empty">Không có sự kiện nào sắp tới.</p>}
      {nextEvent && <div className="next-event-card"><div className="event-time-block"><strong>{formatClock(nextEvent.start)}</strong><span>{formatDateShort(nextEvent.start)}</span></div><div><h5>{nextEvent.title}</h5></div></div>}
    </section>
    <section className="context-section">
      <div className="context-section-head"><h4><i className="bi bi-check2-square"/> Cần chú ý</h4><button onClick={()=>navigate('/tasks/inbox')}>Xem task</button></div>
      {attention.length === 0 && <p className="context-empty">Không có task nào cần chú ý.</p>}
      {attention.length > 0 && <div className="attention-list">{attention.map(t=>{
        const label = attentionLabel(t, overdueIds, dueSoonIds)
        return <div key={t.id}><span className={`attention-dot ${label.tone}`}/><p><strong>{t.title}</strong><small>{t.due_at ? formatDateShort(t.due_at) : 'Không có hạn'}</small></p><b>{label.text}</b></div>
      })}</div>}
    </section>
    <section className="context-section">
      <div className="context-section-head"><h4><i className="bi bi-journal-bookmark"/> Memory liên quan</h4><button onClick={()=>navigate('/memory')}>Xem tất cả</button></div>
      {!latestMemory && <p className="context-empty">Chưa có memory nào.</p>}
      {latestMemory && <div className="related-memory"><i className="bi bi-lightbulb"/><p>{latestMemory.detail || latestMemory.title}</p></div>}
    </section>
    <div className="context-permission"><i className="bi bi-shield-check"/><div><strong>Bạn kiểm soát dữ liệu</strong><p>Orbit chỉ đọc những nguồn bạn đã cấp quyền.</p></div><button className="icon-btn"><i className="bi bi-chevron-right"/></button></div>
  </aside></>
}

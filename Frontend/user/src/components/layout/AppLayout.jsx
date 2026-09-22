import { Suspense, useCallback, useRef, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import Sidebar from './Sidebar'
import TopNavbar from './TopNavbar'
import ReminderToast from './ReminderToast'
import TaskSuggestedToast from './TaskSuggestedToast'
import { useAuth } from '../../context/AuthContext'
import { useToast } from '../../context/ToastContext'
import { useChatSocket } from '../../api/useWebSocket'
import { getNotificationPermission, notifyReminderFired, notifyTaskSuggested } from '../../utils/browserNotifications'
import { queryClient, queryKeys } from '../../query/queryClient'

function ContentFallback() {
  return (
    <div className="route-content-fallback" role="status" aria-live="polite">
      <span className="spinner-border spinner-border-sm text-primary" />
      <span>&#272;ang m&#7903; trang&hellip;</span>
    </div>
  )
}

export default function AppLayout() {
  const [open, setOpen] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => window.localStorage.getItem('orbit-sidebar-collapsed') === 'true',
  )
  const { token, user } = useAuth()
  const { pushToast } = useToast()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const handlersRef = useRef(new Set())
  const [toastReminder, setToastReminder] = useState(null)
  const [toastTask, setToastTask] = useState(null)

  const subscribe = useCallback((handler) => {
    handlersRef.current.add(handler)
    return () => handlersRef.current.delete(handler)
  }, [])

  const { sendJson } = useChatSocket(token, (data) => {
    handlersRef.current.forEach(handler => handler(data))
    const isViewingChat = pathname === '/chat' || pathname.startsWith('/channels')
    if (data.type === 'new_message' && data.message?.sender_id !== user?.id && !isViewingChat) {
      queryClient.setQueriesData({ queryKey: ['conversations'] }, previous => {
        if (!previous?.conversations) return previous
        const index = previous.conversations.findIndex(item => item.id === data.message.conversation_id)
        if (index < 0) return previous
        const current = previous.conversations[index]
        const updated = {
          ...current,
          last_message: data.message,
          updated_at: data.message.created_at,
          unread_count: Number(current.unread_count || 0) + 1,
        }
        return {
          ...previous,
          conversations: [updated, ...previous.conversations.slice(0, index), ...previous.conversations.slice(index + 1)],
        }
      })
    }
    if (['reminder_created', 'reminder_updated'].includes(data.type)) {
      queryClient.setQueryData(queryKeys.reminders, previous => [
        ...(previous || []).filter(reminder => reminder.id !== data.reminder.id),
        data.reminder,
      ])
    }
    if (data.type === 'reminder_deleted') {
      queryClient.setQueryData(queryKeys.reminders, previous => (
        previous || []
      ).filter(reminder => reminder.id !== data.reminder_id))
    }
    if (data.type === 'reminder_fired') {
      setToastReminder(data.reminder)
      if (
        user?.preferences?.desktop_notifications !== false &&
        document.visibilityState !== 'visible' &&
        getNotificationPermission() === 'granted'
      ) notifyReminderFired(data.reminder, { onClick: () => navigate('/reminders') })
      queryClient.setQueryData(queryKeys.reminders, previous => (previous || []).map(reminder => (
        reminder.id === data.reminder.id ? { ...reminder, status: 'fired' } : reminder
      )))
    }
    if (data.type === 'task_suggested') {
      setToastTask(data.task)
      if (
        user?.preferences?.ai_suggestion_alerts === true &&
        document.visibilityState !== 'visible' &&
        getNotificationPermission() === 'granted'
      ) notifyTaskSuggested(data.task, { onClick: () => navigate('/tasks') })
    }
    if (data.type === 'usage_budget_alert') pushToast(data.message || 'AI usage budget alert')
  })

  const toggleSidebar = () => {
    setSidebarCollapsed(current => {
      const next = !current
      window.localStorage.setItem('orbit-sidebar-collapsed', String(next))
      return next
    })
  }

  return (
    <div className={`app-shell ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
      <Sidebar open={open} onClose={() => setOpen(false)} collapsed={sidebarCollapsed} onToggleCollapse={toggleSidebar} />
      <div className="app-column"><TopNavbar onMenu={() => setOpen(true)} /><main className="app-main"><Suspense fallback={<ContentFallback />}><Outlet context={{ sendJson, subscribe }} /></Suspense></main></div>
      {toastReminder && <ReminderToast reminder={toastReminder} onClose={() => setToastReminder(null)} />}
      {toastTask && <TaskSuggestedToast task={toastTask} onClose={() => setToastTask(null)} />}
    </div>
  )
}

import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { NavLink, useLocation } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { useWorkspace } from '../../context/WorkspaceContext'
import { useAvailableAgentsQuery, useConversationsQuery } from '../../hooks/useWorkspaceData'
import { preloadPrimaryRoutes, preloadRoute } from '../../router/routeModules'
import { listConversations } from '../../api/chat'
import { listMemories } from '../../api/memories'
import { listReminders } from '../../api/reminders'
import { listTasks } from '../../api/tasks'
import { listAvailableAgentWorkspaces } from '../../api/workspaces'
import { getAIUsageStatus } from '../../api/agent'
import { queryClient, queryKeys } from '../../query/queryClient'

const personalNav = [
  ['assistant', 'bi-stars', 'AI Assistant'], ['chat', 'bi-chat-dots', 'Chats'],
  ['calendar', 'bi-calendar4-week', 'Calendar'], ['reminders', 'bi-bell', 'Reminders'],
  ['memory', 'bi-stars', 'Memory'], ['profile', 'bi-person', 'Profile'],
]

const myWorkNav = [
  ['tasks', 'bi-check2-square', 'My Tasks'],
  ['tasks/inbox', 'bi-inbox', 'Inbox'],
]

const getInitials = (name) => (name || '?').trim().split(/\s+/).map(w => w[0]).slice(0, 2).join('').toUpperCase()

export default function Sidebar({ open, onClose, collapsed, onToggleCollapse }) {
  const { user, token, isAdmin } = useAuth()
  const { workspace, workspaceId, workspaces } = useWorkspace()
  const location = useLocation()
  const [channelsOpen, setChannelsOpen] = useState(() => location.pathname.startsWith('/channels'))
  const organizationWorkspaceId = workspace?.type === 'organization'
    ? workspaceId
    : workspaces.find(item => item.type === 'organization')?.id
  const assignedAgentsQuery = useAvailableAgentsQuery(token, organizationWorkspaceId)
  const conversationsQuery = useConversationsQuery(token, organizationWorkspaceId)
  const usageQuery = useQuery({
    queryKey: queryKeys.aiUsage(user?.id),
    queryFn: () => getAIUsageStatus(token),
    enabled: Boolean(token),
    staleTime: 30_000,
    refetchInterval: 60_000,
  })
  const deliveryWorkspace = (assignedAgentsQuery.data || []).find(agent => agent.agent_profile === 'product_delivery')
  const sidebarChannels = deliveryWorkspace
    ? (conversationsQuery.data?.conversations || [])
      .filter(conversation => conversation.scope === 'channel' && conversation.agent_workspace_id === deliveryWorkspace.id)
      .sort((left, right) => (left.name || '').localeCompare(right.name || '', 'vi'))
    : []
  const personalUnreadCount = (conversationsQuery.data?.conversations || [])
    .filter(conversation => conversation.scope !== 'channel')
    .reduce((total, conversation) => total + Number(conversation.unread_count || 0), 0)
  const channelsExpanded = !collapsed && channelsOpen
  const hasAssignedAgent = (assignedAgentsQuery.data || []).length === 1
  const usage = usageQuery.data
  const usagePct = Math.max(0, Number(usage?.used_pct || 0))
  const usageBarPct = Math.min(100, usagePct)
  const budgetDisabled = usage?.daily_token_budget === 0
  const usageTone = usagePct >= 100 ? 'exceeded' : usagePct >= 80 ? 'warning' : 'normal'
  const usageLabel = budgetDisabled ? 'Không giới hạn' : usage ? `${Math.round(usagePct)}%` : '—'
  const usageDetail = budgetDisabled
    ? 'Không đặt giới hạn token theo ngày'
    : usage
      ? `${Number(usage.tokens_used_today || 0).toLocaleString('vi-VN')} / ${Number(usage.daily_token_budget || 0).toLocaleString('vi-VN')} token của bạn`
      : 'Đang tải hạn mức AI…'
  const adminUrl = import.meta.env.VITE_ADMIN_APP_URL || 'http://localhost:5174'
  useEffect(() => {
    const connection = navigator.connection || navigator.mozConnection || navigator.webkitConnection
    if (connection?.saveData || /(^|-)2g$/.test(connection?.effectiveType || '')) return undefined
    const preload = () => preloadPrimaryRoutes()
    if ('requestIdleCallback' in window) {
      const id = window.requestIdleCallback(preload, { timeout: 2500 })
      return () => window.cancelIdleCallback(id)
    }
    const id = window.setTimeout(preload, 1200)
    return () => window.clearTimeout(id)
  }, [])
  useEffect(() => {
    if (location.pathname === '/channels') setChannelsOpen(true)
  }, [location.pathname])
  const preloadDestination = path => {
    preloadRoute(path)
    if (!token) return
    if (path === '/tasks' || path === '/tasks/inbox') {
      queryClient.prefetchQuery({ queryKey: queryKeys.tasks, queryFn: () => listTasks(token, { scope: 'all' }), staleTime: 30_000 })
    } else if (path === '/reminders') {
      queryClient.prefetchQuery({ queryKey: queryKeys.reminders, queryFn: () => listReminders(token), staleTime: 30_000 })
    } else if (path === '/memory') {
      queryClient.prefetchQuery({ queryKey: queryKeys.memories, queryFn: () => listMemories(token), staleTime: 60_000 })
    } else if (path === '/chat' || path === '/channels') {
      if (organizationWorkspaceId) queryClient.prefetchQuery({ queryKey: queryKeys.conversations(organizationWorkspaceId), queryFn: () => listConversations(token, organizationWorkspaceId), staleTime: 30_000 })
    } else if ((path === '/workspace-agent' || path === '/workspaces') && workspaceId) {
      queryClient.prefetchQuery({ queryKey: queryKeys.availableAgents(workspaceId), queryFn: () => listAvailableAgentWorkspaces(token, workspaceId), staleTime: 2 * 60_000 })
    }
  }
  return (
    <>
      <div className={`sidebar-backdrop ${open ? 'show' : ''}`} onClick={onClose} />
      <aside className={`app-sidebar ${open ? 'open' : ''}`}>
        <div className="brand">
          <span className="brand-mark" title="Orbit"><i className="bi bi-command" /></span>
          <span className="brand-name">Orbit</span>
          <button type="button" className="sidebar-collapse-btn" onClick={onToggleCollapse} aria-label={collapsed ? 'Mở rộng sidebar' : 'Thu gọn sidebar'} title={collapsed ? 'Mở rộng sidebar' : 'Thu gọn sidebar'}>
            <i className={`bi ${collapsed ? 'bi-chevron-right' : 'bi-chevron-left'}`} />
          </button>
        </div>
        <nav className="sidebar-nav">
          <div className="nav-caption">Personal</div>
          {personalNav.map(([path, icon, label]) => (
            // `end` matters here: without it, `/tasks` would also read as "active" while on
            // `/tasks/inbox` (NavLink prefix-matches by default), highlighting both at once.
            <NavLink key={path} to={`/${path}`} end title={collapsed ? label : undefined} onMouseEnter={() => preloadDestination(`/${path}`)} onFocus={() => preloadDestination(`/${path}`)} onClick={onClose} className={({ isActive }) => `side-link ${label === 'AI Assistant' ? 'assistant-link' : ''} ${isActive ? 'active' : ''}`}>
              <i className={`bi ${icon}`} /><span>{label}</span>
              {label === 'Chats' && personalUnreadCount > 0 && <b className="side-count" aria-label={`${personalUnreadCount} tin nhắn chưa đọc`}>{personalUnreadCount > 99 ? '99+' : personalUnreadCount}</b>}
            </NavLink>
          ))}
          <div className="nav-caption workspace-caption">My Work</div>
          {myWorkNav.map(([path, icon, label]) => (
            <NavLink key={path} to={`/${path}`} end title={collapsed ? label : undefined} onMouseEnter={() => preloadDestination(`/${path}`)} onFocus={() => preloadDestination(`/${path}`)} onClick={onClose} className={({ isActive }) => `side-link ${isActive ? 'active' : ''}`}>
              <i className={`bi ${icon}`} /><span>{label}</span>
            </NavLink>
          ))}
          <div className="nav-caption workspace-caption">Workspace</div>
          {hasAssignedAgent && (
            <NavLink to="/workspace-agent" end title={collapsed ? 'Workspace Agent' : undefined} onMouseEnter={() => preloadDestination('/workspace-agent')} onFocus={() => preloadDestination('/workspace-agent')} onClick={onClose} className={({ isActive }) => `side-link assistant-link ${isActive ? 'active' : ''}`}>
              <i className="bi bi-robot" /><span>Workspace Agent</span><span className="new-pill">AI</span>
            </NavLink>
          )}
          <div className="side-channel-nav">
            <NavLink to="/channels" title={collapsed ? 'Channels' : undefined} onMouseEnter={() => preloadDestination('/channels')} onFocus={() => preloadDestination('/channels')} onClick={() => { setChannelsOpen(true); onClose() }} className={({ isActive }) => `side-link ${isActive ? 'active' : ''}`}>
              <i className="bi bi-hash" /><span>Channels</span>
            </NavLink>
            {!collapsed && (
              <button type="button" className="side-channel-toggle" onClick={() => setChannelsOpen(current => !current)} aria-label={channelsExpanded ? 'Thu gọn danh sách channel' : 'Mở danh sách channel'} aria-expanded={channelsExpanded}>
                <i className={`bi ${channelsExpanded ? 'bi-chevron-down' : 'bi-chevron-right'}`} />
              </button>
            )}
          </div>
          {channelsExpanded && (
            <div className="side-channel-list" aria-label="Workspace channels">
              {sidebarChannels.map(channel => (
                <NavLink key={channel.id} to={`/channels/${channel.id}`} end onClick={onClose} className={({ isActive }) => `side-channel-link ${isActive ? 'active' : ''}`}>
                  <i className="bi bi-hash" />
                  <span title={channel.name}>{channel.name}</span>
                  {channel.unread_count > 0 && <b>{channel.unread_count > 99 ? '99+' : channel.unread_count}</b>}
                </NavLink>
              ))}
            </div>
          )}
          <NavLink to="/workspaces" end title={collapsed ? 'Workspaces' : undefined} onMouseEnter={() => preloadDestination('/workspaces')} onFocus={() => preloadDestination('/workspaces')} onClick={onClose} className={({ isActive }) => `side-link ${isActive ? 'active' : ''}`}>
            <i className="bi bi-diagram-3" /><span>Workspaces</span>
          </NavLink>
          {isAdmin && <><div className="nav-caption">Administration</div><a className="side-link" href={adminUrl}><i className="bi bi-box-arrow-up-right" /><span>Open Admin</span></a></>}
        </nav>
        <div className="sidebar-bottom">
          <div className={`ai-usage ${usageTone}`} title="Ngân sách token AI dùng chung của hệ thống, đặt lại vào đầu ngày mới.">
            <div className="ai-usage-heading"><i className="bi bi-stars" /><strong>AI hôm nay</strong><span>{usageLabel}</span></div>
            {!budgetDisabled && <div className="progress" role="progressbar" aria-label="Mức sử dụng AI hôm nay" aria-valuemin="0" aria-valuemax="100" aria-valuenow={usageBarPct}><div className="progress-bar" style={{width:`${usageBarPct}%`}} /></div>}
            <small>{usageDetail}</small>
            <em>{usagePct >= 100 ? 'Personal Agent đang bị giới hạn' : 'Đặt lại lúc 00:00'}</em>
          </div>
          <NavLink to="/profile" className="user-mini"><span className="avatar-photo">{getInitials(user?.display_name)}</span><span><strong>{user?.display_name || 'Loading...'}</strong><small>{user?.email}</small></span><i className="bi bi-three-dots ms-auto" /></NavLink>
        </div>
      </aside>
    </>
  )
}

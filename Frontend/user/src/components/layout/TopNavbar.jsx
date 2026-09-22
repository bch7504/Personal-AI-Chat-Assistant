import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { useWorkspace } from '../../context/WorkspaceContext'
import { useRemindersQuery } from '../../hooks/usePersonalData'
import { useAvailableAgentsQuery } from '../../hooks/useWorkspaceData'
import { useTheme } from '../../context/ThemeContext'
import { getAgentWorkspaceDisplayName } from '../../utils/workspaceLabels'

const getInitials = name => (name || '?').trim().split(/\s+/).map(word => word[0]).slice(0, 2).join('').toUpperCase()

export default function TopNavbar({ onMenu }) {
  const { user, token, logout } = useAuth()
  const { workspaces, workspaceId, selectWorkspace } = useWorkspace()
  const { resolvedTheme, toggleTheme } = useTheme()
  const { pathname } = useLocation()
  const { items: reminders } = useRemindersQuery(token)
  const [helpOpen, setHelpOpen] = useState(false)
  const navigate = useNavigate()
  const organizationWorkspaces = workspaces.filter(workspace => workspace.type === 'organization')
  const selectedOrganization = organizationWorkspaces.find(workspace => workspace.id === workspaceId)
    || organizationWorkspaces[0]
  const organizationWorkspaceId = selectedOrganization?.id || ''
  const isWorkspaceRoute = ['/chat', '/channels', '/relationships', '/workspaces', '/workspace-agent', '/delivery-agent']
    .some(path => pathname === path || pathname.startsWith(`${path}/`))
  const isProductDeliveryRoute = ['/workspaces', '/channels', '/workspace-agent', '/delivery-agent']
    .some(path => pathname === path || pathname.startsWith(`${path}/`))
  const agentsQuery = useAvailableAgentsQuery(token, isProductDeliveryRoute ? organizationWorkspaceId : null)
  const deliveryWorkspace = (agentsQuery.data || []).find(agent => agent.agent_profile === 'product_delivery')
  const workspaceLabel = workspace => isProductDeliveryRoute && workspace.id === organizationWorkspaceId
    ? getAgentWorkspaceDisplayName(deliveryWorkspace) || 'Product Delivery'
    : workspace.name
  const activeReminderCount = reminders.filter(reminder => reminder.status === 'scheduled').length
  const onLogout = () => { logout(); navigate('/login', { replace: true }) }

  useEffect(() => {
    if (isWorkspaceRoute && organizationWorkspaceId && workspaceId !== organizationWorkspaceId) {
      selectWorkspace(organizationWorkspaceId)
    }
  }, [isWorkspaceRoute, organizationWorkspaceId, selectWorkspace, workspaceId])

  return (
    <header className="top-navbar">
      <button className="icon-btn mobile-menu" onClick={onMenu} aria-label="Open menu"><i className="bi bi-list" /></button>
      {isWorkspaceRoute ? (
        <label className="workspace-switcher" aria-label="Không gian làm việc hiện tại">
          <i className="bi bi-buildings" />
          <select value={organizationWorkspaceId} onChange={event => selectWorkspace(event.target.value)}>
            {!organizationWorkspaces.length && <option value="">Chưa tham gia workspace</option>}
          {organizationWorkspaces.map(workspace => <option key={workspace.id} value={workspace.id}>{workspaceLabel(workspace)}</option>)}
          </select>
        </label>
      ) : (
        <div className="workspace-switcher" aria-label="Không gian cá nhân hiện tại"><i className="bi bi-person-lock" /><span>Không gian cá nhân</span></div>
      )}
      <div className="nav-actions">
        <button className="icon-btn" aria-label="Trợ giúp" title="Trợ giúp" onClick={() => setHelpOpen(open => !open)}><i className="bi bi-question-circle" /></button>
        <button className="icon-btn theme-toggle" aria-label={resolvedTheme === 'dark' ? 'Chuyển sang giao diện sáng' : 'Chuyển sang giao diện tối'} title={resolvedTheme === 'dark' ? 'Giao diện sáng' : 'Giao diện tối'} onClick={toggleTheme}><i className={`bi ${resolvedTheme === 'dark' ? 'bi-sun' : 'bi-moon-stars'}`} /></button>
        <button className="icon-btn notification-btn" aria-label={activeReminderCount ? `Mở ${activeReminderCount} nhắc nhở đang hoạt động` : 'Mở nhắc nhở'} title={activeReminderCount ? `${activeReminderCount} nhắc nhở đang hoạt động` : 'Không có nhắc nhở đang hoạt động'} onClick={() => navigate('/reminders')}><i className="bi bi-bell" />{activeReminderCount > 0 && <span className="notification-count" aria-hidden="true">{activeReminderCount > 99 ? '99+' : activeReminderCount}</span>}</button>
        <button className="nav-avatar" aria-label="Mở hồ sơ" title="Mở hồ sơ" onClick={() => navigate('/profile')}>{getInitials(user?.display_name)}</button>
        <button className="icon-btn" onClick={onLogout} aria-label="Log out" title="Log out"><i className="bi bi-box-arrow-right" /></button>
      </div>
      {helpOpen && <div className="top-help-popover"><strong>Orbit Help</strong><span>Dùng thanh bên để mở Chats, Tasks, Calendar và Reminders.</span><button onClick={() => { setHelpOpen(false); navigate('/profile#ai') }}>Mở cài đặt AI</button></div>}
    </header>
  )
}

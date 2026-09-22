import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'

export default function AdminLayout() {
  const [open, setOpen] = useState(false)
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const userAppUrl = import.meta.env.VITE_USER_APP_URL || 'http://localhost:5173'
  const initials = user?.display_name?.split(/\s+/).filter(Boolean).map(part => part[0]).slice(0, 2).join('').toUpperCase() || 'PA'
  const navigation = [
    ['/admin', 'bi-grid-1x2', 'Dashboard'],
    ['/admin/users', 'bi-people', 'Users'],
    ['/admin/workspaces', 'bi-buildings', 'Workspaces'],
    ['/admin/user-data', 'bi-database', 'Support access'],
    ['/admin/ai', 'bi-cpu', 'AI management'],
    ['/admin/ai-usage', 'bi-bar-chart', 'AI usage'],
    ['/admin/audit-log', 'bi-shield-check', 'Audit log'],
  ]
  const signOut = () => { logout(); navigate('/login', { replace: true }) }
  return <div className="admin-shell">
    <div className={`admin-backdrop ${open ? 'show' : ''}`} onClick={() => setOpen(false)} />
    <aside className={`admin-sidebar ${open ? 'open' : ''}`}>
      <div className="admin-brand"><span className="admin-brand-mark"><i className="bi bi-command" /></span><span>Orbit</span><b>ADMIN</b></div>
      <div className="admin-nav-label">Platform</div>
      <nav className="admin-nav">{navigation.map(([to, icon, label]) => <NavLink key={to} to={to} end={to === '/admin'} onClick={() => setOpen(false)} className={({ isActive }) => `admin-nav-link ${isActive ? 'active' : ''}`}><i className={`bi ${icon}`} /><span>{label}</span></NavLink>)}</nav>
      <div className="admin-sidebar-footer">
        <a href={userAppUrl} className="admin-user-app-link"><i className="bi bi-arrow-left-right" /><span><strong>User application</strong><small>Open Orbit workspace</small></span><i className="bi bi-arrow-up-right" /></a>
        <div className="admin-profile"><span>{initials}</span><div><strong>{user?.display_name}</strong><small>{user?.email}</small></div><button onClick={signOut} aria-label="Sign out" title="Sign out"><i className="bi bi-box-arrow-right" /></button></div>
      </div>
    </aside>
    <div className="admin-column">
      <header className="admin-topbar"><button className="admin-icon-button admin-menu-button" onClick={() => setOpen(true)} aria-label="Open navigation"><i className="bi bi-list" /></button><div className="admin-search disabled"><i className="bi bi-search" /><input placeholder="Platform administration" disabled /></div><div className="admin-top-actions"><span className="admin-system-pill"><i /> Secured admin session</span><button className="admin-icon-button" aria-label="Help"><i className="bi bi-question-circle" /></button></div></header>
      <main className="admin-main"><Outlet /></main>
    </div>
  </div>
}

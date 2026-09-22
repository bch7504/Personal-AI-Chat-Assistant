import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'

const links = [
  ['/admin', 'bi-speedometer2', 'Dashboard'],
  ['/admin/users', 'bi-people', 'Users'],
  ['/admin/user-data', 'bi-database', 'Support access'],
  ['/admin/ai', 'bi-cpu', 'AI Management'],
  ['/admin/ai-usage', 'bi-bar-chart', 'AI Usage'],
  ['/admin/audit-log', 'bi-shield-check', 'Audit Log'],
]

export default function AdminSidebar() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const signOut = () => { logout(); navigate('/login') }
  return <aside className="app-sidebar"><div className="brand"><span className="brand-mark"><i className="bi bi-command" /></span><span>Orbit Admin</span></div><nav className="sidebar-nav"><div className="nav-caption">Platform</div>{links.map(([path, icon, label])=><NavLink key={path} to={path} end className={({isActive})=>`side-link ${isActive?'active':''}`}><i className={`bi ${icon}`} /><span>{label}</span></NavLink>)}</nav><div className="sidebar-bottom"><div className="user-mini"><span className="avatar-photo">{(user?.display_name || '?').slice(0,2).toUpperCase()}</span><span><strong>{user?.display_name}</strong><small>{user?.email}</small></span><button className="icon-btn ms-auto" onClick={signOut} title="Sign out"><i className="bi bi-box-arrow-right" /></button></div></div></aside>
}

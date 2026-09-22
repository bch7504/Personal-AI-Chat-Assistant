import { useAuth } from '../context/AuthContext'

export default function AccessDeniedPage() {
  const { logout } = useAuth()
  return <main className="admin-auth-state denied"><span className="admin-auth-mark danger"><i className="bi bi-shield-lock" /></span><h1>Access denied</h1><p>This application is restricted to platform administrators.</p><div><a className="admin-secondary-button" href={import.meta.env.VITE_USER_APP_URL || 'http://localhost:5173'}>Open user application</a><button className="admin-primary-button" onClick={logout}>Sign out</button></div></main>
}

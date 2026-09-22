import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function AdminGuard() {
  const { user, loading, isAdmin } = useAuth()
  if (loading) return <div className="auth-loading">Loading...</div>
  if (!user) return <Navigate to="/login" replace />
  return isAdmin ? <Outlet /> : <Navigate to="/access-denied" replace />
}

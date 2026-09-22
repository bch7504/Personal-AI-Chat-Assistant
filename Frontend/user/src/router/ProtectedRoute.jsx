import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function ProtectedRoute() {
  const { user, loading } = useAuth()
  if (loading) return <div className="auth-loading">Loading...</div>
  return user ? <Outlet /> : <Navigate to="/login" replace />
}

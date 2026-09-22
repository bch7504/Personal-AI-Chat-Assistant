import { useEffect } from 'react'
import { BrowserRouter, Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { useAuth } from '../../src/context/AuthContext'
import AdminShell from './AdminShell'
import AdminLoginPage from './AdminLoginPage'
import AdminRegisterPage from './AdminRegisterPage'
import AdminAIManagementPage from './AdminAIManagementPage'
import AdminAIUsagePage from './AdminAIUsagePage'
import AdminAuditLogPage from './AdminAuditLogPage'
import AdminUsersPage from '../../src/pages/admin/AdminUsersPage'

function AdminGuard() {
  const { user, loading, isAdmin, logout } = useAuth()
  useEffect(() => {
    if (user && !isAdmin) logout()
  }, [user, isAdmin, logout])

  if (loading) return <div className="auth-loading">Loading admin console...</div>
  if (!user || !isAdmin) return <Navigate to="/login" replace />
  return <Outlet />
}

export default function AdminRouter() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<AdminLoginPage />} />
        <Route path="/register" element={<AdminRegisterPage />} />
        <Route element={<AdminGuard />}>
          <Route element={<AdminShell />}>
            <Route index element={<Navigate to="/users" replace />} />
            <Route path="users" element={<AdminUsersPage />} />
            <Route path="ai-management" element={<AdminAIManagementPage />} />
            <Route path="ai-usage" element={<AdminAIUsagePage />} />
            <Route path="audit-log" element={<AdminAuditLogPage />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

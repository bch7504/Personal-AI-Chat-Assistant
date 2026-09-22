import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import AppLayout from '../components/layout/AppLayout'
import ProtectedRoute from './ProtectedRoute'
import { importRoute } from './routeModules'

const LoginPage = lazy(() => import('../pages/LoginPage'))
const RegisterPage = lazy(() => import('../pages/RegisterPage'))
const PrivacyPolicyPage = lazy(() => import('../pages/PrivacyPolicyPage'))
const TermsPage = lazy(() => import('../pages/TermsPage'))
const ChatPage = lazy(importRoute('/chat'))
const TaskPage = lazy(importRoute('/tasks'))
const TaskInboxPage = lazy(importRoute('/tasks/inbox'))
const CalendarPage = lazy(importRoute('/calendar'))
const ReminderPage = lazy(importRoute('/reminders'))
const MemoryPage = lazy(importRoute('/memory'))
const ProfilePage = lazy(importRoute('/profile'))
const PersonalAssistantPage = lazy(importRoute('/assistant'))
const RelationshipsPage = lazy(importRoute('/relationships'))
const WorkspaceManagementPage = lazy(importRoute('/workspaces'))
const WorkspaceAgentPage = lazy(importRoute('/workspace-agent'))
const WorkspaceGroupsPage = lazy(importRoute('/channels'))

function RouteFallback() {
  return (
    <div className="d-flex justify-content-center align-items-center min-vh-100" role="status">
      <div className="spinner-border text-primary" aria-label="Loading page" />
    </div>
  )
}

export default function AppRouter() {
  return (
    <BrowserRouter>
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/" element={<Navigate to="/login" replace />} />
          <Route path="/privacy" element={<PrivacyPolicyPage />} />
          <Route path="/terms" element={<TermsPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route element={<ProtectedRoute />}>
            <Route element={<AppLayout />}>
              <Route path="/assistant" element={<PersonalAssistantPage />} />
              <Route path="/chat" element={<ChatPage />} />
              <Route path="/relationships" element={<RelationshipsPage />} />
              <Route path="/workspaces" element={<WorkspaceManagementPage />} />
              <Route path="/channels" element={<WorkspaceGroupsPage />} />
              <Route path="/channels/:conversationId" element={<ChatPage mode="channel" />} />
              <Route path="/groups" element={<Navigate to="/channels" replace />} />
              <Route path="/workspace-agent" element={<WorkspaceAgentPage />} />
              <Route path="/delivery-agent" element={<Navigate to="/workspace-agent" replace />} />
              <Route path="/quality-agent" element={<Navigate to="/workspace-agent" replace />} />
              <Route path="/tasks" element={<TaskPage />} />
              <Route path="/tasks/inbox" element={<TaskInboxPage />} />
              <Route path="/calendar" element={<CalendarPage />} />
              <Route path="/reminders" element={<ReminderPage />} />
              <Route path="/memory" element={<MemoryPage />} />
              <Route path="/profile" element={<ProfilePage />} />
            </Route>
          </Route>
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}

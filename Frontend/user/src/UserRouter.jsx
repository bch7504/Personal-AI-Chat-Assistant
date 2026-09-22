import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import AppLayout from '../../src/components/layout/AppLayout'
import ProtectedRoute from '../../src/router/ProtectedRoute'
import LoginPage from '../../src/pages/LoginPage'
import RegisterPage from '../../src/pages/RegisterPage'
import ChatPage from '../../src/pages/ChatPage'
import TaskPage from '../../src/pages/TaskPage'
import TaskInboxPage from '../../src/pages/TaskInboxPage'
import CalendarPage from '../../src/pages/CalendarPage'
import ReminderPage from '../../src/pages/ReminderPage'
import MemoryPage from '../../src/pages/MemoryPage'
import ProfilePage from '../../src/pages/ProfilePage'
import PersonalAssistantPage from '../../src/pages/PersonalAssistantPage'

export default function UserRouter() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/assistant" replace />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route element={<ProtectedRoute />}>
          <Route element={<AppLayout />}>
            <Route path="/assistant" element={<PersonalAssistantPage />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/tasks" element={<TaskPage />} />
            <Route path="/tasks/inbox" element={<TaskInboxPage />} />
            <Route path="/calendar" element={<CalendarPage />} />
            <Route path="/reminders" element={<ReminderPage />} />
            <Route path="/memory" element={<MemoryPage />} />
            <Route path="/profile" element={<ProfilePage />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/assistant" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

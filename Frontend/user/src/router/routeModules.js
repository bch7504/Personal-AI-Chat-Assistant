const routeModules = {
  '/assistant': () => import('../pages/PersonalAssistantPage'),
  '/chat': () => import('../pages/ChatPage'),
  '/tasks': () => import('../pages/TaskPage'),
  '/tasks/inbox': () => import('../pages/TaskInboxPage'),
  '/calendar': () => import('../pages/CalendarPage'),
  '/reminders': () => import('../pages/ReminderPage'),
  '/memory': () => import('../pages/MemoryPage'),
  '/profile': () => import('../pages/ProfilePage'),
  '/relationships': () => import('../pages/RelationshipsPage'),
  '/workspaces': () => import('../pages/WorkspaceManagementPage'),
  '/channels': () => import('../pages/WorkspaceGroupsPage'),
  '/workspace-agent': () => import('../pages/WorkspaceAgentPage'),
}

export const importRoute = path => routeModules[path]
export const preloadRoute = path => routeModules[path]?.()
export const preloadPrimaryRoutes = () => Promise.allSettled([
  '/assistant', '/chat', '/tasks', '/tasks/inbox', '/calendar', '/reminders', '/memory',
  '/profile', '/relationships', '/channels', '/workspaces', '/workspace-agent',
].map(preloadRoute))

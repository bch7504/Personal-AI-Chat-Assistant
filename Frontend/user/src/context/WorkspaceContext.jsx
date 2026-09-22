import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { useAuth } from './AuthContext'
import { useWorkspacesQuery } from '../hooks/useWorkspaceData'

const WORKSPACE_KEY = 'orbit_workspace_id'
const WorkspaceContext = createContext(null)

export function WorkspaceProvider({ children }) {
  const { token } = useAuth()
  const [workspaceId, setWorkspaceId] = useState(() => localStorage.getItem(WORKSPACE_KEY))
  const workspaceQuery = useWorkspacesQuery(token)
  const workspaces = workspaceQuery.data || []

  const refreshWorkspaces = async (preferredId) => {
    if (!token) return []
    const { data: items = [] } = await workspaceQuery.refetch()
    const selected = items.find(item => item.id === (preferredId || workspaceId))
      || items.find(item => item.type === 'organization')
      || items[0]
    setWorkspaceId(selected?.id || null)
    if (selected) localStorage.setItem(WORKSPACE_KEY, selected.id)
    return items
  }

  useEffect(() => {
    if (!token) {
      setWorkspaceId(null)
      localStorage.removeItem(WORKSPACE_KEY)
      return
    }
    if (!workspaces.length) return
    const selected = workspaces.find(item => item.id === workspaceId)
      || workspaces.find(item => item.type === 'organization')
      || workspaces[0]
    setWorkspaceId(selected?.id || null)
    if (selected) localStorage.setItem(WORKSPACE_KEY, selected.id)
  }, [token, workspaces, workspaceId])

  const selectWorkspace = (id) => {
    if (!workspaces.some(workspace => workspace.id === id)) return
    setWorkspaceId(id)
    localStorage.setItem(WORKSPACE_KEY, id)
  }

  const workspace = useMemo(
    () => workspaces.find(item => item.id === workspaceId) || null,
    [workspaces, workspaceId],
  )

  return (
    <WorkspaceContext.Provider value={{
      workspaces,
      workspace,
      workspaceId,
      selectWorkspace,
      refreshWorkspaces,
    }}>
      {children}
    </WorkspaceContext.Provider>
  )
}

export function useWorkspace() {
  const context = useContext(WorkspaceContext)
  if (!context) throw new Error('useWorkspace must be used within WorkspaceProvider')
  return context
}

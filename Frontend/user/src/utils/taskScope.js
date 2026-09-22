const CONTEXT_FIELDS = [
  'workspace_type',
  'workspace_name',
  'agent_workspace_name',
  'agent_profile',
  'conversation_name',
]

export const getTaskScope = task => {
  if (task?.workspace_type === 'personal' || !task?.agent_workspace_id) return 'personal'
  if (task?.agent_profile === 'product_delivery' || (task?.agent_workspace_id && !task?.agent_profile)) {
    return 'product_delivery'
  }
  return task?.workspace_type === 'organization' ? 'workspace' : 'personal'
}

export const getTaskScopeLabel = task => {
  const scope = getTaskScope(task)
  if (scope === 'personal') return 'Personal'
  if (scope === 'product_delivery') return task.agent_workspace_name || 'Product Delivery'
  return task.agent_workspace_name || task.workspace_name || 'Workspace'
}

export const upsertTaskWithContext = (items, task) => {
  const existing = items.find(item => item.id === task.id)
  if (!existing) return [...items, task]
  const merged = { ...existing, ...task }
  CONTEXT_FIELDS.forEach(field => {
    if (merged[field] == null && existing[field] != null) merged[field] = existing[field]
  })
  return [...items.filter(item => item.id !== task.id), merged]
}

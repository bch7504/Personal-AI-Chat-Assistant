export const getAgentWorkspaceDisplayName = workspace => {
  if (!workspace) return ''
  if (workspace.agent_profile !== 'product_delivery') return workspace.name
  return (workspace.name || 'Product Delivery').replace(/\s+demo\s*$/i, '').trim()
}

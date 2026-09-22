import { useEffect, useMemo, useState } from 'react'
import { AdminPageHeader, EmptyState, StatusBadge } from '../../components/AdminCommon'
import { useAuth } from '../../context/AuthContext'
import {
  addManagedWorkspaceMember,
  assignManagedWorkspaceLead,
  createManagedWorkspace,
  getCompany,
  listManagedWorkspaceMembers,
  listManagedWorkspaces,
  listUsers,
  revokeManagedWorkspaceMember,
  updateManagedWorkspace,
} from '../../api/admin'

const blankWorkspace = {
  name: '', key: '', agent_profile: 'product_delivery', lead_email: '',
}
const blankMember = { email: '', business_role: 'member' }

const profileLabel = profile => ({
  product_delivery: 'Product Delivery Agent',
  quality_assurance: 'Quality Assurance Agent',
  executive: 'Executive Agent',
}[profile] || profile)

export default function AdminWorkspacesPage() {
  const { token } = useAuth()
  const [company, setCompany] = useState(null)
  const [users, setUsers] = useState([])
  const [workspaces, setWorkspaces] = useState([])
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState('')
  const [workspaceMembers, setWorkspaceMembers] = useState([])
  const [workspaceForm, setWorkspaceForm] = useState(blankWorkspace)
  const [memberForm, setMemberForm] = useState(blankMember)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const businessUsers = useMemo(
    () => users.filter(user => user.is_active && user.platform_role !== 'platform_admin'),
    [users],
  )

  const refreshWorkspaces = async companyId => {
    if (!companyId) return
    const items = await listManagedWorkspaces(token, companyId)
    setWorkspaces(items)
    setSelectedWorkspaceId(current => (
      items.some(item => item.id === current) ? current : items[0]?.id || ''
    ))
  }

  const refreshMembers = async () => {
    if (!company?.id || !selectedWorkspaceId) {
      setWorkspaceMembers([])
      return
    }
    setWorkspaceMembers(
      await listManagedWorkspaceMembers(token, company.id, selectedWorkspaceId),
    )
  }

  useEffect(() => {
    setLoading(true)
    Promise.all([getCompany(token), listUsers(token)])
      .then(async ([companyItem, userItems]) => {
        setCompany(companyItem)
        setUsers(userItems)
        await refreshWorkspaces(companyItem.id)
      })
      .catch(err => setError(err.detail || 'Could not load workspace administration.'))
      .finally(() => setLoading(false))
  }, [token])

  useEffect(() => {
    refreshMembers().catch(err => setError(err.detail || 'Could not load workspace members.'))
  }, [token, company?.id, selectedWorkspaceId])

  const createWorkspace = async event => {
    event.preventDefault(); setSaving(true); setError('')
    try {
      await createManagedWorkspace(token, company.id, workspaceForm)
      setWorkspaceForm(blankWorkspace)
      await refreshWorkspaces(company.id)
    } catch (err) { setError(err.detail || 'Could not create workspace.') }
    finally { setSaving(false) }
  }

  const changeLead = async (workspace, email) => {
    setError('')
    try {
      await assignManagedWorkspaceLead(token, company.id, workspace.id, email)
      await Promise.all([refreshWorkspaces(company.id), refreshMembers()])
    } catch (err) { setError(err.detail || 'Could not assign workspace lead.') }
  }

  const toggleStatus = async workspace => {
    setError('')
    try {
      await updateManagedWorkspace(token, company.id, workspace.id, {
        status: workspace.status === 'active' ? 'suspended' : 'active',
      })
      await refreshWorkspaces(company.id)
    } catch (err) { setError(err.detail || 'Could not update workspace status.') }
  }

  const addMember = async event => {
    event.preventDefault(); setSaving(true); setError('')
    try {
      await addManagedWorkspaceMember(
        token, company.id, selectedWorkspaceId, memberForm,
      )
      setMemberForm(blankMember)
      await refreshMembers()
    } catch (err) { setError(err.detail || 'Could not add workspace member.') }
    finally { setSaving(false) }
  }

  const revokeMember = async member => {
    setError('')
    try {
      await revokeManagedWorkspaceMember(
        token, company.id, selectedWorkspaceId, member.id,
      )
      await refreshMembers()
    } catch (err) { setError(err.detail || 'Could not revoke workspace member.') }
  }

  return <div className="admin-page">
    <AdminPageHeader
      title="Workspace administration"
      description={`Create and govern workspaces inside ${company?.name || 'the company'}.`}
    />
    {error && <div className="admin-warning-banner"><i className="bi bi-exclamation-triangle" /><div><strong>Workspace action failed</strong><span>{error}</span></div></div>}

    <section className="admin-card admin-workspace-create">
      <div className="admin-section-heading"><span><i className="bi bi-diagram-3" /></span><div><strong>Create a workspace and attach its agent</strong><small>Choose a department agent or create an Executive Workspace for a director. Admin appoints the workspace lead.</small></div></div>
      {company && <form onSubmit={createWorkspace} className="admin-workspace-form">
        <label>Workspace name<input required value={workspaceForm.name} onChange={event => setWorkspaceForm(value => ({ ...value, name: event.target.value }))} placeholder="Product Delivery" /></label>
        <label>Workspace key<input required value={workspaceForm.key} onChange={event => setWorkspaceForm(value => ({ ...value, key: event.target.value }))} placeholder="product-delivery" /></label>
        <label>Supporting agent<select value={workspaceForm.agent_profile} onChange={event => setWorkspaceForm(value => ({ ...value, agent_profile: event.target.value }))}><option value="product_delivery">Product Delivery Agent</option><option value="quality_assurance">Quality Assurance Agent</option><option value="executive">Executive Agent</option></select></label>
        <label>{workspaceForm.agent_profile === 'executive' ? 'Director' : 'Workspace lead'}<select required value={workspaceForm.lead_email} onChange={event => setWorkspaceForm(value => ({ ...value, lead_email: event.target.value }))}><option value="">Select person</option>{businessUsers.map(user => <option key={user.id} value={user.email}>{user.display_name} — {user.email}</option>)}</select></label>
        <button className="admin-primary-button" disabled={saving}><i className="bi bi-plus-lg" />{saving ? 'Creating…' : 'Create workspace'}</button>
      </form>}
    </section>

    <section className="admin-card admin-table-card">
      <div className="admin-table-toolbar"><div><strong>Company workspaces</strong><small>{workspaces.length} configured workspaces</small></div></div>
      <div className="admin-table-scroll"><table className="admin-table admin-workspace-table"><thead><tr><th>Workspace</th><th>Supporting agent</th><th>Lead / Director</th><th>Status</th><th>Action</th></tr></thead><tbody>{workspaces.map(item => <tr key={item.id}><td><strong>{item.name}</strong><small>{item.key}</small></td><td>{profileLabel(item.agent_profile)}</td><td><select value={item.lead_email || ''} onChange={event => changeLead(item, event.target.value)}>{businessUsers.map(user => <option key={user.id} value={user.email}>{user.display_name}</option>)}</select><small>{item.lead_email}</small></td><td><StatusBadge value={item.status} /></td><td><button className="admin-secondary-button" onClick={() => toggleStatus(item)}>{item.status === 'active' ? 'Suspend' : 'Activate'}</button></td></tr>)}</tbody></table>{loading && <div className="admin-empty"><span className="spinner-border spinner-border-sm" /><strong>Loading workspaces…</strong></div>}{!loading && !workspaces.length && <EmptyState text="No company workspaces created" />}</div>
    </section>

    {workspaces.length > 0 && <section className="admin-card admin-workspace-create">
      <div className="admin-section-heading"><span><i className="bi bi-people" /></span><div><strong>Assign workspace members</strong><small>Department members use their local agent. Executive Workspace members receive aggregate access through the Executive Agent.</small></div></div>
      <div className="admin-workspace-form"><label>Workspace<select value={selectedWorkspaceId} onChange={event => setSelectedWorkspaceId(event.target.value)}>{workspaces.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label></div>
      <form onSubmit={addMember} className="admin-workspace-form">
        <label>User<select required value={memberForm.email} onChange={event => setMemberForm(value => ({ ...value, email: event.target.value }))}><option value="">Select user</option>{businessUsers.map(user => <option key={user.id} value={user.email}>{user.display_name} — {user.email}</option>)}</select></label>
        <label>Workspace role<select value={memberForm.business_role} onChange={event => setMemberForm(value => ({ ...value, business_role: event.target.value }))}><option value="member">Member</option><option value="executive_viewer">Executive viewer</option></select></label>
        <button className="admin-primary-button" disabled={saving}>Add member</button>
      </form>
      <div className="admin-table-scroll"><table className="admin-table"><thead><tr><th>Member</th><th>Role</th><th>Status</th><th>Action</th></tr></thead><tbody>{workspaceMembers.map(member => <tr key={member.id}><td><strong>{member.display_name}</strong><small>{member.email}</small></td><td>{member.business_role}</td><td><StatusBadge value={member.status} /></td><td><button className="admin-secondary-button" disabled={member.business_role === 'lead'} onClick={() => revokeMember(member)}>Revoke</button></td></tr>)}</tbody></table></div>
    </section>}
  </div>
}

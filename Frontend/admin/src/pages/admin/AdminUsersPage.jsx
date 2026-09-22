import { useEffect, useMemo, useState } from 'react'
import { AdminPageHeader, EmptyState, StatusBadge, UserCell } from '../../components/AdminCommon'
import { useAuth } from '../../context/AuthContext'
import { listUsers, updateUserRole, updateUserStatus } from '../../api/admin'

const userView = user => ({
  ...user,
  name: user.display_name || user.email,
  initials: (user.display_name || user.email).split(/\s+/).map(word => word[0]).slice(0, 2).join('').toUpperCase(),
  color: user.platform_role === 'platform_admin' ? '#8b5bd3' : '#596ff0',
})

export default function AdminUsersPage() {
  const { token, user: currentUser } = useAuth()
  const [users, setUsers] = useState([])
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const refresh = () => {
    setLoading(true); setError('')
    listUsers(token, search).then(setUsers).catch(err => setError(err.detail || 'Could not load users.')).finally(() => setLoading(false))
  }
  useEffect(() => { refresh() }, [token, search])

  const visible = useMemo(() => users.filter(item => !status || (status === 'active' ? item.is_active : !item.is_active)).map(userView), [users, status])
  const updateRole = async item => {
    try {
      const updated = await updateUserRole(token, item.id, item.platform_role === 'platform_admin' ? 'user' : 'admin')
      setUsers(list => list.map(entry => entry.id === updated.id ? updated : entry))
    } catch (err) { setError(err.detail || 'Could not update user role.') }
  }
  const updateStatus = async item => {
    try {
      const updated = await updateUserStatus(token, item.id, !item.is_active)
      setUsers(list => list.map(entry => entry.id === updated.id ? updated : entry))
    } catch (err) { setError(err.detail || 'Could not update user status.') }
  }

  return <div className="admin-page">
    <AdminPageHeader title="User management" description="Manage platform roles and revoke account access immediately." />
    {error && <div className="admin-warning-banner"><i className="bi bi-exclamation-triangle" /><div><strong>User action failed</strong><span>{error}</span></div></div>}
    <div className="admin-summary-strip"><div><span className="blue"><i className="bi bi-people" /></span><div><strong>{users.length}</strong><small>Total users</small></div></div><div><span className="green"><i className="bi bi-person-check" /></span><div><strong>{users.filter(item => item.is_active).length}</strong><small>Active accounts</small></div></div><div><span className="red"><i className="bi bi-shield-lock" /></span><div><strong>{users.filter(item => item.platform_role === 'platform_admin').length}</strong><small>Platform admins</small></div></div></div>
    <section className="admin-card admin-table-card">
      <div className="admin-table-toolbar"><div className="admin-filter-search"><i className="bi bi-search" /><input value={search} onChange={event => setSearch(event.target.value)} placeholder="Search name or email..." /></div><div className="admin-filter-actions"><select value={status} onChange={event => setStatus(event.target.value)}><option value="">All statuses</option><option value="active">Active</option><option value="locked">Locked</option></select></div></div>
      <div className="admin-table-scroll"><table className="admin-table"><thead><tr><th>User</th><th>Joined</th><th>Platform role</th><th>Status</th><th>Actions</th></tr></thead><tbody>{visible.map(item => <tr key={item.id}><td><UserCell user={item} /></td><td>{new Date(item.created_at).toLocaleDateString()}</td><td><StatusBadge value={item.platform_role === 'platform_admin' ? 'Admin' : 'User'} /></td><td><StatusBadge value={item.is_active ? 'Active' : 'Locked'} /></td><td><button className="admin-row-action" disabled={item.id === currentUser?.id} onClick={() => updateRole(item)} title="Toggle platform role"><i className="bi bi-shield-check" /></button><button className={`admin-row-action ${item.is_active ? '' : 'unlock'}`} disabled={item.id === currentUser?.id} onClick={() => updateStatus(item)} title={item.is_active ? 'Lock user' : 'Unlock user'}><i className={`bi ${item.is_active ? 'bi-lock' : 'bi-unlock'}`} /></button></td></tr>)}</tbody></table>{loading && <div className="admin-empty"><span className="spinner-border spinner-border-sm" /><strong>Loading users…</strong></div>}{!loading && !visible.length && <EmptyState text="No users found" />}</div>
    </section>
  </div>
}

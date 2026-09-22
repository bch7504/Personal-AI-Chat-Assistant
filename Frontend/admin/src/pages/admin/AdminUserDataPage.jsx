import { useEffect, useState } from 'react'
import { AdminPageHeader } from '../../components/AdminCommon'
import AdminTaskTable from '../../components/admin/AdminTaskTable'
import AdminReminderTable from '../../components/admin/AdminReminderTable'
import AdminMemoryTable from '../../components/admin/AdminMemoryTable'
import { useAuth } from '../../context/AuthContext'
import {
  listUsers,
  listTasks, deleteTask,
  listReminders, deleteReminder,
  listMemories, deleteMemory,
} from '../../api/admin'
import { listSupportGrants, requestSupportGrant } from '../../api/platform'

const TABS = [
  { key: 'tasks', label: 'Tasks' },
  { key: 'reminders', label: 'Reminders' },
  { key: 'memories', label: 'Memories' },
]

const listFor = { tasks: listTasks, reminders: listReminders, memories: listMemories }
const deleteFor = { tasks: deleteTask, reminders: deleteReminder, memories: deleteMemory }
const confirmLabel = { tasks: 'task', reminders: 'reminder', memories: 'memory' }

export default function AdminUserDataPage() {
  const { token } = useAuth()
  const [tab, setTab] = useState('tasks')
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [users, setUsers] = useState([])
  const [ownerFilter, setOwnerFilter] = useState('')
  const [workspaceId, setWorkspaceId] = useState('')
  const [grants, setGrants] = useState([])
  const [requestedScope, setRequestedScope] = useState('personal_data:read')
  const [reason, setReason] = useState('Investigating a user-reported support issue')
  const [error, setError] = useState('')
  const [requesting, setRequesting] = useState(false)

  useEffect(() => { listUsers(token).then(setUsers) }, [token])

  const hasScope = (scope) => grants.some(grant => grant.status === 'approved' && grant.requested_scope === scope && new Date(grant.expires_at) > new Date())
  const canRead = hasScope('personal_data:read') || hasScope('personal_data:manage')
  const canManage = hasScope('personal_data:manage')

  const refreshGrants = () => {
    if (!workspaceId) { setGrants([]); return }
    listSupportGrants(token, workspaceId).then(setGrants).catch(err => setError(err.detail || 'Could not load support grants.'))
  }

  useEffect(() => { refreshGrants() }, [token, workspaceId])

  const refresh = () => {
    if (!workspaceId || !canRead) { setItems([]); setLoading(false); return }
    setLoading(true)
    setError('')
    listFor[tab](token, workspaceId, ownerFilter || undefined).then(setItems).catch(err => setError(err.detail || 'Could not load scoped user data.')).finally(() => setLoading(false))
  }

  useEffect(() => { refresh() }, [token, tab, ownerFilter, workspaceId, grants])

  const requestAccess = async (event) => {
    event.preventDefault()
    if (!workspaceId || reason.trim().length < 10) return
    setRequesting(true); setError('')
    try {
      await requestSupportGrant(token, { workspace_id: workspaceId, requested_scope: requestedScope, reason: reason.trim(), duration_minutes: 30 })
      await refreshGrants()
    } catch (err) { setError(err.detail || 'Could not request support access.') }
    finally { setRequesting(false) }
  }

  const onDelete = async (item) => {
    if (!window.confirm(`Delete this ${confirmLabel[tab]}? This cannot be undone.`)) return
    if (!canManage) { setError('An approved personal_data:manage grant is required to delete data.'); return }
    await deleteFor[tab](token, workspaceId, item.id)
    setItems(list => list.filter(x => x.id !== item.id))
  }

  return (
    <div className="admin-page">
      <AdminPageHeader title="Support access" description="Time-limited, owner-approved access to workspace support data." />
      {error && <div className="admin-warning-banner"><i className="bi bi-exclamation-triangle" /><div><strong>Support action failed</strong><span>{error}</span></div></div>}
      <section className="admin-card content-card mb-3 p-3">
        <form onSubmit={requestAccess} className="row g-2 align-items-end">
          <label className="col-md-3"><span className="form-label small">Workspace ID</span><input className="form-control" value={workspaceId} onChange={event=>setWorkspaceId(event.target.value.trim())} required/></label>
          <label className="col-md-3"><span className="form-label small">Scope</span><select className="form-select" value={requestedScope} onChange={event=>setRequestedScope(event.target.value)}><option value="personal_data:read">Read support data</option><option value="personal_data:manage">Manage support data</option></select></label>
          <label className="col-md-4"><span className="form-label small">Reason</span><input className="form-control" value={reason} onChange={event=>setReason(event.target.value)} minLength={10} required/></label>
          <div className="col-md-2"><button className="btn btn-primary w-100" disabled={requesting}>{requesting?'Requesting...':'Request access'}</button></div>
        </form>
        {workspaceId && <div className="mt-3 small text-muted">Access: {canManage ? 'Manage approved' : canRead ? 'Read approved' : grants.some(grant=>grant.status==='requested') ? 'Waiting for workspace owner approval' : 'No active grant'}</div>}
      </section>
      <section className="admin-card content-card">
        <div className="card-toolbar">
          <div className="btn-group">
            {TABS.map(t => (
              <button key={t.key} className={`btn btn-sm ${tab === t.key ? 'btn-primary' : 'btn-light'}`} onClick={() => setTab(t.key)}>{t.label}</button>
            ))}
          </div>
          <div className="toolbar-actions">
            <select className="form-select form-select-sm" value={ownerFilter} onChange={e => setOwnerFilter(e.target.value)}>
              <option value="">All users</option>
              {users.map(u => <option key={u.id} value={u.id}>{u.display_name} ({u.email})</option>)}
            </select>
          </div>
        </div>
        {!canRead ? <p className="text-muted small p-3 mb-0">Enter a workspace and obtain owner approval before viewing private support data.</p> : loading ? <p className="text-muted small p-3 mb-0">Loading...</p> : (
          <>
            {tab === 'tasks' && <AdminTaskTable tasks={items} onDelete={onDelete} />}
            {tab === 'reminders' && <AdminReminderTable reminders={items} onDelete={onDelete} />}
            {tab === 'memories' && <AdminMemoryTable memories={items} onDelete={onDelete} />}
          </>
        )}
      </section>
    </div>
  )
}

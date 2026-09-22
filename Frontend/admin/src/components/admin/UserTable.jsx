import Avatar from '../common/Avatar'
import { getInitials, getColor } from '../../utils/avatar'
import { formatDateShort } from '../../utils/datetime'

export default function UserTable({ users, currentUserId, onToggleRole, onToggleStatus }) {
  return (
    <div className="table-responsive task-table-wrap">
      <table className="table task-table align-middle mb-0">
        <thead><tr><th>User</th><th>Role</th><th>Status</th><th>Joined</th><th/></tr></thead>
        <tbody>
          {users.map(u => {
            const isSelf = u.id === currentUserId
            return (
              <tr key={u.id}>
                <td><div className="d-flex align-items-center gap-2"><Avatar initials={getInitials(u.display_name)} color={getColor(u.id)} size={34} /><div><strong>{u.display_name}</strong><small className="d-block text-muted">{u.email}</small></div></div></td>
                <td><span className={`soft-badge ${u.platform_role === 'platform_admin' ? 'danger' : 'info'}`}>{u.platform_role === 'platform_admin' ? 'Platform admin' : 'User'}</span></td>
                <td><span className={`status-badge ${u.is_active ? 'success' : 'secondary'}`}>{u.is_active ? 'Active' : 'Locked'}</span></td>
                <td>{formatDateShort(u.created_at)}</td>
                <td>
                  <div className="d-flex gap-2 justify-content-end">
                    <button className="btn btn-sm btn-light" disabled={isSelf} onClick={() => onToggleRole(u)}>
                      {u.platform_role === 'platform_admin' ? 'Demote' : 'Promote'}
                    </button>
                    <button className="btn btn-sm btn-light" disabled={isSelf} onClick={() => onToggleStatus(u)}>
                      {u.is_active ? 'Lock' : 'Unlock'}
                    </button>
                  </div>
                </td>
              </tr>
            )
          })}
          {!users.length && <tr><td colSpan={5} className="text-center text-muted py-4">No users found.</td></tr>}
        </tbody>
      </table>
    </div>
  )
}

import { formatDateTime } from '../../utils/datetime'

const statusClass = { scheduled: 'primary', fired: 'success', cancelled: 'secondary' }

export default function AdminReminderTable({ reminders, onDelete }) {
  return (
    <div className="table-responsive task-table-wrap">
      <table className="table task-table align-middle mb-0">
        <thead><tr><th>Owner</th><th>Title</th><th>Due at</th><th>Fires at</th><th>Status</th><th>Source</th><th/></tr></thead>
        <tbody>
          {reminders.map(r => (
            <tr key={r.id}>
              <td>{r.owner_id ? <><strong>{r.owner_display_name}</strong><small className="d-block text-muted">{r.owner_email}</small></> : <span className="text-muted">No owner (agent)</span>}</td>
              <td>{r.title}</td>
              <td>{formatDateTime(r.due_at)}</td>
              <td>{formatDateTime(r.fire_at)}</td>
              <td><span className={`status-badge ${statusClass[r.status] || 'secondary'}`}>{r.status}</span></td>
              <td><span className="soft-badge info">{r.source}</span></td>
              <td>
                <div className="d-flex gap-2 justify-content-end">
                  <button className="btn btn-sm btn-light text-danger" onClick={() => onDelete(r)}>Delete</button>
                </div>
              </td>
            </tr>
          ))}
          {!reminders.length && <tr><td colSpan={7} className="text-center text-muted py-4">No reminders found.</td></tr>}
        </tbody>
      </table>
    </div>
  )
}

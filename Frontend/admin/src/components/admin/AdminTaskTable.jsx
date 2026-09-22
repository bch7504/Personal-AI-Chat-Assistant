import { formatDateShort } from '../../utils/datetime'

const priorityClass = { High: 'danger', Medium: 'warning', Low: 'info' }

export default function AdminTaskTable({ tasks, onDelete }) {
  return (
    <div className="table-responsive task-table-wrap">
      <table className="table task-table align-middle mb-0">
        <thead><tr><th>Owner</th><th>Task</th><th>Deadline</th><th>Priority</th><th>Status</th><th>Conversation</th><th/></tr></thead>
        <tbody>
          {tasks.map(t => (
            <tr key={t.id}>
              <td><strong>{t.owner_display_name}</strong><small className="d-block text-muted">{t.owner_email}</small></td>
              <td>{t.title}</td>
              <td>{formatDateShort(t.due_at) || 'No due date'}</td>
              <td><span className={`soft-badge ${priorityClass[t.priority] || 'info'}`}>{t.priority}</span></td>
              <td><span className="status-badge secondary">{t.status}</span></td>
              <td>{t.conversation_label || '—'}</td>
              <td>
                <div className="d-flex gap-2 justify-content-end">
                  <button className="btn btn-sm btn-light text-danger" onClick={() => onDelete(t)}>Delete</button>
                </div>
              </td>
            </tr>
          ))}
          {!tasks.length && <tr><td colSpan={7} className="text-center text-muted py-4">No tasks found.</td></tr>}
        </tbody>
      </table>
    </div>
  )
}

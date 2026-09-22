import { formatDateShort } from '../../utils/datetime'

export default function AdminMemoryTable({ memories, onDelete }) {
  return (
    <div className="table-responsive task-table-wrap">
      <table className="table task-table align-middle mb-0">
        <thead><tr><th>Owner</th><th>Category</th><th>Title</th><th>Detail</th><th>Created</th><th/></tr></thead>
        <tbody>
          {memories.map(m => (
            <tr key={m.id}>
              <td><strong>{m.owner_display_name}</strong><small className="d-block text-muted">{m.owner_email}</small></td>
              <td><span className="soft-badge info">{m.category}</span></td>
              <td>{m.title}</td>
              <td className="text-truncate" style={{maxWidth: 260}}>{m.detail}</td>
              <td>{formatDateShort(m.created_at)}</td>
              <td>
                <div className="d-flex gap-2 justify-content-end">
                  <button className="btn btn-sm btn-light text-danger" onClick={() => onDelete(m)}>Delete</button>
                </div>
              </td>
            </tr>
          ))}
          {!memories.length && <tr><td colSpan={6} className="text-center text-muted py-4">No memories found.</td></tr>}
        </tbody>
      </table>
    </div>
  )
}

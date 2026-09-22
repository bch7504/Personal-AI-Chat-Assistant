import { formatDateShort } from '../../utils/datetime'

export default function ConversationTable({ conversations, onView, onDelete }) {
  return (
    <div className="table-responsive task-table-wrap">
      <table className="table task-table align-middle mb-0">
        <thead><tr><th>Conversation</th><th>Type</th><th>Participants</th><th>Messages</th><th>Created</th><th/></tr></thead>
        <tbody>
          {conversations.map(c => (
            <tr key={c.id}>
              <td><strong>{c.name || (c.type === 'direct' ? 'Direct message' : 'Group chat')}</strong></td>
              <td><span className="soft-badge info">{c.type}</span></td>
              <td>{c.participant_count}</td>
              <td>{c.message_count}</td>
              <td>{formatDateShort(c.created_at)}</td>
              <td>
                <div className="d-flex gap-2 justify-content-end">
                  <button className="btn btn-sm btn-light" onClick={() => onView(c)}>View</button>
                  <button className="btn btn-sm btn-light text-danger" onClick={() => onDelete(c)}>Delete</button>
                </div>
              </td>
            </tr>
          ))}
          {!conversations.length && <tr><td colSpan={6} className="text-center text-muted py-4">No conversations found.</td></tr>}
        </tbody>
      </table>
    </div>
  )
}

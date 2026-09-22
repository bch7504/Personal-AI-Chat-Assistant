import { useEffect, useState } from 'react'
import { useAuth } from '../../context/AuthContext'
import { getConversationMessages } from '../../api/admin'
import Avatar from '../common/Avatar'
import { getInitials, getColor, formatTime } from '../../utils/avatar'

export default function ConversationMessagesModal({ conversation, onClose }) {
  const { token } = useAuth()
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!conversation) return
    setLoading(true)
    getConversationMessages(token, conversation.id).then(setMessages).finally(() => setLoading(false))
  }, [conversation, token])

  if (!conversation) return null

  return (
    <div className="modal show d-block" tabIndex="-1" style={{ background: 'rgba(20,30,50,.32)' }} onClick={onClose}>
      <div className="modal-dialog modal-dialog-centered modal-lg" onClick={e => e.stopPropagation()}>
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title">{conversation.name || (conversation.type === 'direct' ? 'Direct message' : 'Group chat')}</h5>
            <button className="btn-close" onClick={onClose} />
          </div>
          <div className="modal-body" style={{ maxHeight: 420, overflowY: 'auto' }}>
            {loading && <p className="text-muted small mb-0">Loading messages...</p>}
            {!loading && !messages.length && <p className="text-muted small mb-0">No messages in this conversation.</p>}
            <div className="d-flex flex-column gap-3">
              {messages.map(m => (
                <div key={m.id} className="d-flex align-items-start gap-2">
                  <Avatar initials={getInitials(m.sender_display_name)} color={getColor(m.sender_id)} size={32} />
                  <div>
                    <div><strong>{m.sender_display_name}</strong> <small className="text-muted">{formatTime(m.created_at)}</small></div>
                    <div>{m.content}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="modal-footer"><button className="btn btn-light" onClick={onClose}>Close</button></div>
        </div>
      </div>
    </div>
  )
}

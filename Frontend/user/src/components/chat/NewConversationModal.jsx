import { useEffect, useState } from 'react'
import { useAuth } from '../../context/AuthContext'
import { listUsers, createConversation } from '../../api/chat'
import Avatar from '../common/Avatar'
import { getInitials, getColor } from '../../utils/avatar'

export default function NewConversationModal({ open, workspaceId, onClose, onCreated }) {
  const { token } = useAuth()
  const [users, setUsers] = useState([])
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState([])
  const [groupName, setGroupName] = useState('')
  const [groupAiEnabled, setGroupAiEnabled] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    listUsers(token, search, workspaceId).then(setUsers).catch(() => setUsers([]))
  }, [open, search, token, workspaceId])

  useEffect(() => {
    if (open) return
    setSelected([])
    setGroupName('')
    setGroupAiEnabled(false)
    setSearch('')
    setError('')
  }, [open])

  if (!open) return null

  const isGroup = selected.length > 1
  const toggle = id => setSelected(current => current.includes(id)
    ? current.filter(item => item !== id)
    : [...current, id])

  const submit = async event => {
    event.preventDefault()
    if (!selected.length) return
    if (isGroup && !groupName.trim()) {
      setError('Vui lòng đặt tên cho cuộc trò chuyện nhóm.')
      return
    }
    setSubmitting(true)
    setError('')
    try {
      const conversation = await createConversation(token, {
        type: isGroup ? 'group' : 'direct',
        participant_ids: selected,
        name: isGroup ? groupName.trim() : undefined,
        workspace_id: workspaceId,
        ai_enabled: isGroup && groupAiEnabled,
      })
      onCreated(conversation)
      onClose()
    } catch (requestError) {
      setError(requestError.detail || 'Không thể tạo cuộc trò chuyện.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="modal show d-block" tabIndex="-1" style={{ background: 'rgba(20,30,50,.32)' }} onClick={onClose}>
      <div className="modal-dialog modal-dialog-centered" onClick={event => event.stopPropagation()}>
        <div className="modal-content new-conversation-modal">
          <div className="modal-header">
            <div><h5 className="modal-title">Cuộc trò chuyện mới</h5><small>Chọn một hoặc nhiều người trong công ty</small></div>
            <button type="button" className="btn-close" onClick={onClose} aria-label="Đóng" />
          </div>
          <form onSubmit={submit}>
            <div className="modal-body">
              <div className="conversation-privacy-note">
                <i className="bi bi-chat-dots" />
                <span>{isGroup ? `Bạn đang tạo cuộc trò chuyện với ${selected.length} thành viên.` : 'Chọn một người để nhắn trực tiếp hoặc chọn nhiều người để tạo cuộc trò chuyện nhóm.'}</span>
              </div>
              {error && <div className="auth-error">{error}</div>}
              {isGroup && (
                <>
                  <div className="mb-3">
                    <label className="form-label small fw-semibold" htmlFor="conversation-group-name">Tên cuộc trò chuyện</label>
                    <input id="conversation-group-name" className="form-control" placeholder="Ví dụ: Nhóm thiết kế, Đi ăn trưa…" value={groupName} onChange={event => setGroupName(event.target.value)} autoFocus />
                  </div>
                  <div className="conversation-privacy-note mb-3">
                    <i className="bi bi-stars" />
                    <span className="flex-grow-1"><strong>Bật AI cho cả nhóm</strong><small className="d-block">Một chính sách chung: khi bật, mọi thành viên đều dùng được AI trong cuộc trò chuyện này.</small></span>
                    <div className="form-check form-switch m-0">
                      <input id="conversation-group-ai" className="form-check-input" type="checkbox" role="switch" checked={groupAiEnabled} onChange={event => setGroupAiEnabled(event.target.checked)} />
                    </div>
                  </div>
                </>
              )}
              <label className="form-label small fw-semibold" htmlFor="conversation-user-search">Người nhận</label>
              <div className="conversation-member-search"><i className="bi bi-search" /><input id="conversation-user-search" placeholder="Tìm theo tên hoặc email..." value={search} onChange={event => setSearch(event.target.value)} /></div>
              <div className="conversation-member-list">
                {users.map(user => (
                  <label key={user.id} className={selected.includes(user.id) ? 'selected' : ''}>
                    <input type="checkbox" checked={selected.includes(user.id)} onChange={() => toggle(user.id)} />
                    <Avatar initials={getInitials(user.display_name)} color={getColor(user.id)} size={36} />
                    <span><strong>{user.display_name}</strong><small>{user.email}</small></span>
                    {selected.includes(user.id) && <i className="bi bi-check-circle-fill" />}
                  </label>
                ))}
                {!users.length && <div className="conversation-members-empty"><i className="bi bi-person-x" /><span>Không tìm thấy thành viên phù hợp.</span></div>}
              </div>
            </div>
            <div className="modal-footer">
              <span className="conversation-selection-count">{selected.length ? `Đã chọn ${selected.length} người` : 'Chưa chọn người nhận'}</span>
              <button type="button" className="btn btn-light" onClick={onClose}>Hủy</button>
              <button type="submit" className="btn btn-primary" disabled={submitting || !selected.length || (isGroup && !groupName.trim())}>
                {submitting ? 'Đang tạo…' : 'Bắt đầu trò chuyện'}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}

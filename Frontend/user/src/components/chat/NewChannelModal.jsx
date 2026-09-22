import { useEffect, useMemo, useState } from 'react'
import { createChannel, listChannelMembers } from '../../api/chat'
import Avatar from '../common/Avatar'
import { getColor, getInitials } from '../../utils/avatar'

export default function NewChannelModal({ open, token, workspaceId, agentWorkspace, onClose, onCreated }) {
  const [name, setName] = useState('')
  const [channelKind, setChannelKind] = useState('project')
  const [search, setSearch] = useState('')
  const [members, setMembers] = useState([])
  const [selected, setSelected] = useState([])
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open || !workspaceId || !agentWorkspace?.id) return
    setLoading(true)
    setError('')
    listChannelMembers(token, workspaceId, agentWorkspace.id)
      .then(items => {
        setMembers(items)
        setSelected(items.map(item => item.id))
      })
      .catch(requestError => setError(requestError.detail || 'Không thể tải thành viên workspace.'))
      .finally(() => setLoading(false))
  }, [agentWorkspace?.id, open, token, workspaceId])

  useEffect(() => {
    if (open) return
    setName('')
    setChannelKind('project')
    setSearch('')
    setMembers([])
    setSelected([])
    setError('')
  }, [open])

  const visibleMembers = useMemo(() => {
    const keyword = search.trim().toLowerCase()
    if (!keyword) return members
    return members.filter(member =>
      member.display_name.toLowerCase().includes(keyword)
      || member.email.toLowerCase().includes(keyword),
    )
  }, [members, search])

  if (!open) return null

  const toggleMember = id => setSelected(current => current.includes(id)
    ? current.filter(item => item !== id)
    : [...current, id])

  const submit = async event => {
    event.preventDefault()
    if (!name.trim() || !selected.length) return
    setSubmitting(true)
    setError('')
    try {
      const channel = await createChannel(token, workspaceId, agentWorkspace.id, {
        name: name.trim(),
        participant_ids: selected,
        channel_kind: channelKind,
      })
      await onCreated(channel)
      onClose()
    } catch (requestError) {
      setError(requestError.detail || 'Không thể tạo channel.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="modal show d-block" tabIndex="-1" style={{ background: 'rgba(20,30,50,.32)' }} onClick={onClose}>
      <div className="modal-dialog modal-dialog-centered" onClick={event => event.stopPropagation()}>
        <div className="modal-content new-conversation-modal">
          <div className="modal-header">
            <div><h5 className="modal-title">Tạo workspace channel</h5><small>{agentWorkspace?.name || 'Workspace'}</small></div>
            <button type="button" className="btn-close" onClick={onClose} aria-label="Đóng" />
          </div>
          <form onSubmit={submit}>
            <div className="modal-body">
              <div className="conversation-privacy-note channel-governance-note">
                <i className="bi bi-shield-check" />
                <span>Chỉ Lead được tạo channel. Product Delivery Agent chỉ đọc nội dung sau khi channel được bật AI.</span>
              </div>
              {error && <div className="auth-error">{error}</div>}
              <div className="mb-3">
                <label className="form-label small fw-semibold" htmlFor="channel-name">Tên channel</label>
                <div className="input-group"><span className="input-group-text">#</span><input id="channel-name" className="form-control" placeholder="release-34, mobile-team..." value={name} onChange={event => setName(event.target.value)} autoFocus /></div>
              </div>
              <div className="mb-3">
                <label className="form-label small fw-semibold" htmlFor="channel-kind">Loại channel</label>
                <select id="channel-kind" className="form-select" value={channelKind} onChange={event => setChannelKind(event.target.value)}>
                  <option value="project">Project · Theo sản phẩm hoặc dự án</option>
                  <option value="team">Team · Theo đội chuyên môn</option>
                  <option value="release">Release · Theo đợt phát hành</option>
                  <option value="announcement">Announcement · Thông báo chung</option>
                </select>
              </div>
              <div className="d-flex align-items-center justify-content-between mb-1">
                <label className="form-label small fw-semibold mb-0" htmlFor="channel-member-search">Thành viên channel</label>
                {!!members.length && <button type="button" className="link-button" onClick={() => setSelected(selected.length === members.length ? [] : members.map(member => member.id))}>{selected.length === members.length ? 'Bỏ chọn tất cả' : 'Chọn tất cả'}</button>}
              </div>
              <div className="conversation-member-search"><i className="bi bi-search" /><input id="channel-member-search" placeholder="Tìm thành viên trong workspace..." value={search} onChange={event => setSearch(event.target.value)} /></div>
              <div className="conversation-member-list">
                {loading && <div className="conversation-members-empty"><span className="spinner-border spinner-border-sm" /><span>Đang tải thành viên…</span></div>}
                {!loading && visibleMembers.map(member => (
                  <label key={member.id} className={selected.includes(member.id) ? 'selected' : ''}>
                    <input type="checkbox" checked={selected.includes(member.id)} onChange={() => toggleMember(member.id)} />
                    <Avatar initials={getInitials(member.display_name)} color={getColor(member.id)} size={36} />
                    <span><strong>{member.display_name}</strong><small>{member.email}</small></span>
                    {selected.includes(member.id) && <i className="bi bi-check-circle-fill" />}
                  </label>
                ))}
                {!loading && !visibleMembers.length && <div className="conversation-members-empty"><i className="bi bi-person-x" /><span>Không có thành viên phù hợp.</span></div>}
              </div>
            </div>
            <div className="modal-footer">
              <span className="conversation-selection-count">Lead luôn là quản lý channel · Đã chọn {selected.length}</span>
              <button type="button" className="btn btn-light" onClick={onClose}>Hủy</button>
              <button type="submit" className="btn btn-primary" disabled={submitting || !name.trim() || !selected.length}>
                {submitting ? 'Đang tạo…' : 'Tạo channel'}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}

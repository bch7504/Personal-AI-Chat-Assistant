import { useState } from 'react'
import Avatar from '../common/Avatar'
import { getInitials, getColor, formatTime } from '../../utils/avatar'

const MODE_CONTENT = {
  personal: {
    heading: 'Tin nhắn',
    description: 'Hội thoại của bạn trong công ty',
    listTitle: 'Gần đây',
    icon: 'bi-chat-dots',
    search: 'Tìm người hoặc cuộc trò chuyện',
    emptyTitle: 'Chưa có cuộc trò chuyện',
    emptyDescription: 'Bắt đầu trò chuyện với một hoặc nhiều thành viên trong công ty.',
  },
  channel: {
    heading: 'Channels',
    description: 'Kênh làm việc có quản trị',
    listTitle: 'Channels của bạn',
    icon: 'bi-hash',
    search: 'Tìm channel',
    emptyTitle: 'Chưa có channel nào',
    emptyDescription: 'Lead sẽ tạo channel theo team, dự án hoặc luồng công việc.',
  },
}

export default function ConversationList({ mode = 'personal', conversations, selectedId, currentUserId, onSelect, onNewConversation, onToggleAi }) {
  const [search, setSearch] = useState('')
  const content = MODE_CONTENT[mode]
  const filtered = conversations.filter(conversation =>
    conversation.name.toLowerCase().includes(search.trim().toLowerCase()),
  )

  return (
    <section className="conversation-list">
      <div className="conversation-title">
        <div><h2>{content.heading}</h2><span>{content.description}</span></div>
        {onNewConversation && <button className="icon-btn primary-soft" onClick={onNewConversation} aria-label="Tạo cuộc trò chuyện" title="Tạo cuộc trò chuyện"><i className="bi bi-pencil-square" /></button>}
      </div>

      <div className="conversation-search"><i className="bi bi-search" /><input placeholder={content.search} value={search} onChange={event => setSearch(event.target.value)} /></div>
      <div className="conversation-list-heading unified">
        <span><i className={`bi ${content.icon}`} /> {content.listTitle}</span>
        <small>{conversations.length} {mode === 'channel' ? 'channel' : 'cuộc trò chuyện'}</small>
      </div>

      <div className="conversation-items">
        {filtered.map(conversation => {
          const lastMessageIsMine = conversation.last_message?.sender_id === currentUserId
          const visuallyUnread = conversation.unread_count > 0 && !lastMessageIsMine
          return (
          <div
            key={conversation.id}
            className={`chat-item ${conversation.id === selectedId ? 'active' : ''} ${visuallyUnread ? 'unread' : ''}`}
            role="button"
            tabIndex={0}
            onClick={() => onSelect(conversation.id)}
            onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect(conversation.id) } }}
          >
            <span className="chat-item-avatar">
              <Avatar initials={getInitials(conversation.name)} color={getColor(conversation.id)} size={44} />
              {conversation.type === 'group' && <i className={`bi ${conversation.scope === 'channel' ? 'bi-hash' : 'bi-people-fill'}`} />}
            </span>
            <span className="chat-item-body">
              <span className="chat-item-top">
                <strong>{conversation.scope === 'channel' ? `# ${conversation.name}` : conversation.name}</strong>
                <span className="chat-item-top-right">
                  <time>{formatTime(conversation.last_message?.created_at || conversation.updated_at)}</time>
                  <label className="form-check form-switch chat-item-ai-toggle m-0" onClick={event => event.stopPropagation()} title={conversation.type === 'group' && conversation.my_resource_role !== 'manager' ? 'Chỉ người quản lý hội thoại có thể đổi chính sách AI' : conversation.ai_permission_granted ? 'AI đang được đọc hội thoại này - bấm để tắt' : 'AI chưa được đọc hội thoại này - bấm để bật'}>
                    <input
                      className="form-check-input"
                      type="checkbox"
                      role="switch"
                      checked={!!conversation.ai_permission_granted}
                      disabled={conversation.type === 'group' && conversation.my_resource_role !== 'manager'}
                      onChange={event => onToggleAi(conversation.id, event.target.checked)}
                      aria-label={`AI ${conversation.ai_permission_granted ? 'đang bật' : 'đang tắt'} cho ${conversation.name}`}
                    />
                  </label>
                </span>
              </span>
              <span className="chat-item-bottom"><span>{lastMessageIsMine && <em>Bạn: </em>}{conversation.last_message?.content || 'Chưa có tin nhắn'}</span>{visuallyUnread && <b aria-label={`${conversation.unread_count} tin nhắn chưa đọc`}>{conversation.unread_count > 99 ? '99+' : conversation.unread_count}</b>}</span>
              {conversation.type === 'group' && <span className="chat-item-role"><i className={`bi ${conversation.scope === 'channel' ? 'bi-hash' : 'bi-people'}`} /> {conversation.participants.length} thành viên{conversation.scope === 'channel' ? ' · Workspace channel' : ''}</span>}
            </span>
          </div>
        )})}
        {!filtered.length && (
          <div className="conversation-list-empty">
            <i className={`bi ${search ? 'bi-search' : content.icon}`} />
            <strong>{search ? 'Không tìm thấy kết quả' : content.emptyTitle}</strong>
            <p>{search ? 'Thử tìm kiếm bằng tên khác.' : content.emptyDescription}</p>
            {!search && onNewConversation && <button type="button" className="btn btn-sm btn-primary" onClick={onNewConversation}><i className="bi bi-plus-lg me-1" /> Tạo cuộc trò chuyện</button>}
          </div>
        )}
      </div>
    </section>
  )
}

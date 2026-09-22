import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import PageHeader from '../components/common/PageHeader'
import NewChannelModal from '../components/chat/NewChannelModal'
import { useAuth } from '../context/AuthContext'
import { useWorkspace } from '../context/WorkspaceContext'
import { useAvailableAgentsQuery, useConversationsQuery } from '../hooks/useWorkspaceData'
import { getInitials, getColor } from '../utils/avatar'
import { getAgentWorkspaceDisplayName } from '../utils/workspaceLabels'

const formatUpdatedAt = value => {
  if (!value) return 'Chưa có hoạt động'
  return new Intl.DateTimeFormat('vi-VN', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
}

const CHANNEL_SECTIONS = [
  { kind: 'announcement', title: 'Thông báo chung', description: 'Thông tin chính thức dành cho toàn workspace', icon: 'bi-megaphone' },
  { kind: 'team', title: 'Team channels', description: 'Trao đổi ổn định theo đội chuyên môn', icon: 'bi-people' },
  { kind: 'project', title: 'Project channels', description: 'Công việc và ngữ cảnh theo từng sản phẩm hoặc dự án', icon: 'bi-kanban' },
  { kind: 'release', title: 'Release channels', description: 'Điều phối checkpoint, blocker và readiness theo đợt phát hành', icon: 'bi-rocket-takeoff' },
]

export default function WorkspaceGroupsPage() {
  const { token } = useAuth()
  const { workspace, workspaceId } = useWorkspace()
  const navigate = useNavigate()
  const [newChannelOpen, setNewChannelOpen] = useState(false)
  const conversationsQuery = useConversationsQuery(token, workspaceId)
  const agentsQuery = useAvailableAgentsQuery(token, workspace?.type === 'organization' ? workspaceId : null)
  const conversations = conversationsQuery.data?.conversations || []
  const deliveryWorkspace = (agentsQuery.data || []).find(agent => agent.agent_profile === 'product_delivery')
  const deliveryRole = deliveryWorkspace?.current_user_business_role || null
  const deliveryWorkspaceName = getAgentWorkspaceDisplayName(deliveryWorkspace) || 'Product Delivery'
  const loading = conversationsQuery.isPending || (workspace?.type === 'organization' && agentsQuery.isPending)
  const requestError = conversationsQuery.error || agentsQuery.error
  const error = requestError?.detail || (requestError ? 'Không thể tải danh sách channel của workspace.' : '')

  const channels = useMemo(
    () => conversations.filter(conversation =>
      conversation.scope === 'channel'
      && conversation.agent_workspace_id === deliveryWorkspace?.id),
    [conversations, deliveryWorkspace?.id],
  )
  const unreadCount = channels.reduce((total, channel) => total + (channel.unread_count || 0), 0)
  const channelSections = CHANNEL_SECTIONS.map(section => ({
    ...section,
    channels: channels.filter(channel => (channel.channel_kind || 'project') === section.kind),
  })).filter(section => section.channels.length)
  const isLead = deliveryRole === 'lead'

  const onChannelCreated = async channel => {
    await conversationsQuery.refetch()
    navigate(`/channels/${channel.id}`)
  }

  return (
    <div className="page-container workspace-groups-page">
      <PageHeader
        eyebrow="Workspace collaboration"
        title="Workspace Channels"
        description={isLead
          ? 'Tạo và quản trị các channel chính thức theo team, dự án hoặc luồng công việc.'
          : 'Các channel chính thức bạn được tham gia. Chỉ Lead mới có quyền tạo channel.'}
        action={isLead ? <button type="button" className="btn btn-primary" onClick={() => setNewChannelOpen(true)}><i className="bi bi-plus-lg me-2" />Tạo channel</button> : null}
      />

      <div className="group-overview-strip">
        <div><i className="bi bi-buildings" /><span><small>Workspace</small><strong>{deliveryWorkspaceName}</strong></span></div>
        <div><i className="bi bi-person-badge" /><span><small>Vai trò</small><strong>{isLead ? 'Lead · Có quyền tạo channel' : deliveryRole === 'member' ? 'Member' : 'Chưa được gán'}</strong></span></div>
        <div><i className="bi bi-hash" /><span><small>Channel được tham gia</small><strong>{channels.length}</strong></span></div>
        <div><i className="bi bi-chat-left-text" /><span><small>Tin chưa đọc</small><strong>{unreadCount}</strong></span></div>
      </div>

      {workspace?.type !== 'organization' && (
        <div className="alert alert-info">Hãy chọn workspace công ty để xem các channel.</div>
      )}
      {error && <div className="alert alert-warning">{error}</div>}
      {loading && <div className="groups-loading"><span className="spinner-border spinner-border-sm" /> Đang tải channel…</div>}

      {!loading && workspace?.type === 'organization' && !channels.length && !error && (
        <div className="groups-empty-state">
          <i className="bi bi-hash" />
          <h2>Chưa có workspace channel</h2>
          <p>{isLead ? 'Tạo channel đầu tiên cho team hoặc dự án của bạn.' : 'Liên hệ Lead để được tạo hoặc thêm vào channel phù hợp.'}</p>
          {isLead && <button type="button" className="btn btn-primary mt-3" onClick={() => setNewChannelOpen(true)}>Tạo channel đầu tiên</button>}
        </div>
      )}

      {channelSections.map(section => (
        <section className="workspace-channel-section" key={section.kind}>
          <header className="workspace-channel-section-heading">
            <span><i className={`bi ${section.icon}`} /></span>
            <div><h2>{section.title}</h2><p>{section.description}</p></div>
            <b>{section.channels.length}</b>
          </header>
          <div className="workspace-group-grid">
            {section.channels.map(channel => (
              <article className="workspace-group-card" key={channel.id}>
            <header>
              <span className="workspace-group-icon" style={{ background: getColor(channel.id) }}>#</span>
              <div><h2>{channel.name}</h2><p>Cập nhật {formatUpdatedAt(channel.last_message?.created_at || channel.updated_at)}</p></div>
              {channel.unread_count > 0 && <b className="group-unread">{channel.unread_count}</b>}
            </header>
            <div className="group-card-badges">
              <span className={channel.my_resource_role === 'manager' ? 'manager' : ''}>
                <i className="bi bi-shield-check" /> {channel.my_resource_role === 'manager' ? 'Quản lý channel' : 'Thành viên'}
              </span>
              <span className={channel.ai_enabled ? 'ai-on' : ''}>
                <i className={`bi ${channel.ai_enabled ? 'bi-stars' : 'bi-shield-lock'}`} /> AI {channel.ai_enabled ? 'đang bật' : 'đang tắt'}
              </span>
            </div>
            <section className="group-members-preview">
              <div className="group-member-stack">
                {channel.participants.slice(0, 5).map(participant => (
                  <span key={participant.id} title={participant.display_name} style={{ background: getColor(participant.id) }}>{getInitials(participant.display_name)}</span>
                ))}
              </div>
              <strong>{channel.participants.length} thành viên</strong>
            </section>
            <div className="group-last-message">
              <i className="bi bi-chat-quote" />
              <span><small>{channel.last_message?.sender_name || 'Chưa có tin nhắn'}</small><p>{channel.last_message?.content || 'Bắt đầu trao đổi công việc trong channel.'}</p></span>
            </div>
            <button type="button" className="btn btn-primary w-100" onClick={() => navigate(`/channels/${channel.id}`)}>
              <i className="bi bi-hash me-2" />Mở channel
            </button>
              </article>
            ))}
          </div>
        </section>
      ))}

      <NewChannelModal
        open={newChannelOpen}
        token={token}
        workspaceId={workspaceId}
        agentWorkspace={deliveryWorkspace}
        onClose={() => setNewChannelOpen(false)}
        onCreated={onChannelCreated}
      />
    </div>
  )
}

import { useState } from 'react'
import Avatar from '../common/Avatar'
import ConfirmDialog from '../common/ConfirmDialog'
import { getInitials, getColor } from '../../utils/avatar'
import { useToast } from '../../context/ToastContext'

export default function ConversationHeader({ conversation, onBack, onAI, onHide, onLeave, aiGranted, onToggleAi, aiMode = 'individual', canManageAi = false, aiPanelCollapsed = false }) {
  const { pushToast } = useToast()
  const [confirming, setConfirming] = useState(null)
  const handleToggleAi = () => {
    if (aiMode === 'group_managed' && !canManageAi) { onAI(); return }
    onToggleAi(!aiGranted).catch(error => pushToast(error.detail || 'Không thể cập nhật quyền AI.'))
  }
  const confirmAction = (action) => {
    setConfirming(null)
    return action()
  }
  return (
    <header className="conversation-header">
      <button className="icon-btn chat-back" onClick={onBack}><i className="bi bi-arrow-left" /></button>
      <Avatar initials={getInitials(conversation.name)} color={getColor(conversation.id)} size={44} />
      <div className="conversation-meta">
        <div><h3>{conversation.name}</h3><span>{conversation.type === 'group' ? `${conversation.participants.length} members` : 'Direct message'}</span></div>
        <button
          type="button"
          className={`ai-active${aiGranted ? '' : ' off'}`}
          onClick={handleToggleAi}
          title={aiMode === 'group_managed' ? (canManageAi ? 'Manage the group-wide AI policy' : 'AI policy is managed by a conversation manager') : 'Manage your Assistant access'}
        >
          <i className={`bi ${aiGranted ? 'bi-stars' : 'bi-slash-circle'}`} />{aiGranted ? 'Assistant enabled' : 'Assistant disabled'}
        </button>
      </div>
      <div className="header-actions"><button className="icon-btn"><i className="bi bi-telephone" /></button><button className="icon-btn"><i className="bi bi-camera-video" /></button><button className={`icon-btn ai-sidebar-open-btn ${aiPanelCollapsed ? 'show' : ''}`} onClick={onAI} aria-label="Mở bảng AI Assistant" data-tooltip="Mở AI Assistant"><i className="bi bi-stars" /></button><button className="icon-btn ai-mobile-btn" onClick={onAI} aria-label="Mở AI Assistant"><i className="bi bi-stars" /></button><div className="dropdown"><button className="icon-btn" data-bs-toggle="dropdown" aria-label="Conversation actions"><i className="bi bi-three-dots-vertical" /></button><div className="dropdown-menu dropdown-menu-end"><button className="dropdown-item" onClick={()=>setConfirming('hide')}><i className="bi bi-eye-slash me-2"/>Hide for me</button>{conversation.type === 'group' && <button className="dropdown-item text-danger" onClick={()=>setConfirming('leave')}><i className="bi bi-box-arrow-right me-2"/>Leave group</button>}</div></div></div>
      <ConfirmDialog
        open={confirming === 'hide'}
        title="Hide conversation"
        message="Hide this conversation from your list? It will return when a new message arrives."
        confirmLabel="Hide"
        danger={false}
        onCancel={()=>setConfirming(null)}
        onConfirm={()=>confirmAction(onHide)}
      />
      <ConfirmDialog
        open={confirming === 'leave'}
        title="Leave group"
        message="Leave this group? You will immediately lose access."
        confirmLabel="Leave"
        onCancel={()=>setConfirming(null)}
        onConfirm={()=>confirmAction(onLeave)}
      />
    </header>
  )
}

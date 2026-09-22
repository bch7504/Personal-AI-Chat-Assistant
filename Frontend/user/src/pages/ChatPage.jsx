import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useOutletContext, useParams } from 'react-router-dom'
import ConversationList from '../components/chat/ConversationList'
import ConversationHeader from '../components/chat/ConversationHeader'
import MessageArea from '../components/chat/MessageArea'
import AIPanel from '../components/chat/AIPanel'
import NewConversationModal from '../components/chat/NewConversationModal'
import { useAuth } from '../context/AuthContext'
import { useToast } from '../context/ToastContext'
import { useConversations } from '../hooks/useConversations'
import { useMessages } from '../hooks/useMessages'
import { getAiPermission, hideConversation, leaveConversation, markRead, setAiPermission, setGroupAiPolicy } from '../api/chat'
import { useWorkspace } from '../context/WorkspaceContext'

export default function ChatPage({ mode = 'personal' }) {
  const { token, user } = useAuth()
  const { pushToast } = useToast()
  const { workspaceId, workspaces } = useWorkspace()
  const location = useLocation()
  const navigate = useNavigate()
  const { conversationId: channelConversationId } = useParams()
  const organizationWorkspace = workspaces.find(item => item.id === workspaceId && item.type === 'organization')
    || workspaces.find(item => item.type === 'organization')
  const conversationWorkspaceId = organizationWorkspace?.id || workspaceId
  const { sendJson, subscribe } = useOutletContext()
  const isSingleChannel = mode === 'channel' && Boolean(channelConversationId)
  const [mobileChat, setMobileChat] = useState(false)
  const [aiOpen, setAiOpen] = useState(false)
  const [aiPanelCollapsed, setAiPanelCollapsed] = useState(() => {
    try { return window.localStorage.getItem('orbit-chat-ai-panel-collapsed') === 'true' }
    catch { return false }
  })
  const [newConvoOpen, setNewConvoOpen] = useState(false)
  const [selectedId, setSelectedId] = useState(() => channelConversationId || location.state?.conversationId || null)
  const [aiGranted, setAiGranted] = useState(false)
  const [aiContributionAllowed, setAiContributionAllowed] = useState(false)
  const [aiMode, setAiMode] = useState('individual')
  const [canManageAi, setCanManageAi] = useState(false)
  const [unreadHint, setUnreadHint] = useState(0)
  const { conversations, setConversations } = useConversations(token, conversationWorkspaceId)
  const scopedConversations = conversations.filter(conversation => mode === 'channel'
    ? conversation.scope === 'channel'
    : conversation.scope !== 'channel')
  const { messages, setMessages, readReceipts, setReadReceipts, loading: messagesLoading, firstUnreadMessageId, unreadCount } = useMessages(token, selectedId, unreadHint)

  // Direct-chat AI permission is per user; groups expose one manager-owned policy shared by every
  // participant. Keep both modes in one state so the header, list and AI panel always agree.
  useEffect(() => {
    if (!selectedId) { setAiGranted(false); setAiContributionAllowed(false); setAiMode('individual'); setCanManageAi(false); return }
    let cancelled = false
    getAiPermission(token, selectedId).then(res => {
      if (!cancelled) {
        setAiGranted(res.granted)
        setAiContributionAllowed(res.contribution_allowed)
        setAiMode(res.mode || 'individual')
        setCanManageAi(Boolean(res.can_manage))
      }
    }).catch(() => {})
    return () => { cancelled = true }
  }, [selectedId, token])

  const toggleAiPermission = (id, next) => {
    const conversation = conversations.find(item => item.id === id)
    const update = conversation?.type === 'group'
      ? setGroupAiPolicy(token, id, next)
      : setAiPermission(token, id, { granted: next })
    return update.then(res => {
      setConversations(prev => prev.map(item => item.id === id ? {
        ...item,
        ai_permission_granted: res.granted,
        ...(res.mode === 'group_managed' ? { ai_enabled: res.granted } : {}),
      } : item))
      if (id === selectedId) {
        setAiGranted(res.granted)
        setAiContributionAllowed(res.contribution_allowed)
        setAiMode(res.mode || 'individual')
        setCanManageAi(Boolean(res.can_manage))
      }
      return res
    })
  }

  const onToggleAi = (next) => toggleAiPermission(selectedId, next)
  const onToggleAiInList = (id, next) =>
    toggleAiPermission(id, next).catch(error => pushToast(error.detail || 'Không thể cập nhật quyền AI.'))

  const onToggleContribution = (next) =>
    setAiPermission(token, selectedId, { contribution_allowed: next }).then(res => {
      setAiGranted(res.granted)
      setAiContributionAllowed(res.contribution_allowed)
      return res
    })

  const stateRef = useRef({ selectedId, userId: user?.id })
  stateRef.current = { selectedId, userId: user?.id }

  useEffect(() => {
    if (channelConversationId) {
      setSelectedId(channelConversationId)
      setMobileChat(true)
      return
    }
    if (location.state?.conversationId) {
      setSelectedId(location.state.conversationId)
      setMobileChat(true)
    }
  }, [channelConversationId, location.state?.conversationId])

  useEffect(() => {
    if (!scopedConversations.length) return
    const selected = scopedConversations.find(conversation => conversation.id === selectedId)
    if (selected) return
    // Mobile uses separate list/thread screens, so do not skip the list by auto-opening row one.
    if (typeof window !== 'undefined' && window.matchMedia('(max-width: 768px)').matches) return

    const fallback = scopedConversations[0]
    const fallbackId = fallback.id
    setSelectedId(fallbackId)
    setUnreadHint(fallback.unread_count || 0)
    setConversations(prev => prev.map(c => c.id === fallbackId ? { ...c, unread_count: 0 } : c))
  }, [scopedConversations, selectedId, setConversations])

  useEffect(() => subscribe((data) => {
    if (data.type === 'conversation_read') {
      const { selectedId, userId } = stateRef.current
      if (data.conversation_id === selectedId && data.user_id !== userId) {
        setReadReceipts(previous => [
          ...previous.filter(receipt => receipt.user_id !== data.user_id),
          { user_id: data.user_id, display_name: data.display_name, read_at: data.read_at },
        ])
      }
      return
    }
    if (data.type === 'group_ai_policy_changed') {
      setConversations(prev => prev.map(c => c.id === data.conversation_id ? { ...c, ai_enabled: data.enabled } : c))
      if (data.conversation_id === stateRef.current.selectedId) {
        setAiGranted(data.enabled)
        setAiContributionAllowed(data.enabled)
      }
      return
    }
    if (data.type === 'conversation_member_left') {
      setConversations(prev => prev.map(conversation => conversation.id === data.conversation_id
        ? { ...conversation, participants: conversation.participants.filter(participant => participant.id !== data.user_id) }
        : conversation))
      return
    }
    if (data.type !== 'new_message') return
    const { selectedId, userId } = stateRef.current
    const msg = data.message
    if (msg.conversation_id === selectedId) {
      setMessages(prev => prev.some(message => message.id === msg.id) ? prev : [...prev, msg])
      if (msg.sender_id !== userId) {
        setReadReceipts(previous => [
          ...previous.filter(receipt => receipt.user_id !== msg.sender_id),
          { user_id: msg.sender_id, display_name: msg.sender_name, read_at: msg.created_at },
        ])
      }
    }
    setConversations(prev => {
      const idx = prev.findIndex(c => c.id === msg.conversation_id)
      if (idx === -1) return prev
      const bumpUnread = msg.conversation_id !== selectedId && msg.sender_id !== userId
      const updated = { ...prev[idx], last_message: msg, updated_at: msg.created_at, unread_count: bumpUnread ? (prev[idx].unread_count || 0) + 1 : prev[idx].unread_count }
      return [updated, ...prev.slice(0, idx), ...prev.slice(idx + 1)]
    })
  }), [subscribe, setMessages, setReadReceipts, setConversations])

  const selectedConversation = scopedConversations.find(conversation => conversation.id === selectedId) || null

  const onSelect = (id) => {
    setSelectedId(id)
    if (mode === 'channel' && id !== channelConversationId) navigate(`/channels/${id}`)
    setMobileChat(true)
    setUnreadHint(scopedConversations.find(conversation => conversation.id === id)?.unread_count || 0)
    setConversations(prev => prev.map(c => c.id === id ? { ...c, unread_count: 0 } : c))
  }

  const markedReadRef = useRef(null)
  const latestMessageId = messages.at(-1)?.id || 'empty'
  useEffect(() => {
    if (!selectedId || messagesLoading) return
    const readVersion = `${selectedId}:${latestMessageId}`
    if (markedReadRef.current === readVersion) return
    markedReadRef.current = readVersion
    markRead(token, selectedId).catch(() => {
      if (markedReadRef.current === readVersion) markedReadRef.current = null
    })
  }, [latestMessageId, messagesLoading, selectedId, token])

  const onSend = (content) => { if (selectedId) sendJson({ type: 'send_message', conversation_id: selectedId, content }) }

  const setDesktopAiPanelCollapsed = collapsed => {
    setAiPanelCollapsed(collapsed)
    try { window.localStorage.setItem('orbit-chat-ai-panel-collapsed', String(collapsed)) } catch { /* Keep the in-session state. */ }
  }

  const openAiPanel = () => {
    setDesktopAiPanelCollapsed(false)
    setAiOpen(true)
  }
  const closeAiPanel = () => {
    if (window.matchMedia('(min-width: 1201px)').matches) setDesktopAiPanelCollapsed(true)
    setAiOpen(false)
  }

  const onCreated = (conv) => {
    setConversations(prev => [conv, ...prev.filter(c => c.id !== conv.id)])
    setSelectedId(conv.id)
    setMobileChat(true)
  }

  const removeCurrentConversation = () => {
    setConversations(previous => previous.filter(conversation => conversation.id !== selectedId))
    setSelectedId(null)
    setMessages([])
    setMobileChat(false)
  }

  const onHide = async () => {
    if (!selectedId) return
    try { await hideConversation(token, selectedId); removeCurrentConversation() }
    catch (error) { pushToast(error.detail || 'Không thể ẩn hội thoại.') }
  }

  const onLeave = async () => {
    if (!selectedId) return
    try { await leaveConversation(token, selectedId); removeCurrentConversation() }
    catch (error) { pushToast(error.detail || 'Không thể rời nhóm.') }
  }

  return (
    <div className={`chat-layout ${mobileChat ? 'show-chat' : ''} ${aiPanelCollapsed ? 'ai-panel-collapsed' : ''} ${isSingleChannel ? 'single-channel' : ''}`}>
      {!isSingleChannel && <ConversationList mode={mode} conversations={scopedConversations} selectedId={selectedId} currentUserId={user?.id} onSelect={onSelect} onNewConversation={mode === 'personal' ? () => setNewConvoOpen(true) : null} onToggleAi={onToggleAiInList} />}
      <section className="conversation-pane">
        {selectedConversation ? (
          <>
            <ConversationHeader conversation={selectedConversation} onBack={() => isSingleChannel ? navigate('/channels') : setMobileChat(false)} onAI={openAiPanel} onHide={onHide} onLeave={onLeave} aiGranted={aiGranted} onToggleAi={onToggleAi} aiMode={aiMode} canManageAi={canManageAi} aiPanelCollapsed={aiPanelCollapsed} />
            <MessageArea conversation={selectedConversation} messages={messages} readReceipts={readReceipts} currentUserId={user?.id} onSend={onSend} loading={messagesLoading} firstUnreadMessageId={firstUnreadMessageId} unreadCount={unreadCount} />
          </>
        ) : (
          <div className="chat-empty-state"><i className={`bi ${mode === 'channel' ? 'bi-hash' : 'bi-chat-dots'}`} /><p>{mode === 'channel' ? 'Chọn một channel trong workspace.' : 'Chọn một cuộc trò chuyện hoặc bắt đầu cuộc trò chuyện mới.'}</p></div>
        )}
      </section>
      <AIPanel
        open={aiOpen}
        onClose={closeAiPanel}
        messages={messages}
        conversationId={selectedId}
        workspaceId={conversationWorkspaceId}
        granted={aiGranted}
        contributionAllowed={aiContributionAllowed}
        onToggleGrant={onToggleAi}
        onToggleContribution={onToggleContribution}
        aiMode={aiMode}
        canManageAi={canManageAi}
      />
      {mode === 'personal' && <NewConversationModal open={newConvoOpen} workspaceId={conversationWorkspaceId} onClose={() => setNewConvoOpen(false)} onCreated={onCreated} />}
    </div>
  )
}

import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { useAuth } from '../../context/AuthContext'
import { chatWithAgent, resumeAgent } from '../../api/agent'
import { createTask } from '../../api/tasks'
import { backfillEventCandidates, confirmEventCandidate, dismissEventCandidate, listEventCandidates } from '../../api/calendar'
import Markdown from '../common/Markdown'

const actions = [
  ['bi-text-paragraph', 'Summarize', 'Get the key points', '#526ff5'],
  ['bi-check2-square', 'Extract tasks', 'Find action items', '#8b5cf6'],
  ['bi-calendar-event', 'Find schedule', 'Detect events', '#10b981'],
  ['bi-alarm', 'Deadlines', 'Spot due dates', '#f59e0b'],
  ['bi-bell', 'Suggest reminder', 'Draft a reminder', '#ef5675'],
]

const scopeOptions = {
  latest_20: { label: '20 latest messages', request: { kind: 'latest_n', count: 20 }, count: 20 },
  latest_50: { label: '50 latest messages', request: { kind: 'latest_n', count: 50 }, count: 50 },
  unread: { label: 'Unread messages (up to 200)', request: { kind: 'unread', count: 200 }, count: 200 },
  today: { label: 'Today', request: { kind: 'today' }, count: 50 },
  yesterday: { label: 'Yesterday', request: { kind: 'yesterday' }, count: 50 },
  this_week: { label: 'This week', request: { kind: 'this_week' }, count: 50 },
  last_hour: { label: 'Last hour', request: { kind: 'rolling_hours', hours: 1 }, count: 50 },
  last_five_hours: { label: 'Last 5 hours', request: { kind: 'rolling_hours', hours: 5 }, count: 50 },
  custom: { label: 'Custom range', request: { kind: 'custom_range' }, count: 50 },
}

function parseJsonArray(text) {
  const cleaned = text.trim().replace(/^```(?:json)?/i, '').replace(/```$/, '').trim()
  const parsed = JSON.parse(cleaned)
  if (!Array.isArray(parsed)) throw new Error('Expected a JSON array')
  return parsed
}

function describeInterrupt(interrupt) {
  const d = interrupt.draft
  if (interrupt.type === 'reminder') return `Tạo nhắc nhở "${d.title}" lúc ${d.due_at}?`
  if (interrupt.type === 'reminder_update') return `Cập nhật nhắc nhở ${d.reminder_id}?`
  if (interrupt.type === 'reminder_cancel') return `Hủy nhắc nhở ${d.reminder_id}?`
  if (interrupt.type === 'reminder_snooze') return `Hoãn nhắc nhở ${d.reminder_id} thêm ${d.minutes} phút?`
  if (interrupt.type === 'calendar_event') {
    if (d.conflicts?.length) {
      const clash = d.conflicts.map(conflict => conflict.title).join(', ')
      return `Trùng với "${clash}" (${d.start} - ${d.end}). Tạo "${d.summary}" vào giờ đó, hay chọn giờ thay thế bên dưới?`
    }
    return `Tạo sự kiện "${d.summary}" từ ${d.start} đến ${d.end}?`
  }
  if (interrupt.type === 'calendar_event_update') return `Cập nhật sự kiện ${d.event_id}?`
  if (interrupt.type === 'calendar_event_delete') return `Xóa sự kiện ${d.event_id}?`
  return 'Xác nhận hành động này?'
}

function CalendarReminderOptions({ disabled, onConfirm, alternatives = [] }) {
  const [createReminder, setCreateReminder] = useState(true)
  const [leadMinutes, setLeadMinutes] = useState(30)
  const options = { create_reminder: createReminder, reminder_lead_minutes: Number(leadMinutes) }
  return <div className="mt-2"><label className="form-check form-switch"><input className="form-check-input" type="checkbox" checked={createReminder} onChange={event=>setCreateReminder(event.target.checked)} disabled={disabled}/><span className="form-check-label">Nhắc trước sự kiện</span></label>{createReminder && <select className="form-select form-select-sm mb-2" value={leadMinutes} onChange={event=>setLeadMinutes(Number(event.target.value))} disabled={disabled}><option value={15}>15 phút</option><option value={30}>30 phút</option><option value={60}>1 giờ</option><option value={1440}>1 ngày</option></select>}<div className="d-flex flex-wrap gap-2">{alternatives.map((alternative,index)=><button className="btn btn-sm btn-outline-primary" disabled={disabled} key={`${alternative.start}-${index}`} onClick={()=>onConfirm({...options,start:alternative.start,end:alternative.end})}>Dùng {alternative.start} - {alternative.end}</button>)}<button className="btn btn-sm btn-primary" disabled={disabled} onClick={()=>onConfirm(options)}>Xác nhận</button></div></div>
}

function CandidateConfirmation({ candidate, disabled, onConfirm, onDismiss }) {
  const [createReminder, setCreateReminder] = useState(true)
  const [leadMinutes, setLeadMinutes] = useState(30)
  return <div className="mt-2"><label className="form-check form-switch mb-1"><input className="form-check-input" type="checkbox" checked={createReminder} onChange={event=>setCreateReminder(event.target.checked)} disabled={disabled}/><span className="form-check-label">Tạo reminder liên kết</span></label>{createReminder && <select className="form-select form-select-sm mb-2" value={leadMinutes} onChange={event=>setLeadMinutes(Number(event.target.value))} disabled={disabled}><option value={15}>15 phút trước</option><option value={30}>30 phút trước</option><option value={60}>1 giờ trước</option><option value={1440}>1 ngày trước</option></select>}<div className="d-flex gap-2"><button className="btn btn-sm btn-primary" disabled={disabled || candidate.missing_fields.length>0} onClick={()=>onConfirm({create_reminder:createReminder,reminder_lead_minutes:Number(leadMinutes)})}>Confirm</button><button className="btn btn-sm btn-light" disabled={disabled} onClick={onDismiss}>Dismiss</button></div></div>
}

export default function AIPanel({
  open,
  onClose,
  messages = [],
  conversationId = null,
  workspaceId = null,
  granted = false,
  contributionAllowed = false,
  onToggleGrant,
  onToggleContribution,
  aiMode = 'individual',
  canManageAi = false,
}) {
  const { token } = useAuth()
  const [scope, setScope] = useState('latest_20')
  const [customSince, setCustomSince] = useState('')
  const [customUntil, setCustomUntil] = useState('')
  const [runningAction, setRunningAction] = useState(null)
  const [resultTitle, setResultTitle] = useState('')
  const [result, setResult] = useState('')
  const [error, setError] = useState('')
  const [pending, setPending] = useState(null)
  const [contextScope, setContextScope] = useState(null)
  const [eventCandidates, setEventCandidates] = useState([])
  const [candidateBusy, setCandidateBusy] = useState(null)
  const [backfillStatus, setBackfillStatus] = useState(null)
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [permissionExpanded, setPermissionExpanded] = useState(false)

  const refreshEventCandidates = () => {
    if (!conversationId || !granted || aiMode !== 'group_managed') {
      setEventCandidates([])
      return Promise.resolve()
    }
    return listEventCandidates(token, conversationId)
      .then(setEventCandidates)
      .catch(() => setEventCandidates([]))
  }

  useEffect(() => {
    if (open) refreshEventCandidates()
    // refreshEventCandidates deliberately uses the current panel identity only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, conversationId, granted, aiMode])

  const toggleGrant = async (next) => {
    try { await onToggleGrant(next) }
    catch (err) { setError(err.detail || 'Could not update AI permission.') }
  }

  const selectedScope = () => ({
    ...scopeOptions[scope].request,
    ...(scope === 'custom' ? {
      since: customSince ? new Date(customSince).toISOString() : null,
      until: customUntil ? new Date(customUntil).toISOString() : null,
    } : {}),
  })

  const scopedMessages = () => messages.slice(-scopeOptions[scope].count).map(message => ({
    role: 'user', sender: message.sender_name, content: message.content, timestamp: message.created_at,
  }))

  const handleAgentResult = (response) => {
    setContextScope(response.context_scope || null)
    if (response.status === 'error') {
      setError(response.response || 'The AI agent hit an error.')
      return true
    }
    if (response.status === 'interrupted') {
      setPending({ thread_id: response.thread_id, interrupt: response.interrupt })
      setResultTitle('Confirm action')
      setResult(describeInterrupt(response.interrupt))
      return true
    }
    return false
  }

  const callAgent = async (action, prompt, title) => {
    if (!messages.length) { setError('No messages in this conversation yet.'); setResult(''); return null }
    setRunningAction(action); setError(''); setResult(''); setPending(null)
    try {
      const response = await chatWithAgent(token, {
        message: prompt,
        messages: scopedMessages(),
        conversation_id: conversationId,
        workspace_id: workspaceId,
        context_limit: scopeOptions[scope].count,
        scope: selectedScope(),
      })
      if (handleAgentResult(response)) return null
      setResultTitle(title)
      setResult(response.response)
      return response
    } catch (err) {
      setError(err.detail || 'Could not reach the AI agent.')
      return null
    } finally { setRunningAction(null) }
  }

  const runExtractTasks = async () => {
    const response = await callAgent('Extract tasks', 'Extract tasks from this conversation.', 'Tasks extracted')
    if (!response) return
    try {
      const items = parseJsonArray(response.response)
      const settled = await Promise.allSettled(items.map(item => createTask(token, {
        workspace_id: workspaceId,
        title: item.title,
        due_at: item.due_at || null,
        priority: item.priority || 'Medium',
        conversation_id: conversationId,
        source: 'ai_extracted',
        source_message_ids: response.context_scope?.source_message_ids || null,
        consent_scope_hash: response.context_scope?.consent_scope_hash || null,
      })))
      const added = settled.filter(item => item.status === 'fulfilled').length
      setResult(added ? `Added ${added} task${added > 1 ? 's' : ''} for review.` : 'No action items found.')
    } catch (err) { setError(err.detail || 'Could not save extracted tasks.') }
  }

  const handlers = {
    Summarize: () => callAgent('Summarize', 'Summarize this conversation.', 'Summary'),
    'Extract tasks': runExtractTasks,
    'Find schedule': () => callAgent('Find schedule', 'List events, meetings, or scheduled times mentioned in this conversation.', 'Schedule found'),
    Deadlines: () => callAgent('Deadlines', 'List deadlines or due dates mentioned in this conversation.', 'Deadlines found'),
    'Suggest reminder': () => callAgent('Suggest reminder', 'Find the most important deadline or appointment and draft a reminder. Ask me to confirm first.', 'Suggest reminder'),
  }

  const respondToInterrupt = async (approved, edits) => {
    if (!pending || runningAction) return
    setRunningAction('__resume__'); setError('')
    try {
      const response = await resumeAgent(token, { thread_id: pending.thread_id, approved, edits })
      setPending(null)
      if (!handleAgentResult(response)) {
        setResultTitle(approved ? 'Done' : 'Cancelled')
        setResult(response.response)
      }
    } catch (err) { setError(err.detail || 'Could not reach the AI agent.') }
    finally { setRunningAction(null) }
  }

  const askOrbit = async (value = question) => {
    if (!value.trim() || asking) return
    setAsking(true)
    const response = await callAgent('__ask__', value, 'Orbit says')
    if (response) setQuestion('')
    setAsking(false)
  }

  const actOnCandidate = async (candidate, action, options = {}) => {
    setCandidateBusy(candidate.id); setError('')
    try {
      if (action === 'confirm') await confirmEventCandidate(token, candidate.id, options)
      else await dismissEventCandidate(token, candidate.id)
      await refreshEventCandidates()
      setResultTitle(action === 'confirm' ? 'Calendar updated' : 'Suggestion dismissed')
      setResult(action === 'confirm' ? 'The reviewed calendar change was applied.' : 'The suggestion was dismissed.')
    } catch (err) { setError(err.detail || 'Could not update this event suggestion.') }
    finally { setCandidateBusy(null) }
  }

  const scanHistory = async () => {
    setCandidateBusy('__backfill__'); setError('')
    try {
      const response = await backfillEventCandidates(token, conversationId, 200)
      setBackfillStatus(response)
      await refreshEventCandidates()
    } catch (err) { setError(err.detail || 'Could not scan the next history batch.') }
    finally { setCandidateBusy(null) }
  }

  return (
    <><div className={`ai-backdrop ${open ? 'show' : ''}`} onClick={onClose}/><aside className={`ai-panel ${open ? 'open' : ''}`}>
      <div className="ai-panel-header"><div className="ai-title-icon"><i className="bi bi-stars"/></div><div><h3>AI Assistant</h3><span>Context-aware help</span></div><button className="icon-btn ai-close" onClick={onClose} aria-label="Đóng bảng AI Assistant" title="Thu gọn AI Assistant"><i className="bi bi-layout-sidebar"/></button></div>
      <div className={`permission-card ${granted ? 'granted' : ''}`}>
        <div className="permission-top"><div><i className={`bi ${granted ? 'bi-shield-check' : 'bi-shield-lock'}`}/></div><span><strong>{granted ? 'Assistant enabled' : 'Assistant disabled'}</strong><small>{aiMode === 'group_managed' ? 'Group policy · conversation context' : 'Personal access · author consent'}</small></span>{granted && <span className="live-badge">Active</span>}<button className="permission-expand" type="button" aria-expanded={permissionExpanded} aria-label={permissionExpanded ? 'Thu gọn cài đặt AI' : 'Mở cài đặt AI'} onClick={()=>setPermissionExpanded(value=>!value)}><i className={`bi bi-chevron-${permissionExpanded ? 'up' : 'down'}`}/></button></div>
        {permissionExpanded && <div className="permission-details">
          {aiMode === 'group_managed' ? <>
            {canManageAi ? <button className={`btn w-100 ${granted ? 'btn-light text-danger' : 'btn-primary'}`} onClick={()=>toggleGrant(!granted)} disabled={!conversationId}>{granted ? 'Disable AI for this group' : 'Enable AI for this group'}</button> : <div className="alert alert-light border small mb-0">Only a conversation manager can change this policy.</div>}
            <small className="d-block text-muted mt-2">When enabled, all group messages may be processed as continuous context.</small>
          </> : <>
            {granted ? <button className="revoke-btn" onClick={()=>toggleGrant(false)}>Disable my Assistant access</button> : <button className="btn btn-primary w-100" onClick={()=>toggleGrant(true)} disabled={!conversationId}><i className="bi bi-shield-check me-2"/>Enable my Assistant access</button>}
            <label className="d-flex align-items-start gap-2 mt-2 small"><input type="checkbox" className="form-check-input mt-0" checked={contributionAllowed} onChange={event=>onToggleContribution(event.target.checked).catch(err=>setError(err.detail || 'Could not update contribution consent.'))} disabled={!conversationId}/><span>Allow processing of messages I author.</span></label>
          </>}
          {granted && <><label className="mt-2">Request window</label><select value={scope} onChange={event=>setScope(event.target.value)} className="form-select">{Object.entries(scopeOptions).map(([value, option])=><option key={value} value={value}>{option.label}</option>)}</select>{scope === 'custom' && <div className="row g-2 mt-1"><label className="col-6 small">From<input className="form-control form-control-sm" type="datetime-local" value={customSince} onChange={event=>setCustomSince(event.target.value)}/></label><label className="col-6 small">To<input className="form-control form-control-sm" type="datetime-local" value={customUntil} onChange={event=>setCustomUntil(event.target.value)}/></label></div>}</>}
          <small className="d-block text-muted mt-2">Authorized content is sent to the configured AI provider.</small>
        </div>}
      </div>

      {aiMode === 'group_managed' && granted && <div className="ai-calendar-card border rounded-3 p-3 mt-3 small">
        <div className="ai-calendar-head d-flex justify-content-between align-items-center gap-2"><strong>Calendar suggestions</strong>{canManageAi && <button className="btn btn-sm btn-primary ai-history-scan" onClick={scanHistory} disabled={candidateBusy==='__backfill__'}>{candidateBusy==='__backfill__' ? 'Scanning…' : 'Scan 200 messages'}</button>}</div>
        {backfillStatus && <div className="text-muted mt-2">Processed {backfillStatus.processed} messages; found {backfillStatus.extracted}. {backfillStatus.has_more ? 'More history remains.' : 'History scan is complete.'}</div>}
        {!eventCandidates.length && <div className="ai-calendar-empty text-muted">No pending suggestions.</div>}
        {eventCandidates.map(candidate => <div className="border-top mt-2 pt-2" key={candidate.id}><strong>{candidate.operation === 'cancel' ? 'Cancel: ' : candidate.operation === 'update' ? 'Update: ' : ''}{candidate.title}</strong><div className="text-muted">{candidate.start_at ? new Date(candidate.start_at).toLocaleString() : 'Time missing'} · confidence {Math.round(candidate.confidence*100)}%</div>{candidate.missing_fields.length > 0 && <div className="text-warning">Missing: {candidate.missing_fields.join(', ')}</div>}{canManageAi && (candidate.operation === 'create' ? <CandidateConfirmation candidate={candidate} disabled={candidateBusy===candidate.id} onConfirm={options=>actOnCandidate(candidate,'confirm',options)} onDismiss={()=>actOnCandidate(candidate,'dismiss')}/> : <div className="d-flex gap-2 mt-2"><button className="btn btn-sm btn-primary" disabled={candidateBusy===candidate.id || candidate.missing_fields.length>0} onClick={()=>actOnCandidate(candidate,'confirm')}>Confirm</button><button className="btn btn-sm btn-light" disabled={candidateBusy===candidate.id} onClick={()=>actOnCandidate(candidate,'dismiss')}>Dismiss</button></div>)}</div>)}
      </div>}

      <div className="ai-section-title"><span>Quick actions</span><i className="bi bi-lightning-charge-fill"/></div>
      <div className="quick-grid">{actions.map(([icon,title,sub,color])=>{ const isRunning = runningAction === title; const invalidCustom = scope === 'custom' && (!customSince || !customUntil); return <motion.button key={title} whileHover={{y:-2}} whileTap={{scale:.98}} disabled={!granted || Boolean(runningAction) || invalidCustom} onClick={handlers[title]}><span style={{color,background:`${color}12`}}><i className={`bi ${isRunning ? 'bi-hourglass-split' : icon}`}/></span><strong>{title}</strong><small>{isRunning ? 'Working...' : sub}</small></motion.button> })}</div>
      {error && <div className="auth-error">{error}</div>}
      {contextScope && <div className="alert alert-light border py-2 px-3 small mt-2 mb-2">This request used {contextScope.included_message_count}/{contextScope.window_message_count} messages in its selected window.{contextScope.excluded_participants?.length > 0 && <> Excluded authors: {contextScope.excluded_participants.join(', ')}.</>}</div>}
      {result && <div className="ai-result-card border rounded-3 p-3 mt-2 small"><strong className="d-block mb-1">{resultTitle}</strong><Markdown>{result}</Markdown>{pending && (pending.interrupt?.type === 'calendar_event' ? <><CalendarReminderOptions disabled={runningAction==='__resume__'} alternatives={pending.interrupt?.draft?.alternatives || []} onConfirm={edits=>respondToInterrupt(true,edits)}/><button className="btn btn-sm btn-light mt-2" disabled={runningAction==='__resume__'} onClick={()=>respondToInterrupt(false)}>Hủy</button></> : <div className="d-flex flex-wrap gap-2 mt-2"><button className="btn btn-sm btn-primary" disabled={runningAction==='__resume__'} onClick={()=>respondToInterrupt(true)}>Xác nhận</button><button className="btn btn-sm btn-light" disabled={runningAction==='__resume__'} onClick={()=>respondToInterrupt(false)}>Hủy</button></div>)}</div>}
      <div className="ask-card"><div className="ask-title"><span><i className="bi bi-stars"/></span><div><strong>Ask Orbit</strong><small>About this conversation</small></div></div><textarea value={question} onChange={event=>setQuestion(event.target.value)} onKeyDown={event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();askOrbit()}}} placeholder="Ask anything about this conversation..." disabled={!granted}/><div className="ask-footer"><span>AI may make mistakes</span><button disabled={!granted || asking || !question.trim()} onClick={()=>askOrbit()}><i className={`bi ${asking?'bi-hourglass-split':'bi-arrow-up'}`}/></button></div></div>
      <div className="suggested-prompts"><span>Try asking</span><button disabled={asking || !granted} onClick={()=>askOrbit('What decisions were made today?')}>“What decisions were made today?”</button><button disabled={asking || !granted} onClick={()=>askOrbit('Who assigned me tasks?')}>“Who assigned me tasks?”</button></div>
    </aside></>
  )
}

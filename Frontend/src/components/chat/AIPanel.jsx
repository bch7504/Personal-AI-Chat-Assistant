import { useState } from 'react'
import { motion } from 'framer-motion'
import { useAuth } from '../../context/AuthContext'
import { chatWithAgent, resumeAgent } from '../../api/agent'
import { createTask } from '../../api/tasks'

const actions = [
  ['bi-text-paragraph', 'Summarize', 'Get the key points', '#526ff5'],
  ['bi-check2-square', 'Extract tasks', 'Find action items', '#8b5cf6'],
  ['bi-calendar-event', 'Find schedule', 'Detect events', '#10b981'],
  ['bi-alarm', 'Deadlines', 'Spot due dates', '#f59e0b'],
  ['bi-bell', 'Suggest reminder', 'Draft a reminder', '#ef5675'],
]

// Every option here is resolved server-side against the DB (chat_service.get_scoped_messages) -
// none of these filter the already-loaded `messages` prop (that array is at most the last 50
// anyway, see the shared hooks/useMessages.js implementation, which isn't enough for e.g. "This week").
const scopeOptions = [
  ['20 latest messages', { kind: 'latest_n', count: 20 }],
  ['50 latest messages', { kind: 'latest_n', count: 50 }],
  ['Last 1 hour', { kind: 'rolling_hours', hours: 1 }],
  ['Last 5 hours', { kind: 'rolling_hours', hours: 5 }],
  ["Today's messages", { kind: 'today' }],
  ["Yesterday's messages", { kind: 'yesterday' }],
  ["This week's messages", { kind: 'this_week' }],
  ['Unread messages', { kind: 'unread' }],
  ['Custom time range', { kind: 'custom_range' }],
]

function parseJsonArray(text) {
  const cleaned = text.trim().replace(/^```(?:json)?/i, '').replace(/```$/, '').trim()
  const parsed = JSON.parse(cleaned)
  if (!Array.isArray(parsed)) throw new Error('Expected a JSON array')
  return parsed
}

function describeInterrupt(interrupt) {
  const d = interrupt.draft
  if (interrupt.type === 'reminder') return `Tạo nhắc nhở "${d.title}" lúc ${d.due_at}?`
  if (interrupt.type === 'calendar_event') return `Tạo sự kiện "${d.summary}" từ ${d.start} đến ${d.end}?`
  if (interrupt.type === 'calendar_event_update') return `Cập nhật sự kiện ${d.event_id}?`
  if (interrupt.type === 'calendar_event_delete') return `Xoá sự kiện ${d.event_id}?`
  return 'Xác nhận hành động này?'
}

export default function AIPanel({
  open,
  onClose,
  messages = [],
  conversationId = null,
  granted = false,
  onToggleGrant,
}) {
  const { token } = useAuth()
  const [scope, setScope] = useState('20 latest messages')
  const [customSince, setCustomSince] = useState('')
  const [customUntil, setCustomUntil] = useState('')
  const [runningAction, setRunningAction] = useState(null)
  const [resultTitle, setResultTitle] = useState('')
  const [result, setResult] = useState('')
  const [error, setError] = useState('')
  const [pending, setPending] = useState(null)

  const isCustomRangeIncomplete = scope === 'Custom time range' && !customSince && !customUntil

  // Permission itself lives in ChatPage (shared with the header badge) - this just calls up and
  // surfaces a failure locally, same as every other action in this panel.
  const toggleGrant = async (next) => {
    try { await onToggleGrant(next) }
    catch (err) { setError(err.detail || 'Could not update AI permission.') }
  }

  const buildScope = () => {
    const base = scopeOptions.find(([label]) => label === scope)?.[1]
    if (base?.kind !== 'custom_range') return base
    return {
      kind: 'custom_range',
      since: customSince ? `${customSince}:00` : null,
      until: customUntil ? `${customUntil}:00` : null,
    }
  }

  // Shared by every quick action / Ask Orbit: a tool call needing confirmation (reminder,
  // calendar create/update/delete) comes back as status "interrupted" instead of a plain answer.
  const handleAgentResult = (res) => {
    if (res.status === 'error') { setError(res.response || 'The AI agent hit an error.'); return true }
    if (res.status === 'interrupted') {
      setPending({ thread_id: res.thread_id, interrupt: res.interrupt })
      setResultTitle('Confirm action'); setResult(describeInterrupt(res.interrupt))
      return true
    }
    return false
  }

  const respondToInterrupt = async (approved) => {
    if (!pending || runningAction) return
    setRunningAction('__resume__'); setError('')
    try {
      const res = await resumeAgent(token, { thread_id: pending.thread_id, approved })
      setPending(null)
      if (!handleAgentResult(res)) { setResultTitle(approved ? 'Done' : 'Cancelled'); setResult(res.response) }
    } catch (err) { setError(err.detail || 'Could not reach the AI agent.') }
    finally { setRunningAction(null) }
  }

  const runSummarize = async () => {
    if (!messages.length) { setError('No messages in this conversation yet.'); setResult(''); return }
    setRunningAction('Summarize'); setError(''); setResult(''); setPending(null)
    try {
      const res = await chatWithAgent(token, { message: 'Summarize this conversation.', scope: buildScope(), conversation_id: conversationId })
      if (handleAgentResult(res)) return
      setResultTitle('Summary'); setResult(res.response)
    } catch (err) { setError(err.detail || 'Could not summarize this conversation.') }
    finally { setRunningAction(null) }
  }

  const runExtractTasks = async () => {
    if (!messages.length) { setError('No messages in this conversation yet.'); setResult(''); return }
    setRunningAction('Extract tasks'); setError(''); setResult(''); setPending(null)
    try {
      const res = await chatWithAgent(token, { message: 'Extract tasks from this conversation.', scope: buildScope(), conversation_id: conversationId })
      if (handleAgentResult(res)) return
      const items = parseJsonArray(res.response)
      // source: 'proactive' (not 'manual') even though a person clicked the button - these titles
      // came from the LLM reading the conversation, same provenance as the background detector, so
      // they get the same treatment: Accept in Tasks auto-creates the Calendar event + Reminder
      // (task_routes.py::_add_to_calendar_and_reminder gates on source == "proactive").
      const settled = await Promise.allSettled(items.map(item => createTask(token, {
        title: item.title, due_at: item.due_at || null, priority: item.priority || 'Medium',
        conversation_id: conversationId, source: 'proactive',
      })))
      const added = settled.filter(r => r.status === 'fulfilled').length
      setResultTitle('Tasks extracted')
      setResult(added ? `Added ${added} task${added > 1 ? 's' : ''} to your Tasks inbox for review.` : 'No action items found in this conversation.')
    } catch (err) { setError(err.detail || 'Could not extract tasks from this conversation.') }
    finally { setRunningAction(null) }
  }

  const runFindSchedule = async () => {
    if (!messages.length) { setError('No messages in this conversation yet.'); setResult(''); return }
    setRunningAction('Find schedule'); setError(''); setResult(''); setPending(null)
    try {
      const res = await chatWithAgent(token, { message: 'List any events, meetings, or scheduled times mentioned in this conversation.', scope: buildScope(), conversation_id: conversationId })
      if (handleAgentResult(res)) return
      setResultTitle('Schedule found'); setResult(res.response)
    } catch (err) { setError(err.detail || 'Could not find schedule in this conversation.') }
    finally { setRunningAction(null) }
  }

  const runDeadlines = async () => {
    if (!messages.length) { setError('No messages in this conversation yet.'); setResult(''); return }
    setRunningAction('Deadlines'); setError(''); setResult(''); setPending(null)
    try {
      const res = await chatWithAgent(token, { message: 'List any deadlines or due dates mentioned in this conversation.', scope: buildScope(), conversation_id: conversationId })
      if (handleAgentResult(res)) return
      setResultTitle('Deadlines found'); setResult(res.response)
    } catch (err) { setError(err.detail || 'Could not find deadlines in this conversation.') }
    finally { setRunningAction(null) }
  }

  const runSuggestReminder = async () => {
    if (!messages.length) { setError('No messages in this conversation yet.'); setResult(''); return }
    setRunningAction('Suggest reminder'); setError(''); setResult(''); setPending(null)
    try {
      const res = await chatWithAgent(token, {
        message: 'Find the most important deadline or appointment in this conversation and draft a reminder for it (ask me to confirm first).',
        scope: buildScope(),
        conversation_id: conversationId,
      })
      if (handleAgentResult(res)) return
      setResultTitle('Suggest reminder'); setResult(res.response || 'No deadline or appointment found to remind about.')
    } catch (err) { setError(err.detail || 'Could not draft a reminder from this conversation.') }
    finally { setRunningAction(null) }
  }

  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)

  const askOrbit = async (q = question) => {
    if (!q.trim() || asking) return
    setAsking(true); setError(''); setResult(''); setPending(null)
    try {
      const res = await chatWithAgent(token, { message: q, scope: buildScope(), conversation_id: conversationId })
      if (handleAgentResult(res)) return
      setResultTitle('Orbit says'); setResult(res.response)
      setQuestion('')
    } catch (err) { setError(err.detail || 'Could not reach the AI agent.') }
    finally { setAsking(false) }
  }

  const handlers = {
    Summarize: runSummarize, 'Extract tasks': runExtractTasks, 'Find schedule': runFindSchedule,
    Deadlines: runDeadlines, 'Suggest reminder': runSuggestReminder,
  }

  return (
    <><div className={`ai-backdrop ${open ? 'show' : ''}`} onClick={onClose}/><aside className={`ai-panel ${open ? 'open' : ''}`}>
      <div className="ai-panel-header"><div className="ai-title-icon"><i className="bi bi-stars"/></div><div><h3>AI Assistant</h3><span>Context-aware help</span></div><button className="icon-btn ai-close" onClick={onClose}><i className="bi bi-x-lg"/></button></div>
      <div className={`permission-card ${granted ? 'granted' : ''}`}>
        <div className="permission-top"><div><i className={`bi ${granted ? 'bi-shield-check' : 'bi-shield-lock'}`}/></div><span><strong>{granted ? 'Permission granted' : 'Permission required'}</strong><small>{granted ? 'AI can read selected messages' : 'Allow AI to read this conversation'}</small></span>{granted && <span className="live-badge">Active</span>}</div>
        {granted ? <><label>Permission scope</label><select value={scope} onChange={e=>setScope(e.target.value)} className="form-select">{scopeOptions.map(([label])=><option key={label}>{label}</option>)}</select>
          {scope === 'Custom time range' && <div className="d-flex gap-2 mt-2">
            <div className="flex-fill"><label className="form-label small">From</label><input type="datetime-local" className="form-control" value={customSince} onChange={e=>setCustomSince(e.target.value)} /></div>
            <div className="flex-fill"><label className="form-label small">To</label><input type="datetime-local" className="form-control" value={customUntil} onChange={e=>setCustomUntil(e.target.value)} /></div>
          </div>}
          <button className="revoke-btn" onClick={()=>toggleGrant(false)}>Revoke permission</button></> : <button className="btn btn-primary w-100 mt-3" onClick={()=>toggleGrant(true)} disabled={!conversationId}><i className="bi bi-shield-check me-2"/>Grant Permission</button>}
        <small className="d-block text-muted mt-2">Nội dung tin nhắn trong phạm vi trên sẽ được gửi tới nhà cung cấp AI ngoài (Google Gemini, Groq, hoặc OpenAI, tuỳ cấu hình hệ thống) để xử lý.</small>
      </div>
      <div className="ai-section-title"><span>Quick actions</span><i className="bi bi-lightning-charge-fill"/></div>
      <div className="quick-grid">{actions.map(([icon,title,sub,color])=>{
        const hasHandler = Boolean(handlers[title])
        const isRunning = runningAction === title
        return <motion.button key={title} whileHover={{y:-2}} whileTap={{scale:.98}} disabled={hasHandler && (!granted || Boolean(runningAction) || isCustomRangeIncomplete)} onClick={hasHandler ? handlers[title] : undefined}><span style={{color,background:`${color}12`}}><i className={`bi ${isRunning ? 'bi-hourglass-split' : icon}`}/></span><strong>{title}</strong><small>{isRunning ? 'Working...' : sub}</small></motion.button>
      })}</div>
      {error && <div className="auth-error">{error}</div>}
      {isCustomRangeIncomplete && <small className="d-block text-muted mt-2">Nhập ít nhất một mốc "From"/"To" cho Custom time range trước khi dùng.</small>}
      {result && <div className="border rounded-3 p-3 mt-2 small"><strong className="d-block mb-1">{resultTitle}</strong>{result}{pending && <div className="d-flex gap-2 mt-2"><button className="btn btn-sm btn-primary" disabled={runningAction==='__resume__'} onClick={()=>respondToInterrupt(true)}>Xác nhận</button><button className="btn btn-sm btn-light" disabled={runningAction==='__resume__'} onClick={()=>respondToInterrupt(false)}>Huỷ</button></div>}</div>}
      <div className="ask-card"><div className="ask-title"><span><i className="bi bi-stars"/></span><div><strong>Ask Orbit</strong><small>About this conversation</small></div></div><textarea value={question} onChange={e=>setQuestion(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();askOrbit()}}} disabled={!granted} placeholder="Ask anything about this conversation..."/><div className="ask-footer"><span>AI may make mistakes</span><button disabled={!granted || asking || !question.trim() || isCustomRangeIncomplete} onClick={()=>askOrbit()}><i className={`bi ${asking?'bi-hourglass-split':'bi-arrow-up'}`}/></button></div></div>
      <div className="suggested-prompts"><span>Try asking</span><button disabled={!granted || asking || isCustomRangeIncomplete} onClick={()=>askOrbit('What decisions were made today?')}>“What decisions were made today?”</button><button disabled={!granted || asking || isCustomRangeIncomplete} onClick={()=>askOrbit('Who assigned me tasks?')}>“Who assigned me tasks?”</button></div>
    </aside></>
  )
}

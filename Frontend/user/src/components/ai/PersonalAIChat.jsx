import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { useAuth } from '../../context/AuthContext'
import { chatWithAgent, resumeAgent } from '../../api/agent'
import { getAssistantThreadMessages, getAssistantThreadPending } from '../../api/assistant'
import Markdown from '../common/Markdown'
import { queryClient, queryKeys } from '../../query/queryClient'

const prompts = [
  { icon:'bi-sun', label:'Lên kế hoạch hôm nay', prompt:'Tổng hợp lịch, task và deadline của tôi hôm nay' },
  { icon:'bi-calendar-check', label:'Lịch sắp tới', prompt:'Tuần này tôi có những cuộc họp quan trọng nào?' },
  { icon:'bi-exclamation-diamond', label:'Deadline gần nhất', prompt:'Deadline nào đang đến gần và cần ưu tiên?' },
  { icon:'bi-journal-bookmark', label:'Tìm trong memory', prompt:'Tóm tắt những gì bạn nhớ về cách tôi làm việc' },
]

const fallbackProcessSteps = [
  'Phân tích yêu cầu và xác định phạm vi xử lý',
  'Tổng hợp kết quả từ các nguồn được cấp quyền',
]

function PersonalProcessTrace({ steps, summary }) {
  const visibleSteps = Array.isArray(steps) && steps.length ? steps : fallbackProcessSteps
  const needsInput = summary?.includes('bổ sung dữ kiện')
  return <details className="personal-process-trace" defaultOpen={needsInput}>
    <summary title={summary || 'Xem tiến trình xử lý của Orbit'}>
      <span className="personal-process-title"><i className="bi bi-diagram-3"/><strong>Orbit đã xử lý qua {visibleSteps.length} bước</strong><em>{needsInput ? 'Cần bổ sung' : 'Hoàn tất'}</em></span>
      <span className="personal-process-action"><small>Xem tiến trình</small><i className="bi bi-chevron-down"/></span>
    </summary>
    <div className="personal-process-timeline">
      {summary && <p className="personal-process-summary">{summary}</p>}
      {visibleSteps.map((step, index) => <div className="personal-process-step" key={`${index}-${step}`}>
        <span><i className="bi bi-check-lg"/></span>
        <p>{step}</p>
      </div>)}
    </div>
  </details>
}

const workingPhases = [
  {
    icon: 'bi-search',
    title: 'Đang đọc yêu cầu',
    description: 'Orbit đang xác định mục tiêu và những dữ kiện cần thiết để xử lý chính xác.',
  },
  {
    icon: 'bi-diagram-3',
    title: 'Đang lập kế hoạch xử lý',
    description: 'Orbit đang chia yêu cầu thành các bước và chọn nguồn dữ liệu phù hợp.',
  },
  {
    icon: 'bi-database-check',
    title: 'Đang kiểm tra dữ liệu được cấp quyền',
    description: 'Orbit đang đối chiếu Chats, Tasks, Calendar và Memory trong phạm vi của bạn.',
  },
  {
    icon: 'bi-stars',
    title: 'Đang tổng hợp câu trả lời',
    description: 'Orbit đang kiểm tra kết quả và chuẩn bị phản hồi cuối cùng.',
  },
]

const formatWorkingTime = seconds => {
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  return `${minutes}m ${String(seconds % 60).padStart(2, '0')}s`
}

function PersonalThinkingState() {
  const startedAt = useRef(Date.now())
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    const updateElapsed = () => setElapsed(Math.floor((Date.now() - startedAt.current) / 1000))
    updateElapsed()
    const timer = window.setInterval(updateElapsed, 250)
    return () => window.clearInterval(timer)
  }, [])

  const phaseIndex = elapsed < 1 ? 0 : elapsed < 3 ? 1 : elapsed < 6 ? 2 : 3
  const phase = workingPhases[phaseIndex]

  return <div className="personal-message personal-thinking-message" role="status" aria-live="polite">
    <div className="message-ai-icon"><i className="bi bi-stars"/></div>
    <div className="personal-thinking-card">
      <header className="personal-working-header">
        <span className="personal-working-label"><i/>Working for {formatWorkingTime(elapsed)}</span>
        <span className="personal-thinking-dots" aria-hidden="true"><i/><i/><i/></span>
      </header>
      <div className="personal-working-progress"><span key={phaseIndex}/></div>
      <p className="personal-working-description">{phase.description}</p>
      <div className="personal-working-activity">
        <span><i className={`bi ${phase.icon}`}/></span>
        <strong>{phase.title}</strong>
      </div>
    </div>
  </div>
}

function describeInterrupt(interrupt) {
  const d = interrupt.draft
  if (interrupt.type === 'calendar_event') {
    if (d.conflicts?.length) {
      const clash = d.conflicts.map(c => c.title).join(', ')
      return `Khung giờ ${d.start} - ${d.end} bị trùng với "${clash}". Bạn có muốn tạo "${d.summary}" vào giờ đó, hay chọn giờ thay thế bên dưới?`
    }
    return `Bạn có muốn tạo sự kiện "${d.summary}" từ ${d.start} đến ${d.end}?`
  }
  if (interrupt.type === 'reminder') return `Bạn có muốn đặt nhắc nhở "${d.title}" lúc ${d.due_at}?`
  if (interrupt.type === 'reminder_update') return `Bạn có muốn cập nhật nhắc nhở ${d.reminder_id}?`
  if (interrupt.type === 'reminder_cancel') return `Bạn có muốn hủy nhắc nhở ${d.reminder_id}?`
  if (interrupt.type === 'reminder_snooze') return `Bạn có muốn hoãn nhắc nhở ${d.reminder_id} thêm ${d.minutes} phút?`
  return 'Bạn có muốn xác nhận hành động này?'
}

function CalendarInterruptActions({ interrupt, sending, onConfirm, onDecline }) {
  const draft = interrupt.draft || {}
  const [createReminder, setCreateReminder] = useState(draft.create_reminder !== false)
  const [leadMinutes, setLeadMinutes] = useState(draft.reminder_lead_minutes || 30)
  const reminderEdits = { create_reminder: createReminder, reminder_lead_minutes: Number(leadMinutes) }
  return <div className="calendar-confirmation-controls mt-3">
    <label className="form-check form-switch"><input className="form-check-input" type="checkbox" checked={createReminder} onChange={event=>setCreateReminder(event.target.checked)} disabled={sending}/><span className="form-check-label">Nhắc tôi trước sự kiện</span></label>
    {createReminder && <select className="form-select form-select-sm mb-2" value={leadMinutes} onChange={event=>setLeadMinutes(Number(event.target.value))} disabled={sending}><option value={15}>15 phút trước</option><option value={30}>30 phút trước</option><option value={60}>1 giờ trước</option><option value={1440}>1 ngày trước</option></select>}
    <div className="d-flex gap-2 flex-wrap">{draft.alternatives?.map((alt,i)=><button key={i} className="btn btn-sm btn-outline-primary" disabled={sending} onClick={()=>onConfirm({...reminderEdits,start:alt.start,end:alt.end})}>Dùng {alt.start} - {alt.end}</button>)}<button className="btn btn-sm btn-primary" disabled={sending} onClick={()=>onConfirm(reminderEdits)}>Xác nhận</button><button className="btn btn-sm btn-light" disabled={sending} onClick={onDecline}>Huỷ</button></div>
  </div>
}

// `threadId` is controlled from PersonalAssistantPage (not local state here) so the "Gần đây"
// sidebar and this chat panel stay in sync: selecting a past session sets it from outside, and this
// component reports back (onThreadIdChange) whenever the server mints a new one on the first
// message of a fresh session.
export default function PersonalAIChat({ onContext, contextCollapsed, threadId, onThreadIdChange, onActivity }) {
  const { token, user } = useAuth()
  const [draft,setDraft]=useState('')
  const [messages,setMessages]=useState([])
  // Which thread's history is currently reflected in `messages` - lets the load effect below tell
  // "just sent/received a turn in this same thread" (already up to date, no need to re-fetch) apart
  // from "the user picked a different thread from the sidebar" (needs a real fetch).
  const [loadedThreadId,setLoadedThreadId]=useState(null)
  const [pending,setPending]=useState(null)
  const [sending,setSending]=useState(false)
  const messagesRef=useRef(null)
  const composerRef=useRef(null)

  const pushMessage = (msg) => setMessages(prev => [...prev, { id: Date.now() + Math.random(), ...msg }])

  useEffect(() => {
    if (!threadId) { setMessages([]); setPending(null); setLoadedThreadId(null); return }
    if (threadId === loadedThreadId) return
    let cancelled = false
    Promise.all([
      queryClient.fetchQuery({
        queryKey: queryKeys.assistantMessages(threadId),
        queryFn: () => getAssistantThreadMessages(token, threadId),
        staleTime: 30_000,
      }),
      queryClient.fetchQuery({
        queryKey: queryKeys.assistantPending(threadId),
        queryFn: () => getAssistantThreadPending(token, threadId),
        staleTime: 0,
      }),
    ]).then(([history, pendingInterrupt]) => {
      if (cancelled) return
      const restored = history.map((m,i) => ({ id: `${threadId}-${i}`, own: m.role === 'user', text: m.content, analysis: m.analysis, analysisSteps: m.analysis_steps }))
      if (pendingInterrupt) restored.push({ id: `${threadId}-pending`, text: describeInterrupt(pendingInterrupt), interrupt: pendingInterrupt })
      setMessages(restored)
      setPending(pendingInterrupt ? { thread_id: threadId, interrupt: pendingInterrupt } : null)
      setLoadedThreadId(threadId)
    }).catch(error => {
      if (cancelled) return
      if (error?.status === 404) {
        // The saved thread may have been deleted in another tab/device. Drop the stale selection
        // instead of trapping the user on a conversation that can no longer be opened.
        onThreadIdChange?.(null)
        return
      }
      pushMessage({ text: 'Không tải được lịch sử cuộc trò chuyện.' })
    })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- loadedThreadId is the "already handled" guard, re-running on it would defeat that
  }, [threadId, token])

  const handleResult = (res) => {
    if (res.thread_id) queryClient.invalidateQueries({ queryKey: queryKeys.assistantMessages(res.thread_id) })
    if (res.thread_id) queryClient.invalidateQueries({ queryKey: queryKeys.assistantPending(res.thread_id) })
    queryClient.invalidateQueries({ queryKey: queryKeys.aiUsage(user?.id) })
    if (res.thread_id && res.thread_id !== threadId) onThreadIdChange?.(res.thread_id)
    setLoadedThreadId(res.thread_id)
    if (res.status === 'interrupted') {
      setPending({ thread_id: res.thread_id, interrupt: res.interrupt })
      pushMessage({ text: describeInterrupt(res.interrupt), interrupt: res.interrupt, analysis: res.analysis, analysisSteps: res.analysis_steps })
    } else {
      pushMessage({ text: res.response || (res.status === 'error' ? 'Đã có lỗi xảy ra, thử lại sau.' : 'Orbit không có câu trả lời cho yêu cầu này.'), analysis: res.analysis, analysisSteps: res.analysis_steps })
    }
    if (res.status !== 'error') onActivity?.()
  }

  const send = async (value=draft) => {
    if(!value.trim() || sending) return
    pushMessage({ own:true, text:value })
    setDraft('')
    setSending(true)
    try {
      const res = await chatWithAgent(token, { message: value, thread_id: threadId, context_limit: 20 })
      handleResult(res)
    } catch (err) {
      pushMessage({ text: err.detail || 'Không gọi được AI Assistant, thử lại sau.' })
    } finally { setSending(false) }
  }

  const respond = async (approved, edits) => {
    if (!pending || sending) return
    setSending(true)
    try {
      const res = await resumeAgent(token, { thread_id: pending.thread_id, approved, edits })
      setPending(null)
      handleResult(res)
    } catch (err) {
      pushMessage({ text: err.detail || 'Không gọi được AI Assistant, thử lại sau.' })
    } finally { setSending(false) }
  }

  useEffect(() => {
    const container = messagesRef.current
    if (!container) return
    const frame = requestAnimationFrame(() => container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' }))
    return () => cancelAnimationFrame(frame)
  }, [messages, sending, pending])

  const resizeComposer = event => {
    const field = event.currentTarget
    field.style.height = 'auto'
    field.style.height = `${Math.min(field.scrollHeight, 120)}px`
  }

  return <section className="personal-chat">
    <header className="personal-chat-header"><div className="personal-ai-avatar"><i className="bi bi-stars"/><span/></div><div><h3>Orbit Personal AI</h3><span><i/> Sẵn sàng hỗ trợ bạn</span></div><div className="personal-header-actions"><button className={`context-mobile-btn context-toggle-btn ${contextCollapsed ? 'show-desktop' : ''}`} onClick={onContext} aria-label="Mở bảng bối cảnh"><span><i className="bi bi-layout-sidebar-reverse"/></span>Bối cảnh</button><button className="icon-btn" aria-label="Cuộc trò chuyện mới" onClick={()=>onThreadIdChange?.(null)}><i className="bi bi-arrow-clockwise"/></button><button className="icon-btn"><i className="bi bi-three-dots"/></button></div></header>
    <div ref={messagesRef} className="personal-messages">
      {messages.length===0 && <div className="personal-welcome"><motion.div initial={{scale:.85,opacity:0}} animate={{scale:1,opacity:1}} className="welcome-ai-mark"><i className="bi bi-stars"/></motion.div><span className="welcome-kicker">Chào {user?.display_name || 'bạn'}</span><h1>Hôm nay mình có thể<br/><em>giúp gì cho bạn?</em></h1><p>Hỏi mình về lịch, công việc, deadline hoặc thông tin từ các cuộc trò chuyện đã được cấp quyền.</p><div className="prompt-grid">{prompts.map(p=><motion.button whileHover={{y:-3}} whileTap={{scale:.98}} key={p.label} onClick={()=>send(p.prompt)}><span><i className={`bi ${p.icon}`}/></span><strong>{p.label}</strong><small>{p.prompt}</small><i className="bi bi-arrow-up-right"/></motion.button>)}</div></div>}
      <AnimatePresence>{messages.map(m=><motion.div key={m.id} initial={{opacity:0,y:8}} animate={{opacity:1,y:0}} className={`personal-message ${m.own?'own':''}`}>
        {!m.own&&<div className="message-ai-icon"><i className="bi bi-stars"/></div>}<div><div className="personal-message-bubble">{m.own ? m.text : <Markdown>{m.text}</Markdown>}{m.interrupt && pending?.thread_id===threadId && (m.interrupt.type === 'calendar_event' ? <CalendarInterruptActions interrupt={m.interrupt} sending={sending} onConfirm={edits=>respond(true,edits)} onDecline={()=>respond(false)}/> : <div className="d-flex gap-2 mt-2 flex-wrap"><button className="btn btn-sm btn-primary" disabled={sending} onClick={()=>respond(true)}>Xác nhận</button><button className="btn btn-sm btn-light" disabled={sending} onClick={()=>respond(false)}>Huỷ</button></div>)}</div>{!m.own && <PersonalProcessTrace steps={m.analysisSteps} summary={m.analysis}/>}<time>Bây giờ</time></div>
      </motion.div>)}</AnimatePresence>
      {sending && <PersonalThinkingState/>}
    </div>
    <div className="personal-composer-wrap"><div className="active-sources"><span><i className="bi bi-database-check"/> Đang dùng 4 nguồn</span><button>Chats <i className="bi bi-check"/></button><button>Tasks <i className="bi bi-check"/></button><button>Calendar <i className="bi bi-check"/></button><button>Memory <i className="bi bi-check"/></button></div><form className="personal-composer" onSubmit={e=>{e.preventDefault();send();if(composerRef.current)composerRef.current.style.height='auto'}}><button type="button" className="icon-btn"><i className="bi bi-plus-lg"/></button><textarea ref={composerRef} rows="1" value={draft} onChange={e=>setDraft(e.target.value)} onInput={resizeComposer} placeholder="Hỏi Orbit về công việc và lịch trình của bạn..." onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send();if(composerRef.current)composerRef.current.style.height='auto'}}}/><button className="personal-send" aria-label="Gửi" disabled={sending} onClick={e=>{e.preventDefault();send();if(composerRef.current)composerRef.current.style.height='auto'}}><i className="bi bi-arrow-up"/></button></form><small>Orbit có thể mắc lỗi. Hãy kiểm tra lại thông tin quan trọng.</small></div>
  </section>
}

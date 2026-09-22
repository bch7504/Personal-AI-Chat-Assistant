import { useEffect, useMemo, useRef, useState } from 'react'
import {
  createQualityDefect,
  createQualityEvidence,
  createQualityPolicy,
  createQualityRequirement,
  createQualityTestCase,
  createQualityTestRun,
  getQualityBrief,
  getQualityCapabilities,
  getQualityControlPlane,
  listQualityReleaseCandidates,
  transitionQualityRecord,
  updateQualityReleaseCandidate,
} from '../api/agent'
import Markdown from '../components/common/Markdown'
import { useAuth } from '../context/AuthContext'
import { useWorkspace } from '../context/WorkspaceContext'
import { queryClient, queryKeys } from '../query/queryClient'

const tone = { READY: 'success', AT_RISK: 'warning', NOT_READY: 'danger' }
const suggestions = [
  'Đánh giá release hiện tại và nêu rõ các gate chưa đạt.',
  'Liệt kê defect nghiêm trọng và người đang phụ trách.',
  'Còn data gap hoặc test nào chưa hoàn tất trước khi phát hành?',
]

const welcome = {
  id: 'quality-welcome', role: 'assistant', createdAt: new Date().toISOString(),
  content: 'Xin chào. Tôi là **Quality Assurance Workspace Agent**. Kết luận readiness do rule engine quyết định; LLM chỉ giải thích từ dữ liệu và nguồn đã được cấp quyền.',
}

const formatTime = value => new Intl.DateTimeFormat('vi-VN', {
  hour: '2-digit', minute: '2-digit',
}).format(new Date(value))

function QualityResult({ result }) {
  const assessment = result?.payload?.assessment
  const brief = result?.payload?.brief
  if (!assessment || !brief) return null
  const evidence = result.payload.message_evidence || []
  const candidate = result.payload.release_candidate
  return (
    <div className="workspace-agent-result">
      <div className="workspace-agent-metrics">
        <span><strong>{assessment.test_progress?.total || 0}</strong><small>Test/check</small></span>
        <span><strong>{assessment.critical_defects?.length || 0}</strong><small>Critical defect</small></span>
        <span><strong>{assessment.blocked_tests?.length || 0}</strong><small>Failed/blocked</small></span>
        <span><strong>{brief.sources?.length || 0}</strong><small>Source</small></span>
      </div>
      <p><strong>Kết luận:</strong> <span className={`status-badge ${tone[brief.release_readiness] || 'secondary'}`}>{brief.release_readiness}</span></p>
      {assessment.reasons?.length > 0 && <p><strong>Lý do:</strong> {assessment.reasons.join(', ')}</p>}
      {candidate && <p><strong>Delivery handoff:</strong> {candidate.release_key} · build {candidate.build_number || 'N/A'} · {candidate.handoff_status}</p>}
      {evidence.length > 0 && <details><summary>Xem {evidence.length} bằng chứng từ QA group</summary><div className="agent-evidence-list">{evidence.slice(0, 8).map(item => <p key={item.message_id}>{item.excerpt}</p>)}</div></details>}
      {result.data_gaps?.length > 0 && <div className="agent-data-gap">Dữ liệu chưa đầy đủ: {result.data_gaps.join(', ')}</div>}
      <footer><i className="bi bi-shield-check" /> Readiness được tính theo release scope và policy hiện hành.</footer>
    </div>
  )
}

function QualityControlPanel({ token, workspaceId, agentId, releaseId, conversationId, permissions }) {
  const [plane, setPlane] = useState(null)
  const [candidates, setCandidates] = useState([])
  const [kind, setKind] = useState('evidence')
  const [form, setForm] = useState({})
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')

  const refresh = async (force = false) => {
    if (!workspaceId || !agentId || !releaseId) return
    const controlKey = queryKeys.qualityControlPlane(workspaceId, agentId, releaseId)
    const candidatesKey = queryKeys.qualityReleaseCandidates(workspaceId, agentId)
    if (force) await Promise.all([
      queryClient.invalidateQueries({ queryKey: controlKey }),
      queryClient.invalidateQueries({ queryKey: candidatesKey }),
    ])
    const [control, releases] = await Promise.all([
      queryClient.fetchQuery({
        queryKey: controlKey,
        queryFn: () => getQualityControlPlane(token, workspaceId, agentId, releaseId),
        staleTime: 30_000,
      }),
      queryClient.fetchQuery({
        queryKey: candidatesKey,
        queryFn: () => listQualityReleaseCandidates(token, workspaceId, agentId),
        staleTime: 30_000,
      }),
    ])
    setPlane(control)
    setCandidates(releases)
  }

  useEffect(() => {
    refresh().catch(error => setNotice(error.detail || 'Không thể tải Quality control plane.'))
  }, [agentId, releaseId, workspaceId]) // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async event => {
    event.preventDefault()
    setBusy(true)
    setNotice('')
    const scoped = { conversation_id: conversationId, release_id: releaseId }
    try {
      if (kind === 'requirement') await createQualityRequirement(token, workspaceId, agentId, {
        ...scoped, requirement_key: form.key, title: form.title, required: true,
      })
      if (kind === 'test_case') await createQualityTestCase(token, workspaceId, agentId, {
        ...scoped, test_case_key: form.key, title: form.title,
        requirement_id: form.requirementId || null, test_kind: form.testKind || 'functional', required: true,
      })
      if (kind === 'evidence') await createQualityEvidence(token, workspaceId, agentId, {
        ...scoped, artifact_type: 'report', uri: form.uri,
      })
      if (kind === 'test_run') await createQualityTestRun(token, workspaceId, agentId, {
        ...scoped, test_case_id: form.testCaseId, evidence_id: form.evidenceId || null,
        release_candidate_id: candidates.find(item => item.release_key === releaseId)?.id || null,
        build_number: form.buildNumber,
        environment: candidates.find(item => item.release_key === releaseId)?.environment || 'staging',
        status: form.runStatus || 'passed',
      })
      if (kind === 'defect') await createQualityDefect(token, workspaceId, agentId, {
        ...scoped, defect_key: form.key, title: form.title, severity: form.severity || 'medium',
      })
      if (kind === 'policy') await createQualityPolicy(token, workspaceId, agentId, {
        version: form.version, activate: true,
      })
      setForm({})
      setNotice('Đã ghi nhận và audit thành công.')
      await refresh(true)
    } catch (error) {
      setNotice(error.detail || 'Không thể cập nhật Quality control plane.')
    } finally {
      setBusy(false)
    }
  }

  const verifyEvidence = async record => {
    setBusy(true)
    try {
      await transitionQualityRecord(token, workspaceId, agentId, 'evidence', record.id, {
        status: 'verified', expected_row_version: record.row_version,
      })
      await refresh(true)
    } catch (error) {
      setNotice(error.detail || 'Evidence đã thay đổi; vui lòng tải lại.')
    } finally {
      setBusy(false)
    }
  }

  const decideRelease = async (candidate, status) => {
    setBusy(true)
    try {
      await updateQualityReleaseCandidate(token, workspaceId, agentId, candidate.id, {
        status, expected_row_version: candidate.row_version,
      })
      await refresh(true)
    } catch (error) {
      setNotice(error.detail || 'Quality gate từ chối thay đổi này.')
    } finally {
      setBusy(false)
    }
  }

  if (!releaseId) return null
  const candidate = candidates.find(item => item.release_key === releaseId)
  const canGovern = Boolean(permissions.can_manage_control_plane)
  const canOperate = Boolean(
    permissions.can_execute_tests || permissions.can_submit_evidence || permissions.can_report_defects
  )
  const formKinds = [
    ...(canGovern ? ['requirement', 'test_case'] : []),
    ...(permissions.can_submit_evidence ? ['evidence'] : []),
    ...(permissions.can_execute_tests ? ['test_run'] : []),
    ...(permissions.can_report_defects ? ['defect'] : []),
    ...(canGovern ? ['policy'] : []),
  ]
  return <details className="quality-control-panel">
    <summary><span><i className="bi bi-clipboard2-check" /> Quality control plane</span><span className={`status-badge ${tone[plane?.assessment?.release_readiness] || 'secondary'}`}>{plane?.assessment?.release_readiness || 'LOADING'}</span></summary>
    {plane && <div className="quality-control-summary">
      <span>Requirements <strong>{plane.requirements.length}</strong></span>
      <span>Test cases <strong>{plane.test_cases.length}</strong></span>
      <span>Runs <strong>{plane.test_runs.length}</strong></span>
      <span>Defects <strong>{plane.defects.length}</strong></span>
      <span>Evidence <strong>{plane.evidence.length}</strong></span>
      <span>Coverage <strong>{plane.traceability.coverage_percent}%</strong></span>
    </div>}
    {candidate && <div className="quality-release-actions"><strong>{candidate.release_key} · build {candidate.build_number} · {candidate.status}</strong>{permissions.can_decide_release && candidate.status === 'qa_requested' && <button disabled={busy} onClick={() => decideRelease(candidate, 'qa_in_progress')}>Start QA</button>}{permissions.can_decide_release && candidate.status === 'qa_in_progress' && <><button disabled={busy} onClick={() => decideRelease(candidate, 'approved')}>Approve</button><button disabled={busy} className="danger" onClick={() => decideRelease(candidate, 'rejected')}>Reject</button></>}</div>}
    {(canGovern || canOperate) && <form className="quality-control-form" onSubmit={submit}>
      <select value={formKinds.includes(kind) ? kind : (formKinds[0] || '')} onChange={event => { setKind(event.target.value); setForm({}) }}>{formKinds.map(value => <option value={value} key={value}>{({ requirement: 'Requirement', test_case: 'Test case', evidence: 'Evidence', test_run: 'Test run', defect: 'Defect', policy: 'Gate policy' })[value]}</option>)}</select>
      {['requirement', 'test_case', 'defect'].includes(kind) && <><input required placeholder="Key" value={form.key || ''} onChange={event => setForm({ ...form, key: event.target.value })} /><input required placeholder="Title" value={form.title || ''} onChange={event => setForm({ ...form, title: event.target.value })} /></>}
      {kind === 'test_case' && <><select value={form.requirementId || ''} onChange={event => setForm({ ...form, requirementId: event.target.value })}><option value="">No requirement link</option>{plane?.requirements.map(item => <option key={item.id} value={item.id}>{item.requirement_key}</option>)}</select><select value={form.testKind || 'functional'} onChange={event => setForm({ ...form, testKind: event.target.value })}>{['functional', 'regression', 'security', 'performance', 'compliance'].map(value => <option key={value}>{value}</option>)}</select></>}
      {kind === 'evidence' && <input required type="url" placeholder="Evidence URL" value={form.uri || ''} onChange={event => setForm({ ...form, uri: event.target.value })} />}
      {kind === 'test_run' && <><select required value={form.testCaseId || ''} onChange={event => setForm({ ...form, testCaseId: event.target.value })}><option value="">Select test case</option>{plane?.test_cases.map(item => <option key={item.id} value={item.id}>{item.test_case_key}</option>)}</select><select value={form.evidenceId || ''} onChange={event => setForm({ ...form, evidenceId: event.target.value })}><option value="">No evidence</option>{plane?.evidence.map(item => <option key={item.id} value={item.id}>{item.uri}</option>)}</select><input required placeholder="Build number" value={form.buildNumber || ''} onChange={event => setForm({ ...form, buildNumber: event.target.value })} /><select value={form.runStatus || 'passed'} onChange={event => setForm({ ...form, runStatus: event.target.value })}>{['queued', 'running', 'passed', 'failed', 'blocked'].map(value => <option key={value}>{value}</option>)}</select></>}
      {kind === 'defect' && <select value={form.severity || 'medium'} onChange={event => setForm({ ...form, severity: event.target.value })}>{['low', 'medium', 'high', 'critical'].map(value => <option key={value}>{value}</option>)}</select>}
      {kind === 'policy' && <input required placeholder="Policy version" value={form.version || ''} onChange={event => setForm({ ...form, version: event.target.value })} />}
      <button disabled={busy || (!conversationId && kind !== 'policy')} type="submit">Add</button>
    </form>}
    {permissions.can_verify_evidence && plane?.evidence.filter(item => item.verification_status === 'pending').map(item => <button className="quality-verify-button" key={item.id} disabled={busy} onClick={() => verifyEvidence(item)}>Verify {item.uri}</button>)}
    {notice && <p className="quality-control-notice">{notice}</p>}
  </details>
}

export default function QualityAgentPage({ assignedAgent }) {
  const { token, user } = useAuth()
  const { workspaces } = useWorkspace()
  const company = useMemo(
    () => workspaces.find(item => item.type === 'organization' && item.slug === 'company-root')
      || workspaces.find(item => item.type === 'organization'),
    [workspaces],
  )
  const [agents, setAgents] = useState(() => assignedAgent ? [assignedAgent] : [])
  const [agentId, setAgentId] = useState(() => assignedAgent?.id || '')
  const [capabilities, setCapabilities] = useState({
    groups: [], release_ids: [], current_user_business_role: null, view_scope: null,
    can_select_group: false, can_manage_control_plane: false, can_execute_tests: false,
    can_submit_evidence: false, can_report_defects: false, can_verify_evidence: false,
    can_decide_release: false, can_update_own_work_items: false, can_propose_actions: false,
  })
  const [releaseId, setReleaseId] = useState('')
  const [groupId, setGroupId] = useState('')
  const [question, setQuestion] = useState('')
  const [messages, setMessages] = useState([welcome])
  const [threadId, setThreadId] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const scrollRef = useRef(null)
  const storageKey = user?.id && agentId ? `orbit_quality_agent_chat:${user.id}:${agentId}` : null
  const threadStorageKey = storageKey ? `${storageKey}:thread` : null

  useEffect(() => {
    if (!mobileSidebarOpen) return undefined
    const closeOnEscape = event => {
      if (event.key === 'Escape') setMobileSidebarOpen(false)
    }
    document.addEventListener('keydown', closeOnEscape)
    return () => document.removeEventListener('keydown', closeOnEscape)
  }, [mobileSidebarOpen])

  useEffect(() => {
    const quality = assignedAgent?.agent_profile === 'quality_assurance' ? [assignedAgent] : []
    setAgents(quality)
    setAgentId(quality[0]?.id || '')
  }, [assignedAgent])

  useEffect(() => {
    if (!company?.id || !agentId) return
    queryClient.fetchQuery({
      queryKey: queryKeys.qualityCapabilities(company.id, agentId),
      queryFn: () => getQualityCapabilities(token, company.id, agentId),
      staleTime: 2 * 60_000,
    }).then(next => {
      setCapabilities(next)
      setReleaseId(previous => next.release_ids.includes(previous) ? previous : (next.release_ids[0] || ''))
      setGroupId('')
    }).catch(requestError => setError(requestError.detail || 'Không thể tải phạm vi Quality.'))
  }, [agentId, company?.id, token])

  useEffect(() => {
    if (!storageKey) return
    try {
      const saved = JSON.parse(sessionStorage.getItem(storageKey) || '[]')
      setMessages(Array.isArray(saved) && saved.length ? saved : [welcome])
      setThreadId(threadStorageKey ? sessionStorage.getItem(threadStorageKey) : null)
    } catch {
      setMessages([welcome])
      setThreadId(null)
    }
  }, [storageKey, threadStorageKey])

  useEffect(() => {
    if (!storageKey) return
    sessionStorage.setItem(storageKey, JSON.stringify(messages.slice(-30)))
    scrollRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, storageKey])

  const askAgent = async event => {
    event?.preventDefault()
    const content = question.trim()
    if (!content || !releaseId.trim() || loading) return
    setMessages(previous => [...previous, { id: `user-${Date.now()}`, role: 'user', content, createdAt: new Date().toISOString() }])
    setQuestion('')
    setLoading(true)
    setError('')
    try {
      const response = await getQualityBrief(token, company.id, agentId, {
        message: content,
        release_id: releaseId.trim(),
        selected_conversation_id: capabilities.can_select_group && groupId ? groupId : null,
        thread_id: threadId,
      })
      const nextThreadId = response.payload?.thread_id || null
      setThreadId(nextThreadId)
      if (threadStorageKey && nextThreadId) sessionStorage.setItem(threadStorageKey, nextThreadId)
      setMessages(previous => [...previous, {
        id: `assistant-${Date.now()}`, role: 'assistant',
        content: response.payload?.agent_response || response.payload?.brief?.headline || 'Đã hoàn tất đánh giá Quality.',
        createdAt: new Date().toISOString(), result: response,
      }])
    } catch (requestError) {
      const detail = requestError.detail || 'Quality Agent hiện không khả dụng.'
      setError(detail)
      setMessages(previous => [...previous, {
        id: `error-${Date.now()}`, role: 'assistant', content: detail,
        createdAt: new Date().toISOString(), error: true,
      }])
    } finally {
      setLoading(false)
    }
  }

  const clearConversation = () => {
    setMessages([welcome])
    setThreadId(null)
    setMobileSidebarOpen(false)
    if (storageKey) sessionStorage.setItem(storageKey, JSON.stringify([welcome]))
    if (threadStorageKey) sessionStorage.removeItem(threadStorageKey)
  }

  return (
    <div className="workspace-agent-page">
      <button
        type="button"
        className={`workspace-agent-sidebar-backdrop ${mobileSidebarOpen ? 'show' : ''}`}
        aria-label="Đóng thiết lập Quality Agent"
        tabIndex={mobileSidebarOpen ? 0 : -1}
        onClick={() => setMobileSidebarOpen(false)}
      />
      <aside className={`workspace-agent-sidebar ${mobileSidebarOpen ? 'mobile-open' : ''}`} id="quality-agent-sidebar" aria-label="Thiết lập Quality Agent">
        <div className="workspace-agent-identity"><span><i className="bi bi-shield-check" /></span><div><small>LangGraph · deterministic gate</small><strong>Quality Assurance</strong><p>Workspace Agent</p></div><button type="button" className="workspace-agent-sidebar-close" aria-label="Đóng thiết lập Quality Agent" onClick={() => setMobileSidebarOpen(false)}><i className="bi bi-x-lg" /></button></div>
        <section><label htmlFor="qa-workspace">Agent workspace</label><select id="qa-workspace" className="form-select" value={agentId} onChange={event => setAgentId(event.target.value)}>{agents.map(agent => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select></section>
        {capabilities.current_user_business_role && <section className="agent-access-card"><h2><i className="bi bi-shield-check" /> Phạm vi truy cập</h2><p><strong>{capabilities.current_user_business_role === 'lead' ? 'QA Lead' : 'QA Member'}</strong> · {company?.name || 'Workspace'}</p>{capabilities.current_user_business_role === 'lead' ? <small>Đọc toàn bộ QA workspace, quản trị quality gate, xác minh evidence và quyết định release.</small> : <small>Chỉ đọc công việc của bạn trong {capabilities.groups.length} group được tham gia; được chạy test, nộp evidence và báo defect trong phạm vi đó.</small>}</section>}
        <section><label htmlFor="qa-release">Release</label><input id="qa-release" className="form-control" list="qa-releases" value={releaseId} onChange={event => setReleaseId(event.target.value)} placeholder="Ví dụ: R1" /><datalist id="qa-releases">{capabilities.release_ids.map(id => <option value={id} key={id} />)}</datalist></section>
        {capabilities.can_select_group && <section><label htmlFor="qa-group">Phạm vi phân tích</label><select id="qa-group" className="form-select" value={groupId} onChange={event => setGroupId(event.target.value)}><option value="">Toàn bộ Quality workspace</option>{capabilities.groups.map(group => <option value={group.id} key={group.id}>{group.name}</option>)}</select></section>}
        <section className="agent-security-note"><i className="bi bi-lock" /><p><strong>Guardrail đang hoạt động</strong><small>Release-scoped, RBAC, source consent, audit trail và readiness không do LLM quyết định.</small></p></section>
      </aside>
      <main className="workspace-agent-chat">
        <header><div className="workspace-agent-heading"><button type="button" className="workspace-agent-mobile-sidebar-toggle" aria-label="Mở thiết lập Quality Agent" aria-controls="quality-agent-sidebar" aria-expanded={mobileSidebarOpen} onClick={() => setMobileSidebarOpen(true)}><i className="bi bi-sliders" /></button><div><h1>Quality Assurance Agent</h1><p><span /> Trực tuyến · Memory tách biệt theo workspace</p></div></div><button type="button" className="btn btn-light btn-sm" onClick={clearConversation}><i className="bi bi-plus-lg me-2" />Cuộc chat mới</button></header>
        <QualityControlPanel token={token} workspaceId={company?.id} agentId={agentId} releaseId={releaseId} conversationId={groupId || capabilities.groups[0]?.id || ''} permissions={capabilities} />
        <div className="workspace-agent-messages">
          {!agents.length && <div className="agent-unavailable"><i className="bi bi-shield-lock" /><h2>Chưa có quyền sử dụng Agent</h2><p>Tài khoản chưa được gán vào Quality Assurance workspace.</p></div>}
          {messages.map(message => <article className={`workspace-agent-message ${message.role} ${message.error ? 'error' : ''}`} key={message.id}><span className="agent-message-avatar">{message.role === 'assistant' ? <i className="bi bi-shield-check" /> : (user?.display_name || '?').trim()[0]}</span><div><header><strong>{message.role === 'assistant' ? 'Quality Agent' : 'Bạn'}</strong><time>{formatTime(message.createdAt)}</time></header><section>{message.role === 'assistant' ? <Markdown>{message.content}</Markdown> : <p>{message.content}</p>}</section><QualityResult result={message.result} /></div></article>)}
          {loading && <article className="workspace-agent-message assistant"><span className="agent-message-avatar"><i className="bi bi-shield-check" /></span><div><section className="agent-thinking"><i /><i /><i /><span>Đang chạy tool và quality gate…</span></section></div></article>}
          <div ref={scrollRef} />
        </div>
        {agents.length > 0 && <footer className="workspace-agent-composer">{!messages.some(message => message.role === 'user') && <div className="agent-prompt-suggestions">{suggestions.map(prompt => <button type="button" key={prompt} onClick={() => setQuestion(prompt)}>{prompt}</button>)}</div>}<form onSubmit={askAgent}><textarea rows="2" maxLength="2000" value={question} onChange={event => setQuestion(event.target.value)} placeholder="Hỏi về release, defect, test, gate hoặc dữ liệu còn thiếu…" /><button type="submit" disabled={loading || !releaseId.trim() || !question.trim()} aria-label="Gửi câu hỏi"><i className="bi bi-send-fill" /></button></form><small><i className="bi bi-info-circle" /> READY chỉ xuất hiện khi required checks đã pass và không có data gap.</small></footer>}
        {error && <div className="workspace-agent-error" role="alert">{error}</div>}
      </main>
    </div>
  )
}

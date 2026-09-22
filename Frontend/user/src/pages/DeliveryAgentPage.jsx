import { useEffect, useMemo, useRef, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import {
  createDeliveryDecision,
  createDeliveryCheckpoint,
  createDeliveryDependency,
  createDeliveryTask,
  createDeliveryReleaseCandidate,
  decideWorkspaceActionProposal,
  createWorkspaceActionProposal,
  deleteDeliveryThread,
  getDeliveryBrief,
  getDeliveryCapabilities,
  getDeliveryDashboard,
  getDeliveryReleaseTargets,
  getDeliveryThreadMessages,
  listDeliveryReleaseCandidates,
  listDeliveryCheckpoints,
  listDeliveryThreads,
  listDeliveryTaskReviews,
  reviewDeliveryCheckpointQuality,
  reviewDeliveryTask,
  listWorkspaceActionProposals,
  updateDeliveryReleaseCandidate,
} from '../api/agent'
import Markdown from '../components/common/Markdown'
import ConfirmDialog from '../components/common/ConfirmDialog'
import { useAuth } from '../context/AuthContext'
import { useWorkspace } from '../context/WorkspaceContext'
import { queryClient, queryKeys } from '../query/queryClient'
import { getAgentWorkspaceDisplayName } from '../utils/workspaceLabels'

const leadPrompts = [
  'Tổng hợp các task và đánh giá tiến độ theo checkpoint của kế hoạch.',
  'Tổng hợp tiến độ toàn bộ workspace và các blocker cần xử lý.',
  'Nhóm nào đang có nguy cơ trễ hạn và ai đang phụ trách?',
  'Các quyết định nào Lead cần chốt trong tuần này?',
]

const memberPrompts = [
  'Lịch công việc và các deadline của tôi trong checkpoint hiện tại là gì?',
  'Công việc của tôi hiện tại là gì?',
  'Tôi có nhiệm vụ nào sắp đến hạn hoặc đang bị blocker không?',
  'Tóm tắt những thông tin trong nhóm có liên quan trực tiếp đến tôi.',
]

const createWelcomeMessage = role => ({
  id: `welcome-${role || 'user'}`,
  role: 'assistant',
  createdAt: new Date().toISOString(),
  content: role === 'lead'
    ? 'Xin chào Lead. Tôi là **Product Delivery Workspace Agent**. Tôi có thể tổng hợp tiến độ của toàn workspace hoặc phân tích một nhóm cụ thể trong phạm vi bạn quản lý.'
    : 'Xin chào. Tôi là **Product Delivery Workspace Agent**. Tôi chỉ sử dụng dữ liệu nhóm bạn được tham gia và chỉ trả về công việc, mốc thời gian liên quan đến quyền của bạn.',
})

const formatMessageTime = value => new Intl.DateTimeFormat('vi-VN', {
  hour: '2-digit', minute: '2-digit',
}).format(new Date(value))

const historyGroupLabel = value => {
  const today = new Date()
  const date = new Date(value)
  const todayStart = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  const dateStart = new Date(date.getFullYear(), date.getMonth(), date.getDate())
  const daysAgo = Math.floor((todayStart - dateStart) / 86_400_000)
  if (daysAgo <= 0) return 'Hôm nay'
  if (daysAgo === 1) return 'Hôm qua'
  if (daysAgo <= 7) return '7 ngày trước'
  return '30 ngày trước'
}

const specialistLabels = {
  task_intelligence: 'Delivery Task Intelligence',
  // Historical runs are rendered as the unified task agent, not as a second specialist.
  work_intelligence: 'Delivery Task Intelligence',
  risk_dependency: 'Rủi ro & phụ thuộc',
  planning_forecast: 'Kế hoạch & dự báo',
  evidence_knowledge: 'Bằng chứng & quyết định',
  capacity_flow: 'Năng lực & luồng việc',
}

const progressLabels = {
  routing: 'Workspace Agent đang phân tích yêu cầu…',
  route_selected: 'Đã chọn luồng xử lý phù hợp',
  context_ready: 'Đã đọc dữ liệu được cấp quyền và đóng gói bằng chứng',
  specialist_dispatch_started: 'Workspace Agent đang điều phối các agent chuyên biệt',
  specialist_started: 'Một agent chuyên biệt đang xử lý',
  specialist_completed: 'Một agent đã hoàn thành và bàn giao kết quả',
  specialist_handoff: 'Đang bàn giao dữ liệu giữa các agent',
  specialist_failed: 'Một agent không hoàn thành',
  synthesis_started: 'Workspace Agent đang tổng hợp kết quả cuối',
  specialists_completed: 'Các agent chuyên biệt đã trả kết quả; đang tổng hợp',
  synthesis_completed: 'Workspace Agent đã hoàn tất câu trả lời',
  failed: 'Luồng agent gặp lỗi và đang chuyển sang kết quả an toàn',
}

const specialistActions = {
  task_intelligence: 'Tổng hợp task theo từng team, tính tiến độ và tìm các task cần chú ý.',
  risk_dependency: 'Nhận kết quả task, nối chuỗi phụ thuộc và giải thích rủi ro kinh doanh.',
  planning_forecast: 'Nhận đánh giá rủi ro, xếp thứ tự team và tạo agenda cùng quyết định cần chốt.',
  evidence_knowledge: 'Kiểm tra bằng chứng và các quyết định cần Lead xác nhận.',
  capacity_flow: 'Đánh giá tải công việc, năng lực và điểm nghẽn luồng xử lý.',
}

const artifactLabels = {
  'team_task_assessment.v1': 'Bảng đánh giá task theo team',
  'dependency_risk_analysis.v1': 'Bản đồ phụ thuộc và rủi ro',
  'meeting_plan.v1': 'Kế hoạch họp có bằng chứng',
}

function mergeDeliveryProgress(previous, event) {
  const next = { ...(previous || {}), ...event }
  let specialists = (event.specialists || previous?.specialists || []).map(item => (
    typeof item === 'string' ? { name: item, status: 'queued', tools: [], depends_on: [] } : { ...item }
  ))
  const completed = new Set([...(previous?.specialists_completed || []), ...(event.specialists_completed || [])])
  const failed = new Set([...(previous?.specialists_failed || []), ...(event.specialists_failed || [])])
  if (event.specialist) {
    specialists = specialists.map(item => item.name !== event.specialist ? item : {
      ...item,
      depends_on: event.depends_on || item.depends_on || [],
      tools: event.tools || item.tools || [],
      status: event.phase === 'specialist_started'
        ? 'running'
        : event.phase === 'specialist_completed'
          ? 'completed'
          : event.phase === 'specialist_failed' ? 'failed' : item.status,
      output_hash: event.output_hash || item.output_hash,
      artifact_type: event.artifact_type || item.artifact_type,
    })
    if (event.phase === 'specialist_completed') completed.add(event.specialist)
    if (event.phase === 'specialist_failed') failed.add(event.specialist)
  }
  if (event.phase === 'specialists_completed') {
    specialists = specialists.map(item => ({
      ...item,
      status: failed.has(item.name) ? 'failed' : completed.has(item.name) ? 'completed' : item.status,
    }))
  }
  const handoffs = [...(previous?.handoffs || [])]
  if (event.phase === 'specialist_handoff' && event.from_specialist && event.to_specialist) {
    handoffs.push({ from: event.from_specialist, to: event.to_specialist })
  }
  return {
    ...next,
    specialists,
    specialists_completed: [...completed],
    specialists_failed: [...failed],
    handoffs: handoffs.slice(-4),
  }
}

function LiveOrchestrationProgress({ progress }) {
  const specialists = (progress?.specialists || []).map(item => (
    typeof item === 'string' ? { name: item, status: 'planned', tools: [], depends_on: [] } : item
  ))
  const completed = new Set(progress?.specialists_completed || [])
  const failed = new Set(progress?.specialists_failed || [])
  const terminal = progress?.phase === 'synthesis_completed' || progress?.phase === 'failed'
  const specialistState = item => (
    failed.has(item.name) ? 'failed' : completed.has(item.name) ? 'completed' : item.status || 'planned'
  )
  const activeSpecialists = specialists.filter(item => specialistState(item) === 'running')
  const headline = progress?.phase === 'specialist_dispatch_started' && specialists.length
    ? `Workflow gồm ${specialists.length} agent, chạy theo thứ tự phụ thuộc`
    : progressLabels[progress?.phase] || progressLabels.routing
  return <section className="delivery-live-progress" aria-live="polite">
    <header>
      {terminal
        ? <i className={`bi ${progress?.phase === 'failed' ? 'bi-exclamation-triangle' : 'bi-check-circle'}`} />
        : <span className="spinner-border spinner-border-sm" />}
      <div><strong>{headline}</strong>
        {progress?.intent && <small>{progress.intent} · {progress.execution_mode || 'đang định tuyến'}</small>}
        {activeSpecialists.length > 0 && <em>
          Đang chạy: {activeSpecialists.map(item => specialistLabels[item.name] || item.name).join(', ')}
        </em>}
      </div>
    </header>
    {specialists.length > 0 && <div className="delivery-live-dag">
      {specialists.map((item, index) => {
        const state = specialistState(item)
        return <div key={item.name} className={state}>
          <span>{state === 'completed'
            ? <i className="bi bi-check-lg" />
            : state === 'running'
              ? <i className="spinner-border spinner-border-sm" />
              : state === 'failed'
                ? <i className="bi bi-exclamation-lg" />
                : index + 1}</span>
          <p><strong>{specialistLabels[item.name] || item.name}</strong>
            <small>{state === 'queued'
              ? `Đang chờ kết quả từ ${item.depends_on?.map(name => specialistLabels[name] || name).join(', ')}`
              : state === 'completed'
                ? `Đã hoàn thành ✓${item.artifact_type ? ` · ${artifactLabels[item.artifact_type] || item.artifact_type}` : ''}`
              : state === 'running'
                  ? 'Đang phân tích dữ liệu được giao…'
                  : state === 'failed'
                    ? 'Không hoàn thành'
                    : 'Đã đưa vào workflow'}</small>
            <em>{specialistActions[item.name] || 'Xử lý phần việc được Supervisor giao.'}</em>
          </p>
        </div>
      })}
    </div>}
    {progress?.handoffs?.length > 0 && <div className="delivery-agent-handoffs">
      {progress.handoffs.map((handoff, index) => <small key={`${handoff.from}-${handoff.to}-${index}`}>
        <i className="bi bi-arrow-right-circle" /> {specialistLabels[handoff.from] || handoff.from}
        {' bàn giao kết quả có kiểm chứng cho '}
        <strong>{specialistLabels[handoff.to] || handoff.to}</strong>
      </small>)}
    </div>}
    {specialists.length > 0 && <footer>
      Agent trong workflow: {specialists.map(item => specialistLabels[item.name] || item.name).join(' → ')}
    </footer>}
    {progress?.source_count != null && <footer>{progress.source_count} nguồn đã được kiểm tra theo quyền hiện tại</footer>}
  </section>
}

function OrchestrationSummary({ orchestration, results = [] }) {
  if (!orchestration) return null
  const requested = orchestration.specialists_requested || []
  const completed = new Set(orchestration.specialists_completed || [])
  const failed = new Set(orchestration.specialists_failed || [])
  const workspaceOnly = orchestration.execution_mode === 'workspace_only'
  const routingAttempts = orchestration.routing_llm_attempts || []
  const totalAttempts = orchestration.llm_attempts_total ?? (orchestration.llm_calls || 0)
  const totalSuccesses = orchestration.llm_successes_total ?? (orchestration.llm_calls || 0)
  const workflowLabel = workspaceOnly
    ? 'Workspace Agent'
    : orchestration.execution_mode === 'single_specialist'
      ? 'Workspace Agent → Specialist'
      : 'Workspace Agent → Multi-agent DAG'
  return <div className="delivery-orchestration" data-mode={orchestration.execution_mode}>
    <header>
      <span><i className="bi bi-diagram-3" /> {workflowLabel}</span>
      <small>{orchestration.workflow_status || 'completed'} · {orchestration.intent || 'task_lookup'}</small>
    </header>
    {requested.length > 0 && <div className="delivery-specialist-grid">
      {requested.map(specialist => {
        const specialistResult = results.find(item => item.specialist === specialist)
        const state = failed.has(specialist) ? 'failed' : completed.has(specialist) ? 'completed' : 'pending'
        return <span className={state} key={specialist} title={specialistResult?.summary || ''}>
          <i className={`bi ${state === 'failed' ? 'bi-exclamation-triangle' : state === 'completed' ? 'bi-check-circle' : 'bi-hourglass-split'}`} />
          <b>{specialistLabels[specialist] || specialist}</b>
          {specialistResult && <small>
            {specialistActions[specialist] || 'Xử lý phần việc được Supervisor giao.'}
            <br />Công cụ: {(specialistResult.tool_calls || []).map(item => item.tool_name).join(', ') || 'không gọi công cụ'}
            {specialistResult.artifact?.artifact_type
              ? <><br />Bàn giao: {artifactLabels[specialistResult.artifact.artifact_type] || specialistResult.artifact.artifact_type}</>
              : null}
            {(specialistResult.upstream_result_hashes || []).length > 0
              ? ` · nhận ${specialistResult.upstream_result_hashes.length} gói kết quả từ agent trước`
              : ''}
          </small>}
        </span>
      })}
    </div>}
    <footer>
      {workspaceOnly
        ? `${totalSuccesses}/${totalAttempts} lượt LLM thành công · không gọi specialist · không đọc dữ liệu nghiệp vụ`
        : `${orchestration.llm_calls || 0} lượt gọi LLM`}
      {workspaceOnly && orchestration.synthesis_model ? ` · model ${orchestration.synthesis_model}` : ''}
      {orchestration.synthesis_fallback ? ` · fallback ${orchestration.fallback_reason || 'LLM_UNAVAILABLE'}` : ''}
      {!workspaceOnly && orchestration.specialist_model ? ` · specialist ${orchestration.specialist_model}` : ''}
      {' · '}plan {orchestration.plan_version || 'delivery-adaptive-routing-v2'}
    </footer>
    {routingAttempts.length > 0 && <footer>
      Semantic router: {routingAttempts.map(attempt => (
        `${attempt.provider}/${attempt.model} ${attempt.status === 'succeeded' ? `thành công (${attempt.duration_ms} ms)` : `lỗi ${attempt.error_code}`}`
      )).join(' → ')}
    </footer>}
    {!workspaceOnly && Object.keys(orchestration.specialist_model_attempts || {}).length > 0 && <footer>
      Specialist LLM: {Object.entries(orchestration.specialist_model_attempts).map(([specialist, attempts]) => (
        `${specialistLabels[specialist] || specialist} [${attempts.map(attempt => (
          `${attempt.provider}/${attempt.model}: ${attempt.status === 'succeeded' ? 'thành công' : attempt.error_code}`
        )).join(' → ')}]`
      )).join(' · ')}
    </footer>}
    {!workspaceOnly && requested.length > 1 && <footer>
      Giao tiếp có kiểm soát: {requested.map(item => specialistLabels[item] || item).join(' → ')}.
      Agent sau chỉ nhận gói kết quả có hash từ agent trước, không tự mở rộng dữ liệu ngoài phạm vi.
    </footer>}
  </div>
}

function AgentRunHistory({ result, runHistory }) {
  const [expanded, setExpanded] = useState(false)
  const orchestration = result?.payload?.orchestration
  const specialistResults = result?.payload?.specialist_results || []
  let history = runHistory
  if (!history && orchestration) {
    const completed = new Set(orchestration.specialists_completed || [])
    const failed = new Set(orchestration.specialists_failed || [])
    const requested = orchestration.specialists_requested || []
    const routingAttempts = orchestration.routing_llm_attempts || []
    const routingSucceeded = routingAttempts.some(attempt => attempt.status === 'succeeded')
    const routingFailed = routingAttempts.length > 0 && !routingSucceeded
    const routingDetail = routingAttempts.length
      ? routingAttempts.map(attempt => (
        `${attempt.provider}/${attempt.model}: ${attempt.status === 'succeeded' ? `thành công trong ${attempt.duration_ms} ms` : attempt.error_code || 'lỗi provider'}`
      )).join(' → ')
      : `Định tuyến deterministic: ${orchestration.execution_mode} cho ${orchestration.intent}; không cần gọi routing LLM.`
    const steps = [{
      kind: 'routing',
      status: routingFailed ? 'partial' : 'succeeded',
      title: 'Phân tích yêu cầu và lập workflow',
      detail: routingDetail,
      error_code: routingFailed ? routingAttempts.at(-1)?.error_code : '',
    }]
    requested.forEach((specialist, specialistIndex) => {
      const specialistResult = specialistResults.find(item => item.specialist === specialist)
      const upstreamCount = specialistResult?.upstream_result_hashes?.length || 0
      steps.push({
        kind: 'specialist',
        specialist,
        status: failed.has(specialist) ? 'failed' : completed.has(specialist) ? 'succeeded' : 'pending',
        title: specialist,
        detail: specialistActions[specialist],
        depends_on: upstreamCount
          ? requested.slice(0, specialistIndex).slice(-upstreamCount)
          : [],
        tools: (specialistResult?.tool_calls || []).map(item => item.tool_name),
        error_code: specialistResult?.data_gaps?.[0],
      })
    })
    steps.push({
      kind: 'synthesis',
      status: orchestration.synthesis_fallback ? 'partial' : 'succeeded',
      title: 'Workspace Agent tổng hợp kết quả',
      detail: requested.length
        ? `Nhận kết quả từ ${requested.length} agent chuyên biệt.`
        : (orchestration.conversation_llm_attempts > 0
          ? `Workspace conversation LLM: ${orchestration.conversation_llm_successes || 0}/${orchestration.conversation_llm_attempts} lượt thành công.`
          : 'Phản hồi theo policy deterministic; không gọi conversation LLM.'),
      error_code: orchestration.fallback_reason,
    })
    history = {
      status: orchestration.workflow_status || 'completed',
      intent: orchestration.intent,
      execution_mode: orchestration.execution_mode,
      steps,
    }
  }
  const terminalState = status => (
    ['succeeded', 'success', 'completed'].includes(status)
      ? 'completed'
      : status === 'partial'
        ? 'partial'
        : ['failed', 'timed_out', 'cancelled'].includes(status) ? 'failed' : 'pending'
  )
  const steps = history?.steps || []
  const completedCount = steps.filter(step => ['completed', 'partial'].includes(terminalState(step.status))).length
  const failedCount = steps.filter(step => terminalState(step.status) === 'failed').length
  const partialCount = steps.filter(step => terminalState(step.status) === 'partial').length
  const pendingCount = steps.filter(step => terminalState(step.status) === 'pending').length
  const runState = failedCount > 0 ? 'failed' : partialCount > 0 ? 'attention' : pendingCount > 0 ? 'running' : 'completed'

  useEffect(() => {
    setExpanded(runState !== 'completed')
  }, [history?.status, steps.length, completedCount, failedCount, partialCount, pendingCount])

  if (!steps.length) return null
  const stateLabel = runState === 'failed' ? 'Có lỗi' : runState === 'attention' ? 'Cần chú ý' : runState === 'running' ? 'Đang chạy' : 'Hoàn tất'
  return <details className={`agent-run-history ${runState}`} open={expanded} onToggle={event=>setExpanded(event.currentTarget.open)}>
    <summary title={expanded ? 'Thu gọn quá trình thực hiện' : 'Xem chi tiết quá trình thực hiện'}>
      <span className="agent-run-history-title"><i className="bi bi-terminal" /><span>Quá trình Agent thực hiện</span><em>{stateLabel}</em></span>
      <span className="agent-run-history-meta"><small>{completedCount}/{steps.length} bước · {history.intent}</small><i className="bi bi-chevron-down" /></span>
    </summary>
    <div className="agent-run-timeline">
      {steps.map((step, index) => {
        const state = terminalState(step.status)
        const label = step.kind === 'specialist'
          ? specialistLabels[step.specialist] || step.title
          : step.title
        const action = step.detail || (step.specialist ? specialistActions[step.specialist] : '')
        return <div className={`agent-run-step ${state}`} key={`${step.kind}-${step.specialist || index}`}>
          <span className="agent-run-step-state">
            <i className={`bi ${state === 'failed' ? 'bi-x-lg' : state === 'pending' ? 'bi-three-dots' : 'bi-check-lg'}`} />
          </span>
          <div className="agent-run-step-content">
            <strong>{label}</strong>
            {action && <p>{action}</p>}
            {step.depends_on?.length > 0 && <small>
              <i className="bi bi-arrow-down-right" /> Nhận bàn giao từ {step.depends_on.map(item => specialistLabels[item] || item).join(', ')}
            </small>}
            {step.tools?.length > 0 && <small><i className="bi bi-tools" /> Công cụ: {step.tools.join(', ')}</small>}
            {step.model_name && <small><i className="bi bi-cpu" /> LLM: {step.model_name}</small>}
            {step.error_code && <small className="error"><i className="bi bi-exclamation-triangle" /> {step.error_code}</small>}
          </div>
        </div>
      })}
    </div>
  </details>
}

function ResultSummary({ result }) {
  const brief = result?.payload?.brief
  const orchestration = result?.payload?.orchestration
  const specialistResults = result?.payload?.specialist_results || []
  if (!brief) {
    if (!orchestration || orchestration.execution_mode === 'workspace_only') return null
    return <details className="workspace-agent-result workspace-agent-execution-only">
      <summary className="workspace-agent-result-summary">
        <span><i className="bi bi-diagram-3" /> Chi tiết điều phối agent</span>
        <small>{orchestration.specialists_completed?.length || 0} agent đã hoàn thành</small>
      </summary>
      <div className="workspace-agent-result-body">
        <OrchestrationSummary orchestration={orchestration} results={specialistResults} />
      </div>
    </details>
  }
  const evidence = result.payload.message_evidence || []
  const groups = result.payload.groups || []
  const health = result.payload.portfolio_health || brief.portfolio_health
  const risks = result.payload.risks || brief.risks || []
  const dependencies = result.payload.dependencies || brief.dependencies || []
  const decisions = result.payload.decisions || brief.decisions_needed || []
  const releases = result.payload.releases || brief.releases || []
  const checkpoints = result.payload.checkpoint_progress || []
  const dataGaps = result.data_gaps || brief.data_gaps || []
  const metrics = [
    ['Nhóm trong phạm vi', groups.length, 'bi-people'],
    ['Risks', risks.length, 'bi-exclamation-octagon'],
    ['Quá hạn', brief.overdue_items?.length || 0, 'bi-clock-history'],
    ['Pending decisions', decisions.filter(item => item.status === 'pending').length, 'bi-signpost-split'],
  ]
  return (
    <details className="workspace-agent-result">
      <summary className="workspace-agent-result-summary">
        <span><i className="bi bi-bar-chart-line" /> Chi tiết điều phối và dữ liệu</span>
        <small>{groups.length} nhóm · {checkpoints.length} checkpoint · {risks.length} rủi ro</small>
      </summary>
      <div className="workspace-agent-result-body">
        <OrchestrationSummary orchestration={orchestration} results={specialistResults} />
      {health?.health && (
        <div className={`agent-data-gap delivery-health-${health.health.toLowerCase()}`}>
          <i className="bi bi-activity" /> Portfolio health: <strong>{health.health}</strong>
          {health.reasons?.length > 0 && <span> Â· {health.reasons.join(', ')}</span>}
        </div>
      )}
      <div className="workspace-agent-metrics">
        {metrics.map(([label, value, icon]) => <span key={label}><i className={`bi ${icon}`} /><strong>{value}</strong><small>{label}</small></span>)}
      </div>
      {checkpoints.length > 0 && <details open>
        <summary><i className="bi bi-check2-square" /> Tiến độ checkpoint ({checkpoints.length})</summary>
        <div className="agent-evidence-list">
          {checkpoints.map(item => <p key={item.checkpoint_id}>
            <strong>{item.title}</strong> · {item.completion_percent}% · {item.schedule_status}
            {' · '}Chất lượng: {item.quality_review_status === 'pending' ? 'chờ Lead đánh giá' : item.quality_review_status}
          </p>)}
        </div>
      </details>}
      {(risks.length > 0 || dependencies.length > 0 || decisions.length > 0 || releases.length > 0) && (
        <details>
          <summary><i className="bi bi-diagram-3" /> Delivery control plane</summary>
          <div className="agent-evidence-list">
            {risks.map(item => <p key={`risk-${item.id}`}><strong>[{item.severity}]</strong> {item.title}</p>)}
            {dependencies.map(item => <p key={`dependency-${item.id}`}><strong>Dependency Â· {item.status}</strong> {item.title}</p>)}
            {decisions.map(item => <p key={`decision-${item.id}`}><strong>Decision Â· {item.status}</strong> {item.title}</p>)}
            {releases.map(item => <p key={`release-${item.id}`}><strong>Release Â· {item.status}</strong> {item.release_key} {item.version}</p>)}
          </div>
        </details>
      )}
      {evidence.length > 0 && (
        <details>
          <summary><i className="bi bi-chat-quote" /> Xem {evidence.length} bằng chứng từ group chat</summary>
          <div className="agent-evidence-list">
            {evidence.slice(0, 8).map(item => <p key={item.message_id}>{item.excerpt}</p>)}
          </div>
        </details>
      )}
      {dataGaps.length > 0 && <div className="agent-data-gap"><i className="bi bi-info-circle" /> Dữ liệu chưa đầy đủ: {dataGaps.join(', ')}</div>}
        <footer><i className="bi bi-shield-check" /> Kết quả được giới hạn theo quyền tại thời điểm truy vấn · {result.payload.freshness || 'fresh'}</footer>
      </div>
    </details>
  )
}

function DeliveryLeadControls({ token, workspaceId, agentId, conversationId, qualityWorkspaces }) {
  const [kind, setKind] = useState('task')
  const [form, setForm] = useState({})
  const [releases, setReleases] = useState([])
  const [checkpoints, setCheckpoints] = useState([])
  const [taskReviews, setTaskReviews] = useState([])
  const [dashboard, setDashboard] = useState(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')

  const refresh = async (force = false) => {
    if (!workspaceId || !agentId) return
    const queryKey = queryKeys.deliveryReleaseCandidates(workspaceId, agentId)
    if (force) await queryClient.invalidateQueries({ queryKey })
    const [releaseRows, checkpointRows, reviewRows, dashboardRow] = await Promise.all([queryClient.fetchQuery({
      queryKey,
      queryFn: () => listDeliveryReleaseCandidates(token, workspaceId, agentId),
      staleTime: 30_000,
    }), listDeliveryCheckpoints(token, workspaceId, agentId), listDeliveryTaskReviews(token, workspaceId, agentId), getDeliveryDashboard(token, workspaceId, agentId)])
    setReleases(releaseRows)
    setCheckpoints(checkpointRows || [])
    setTaskReviews(reviewRows || [])
    setDashboard(dashboardRow)
  }

  useEffect(() => {
    refresh().catch(error => setNotice(error.detail || 'Không thể tải release handoff.'))
  }, [agentId, workspaceId, conversationId]) // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async event => {
    event.preventDefault()
    setBusy(true)
    setNotice('')
    try {
      if (kind === 'dependency') await createDeliveryDependency(token, workspaceId, agentId, {
        source_conversation_id: conversationId, title: form.title,
      })
      if (kind === 'task') await createDeliveryTask(token, workspaceId, agentId, {
        source_conversation_id: conversationId,
        owner_id: form.ownerId,
        title: form.title,
        due_at: form.dueAt ? new Date(form.dueAt).toISOString() : null,
        priority: form.priority || 'Medium',
        requires_review: Boolean(form.requiresReview),
      })
      if (kind === 'decision') await createDeliveryDecision(token, workspaceId, agentId, {
        source_conversation_id: conversationId, title: form.title,
        options: (form.options || '').split(',').map(value => value.trim()).filter(Boolean),
      })
      if (kind === 'release') await createDeliveryReleaseCandidate(token, workspaceId, agentId, {
        quality_agent_workspace_id: form.qualityWorkspaceId,
        source_conversation_id: conversationId,
        release_key: form.releaseKey,
        version: form.version || '',
        build_number: form.buildNumber || '',
        environment: form.environment || 'staging',
        submit_to_qa: true,
      })
      if (kind === 'checkpoint') await createDeliveryCheckpoint(token, workspaceId, agentId, {
        source_conversation_id: conversationId,
        plan_key: form.planKey || 'default',
        title: form.title,
        due_at: new Date(form.dueAt).toISOString(),
        required_task_ids: (form.taskIds || '').split(',').map(value => value.trim()).filter(Boolean),
      })
      if (kind === 'groupUpdate') await createWorkspaceActionProposal(token, workspaceId, agentId, {
        action: 'delivery_group_update',
        payload: { conversation_id: conversationId, content: form.content },
        idempotency_key: crypto.randomUUID(),
      })
      if (kind === 'groupSchedule') await createWorkspaceActionProposal(token, workspaceId, agentId, {
        action: 'delivery_group_reminder_schedule',
        payload: {
          conversation_id: conversationId,
          title: form.title,
          content: form.content,
          scheduled_for: new Date(form.scheduledFor).toISOString(),
        },
        idempotency_key: crypto.randomUUID(),
      })
      setForm({})
      setNotice('Đã ghi nhận vào Delivery control plane.')
      await refresh(true)
    } catch (error) {
      setNotice(error.detail || 'Không thể cập nhật Delivery control plane.')
    } finally {
      setBusy(false)
    }
  }

  const transitionRelease = async (release, status) => {
    setBusy(true)
    try {
      await updateDeliveryReleaseCandidate(token, workspaceId, agentId, release.id, {
        status, expected_row_version: release.row_version,
      })
      await refresh(true)
    } catch (error) {
      setNotice(error.detail || 'Release đã thay đổi; vui lòng tải lại.')
    } finally {
      setBusy(false)
    }
  }

  const reviewCheckpoint = async (checkpoint, qualityReviewStatus) => {
    setBusy(true)
    setNotice('')
    try {
      await reviewDeliveryCheckpointQuality(token, workspaceId, agentId, checkpoint.checkpoint_id, {
        quality_review_status: qualityReviewStatus,
        quality_review_note: qualityReviewStatus === 'accepted'
          ? 'Lead xác nhận chất lượng đạt.'
          : 'Lead yêu cầu chỉnh sửa chất lượng.',
        expected_row_version: checkpoint.row_version,
      })
      await refresh(true)
    } catch (error) {
      setNotice(error.detail || 'Checkpoint đã thay đổi; vui lòng tải lại.')
    } finally {
      setBusy(false)
    }
  }

  const reviewTask = async (task, decision) => {
    const reviewNote = window.prompt(
      decision === 'accepted' ? 'Ghi chú nghiệm thu (không bắt buộc):' : 'Nêu rõ nội dung cần chỉnh sửa:',
      decision === 'accepted' ? 'Evidence đã được xác minh.' : '',
    )
    if (reviewNote === null || (decision === 'changes_requested' && !reviewNote.trim())) return
    setBusy(true); setNotice('')
    try {
      await reviewDeliveryTask(token, workspaceId, agentId, task.id, {
        decision,
        review_note: reviewNote.trim() || null,
        expected_row_version: task.row_version,
      })
      setNotice(decision === 'accepted' ? 'Task đã được nghiệm thu và hoàn thành.' : 'Đã trả task về cho thành viên chỉnh sửa.')
      await refresh(true)
    } catch (error) {
      setNotice(error.detail || 'Task đã thay đổi; vui lòng tải lại hàng đợi review.')
    } finally { setBusy(false) }
  }

  const ownerOptions = (dashboard?.members || []).filter(member =>
    (member.groups || []).some(group => group.id === conversationId),
  )

  return <details className="quality-control-panel delivery-control-panel">
    <summary><span><i className="bi bi-kanban" /> Delivery control plane</span><span className="status-badge secondary">{releases.length} releases</span></summary>
    <form className="quality-control-form" onSubmit={submit}>
      <select value={kind} onChange={event => { setKind(event.target.value); setForm({}) }}><option value="task">Giao task</option><option value="dependency">Dependency</option><option value="decision">Decision</option><option value="release">QA handoff</option><option value="checkpoint">Plan checkpoint</option><option value="groupUpdate">Gửi cập nhật nhóm</option><option value="groupSchedule">Đặt lịch nhắc nhóm</option></select>
      {!['release', 'groupUpdate'].includes(kind) && <input required placeholder="Title" value={form.title || ''} onChange={event => setForm({ ...form, title: event.target.value })} />}
      {kind === 'decision' && <input placeholder="Options, comma separated" value={form.options || ''} onChange={event => setForm({ ...form, options: event.target.value })} />}
      {kind === 'task' && <><select required value={form.ownerId || ''} onChange={event => setForm({ ...form, ownerId: event.target.value })}><option value="">Chọn người phụ trách</option>{ownerOptions.map(item => <option key={item.user_id} value={item.user_id}>{item.display_name} · {item.job_title || 'Member'}</option>)}</select><select value={form.priority || 'Medium'} onChange={event => setForm({ ...form, priority: event.target.value })}><option>High</option><option>Medium</option><option>Low</option></select><input type="datetime-local" value={form.dueAt || ''} onChange={event => setForm({ ...form, dueAt: event.target.value })} /><label className="d-flex gap-2 align-items-center"><input type="checkbox" checked={Boolean(form.requiresReview)} onChange={event => setForm({ ...form, requiresReview: event.target.checked })} /> Bắt buộc nộp evidence và Lead nghiệm thu</label></>}
      {kind === 'release' && <><select required value={form.qualityWorkspaceId || ''} onChange={event => setForm({ ...form, qualityWorkspaceId: event.target.value })}><option value="">Select QA workspace</option>{qualityWorkspaces.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select><input required placeholder="Release key" value={form.releaseKey || ''} onChange={event => setForm({ ...form, releaseKey: event.target.value })} /><input required placeholder="Build number" value={form.buildNumber || ''} onChange={event => setForm({ ...form, buildNumber: event.target.value })} /></>}
      {kind === 'checkpoint' && <><input required placeholder="Plan key, ví dụ Sprint-12" value={form.planKey || ''} onChange={event => setForm({ ...form, planKey: event.target.value })} /><input required type="datetime-local" value={form.dueAt || ''} onChange={event => setForm({ ...form, dueAt: event.target.value })} /><input required placeholder="Task IDs, phân tách bằng dấu phẩy" value={form.taskIds || ''} onChange={event => setForm({ ...form, taskIds: event.target.value })} /></>}
      {['groupUpdate', 'groupSchedule'].includes(kind) && <textarea required placeholder="Nội dung gửi cho nhóm" value={form.content || ''} onChange={event => setForm({ ...form, content: event.target.value })} />}
      {kind === 'groupSchedule' && <input required type="datetime-local" value={form.scheduledFor || ''} onChange={event => setForm({ ...form, scheduledFor: event.target.value })} />}
      <button disabled={busy || !conversationId} type="submit">Add</button>
    </form>
    {releases.length > 0 && <div className="delivery-release-list">{releases.map(release => <div key={release.id}><span><strong>{release.release_key}</strong> · build {release.build_number} · {release.status}</span>{release.status === 'rejected' && <button disabled={busy} onClick={() => transitionRelease(release, 'qa_requested')}>Resubmit</button>}{release.status === 'approved' && <button disabled={busy} onClick={() => transitionRelease(release, 'released')}>Mark released</button>}{['draft', 'qa_requested', 'rejected', 'approved'].includes(release.status) && <button className="danger" disabled={busy} onClick={() => transitionRelease(release, 'cancelled')}>Cancel</button>}</div>)}</div>}
    {checkpoints.length > 0 && <div className="delivery-release-list">{checkpoints.map(checkpoint => <div key={checkpoint.checkpoint_id}>
      <span><strong>{checkpoint.title}</strong> · {checkpoint.completion_percent}% · {checkpoint.schedule_status} · quality {checkpoint.quality_review_status}</span>
      <button disabled={busy} onClick={() => reviewCheckpoint(checkpoint, 'accepted')}>Lead: đạt</button>
      <button className="danger" disabled={busy} onClick={() => reviewCheckpoint(checkpoint, 'rejected')}>Lead: chưa đạt</button>
    </div>)}</div>}
    <div className="delivery-review-queue">
      <h4><i className="bi bi-inbox-check" /> Task chờ Lead nghiệm thu <span className="status-badge secondary">{taskReviews.length}</span></h4>
      {taskReviews.length === 0 ? <p className="text-muted">Không có submission nào đang chờ review.</p> : taskReviews.map(task => <article key={task.id} className="delivery-review-card">
        <div><strong>{task.title}</strong><small>{task.owner_name} · {task.conversation_name} · {task.priority}</small>{task.submission_note && <p>{task.submission_note}</p>}{task.evidence_urls.map(url => <a key={url} href={url} target="_blank" rel="noreferrer">{url}</a>)}</div>
        <span><button disabled={busy} onClick={() => reviewTask(task, 'accepted')}>Accept</button><button className="danger" disabled={busy} onClick={() => reviewTask(task, 'changes_requested')}>Request changes</button></span>
      </article>)}
    </div>
    {notice && <p className="quality-control-notice">{notice}</p>}
  </details>
}

function DeliveryApprovalQueue({ token, workspaceId, agentId }) {
  const [proposals, setProposals] = useState([])
  const [busyId, setBusyId] = useState(null)
  const [notice, setNotice] = useState('')

  const refresh = async () => {
    if (!workspaceId || !agentId) return
    const rows = await listWorkspaceActionProposals(token, workspaceId, agentId)
    setProposals((rows || []).filter(item => item.status === 'pending'))
  }

  useEffect(() => {
    refresh().catch(error => setNotice(error.detail || 'Không thể tải hàng đợi phê duyệt.'))
  }, [workspaceId, agentId]) // eslint-disable-line react-hooks/exhaustive-deps

  const decide = async (proposal, decision) => {
    setBusyId(proposal.id)
    setNotice('')
    try {
      await decideWorkspaceActionProposal(token, workspaceId, agentId, proposal.id, {
        decision,
        expected_row_version: proposal.row_version,
      })
      await refresh()
    } catch (error) {
      setNotice(error.detail || 'Proposal đã thay đổi; vui lòng tải lại.')
    } finally {
      setBusyId(null)
    }
  }

  return <details className="delivery-approval-queue">
    <summary>
      <span><i className="bi bi-person-check" /> Human approval queue</span>
      <span className="status-badge secondary">{proposals.length} pending</span>
    </summary>
    {proposals.length === 0
      ? <p>Không có hành động nào đang chờ Lead phê duyệt.</p>
      : <div className="delivery-proposal-list">{proposals.map(proposal => <article key={proposal.id}>
        <div>
          <strong>{proposal.action.replaceAll('_', ' ')}</strong>
          <small>Người đề xuất: {proposal.actor_user_id} · hết hạn {new Date(proposal.expires_at).toLocaleString('vi-VN')}</small>
          <code>{JSON.stringify(proposal.payload)}</code>
        </div>
        <span>
          <button disabled={busyId === proposal.id} onClick={() => decide(proposal, 'approved')}>Phê duyệt</button>
          <button className="danger" disabled={busyId === proposal.id} onClick={() => decide(proposal, 'rejected')}>Từ chối</button>
        </span>
      </article>)}</div>}
    {notice && <p className="quality-control-notice">{notice}</p>}
  </details>
}

export default function DeliveryAgentPage({ assignedAgent }) {
  const { token, user } = useAuth()
  const { workspaces } = useWorkspace()
  const { subscribe } = useOutletContext()
  const company = useMemo(
    () => workspaces.find(item => item.type === 'organization' && item.slug === 'company-root')
      || workspaces.find(item => item.type === 'organization'),
    [workspaces],
  )
  const [agentWorkspaces, setAgentWorkspaces] = useState(() => assignedAgent ? [assignedAgent] : [])
  const [agentWorkspaceId, setAgentWorkspaceId] = useState('')
  const [businessRole, setBusinessRole] = useState(null)
  const [groups, setGroups] = useState([])
  const [qualityWorkspaces, setQualityWorkspaces] = useState([])
  const [canSelectGroup, setCanSelectGroup] = useState(false)
  const [selectedConversationId, setSelectedConversationId] = useState('')
  const [messages, setMessages] = useState([])
  const [threadId, setThreadId] = useState(null)
  const [threads, setThreads] = useState([])
  const [threadSearch, setThreadSearch] = useState('')
  const [historyLoading, setHistoryLoading] = useState(false)
  const [deletingThreadId, setDeletingThreadId] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(false)
  const [initializing, setInitializing] = useState(true)
  const [error, setError] = useState('')
  const [liveProgress, setLiveProgress] = useState(null)
  const [showLeadTools, setShowLeadTools] = useState(false)
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const messagesContainerRef = useRef(null)
  const shouldStickToBottomRef = useRef(true)
  const activeRequestRef = useRef(null)

  const activeAgent = agentWorkspaces.find(agent => agent.id === agentWorkspaceId) || null
  const analysisScopeKey = selectedConversationId || 'workspace'
  const storageKey = user?.id && agentWorkspaceId
    ? `orbit_workspace_agent_chat:${user.id}:${agentWorkspaceId}:${analysisScopeKey}`
    : null
  const threadStorageKey = storageKey ? `${storageKey}:thread` : null
  const promptSuggestions = businessRole === 'lead' ? leadPrompts : memberPrompts
  const selectedGroupName = groups.find(group => group.id === selectedConversationId)?.name || ''
  const defaultScopeName = businessRole === 'lead' ? 'Toàn bộ workspace' : 'Task của tôi'
  const visibleThreads = threads.filter(thread => (
    `${thread.title} ${thread.preview}`.toLocaleLowerCase('vi-VN')
      .includes(threadSearch.trim().toLocaleLowerCase('vi-VN'))
  ))
  const groupedThreads = visibleThreads.reduce((groupsByDate, thread) => {
    const label = historyGroupLabel(thread.updated_at)
    const group = groupsByDate.find(item => item.label === label)
    if (group) group.threads.push(thread)
    else groupsByDate.push({ label, threads: [thread] })
    return groupsByDate
  }, [])

  useEffect(() => {
    if (!mobileSidebarOpen) return undefined
    const closeOnEscape = event => {
      if (event.key === 'Escape') setMobileSidebarOpen(false)
    }
    document.addEventListener('keydown', closeOnEscape)
    return () => document.removeEventListener('keydown', closeOnEscape)
  }, [mobileSidebarOpen])

  useEffect(() => {
    const deliveryAgents = assignedAgent?.agent_profile === 'product_delivery' ? [assignedAgent] : []
    setAgentWorkspaces(deliveryAgents)
    setAgentWorkspaceId(deliveryAgents[0]?.id || '')
    setBusinessRole(deliveryAgents[0]?.current_user_business_role || null)
    setInitializing(false)
  }, [assignedAgent])

  useEffect(() => {
    const selectedAgent = agentWorkspaces.find(agent => agent.id === agentWorkspaceId)
    setBusinessRole(selectedAgent?.current_user_business_role || null)
    if (!company?.id || !agentWorkspaceId) return
    let cancelled = false
    Promise.all([
      queryClient.fetchQuery({
        queryKey: queryKeys.deliveryCapabilities(company.id, agentWorkspaceId),
        queryFn: () => getDeliveryCapabilities(token, company.id, agentWorkspaceId),
        staleTime: 2 * 60_000,
      }),
      selectedAgent?.current_user_business_role === 'lead'
        ? queryClient.fetchQuery({
          queryKey: queryKeys.deliveryReleaseTargets(company.id, agentWorkspaceId),
          queryFn: () => getDeliveryReleaseTargets(token, company.id, agentWorkspaceId),
          staleTime: 2 * 60_000,
        })
        : Promise.resolve([]),
    ])
      .then(([response, releaseTargets]) => {
        if (cancelled) return
        setBusinessRole(response.current_user_business_role || null)
        setCanSelectGroup(Boolean(response.can_select_group))
        setGroups(response.groups || [])
        setQualityWorkspaces(releaseTargets || [])
        setSelectedConversationId('')
      })
      .catch(() => {
        if (!cancelled) {
          setCanSelectGroup(false)
          setGroups([])
          setQualityWorkspaces([])
        }
      })
    return () => { cancelled = true }
  }, [agentWorkspaceId, agentWorkspaces, company?.id, token])

  useEffect(() => {
    if (!company?.id || !agentWorkspaceId || !businessRole) return undefined
    let cancelled = false
    setHistoryLoading(true)
    const load = async () => {
      try {
        const availableThreads = await queryClient.fetchQuery({
          queryKey: queryKeys.deliveryThreads(company.id, agentWorkspaceId, analysisScopeKey),
          queryFn: () => listDeliveryThreads(token, company.id, agentWorkspaceId, selectedConversationId),
          staleTime: 60_000,
        })
        if (cancelled) return
        setThreads(availableThreads)
        let cachedThreadId = null
        try { cachedThreadId = threadStorageKey ? sessionStorage.getItem(threadStorageKey) : null } catch { /* optional cache */ }
        const targetThreadId = availableThreads.some(item => item.thread_id === cachedThreadId)
          ? cachedThreadId
          : availableThreads[0]?.thread_id || null
        if (!targetThreadId) {
          setThreadId(null)
          setMessages([createWelcomeMessage(businessRole)])
          return
        }
        const history = await queryClient.fetchQuery({
          queryKey: queryKeys.deliveryThreadMessages(company.id, agentWorkspaceId, targetThreadId, analysisScopeKey),
          queryFn: () => getDeliveryThreadMessages(token, company.id, agentWorkspaceId, targetThreadId, selectedConversationId),
          staleTime: 60_000,
        })
        if (cancelled) return
        setThreadId(targetThreadId)
        setMessages(history.map(item => ({
          id: item.id,
          role: item.role,
          content: item.content,
          createdAt: item.created_at,
          runHistory: item.run_history,
        })))
        if (threadStorageKey) sessionStorage.setItem(threadStorageKey, targetThreadId)
      } catch {
        if (!cancelled) {
          setThreads([])
          setThreadId(null)
          setMessages([createWelcomeMessage(businessRole)])
        }
      } finally {
        if (!cancelled) setHistoryLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [agentWorkspaceId, businessRole, company?.id, threadStorageKey, token])

  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      const container = messagesContainerRef.current
      if (!container || !shouldStickToBottomRef.current) return
      container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' })
    })
    return () => cancelAnimationFrame(frame)
  }, [messages])

  useEffect(() => {
    if (!loading || !shouldStickToBottomRef.current) return
    const frame = requestAnimationFrame(() => {
      const container = messagesContainerRef.current
      if (container) container.scrollTop = container.scrollHeight
    })
    return () => cancelAnimationFrame(frame)
  }, [liveProgress, loading])

  useEffect(() => subscribe(data => {
    if (
      data.type !== 'workspace_agent_progress'
      || data.request_id !== activeRequestRef.current
      || data.agent_workspace_id !== agentWorkspaceId
    ) return
    setLiveProgress(previous => mergeDeliveryProgress(previous, data))
  }), [agentWorkspaceId, subscribe])

  const askAgent = async event => {
    event?.preventDefault()
    const content = question.trim()
    if (!content || !company?.id || !agentWorkspaceId || loading) return
    const userMessage = { id: `user-${Date.now()}`, role: 'user', content, createdAt: new Date().toISOString() }
    setMessages(previous => [...previous, userMessage])
    setQuestion('')
    setLoading(true)
    setError('')
    shouldStickToBottomRef.current = true
    const requestId = globalThis.crypto?.randomUUID?.() || `delivery-${Date.now()}-${Math.random().toString(16).slice(2)}`
    activeRequestRef.current = requestId
    setLiveProgress({ request_id: requestId, phase: 'routing', specialists: [] })
    try {
      const response = await getDeliveryBrief(token, company.id, agentWorkspaceId, {
        message: content,
        selected_conversation_id: canSelectGroup && selectedConversationId ? selectedConversationId : null,
        thread_id: threadId,
        client_request_id: requestId,
      })
      const nextThreadId = response.payload?.thread_id || null
      setThreadId(nextThreadId)
      if (threadStorageKey && nextThreadId) {
        try { sessionStorage.setItem(threadStorageKey, nextThreadId) } catch { /* non-critical cache */ }
      }
      const answer = response.payload?.agent_response || response.payload?.brief?.headline || 'Đã tổng hợp xong dữ liệu Delivery trong phạm vi của bạn.'
      setMessages(previous => [...previous, {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: answer,
        createdAt: new Date().toISOString(),
        result: response,
      }])
      queryClient.invalidateQueries({
        queryKey: queryKeys.deliveryThreadMessages(company.id, agentWorkspaceId, nextThreadId, analysisScopeKey),
      })
      listDeliveryThreads(token, company.id, agentWorkspaceId, selectedConversationId)
        .then(nextThreads => {
          queryClient.setQueryData(queryKeys.deliveryThreads(company.id, agentWorkspaceId, analysisScopeKey), nextThreads)
          setThreads(nextThreads)
        })
        .catch(() => { /* the completed chat remains usable even if the list refresh fails */ })
    } catch (requestError) {
      const detail = requestError.detail || 'Workspace Agent hiện không khả dụng.'
      setError(detail)
      setMessages(previous => [...previous, {
        id: `error-${Date.now()}`,
        role: 'assistant',
        content: `Tôi chưa thể hoàn thành truy vấn này: ${detail}`,
        createdAt: new Date().toISOString(),
        error: true,
      }])
    } finally {
      setLoading(false)
      activeRequestRef.current = null
    }
  }

  const clearConversation = () => {
    if (loading) return
    const next = [createWelcomeMessage(businessRole)]
    setMessages(next)
    setThreadId(null)
    setLiveProgress(null)
    setError('')
    if (threadStorageKey) {
      try { sessionStorage.removeItem(threadStorageKey) } catch { /* optional cache */ }
    }
    setMobileSidebarOpen(false)
  }

  const openThread = async nextThreadId => {
    if (!nextThreadId || loading || historyLoading || !company?.id || !agentWorkspaceId) return
    setMobileSidebarOpen(false)
    setHistoryLoading(true)
    setError('')
    setLiveProgress(null)
    shouldStickToBottomRef.current = true
    try {
      const history = await queryClient.fetchQuery({
        queryKey: queryKeys.deliveryThreadMessages(company.id, agentWorkspaceId, nextThreadId, analysisScopeKey),
        queryFn: () => getDeliveryThreadMessages(token, company.id, agentWorkspaceId, nextThreadId, selectedConversationId),
        staleTime: 60_000,
      })
      setThreadId(nextThreadId)
      setMessages(history.map(item => ({
        id: item.id,
        role: item.role,
        content: item.content,
        createdAt: item.created_at,
        runHistory: item.run_history,
      })))
      if (threadStorageKey) sessionStorage.setItem(threadStorageKey, nextThreadId)
    } catch (historyError) {
      setError(historyError.detail || 'Không thể mở lại cuộc trò chuyện này.')
    } finally {
      setHistoryLoading(false)
    }
  }

  const removeThread = async targetThread => {
    if (
      !targetThread?.thread_id
      || loading
      || historyLoading
      || deletingThreadId
      || !company?.id
      || !agentWorkspaceId
    ) return
    setDeletingThreadId(targetThread.thread_id)
    setError('')
    try {
      await deleteDeliveryThread(
        token,
        company.id,
        agentWorkspaceId,
        targetThread.thread_id,
        selectedConversationId,
      )
      const nextThreads = threads.filter(item => item.thread_id !== targetThread.thread_id)
      setThreads(nextThreads)
      queryClient.setQueryData(
        queryKeys.deliveryThreads(company.id, agentWorkspaceId, analysisScopeKey),
        nextThreads,
      )
      queryClient.removeQueries({
        queryKey: queryKeys.deliveryThreadMessages(
          company.id,
          agentWorkspaceId,
          targetThread.thread_id,
          analysisScopeKey,
        ),
        exact: true,
      })
      if (targetThread.thread_id === threadId) {
        setThreadId(null)
        setMessages([createWelcomeMessage(businessRole)])
        setLiveProgress(null)
        if (threadStorageKey) {
          try { sessionStorage.removeItem(threadStorageKey) } catch { /* optional cache */ }
        }
      }
      setDeleteTarget(null)
    } catch (deleteError) {
      setError(deleteError.detail || 'Không thể xóa lịch sử Workspace Agent này.')
    } finally {
      setDeletingThreadId(null)
    }
  }

  return (
    <div className="workspace-agent-page">
      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="Xóa lịch sử Workspace Agent?"
        message={deleteTarget ? `Cuộc trò chuyện “${deleteTarget.title}” sẽ bị xóa vĩnh viễn. Task, workflow và dữ liệu nguồn của workspace vẫn được giữ nguyên.` : ''}
        confirmLabel={deletingThreadId ? 'Đang xóa…' : 'Xóa cuộc trò chuyện'}
        busy={Boolean(deletingThreadId)}
        onCancel={()=>{ if (!deletingThreadId) setDeleteTarget(null) }}
        onConfirm={()=>{ if (deleteTarget && !deletingThreadId) removeThread(deleteTarget) }}
      />
      <button
        type="button"
        className={`workspace-agent-sidebar-backdrop ${mobileSidebarOpen ? 'show' : ''}`}
        aria-label="Đóng lịch sử trò chuyện"
        tabIndex={mobileSidebarOpen ? 0 : -1}
        onClick={() => setMobileSidebarOpen(false)}
      />
      <aside
        className={`workspace-agent-sidebar ${mobileSidebarOpen ? 'mobile-open' : ''}`}
        id="delivery-agent-sidebar"
        aria-label="Lịch sử Workspace Agent"
      >
        <div className="workspace-agent-identity">
          <span><i className="bi bi-robot" /></span>
          <div><small>Agentic AI · LLM enabled</small><strong>Product Delivery</strong><p>Workspace Agent</p></div>
          <button type="button" className="workspace-agent-sidebar-close" aria-label="Đóng lịch sử trò chuyện" onClick={() => setMobileSidebarOpen(false)}><i className="bi bi-x-lg" /></button>
        </div>

        <section className="workspace-agent-history">
          <button type="button" className="workspace-agent-new-chat" onClick={clearConversation} disabled={loading}>
            <i className="bi bi-pencil-square" /><span>Chat mới</span>
          </button>
          <label className="workspace-agent-history-search">
            <i className="bi bi-search" />
            <input
              value={threadSearch}
              onChange={event => setThreadSearch(event.target.value)}
              placeholder="Tìm cuộc trò chuyện"
            />
          </label>
          <div className="workspace-agent-history-list">
            {historyLoading && !threads.length && <p className="workspace-agent-history-empty">Đang tải lịch sử…</p>}
            {!historyLoading && !visibleThreads.length && <p className="workspace-agent-history-empty">
              {threadSearch ? 'Không tìm thấy cuộc trò chuyện.' : 'Chưa có cuộc trò chuyện nào.'}
            </p>}
            {groupedThreads.map(group => <section className="workspace-agent-history-group" key={group.label}>
              <h3>{group.label}</h3>
              {group.threads.map(thread => <div
                className={`workspace-agent-history-row ${thread.thread_id === threadId ? 'active' : ''}`}
                key={thread.thread_id}
              >
                <button
                  type="button"
                  className={`workspace-agent-thread-button ${thread.thread_id === threadId ? 'active' : ''}`}
                  onClick={() => openThread(thread.thread_id)}
                  disabled={loading || historyLoading || Boolean(deletingThreadId)}
                  title={thread.title}
                ><span>{thread.title}</span></button>
                <button
                  type="button"
                  className="workspace-agent-history-delete"
                  aria-label={`Xóa cuộc trò chuyện ${thread.title}`}
                  title="Xóa cuộc trò chuyện"
                  onClick={event => { event.stopPropagation(); setError(''); setDeleteTarget(thread) }}
                  disabled={loading || historyLoading || Boolean(deletingThreadId)}
                ><i className="bi bi-trash3" /></button>
              </div>)}
            </section>)}
          </div>
        </section>
      </aside>

      <main className="workspace-agent-chat">
        <header>
          <div className="workspace-agent-heading">
            <button
              type="button"
              className="workspace-agent-mobile-sidebar-toggle"
              aria-label="Mở lịch sử trò chuyện"
              aria-controls="delivery-agent-sidebar"
              aria-expanded={mobileSidebarOpen}
              onClick={() => setMobileSidebarOpen(true)}
            ><i className="bi bi-layout-sidebar-inset" /></button>
            <div><h1>{getAgentWorkspaceDisplayName(activeAgent) || 'Product Delivery'}</h1><p><span /> Trực tuyến · Phạm vi: {selectedGroupName || (canSelectGroup ? defaultScopeName : 'Công việc được cấp quyền')}</p></div>
          </div>
          <div className="workspace-agent-header-actions">
            {canSelectGroup && <label className="workspace-agent-scope-selector">
              <span>Phạm vi task</span>
              <select
                value={selectedConversationId}
                onChange={event => {
                  setSelectedConversationId(event.target.value)
                  setThreadId(null)
                  setMessages([createWelcomeMessage(businessRole)])
                  setLiveProgress(null)
                  setError('')
                }}
                disabled={loading || historyLoading}
              >
                <option value="">{businessRole === 'lead' ? 'Toàn bộ workspace' : 'Task của tôi'}</option>
                {groups.map(group => <option key={group.id} value={group.id}>{group.name}</option>)}
              </select>
            </label>}
            {businessRole === 'lead' && <button
              type="button"
              className={`btn btn-sm ${showLeadTools ? 'btn-primary' : 'btn-light'}`}
              aria-expanded={showLeadTools}
              aria-controls="delivery-lead-tools"
              onClick={() => setShowLeadTools(value => !value)}
            ><i className="bi bi-sliders me-2" />Công cụ Lead</button>}
          </div>
        </header>
        {businessRole === 'lead' && showLeadTools && <div className="workspace-agent-control-dock" id="delivery-lead-tools">
          <DeliveryLeadControls token={token} workspaceId={company?.id} agentId={agentWorkspaceId} conversationId={selectedConversationId || groups[0]?.id || ''} qualityWorkspaces={qualityWorkspaces} />
          <DeliveryApprovalQueue token={token} workspaceId={company?.id} agentId={agentWorkspaceId} />
        </div>}

        <div
          className="workspace-agent-messages"
          ref={messagesContainerRef}
          onScroll={event => {
            const element = event.currentTarget
            shouldStickToBottomRef.current = element.scrollHeight - element.scrollTop - element.clientHeight < 96
          }}
        >
          {initializing && <div className="agent-initializing"><span className="spinner-border spinner-border-sm" /> Đang khởi tạo Workspace Agent…</div>}
          {!initializing && !agentWorkspaces.length && <div className="agent-unavailable"><i className="bi bi-shield-lock" /><h2>Chưa có quyền sử dụng Agent</h2><p>Tài khoản của bạn chưa được gán vào Product Delivery agent workspace.</p></div>}
          {messages.map(message => (
            <article className={`workspace-agent-message ${message.role} ${message.error ? 'error' : ''}`} key={message.id}>
              <span className="agent-message-avatar">{message.role === 'assistant' ? <i className="bi bi-robot" /> : (user?.display_name || '?').trim()[0]}</span>
              <div>
                <header><strong>{message.role === 'assistant' ? 'Workspace Agent' : 'Bạn'}</strong><time>{formatMessageTime(message.createdAt)}</time></header>
                <section>{message.role === 'assistant' ? <Markdown>{message.content}</Markdown> : <p>{message.content}</p>}</section>
                {message.role === 'assistant' && <AgentRunHistory result={message.result} runHistory={message.runHistory} />}
                <ResultSummary result={message.result} />
              </div>
            </article>
          ))}
          {loading && <article className="workspace-agent-message assistant"><span className="agent-message-avatar"><i className="bi bi-robot" /></span><div><header><strong>Workspace Agent</strong></header><LiveOrchestrationProgress progress={liveProgress} /></div></article>}
        </div>

        {agentWorkspaces.length > 0 && (
          <footer className="workspace-agent-composer">
            {!messages.some(message => message.role === 'user') && (
              <div className="agent-prompt-suggestions">
                {promptSuggestions.map(prompt => <button type="button" key={prompt} onClick={() => setQuestion(prompt)}>{prompt}</button>)}
              </div>
            )}
            <form onSubmit={askAgent}>
              <textarea
                rows="2"
                maxLength="2000"
                value={question}
                onChange={event => setQuestion(event.target.value)}
                onKeyDown={event => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault()
                    askAgent()
                  }
                }}
                placeholder={businessRole === 'lead' ? 'Hỏi về tiến độ, blocker, deadline hoặc quyết định cần chốt…' : 'Hỏi về công việc và tiến độ liên quan đến bạn…'}
              />
              <button type="submit" disabled={loading || !question.trim()} aria-label="Gửi câu hỏi"><i className="bi bi-send-fill" /></button>
            </form>
            <small><i className="bi bi-info-circle" /> Workspace Agent có thể sai. Hãy đối chiếu bằng chứng trước quyết định quan trọng.</small>
          </footer>
        )}
        {error && <div className="workspace-agent-error" role="alert">{error}</div>}
      </main>
    </div>
  )
}

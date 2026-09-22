import { useMemo } from 'react'
import { useQueries } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { getDeliveryDashboard } from '../api/agent'
import PageHeader from '../components/common/PageHeader'
import { useAuth } from '../context/AuthContext'
import { useWorkspace } from '../context/WorkspaceContext'
import { getAgentWorkspaceDisplayName } from '../utils/workspaceLabels'
import { useAvailableAgentsQuery } from '../hooks/useWorkspaceData'
import { queryKeys } from '../query/queryClient'
import { getColor, getInitials } from '../utils/avatar'

const profileName = profile => ({
  product_delivery: 'Product Delivery Agent',
  quality_assurance: 'Quality Assurance Agent',
  executive: 'Executive Agent',
}[profile] || profile)

const statusLabel = status => ({
  pending: 'Chờ xử lý', suggested: 'Đề xuất', in_progress: 'Đang làm', blocked: 'Bị chặn',
  completed: 'Hoàn thành', dismissed: 'Đã bỏ', invalidated: 'Mất hiệu lực',
}[status] || status)

const formatDate = value => value
  ? new Intl.DateTimeFormat('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric' }).format(new Date(value))
  : 'Chưa có hạn'

const formatActivity = value => value
  ? new Intl.DateTimeFormat('vi-VN', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
  : 'Chưa có hoạt động'

function ProgressBar({ value }) {
  return <div className="delivery-progress-track"><span style={{ width: `${value}%` }} /></div>
}

function WorkItemList({ title, items, emptyText }) {
  return (
    <section className="workspace-work-list">
      <h4>{title} <span>{items.length}</span></h4>
      {items.map(item => (
        <article key={item.id}>
          <span className={`work-status-dot ${item.status}`} />
          <div>
            <strong>{item.title}</strong>
            <small>{item.assignee_name || 'Chưa gán người phụ trách'} · {formatDate(item.due_at)}</small>
            {item.blocked_reason && <p><i className="bi bi-exclamation-triangle" /> {item.blocked_reason}</p>}
          </div>
          <em className={item.status}>{statusLabel(item.status)}</em>
        </article>
      ))}
      {!items.length && <p className="workspace-empty-copy">{emptyText}</p>}
    </section>
  )
}

function WorkspaceMemberTable({ members }) {
  return (
    <section className="delivery-members-panel">
      <header>
        <div><span className="eyebrow">Team directory</span><h2>Thành viên Product Delivery</h2><p>Vai trò, chức danh và nhóm tham gia trong phạm vi được phép.</p></div>
        <strong>{members.length} người</strong>
      </header>
      <div className="delivery-member-table-wrap">
        <table className="delivery-member-table">
          <thead><tr><th>Thành viên</th><th>Vai trò</th><th>Nhóm tham gia</th><th>Khối lượng công việc</th><th>Liên hệ</th></tr></thead>
          <tbody>
            {members.map(member => (
              <tr key={member.user_id}>
                <td data-label="Thành viên"><span className="member-table-avatar" style={{ background: getColor(member.user_id) }}>{getInitials(member.display_name)}</span><div><strong>{member.display_name}</strong><small>{member.job_title || 'Chưa cập nhật chức danh'}</small></div></td>
                <td data-label="Vai trò"><span className={`member-role-pill ${member.business_role || 'participant'}`}>{member.business_role === 'lead' ? 'Delivery Lead' : member.business_role === 'member' ? 'Member' : 'Group participant'}</span></td>
                <td data-label="Nhóm tham gia"><div className="member-group-pills">{member.groups.map(group => <span key={group.id}>{group.name}</span>)}</div></td>
                <td data-label="Khối lượng công việc">{member.task_stats ? <div className="member-workload"><span><strong>{member.task_stats.total}</strong> task · <b>{member.task_stats.in_progress} đang làm</b> · <em>{member.task_stats.blocked} blocker</em></span><ProgressBar value={member.task_stats.completion_percent} /><small>{member.milestone_count || 0} milestone · hoàn thành {member.task_stats.completion_percent}%</small></div> : <span className="member-private-work"><i className="bi bi-lock" /> Ẩn theo quyền</span>}</td>
                <td data-label="Liên hệ"><a href={`mailto:${member.email}`}>{member.email}</a></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function DeliveryWorkspaceDashboard({ workspace, dashboard }) {
  const isLead = dashboard.current_user_business_role === 'lead'
  const scopeLabel = isLead ? 'Toàn bộ workspace được quản lý' : 'Nhóm và công việc liên quan đến bạn'
  const stats = [
    ['Nhóm trong phạm vi', dashboard.total_groups, 'bi-people', 'blue'],
    ['Thành viên', dashboard.total_members, 'bi-person-badge', 'violet'],
    ['Tiến độ task', `${dashboard.task_stats.completion_percent}%`, 'bi-graph-up-arrow', 'green'],
    ['Task bị chặn', dashboard.task_stats.blocked, 'bi-exclamation-octagon', 'red'],
    ['Task quá hạn', dashboard.task_stats.overdue, 'bi-clock-history', 'orange'],
    ['Milestone', dashboard.milestone_stats.total, 'bi-flag', 'cyan'],
  ]

  return (
    <div className="delivery-workspace-dashboard">
      <section className="delivery-workspace-hero">
        <div className="delivery-workspace-title">
          <span className="delivery-workspace-logo"><i className="bi bi-boxes" /></span>
          <div><span className="eyebrow">Product Delivery Workspace</span><h2>{getAgentWorkspaceDisplayName(workspace)}</h2><p>{profileName(workspace.agent_profile)} · Lead: {workspace.lead_display_name || workspace.lead_email}</p></div>
        </div>
        <div className="delivery-workspace-actions">
          <span className={`workspace-role ${isLead ? 'lead' : 'member'}`}><i className="bi bi-shield-check" /> {isLead ? 'Delivery Lead' : 'Member'}</span>
          <Link className="btn btn-light btn-sm" to="/groups"><i className="bi bi-people me-2" />Xem nhóm</Link>
          <Link className="btn btn-primary btn-sm" to="/workspace-agent"><i className="bi bi-robot me-2" />Mở Workspace Agent</Link>
        </div>
      </section>

      <div className="delivery-scope-banner"><i className="bi bi-lock" /><span><strong>Phạm vi hiển thị: {scopeLabel}</strong><small>Số liệu lấy trực tiếp từ database đã scope; trang này không gọi LLM và không quét toàn Company.</small></span><time>Cập nhật {formatActivity(dashboard.generated_at)}</time></div>

      <section className="delivery-kpi-grid">
        {stats.map(([label, value, icon, color]) => <article key={label}><span className={color}><i className={`bi ${icon}`} /></span><div><strong>{value}</strong><small>{label}</small></div></article>)}
      </section>

      <section className="delivery-progress-overview">
        <div><span><strong>Tiến độ công việc</strong><small>{dashboard.task_stats.completed}/{dashboard.task_stats.total} task hoàn thành</small></span><b>{dashboard.task_stats.completion_percent}%</b></div>
        <ProgressBar value={dashboard.task_stats.completion_percent} />
        <footer>
          <span><i className="bi bi-play-circle" /> {dashboard.task_stats.in_progress} đang làm</span>
          <span><i className="bi bi-hourglass-split" /> {dashboard.task_stats.pending} chờ xử lý</span>
          <span className="danger"><i className="bi bi-exclamation-triangle" /> {dashboard.task_stats.blocked} bị chặn</span>
          <span><i className="bi bi-calendar-week" /> {dashboard.task_stats.due_soon} sắp đến hạn</span>
        </footer>
      </section>

      <div className="delivery-section-heading"><div><span className="eyebrow">Group performance</span><h2>Tiến độ theo nhóm</h2><p>Task, milestone, blocker, thành viên và hoạt động chat của từng nhóm.</p></div><span>{dashboard.at_risk_groups} nhóm cần chú ý</span></div>
      <section className="delivery-group-dashboard-grid">
        {dashboard.groups.map(group => {
          const atRisk = group.task_stats.blocked > 0 || group.task_stats.overdue > 0 || group.milestone_stats.blocked > 0
          return (
            <article className="delivery-group-dashboard-card" key={group.id}>
              <header>
                <span className="group-dashboard-logo" style={{ background: getColor(group.id) }}>{getInitials(group.name)}</span>
                <div><h3>{group.name}</h3><p>{group.member_count} thành viên · {group.message_count} tin nhắn</p></div>
                <em className={atRisk ? 'risk' : 'healthy'}><i className={`bi ${atRisk ? 'bi-exclamation-circle' : 'bi-check-circle'}`} /> {atRisk ? 'Cần chú ý' : 'Đúng tiến độ'}</em>
              </header>
              <div className="group-task-progress"><div><span>Task hoàn thành</span><strong>{group.task_stats.completion_percent}%</strong></div><ProgressBar value={group.task_stats.completion_percent} /></div>
              <div className="group-dashboard-metrics">
                <span><strong>{group.task_stats.total}</strong><small>Tổng task</small></span>
                <span><strong>{group.task_stats.in_progress}</strong><small>Đang làm</small></span>
                <span className="danger"><strong>{group.task_stats.blocked}</strong><small>Bị chặn</small></span>
                <span><strong>{group.milestone_stats.total}</strong><small>Milestone</small></span>
              </div>
              <div className="group-dashboard-members"><div>{group.members.slice(0, 5).map(member => <span key={member.user_id} title={`${member.display_name} · ${member.job_title}`} style={{ background: getColor(member.user_id) }}>{getInitials(member.display_name)}</span>)}</div><p>{group.members.map(member => member.display_name.split(' ').slice(-1)[0]).join(', ')}</p></div>
              {group.last_message && <div className="group-dashboard-activity"><i className="bi bi-chat-quote" /><span><strong>{group.last_message.sender_name}</strong><p>{group.last_message.excerpt}</p><small>{formatActivity(group.last_message.created_at)}</small></span></div>}
              <details className="group-dashboard-details">
                <summary>Xem chi tiết task và milestone <i className="bi bi-chevron-down" /></summary>
                <WorkItemList title={isLead ? 'Task của nhóm' : 'Task của tôi trong nhóm'} items={group.tasks} emptyText="Không có task trong phạm vi hiển thị." />
                <WorkItemList title={isLead ? 'Milestone của nhóm' : 'Milestone liên quan đến tôi'} items={group.milestones} emptyText="Không có milestone trong phạm vi hiển thị." />
              </details>
              <footer><span><i className={`bi ${group.ai_enabled ? 'bi-stars' : 'bi-shield-lock'}`} /> AI {group.ai_enabled ? 'đang bật' : 'đang tắt'}</span><span>Cập nhật {formatActivity(group.updated_at)}</span><Link to="/chat" state={{ conversationId: group.id }}>Mở chat <i className="bi bi-arrow-right" /></Link></footer>
            </article>
          )
        })}
      </section>

      <WorkspaceMemberTable members={dashboard.members} />
    </div>
  )
}

export default function WorkspaceManagementPage() {
  const { token } = useAuth()
  const { workspaces } = useWorkspace()
  const company = useMemo(
    () => workspaces.find(item => item.type === 'organization' && item.slug === 'company-root')
      || workspaces.find(item => item.type === 'organization'),
    [workspaces],
  )
  const assignmentsQuery = useAvailableAgentsQuery(token, company?.id)
  const assignedWorkspaces = assignmentsQuery.data || []
  const deliveryWorkspaces = assignedWorkspaces.filter(workspace => workspace.agent_profile === 'product_delivery')
  const dashboardQueries = useQueries({
    queries: deliveryWorkspaces.map(workspace => ({
      queryKey: queryKeys.deliveryDashboard(company?.id, workspace.id),
      queryFn: () => getDeliveryDashboard(token, company.id, workspace.id),
      enabled: Boolean(token && company?.id),
      staleTime: 30_000,
    })),
  })
  const dashboards = Object.fromEntries(deliveryWorkspaces.map((workspace, index) => [workspace.id, dashboardQueries[index]?.data]))
  const loading = Boolean(company?.id) && (assignmentsQuery.isPending || dashboardQueries.some(query => query.isPending))
  const requestError = assignmentsQuery.error || dashboardQueries.find(query => query.error)?.error
  const error = requestError?.detail || (requestError ? 'Không thể tải dữ liệu workspace.' : '')

  return (
    <div className="page-container delivery-workspaces-page">
      <PageHeader eyebrow="Company workspace" title="Tổng quan workspace" description="Theo dõi đội nhóm, thành viên, tiến độ Delivery và truy cập Workspace Agent trong một màn hình." />
      {error && <div className="alert alert-danger mt-3">{error}</div>}
      {loading && <div className="workspace-dashboard-loading"><span className="spinner-border spinner-border-sm" /> Đang tải dữ liệu thành viên và tiến độ…</div>}
      {!company && !loading && <div className="workspace-panel mt-4"><h3>Chưa có workspace</h3><p className="text-secondary mb-0">Hãy liên hệ quản trị viên để được gán vào workspace công ty.</p></div>}
      {!loading && company && !assignedWorkspaces.length && <div className="workspace-panel mt-4"><h3>Chưa được phân quyền</h3><p className="text-secondary mb-0">Tài khoản chưa phải Lead hoặc Member của agent workspace nào.</p></div>}
      {!loading && assignedWorkspaces.map(workspace => workspace.agent_profile === 'product_delivery' && dashboards[workspace.id]
        ? <DeliveryWorkspaceDashboard key={workspace.id} workspace={workspace} dashboard={dashboards[workspace.id]} />
        : <article className="workspace-card mt-4" key={workspace.id}><div className="workspace-card-head"><div><h3>{getAgentWorkspaceDisplayName(workspace)}</h3><small>{profileName(workspace.agent_profile)}</small></div><span className="workspace-role">{workspace.current_user_business_role}</span></div></article>)}
    </div>
  )
}

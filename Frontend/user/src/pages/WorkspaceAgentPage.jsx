import { useMemo } from 'react'
import { useAuth } from '../context/AuthContext'
import { useWorkspace } from '../context/WorkspaceContext'
import { useAvailableAgentsQuery } from '../hooks/useWorkspaceData'
import DeliveryAgentPage from './DeliveryAgentPage'
import QualityAgentPage from './QualityAgentPage'

function EmptyWorkspaceAgent({ title, detail, icon = 'bi-shield-lock' }) {
  return (
    <div className="workspace-agent-page workspace-agent-empty-page">
      <main className="workspace-agent-chat">
        <div className="agent-unavailable">
          <i className={`bi ${icon}`} />
          <h2>{title}</h2>
          <p>{detail}</p>
        </div>
      </main>
    </div>
  )
}

export default function WorkspaceAgentPage() {
  const { token } = useAuth()
  const { workspaces } = useWorkspace()
  const company = useMemo(
    () => workspaces.find(item => item.type === 'organization' && item.slug === 'company-root')
      || workspaces.find(item => item.type === 'organization'),
    [workspaces],
  )
  const assignmentQuery = useAvailableAgentsQuery(token, company?.id)
  const assignedAgents = assignmentQuery.data || []
  const loading = Boolean(company?.id) && assignmentQuery.isPending
  const error = assignmentQuery.error?.detail || (assignmentQuery.error ? 'Không thể kiểm tra quyền Agent Workspace.' : '')

  if (loading) {
    return <EmptyWorkspaceAgent title="Đang kiểm tra quyền truy cập" detail="Đang tải Agent Workspace được phân cho tài khoản…" icon="bi-hourglass-split" />
  }
  if (error) {
    return <EmptyWorkspaceAgent title="Không thể tải Agent Workspace" detail={error} icon="bi-exclamation-triangle" />
  }
  if (!assignedAgents.length) {
    return <EmptyWorkspaceAgent title="Chưa được phân Agent Workspace" detail="Tài khoản này chưa được gán làm Lead hoặc Member của Agent Workspace nào." />
  }
  if (assignedAgents.length > 1) {
    return <EmptyWorkspaceAgent title="Phân quyền Agent Workspace không hợp lệ" detail="Tài khoản đang được gán vào nhiều Agent Workspace. Vui lòng liên hệ quản trị viên để giữ lại đúng một workspace." icon="bi-exclamation-octagon" />
  }

  const [assignedAgent] = assignedAgents
  if (assignedAgent.agent_profile === 'product_delivery') return <DeliveryAgentPage assignedAgent={assignedAgent} />
  if (assignedAgent.agent_profile === 'quality_assurance') return <QualityAgentPage assignedAgent={assignedAgent} />
  return <EmptyWorkspaceAgent title="Agent Workspace chưa được hỗ trợ" detail="Profile của workspace này chưa có giao diện tương ứng." icon="bi-tools" />
}

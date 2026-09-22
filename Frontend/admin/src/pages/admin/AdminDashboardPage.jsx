import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AdminPageHeader, MetricCard, StatusBadge } from '../../components/AdminCommon'
import SimpleChart from '../../components/SimpleChart'
import { useAuth } from '../../context/AuthContext'
import { getAIUsage, getStats, getSystemHealth, listAuditLog } from '../../api/admin'

const colors = ['#596ff0', '#8b5bd3', '#1a9a82', '#d68731']
const label = value => value?.replace(/[._]/g, ' ').replace(/\b\w/g, letter => letter.toUpperCase()) || 'Platform event'

export default function AdminDashboardPage() {
  const { token } = useAuth()
  const [stats, setStats] = useState(null)
  const [health, setHealth] = useState(null)
  const [usage, setUsage] = useState(null)
  const [audit, setAudit] = useState({ items: [] })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    Promise.allSettled([getStats(token), getSystemHealth(token), getAIUsage(token, 7), listAuditLog(token)])
      .then(([statsResult, healthResult, usageResult, auditResult]) => {
        if (!active) return
        if (statsResult.status === 'fulfilled') setStats(statsResult.value)
        else setError(statsResult.reason?.detail || 'Could not load platform statistics.')
        if (healthResult.status === 'fulfilled') setHealth(healthResult.value)
        if (usageResult.status === 'fulfilled') setUsage(usageResult.value)
        if (auditResult.status === 'fulfilled') setAudit(auditResult.value)
      })
      .finally(() => active && setLoading(false))
    return () => { active = false }
  }, [token])

  const nearBudget = (stats?.budget_used_pct ?? 0) >= 80
  const cards = [
    { label: 'Total users', value: stats?.total_users?.toLocaleString() ?? '—', icon: 'bi-people', tone: 'blue', note: `${stats?.new_users_last_7_days ?? 0} new in 7 days` },
    { label: 'Conversations', value: stats?.total_conversations?.toLocaleString() ?? '—', icon: 'bi-chat-square-dots', tone: 'green', note: 'Platform total' },
    { label: 'Messages', value: stats?.total_messages?.toLocaleString() ?? '—', icon: 'bi-envelope', tone: 'violet', note: 'Platform total' },
    { label: 'AI requests today', value: stats?.requests_today?.toLocaleString() ?? '—', icon: 'bi-stars', tone: 'orange', note: 'Live usage' },
    { label: 'Tokens today', value: stats?.tokens_used_today?.toLocaleString() ?? '—', icon: 'bi-lightning-charge', tone: 'pink', note: `Highest account: ${stats?.budget_used_pct ?? 0}%`, trend: nearBudget ? 'down' : 'up' },
  ]
  const totalTokens = usage?.totals?.total_tokens || 0
  let cursor = 0
  const stops = (usage?.models || []).map((item, index) => {
    const end = cursor + (totalTokens ? item.total_tokens / totalTokens * 100 : 0)
    const stop = `${colors[index % colors.length]} ${cursor}% ${end}%`
    cursor = end
    return stop
  })
  const recent = (audit.items || []).slice(0, 5)

  return <div className="admin-page">
    <AdminPageHeader title="Platform overview" description="Live accounts, messaging, AI activity, and infrastructure health." />
    {error && <div className="admin-warning-banner"><i className="bi bi-exclamation-triangle" /><div><strong>Dashboard data is incomplete</strong><span>{error}</span></div></div>}
    {nearBudget && <div className="admin-warning-banner"><i className="bi bi-exclamation-triangle" /><div><strong>An account is nearing its daily AI allowance</strong><span>Highest account usage is {stats.budget_used_pct}% of the {stats.daily_token_budget.toLocaleString()} token per-account limit.</span></div></div>}
    {loading && <div className="admin-empty"><span className="spinner-border spinner-border-sm" /><strong>Loading platform data…</strong></div>}
    {!loading && <>
      <section className="admin-metrics-grid">{cards.map(item => <MetricCard key={item.label} item={item} />)}</section>
      <section className="admin-dashboard-grid">
        <article className="admin-card"><div className="admin-card-head"><div><h2>AI token volume</h2><p>Last seven days</p></div><div className="admin-chart-total"><strong>{totalTokens.toLocaleString()}</strong><span>{usage?.totals?.request_count || 0} requests</span></div></div><SimpleChart values={(usage?.daily || []).map(row => row.total_tokens)} /></article>
        <article className="admin-card"><div className="admin-card-head"><div><h2>Usage by model</h2><p>Recorded token distribution</p></div></div><div className="admin-donut" style={{ background: stops.length ? `conic-gradient(${stops.join(',')})` : '#edf0f5' }}><div><strong>{totalTokens.toLocaleString()}</strong><span>Total tokens</span></div></div><div className="admin-model-legend">{(usage?.models || []).slice(0, 4).map((model, index) => <div key={`${model.provider}:${model.model}`}><i style={{ background: colors[index % colors.length] }} /><span>{model.model}</span><strong>{model.total_tokens.toLocaleString()}</strong><em>{totalTokens ? Math.round(model.total_tokens / totalTokens * 100) : 0}%</em></div>)}</div></article>
      </section>
      <section className="admin-bottom-grid">
        <article className="admin-card"><div className="admin-card-head"><div><h2>Recent platform activity</h2><p>Latest sanitized audit events</p></div><Link to="/admin/audit-log" className="admin-text-link">View audit log <i className="bi bi-arrow-right" /></Link></div><div className="admin-activity-list">{recent.map(row => <div className="admin-activity-row" key={row.id}><span className="admin-activity-icon"><i className="bi bi-shield-check" /></span><div><strong>{label(row.action)}</strong><span>{row.actor_display_name || row.actor_email || row.actor_type} · {label(row.target_type)}</span></div><time>{new Date(row.created_at).toLocaleTimeString()}</time><StatusBadge value="Recorded" /></div>)}{!recent.length && <div className="admin-empty"><strong>No audit activity yet</strong></div>}</div></article>
        <article className="admin-card admin-health-card"><div className="admin-card-head"><div><h2>Platform health</h2><p>Live dependency checks</p></div><span className="admin-live"><i /> LIVE</span></div><div className="admin-health-score"><div><strong>{label(health?.overall_status || 'unknown')}</strong><span>Overall status</span></div><i className={`bi ${health?.overall_status === 'operational' ? 'bi-check-circle-fill' : 'bi-exclamation-triangle-fill'}`} /></div>{(health?.components || []).map(component => <div className="admin-health-row" key={component.key}><span><strong>{component.label}</strong><small>{component.detail}</small></span><StatusBadge value={component.status} /></div>)}</article>
      </section>
    </>}
  </div>
}

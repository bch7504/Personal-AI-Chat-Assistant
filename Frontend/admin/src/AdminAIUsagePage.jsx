import { useEffect, useState } from 'react'
import PageHeader from '../../src/components/common/PageHeader'
import { getAIUsage } from '../../src/api/admin'
import { useAuth } from '../../src/context/AuthContext'

const number = value => value?.toLocaleString() ?? '—'
const cost = value => value == null ? '—' : `$${value.toFixed(4)}`

export default function AdminAIUsagePage() {
  const { token } = useAuth()
  const [days, setDays] = useState(7)
  const [report, setReport] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => { setError(''); getAIUsage(token, days).then(setReport).catch(err => setError(err.detail || 'Could not load AI usage.')) }, [token, days])
  const maxTokens = Math.max(...(report?.daily.map(item => item.total_tokens) || [0]), 1)

  return <div className="page-container admin-dashboard-page">
    <PageHeader eyebrow="Platform admin" title="AI Usage" description="Monitor token consumption, estimated cost, and model distribution." action={<select className="form-select admin-range-select" value={days} onChange={event => setDays(Number(event.target.value))}><option value={7}>Last 7 days</option><option value={14}>Last 14 days</option><option value={30}>Last 30 days</option></select>} />
    {error && <div className="admin-monitor-error"><i className="bi bi-exclamation-triangle" />{error}</div>}
    <div className="stats-grid"><div className="stat-card"><div className="stat-icon bg-primary-subtle text-primary"><i className="bi bi-cpu" /></div><div><div className="stat-value">{number(report?.totals.total_tokens)}</div><div className="stat-label">Total tokens</div></div></div><div className="stat-card"><div className="stat-icon bg-info-subtle text-info"><i className="bi bi-box-arrow-in-right" /></div><div><div className="stat-value">{number(report?.totals.prompt_tokens)}</div><div className="stat-label">Input tokens</div></div></div><div className="stat-card"><div className="stat-icon bg-warning-subtle text-warning"><i className="bi bi-box-arrow-right" /></div><div><div className="stat-value">{number(report?.totals.completion_tokens)}</div><div className="stat-label">Output tokens</div></div></div><div className="stat-card"><div className="stat-icon bg-success-subtle text-success"><i className="bi bi-currency-dollar" /></div><div><div className="stat-value">{cost(report?.totals.estimated_cost_usd)}</div><div className="stat-label">Estimated cost</div></div></div><div className="stat-card"><div className="stat-icon bg-secondary-subtle text-secondary"><i className="bi bi-stars" /></div><div><div className="stat-value">{number(report?.totals.request_count)}</div><div className="stat-label">AI requests</div></div></div></div>
    {(report?.totals.unpriced_tokens ?? 0) > 0 && <div className="admin-pricing-warning"><i className="bi bi-info-circle" />{number(report.totals.unpriced_tokens)} tokens use an unpriced model and are excluded from cost.</div>}
    <div className="admin-monitor-grid"><section className="admin-monitor-card"><div className="admin-monitor-heading"><div><span>Trend</span><h3>Daily token usage</h3></div><i className="bi bi-bar-chart" /></div><div className="admin-usage-chart">{report?.daily.map(item => <div className="admin-usage-bar-row" key={item.date}><span>{new Date(`${item.date}T00:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</span><div><i style={{ width: `${item.total_tokens / maxTokens * 100}%` }} /></div><strong>{number(item.total_tokens)}</strong></div>)}</div></section><section className="admin-monitor-card"><div className="admin-monitor-heading"><div><span>Models</span><h3>Usage distribution</h3></div><i className="bi bi-diagram-3" /></div><div className="admin-model-usage-list">{report?.models.map(item => <div key={`${item.provider}:${item.model}`}><span><strong>{item.model}</strong><small>{item.provider} · {number(item.request_count)} requests</small></span><em>{number(item.total_tokens)} tokens<br />{cost(item.estimated_cost_usd)}</em></div>)}{report && !report.models.length && <p className="admin-monitor-note">No AI usage in this period.</p>}</div></section></div>
    <p className="admin-monitor-note">Cost uses standard paid-tier text-token pricing and is an estimate only. Provider billing remains authoritative.</p>
  </div>
}

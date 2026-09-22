import { useEffect, useState } from 'react'
import { AdminPageHeader, EmptyState } from '../../components/AdminCommon'
import SimpleChart from '../../components/SimpleChart'
import { getAIUsage } from '../../api/admin'
import { useAuth } from '../../context/AuthContext'

const number = value => value?.toLocaleString() ?? '—'
const cost = value => value == null ? '—' : `$${Number(value).toFixed(4)}`

export default function AdminAIUsagePage() {
  const { token } = useAuth()
  const [days, setDays] = useState(7)
  const [report, setReport] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => { setError(''); getAIUsage(token, days).then(setReport).catch(err => setError(err.detail || 'Could not load usage.')) }, [token, days])

  const metrics = [
    ['bi-lightning-charge', 'blue', number(report?.totals.total_tokens), 'Total tokens'],
    ['bi-box-arrow-in-down', 'violet', number(report?.totals.prompt_tokens), 'Input tokens'],
    ['bi-box-arrow-up', 'green', number(report?.totals.completion_tokens), 'Output tokens'],
    ['bi-currency-dollar', 'orange', cost(report?.totals.estimated_cost_usd), 'Estimated cost'],
  ]
  return <div className="admin-page">
    <AdminPageHeader title="AI usage" description="Token consumption, request volume, and estimated model cost." action={<select className="admin-secondary-button" value={days} onChange={event => setDays(Number(event.target.value))}><option value="7">Last 7 days</option><option value="14">Last 14 days</option><option value="30">Last 30 days</option></select>} />
    {error && <div className="admin-warning-banner"><i className="bi bi-exclamation-triangle" /><div><strong>Usage data unavailable</strong><span>{error}</span></div></div>}
    <section className="admin-usage-metrics">{metrics.map(([icon, tone, value, label]) => <article key={label}><span className={tone}><i className={`bi ${icon}`} /></span><div><strong>{value}</strong><small>{label}</small></div></article>)}</section>
    {(report?.totals.unpriced_tokens || 0) > 0 && <div className="admin-warning-banner"><i className="bi bi-info-circle" /><div><strong>Unpriced usage</strong><span>{number(report.totals.unpriced_tokens)} tokens are excluded from the cost estimate.</span></div></div>}
    <section className="admin-card" style={{ marginBottom: 17 }}><div className="admin-card-head"><div><h2>Daily token volume</h2><p>Input and output tokens combined</p></div><div className="admin-chart-total"><strong>{number(report?.totals.total_tokens)}</strong><span>{number(report?.totals.request_count)} requests</span></div></div><SimpleChart values={(report?.daily || []).map(row => row.total_tokens)} /></section>
    <section className="admin-card admin-table-card"><div className="admin-card-head"><div><h2>Usage by model</h2><p>Provider and model totals for the selected period</p></div></div><div className="admin-table-scroll"><table className="admin-table admin-usage-table"><thead><tr><th>Provider / model</th><th>Requests</th><th>Input tokens</th><th>Output tokens</th><th>Total tokens</th><th>Estimated cost</th></tr></thead><tbody>{(report?.models || []).map(row => <tr key={`${row.provider}:${row.model}`}><td><span className="admin-model-badge"><i />{row.provider} · {row.model}</span></td><td>{number(row.request_count)}</td><td>{number(row.prompt_tokens)}</td><td>{number(row.completion_tokens)}</td><td><strong>{number(row.total_tokens)}</strong></td><td>{cost(row.estimated_cost_usd)}</td></tr>)}</tbody></table>{report && !report.models.length && <EmptyState text="No AI usage recorded" />}</div></section>
  </div>
}

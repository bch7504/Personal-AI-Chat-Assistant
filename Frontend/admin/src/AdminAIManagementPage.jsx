import { useEffect, useState } from 'react'
import PageHeader from '../../src/components/common/PageHeader'
import { getAIManagement, getSystemHealth, updateAIManagement } from '../../src/api/admin'
import { useAuth } from '../../src/context/AuthContext'

const statusLabel = { operational: 'Operational', degraded: 'Needs attention', down: 'Unavailable' }

export default function AdminAIManagementPage() {
  const { token } = useAuth()
  const [management, setManagement] = useState(null)
  const [health, setHealth] = useState(null)
  const [draft, setDraft] = useState({ provider: '', model: '', temperature: 0.7 })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const [nextManagement, nextHealth] = await Promise.all([getAIManagement(token), getSystemHealth(token)])
      setManagement(nextManagement)
      setHealth(nextHealth)
      setDraft({ provider: nextManagement.provider, model: nextManagement.model, temperature: nextManagement.temperature })
    } catch (err) {
      setError(err.detail || 'Could not load AI configuration.')
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [token])

  const chooseProvider = provider => {
    const options = management?.model_options?.[provider] || []
    setDraft(current => ({ ...current, provider, model: options[0]?.id || '' }))
    setNotice('')
  }

  const save = async event => {
    event.preventDefault()
    setSaving(true)
    setError('')
    setNotice('')
    try {
      const updated = await updateAIManagement(token, draft)
      setManagement(updated)
      setDraft({ provider: updated.provider, model: updated.model, temperature: updated.temperature })
      setNotice('AI model updated. New AI requests will use this configuration.')
    } catch (err) {
      setError(err.detail || 'Could not update AI configuration.')
    } finally { setSaving(false) }
  }

  const providerReady = management?.configured_providers?.includes(draft.provider)
  const selectedModels = management?.model_options?.[draft.provider] || []
  const unchanged = management && draft.provider === management.provider && draft.model === management.model && Number(draft.temperature) === Number(management.temperature)

  return <div className="page-container admin-dashboard-page">
    <PageHeader eyebrow="Platform admin" title="AI Management" description="Choose the provider and model used by the assistant for all new AI requests." action={<button className="btn btn-light rounded-3" onClick={load} disabled={loading || saving}><i className={`bi ${loading ? 'bi-arrow-repeat admin-spin' : 'bi-arrow-clockwise'} me-2`} />Refresh</button>} />
    {error && <div className="admin-monitor-error"><i className="bi bi-exclamation-triangle" />{error}</div>}
    {notice && <div className="admin-config-success"><i className="bi bi-check-circle-fill" />{notice}</div>}
    <div className="admin-ai-config-grid">
      <section className="admin-monitor-card admin-model-selector-card"><div className="admin-monitor-heading"><div><span>Active AI configuration</span><h3>Select model</h3></div><i className="bi bi-cpu" /></div><form className="admin-model-form" onSubmit={save}><label>Provider<select className="form-select" value={draft.provider} onChange={event => chooseProvider(event.target.value)} disabled={loading || saving}>{Object.keys(management?.model_options || {}).map(provider => <option key={provider} value={provider} disabled={!management.configured_providers.includes(provider)}>{provider[0].toUpperCase() + provider.slice(1)}{management.configured_providers.includes(provider) ? '' : ' — API key missing'}</option>)}</select></label><label>Model<select className="form-select" value={draft.model} onChange={event => setDraft(current => ({ ...current, model: event.target.value }))} disabled={loading || saving}>{selectedModels.map(model => <option key={model.id} value={model.id}>{model.label}</option>)}</select></label><label>Temperature <strong>{Number(draft.temperature).toFixed(1)}</strong><input type="range" min="0" max="2" step="0.1" value={draft.temperature} onChange={event => setDraft(current => ({ ...current, temperature: Number(event.target.value) }))} disabled={loading || saving} /><small>Lower values are more consistent; higher values are more creative.</small></label>{!providerReady && draft.provider && <div className="admin-pricing-warning"><i className="bi bi-key" />Configure the {draft.provider} API key on the backend before selecting this provider.</div>}<button className="btn btn-primary" disabled={loading || saving || !providerReady || !draft.model || unchanged}>{saving ? 'Saving…' : 'Apply model'}</button></form></section>
      <section className="admin-monitor-card admin-model-card"><div className="admin-monitor-heading"><div><span>Currently applied</span><h3>{management?.model || 'Loading…'}</h3></div><i className="bi bi-stars" /></div><dl><div><dt>Provider</dt><dd>{management?.provider || '—'}</dd></div><div><dt>Temperature</dt><dd>{management?.temperature ?? '—'}</dd></div><div><dt>Per-account daily budget</dt><dd>{management?.daily_token_budget?.toLocaleString() ?? '—'} tokens</dd></div><div><dt>Credential</dt><dd className={management?.llm_configured ? 'health-operational' : 'health-degraded'}>{management?.llm_configured ? 'Configured' : 'Missing'}</dd></div></dl><p className="admin-monitor-note">The selection is stored in the database and restored whenever the backend restarts.</p></section>
    </div>
    <div className="stats-grid admin-ai-stats">
      <div className="stat-card"><div className="stat-icon bg-success-subtle text-success"><i className="bi bi-unlock" /></div><div><div className="stat-value">{management?.granted_permissions ?? '—'}</div><div className="stat-label">Active AI permissions</div></div></div>
      <div className="stat-card"><div className="stat-icon bg-warning-subtle text-warning"><i className="bi bi-lock" /></div><div><div className="stat-value">{management?.revoked_permissions ?? '—'}</div><div className="stat-label">Revoked permissions</div></div></div>
      <div className="stat-card"><div className="stat-icon bg-primary-subtle text-primary"><i className="bi bi-lightbulb" /></div><div><div className="stat-value">{management?.proactive_suggestions ?? '—'}</div><div className="stat-label">Proactive suggestions</div></div></div>
      <div className="stat-card"><div className="stat-icon bg-info-subtle text-info"><i className="bi bi-check2" /></div><div><div className="stat-value">{management?.proactive_accepted ?? '—'}</div><div className="stat-label">Suggestions accepted</div></div></div>
      <div className="stat-card"><div className="stat-icon bg-danger-subtle text-danger"><i className="bi bi-x" /></div><div><div className="stat-value">{management?.proactive_dismissed ?? '—'}</div><div className="stat-label">Suggestions dismissed</div></div></div>
    </div>
    <section className="admin-monitor-card admin-health-section"><div className="admin-monitor-heading"><div><span>System health</span><h3>Service availability</h3></div>{health && <em className={`admin-overall health-bg-${health.overall_status}`}>{statusLabel[health.overall_status]}</em>}</div><div className="admin-health-list">{health?.components.map(component => <div className="admin-health-item" key={component.key}><span className={`admin-health-dot health-bg-${component.status}`} /><div><strong>{component.label}</strong><small>{component.detail}</small></div><em className={`health-${component.status}`}>{statusLabel[component.status]}</em></div>)}</div>{health && <p className="admin-health-time">Checked {new Date(health.checked_at).toLocaleString()}</p>}</section>
  </div>
}

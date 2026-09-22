import { useEffect, useState } from 'react'
import { AdminPageHeader, StatusBadge } from '../../components/AdminCommon'
import { getAIManagement, getSystemHealth, updateAIManagement, updateDailyBudget } from '../../api/admin'
import { useAuth } from '../../context/AuthContext'

const providerName = provider => ({ google: 'Google Gemini', groq: 'Groq', openai: 'OpenAI' }[provider] || provider)

export default function AdminAIManagementPage() {
  const { token } = useAuth()
  const [management, setManagement] = useState(null)
  const [health, setHealth] = useState(null)
  const [draft, setDraft] = useState({ provider: '', model: '', temperature: 0.7 })
  const [budget, setBudget] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [isError, setIsError] = useState(false)

  const load = async () => {
    setMessage(''); setIsError(false)
    try {
      const [config, systemHealth] = await Promise.all([getAIManagement(token), getSystemHealth(token)])
      setManagement(config); setHealth(systemHealth)
      setDraft({ provider: config.provider, model: config.model, temperature: config.temperature })
      setBudget(String(config.daily_token_budget))
    } catch (error) { setIsError(true); setMessage(error.detail || 'Could not load AI configuration.') }
  }
  useEffect(() => { load() }, [token])

  const selectProvider = provider => setDraft(current => ({ ...current, provider, model: management?.model_options?.[provider]?.[0]?.id || '' }))
  const saveModel = async event => {
    event.preventDefault(); setBusy(true); setMessage(''); setIsError(false)
    try { const next = await updateAIManagement(token, draft); setManagement(next); setMessage('AI runtime configuration updated.') }
    catch (error) { setIsError(true); setMessage(error.detail || 'Could not update AI configuration.') }
    finally { setBusy(false) }
  }
  const saveBudget = async () => {
    setBusy(true); setMessage(''); setIsError(false)
    try { await updateDailyBudget(token, Number(budget)); await load(); setMessage('Per-account daily token budget updated.') }
    catch (error) { setIsError(true); setMessage(error.detail || 'Could not update token budget.') }
    finally { setBusy(false) }
  }
  const providers = Object.keys(management?.model_options || {})
  const models = management?.model_options?.[draft.provider] || []
  const providerReady = management?.configured_providers?.includes(draft.provider)

  return <div className="admin-page">
    <AdminPageHeader title="AI management" description="Control the runtime model, daily budget, safety safeguards, and service health." />
    {message && <div className="admin-warning-banner"><i className={`bi ${isError ? 'bi-exclamation-triangle' : 'bi-check-circle'}`} /><div><strong>{isError ? 'Configuration action failed' : 'Configuration saved'}</strong><span>{message}</span></div></div>}
    <section className="admin-card admin-ai-master"><span className="admin-master-icon"><i className="bi bi-stars" /></span><div><h2>Orbit AI runtime</h2><p>{management?.provider ? `${providerName(management.provider)} · ${management.model}` : 'Loading active configuration…'}</p></div><StatusBadge value={management?.llm_configured ? 'Operational' : 'Degraded'} /></section>
    <form onSubmit={saveModel}>
      <section className="admin-card admin-settings-section"><div className="admin-section-heading"><span><i className="bi bi-cpu" /></span><div><h2>Provider and model</h2><p>Only providers with a configured API key can be activated.</p></div></div><div className="admin-model-options">{providers.map(provider => { const ready = management.configured_providers.includes(provider); const selected = draft.provider === provider; return <button type="button" key={provider} className={`admin-model-option ${selected ? 'selected' : ''}`} onClick={() => selectProvider(provider)}><div className="admin-model-option-top"><span className="admin-provider-logo">{provider.slice(0, 2).toUpperCase()}</span><span className="admin-radio"><i /></span></div><h3>{providerName(provider)}</h3><small>{ready ? 'API key configured' : 'API key missing'}</small></button> })}</div><div className="row g-3 mt-2"><label className="col-md-6"><span className="form-label small">Model</span><select className="form-select" value={draft.model} onChange={event => setDraft({ ...draft, model: event.target.value })}>{models.map(model => <option key={model.id} value={model.id}>{model.label}</option>)}</select></label><label className="col-md-6"><span className="form-label small">Temperature: {Number(draft.temperature).toFixed(1)}</span><input className="form-range mt-2" type="range" min="0" max="2" step="0.1" value={draft.temperature} onChange={event => setDraft({ ...draft, temperature: Number(event.target.value) })} /></label></div><button className="admin-primary-button mt-3" disabled={busy || !providerReady || !draft.model}><i className="bi bi-check-lg" />Apply runtime model</button></section>
    </form>
    <section className="admin-card admin-settings-section"><div className="admin-section-heading"><span><i className="bi bi-speedometer2" /></span><div><h2>Per-account daily token budget</h2><p>Each account receives this allowance independently. Set 0 for unlimited.</p></div></div><div className="admin-limit-layout"><div><div className="admin-number-input"><input type="number" min="0" value={budget} onChange={event => setBudget(event.target.value)} /><span>tokens / account / day</span></div><div className="admin-presets">{[0, 100000, 500000, 1000000].map(value => <button key={value} type="button" className={Number(budget) === value ? 'active' : ''} onClick={() => setBudget(String(value))}>{value ? value.toLocaleString() : 'Unlimited'}</button>)}</div><button className="admin-primary-button mt-3" disabled={busy || budget === ''} onClick={saveBudget}>Save budget</button></div><div className="admin-usage-preview"><span>Safety controls</span><div className="admin-usage-bar"><i style={{ width: '100%' }} /></div><small>Human confirmation: required · Conversation consent: required</small><div className="mt-2"><strong>{management?.granted_permissions ?? '—'}</strong> active permissions · <strong>{management?.revoked_permissions ?? '—'}</strong> revoked</div></div></div></section>
    <section className="admin-card"><div className="admin-card-head"><div><h2>System health</h2><p>Backend and dependency checks</p></div><StatusBadge value={health?.overall_status || 'Unknown'} /></div>{(health?.components || []).map(component => <div className="admin-health-row" key={component.key}><span><strong>{component.label}</strong><small>{component.detail}</small></span><StatusBadge value={component.status} /></div>)}</section>
  </div>
}

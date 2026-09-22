import { useEffect, useState } from 'react'
import { AdminPageHeader, EmptyState, StatusBadge } from '../../components/AdminCommon'
import { listAuditLog } from '../../api/admin'
import { useAuth } from '../../context/AuthContext'

const label = value => value?.replace(/[._]/g, ' ').replace(/\b\w/g, letter => letter.toUpperCase()) || '—'

export default function AdminAuditLogPage() {
  const { token } = useAuth()
  const [query, setQuery] = useState('')
  const [actorType, setActorType] = useState('')
  const [result, setResult] = useState({ total: 0, items: [] })
  const [error, setError] = useState('')
  const load = () => { setError(''); listAuditLog(token, { q: query.trim(), actorType }).then(setResult).catch(err => setError(err.detail || 'Could not load audit events.')) }
  useEffect(() => { load() }, [token, actorType])

  return <div className="admin-page">
    <AdminPageHeader title="Audit log" description="Review administrative changes without exposing raw messages or private memory content." />
    <div className="admin-audit-notice"><i className="bi bi-shield-check" /><div><strong>Sanitized audit records</strong><span>Tokens, passwords, prompts, and raw private content are never returned here.</span></div></div>
    {error && <div className="admin-warning-banner"><i className="bi bi-exclamation-triangle" /><div><strong>Audit data unavailable</strong><span>{error}</span></div></div>}
    <section className="admin-card admin-table-card">
      <form className="admin-table-toolbar" onSubmit={event => { event.preventDefault(); load() }}><div className="admin-filter-search"><i className="bi bi-search" /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search action, target, or actor..." /></div><div className="admin-filter-actions"><select value={actorType} onChange={event => setActorType(event.target.value)}><option value="">All actors</option><option value="platform_admin">Platform admin</option><option value="user">User</option><option value="system">System</option></select><button className="admin-primary-button">Search</button></div></form>
      <div className="admin-table-scroll"><table className="admin-table admin-audit-table"><thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Target</th><th>Workspace</th><th>Metadata</th><th>Status</th></tr></thead><tbody>{result.items.map(item => <tr key={item.id}><td><strong className="admin-date-cell">{new Date(item.created_at).toLocaleTimeString()}</strong><small>{new Date(item.created_at).toLocaleDateString()}</small></td><td><strong>{item.actor_display_name || label(item.actor_type)}</strong><small>{item.actor_email || 'System process'}</small></td><td><div className="admin-action-cell"><span><i className="bi bi-shield-check" /></span><strong>{label(item.action)}</strong></div></td><td>{label(item.target_type)}<small>{item.target_id || '—'}</small></td><td><code>{item.workspace_id || '—'}</code></td><td><code>{Object.keys(item.metadata || {}).length ? JSON.stringify(item.metadata) : '—'}</code></td><td><StatusBadge value="Recorded" /></td></tr>)}</tbody></table>{!result.items.length && <EmptyState text="No audit events found" />}</div>
    </section>
  </div>
}

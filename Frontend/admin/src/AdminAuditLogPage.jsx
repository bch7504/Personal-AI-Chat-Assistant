import { useEffect, useState } from 'react'
import PageHeader from '../../src/components/common/PageHeader'
import { listAuditLog } from '../../src/api/admin'
import { useAuth } from '../../src/context/AuthContext'

const humanize = value => value?.replace(/[._]/g, ' ').replace(/\b\w/g, letter => letter.toUpperCase()) || '—'

export default function AdminAuditLogPage() {
  const { token } = useAuth()
  const [query, setQuery] = useState('')
  const [actorType, setActorType] = useState('user')
  const [result, setResult] = useState({ total: 0, items: [] })
  const [error, setError] = useState('')
  const load = () => { setError(''); listAuditLog(token, { q: query.trim(), actorType }).then(setResult).catch(err => setError(err.detail || 'Could not load audit log.')) }
  useEffect(() => { load() }, [token, actorType])

  return <div className="page-container admin-dashboard-page">
    <PageHeader eyebrow="Platform admin" title="Audit Log" description="Review user activity without exposing raw conversation or memory content." />
    {error && <div className="admin-monitor-error"><i className="bi bi-exclamation-triangle" />{error}</div>}
    <section className="content-card admin-audit-card"><form className="admin-audit-toolbar" onSubmit={event => { event.preventDefault(); load() }}><div className="mini-search"><i className="bi bi-search" /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search action, target, or actor email" /></div><select className="form-select" value={actorType} onChange={event => setActorType(event.target.value)}><option value="">All actors</option><option value="platform_admin">Platform admin</option><option value="user">User</option><option value="system">System</option></select><button className="btn btn-primary">Search</button><span>{result.total.toLocaleString()} events</span></form><div className="table-responsive"><table className="table admin-audit-table"><thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Target</th><th>Metadata</th></tr></thead><tbody>{result.items.map(item => <tr key={item.id}><td><strong>{new Date(item.created_at).toLocaleDateString()}</strong><small>{new Date(item.created_at).toLocaleTimeString()}</small></td><td><strong>{item.actor_display_name || humanize(item.actor_type)}</strong><small>{item.actor_email || item.actor_type}</small></td><td><span className="soft-badge info">{humanize(item.action)}</span></td><td><strong>{humanize(item.target_type)}</strong><small title={item.target_id || ''}>{item.target_id || '—'}</small></td><td><code>{Object.keys(item.metadata).length ? JSON.stringify(item.metadata) : '—'}</code></td></tr>)}{!result.items.length && <tr><td colSpan="5" className="text-center text-muted py-4">No user activity has been recorded yet. New actions will appear here.</td></tr>}</tbody></table></div></section>
  </div>
}

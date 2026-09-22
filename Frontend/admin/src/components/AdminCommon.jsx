export function AdminPageHeader({ title, description, action }) {
  return <div className="admin-page-header"><div><h1>{title}</h1><p>{description}</p></div>{action}</div>
}

export function MetricCard({ item }) {
  return <article className="admin-metric-card"><div className={`admin-metric-icon ${item.tone}`}><i className={`bi ${item.icon}`} /></div><div className="admin-metric-copy"><span>{item.label}</span><strong>{item.value}</strong>{item.note && <small className={item.trend || 'up'}>{item.note}</small>}</div></article>
}

export function UserCell({ user }) {
  return <div className="admin-user-cell"><span className="admin-table-avatar" style={{ background: user.color || '#596ff0' }}>{user.initials}</span><div><strong>{user.name}</strong><small>{user.email}</small></div></div>
}

export function StatusBadge({ value }) {
  const label = String(value || 'Unknown')
  const slug = label.toLowerCase().replace(/\s+/g, '-')
  return <span className={`admin-status ${slug}`}><i />{label}</span>
}

export function EmptyState({ text = 'No results found' }) {
  return <div className="admin-empty"><i className="bi bi-search" /><strong>{text}</strong><span>Try changing your search or filter.</span></div>
}

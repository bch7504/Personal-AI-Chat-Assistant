export default function StatCard({ label, value, icon, color = 'primary', note }) {
  return <div className="stat-card"><div className={`stat-icon bg-${color}-subtle text-${color}`}><i className={`bi ${icon}`} /></div><div><div className="stat-value">{value}</div><div className="stat-label">{label}</div></div>{note && <span className="stat-note">{note}</span>}</div>
}

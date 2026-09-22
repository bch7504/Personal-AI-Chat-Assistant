import { motion } from 'framer-motion'

export default function StatCard({ label, value, icon, color = 'primary', note }) {
  return (
    <motion.div whileHover={{ y: -3 }} className="stat-card">
      <div className={`stat-icon bg-${color}-subtle text-${color}`}><i className={`bi ${icon}`} /></div>
      <div><div className="stat-value">{value}</div><div className="stat-label">{label}</div></div>
      {note && <span className="stat-note">{note}</span>}
    </motion.div>
  )
}

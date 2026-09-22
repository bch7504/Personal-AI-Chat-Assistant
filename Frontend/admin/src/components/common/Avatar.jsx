export default function Avatar({ initials, color = '#526ff5', size = 42 }) {
  return <span className="avatar flex-shrink-0" style={{ width: size, height: size, background: color, fontSize: size * .32 }}>{initials}</span>
}

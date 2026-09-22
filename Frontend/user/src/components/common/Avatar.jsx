export default function Avatar({ initials, color = '#526ff5', size = 42, status = false }) {
  return (
    <span className="avatar flex-shrink-0" style={{ width: size, height: size, background: color, fontSize: size * .32 }}>
      {initials}{status && <i className="avatar-status" />}
    </span>
  )
}

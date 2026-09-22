import { useEffect } from 'react'

export default function ReminderToast({ reminder, onClose }) {
  useEffect(() => {
    const timer = setTimeout(onClose, 8000)
    return () => clearTimeout(timer)
  }, [reminder, onClose])

  return (
    <div className="reminder-toast" role="alert" style={{ position: 'fixed', bottom: 24, right: 24, zIndex: 1080, maxWidth: 320 }}>
      <div className="border rounded-3 p-3 bg-body shadow-lg d-flex align-items-start gap-2">
        <i className="bi bi-alarm text-primary fs-5" />
        <div className="flex-grow-1">
          <strong className="d-block">{reminder.title}</strong>
          {reminder.message && <small className="text-muted d-block">{reminder.message}</small>}
        </div>
        <button className="btn-close" aria-label="Close" onClick={onClose} />
      </div>
    </div>
  )
}

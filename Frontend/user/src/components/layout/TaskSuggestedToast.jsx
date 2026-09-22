import { useEffect } from 'react'
import { Link } from 'react-router-dom'

export default function TaskSuggestedToast({ task, onClose }) {
  useEffect(() => {
    const timer = setTimeout(onClose, 8000)
    return () => clearTimeout(timer)
  }, [task, onClose])

  return (
    <div className="task-suggested-toast" role="alert" style={{ position: 'fixed', bottom: 24, right: 24, zIndex: 1080, maxWidth: 320 }}>
      <div className="border rounded-3 p-3 bg-body shadow-lg d-flex align-items-start gap-2">
        <i className="bi bi-stars text-primary fs-5" />
        <div className="flex-grow-1">
          <strong className="d-block">Orbit spotted a commitment</strong>
          <small className="text-muted d-block">{task.title}</small>
          <Link to="/tasks" className="small" onClick={onClose}>Review in Tasks</Link>
        </div>
        <button className="btn-close" aria-label="Close" onClick={onClose} />
      </div>
    </div>
  )
}

import { useEffect, useRef } from 'react'

export default function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'Xoá',
  cancelLabel = 'Huỷ',
  danger = true,
  busy = false,
  onConfirm,
  onCancel,
}) {
  const confirmRef = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const frame = requestAnimationFrame(() => confirmRef.current?.focus())
    const onKeyDown = event => {
      if (event.key === 'Escape' && !busy) onCancel()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => {
      cancelAnimationFrame(frame)
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [busy, onCancel, open])

  if (!open) return null
  return (
    <div className="modal show d-block orbit-confirm-backdrop" tabIndex="-1" role="presentation" onMouseDown={busy ? undefined : onCancel}>
      <div className="modal-dialog modal-dialog-centered orbit-confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="orbit-confirm-title" aria-describedby="orbit-confirm-message" onMouseDown={event => event.stopPropagation()}>
        <div className="modal-content">
          <div className="modal-header"><h5 className="modal-title" id="orbit-confirm-title">{title}</h5><button type="button" className="btn-close" aria-label="Đóng" disabled={busy} onClick={onCancel} /></div>
          <div className="modal-body"><div className={`orbit-confirm-icon ${danger ? 'danger' : ''}`}><i className={`bi ${danger ? 'bi-trash3' : 'bi-question-lg'}`} /></div><p className="mb-0" id="orbit-confirm-message">{message}</p></div>
          <div className="modal-footer">
            <button type="button" className="btn btn-light" disabled={busy} onClick={onCancel}>{cancelLabel}</button>
            <button ref={confirmRef} type="button" className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`} disabled={busy} onClick={onConfirm}>{busy && <span className="spinner-border spinner-border-sm me-2" aria-hidden="true"/>}{confirmLabel}</button>
          </div>
        </div>
      </div>
    </div>
  )
}
